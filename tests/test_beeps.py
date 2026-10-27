# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Bips de fin d'émission (roger bip, bip de liaison perdue) : synthèse bornée, réglages, et TESTS DE PANNE
du PttController (le bip retarde la coupure : toute autre coupure doit l'interrompre net)."""
from __future__ import annotations

import asyncio
import contextlib
import json
import math
import time
from array import array

import pytest

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.api.protocol import ProtocolError, parse_command
from trxstation.gateway.audio import beeps as bp
from trxstation.gateway.audio.pcm import FRAME_BYTES, SAMPLE_RATE
from trxstation.gateway.cat import CatLink
from trxstation.gateway.safety import PttController
from trxstation.gateway.safety.ptt import TAIL_MAX_WAIT_S
from trxstation.setup_wizard import dummy_config

from test_safety import beating, fast_limits, until

# ------------------------------------------------------------------ synthèse


@pytest.mark.parametrize("tone", list(bp.TONES))
@pytest.mark.parametrize("pattern", bp.PATTERNS)
def test_every_roger_beep_is_short_soft_edged_and_not_too_loud(tone, pattern):
    seq = bp.roger_sequence(tone, pattern)
    assert bp.sequence_ms(seq) <= bp.MAX_TAIL_S * 1000
    frames = bp.render(seq, bp.LEVEL_DB + 20)                 # gain d'émission excessif : le plafond tient
    assert all(len(f) == FRAME_BYTES for f in frames)
    samples = array("h", b"".join(frames))
    peak = max(abs(x) for x in samples)
    assert peak <= 32767 * 10 ** (bp.MAX_LEVEL_DB / 20) + 1
    assert abs(samples[0]) < 0.05 * peak                      # fondu d'entrée : pas de claquement
    assert len(samples) <= SAMPLE_RATE * bp.MAX_TAIL_S + FRAME_BYTES // 2


def test_link_lost_signature_is_distinct_and_bounded():
    assert bp.sequence_ms(bp.LINK_LOST) <= bp.MAX_TAIL_S * 1000
    tones = [f for f, _ in bp.LINK_LOST if f]
    assert tones == sorted(tones, reverse=True) and len(set(tones)) == 3      # trois tons descendants
    for tone in bp.TONES:
        for pattern in bp.PATTERNS:
            assert [list(s) for s in bp.roger_sequence(tone, pattern)] != [list(s) for s in bp.LINK_LOST]


def test_render_is_truncated_to_the_hard_limit():
    frames = bp.render([(1000, 5000)], -20)                   # 5 s demandées
    assert len(frames) * 0.02 <= bp.MAX_TAIL_S + 0.02


def test_settings_validation_and_persistence(tmp_path):
    path = tmp_path / "beeps.json"
    store = bp.BeepStore(path)
    assert store.config == bp.BeepConfig()                    # absent : tout désactivé
    seen = []
    store.add_listener(seen.append)
    store.update({"roger_enabled": True, "roger_tone": "duo", "roger_pattern": 3})
    assert bp.BeepStore(path).config.roger_pattern == 3 and seen[-1]["roger_sequence"]
    for bad in ({"roger_tone": "440"}, {"roger_pattern": 4}, {"roger_pattern": True}, {"roger_enabled": "oui"},
                {"volume": 1}, {}):
        with pytest.raises(ValueError):
            store.update(bad)
    assert store.config.roger_tone == "duo"
    path.write_text("{abîmé", encoding="utf-8")
    assert bp.BeepStore(path).config == bp.BeepConfig()       # illisible : bips désactivés
    d = bp.BeepConfig().to_dict()
    assert d["tones"] == list(bp.TONES) and d["patterns"] == [1, 2, 3] and d["link_lost_sequence"][0] == [1200, 120]


def test_protocol_beeps_set_closed_list():
    assert parse_command('{"cmd":"beeps_set","id":1,"roger_enabled":true,"roger_pattern":2}').params == \
        {"roger_enabled": True, "roger_pattern": 2}
    for bad in ('{"cmd":"beeps_set","roger_tone":"9999"}', '{"cmd":"beeps_set"}',
                '{"cmd":"beeps_set","link_lost_enabled":1}', '{"cmd":"beeps_set","duree":5}'):
        with pytest.raises(ProtocolError):
            parse_command(bad)


class RecordingSink:
    def __init__(self):
        self.frames, self.flushes = [], 0

    def write(self, pcm):
        self.frames.append(pcm)

    def flush(self):
        self.flushes += 1


def test_player_is_paced_in_real_time_and_stops_on_demand():
    async def go():
        sink = RecordingSink()
        store = bp.BeepStore()
        store.update({"roger_enabled": True, "roger_pattern": 3})
        player = bp.TailPlayer(sink, store)
        t0 = time.perf_counter()
        await player.play("roger")
        elapsed = time.perf_counter() - t0
        assert len(sink.frames) == len(player.frames("roger"))
        assert elapsed >= bp.sequence_ms(bp.roger_sequence("1000", 3)) / 1000 - bp.LEAD_S - 0.03   # pas tout d'un coup
        sink2 = RecordingSink()
        player2 = bp.TailPlayer(sink2, store)
        task = asyncio.ensure_future(player2.play("roger"))
        await asyncio.sleep(0.1)
        player2.stop()
        await task
        assert sink2.flushes == 1 and len(sink2.frames) < len(player2.frames("roger"))
    asyncio.run(go())

# ------------------------------------------------------------------ PttController : tests de panne


def run(scenario):
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        try:
            await asyncio.wait_for(scenario(fake), 20)
        finally:
            await fake.stop()
    asyncio.run(wrapper())


class SpyTail:
    """Joueur de bips factice : note quand il joue, peut traîner ou planter."""

    def __init__(self, fake, *, roger=True, lost=True, duration=0.3, hang=False, crash=False):
        self.fake, self.duration, self.hang, self.crash = fake, duration, hang, crash
        self.wants = {"roger": roger, "link_lost": lost}
        self.store = bp.BeepStore()
        self.played, self.stopped, self.ptt_during = [], 0, []
        self.finished = []

    def wanted(self, kind):
        return self.wants.get(kind, False)

    async def play(self, kind):
        self.played.append(kind)
        self.ptt_during.append(self.fake.ptt)                 # le poste émet ENCORE pendant le bip
        if self.crash:
            raise RuntimeError("carte son perdue")
        await asyncio.sleep(10 if self.hang else self.duration)
        self.finished.append(kind)

    def stop(self):
        self.stopped += 1


@contextlib.asynccontextmanager
async def station(fake, tail, *, limits=None):
    link = CatLink("127.0.0.1", fake.port, poll_fast_s=0.02, slow_every=2,
                   backoff_min_s=0.05, backoff_max_s=0.2, timeout=0.5)
    gate = []
    ctrl = PttController(link, dummy_config(), limits=limits or fast_limits(),
                         audio_gate=lambda open_: gate.append((open_, fake.ptt)), tail=tail)
    link_task = asyncio.create_task(link.run())
    await ctrl.start()
    for c in ("phone", "car"):
        ctrl.connect_client(c)
    await until(lambda: link.state.connected and not ctrl.starting)
    try:
        yield ctrl, gate
    finally:
        await asyncio.wait_for(ctrl.close(), 5)
        link.stop()
        await asyncio.wait_for(link_task, 3)


async def keyed(ctrl, client="phone"):
    await ctrl.toggle(client)
    assert ctrl.snapshot().state == "TX"


def test_roger_beep_on_owner_release_then_rx():
    async def scenario(fake):
        tail = SpyTail(fake)
        async with station(fake, tail) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await keyed(ctrl)
            await ctrl.toggle("phone")
            beat.cancel()
            assert tail.played == ["roger"] and tail.finished == ["roger"] and tail.ptt_during == [1]
            assert gate[-1] == (False, 1)                     # micro du client fermé AVANT le bip, poste encore en émission
            assert ctrl.snapshot().state == "RX" and fake.ptt == 0
            assert ctrl.snapshot().last_cut_reason == "toggle"
    run(scenario)


def test_no_beep_when_disabled_or_released_by_another_client():
    async def scenario(fake):
        tail = SpyTail(fake, roger=False)
        async with station(fake, tail) as (ctrl, gate):
            await keyed(ctrl)
            await ctrl.toggle("phone")
            assert tail.played == [] and fake.ptt == 0
        tail = SpyTail(fake)
        async with station(fake, tail) as (ctrl, gate):
            await keyed(ctrl)
            await ctrl.toggle("car")                          # un autre client coupe : coupure sèche
            assert tail.played == [] and fake.ptt == 0
    run(scenario)


def test_stop_during_the_roger_beep_cuts_at_once():
    async def scenario(fake):
        tail = SpyTail(fake, duration=3.0)
        async with station(fake, tail) as (ctrl, gate):
            await keyed(ctrl)
            release = asyncio.ensure_future(ctrl.toggle("phone"))
            await until(lambda: tail.played)
            t0 = time.perf_counter()
            await ctrl.force_rx("stop", by="car")
            assert time.perf_counter() - t0 < 1.0 and fake.ptt == 0 and ctrl.snapshot().state == "RX"
            assert tail.stopped == 1 and tail.finished == []      # bip interrompu, tampon vidé
            await release
            assert ctrl.snapshot().last_cut_reason == "stop"      # la coupure de STOP prime ; pas de 2e coupure
    run(scenario)


def test_heartbeat_loss_plays_link_lost_beep_then_cuts():
    async def scenario(fake):
        tail = SpyTail(fake)
        async with station(fake, tail) as (ctrl, gate):
            await keyed(ctrl)                                  # aucun battement : le chien de garde coupe
            await until(lambda: ctrl.snapshot().state == "RX", timeout=4)
            assert tail.played == ["link_lost"] and tail.ptt_during == [1] and fake.ptt == 0
            assert ctrl.snapshot().last_cut_reason == "heartbeat"
    run(scenario)


def test_link_lost_beep_disabled_means_immediate_cut():
    async def scenario(fake):
        tail = SpyTail(fake, lost=False)
        async with station(fake, tail) as (ctrl, gate):
            await keyed(ctrl)
            await until(lambda: ctrl.snapshot().state == "RX", timeout=4)
            assert tail.played == []
    run(scenario)


def test_disconnection_plays_link_lost_beep_then_cuts():
    async def scenario(fake):
        tail = SpyTail(fake)
        async with station(fake, tail) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await keyed(ctrl)
            await ctrl.disconnect_client("phone")
            beat.cancel()
            assert tail.played == ["link_lost"] and fake.ptt == 0 and ctrl.snapshot().state == "RX"
            assert ctrl.snapshot().last_cut_reason == "client_disconnected"
    run(scenario)


def test_tot_never_beeps():
    async def scenario(fake):
        tail = SpyTail(fake)
        async with station(fake, tail, limits=fast_limits(tot_s=0.6, warn_before_s=0.2)) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await keyed(ctrl)
            await until(lambda: ctrl.snapshot().state == "RX", timeout=3)
            beat.cancel()
            assert tail.played == [] and ctrl.snapshot().last_cut_reason == "tot"
    run(scenario)


def test_a_hanging_beep_cannot_hold_the_transmitter():
    async def scenario(fake):
        tail = SpyTail(fake, hang=True)
        async with station(fake, tail) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await keyed(ctrl)
            t0 = time.perf_counter()
            await ctrl.toggle("phone")
            beat.cancel()
            assert time.perf_counter() - t0 < TAIL_MAX_WAIT_S + 1.0
            assert fake.ptt == 0 and ctrl.snapshot().state == "RX" and tail.stopped == 1
    run(scenario)


def test_a_crashing_beep_still_cuts():
    async def scenario(fake):
        tail = SpyTail(fake, crash=True)
        async with station(fake, tail) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await keyed(ctrl)
            await ctrl.toggle("phone")
            beat.cancel()
            assert fake.ptt == 0 and ctrl.snapshot().state == "RX"
    run(scenario)


def test_cancelling_the_caller_during_the_beep_still_cuts():
    """La tâche qui a demandé la fin (toggle, déconnexion) est annulée pendant le bip : le chien de garde
    ne surveille plus (état UNKEYING), la coupure doit donc partir quand même."""
    async def scenario(fake):
        tail = SpyTail(fake, duration=3.0)
        async with station(fake, tail) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await keyed(ctrl)
            release = asyncio.ensure_future(ctrl.toggle("phone"))
            await until(lambda: tail.played)
            beat.cancel()
            release.cancel()
            with pytest.raises(asyncio.CancelledError):
                await release
            await until(lambda: fake.ptt == 0 and ctrl.snapshot().state == "RX", timeout=2)
            assert tail.stopped == 1 and tail.finished == []      # bip interrompu par la coupure
    run(scenario)


def test_beep_is_heard_as_transmission_and_rekey_waits():
    async def scenario(fake):
        tail = SpyTail(fake, duration=0.5)
        states = []
        async with station(fake, tail) as (ctrl, gate):
            ctrl.add_listener(lambda snap: states.append(snap.state))
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await keyed(ctrl)
            release = asyncio.ensure_future(ctrl.toggle("phone"))
            await until(lambda: tail.played)
            assert ctrl.snapshot().state == "UNKEYING"         # affiché comme émission pendant le bip
            with pytest.raises(Exception):
                await ctrl.set_frequency(7_100_000)            # pas d'accord pendant le bip
            await release
            beat.cancel()
            assert states[-1] == "RX"
    run(scenario)


def test_gateway_builds_the_tail_player():
    from pathlib import Path
    main = (Path(__file__).resolve().parents[1] / "trxstation" / "gateway" / "main.py").read_text(encoding="utf-8")
    assert "TailPlayer(pipeline.sink, beeps" in main and "tail=tail" in main


def test_session_offers_and_changes_the_beeps():
    from types import SimpleNamespace
    from trxstation.gateway.api.session import ControlSession
    store = bp.BeepStore()
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), tail=SimpleNamespace(store=store),
                           config=SimpleNamespace(rig=SimpleNamespace()))
    sent = []
    session = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append)
    asyncio.run(session.on_message('{"cmd":"beeps_set","id":1,"roger_enabled":true,"roger_tone":"2000"}'))
    assert sent[-1]["ok"] and sent[-1]["settings"]["roger_tone"] == "2000" and store.config.roger_enabled
    bare = ControlSession("phone", SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"),
                                                   config=SimpleNamespace(rig=SimpleNamespace())), SimpleNamespace(), None, None, sent.append)
    asyncio.run(bare.on_message('{"cmd":"beeps_set","id":2,"roger_enabled":true}'))
    assert sent[-1]["ok"] is False and sent[-1]["reason"] == "beeps_unavailable"
