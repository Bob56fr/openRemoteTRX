# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Breizh Audio Box dans la chaîne d'émission : tests de panne du § 9 (docs/breizh-cahier-des-charges.md).

Vraie liaison UDP (BreizhLink) contre le faux Breizh, vraie route et vraie porte ; puis la passerelle complète avec
le faux rigctld (modèle factice) : Breizh perdu pendant une émission ne touche JAMAIS au PTT."""
from __future__ import annotations

import asyncio
import json
import socket
from types import SimpleNamespace

import numpy as np
import pytest

from trxstation.breizh import protocol as bp
from trxstation.breizh.link import BreizhLink
from trxstation.breizh.store import BreizhStore
from trxstation.config import Breizh
from trxstation.devtools import fake_breizh
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.api.session import build_state
from trxstation.gateway.audio import TxAudioGate
from trxstation.gateway.audio.devices import RecordingSink
from trxstation.gateway.audio.limiter import PeakLimiter
from trxstation.gateway.audio.pcm import tone
from trxstation.gateway.audio.route import TxRoute

from test_api import connect, station, until

KEY = bytes(range(32))
FRAME = tone(1000, -20)                       # 20 ms, 2 blocs


def run(coro, timeout=30):
    return asyncio.run(asyncio.wait_for(coro, timeout))


def peak_db(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype="<i2").astype(float)
    return 20 * np.log10(max(1.0, float(np.max(np.abs(samples)))) / 32768)


class Bench:
    """Porte + route + liaison réelle contre le faux Breizh (port libre de 127.0.0.1)."""

    async def start(self, tmp_path, *, mode="echo", fake=True, reactivate_after_s=60, gate=None, sink=None, **options):
        cfg_options = {k: options.pop(k) for k in ("block_timeout_ms", "lost_ms", "fallback_gain_db") if k in options}
        fake_key = options.pop("fake_key", KEY)
        if fake:
            self.fake_transport, self.fake = await fake_breizh.serve(fake_key, "127.0.0.1", 0, mode=mode, **options)
            self.port = self.fake_transport.get_extra_info("sockname")[1]
        else:
            self.fake_transport = self.fake = None
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:      # port fermé : personne n'écoute
                s.bind(("127.0.0.1", 0))
                self.port = s.getsockname()[1]
        self.owner = "phone"
        self.sink = sink or RecordingSink()
        self.gate = gate or TxAudioGate(self.sink, owner_provider=lambda: self.owner)
        self.store = BreizhStore(tmp_path)
        self.events = []
        self.store.add_listener(self.events.append)
        self.cfg = Breizh(enabled=True, host="127.0.0.1", port=self.port, **cfg_options)
        self.link = BreizhLink("127.0.0.1", self.port, KEY, reactivate_after_s=reactivate_after_s,
                               station_version="test", notify=self.store.event)
        self.route = TxRoute(self.gate, self.link, self.cfg, self.store)
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(self.link.run(self.stop))
        if fake and fake_key == KEY and mode not in ("cat_on", "proto2", "mode_off"):
            await until(lambda: self.link.ready, 3)
        return self

    async def close(self):
        self.stop.set()
        await asyncio.wait_for(self.task, 3)
        if self.fake_transport is not None:
            self.fake_transport.close()

    async def speak(self, frames: int, client="phone", pace=0.02):
        for _ in range(frames):
            self.route.push(client, FRAME)
            await asyncio.sleep(pace)

    def written(self) -> bytes:
        return b"".join(self.sink.frames)

    def kinds(self):
        return [e["event"] for e in self.events]


def bench_test(coro_fn, tmp_path, **options):
    async def go():
        b = await Bench().start(tmp_path, **options)
        try:
            await coro_fn(b)
        finally:
            await b.close()
    run(go())


# --------------------------------------------------------------------------- marche normale

def test_echo_passes_every_block_in_order_and_unchanged(tmp_path):
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(20)
        await until(lambda: len(b.written()) == 20 * len(FRAME), 2)
        assert b.written() == FRAME * 20                    # même son, dans l'ordre, rien en double
        assert b.route.snapshot()["state"] == "active" and b.route.snapshot()["route"] == "breizh"
        assert b.route.late == 0 and b.route.fallbacks == 0 and b.fake.stats["audio"] == 40
        b.gate.set_open(False)
        assert b.route.snapshot()["state"] == "ready"
    bench_test(scenario, tmp_path)


def test_breizh_gain_then_return_gain(tmp_path):
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(5)
        await until(lambda: len(b.sink.frames) >= 10, 2)
        assert peak_db(b.written()) == pytest.approx(peak_db(FRAME) - 6, abs=0.2)
        b.gate.set_open(False)
        b.store.update(return_gain_db=6.0)                  # volume retour : appliqué par la station après Breizh
        b.sink.frames.clear()
        b.gate.set_open(True)
        await b.speak(5)
        await until(lambda: len(b.sink.frames) >= 10, 2)
        assert peak_db(b.written()) == pytest.approx(peak_db(FRAME), abs=0.2)
    bench_test(scenario, tmp_path, mode="gain", gain_db=-6.0)


# --------------------------------------------------------------------------- pannes

def test_breizh_absent_at_start_goes_direct_without_delay(tmp_path):
    """Test 1 : personne n'écoute ; l'émission part aussitôt en direct, gain normal ; aucune exception (ICMP)."""
    async def scenario(b):
        await asyncio.sleep(0.3)
        assert b.link.state == "connecting" and not b.link.ready
        b.gate.set_open(True)
        assert b.route.push("phone", FRAME) and b.sink.frames == [FRAME]      # écrit tout de suite
        assert b.route.snapshot()["route"] == "direct"
    bench_test(scenario, tmp_path, fake=False)


def test_frozen_breizh_during_tx_falls_back_fast_and_keeps_the_sound_continuous(tmp_path):
    """Test 2 : repli en moins de lost_ms + marge ; fin de l'émission en direct à gain réduit ; rien de perdu."""
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(10)
        await until(lambda: len(b.sink.frames) == 20, 2)
        b.fake.paused = True
        loop = asyncio.get_running_loop()
        frozen_at = loop.time()
        while b.route.route == "breizh":
            b.route.push("phone", FRAME)
            await asyncio.sleep(0.02)
            assert loop.time() - frozen_at < 0.5
        assert loop.time() - frozen_at < 0.1 + 0.1                # lost_ms (100 ms) + marge des minuteries de Windows
        assert b.kinds()[-1] == "fallback" and b.route.fallbacks == 1
        assert b.route.snapshot()["state"] == "fallback" and b.link.state == "fallback"
        before = len(b.sink.frames)
        b.route.push("phone", FRAME)
        assert len(b.sink.frames) == before + 1                  # direct : tout de suite
        assert peak_db(b.sink.frames[-1]) == pytest.approx(peak_db(FRAME) - 6, abs=0.2)
        pushed = 10 + round((loop.time() - frozen_at) / 0.02) + 1
        assert abs(len(b.written()) - pushed * len(FRAME)) <= 2 * len(FRAME)   # son continu, rien en double
    bench_test(scenario, tmp_path)


def test_slow_breizh_blocks_are_replaced_in_order_and_late_returns_dropped(tmp_path):
    """Test 3 : délai entre block_timeout_ms et lost_ms : blocs secs, ordre gardé, aucun en double, PAS de repli."""
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(15)
        await asyncio.sleep(0.3)
        assert b.route.fallbacks == 0 and b.route.route == "breizh"
        assert b.route.late == 30 and b.link.rejected["late"] > 0
        assert b.written() == b"".join(PeakLimiter().process(FRAME[i:i + 960], -6) for i in (0, 960)) * 15
    bench_test(scenario, tmp_path, mode="slow", delay_ms=70)


def test_too_slow_breizh_falls_back(tmp_path):
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(15)
        await asyncio.sleep(0.2)
        assert b.route.fallbacks == 1 and b.route.route == "direct" and "fallback" in b.kinds()
    bench_test(scenario, tmp_path, mode="slow", delay_ms=400)


def test_forged_returns_never_reach_the_rig(tmp_path):
    """Test 4 : étiquettes fausses : jamais écrites (le son sort sec, à −6 dB), puis repli."""
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(10)
        await asyncio.sleep(0.2)
        assert b.link.rejected["tag"] > 0 and b.route.fallbacks == 1
        dry = PeakLimiter().process(FRAME[:960], -6)
        assert all(peak_db(f) == pytest.approx(peak_db(dry), abs=0.1) for f in b.sink.frames)   # jamais le son à +6 dB
    bench_test(scenario, tmp_path, mode="forge", gain_db=6.0)


def test_garbage_flood_does_not_block_the_microphone(tmp_path):
    """Test 4 : des milliers de paquets faux pendant l'émission : comptés, jamais écrits, le micro passe toujours."""
    async def scenario(b):
        b.gate.set_open(True)
        local = b.link.transport.get_extra_info("sockname")
        forged = bp.encode(bp.Packet(bp.Type.AUDIO_RET, b.link.session, 2 ** 31, 0, bytes(960)), bytes(32))
        flood = b.fake_transport
        for i in range(25):
            for _ in range(200):
                flood.sendto(forged, local)
            b.route.push("phone", FRAME)
            await asyncio.sleep(0.02)
        await until(lambda: len(b.written()) == 25 * len(FRAME), 2)
        assert b.link.rejected["tag"] > 1000
        # sous l'avalanche, un retour vrai peut dépasser 40 ms : le bloc part alors sec (−6 dB) ; jamais le son forgé
        allowed = {FRAME[:960], FRAME[960:], *(PeakLimiter().process(FRAME[i:i + 960], -6) for i in (0, 960))}
        assert all(block in allowed for block in b.sink.frames)
    bench_test(scenario, tmp_path)


def test_replayed_returns_are_dropped(tmp_path):
    """Test 5 : chaque bloc n'est écrit qu'une fois."""
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(10)
        await asyncio.sleep(0.1)
        assert b.written() == FRAME * 10 and b.link.rejected["replay"] > 0
    bench_test(scenario, tmp_path, mode="replay")


def test_unsolicited_returns_are_dropped(tmp_path):
    """Test 6 : AUDIO_RET d'un bloc jamais envoyé."""
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(10)
        await asyncio.sleep(0.1)
        assert b.written() == FRAME * 10 and b.link.rejected["unsolicited"] == 20
    bench_test(scenario, tmp_path, mode="spontaneous")


def test_nothing_from_breizh_reaches_the_rig_after_a_cut(tmp_path):
    """Test 7 : coupure (stop, TOT, battement, déconnexion : la porte se ferme) avec des blocs chez Breizh ; une
    nouvelle émission aussitôt après ne reçoit pas non plus les restes de la précédente."""
    async def scenario(b):
        b.gate.set_open(True)
        for _ in range(5):
            b.route.push("phone", FRAME)
        b.gate.set_open(False)                        # coupure : 10 blocs encore chez Breizh (30 ms)
        assert b.sink.frames == [] and b.sink.flushes == 1
        b.gate.set_open(True)                         # émission suivante, tout de suite
        await asyncio.sleep(0.15)
        assert b.sink.frames == [] and b.link.rejected["late"] == 10
        b.route.push("phone", FRAME)
        await until(lambda: len(b.sink.frames) == 2, 1)
        assert b.written() == FRAME
    bench_test(scenario, tmp_path, mode="slow", delay_ms=30, block_timeout_ms=100, lost_ms=200)   # marges : minuteries de Windows


def test_returns_outside_an_emission_are_ignored(tmp_path):
    """Test 8."""
    async def scenario(b):
        b.route._on_return(0, bytes(960))
        b.route._on_return(5, None)
        assert b.sink.frames == [] and b.gate.passed == 0
    bench_test(scenario, tmp_path)


def test_reactivation_waits_for_stability_and_never_during_an_emission(tmp_path):
    """Test 9 : retour seul après reactivate_after_s sans faute, jamais au milieu d'une émission."""
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(3)
        b.fake.paused = True
        await b.speak(10)
        assert b.route.route == "direct"
        b.fake.paused = False
        await until(lambda: "back" in b.kinds(), 4)
        assert b.link.state == "fallback" and b.route.snapshot()["reactivate_in_s"] is not None
        await until(lambda: b.link.ready, 3)
        assert b.kinds()[-1] == "reactivated"
        await b.speak(3)
        assert b.route.route == "direct"                  # l'émission en cours reste en direct
        b.gate.set_open(False)
        b.gate.set_open(True)
        await b.speak(3)
        assert b.route.route == "breizh"                  # la suivante passe par Breizh
    bench_test(scenario, tmp_path, reactivate_after_s=1)


def test_manual_reactivation_only_when_automatic_is_off(tmp_path):
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(3)
        b.fake.paused = True
        await b.speak(10)
        b.gate.set_open(False)
        b.fake.paused = False
        await until(lambda: "back" in b.kinds(), 4)
        await asyncio.sleep(1.2)
        assert b.link.state == "fallback" and b.route.snapshot()["reactivate_in_s"] is None
        assert b.link.reactivate() is False and b.link.ready and b.kinds()[-1] == "reactivated"
    bench_test(scenario, tmp_path, reactivate_after_s=0)


def test_manual_reactivation_before_breizh_answers_is_pending(tmp_path):
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(3)
        b.fake.paused = True
        await b.speak(10)
        await until(lambda: b.link.session_key is None, 1)
        assert b.link.reactivate() is True               # en attente : Breizh ne répond pas encore
        b.fake.paused = False
        await until(lambda: b.link.ready, 4)
        assert b.kinds()[-1] == "reactivated"
    bench_test(scenario, tmp_path, reactivate_after_s=3600)


@pytest.mark.parametrize("mode,why", [("cat_on", "CAT"), ("proto2", "version"), ("mode_off", "mode OpenRemoteTRX")])
def test_refused_links_keep_the_station_direct(tmp_path, mode, why):
    """Test 10."""
    async def scenario(b):
        await until(lambda: b.link.state == "refused", 3)
        assert b.kinds() == ["refused"] and why in b.events[0]["detail"]
        b.gate.set_open(True)
        assert b.route.push("phone", FRAME) and b.route.snapshot()["route"] == "direct"
        assert b.fake.stats["audio"] == 0
    bench_test(scenario, tmp_path, mode=mode)


def test_wrong_key_gets_no_answer_and_the_station_stays_direct(tmp_path):
    async def scenario(b):
        await asyncio.sleep(0.5)
        assert b.link.state == "connecting" and b.fake.stats["rejected"] >= 1 and b.fake.stats["hello"] == 0
        b.gate.set_open(True)
        assert b.route.push("phone", FRAME) and b.sink.frames == [FRAME]
    bench_test(scenario, tmp_path, fake_key=bytes(32))


def test_bypass_goes_direct_at_the_next_emission_only(tmp_path):
    """Test 16 : « Direct » : aucun AUDIO envoyé, gain normal, PING maintenus ; changé pendant une émission : rien."""
    async def scenario(b):
        b.gate.set_open(True)
        await b.speak(3)
        b.store.update(bypass=True)
        await b.speak(3)
        assert b.route.route == "breizh"
        b.gate.set_open(False)
        sent = b.fake.stats["audio"]
        assert b.route.snapshot()["route"] == "direct"
        b.sink.frames.clear()
        b.gate.set_open(True)
        await b.speak(3)
        assert b.fake.stats["audio"] == sent and b.sink.frames == [FRAME] * 3
        pings = b.fake.stats["ping"]
        await asyncio.sleep(1.2)
        assert b.fake.stats["ping"] > pings and b.link.ready
    bench_test(scenario, tmp_path)


def test_nothing_goes_to_breizh_when_closed_or_not_the_owner(tmp_path):
    """Test 15 : porte d'entrée."""
    async def scenario(b):
        await b.speak(3)                                  # porte fermée
        b.gate.set_open(True)
        await b.speak(3, client="car")                    # pas le propriétaire
        await asyncio.sleep(0.05)
        assert b.fake.stats["audio"] == 0 and b.sink.frames == []
        assert b.gate.dropped_closed == 3 and b.gate.dropped_not_owner == 3
    bench_test(scenario, tmp_path)


def test_final_limiter_caps_both_routes(tmp_path):
    """Test 14 : +6 dB chez Breizh et +6 dB de volume retour sur un son fort : crête <= −1 dBFS ; route directe aussi."""
    loud = tone(1000, -1)

    async def scenario(b):
        b.store.update(return_gain_db=6.0)
        b.gate.set_open(True)
        for _ in range(10):
            b.route.push("phone", loud)
            await asyncio.sleep(0.02)
        await until(lambda: len(b.sink.frames) == 20, 2)
        assert max(peak_db(f) for f in b.sink.frames) <= -1.0 + 0.01
        b.gate.set_open(False)
        b.store.update(bypass=True)
        b.gate.gain_db = 12.0                              # [audio] tx_gain_db excessif
        b.sink.frames.clear()
        b.gate.set_open(True)
        b.route.push("phone", loud)
        assert peak_db(b.sink.frames[0]) <= -1.0 + 0.01
    bench_test(scenario, tmp_path, mode="gain", gain_db=6.0)


def test_limiter_leaves_normal_speech_untouched_and_recovers():
    limiter = PeakLimiter()
    quiet = tone(440, -12)
    assert limiter.process(quiet) == quiet
    limiter.process(tone(440, 0), 6.0)
    assert limiter.gain < 0.6
    for _ in range(200):                                   # 4 s : la remontée est finie
        limiter.process(quiet)
    assert limiter.gain == 1.0 and limiter.process(quiet) == quiet


# --------------------------------------------------------------------------- passerelle complète

def test_breizh_lost_during_a_real_emission_never_touches_the_ptt(tmp_path):
    """Test 2 et 12 sur la passerelle : PTT, battements et TOT inchangés ; l'opérateur reçoit l'événement ; puis client
    perdu à l'instant où Breizh l'est aussi : retour RX normal."""
    async def go():
        fake_rig = FakeRigctld()
        await fake_rig.start()
        try:
            async with station(fake_rig) as st:
                b = await Bench().start(tmp_path, gate=st.pipeline.gate, sink=st.sink)
                st.pipeline.route = b.route
                try:
                    phone = await connect(st, "phone")
                    assert "breizh" in phone.of_type("hello")[0]["features"]
                    await phone.say(cmd="toggle", id=1)
                    assert phone.result(1)["ok"] and st.ctrl.snapshot().state == "TX"
                    for i in range(20):
                        st.pipeline.tx_input.push("phone", FRAME)
                        if i == 5:
                            b.fake.paused = True
                        await phone.say(cmd="heartbeat")
                        await asyncio.sleep(0.02)
                    assert st.ctrl.snapshot().state == "TX" and fake_rig.ptt == 1        # émission jamais coupée
                    await until(lambda: any(m.get("event") == "fallback" for m in phone.of_type("breizh_event")), 1)
                    state = phone.of_type("state")[-1]
                    assert state["breizh"]["route"] == "direct" and state["breizh"]["lost"] == 1
                    await phone.session.close()                                          # client perdu
                    assert st.ctrl.snapshot().state == "RX" and fake_rig.ptt == 0
                finally:
                    await b.close()
        finally:
            await fake_rig.stop()
    run(go())


def test_operator_commands_and_journal(tmp_path):
    async def go():
        fake_rig = FakeRigctld()
        await fake_rig.start()
        try:
            async with station(fake_rig) as st:
                b = await Bench().start(tmp_path, gate=st.pipeline.gate, sink=st.sink)
                st.pipeline.route = b.route
                try:
                    phone = await connect(st, "phone")
                    await phone.say(cmd="breizh_set", id=1, return_gain_db=-3.5, bypass=True)
                    r = phone.result(1)
                    assert r["ok"] and r["breizh"]["return_gain_db"] == -3.5 and r["breizh"]["route"] == "direct"
                    assert json.loads((tmp_path / "breizh.json").read_text())["bypass"] is True
                    await until(lambda: any(m.get("event") == "bypass" for m in phone.of_type("breizh_event")), 1)
                    await phone.say(cmd="breizh_set", id=2, bypass=False)
                    await phone.say(cmd="breizh_reactivate", id=3)
                    assert phone.result(3) == {"type": "result", "id": 3, "ok": True, "pending": False,
                                               "breizh": phone.result(3)["breizh"]}
                    await phone.say(cmd="breizh_log", id=4)
                    events = [e["event"] for e in phone.result(4)["entries"]]
                    assert events == ["connected", "bypass", "unbypass"]
                    assert (tmp_path / "breizh-log.jsonl").read_text().count("\n") == 3
                    await phone.say(cmd="breizh_set", id=5, return_gain_db=9)
                    assert phone.of_type("error")[-1]["code"] == "invalid_params"
                finally:
                    await b.close()
        finally:
            await fake_rig.stop()
    run(go())


def test_listener_never_sees_breizh():
    route = SimpleNamespace(snapshot=lambda: {"state": "ready"})
    from trxstation.gateway.cat import RigState
    from trxstation.gateway.safety.ptt import PttSnapshot
    ctrl = SimpleNamespace(snapshot=lambda: PttSnapshot("RX", None, None, False, "", ""), clients=[])
    pipeline = SimpleNamespace(route=route, stats=lambda: {})
    link = SimpleNamespace(state=RigState())
    assert build_state(link, ctrl, pipeline)["breizh"] == {"state": "ready"}
    assert "breizh" not in build_state(link, ctrl, pipeline, role="listener")
    assert "breizh" not in build_state(link, ctrl, SimpleNamespace(stats=lambda: {}))


def test_store_survives_a_broken_file_and_bounds_the_journal(tmp_path):
    (tmp_path / "breizh.json").write_text("{pas du json", encoding="utf-8")
    store = BreizhStore(tmp_path)
    assert store.settings.return_gain_db == 0.0 and store.settings.bypass is False
    for i in range(250):
        store.event("bad_packets", f"n {i}")
    again = BreizhStore(tmp_path)
    assert len(again.journal) == 200 and again.last(1)[0]["detail"] == "n 249"
    with pytest.raises(ValueError):
        store.update(return_gain_db=6.5)


def test_silent_breizh_is_reported_once_in_the_journal(caplog):
    """Breizh arrêté : rien ne répond aux HELLO ; après SILENT_REPORT_S, ORT-6501 une seule fois (pas de ntfy)."""
    import logging

    from trxstation.breizh import link as bl
    now = [0.0]
    events = []
    link = BreizhLink("127.0.0.1", 9, KEY, reactivate_after_s=60, station_version="0.0.0",
                      notify=lambda kind, text: events.append(kind), clock=lambda: now[0])

    class Transport:
        def sendto(self, data, addr=None):
            pass
    link.transport = Transport()
    caplog.set_level(logging.WARNING)
    for _ in range(3):
        now[0] += bl.SILENT_REPORT_S
        link.tick()
    found = [r for r in caplog.records if r.getMessage().startswith("ORT-6501 ")]
    assert len(found) == 1 and "Breizh Audio Box" in found[0].getMessage() and "127.0.0.1:9" in found[0].getMessage()
    assert events == []                                     # aucun événement envoyé aux clients ni à ntfy
