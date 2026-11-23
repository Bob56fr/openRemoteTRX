# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Veille du SDR (étape 380) : sdr-core arrêté quand personne n'affiche ni n'écoute le SDR depuis 60 s, réveillé par
la passerelle (« use »), jamais par un client ; contre le faux sdr-core."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation import config as cfgmod
from trxstation.gateway import sdr_use
from trxstation.gateway.api.protocol import ProtocolError, parse_command
from trxstation.gateway.sdr_use import SdrUse
from trxstation.sdr import service
from trxstation.sdr.service import SdrService

FAKE = [sys.executable, "-m", "trxstation.devtools.fake_sdr_core"]


class FakeBus:
    def __init__(self) -> None:
        self.connected = asyncio.Event()
        self.connected.set()
        self.sent: list[dict] = []
        self.on_call = self.on_connect = None

    async def client_message(self, **message) -> None:
        self.sent.append(message)


class Clock:
    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t


async def _until(cond, tries=200):
    for _ in range(tries):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


def _svc(tmp_path, clock):
    bus, emitted = FakeBus(), []
    sd = cfgmod.Sdr(enabled=True, serial="TEST1234", lines_per_s=10)
    svc = SdrService(sd, tmp_path, bus, core_prefix=FAKE, clock=clock, emit=lambda code, **kw: emitted.append(code))
    return svc, bus, emitted


def test_core_stops_after_a_minute_without_use_and_wakes_on_use(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service, "IDLE_REPUBLISH_S", 0.2)

    async def scenario():
        clock = Clock()
        svc, bus, emitted = _svc(tmp_path, clock)
        task = asyncio.ensure_future(svc.run())
        assert await _until(lambda: svc.state["state"] == "running")
        clock.t += 59                                          # 59 s sans personne : toujours en marche
        await asyncio.sleep(0.3)
        assert svc.state["state"] == "running"
        clock.t += 2                                           # 61 s : veille
        assert await _until(lambda: svc.state["state"] == "idle" and svc.proc is None)
        idle_states = len([m for m in bus.sent if m["kind"] == "sdr_state" and m["state"] == "idle"])
        await asyncio.sleep(0.5)                               # état republié pendant la veille (tableau de bord)
        assert len([m for m in bus.sent if m["kind"] == "sdr_state" and m["state"] == "idle"]) > idle_states
        status = json.loads((tmp_path / "sdr" / "status.json").read_text(encoding="utf-8"))
        assert status["state"] == "idle"
        await svc.on_call({"action": "use", "args": {"on": True}})          # rubrique ouverte : réveil
        assert await _until(lambda: svc.state["state"] == "running")
        waking = [m for m in bus.sent if m["kind"] == "sdr_state" and m["state"] == "starting"][-1]
        clock.t += 120                                         # « use » redit : reste éveillé
        await svc.on_call({"action": "use", "args": {"on": True}})
        await asyncio.sleep(0.3)
        awake = svc.state["state"]
        svc.stop()
        await asyncio.wait_for(task, 10)
        return waking, awake, svc, emitted
    waking, awake, svc, emitted = asyncio.run(scenario())
    assert waking["waking"] is True                            # la page dit « sortie de veille, quelques secondes »
    assert awake == "running"
    assert svc.restarts == 0 and emitted == []                 # veille voulue : ni panne ni code d'erreur


def test_listening_keeps_the_sdr_awake_and_lease_expires(tmp_path: Path) -> None:
    clock = Clock()
    svc, _, _ = _svc(tmp_path, clock)
    svc.audio_on = True
    clock.t += 600
    assert not svc.idle_due()                                  # quelqu'un écoute
    svc.audio_on = False
    clock.t += 30
    assert not svc.idle_due()
    clock.t += 31
    assert svc.idle_due()
    svc.note_use(True)
    clock.t += 29
    assert not svc.idle_due()                                  # « on » valable 30 s…
    clock.t += 62
    assert svc.idle_due()                                      # … puis 60 s de plus : passerelle partie = veille
    svc.note_use(False)
    assert not svc.idle_due()                                  # « off » : 60 s comptées depuis maintenant


def test_a_client_cannot_wake_or_put_the_sdr_to_sleep() -> None:
    for action in ("use", "audio", "load"):
        with pytest.raises(ProtocolError):
            parse_command(json.dumps({"cmd": "sdr", "id": 1, "action": action, "args": {"on": True}}))


def _session(view=False, listen=False, listener=False):
    return SimpleNamespace(sdr_view=view, sdr_listen=listen, listener=listener)


def test_gateway_tells_the_module_at_once_then_every_ten_seconds() -> None:
    sessions, said, now = [], [], [0.0]
    use = SdrUse(lambda: sessions, lambda data: said.append(data["args"]["on"]), clock=lambda: now[0])
    use.tick()
    assert said == [False]                                     # premier passage : toujours dit
    sessions.append(_session(listener=True, view=True))        # un visiteur ne compte jamais
    use.tick()
    assert said == [False]
    sessions.append(_session(view=True))
    now[0] = 1.0
    use.tick()
    assert said == [False, True]                               # rubrique ouverte : dit tout de suite
    now[0] = 5.0
    use.tick()
    assert said == [False, True]
    now[0] = 11.0
    use.tick()
    assert said == [False, True, True]                         # redit toutes les 10 s pendant l'usage
    sessions[-1] = _session(listen=True)                       # écoute seule : toujours utilisé
    now[0] = 12.0
    use.tick()
    assert said == [False, True, True]
    sessions.pop()
    use.tick()
    assert said == [False, True, True, False]
    now[0] = 100.0
    use.tick()
    assert said == [False, True, True, False]                  # « off » dit une fois


def test_gateway_survives_a_missing_module() -> None:
    def boom(data):
        raise RuntimeError("module absent")
    use = SdrUse(lambda: [_session(view=True)], boom, clock=lambda: 0.0)
    assert use.tick() is True and use.tick() is False          # pas de rafale de messages


def test_run_loop_stops() -> None:
    async def scenario():
        stop, said = asyncio.Event(), []
        use = SdrUse(lambda: [], lambda data: said.append(data))
        task = asyncio.ensure_future(sdr_use.run(use, stop))
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, 2)
        return said
    assert len(asyncio.run(scenario())) == 1
