# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""FreeDV en réception dans la station (étape 164) : [freedv], service (voix décodée à la place du son du poste),
RxHub, commande freedv_set (opérateurs, refusée en émission), état et événements vers TOUS les clients, trx-monitor.

Le moteur est remplacé par FakeEngine (aucun processus) ; ses vrais tests de panne sont dans test_freedv_rx.py."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation import config as cfgmod
from trxstation.config import Access, ClientAuth
from trxstation.freedv.rx_engine import Callsign, SequenceEnd, Status, Voice
from trxstation.freedv.service import FRAME_BYTES, PREFILL_S, RATE, FreedvService, FreedvUnavailable, resolve_program
from trxstation.gateway.api.access import AccessControl
from trxstation.gateway.audio.hub import RxHub
from trxstation.monitor import model
from trxstation.status import GatewayStatus

from test_api import connect, run, station, until

PROGRAM = sys.executable              # un programme qui existe : la vérification de présence passe


class FakeEngine:
    instances: list["FakeEngine"] = []

    def __init__(self, cfg, listener) -> None:
        self.cfg, self.emit = cfg, listener
        self.fed: list[bytes] = []
        self.started = self.stopped = False
        FakeEngine.instances.append(self)

    async def start(self) -> None:
        self.started = True
        self.emit(Status(etat="ecoute"))

    async def stop(self) -> None:
        self.stopped = True

    def feed(self, pcm: bytes) -> None:
        self.fed.append(pcm)


def service(tmp_path, **kw) -> FreedvService:
    return FreedvService(kw.pop("ka9q", PROGRAM), kw.pop("radae", PROGRAM), tmp_path / "freedv",
                         engine_factory=FakeEngine, **kw)


def frame(value: int) -> bytes:
    return value.to_bytes(2, "little", signed=True) * (FRAME_BYTES // 2)


# ---------------------------------------------------------------- [freedv] de station.toml
def test_freedv_section_defaults_validation_and_round_trip():
    cfg = cfgmod.Config()
    assert cfg.freedv.enabled is False and cfg.freedv.ka9q_path == "freedv-ka9q" and cfg.freedv.radae_rx_path == "radae_rx"
    assert cfgmod._freedv_problems(cfg.freedv) == []
    assert cfgmod._freedv_problems(cfgmod.Freedv(enabled="oui")) == ["[freedv] enabled doit valoir true ou false"]
    assert len(cfgmod._freedv_problems(cfgmod.Freedv(ka9q_path="", radae_rx_path="a\nb"))) == 2
    cfg.freedv = cfgmod.Freedv(enabled=True, ka9q_path="/usr/local/bin/freedv-ka9q", radae_rx_path="radae_rx")
    text = cfgmod.render_toml(cfg)
    assert "[freedv]" in text
    import tomllib
    data = tomllib.loads(text)["freedv"]
    assert data == {"enabled": True, "ka9q_path": "/usr/local/bin/freedv-ka9q", "radae_rx_path": "radae_rx", "locator": ""}


def test_resolve_program_finds_a_name_in_the_path_or_a_real_file(tmp_path):
    assert resolve_program(PROGRAM) == PROGRAM
    assert resolve_program(str(tmp_path / "absent")) is None
    assert resolve_program("nexiste-pas-freedv-xyz") is None


def test_resolve_program_finds_a_name_among_the_decoders_shipped_with_the_station(tmp_path):
    """Paquet Windows : décodeurs dans le dossier freedv de la version, à côté de venv (bundled_dir)."""
    from trxstation.freedv.service import bundled_dir
    assert bundled_dir() == Path(sys.prefix).parent / "freedv"
    name = "radae_rx-essai-xyz"
    target = tmp_path / (name + (".exe" if sys.platform == "win32" else ""))
    target.write_bytes(b"x")
    assert resolve_program(name, bundled=tmp_path) == str(target)
    assert resolve_program(name, bundled=tmp_path / "vide") is None


# ---------------------------------------------------------------- service
def test_off_the_station_sound_passes_untouched(tmp_path):
    s = service(tmp_path)
    assert s.process(frame(123)) == frame(123)
    assert s.snapshot()["on"] is False and s.snapshot()["engine"] == "arret"


def test_on_the_decoded_voice_replaces_the_station_sound_after_a_short_prefill(tmp_path):
    async def scenario():
        s = service(tmp_path)
        await s.set_on(True)
        engine = FakeEngine.instances[-1]
        assert engine.cfg.workdir == str(tmp_path / "freedv") and (tmp_path / "freedv").is_dir()
        assert engine.cfg.in_rate == engine.cfg.out_rate == RATE
        assert s.process(frame(500)) == bytes(FRAME_BYTES)                 # pas de voix : silence (synchro = squelch)
        assert engine.fed == [frame(500)]                                    # le son du poste alimente le moteur
        engine.emit(Voice(frame(7) * 4))                                     # 80 ms : sous le remplissage de 150 ms
        assert s.process(frame(500)) == bytes(FRAME_BYTES)
        engine.emit(Voice(frame(7) * 4))                                     # 160 ms : on joue
        outs = [s.process(frame(500)) for _ in range(8)]
        assert outs == [frame(7)] * 8                                        # jamais le son du poste
        assert s.process(frame(500)) == bytes(FRAME_BYTES)                   # plus de voix : silence, nouveau remplissage
        await s.set_on(False)
        assert engine.stopped and s.process(frame(500)) == frame(500)
    asyncio.run(scenario())


def test_the_voice_buffer_never_grows_beyond_one_second(tmp_path):
    async def scenario():
        s = service(tmp_path)
        await s.set_on(True)
        FakeEngine.instances[-1].emit(Voice(frame(1) * 200))                 # 4 s d'un coup
        assert len(s._buf) <= RATE * 2
    asyncio.run(scenario())


def test_missing_decoder_is_refused_with_its_name(tmp_path):
    async def scenario():
        s = service(tmp_path, ka9q=str(tmp_path / "absent-ka9q"))
        with pytest.raises(FreedvUnavailable) as exc:
            await s.set_on(True)
        assert exc.value.reason == "freedv_missing" and "freedv-ka9q" in exc.value.detail
        assert s.on is False
    asyncio.run(scenario())


def test_callsigns_and_sequences_are_kept_and_announced(tmp_path):
    async def scenario():
        s = service(tmp_path, clock=lambda: 1000.0)
        events = []
        s.add_listener(events.append)
        await s.set_on(True)
        e = FakeEngine.instances[-1]
        e.emit(Status(etat="ecoute", sync="sync", confirmed=True, snr_db=7.54, foff_hz=1.5))
        e.emit(Callsign("W6GOK", 9))
        e.emit(SequenceEnd(990.0, 6.7, 5, "SNR médian +12.2 dB", ("W6GOK",)))
        snap = s.snapshot()
        assert snap["confirmed"] is True and snap["snr_db"] == 7.5 and snap["sync"] == "sync"
        assert snap["calls"] == [{"callsign": "W6GOK", "snr_db": 9, "t": 1000.0}]
        assert snap["sequences"][0]["note"] == 5 and snap["sequences"][0]["callsigns"] == ["W6GOK"]
        assert [ev["kind"] for ev in events] == ["callsign", "sequence"]
        summary = s.summary()
        assert summary["last_call"]["callsign"] == "W6GOK" and "calls" not in summary
    asyncio.run(scenario())


def test_engine_failure_leaves_the_mode_and_gives_back_the_station_sound(tmp_path):
    async def scenario():
        s = service(tmp_path)
        events = []
        s.add_listener(events.append)
        await s.set_on(True)
        e = FakeEngine.instances[-1]
        e.emit(Status(etat="panne", cause="radae_rx gelé (plus aucune ligne d'état)", restarts=6))
        await until(lambda: not s.on)
        assert e.stopped and s.fault == "radae_rx gelé (plus aucune ligne d'état)"
        assert s.process(frame(42)) == frame(42)
        assert events[-1] == {"kind": "fault", "cause": "radae_rx gelé (plus aucune ligne d'état)"}
        assert s.snapshot()["fault"] and s.snapshot()["on"] is False
        await s.set_on(True)                                                 # nouvelle demande : la cause s'efface
        assert s.fault is None and s.on
    asyncio.run(scenario())


# ---------------------------------------------------------------- RxHub
def test_hub_freedv_replaces_the_selcall_processor_and_never_breaks_reception(tmp_path):
    hub = RxHub(source=None)
    q = hub.subscribe()
    hub.processor = lambda pcm: bytes(len(pcm))                              # SELCALL en veille : silence
    hub.freedv = SimpleNamespace(on=True, process=lambda pcm: frame(9))
    hub.publish(frame(100))
    assert q.get_nowait() == frame(9)                                        # FreeDV d'abord, SELCALL contourné

    def broken(pcm):
        raise RuntimeError("panne")
    hub.freedv = SimpleNamespace(on=True, process=broken)
    hub.publish(frame(100))
    assert q.get_nowait() == frame(100)                                      # erreur : le son du poste passe
    hub.freedv = SimpleNamespace(on=False, process=broken)
    hub.publish(frame(100))
    assert q.get_nowait() == bytes(FRAME_BYTES)                              # hors mode : chemin habituel (SELCALL)


# ---------------------------------------------------------------- protocole : session
def test_hello_state_and_features_announce_freedv_to_everyone(tmp_path):
    async def scenario(fake):
        async with station(fake) as st:
            st.pipeline.freedv = service(tmp_path)
            phone = await connect(st, "phone")
            hello = phone.of_type("hello")[0]
            assert "freedv" in hello["features"] and hello["freedv"]["on"] is False
            assert phone.of_type("state")[0]["freedv"]["engine"] == "arret"
            await phone.say(cmd="freedv_set", id=1, on=True)
            await until(lambda: any(m.get("id") == 1 for m in phone.of_type("result")))
            assert phone.result(1)["ok"] is True and phone.result(1)["freedv"]["on"] is True
            await until(lambda: phone.of_type("state")[-1]["freedv"]["on"])
            await phone.say(cmd="freedv_set", id=2, on=False)
            await until(lambda: any(m.get("id") == 2 for m in phone.of_type("result")))
            assert phone.result(2)["ok"] and st.pipeline.freedv.on is False
    run(scenario)


def test_station_without_freedv_refuses_the_command():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            assert "freedv" not in phone.of_type("hello")[0]["features"] and phone.of_type("hello")[0]["freedv"] is None
            assert "freedv" not in phone.of_type("state")[0]
            await phone.say(cmd="freedv_set", id=1, on=True)
            await until(lambda: any(m.get("id") == 1 for m in phone.of_type("result")))
            assert phone.result(1)["reason"] == "freedv_unavailable"
    run(scenario)


def test_freedv_mode_cannot_change_during_a_transmission(tmp_path):
    async def scenario(fake):
        async with station(fake) as st:
            st.pipeline.freedv = service(tmp_path)
            phone = await connect(st, "phone")
            await phone.say(cmd="toggle", id=1)
            await until(lambda: st.ctrl.snapshot().state == "TX")
            await phone.say(cmd="freedv_set", id=2, on=True)
            await until(lambda: any(m.get("id") == 2 for m in phone.of_type("result")))
            assert phone.result(2)["ok"] is False and phone.result(2)["reason"] == "freedv_tx"
            assert st.pipeline.freedv.on is False
            await phone.say(cmd="stop", id=3)
    run(scenario)


def test_a_listener_sees_freedv_state_and_events_but_cannot_change_the_mode(tmp_path, monkeypatch):
    from trxstation.gateway.api.access import ListenerSwitch
    original = ListenerSwitch.__init__

    def init(self, path=None):                       # commutateur « Écoute des visiteurs » ouvert, sans fichier
        original(self, path)
        if path is None:
            self.open = True
    monkeypatch.setattr(ListenerSwitch, "__init__", init)

    async def scenario(fake):
        async with station(fake) as st:
            st.pipeline.freedv = service(tmp_path)
            access = AccessControl([ClientAuth("phone", password_hash="x"), ClientAuth("club1", password_hash="y",
                                    role="listener")], Access(max_listeners=2, listeners_need_operator=False))
            visitor = await connect(st, "club1", role="listener", access=access)
            assert "freedv" in visitor.of_type("hello")[0]["features"]
            assert "freedv" in visitor.of_type("state")[0]
            await visitor.say(cmd="freedv_set", id=1, on=True)
            await asyncio.sleep(0.05)
            assert st.pipeline.freedv.on is False                            # liste blanche : refusé
            await st.pipeline.freedv.set_on(True)                            # l'opérateur le choisit ailleurs
            FakeEngine.instances[-1].emit(Callsign("N4WVE", 1))
            await until(lambda: visitor.of_type("freedv_event"))
            assert visitor.of_type("freedv_event")[0] == {"type": "freedv_event", "kind": "callsign",
                                                          "callsign": "N4WVE", "snr_db": 1,
                                                          "t": visitor.of_type("freedv_event")[0]["t"]}
            await st.pipeline.freedv.close()
    run(scenario)


# ---------------------------------------------------------------- trx-monitor
def _snap(freedv: dict):
    status = GatewayStatus(pid=1, seq=1, written_at=0.0, ptt={"state": "RX"}, rig={}, clients=[], freedv=freedv)
    return SimpleNamespace(status=status, gateway_fresh=True)


def test_monitor_shows_freedv_rows():
    assert model._freedv_rows(_snap({})) == ()
    rows = model._freedv_rows(_snap({"on": False, "engine": "arret", "fault": None}))
    assert rows[0].label == "FreeDV" and "non choisi" in rows[0].text
    rows = model._freedv_rows(_snap({"on": False, "fault": "radae_rx gelé"}))
    assert rows[0].level == "bad" and "radae_rx gelé" in rows[0].text
    rows = model._freedv_rows(_snap({"on": True, "engine": "ecoute", "sync": "sync", "confirmed": True, "snr_db": 7.5,
                                     "restarts": 1, "last_call": {"callsign": "W6GOK", "snr_db": 9, "t": 0}}))
    assert "SYNCHRO +7.5 dB" in rows[0].text and "relances 1" in rows[0].text
    assert rows[1].label == "Indicatif" and "W6GOK (9 dB)" in rows[1].text
