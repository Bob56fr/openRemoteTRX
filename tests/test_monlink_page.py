# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Monitoring inter-stations, lot R5 : commande « monitoring » de la page (passerelle -> module « monlink ») et calculs
de la rubrique (monitoring.js, sous Node)."""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation.gateway.api.session import ControlSession
from trxstation.modules.bus import CommandRefused

ROOT = Path(__file__).resolve().parents[1]


def _session(sent, *, role="operator", monitoring=None):
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), heartbeat=lambda cid: None,
                           config=SimpleNamespace(rig=SimpleNamespace(), safety=SimpleNamespace(allow_replay=False)))
    s = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append, role=role)
    s.monitoring_call = monitoring
    return s


def test_monitoring_command_is_relayed_for_an_operator_only():
    calls, sent = [], []

    async def monitoring(data):
        calls.append(data)
        if data["action"] == "confirm":
            raise CommandRefused("profile", "profil obligatoire")
        return {"links": []}

    s = _session(sent, monitoring=monitoring)
    assert "monitoring" in s.features()
    asyncio.run(s.on_message(json.dumps({"cmd": "monitoring", "id": 1, "action": "view"})))
    assert sent[-1] == {"type": "result", "id": 1, "ok": True, "action": "view", "data": {"links": []}}
    assert calls[-1] == {"action": "view", "args": {}, "client": "phone"}
    asyncio.run(s.on_message(json.dumps({"cmd": "monitoring", "id": 2, "action": "confirm", "args": {"peer": "0" * 32}})))
    assert sent[-1]["ok"] is False and sent[-1]["reason"] == "profile"
    asyncio.run(s.on_message(json.dumps({"cmd": "monitoring", "id": 3, "action": "shell"})))
    assert sent[-1]["type"] == "error" and sent[-1]["code"] == "invalid_params"
    bare = _session(sent)
    assert "monitoring" not in bare.features()
    asyncio.run(bare.on_message(json.dumps({"cmd": "monitoring", "id": 4, "action": "view"})))
    assert sent[-1]["reason"] == "monitoring_unavailable" and sent[-1]["ort"] == "ORT-4014"
    visitor_sent = []
    visitor = _session(visitor_sent, role="listener", monitoring=monitoring)
    assert "monitoring" not in visitor.features()
    before = len(calls)
    asyncio.run(visitor.on_message(json.dumps({"cmd": "monitoring", "id": 5, "action": "view"})))
    assert len(calls) == before                                    # jamais relayée pour un visiteur
    assert visitor_sent and visitor_sent[-1].get("ok") is not True


def test_module_answers_the_page_and_hands_the_report_in_parts(tmp_path):
    """Le module lui-même : on_call (actions du menu 5.5) et report_part (morceaux de 30 ko, recollés à l'identique)."""
    from trxstation import config as cfgmod
    from trxstation.devtools.fake_monlink_relay import FakeMonRelay
    from trxstation.modules.client import CallRefused
    from trxstation.monlink.service import MonlinkService
    from trxstation.setup_wizard import dummy_config

    class Clock:
        t = 1_795_200_000.0

        def __call__(self):
            return self.t

    clock = Clock()
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    cfg.supervisor.status_path = str(tmp_path / "etat" / "gw.json")
    cfg.monitor_link.enabled = True
    service = MonlinkService(cfg, tmp_path / "station.toml", relay_factory=FakeMonRelay(clock=clock).transport,
                             clock=clock, monitor=SimpleNamespace(summary=lambda: {}))
    service.setup()
    assert asyncio.run(service.on_call({"action": "pseudo", "args": {"pseudo": "Dev 56"}, "client": "phone"})) \
        == {"pseudo": "Dev 56"}
    with pytest.raises(CallRefused) as err:
        asyncio.run(service.on_call({"action": "shell", "args": {}}))
    assert err.value.code == "unknown_action"
    with pytest.raises(CallRefused):
        asyncio.run(service.on_call({"action": "view", "args": "x"}))
    # rapport reçu (posé à la main) : morceaux de 30 ko, recollés à l'identique
    peer = "a" * 32
    data = bytes(range(256)) * 300                                  # 76,8 ko : 3 morceaux
    folder = service.store.folder / "rapports"
    folder.mkdir(parents=True)
    (folder / "rapport-x.zip").write_bytes(data)
    service.store.links[peer] = {"role": "receiver", "state": "active", "pseudo": "F4XYZ", "x": "", "ed": "",
                                 "reports": [str(folder / "rapport-x.zip")]}
    first = asyncio.run(service.on_call({"action": "report_part", "args": {"peer": peer, "part": 0}}))
    assert first["parts"] == 3 and first["size"] == len(data) and first["name"] == "rapport-x.zip"
    got = b"".join(base64.urlsafe_b64decode(asyncio.run(service.on_call(
        {"action": "report_part", "args": {"peer": peer, "part": i}}))["data"] + "==") for i in range(3))
    assert got == data
    with pytest.raises(CallRefused) as err:
        asyncio.run(service.on_call({"action": "report_part", "args": {"peer": peer, "part": 3}}))
    assert err.value.code == "part"


def test_page_code_runs_under_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node absent")
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "monitoring_test.js")], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
