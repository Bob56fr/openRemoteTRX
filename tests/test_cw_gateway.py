# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lot CW-1 (étape 413) : manipulation CW, mode A, dans la passerelle, avec le poste factice (modèle Hamlib 1).

Tests de panne exigés par les règles d'émission (CLAUDE.md) et le cahier § 3 : bail dépassé, connexion fermée,
battement perdu, STOP d'un autre client, TOT, passerelle gênée (rendu en retard), QSY refusé pendant l'armement,
porteuse hors bande, mode du poste, réglages changés pendant l'armement, inactivité, appui trop long.
"""
from __future__ import annotations

import asyncio
import json
import time

import numpy as np
import pytest

from trxstation.cw import analysis as an
from trxstation.cw import sim
from trxstation.gateway.api.access import LISTENER
from trxstation.gateway.audio.devices import RecordingSink
from trxstation.gateway.audio.pcm import FRAME_S
from trxstation.gateway.cw import LEAD_S, CwKeyer
from trxstation.gateway.safety import PttLimits

from test_api import connect, run, station, until

FS = 48000


class Bench:
    def __init__(self, st, keyer, sink):
        self.st, self.keyer, self.sink = st, keyer, sink

    def audio(self) -> np.ndarray:
        pcm = b"".join(self.sink.frames)
        return np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32767.0


def bench(st, tmp_path, *, clock=time.monotonic, **cw) -> Bench:
    cfg = st.ctrl.config
    cfg.cw.enabled = True
    cw.setdefault("ptt_variant", "hold")                 # V1 par défaut dans ce banc ; la station est en V2 par défaut
    for key, value in cw.items():
        setattr(cfg.cw, key, value)
    sink = RecordingSink()
    keyer = CwKeyer(st.ctrl, sink, cfg, state_dir=tmp_path, clock=clock)
    return Bench(st, keyer, sink)


async def heartbeats(client, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await client.say(cmd="heartbeat")
        await asyncio.sleep(0.25)


async def send_packets(keyer, client_id: str, sequences, *, until_ms: float | None = None) -> None:
    """Rejoue les paquets du client (cahier § 5.1) en temps réel ; `until_ms` : liaison coupée à partir de là."""
    sent = sim.client_packets(sequences)
    t0 = time.monotonic() * 1000 - sequences[0].start_ms
    for item in sent:
        if until_ms is not None and item.send_ms >= until_ms:
            return
        wait = (t0 + item.send_ms) / 1000 - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        keyer.receive(client_id, json.dumps(item.msg))


def prepare(fake, freq=7_030_000, mode="PKTUSB"):
    fake.freq, fake.mode = freq, mode


async def unkeyed(st, fake, timeout=3.0):
    """Retour en réception CONFIRMÉ (motif de la coupure écrit) et poste relu en réception."""
    await until(lambda: fake.ptt == 0 and st.ctrl.snapshot().state == "RX" and st.ctrl.snapshot().last_cut_reason,
                timeout=timeout)


async def armed(st, b, phone, ident=1, **params):
    await phone.say(cmd="cw_arm", id=ident, **params)
    return phone.result(ident)


# --------------------------------------------------------------------------- annonce et refus (rien n'émet)
def test_v2_is_the_default_variant():
    from trxstation.config import Cw
    assert Cw().ptt_variant == "hang"


def test_cw_is_announced_only_when_enabled(tmp_path):
    async def scenario(fake):
        async with station(fake) as st:
            b = bench(st, tmp_path)
            st.ctrl.config.cw.enabled = False
            off = await connect(st, "off", cw=b.keyer)
            assert "cw" not in off.of_type("hello")[0]["features"]
            assert off.of_type("hello")[0]["cw"] is None
            await off.say(cmd="cw_arm", id=1)
            assert off.result(1)["reason"] == "cw_unavailable" and fake.ptt == 0
            st.ctrl.config.cw.enabled = True
            on = await connect(st, "on", cw=b.keyer)
            assert "cw" in on.of_type("hello")[0]["features"]
            # mode exigé annoncé : la page CW propose d'y mettre le poste (commande de mode de l'opérateur)
            assert on.of_type("hello")[0]["cw"] == {"mode": "PKTUSB", "variant": "hold"}
            listener = await connect(st, "visiteur", cw=b.keyer, role=LISTENER)
            assert "cw" not in listener.of_type("hello")[0]["features"]
            assert listener.of_type("hello")[0]["cw"] is None
    run(scenario)


def test_wrong_mode_is_refused_and_the_station_never_changes_it(tmp_path):
    async def scenario(fake):
        prepare(fake, mode="USB")
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone = await connect(st, "phone", cw=b.keyer)
            r = await armed(st, b, phone)
            assert not r["ok"] and r["reason"] == "cw_mode" and fake.mode == "USB" and fake.ptt == 0
    run(scenario)


@pytest.mark.parametrize("freq,mode", [(7_199_500, "PKTUSB"), (7_000_300, "PKTLSB")])
def test_carrier_out_of_band_is_refused(tmp_path, freq, mode):
    async def scenario(fake):
        prepare(fake, freq, mode)
        async with station(fake) as st:
            b = bench(st, tmp_path, data_mode=mode)
            phone = await connect(st, "phone", cw=b.keyer)
            r = await armed(st, b, phone)
            assert not r["ok"] and r["reason"] == "out_of_band" and "porteuse" in r["detail"] and fake.ptt == 0
            assert not b.keyer.armed and b.sink.frames == []
    run(scenario)


def test_carrier_changed_between_the_check_and_the_keying_is_cut(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            real = st.ctrl.read_transmit_plan

            async def stale_plan():
                freq, tx, plan = await real()
                return freq - 1000, tx - 1000, plan          # lu avant un QSY fait à la main entre-temps
            st.ctrl.read_transmit_plan = stale_plan
            phone = await connect(st, "phone", cw=b.keyer)
            r = await armed(st, b, phone)
            assert not r["ok"] and r["reason"] == "cw_carrier_changed"
            await until(lambda: fake.ptt == 0 and st.ctrl.snapshot().state == "RX")
            assert not b.keyer.armed and b.sink.frames == []
    run(scenario)


# --------------------------------------------------------------------------- armement, tonalité, désarmement
def test_arming_keys_with_the_mic_closed_plays_the_keying_exactly_and_disarms(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            r = await armed(st, b, phone, wpm=20, delay_ms=200)
            assert r["ok"] and r["cw"]["carrier_hz"] == 7_030_700 and fake.ptt == 1
            assert not st.pipeline.gate.is_open                         # micro : jamais pendant la CW
            assert not st.pipeline.gate.push("phone", bytes(1920))
            sq = sim.Sequence(0, 0.0, sim.morse_timeline("TEST", 20), tail_ms=400)
            await send_packets(b.keyer, "phone", [sq])
            await asyncio.sleep(0.6)
            await phone.say(cmd="cw_disarm", id=2)
            assert phone.result(2)["ok"] and fake.ptt == 0 and not b.keyer.armed
            stop.set()
            await beat
            rep = an.compare(sq.edges, an.detect_edges(b.audio(), FS, 700, 0.5), FS)
            assert rep.complete and rep.p95_ms <= 2.0
            assert {"type": "cw_state", "state": "idle", "reason": "cw_disarm"} in phone.messages
            assert st.ctrl.snapshot().last_cut_reason == "cw_disarm"
    run(scenario)


def test_owner_toggle_disarms_and_align_puts_the_carrier_on_the_dial(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone = await connect(st, "phone", cw=b.keyer)
            r = await armed(st, b, phone, align=True)
            assert r["ok"] and fake.freq == 7_029_300 and r["cw"]["carrier_hz"] == 7_030_000
            await phone.say(cmd="toggle", id=2)
            assert fake.ptt == 0 and not b.keyer.armed
    run(scenario)


def test_the_station_never_writes_more_than_its_lead_ahead(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone)
            start = time.monotonic()
            await asyncio.sleep(1.0)
            elapsed = time.monotonic() - start
            assert len(b.sink.frames) <= (elapsed + LEAD_S) / FRAME_S + 3   # passerelle gelée : au plus ~80 ms de son
            await phone.say(cmd="cw_disarm", id=2)
            stop.set()
            await beat
    run(scenario)


# --------------------------------------------------------------------------- pannes et coupures
def test_lease_expired_during_a_dash_closes_softly_then_unkeys(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone, delay_ms=200)
            sq = sim.Sequence(0, 0.0, [(0.0, True), (1500.0, False)], tail_ms=200)
            await send_packets(b.keyer, "phone", [sq], until_ms=500)       # liaison coupée au milieu du trait
            await unkeyed(st, fake, 3.0)
            stop.set()
            await beat
            assert any(m.get("type") == "cw_fault" and m["reason"] == "lease_expired" for m in phone.messages)
            assert st.ctrl.snapshot().last_cut_reason == "cw_lease_expired" and not b.keyer.armed
            env = an.envelope(b.audio())
            on = np.nonzero(env > 0.25)[0]
            # tonalité de ~ 480 ms couverte par le bail + marge, jamais au-delà de 60 ms + front
            assert (on[-1] - on[0]) / FS * 1000 <= 480 + 60 + 20
            assert np.max(np.abs(np.diff(b.audio()))) <= an.sine_step(0.5, 700, FS) * 1.05   # fermeture sans clic
    run(scenario)


def test_stop_from_another_client_cuts_the_tone_at_once(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone, car = await connect(st, "phone", cw=b.keyer), await connect(st, "car", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone)
            sender = asyncio.create_task(send_packets(b.keyer, "phone", [sim.Sequence(0, 0.0, [(0.0, True), (1800.0, False)])]))
            await asyncio.sleep(0.6)
            flushes = b.sink.flushes
            await car.say(cmd="stop", id=9)
            assert fake.ptt == 0 and not b.keyer.armed and b.sink.flushes > flushes   # tampon jeté : coupé net
            written = len(b.sink.frames)
            await asyncio.sleep(0.3)
            assert len(b.sink.frames) == written                    # plus rien n'est écrit
            assert {"type": "cw_state", "state": "idle", "reason": "stop"} in phone.messages
            await sender
            stop.set()
            await beat
            assert fake.ptt == 0
    run(scenario)


def test_connection_closed_unkeys_and_disarms(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone = await connect(st, "phone", cw=b.keyer)
            await armed(st, b, phone)
            await phone.session.close()
            await unkeyed(st, fake)
            assert not b.keyer.armed
    run(scenario)


def test_lost_heartbeat_unkeys_and_disarms(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone = await connect(st, "phone", cw=b.keyer)
            await armed(st, b, phone)                              # aucun battement ensuite (limite 1 s du banc)
            await unkeyed(st, fake, 3.0)
            assert not b.keyer.armed and st.ctrl.snapshot().last_cut_reason == "heartbeat"
    run(scenario)


def test_tot_still_applies_during_cw(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake, limits=PttLimits(tot_s=1.5, warn_before_s=0.5, heartbeat_timeout_s=1.0, tick_s=0.02,
                                                  rekey_cooldown_s=0, unkey_retry_s=0.05, unkey_deadline_s=0.5)) as st:
            b = bench(st, tmp_path, idle_disarm_s=20)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone)
            await unkeyed(st, fake, 3.0)
            stop.set()
            await beat
            assert not b.keyer.armed and st.ctrl.snapshot().last_cut_reason == "tot"
    run(scenario)


def test_idle_disarm_returns_to_receive(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path, idle_disarm_s=2)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone)
            await unkeyed(st, fake, 4.0)
            stop.set()
            await beat
            assert st.ctrl.snapshot().last_cut_reason == "cw_idle"
    run(scenario)


def test_key_held_too_long_is_cut(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path, max_keydown_ms=500)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone, delay_ms=150)
            await send_packets(b.keyer, "phone", [sim.Sequence(0, 0.0, [(0.0, True), (1500.0, False)])], until_ms=1200)
            await unkeyed(st, fake, 3.0)
            stop.set()
            await beat
            assert st.ctrl.snapshot().last_cut_reason == "cw_keydown_too_long"
            on = np.nonzero(an.envelope(b.audio()) > 0.25)[0]
            assert (on[-1] - on[0]) / FS * 1000 <= 500 + 10
    run(scenario)


def test_stalled_rendering_disarms(tmp_path):
    async def scenario(fake):
        prepare(fake)
        offset = [0.0]
        async with station(fake) as st:
            b = bench(st, tmp_path, clock=lambda: time.monotonic() + offset[0])
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone)
            await asyncio.sleep(0.2)
            offset[0] = 1.0                                         # la boucle a « dormi » une seconde
            await unkeyed(st, fake, 3.0)
            stop.set()
            await beat
            assert st.ctrl.snapshot().last_cut_reason == "cw_stalled" and not b.keyer.armed
    run(scenario)


def test_qsy_and_other_clients_are_refused_while_armed(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path)
            phone, car = await connect(st, "phone", cw=b.keyer), await connect(st, "car", cw=b.keyer)
            await armed(st, b, phone)
            await phone.say(cmd="set_frequency", id=2, hz=7_040_000)
            assert phone.result(2)["reason"] == "tx_active" and fake.freq == 7_030_000
            await car.say(cmd="cw_arm", id=3)
            assert car.result(3)["reason"] == "cw_busy"
            b.keyer.receive("car", json.dumps({"type": "cw", "seq": 0, "edges": [[1, 1, 0]], "lease": 0}))
            assert b.keyer.ignored_packets == 1 and not b.keyer.player.active   # paquets d'un autre client : ignorés
            b.keyer.receive("phone", "pas du json")
            b.keyer.receive("phone", json.dumps({"type": "cw", "seq": 0, "edges": [[1, 2, 0]], "lease": 0}))
            assert b.keyer.ignored_packets == 3
            await phone.say(cmd="cw_disarm", id=4)
            assert fake.ptt == 0
    run(scenario)


def test_sequence_statistics_are_recorded_without_any_sound_or_text(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path, seq_gap_ms=500)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone, delay_ms=150, interface="iambic_b", net="wifi")
            await send_packets(b.keyer, "phone", [sim.Sequence(0, 0.0, sim.morse_timeline("E", 20), tail_ms=900)])
            await until(lambda: phone.of_type("cw_stats"), timeout=3.0)
            await phone.say(cmd="cw_disarm", id=2)
            stop.set()
            await beat
            lines = (tmp_path / "cw" / "sequences.jsonl").read_text(encoding="utf-8").splitlines()
            entry = json.loads(lines[0])
            assert entry["interface"] == "iambic_b" and entry["net"] == "wifi" and entry["reason"] == "end"
            assert "edges" not in entry and "text" not in entry
    run(scenario)


# --------------------------------------------------------------------------- V2 (« hang », cahier § 5.4)
DIT_GAP_DIT = [(0.0, True), (60.0, False), (1000.0, True), (1060.0, False)]   # même séquence, 940 ms de silence


def test_v2_releases_after_the_silence_and_resumes_at_the_next_element(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path, ptt_variant="hang", hang_ms=400)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            r = await armed(st, b, phone, delay_ms=200)
            assert r["ok"] and fake.ptt == 1
            sender = asyncio.create_task(send_packets(b.keyer, "phone", [sim.Sequence(0, 0.0, DIT_GAP_DIT, tail_ms=300)]))
            await until(lambda: fake.ptt == 0 and st.ctrl.snapshot().last_cut_reason == "cw_hang", timeout=2.0)
            assert b.keyer.armed and st.ctrl.snapshot().state == "RX"         # relâché pendant le silence, CW armée
            assert any(m.get("type") == "cw_state" and m.get("state") == "hang" for m in phone.messages)
            written = len(b.sink.frames)
            await asyncio.sleep(0.15)
            assert len(b.sink.frames) == written                             # PTT relâché : rien vers le poste
            await until(lambda: fake.ptt == 1, timeout=2.0)                  # repris au point suivant
            await sender
            await asyncio.sleep(0.3)
            await phone.say(cmd="cw_disarm", id=2)
            stop.set()
            await beat
            assert fake.ptt == 0 and not b.keyer.armed and b.keyer.retakes == 1
            found = an.detect_edges(b.audio(), FS, 700, 0.5)
            marks = [(found[i + 1][0] - found[i][0]) * 1000 / FS for i in range(0, len(found) - 1, 2)]
            assert len(marks) == 2 and all(abs(m - 60.0) < 1.0 for m in marks)   # les deux points, entiers
    run(scenario)


def test_v2_stop_during_the_pause_disarms_for_good(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path, ptt_variant="hang", hang_ms=400)
            phone, car = await connect(st, "phone", cw=b.keyer), await connect(st, "car", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone, delay_ms=200)
            sender = asyncio.create_task(send_packets(b.keyer, "phone", [sim.Sequence(0, 0.0, DIT_GAP_DIT, tail_ms=300)]))
            await until(lambda: fake.ptt == 0 and b.keyer._phase == "hang", timeout=2.0)
            await car.say(cmd="stop", id=9)
            await until(lambda: not b.keyer.armed, timeout=1.0)
            await sender                                                     # le point suivant arrive : jamais repris
            await asyncio.sleep(0.4)
            stop.set()
            await beat
            assert fake.ptt == 0 and b.keyer.retakes == 0
            assert {"type": "cw_state", "state": "idle", "reason": "stop"} in phone.messages
    run(scenario)


def test_v2_resume_is_refused_when_the_rig_changed_during_the_pause(tmp_path):
    async def scenario(fake):
        prepare(fake)
        async with station(fake) as st:
            b = bench(st, tmp_path, ptt_variant="hang", hang_ms=400)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone, delay_ms=200)
            sender = asyncio.create_task(send_packets(b.keyer, "phone", [sim.Sequence(0, 0.0, DIT_GAP_DIT, tail_ms=300)]))
            await until(lambda: fake.ptt == 0 and b.keyer._phase == "hang", timeout=2.0)
            fake.mode = "USB"                                                # poste changé pendant la pause
            await until(lambda: not b.keyer.armed, timeout=2.0)
            await sender
            stop.set()
            await beat
            assert fake.ptt == 0 and b.keyer.retakes == 0
            assert any(m.get("type") == "cw_fault" and m["reason"] == "retake_refused" for m in phone.messages)
            assert {"type": "cw_state", "state": "idle", "reason": "cw_retake_refused"} in phone.messages
    run(scenario)


def test_v2_resume_waits_for_the_rekey_cooldown_and_never_lowers_it(tmp_path):
    async def scenario(fake):
        prepare(fake)
        limits = PttLimits(tot_s=5, warn_before_s=1, heartbeat_timeout_s=1.0, tick_s=0.02, rekey_cooldown_s=0.8,
                           unkey_retry_s=0.05, unkey_deadline_s=0.5)
        async with station(fake, limits=limits) as st:
            b = bench(st, tmp_path, ptt_variant="hang", hang_ms=300)
            phone = await connect(st, "phone", cw=b.keyer)
            stop = asyncio.Event()
            beat = asyncio.create_task(heartbeats(phone, stop))
            await armed(st, b, phone, delay_ms=200)
            edges = [(0.0, True), (60.0, False), (500.0, True), (560.0, False)]   # point 440 ms après : dans l'anti-rebond
            sender = asyncio.create_task(send_packets(b.keyer, "phone", [sim.Sequence(0, 0.0, edges, tail_ms=1500)]))
            await until(lambda: fake.ptt == 0, timeout=2.0)
            released = time.monotonic()
            await until(lambda: fake.ptt == 1, timeout=3.0)
            assert time.monotonic() - released >= 0.75                       # repris seulement après l'anti-rebond
            await sender
            await phone.say(cmd="cw_disarm", id=2)
            stop.set()
            await beat
            found = an.detect_edges(b.audio(), FS, 700, 0.5)
            marks = [(found[i + 1][0] - found[i][0]) * 1000 / FS for i in range(0, len(found) - 1, 2)]
            assert len(marks) == 2 and all(abs(m - 60.0) < 1.0 for m in marks)   # point retardé mais entier
            assert b.keyer.retakes == 1 and fake.ptt == 0
    run(scenario)


# --------------------------------------------------------------------------- configuration [cw]
def test_cw_section_is_off_by_default_and_checked():
    from trxstation import config as cfgmod
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    assert cfg.cw.enabled is False and cfgmod.validate(cfg) == []
    cfg.rig.tx_modes = ["USB"]
    assert cfgmod.validate(cfg) == []                       # défaut PKTUSB sans effet tant que la CW est désactivée
    cfg.cw.enabled = True
    assert any("data_mode" in p for p in cfgmod.validate(cfg))
    cfg.rig.tx_modes = ["PKTUSB"]
    assert cfgmod.validate(cfg) == []
    for key, value in (("max_keydown_ms", 6000), ("lease_grace_ms", 5), ("tone_hz", 2000), ("ptt_variant", "pause"),
                       ("hang_ms", 100), ("hang_ms", 5000),
                       ("modes", ["A", "C"]), ("delay_ms", 100), ("enabled", "oui")):
        bad = dummy_config()
        setattr(bad.cw, key, value)
        assert cfgmod.validate(bad), key


def test_cw_section_is_read_from_station_toml():
    from trxstation import config as cfgmod
    from trxstation.setup_wizard import dummy_config
    data = {"rig": {"model": 1, "tx_modes": ["PKTUSB"]}, "bands": [{"name": "40m", "low_mhz": 7.0, "high_mhz": 7.2}],
            "cw": {"enabled": True, "delay_ms": 250, "idle_disarm_s": 10}}
    cfg = cfgmod.from_dict(data)
    assert cfg.cw.enabled and cfg.cw.delay_ms == 250 and cfg.cw.idle_disarm_s == 10
    assert dummy_config().cw.delay_ms == 300
