# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""SELCALL, lot 3 : ÉMISSION de la trame (fin d'émission à la place du roger bip ; appel manuel répété).
TESTS DE PANNE du PttController : toute coupure (STOP, TOT, battement perdu, déconnexion, nouvel appui, séquence
bloquée) l'interrompt net ; le micro du client n'est jamais ouvert pendant un appel ; le poste revient en RX."""
from __future__ import annotations

import asyncio
import contextlib
import time

import numpy as np
import pytest

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.audio import beeps as bp
from trxstation.gateway.audio.pcm import SAMPLE_RATE
from trxstation.gateway.cat import CatLink
from trxstation.gateway.safety import PttController
from trxstation.gateway.safety.ptt import Refused
from trxstation.selcall import decoder as dec
from trxstation.selcall import protocol as sp
from trxstation.setup_wizard import dummy_config

from test_beeps import RecordingSink
from test_safety import beating, fast_limits, until


def run(scenario):
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        try:
            await asyncio.wait_for(scenario(fake), 30)
        finally:
            await fake.stop()
    asyncio.run(wrapper())


class SelcallSpyTail:
    """Joueur factice : trame SELCALL de fin voulue ou non, durée réglable, peut bloquer."""

    def __init__(self, fake, *, selcall=True, roger=True, duration=0.4, hang=False):
        self.fake, self.duration, self.hang = fake, duration, hang
        self.code = "4721" if selcall else None
        self.roger = roger
        self.store = bp.BeepStore()
        self.played, self.ptt_during, self.finished, self.stopped = [], [], [], 0

    def wanted(self, kind):
        return {"selcall": self.code is not None, "roger": self.roger}.get(kind, False)

    def max_wait(self, kind):
        return sp.duration_s(self.code) + bp.SELCALL_MARGIN_S if kind == "selcall" else bp.TAIL_WAIT_S

    async def play(self, kind):
        self.played.append(kind)
        self.ptt_during.append(self.fake.ptt)
        await asyncio.sleep(30 if self.hang else self.duration)
        self.finished.append(kind)

    def stop(self):
        self.stopped += 1


@contextlib.asynccontextmanager
async def station(fake, tail, *, limits=None):
    link = CatLink("127.0.0.1", fake.port, poll_fast_s=0.02, slow_every=2, backoff_min_s=0.05, backoff_max_s=0.2, timeout=0.5)
    gate = []
    ctrl = PttController(link, dummy_config(), limits=limits or fast_limits(),
                         audio_gate=lambda open_: gate.append((open_, fake.ptt)), tail=tail)
    task = asyncio.create_task(link.run())
    await ctrl.start()
    for c in ("phone", "car"):
        ctrl.connect_client(c)
    await until(lambda: link.state.connected and not ctrl.starting)
    try:
        yield ctrl, gate
    finally:
        await asyncio.wait_for(ctrl.close(), 5)
        link.stop()
        await asyncio.wait_for(task, 3)


def sequence_of(seconds, log, hang=False):
    async def seq():
        log.append("début")
        await asyncio.sleep(60 if hang else seconds)
        log.append("fin")
    return seq


# ------------------------------------------------------------------ la trame elle-même


def test_selcall_frames_are_paced_level_bounded_and_decodable():
    frames, marks = bp.selcall_frames("4721", -6.0, gap_s=0.5, repeat=3)
    pcm = np.frombuffer(b"".join(frames), dtype="<i2").astype(np.float64) / 32768
    one = sp.duration_s("4721")
    assert len(pcm) == pytest.approx((3 * one + 2 * 0.5) * SAMPLE_RATE, abs=960)
    assert np.max(np.abs(pcm)) <= 10 ** (-6 / 20) + 1e-3
    assert marks == [0, round((one + 0.5) * SAMPLE_RATE) // 960, round(2 * (one + 0.5) * SAMPLE_RATE) // 960]
    decoded = dec.decode(pcm[::6] + np.random.default_rng(1).standard_normal(len(pcm[::6])) * 0.002)   # 48 -> 8 kHz
    assert [f.code for f in decoded if f.valid] == ["4721"] * 3


def test_real_player_plays_the_end_frame_and_the_manual_call_with_progress():
    async def go():
        sink = RecordingSink()
        player = bp.TailPlayer(sink, bp.BeepStore())
        assert not player.wanted("selcall")
        player.selcall_code = lambda: "123"
        assert player.wanted("selcall") and player.max_wait("selcall") == pytest.approx(2.2 + bp.SELCALL_MARGIN_S)
        t0 = time.perf_counter()
        await player.play("selcall")
        assert time.perf_counter() - t0 >= 2.2 - bp.LEAD_S - 0.05                      # au rythme réel
        assert len(sink.frames) == len(player.frames("selcall"))
        steps = []
        sink2 = RecordingSink()
        caller = bp.TailPlayer(sink2, bp.BeepStore())
        task = asyncio.ensure_future(caller.play_selcall_call("123", 3, 0.2, progress=lambda k, n: steps.append(f"{k}/{n}")))
        await asyncio.sleep(0.5)
        caller.stop()                                                                    # annulation : tampon vidé
        await task
        assert steps == ["1/3"] and sink2.flushes == 1
    asyncio.run(go())


# ------------------------------------------------------------------ fin d'émission


def test_end_of_transmission_selcall_replaces_the_roger_beep():
    async def scenario(fake):
        tail = SelcallSpyTail(fake, duration=2.2)                                       # plus long qu'un bip (1,2 s)
        async with station(fake, tail) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            await ctrl.toggle("phone")
            beat.cancel()
            assert tail.played == ["selcall"] and tail.finished == ["selcall"] and tail.ptt_during == [1]
            assert gate[-1] == (False, 1)                                               # micro fermé AVANT la trame
            assert ctrl.snapshot().state == "RX" and fake.ptt == 0
    run(scenario)


def test_end_frame_is_skipped_when_the_tot_cannot_hold_it():
    async def scenario(fake):
        tail = SelcallSpyTail(fake)
        async with station(fake, tail, limits=fast_limits(tot_s=3.5)) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            await asyncio.sleep(1.0)                                                    # restent 2,5 s < 3,1 s de trame
            await ctrl.toggle("phone")
            beat.cancel()
            assert tail.played == ["roger"] and fake.ptt == 0
    run(scenario)


@pytest.mark.parametrize("how", ["stop", "disconnect", "rekey"])
def test_any_cut_during_the_end_frame_stops_it_at_once(how):
    async def scenario(fake):
        tail = SelcallSpyTail(fake, duration=3.0)
        async with station(fake, tail) as (ctrl, gate):
            await ctrl.toggle("phone")
            release = asyncio.ensure_future(ctrl.toggle("phone"))
            await until(lambda: tail.played)
            t0 = time.perf_counter()
            if how == "stop":
                await ctrl.force_rx("stop", by="car")
            elif how == "disconnect":
                await ctrl.disconnect_client("phone")
            else:
                await ctrl.toggle("phone")                                              # nouvel appui pendant la trame
            assert time.perf_counter() - t0 < 1.0 and fake.ptt == 0 and ctrl.snapshot().state == "RX"
            assert tail.stopped >= 1 and tail.finished == []
            await release
    run(scenario)


def test_a_hanging_end_frame_cannot_hold_the_transmitter():
    async def scenario(fake):
        tail = SelcallSpyTail(fake, hang=True)
        async with station(fake, tail) as (ctrl, gate):
            await ctrl.toggle("phone")
            t0 = time.perf_counter()
            await ctrl.toggle("phone")
            assert time.perf_counter() - t0 < sp.duration_s("4721") + bp.SELCALL_MARGIN_S + 1.0
            assert fake.ptt == 0 and ctrl.snapshot().state == "RX"
    run(scenario)


# ------------------------------------------------------------------ appel manuel


def test_manual_call_keys_with_the_mic_closed_plays_then_returns_to_rx():
    async def scenario(fake):
        async with station(fake, SelcallSpyTail(fake)) as (ctrl, gate):
            log = []
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            snap = await ctrl.send_selcall("phone", sequence_of(0.6, log), 0.6)
            assert snap.state == "TX" and snap.owner == "phone" and fake.ptt == 1
            await until(lambda: ctrl.snapshot().state == "RX", timeout=3)
            beat.cancel()
            assert log == ["début", "fin"] and fake.ptt == 0
            assert ctrl.snapshot().last_cut_reason == "selcall_sent"
            assert all(open_ is False for open_, _ in gate)                              # micro du client JAMAIS ouvert
    run(scenario)


@pytest.mark.parametrize("how", ["stop", "owner_toggle", "other_client", "disconnect", "heartbeat"])
def test_manual_call_is_interrupted_by_any_cut(how):
    async def scenario(fake):
        async with station(fake, SelcallSpyTail(fake)) as (ctrl, gate):
            log = []
            beat = asyncio.ensure_future(beating(ctrl, "phone")) if how != "heartbeat" else None
            await ctrl.send_selcall("phone", sequence_of(5.0, log), 3.0)
            await asyncio.sleep(0.2)
            if how == "stop":
                await ctrl.force_rx("stop", by="car")
            elif how == "owner_toggle":
                await ctrl.toggle("phone")
            elif how == "other_client":
                await ctrl.toggle("car")
            elif how == "disconnect":
                await ctrl.disconnect_client("phone")
            await until(lambda: ctrl.snapshot().state == "RX", timeout=3)                # battement perdu : chien de garde
            if beat is not None:
                beat.cancel()
            assert fake.ptt == 0 and "fin" not in log
            expected = {"stop": "stop", "owner_toggle": "toggle", "other_client": "toggle", "disconnect": "client_disconnected",
                        "heartbeat": "heartbeat"}[how]
            assert ctrl.snapshot().last_cut_reason == expected
    run(scenario)


def test_manual_call_is_cut_by_the_tot_and_by_its_own_bound():
    async def scenario(fake):
        async with station(fake, SelcallSpyTail(fake), limits=fast_limits(tot_s=2.0)) as (ctrl, gate):
            with pytest.raises(Refused) as exc:
                await ctrl.send_selcall("phone", sequence_of(5.0, []), 5.0)              # plus long que le TOT : refus
            assert exc.value.reason == "selcall_too_long" and fake.ptt == 0
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            log = []
            await ctrl.send_selcall("phone", sequence_of(0.3, log, hang=True), 0.3)    # séquence bloquée
            await until(lambda: ctrl.snapshot().state == "RX", timeout=5)
            beat.cancel()
            assert ctrl.snapshot().last_cut_reason in ("selcall_timeout", "tot") and fake.ptt == 0
    run(scenario)


def test_manual_call_is_refused_like_a_toggle():
    async def scenario(fake):
        async with station(fake, SelcallSpyTail(fake)) as (ctrl, gate):
            beat = asyncio.ensure_future(beating(ctrl, "car"))
            await ctrl.toggle("car")                                                    # un autre client émet
            with pytest.raises(Refused):
                await ctrl.send_selcall("phone", sequence_of(0.3, []), 0.3)
            await ctrl.toggle("car")
            beat.cancel()
            with pytest.raises(Refused):
                await ctrl.send_selcall("intrus", sequence_of(0.3, []), 0.3)           # client inconnu
            assert fake.ptt == 0
    run(scenario)


# ------------------------------------------------------------------ commande des clients


def test_client_manual_call_through_the_session_with_progress_and_real_audio(tmp_path):
    """`selcall_send` sur une vraie station de test : refus si non armé, puis émission, progression 1/3..3/3 vue par
    tous, trame réellement écrite vers le poste (décodable), retour en RX ; option `send_on_tx_end` réglable."""
    from test_api import connect, run as api_run, station as api_station
    from trxstation.selcall import receiver as rc

    async def scenario(fake):
        async with api_station(fake, limits=fast_limits(tot_s=15.0)) as st:
            store = rc.SelcallStore(tmp_path / "selcall.json")
            st.pipeline.selcall = rc.SelcallReceiver(store)
            st.ctrl.config.selcall.manual_repeat = 3
            st.ctrl.config.selcall.manual_gap_ms = 300
            st.ctrl.tail = bp.TailPlayer(st.sink, bp.BeepStore())
            phone, pc = await connect(st, "phone"), await connect(st, "pc")
            assert "selcall_send" in phone.of_type("hello")[0]["features"]
            await phone.say(cmd="selcall_send", id=1)
            assert phone.result(1)["reason"] == "selcall_not_armed" and fake.ptt == 0
            await phone.say(cmd="selcall_activate", id=2, code="123")
            await pc.say(cmd="selcall_options", id=3, send_on_tx_end=True)
            assert store.tail_code() == "123"
            beat = asyncio.ensure_future(beating(st.ctrl, "phone"))
            await phone.say(cmd="selcall_send", id=4)
            assert phone.result(4)["ok"] and phone.result(4)["ptt"]["state"] == "TX"
            await until(lambda: st.ctrl.snapshot().state == "RX", timeout=12)
            beat.cancel()
            steps = [m["status"]["sending"] for m in pc.of_type("selcall") if m["status"]["sending"]]
            assert steps == ["1/3", "2/3", "3/3"] and store.status.sending == ""
            assert st.ctrl.snapshot().last_cut_reason == "selcall_sent" and fake.ptt == 0
            assert st.pipeline.gate.passed == 0                                         # aucun son de micro passé
            pcm = np.frombuffer(b"".join(st.sink.frames), dtype="<i2").astype(np.float64) / 32768
            decoded = dec.decode(pcm[::6] + np.random.default_rng(2).standard_normal(len(pcm[::6])) * 0.002)
            assert [f.code for f in decoded if f.valid] == ["123"] * 3

    api_run(scenario)
