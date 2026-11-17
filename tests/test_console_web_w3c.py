# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Console web, lot W3c (étape 238) : tableau de bord dessiné par la page (mêmes panneaux et même journal que
trx-monitor, lecture seule, STOP TX qui ne peut que couper) et station.toml modifiée dans un champ de la page (même
chemin que nano : copie, vérification, différences, confirmation)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

from aiohttp.test_utils import TestClient, TestServer

from trxstation import config as cfgmod
from trxstation.console import Console
from trxstation.console_web.server import WebConsole
from trxstation.setup_wizard import dummy_config
from trxstation.status import GatewayStatus, write_status

from test_console_web import FakeTerminal, free_port, login


def make(tmp_path):
    path = tmp_path / "station.toml"
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    cfg.supervisor.status_path = str(tmp_path / "gateway-status.json")
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return WebConsole(path, port=free_port(), terminal_factory=FakeTerminal,
                      console_factory=lambda p: Console(p, ask=lambda _q: "", say=lambda _t: None, installed="0.181.0"))


def test_the_dashboard_is_drawn_by_the_page_and_stop_tx_can_only_cut(tmp_path, monkeypatch):
    calls = []

    def fake_stop(cfg):
        calls.append(cfg.network.rigctld_port)
        return True, "PTT coupé"

    monkeypatch.setattr("trxstation.monitor.actions.stop_tx", fake_stop)

    async def run():
        wc = make(tmp_path)
        write_status(tmp_path / "gateway-status.json",
                     GatewayStatus(pid=7, seq=1, written_at=time.time(), ptt={"state": "TX", "owner": "pc"},
                                   rig={"connected": True, "frequency_hz": 7074000, "mode": "USB"}, clients=["pc"]))
        async with TestClient(TestServer(wc.app(), host="127.0.0.1", port=wc.port)) as client:
            assert (await client.get("/api/dashboard")).status == 403              # sans session
            origin = await login(wc, client)
            r = await client.post("/api/open", json={"key": "1.3"}, headers=origin)
            assert (await r.json())["mode"] == "dashboard" and wc.flow is None   # aucun menu lancé
            data = await (await client.get("/api/dashboard")).json()
            assert data["ok"] and data["ptt"] == "TX"
            radio = next(p for p in data["panels"] if p["key"] == "radio")
            assert ["PTT", "ÉMISSION", "bad"] in radio["rows"]
            assert {p["key"] for p in data["panels"]} == {"radio", "audio", "connexion", "sante", "materiel", "reseau"}
            assert any("trx-monitor démarré" in line for line in data["log"])
            assert (await client.post("/api/stop_tx")).status == 403               # autre origine : refusé
            assert calls == []
            answer = await (await client.post("/api/stop_tx", headers=origin)).json()
            assert answer == {"ok": True, "message": "PTT coupé"} and calls == [4532]
            data = await (await client.get("/api/dashboard")).json()
            assert any("STOP TX : PTT coupé" in line for line in data["log"])
            net = await (await client.get("/api/dashboard?net=1")).json()
            assert net["ok"]
    asyncio.run(run())


def test_a_broken_station_toml_is_told_not_crashed(tmp_path):
    async def run():
        wc = make(tmp_path)
        (tmp_path / "station.toml").write_text("[rig\n", encoding="utf-8")
        async with TestClient(TestServer(wc.app(), host="127.0.0.1", port=wc.port)) as client:
            origin = await login(wc, client)
            data = await (await client.get("/api/dashboard")).json()
            assert data["ok"] is False and data["error"]
            answer = await (await client.post("/api/stop_tx", headers=origin)).json()
            assert answer["ok"] is False and "STOP" in answer["message"]
    asyncio.run(run())


def play_81(tmp_path, edits, answers):
    """Menu 8.1 joué par le vrai worker : `edits` = textes renvoyés à chaque ouverture de l'éditeur (None = annuler),
    `answers` = réponses aux questions."""
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    env = dict(os.environ, APPDATA=str(tmp_path / "a"), HOME=str(tmp_path / "h"), PYTHONIOENCODING="utf-8",
               TRX_CONSOLE_PAGE="local")
    proc = subprocess.Popen([sys.executable, "-m", "trxstation.console_web.worker", "--config", str(path), "--key", "8.1"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    events, edits, answers = [], list(edits), list(answers)
    deadline = time.monotonic() + 60
    for line in proc.stdout:
        ev = json.loads(line)
        events.append(ev)
        reply = None
        if ev["type"] == "edit":
            text = edits.pop(0)
            reply = {"type": "edit", "cancel": True} if text is None else {"type": "edit", "text": text(ev["text"])}
        elif ev["type"] == "form":
            reply = {"type": "answer", "value": answers.pop(0) if answers else ""}
        if reply is not None:
            proc.stdin.write((json.dumps(reply) + "\n").encode())
            proc.stdin.flush()
        if ev["type"] == "done" or time.monotonic() > deadline:
            break
    proc.stdin.close()
    proc.wait(timeout=20)
    return events, path


def test_station_toml_is_edited_in_the_page_checked_and_refused_when_wrong(tmp_path):
    before = None

    def wrong(text):
        nonlocal before
        before = text
        return text.replace("tot_s = 90", "tot_s = 500")

    # texte faux : refusé (rouge), « Reprendre » = non : abandon, fichier inchangé
    events, path = play_81(tmp_path, [wrong], ["n"])
    edit = next(e for e in events if e["type"] == "edit")
    assert edit["name"] == "station.toml" and "tot_s = 90" in edit["text"]
    says = [e for e in events if e["type"] == "say"]
    assert not any("nano" in e["text"] for e in says)                        # pas de mode d'emploi de nano
    assert any(e.get("tone") == "bad" and "500" in e["text"] for e in says)
    assert path.read_bytes().decode("utf-8") == before                         # octet pour octet


def test_station_toml_edited_in_the_page_is_saved_after_the_differences(tmp_path):
    events, path = play_81(tmp_path, [lambda t: t.replace("tot_s = 90", "tot_s = 60")], ["o"])
    assert any(e["type"] == "form" and e["kind"] == "yesno" for e in events)        # différences puis confirmation
    assert cfgmod.load(path).safety.tot_s == 60
    assert any(e["type"] == "say" and e.get("tone") == "success" for e in events)


def test_cancelling_the_editor_changes_nothing(tmp_path):
    events, path = play_81(tmp_path, [None], [])
    assert any(e["type"] == "say" and e.get("tone") == "unchanged" for e in events)
    assert cfgmod.load(path).safety.tot_s == 90
