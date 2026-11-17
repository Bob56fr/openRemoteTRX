# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diffusion en direct, lot D2 : commande « diffusion » des opérateurs (passerelle -> module), state.diffusion, silence
hors bandes ([diffusion] outside_bands) et calculs de la page (diffusion.js, sous Node)."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation.diffusion import audio as au
from trxstation.gateway.api.session import ControlSession, build_state
from trxstation.gateway.audio.diffusion_out import DiffusionOut
from trxstation.gateway.audio.listeners import ListenerMix, TxTap
from trxstation.modules.bus import CommandRefused

ROOT = Path(__file__).resolve().parents[1]
STATUS = {"enabled": True, "active": True, "access": "prive", "phase": "en_direct", "listeners": 2,
          "remaining_s": 120, "listen_page": "https://diffusion.example.org/ecoute/bob56fr"}


def _session(sent, *, role="operator", diffusion=None, status=None):
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), heartbeat=lambda cid: None,
                           config=SimpleNamespace(rig=SimpleNamespace(), safety=SimpleNamespace(allow_replay=False)))
    s = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append, role=role)
    s.diffusion_call = diffusion
    s.diffusion_status = status
    return s


def test_command_is_relayed_for_an_operator_with_arguments_built_by_the_gateway():
    calls, sent = [], []

    async def diffusion(data):
        calls.append(data)
        if data["action"] == "start" and not data["args"].get("confirm"):
            raise CommandRefused("confirm_required", "avertissement à confirmer")
        return {"active": data["action"] == "start"}

    s = _session(sent, diffusion=diffusion)
    assert "diffusion" in s.features()
    asyncio.run(s.on_message(json.dumps({"cmd": "diffusion", "id": 1, "action": "start",
                                         "args": {"access": "public", "hours": 2, "operator": "usurpé", "cause": "x",
                                                  "secret": 1}})))
    assert sent[-1]["ok"] is False and sent[-1]["reason"] == "diffusion_confirm_required"
    assert sent[-1]["ort"] == "ORT-6109"
    assert calls[-1] == {"action": "start", "args": {"access": "public", "hours": 2, "operator": "phone"},
                         "client": "phone"}                         # opérateur posé par la passerelle, le reste filtré
    asyncio.run(s.on_message(json.dumps({"cmd": "diffusion", "id": 2, "action": "start", "args": {"confirm": True}})))
    assert sent[-1] == {"type": "result", "id": 2, "ok": True, "action": "start", "data": {"active": True}}
    asyncio.run(s.on_message(json.dumps({"cmd": "diffusion", "id": 3, "action": "stop",
                                         "args": {"cause": "overload"}})))
    assert calls[-1]["args"] == {"operator": "phone"}               # jamais une cause choisie par le client
    asyncio.run(s.on_message(json.dumps({"cmd": "diffusion", "id": 4, "action": "listener",
                                         "args": {"generate": True, "access": "public"}})))
    assert calls[-1]["args"] == {"generate": True}
    asyncio.run(s.on_message(json.dumps({"cmd": "diffusion", "id": 5, "action": "shell"})))
    assert sent[-1]["type"] == "error" and sent[-1]["code"] == "invalid_params"


def test_unavailable_errors_and_visitors():
    sent = []
    bare = _session(sent)
    assert "diffusion" not in bare.features()
    asyncio.run(bare.on_message(json.dumps({"cmd": "diffusion", "id": 1, "action": "status"})))
    assert sent[-1]["reason"] == "diffusion_unavailable" and sent[-1]["ort"] == "ORT-4014"

    async def broken(data):
        raise RuntimeError("panne")

    s = _session(sent, diffusion=broken)
    asyncio.run(s.on_message(json.dumps({"cmd": "diffusion", "id": 2, "action": "status"})))
    assert sent[-1]["reason"] == "diffusion_error" and sent[-1]["ort"] == "ORT-4018"

    calls, visitor_sent = [], []

    async def diffusion(data):
        calls.append(data)
        return {}

    visitor = _session(visitor_sent, role="listener", diffusion=diffusion, status=lambda: dict(STATUS))
    assert "diffusion" not in visitor.features()
    asyncio.run(visitor.on_message(json.dumps({"cmd": "diffusion", "id": 3, "action": "stop"})))
    assert not calls and visitor_sent[-1].get("ok") is not True     # jamais relayée pour un visiteur


def test_state_carries_the_broadcast_for_operators_only():
    link = SimpleNamespace(state=SimpleNamespace(connected=True, frequency_hz=7074000, mode="USB", passband_hz=2400,
                                                 strength_db=-60, functions={}, levels={}, split=None,
                                                 tx_frequency_hz=None, offsets={}, vfo=None))
    snap = SimpleNamespace(state="RX", owner=None, tot_remaining_s=None, tot_warning=False, last_cut_reason=None,
                           fault=None, local_remaining_s=None, local_reason=None, local_tx=False, temp_alert=False,
                           temp_c=None)
    ctrl = SimpleNamespace(snapshot=lambda: snap, clients=["phone"])
    op = build_state(link, ctrl, diffusion=dict(STATUS))
    assert op["diffusion"]["listeners"] == 2 and "password" not in json.dumps(op["diffusion"])
    assert "diffusion" not in build_state(link, ctrl, role="listener", diffusion=dict(STATUS))
    assert "diffusion" not in build_state(link, ctrl)


def test_summary_never_carries_a_secret():
    out = DiffusionOut(47999, au.audio_token("s"), None, TxTap(), lambda: False, None)
    assert out.summary() is None
    out.status = dict(STATUS, listener_password="Abcdef234567", secrets="x", meta_choice=["pseudo"])
    s = out.summary()
    assert s["active"] and "listener_password" not in s and "secrets" not in s


def test_outside_bands_silences_the_listeners_without_stopping():
    """Décision de l'utilisateur du 2026-11-17 : hors des [[bands]], silence sauf [diffusion] outside_bands."""
    tap = TxTap()
    state = {"muted": True}
    out = DiffusionOut(47999, au.audio_token("s"), None, tap, lambda: False, None, muted=lambda: state["muted"])
    mix = ListenerMix(tap, out.muted)
    rx = b"\x10\x00" * au.BLOCK
    assert out.frame(mix, rx) == au.SILENCE
    state["muted"] = False
    assert out.frame(mix, rx) == rx                                 # retour dans une bande : le son revient


def test_gateway_mute_rule_follows_the_setting(tmp_path):
    from trxstation import config as cfgmod
    from trxstation.gateway import main as gw
    cfg = cfgmod.Config()
    cfg.bands = [cfgmod.Band("40m", 7.000, 7.200)]
    captured = {}

    class FakeOut:
        def __init__(self, *a, **kw):
            captured["muted"] = a[7] if len(a) > 7 else kw.get("muted")

        async def run(self, stop):
            return None

        def summary(self):
            return None

    link = SimpleNamespace(state=SimpleNamespace(frequency_hz=7_074_000))
    import trxstation.gateway.audio.diffusion_out as dmod
    orig = dmod.DiffusionOut
    dmod.DiffusionOut = FakeOut
    try:
        cfg.supervisor.state_dir = str(tmp_path)

        async def go():
            pipeline = SimpleNamespace(hub=None, tx_tap=None)
            t = gw._start_diffusion_out(cfg, SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX")), pipeline,
                                        SimpleNamespace(call=None), SimpleNamespace(guard=None), asyncio.Event(),
                                        None, link)
            await t
        asyncio.run(go())
    finally:
        dmod.DiffusionOut = orig
    muted = captured["muted"]
    assert muted() is False                                         # 7,074 MHz : dans la bande
    link.state.frequency_hz = 27_555_000
    assert muted() is True                                          # hors bande : silence
    link.state.frequency_hz = None
    assert muted() is True                                          # fréquence inconnue : silence
    cfg.diffusion.outside_bands = True
    link.state.frequency_hz = 27_555_000
    assert muted() is False                                         # l'opérateur a choisi de tout diffuser


def test_page_code_runs_under_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node absent")
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "diffusion_test.js")], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
