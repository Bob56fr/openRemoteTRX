# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Monitoring inter-stations, lot R3b : TRX Console menu 6.5 et ligne « Monitoring » de trx-monitor.

Deux stations complètes (console + module « monlink » + faux relais) : celle qui AIDE et celle qui est AIDÉE. La
demande de la console va directement au module (le dépôt par fichier est le même que la présence, déjà essayé)."""
from __future__ import annotations

import asyncio
import json
import re

from trxstation import config as cfgmod
from trxstation.console import Console, menu_number
from trxstation.devtools.fake_monlink_relay import FakeMonRelay
from trxstation.monitor.model import monlink_row
from trxstation.monlink.engine import ActionRefused
from trxstation.monlink.service import MonlinkService
from trxstation.setup_wizard import dummy_config
from trxstation.status import GatewayStatus, write_status

NOW = 1_795_000_000


class Clock:
    def __init__(self) -> None:
        self.t = float(NOW)

    def __call__(self) -> float:
        return self.t


class FakeMonitor:
    def summary(self) -> dict:
        return {"cpu": 7, "mem": 30, "disk": 20, "temp": 41}


class FakeRunner:
    def run(self, cmd, *, admin=False):
        return 0

    def output(self, cmd):
        return "active"


class Station:
    """Une station : configuration, module « monlink » réel (faux relais), console dont on écrit les réponses."""

    def __init__(self, tmp, name: str, relay: FakeMonRelay, clock: Clock) -> None:
        self.dir = tmp / name
        self.dir.mkdir()
        cfg = dummy_config()
        cfg.supervisor.state_dir = str(self.dir / "etat")
        cfg.supervisor.status_path = str(self.dir / "etat" / "gw.json")
        cfg.monitor_link.enabled = True
        cfg.modules.run = ["monlink"]
        (self.dir / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
        self.service = MonlinkService(cfg, self.dir / "station.toml", relay_factory=relay.transport, clock=clock,
                                      monitor=FakeMonitor())
        self.service.setup()
        self.service.write_status()
        write_status(cfg.supervisor.status_path, GatewayStatus(pid=1, seq=1, written_at=clock(), ptt={"state": "RX"},
                                                                rig={"connected": True, "frequency_hz": 14_200_000,
                                                                     "mode": "USB"}))
        self.answers: list[str] = []
        self.out: list[str] = []
        self.con = Console(self.dir / "station.toml", FakeRunner(), ask=lambda _: self.answers.pop(0) if self.answers
                           else "", say=self.out.append, python="py")
        self.con.module_request = self._direct

    def _direct(self, request_name, reply_rel, action, args, **kw):
        try:
            return {"id": "x", "ok": True, "result": asyncio.run(self.service.act(action, args or {}))}
        except ActionRefused as exc:
            return {"id": "x", "ok": False, "error": exc.reason, "message": str(exc)}

    def menu(self, *answers: str) -> str:
        """Ouvre le menu 6.5 avec ces réponses (puis Entrée = retour) ; renvoie ce qui a été affiché."""
        self.out.clear()
        self.answers = list(answers) + [""]
        self.con.monitoring()
        return "\n".join(self.out)

    def cycle(self) -> None:
        asyncio.run(self.service.step())


def test_menu_number_and_full_assistance_through_both_consoles(tmp_path):
    assert menu_number("monitoring") == "6.5"
    clock = Clock()
    relay = FakeMonRelay(clock=clock)
    helper, aided = Station(tmp_path, "helper", relay, clock), Station(tmp_path, "aided", relay, clock)

    text = helper.menu("1", "Dev 56", "3")
    assert "Pseudo enregistré : Dev 56" in text
    code = re.search(r"\b([0-9A-Z]{5}-[0-9A-Z]{5})\b", text).group(1)
    assert "15 minutes" in text and "6.5" in text

    # La station aidée confirme LA PREMIÈRE (cas ordinaire au téléphone) : aucune erreur, rien ne part encore.
    text = aided.menu("1", "F4XYZ", "4", code.lower(), "oui", "2", "non")
    fp = re.search(r"(\d{3} \d{3})", text).group(1)
    assert "ne pourra RIEN commander" in text and "Liaison active avec Dev 56" in text
    assert "Refusé" not in text

    helper.cycle()                                          # la demande d'appairage arrive
    text = helper.menu("2")
    assert "empreinte à comparer" in text
    text = helper.menu("5", "oui")
    assert fp in text and "Liaison active avec F4XYZ" in text

    clock.t += 61
    aided.cycle()                                           # annonce du profil, puis battement et état
    helper.cycle()
    text = helper.menu("2")
    assert "vous aidez cette station" in text and "processeur 7 %" in text and "CAT OK" in text
    assert "14.200 MHz" not in text                         # fréquence masquée (réponse « non »)

    text = helper.menu("6", "1", "1")                       # assistance, 1 heure
    assert "doit l'accepter" in text
    clock.t += 61
    aided.cycle()
    text = aided.menu()
    assert "DEMANDE D'ASSISTANCE" in text
    text = aided.menu("7", "oui")
    assert "Assistance acceptée pour 1.0 h" in text
    assert "assistance encore" in aided.menu()

    text = aided.menu("9", "oui")                           # l'opérateur aidé termine
    assert "Liaison terminée" in text and "Aucune liaison" in aided.menu()


def test_different_fingerprint_refuses_and_deletes_the_link(tmp_path):
    clock = Clock()
    relay = FakeMonRelay(clock=clock)
    helper, aided = Station(tmp_path, "helper", relay, clock), Station(tmp_path, "aided", relay, clock)
    helper.menu("1", "Dev 56")
    aided.menu("1", "F4XYZ")
    code = re.search(r"([0-9A-Z]{5}-[0-9A-Z]{5})", helper.menu("3")).group(1)
    text = aided.menu("4", code, "non")
    assert "liaison refusée et effacée" in text
    assert "Aucune liaison" in aided.menu()
    assert not [c for c in relay.calls if c[1] == "put"]                   # rien n'est parti


def test_menu_when_disabled_explains_how_to_enable(tmp_path):
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    out: list[str] = []
    Console(tmp_path / "station.toml", FakeRunner(), ask=lambda _: "", say=out.append, python="py").monitoring()
    text = "\n".join(out)
    assert "[monitor_link]" in text and "monlink" in text and "5.5" in text


def test_monitor_row():
    assert monlink_row(None) is None and monlink_row({"enabled": False}) is None
    assert "aucune liaison" in monlink_row({"enabled": True, "links": []}).text
    row = monlink_row({"enabled": True, "links": [{"role": "receiver", "state": "active"},
                                                  {"role": "emitter", "state": "confirm"}]})
    assert "vous aidez 1" in row.text and "1 empreinte(s)" in row.text and row.level == "warn"
    row = monlink_row({"enabled": True, "links": [{"role": "emitter", "state": "active", "request": {"assist": 3600}}]})
    assert "DEMANDE en attente" in row.text and row.level == "warn"
    row = monlink_row({"enabled": True, "problem": "relay"})
    assert "relay" in row.text and row.level == "warn"
    assert json.dumps(monlink_row({"enabled": True, "links": [{"role": "emitter", "state": "active",
                                                              "assist_left_s": 600}]}).text)
