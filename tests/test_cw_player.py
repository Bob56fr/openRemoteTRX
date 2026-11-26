# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lot CW-0 : banc de l'ordonnanceur (gigue, pertes, réordonnancement, coupures, bail, appui trop long).

Critères d'adoption du cahier § 11 vérifiés ici : écart de timing ≤ 2 ms au p95 avec rejeu 300 ms et gigue
jusqu'à 150 ms, aucun élément tronqué hors coupure de bail, coupure ≤ lease_grace_ms + 20 ms en temps de rejeu.
"""
from __future__ import annotations

import numpy as np
import pytest

from trxstation.cw import analysis as an
from trxstation.cw import sim
from trxstation.cw.player import CwParams, CwPlayer
from trxstation.cw.protocol import parse_packet

FS = 48000
TEXT = "CQ CQ DE F4XYZ F4XYZ K"


def _seq(text: str = TEXT, wpm: float = 20, start_ms: float = 1000.0, seq: int = 0) -> sim.Sequence:
    return sim.Sequence(seq, start_ms, sim.morse_timeline(text, wpm))


def _audio_ms(r: sim.SimResult, sample: float) -> float:
    return sample * 1000.0 / r.fs


def _report(r: sim.SimResult, sq: sim.Sequence) -> an.TimingReport:
    found = an.detect_edges(r.audio, FS, 700, 0.5)
    return an.compare(sq.edges, found, FS)


# --- critères du cahier -----------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("jitter", [0, 50, 100, 150])
@pytest.mark.parametrize("loss", [0.0, 0.05, 0.10])
def test_timing_within_2_ms_with_300_ms_replay(seed, jitter, loss):
    sq = _seq()
    r = sim.run([sq], sim.Network(jitter_ms=jitter, loss=loss, seed=seed))
    rep = _report(r, sq)
    assert rep.complete, "élément tronqué ou perdu"
    assert rep.p95_ms <= 2.0 and rep.max_ms <= 2.0
    assert max(abs(m) for m in rep.mark_errors_ms) <= 2.0
    assert r.player.late == 0 and r.player.lease_cuts == 0
    assert [e["reason"] for e in r.events] == ["end"]


@pytest.mark.parametrize("wpm", [5, 12, 30, 40])
def test_all_speeds_of_the_specification(wpm):
    sq = _seq("PARIS PARIS", wpm)
    r = sim.run([sq], sim.Network(jitter_ms=150, loss=0.05, seed=7))
    rep = _report(r, sq)
    assert rep.complete and rep.p95_ms <= 2.0


def test_the_station_never_decides_by_timer_only_by_sample():
    sq = _seq("EEEEE")
    r = sim.run([sq], sim.Network())
    assert r.player.max_timing_err_ms <= 1000.0 / FS


def test_duplicates_from_the_window_change_nothing():
    sq = _seq("TEST")
    r = sim.run([sq], sim.Network())
    assert r.player.duplicates > 0
    assert len([e for e in r.player.played if e.reason == ""]) == len(sq.edges)


def test_reordered_packets_are_played_in_order():
    sq = _seq("SOS")
    r = sim.run([sq], sim.Network(jitter_ms=120, seed=11))
    assert any(a[1]["lease"] > b[1]["lease"] for a, b in zip(r.arrivals, r.arrivals[1:])), "pas de désordre"
    samples = [e.sample for e in r.player.played]
    assert samples == sorted(samples)
    assert _report(r, sq).complete


# --- bail -------------------------------------------------------------------------------------------------------
def test_link_cut_during_a_dash_stops_the_tone_within_the_lease_grace():
    sq = sim.Sequence(0, 1000.0, [(0.0, True), (1500.0, False)])     # trait de 1,5 s
    cut_from = 1000.0 + 600.0
    params = CwParams()
    r = sim.run([sq], sim.Network(cuts=[(cut_from, 9999.0)]), params)
    p = r.player
    assert [(e["type"], e["reason"]) for e in r.events] == [("cw_fault", "lease_expired"),
                                                             ("seq_end", "lease_expired")]
    assert p.lease_cuts == 1
    cut = next(e for e in p.played if e.reason == "lease_expired")
    last_lease = max(m["lease"] for t, m in r.arrivals)
    replay_lag_ms = _audio_ms(r, cut.sample) - (_audio_ms(r, p.anchor) + last_lease)
    assert replay_lag_ms <= params.lease_grace_ms + 1e-6
    # fin du son (front adouci compris) ≤ marge du bail + 20 ms
    env = an.envelope(r.audio)
    tail = np.nonzero(env > 0.005)[0][-1]
    assert _audio_ms(r, tail) - (_audio_ms(r, p.anchor) + last_lease) <= params.lease_grace_ms + 20
    # en temps réel : au plus rejeu + marge (+ transit) après le dernier paquet reçu
    last_arrival = max(t for t, m in r.arrivals)
    assert _audio_ms(r, cut.sample) - last_arrival <= params.delay_ms + params.lease_grace_ms + 1


def test_after_a_lease_cut_the_same_sequence_stays_silent_and_the_next_one_plays():
    first = sim.Sequence(0, 1000.0, [(0.0, True), (1200.0, False)])
    second = sim.Sequence(1, 5000.0, sim.morse_timeline("K"))
    r = sim.run([first, second], sim.Network(cuts=[(1400.0, 3000.0)], hold=True))
    reasons = [e["reason"] for e in r.events]
    assert reasons == ["lease_expired", "lease_expired", "end"]   # cw_fault puis seq_end, puis la seconde
    assert r.player.ignored > 0                                    # rafale de la 1re séquence ignorée
    keyed = [e for e in r.player.played if e.seq == 1 and e.reason == ""]
    assert len(keyed) == len(second.edges)


def test_held_burst_never_brings_the_tone_back():
    sq = sim.Sequence(0, 1000.0, [(0.0, True), (800.0, False)])
    r = sim.run([sq], sim.Network(cuts=[(1300.0, 1700.0)], hold=True))
    cut = next(e for e in r.player.played if e.reason == "lease_expired")
    env = an.envelope(r.audio)
    assert not (env[cut.sample + 480:] > 0.005).any()


def test_a_lost_closing_edge_is_repeated_before_the_lease_expires():
    sq = _seq("EEEE TTTT")
    r = sim.run([sq], sim.Network(loss=0.3, seed=5))
    assert r.player.lease_cuts == 0 and _report(r, sq).complete


# --- appui trop long, STOP ---------------------------------------------------------------------------------------
def test_keydown_longer_than_the_limit_is_cut():
    sq = sim.Sequence(0, 1000.0, [(0.0, True), (3000.0, False)])
    r = sim.run([sq], sim.Network())
    assert [e["reason"] for e in r.events] == ["keydown_too_long", "keydown_too_long"]
    down = next(e for e in r.player.played if e.down)
    cut = next(e for e in r.player.played if e.reason == "keydown_too_long")
    assert _audio_ms(r, cut.sample - down.sample) == pytest.approx(2000.0, abs=0.1)


def test_stop_cuts_at_once():
    sq = sim.Sequence(0, 1000.0, [(0.0, True), (1400.0, False)])
    r = sim.run([sq], sim.Network(), stop_at_ms=1700.0)
    cut = next(e for e in r.player.played if e.reason == "stop")
    assert _audio_ms(r, cut.sample) == pytest.approx(1700.0, abs=20.1)
    assert r.player.silent
    env = an.envelope(r.audio)
    assert not (env[cut.sample + 300:] > 0.005).any()


def test_stop_when_idle_is_harmless():
    p = CwPlayer()
    p.stop()
    assert p.silent and p.render(960).size == 960 and not p.render(960).any()


# --- ré-ancrage, séquences, rejeu adaptatif ----------------------------------------------------------------------
def test_late_closing_edge_reanchors_and_keeps_the_elements_intact():
    # liaison figée 450 ms pendant un silence, paquets livrés en rafale : la fermeture suivante arrive en retard
    sq = sim.Sequence(0, 1000.0, [(0.0, True), (100.0, False), (1000.0, True), (1100.0, False)])
    r = sim.run([sq], sim.Network(cuts=[(1950.0, 2400.0)], hold=True))
    assert r.player.late == 1 and r.player.lease_cuts == 0
    found = an.detect_edges(r.audio, FS, 700, 0.5)
    rep = an.compare(sq.edges, found, FS)
    assert rep.complete
    assert max(abs(m) for m in rep.mark_errors_ms) <= 0.1          # éléments intacts
    assert 90.0 <= rep.errors_ms[2] <= 120.0                         # la suite est décalée d'autant
    assert rep.errors_ms[3] == pytest.approx(rep.errors_ms[2], abs=0.1)


def test_two_sequences_are_anchored_separately():
    a = _seq("CQ", seq=0, start_ms=1000.0)
    b = _seq("K", seq=1, start_ms=1000.0 + a.edges[-1][0] + 3000.0)
    r = sim.run([a, b], sim.Network(jitter_ms=80, seed=2))
    assert [e["reason"] for e in r.events] == ["end", "end"]
    found = an.detect_edges(r.audio, FS, 700, 0.5)
    assert an.compare(a.edges, found[:len(a.edges)], FS).p95_ms <= 2.0
    assert an.compare(b.edges, found[len(a.edges):], FS).p95_ms <= 2.0


def test_adaptive_replay_follows_the_jitter_between_sequences_only():
    seqs = [_seq("TEST", seq=i, start_ms=1000.0 + i * 6000.0) for i in range(3)]
    params = CwParams(adaptive=True, delay_ms=300.0)
    r = sim.run(seqs, sim.Network(jitter_ms=100.0, seed=9), params)
    ends = [e for e in r.events if e["type"] == "seq_end"]
    assert ends[0]["delay_ms"] == 300.0                     # aucune mesure encore : valeur de départ
    assert 150.0 <= ends[1]["delay_ms"] <= 160.0            # p95 (~95 ms) + 50, borné à 150 au moins
    assert all(e["reason"] == "end" for e in ends)


def test_adaptive_replay_stays_within_bounds():
    seqs = [_seq("E", seq=i, start_ms=1000.0 + i * 4000.0) for i in range(3)]
    params = CwParams(adaptive=True, delay_ms=300.0, delay_max_ms=400.0)
    r = sim.run(seqs, sim.Network(jitter_ms=700.0, seed=1), params)
    assert max(e["delay_ms"] for e in r.events if e["type"] == "seq_end") == 400.0


def test_a_new_sequence_while_the_previous_plays_is_a_fault():
    p = CwPlayer()
    p.receive(parse_packet({"type": "cw", "seq": 0, "edges": [[1, 1, 0]], "lease": 0}), 0.0)
    p.render(15000)                              # 312 ms : clé fermée depuis 300 ms, bail encore valable
    assert p.key_down
    p.receive(parse_packet({"type": "cw", "seq": 1, "edges": [[2, 1, 0]], "lease": 0}), 1.0)
    assert [(e["type"], e["reason"]) for e in p.drain_events()] == [("cw_fault", "seq_overlap"),
                                                                     ("seq_end", "seq_overlap")]
    assert p.seq == 1 and p.active


def test_stale_and_edgeless_packets_are_ignored():
    p = CwPlayer()
    p.receive(parse_packet({"type": "cw", "seq": 5, "edges": [], "lease": 10}), 0.0)
    assert not p.active and p.ignored == 1
    p.receive(parse_packet({"type": "cw", "seq": 5, "edges": [[1, 0, 0]], "lease": 10}), 0.0)
    assert not p.active and p.ignored == 2           # une séquence ne commence pas par une ouverture


def test_render_always_returns_the_requested_length():
    sq = _seq("EISH")
    p = CwPlayer()
    for t, m in sim.Network(jitter_ms=50).deliver(sim.client_packets([sq])):
        p.receive(parse_packet(m), t / 1000.0)
    for n in (1, 7, 960, 4801):
        assert p.render(n).size == n


@pytest.mark.parametrize("kw", [{"delay_ms": 100}, {"delay_ms": 600}, {"delay_min_ms": 400, "delay_max_ms": 300},
                                {"lease_grace_ms": 10}, {"max_keydown_ms": 6000}, {"seq_gap_ms": 100}])
def test_parameter_bounds(kw):
    with pytest.raises(ValueError):
        CwPlayer(CwParams(**kw))


# --- gels de liaison façon 4G -----------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_stalls_shorter_than_the_replay_cost_nothing(seed):
    sq = _seq()
    r = sim.run([sq], sim.Network(jitter_ms=50, loss=0.02, stalls_per_min=20, stall_max_ms=200, seed=seed))
    rep = _report(r, sq)
    assert rep.complete and rep.p95_ms <= 2.0 and r.player.lease_cuts == 0


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_long_stalls_end_in_a_clean_lease_cut_never_in_a_stuck_tone(seed):
    sq = sim.Sequence(0, 1000.0, [(0.0, True), (1800.0, False)])
    r = sim.run([sq], sim.Network(stalls_per_min=60, stall_max_ms=1500, seed=seed))
    cuts = [e for e in r.player.played if e.reason == "lease_expired"]
    env = an.envelope(r.audio)
    if cuts:
        assert not (env[cuts[0].sample + 300:] > 0.005).any()
    else:
        assert _report(r, sq).complete


def test_bench_cell_runs():
    from trxstation.devtools import cw_bench
    assert cw_bench.cell(50, 0.05, CwParams(), 20, 1).startswith(" 0.00/")


def test_a_new_sequence_after_the_client_gap_ends_the_previous_one_normally():
    # le client compte le silence à son heure : sa nouvelle séquence arrive AVANT que le rejeu (retardé) ait vu la fin
    gap = 1500.0
    a = sim.Sequence(0, 1000.0, sim.morse_timeline("E"), tail_ms=gap)
    b = sim.Sequence(1, 1000.0 + a.edges[-1][0] + gap + 1.0, sim.morse_timeline("T"))
    r = sim.run([a, b], sim.Network(base_ms=30))
    assert [(e["type"], e["reason"]) for e in r.events] == [("seq_end", "end"), ("seq_end", "end")]
    assert r.player.lease_cuts == 0 and len([e for e in r.player.played if e.reason == ""]) == 4


def test_hold_plays_nothing_and_resume_plays_the_waiting_element_whole():
    """V2 (cahier § 5.4) : PTT relâché = aucun front joué ; à la reprise, le point en attente sort entier."""
    p = CwPlayer(CwParams(delay_ms=200))
    p.receive(parse_packet({"type": "cw", "seq": 0, "edges": [[1, 1, 0], [2, 0, 60]], "lease": 60}), 0.0)
    out = p.render(48000)                                    # premier point, puis silence
    assert p.idle_ms > 500 and not p.wants_key
    p.hold()
    p.receive(parse_packet({"type": "cw", "seq": 0, "edges": [[3, 1, 1000], [4, 0, 1060]], "lease": 1060}), 0.95)
    held = p.render(48000)
    assert np.max(np.abs(held)) == 0.0 and p.wants_key      # rien ne joue pendant la pause
    p.resume()
    after = p.render(9600)
    found = an.detect_edges(np.concatenate([out, held, after]), 48000, 700, p.p.level)
    marks = [(found[i + 1][0] - found[i][0]) / 48 for i in range(0, len(found) - 1, 2)]
    assert len(marks) == 2 and all(abs(m - 60.0) < 0.5 for m in marks)
    assert p.hang_reanchors == 1 and p.late == 0             # décalage de la reprise : pas un retard du réseau
