# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diffusion en direct, lot D3 : openRemoteTRX Console (menu 5.6, interrupteur du 5.5), demandes de la console au module, alertes
ntfy de la passerelle au début et à la fin d'une diffusion."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from trxstation import config as cfgmod
from trxstation.console import FEATURES, Console, menu_number, set_feature
from trxstation.diffusion import audio as au, keyfile
from trxstation.diffusion.protocol import DEFAULT_META_CHOICE
from trxstation.diffusion.service import CONSOLE_REPLY, CONSOLE_REQUEST, DiffusionService
from trxstation.errors import codes
from trxstation.gateway.audio.diffusion_out import DiffusionOut
from trxstation.gateway.audio.listeners import TxTap
from trxstation.setup_wizard import dummy_config

KEY = "cd" * 32


class Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, cmd, *, admin=False):
        self.calls.append(cmd)
        if cmd[0] == "install":                         # sudo install : la copie validée remplace l'originale
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(Path(cmd[-2]).read_bytes())
        return 0

    def output(self, cmd):
        return "inactive"


def station(tmp_path) -> Path:
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    path = tmp_path / "etc" / "station.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return path


def make(path: Path, answers, module=None):
    script = iter(answers)
    out: list[str] = []

    def ask(_):
        try:
            return next(script)
        except StopIteration:
            raise EOFError from None

    con = Console(path, Runner(), ask=ask, say=out.append, python="py")
    calls: list[tuple[str, dict]] = []
    if module is not None:
        def request(_name, _reply, action, args, **_kw):
            calls.append((action, dict(args or {})))
            return module(action, args or {})
        con.module_request = request
    return con, out, calls


def test_menu_number_and_feature_switch():
    assert menu_number("diffusion") == "5.6"
    assert ("features.diffusion", "diffusion", "diffusion", "diffusion") in FEATURES
    cfg = dummy_config()
    set_feature(cfg, "diffusion", "diffusion", True)
    assert cfg.diffusion.enabled is True and "diffusion" in cfg.modules.run
    set_feature(cfg, "diffusion", "diffusion", False)
    assert cfg.diffusion.enabled is False and "diffusion" not in cfg.modules.run


def test_settings_are_written_to_station_toml(tmp_path):
    path = station(tmp_path)
    con, out, _ = make(path, ["5", "1", "a b", "1", "Diffusion.Example.org", "o", "2", "bob56fr", "o",
                              "3", "aac", "3", "mp3", "o", "4", "o", "o", "", ""])
    try:
        con.diffusion()
    except EOFError:
        pass
    d = cfgmod.load(path).diffusion
    assert (d.server, d.station, d.codec, d.outside_bands) == ("diffusion.example.org", "bob56fr", "mp3", True)
    text = "\n".join(out)
    assert "Valeur refusée" in text and "C'est vous qui décidez" in text
    assert "Module « diffusion » sans nouvelles" in text and "5.5" in text      # module jamais lancé : le dire


def test_start_asks_the_warning_once_and_sends_safe_defaults(tmp_path):
    path = station(tmp_path)
    answers = iter([{"ok": False, "error": "confirm_required", "message": "avertissement"},
                    {"ok": True, "result": {"active": True, "listen_page": "https://diffusion.example.org/ecoute/b"}}])
    con, out, calls = make(path, ["1", "", "", "", "BOB", "o", ""], module=lambda a, g: next(answers))
    con.diffusion()
    assert calls[0] == ("start", {"access": "prive", "hours": 1, "voice": False, "meta": list(DEFAULT_META_CHOICE),
                                  "pseudo": "BOB"})
    assert calls[1][1]["confirm"] is True and calls[1][1]["voice"] is False
    text = "\n".join(out)
    assert "VOTRE responsabilité" in text and "https://diffusion.example.org/ecoute/b" in text
    assert "Refusé" not in text                                    # la confirmation n'est pas un refus affiché


def test_stop_reveal_and_new_listener_password(tmp_path):
    path = station(tmp_path)

    def module(action, args):
        if action in ("reveal", "listener"):
            return {"ok": True, "result": {"listener_user": "auditeur",
                                           "listener_password": "Neuf23456789" if args.get("generate") else "Abcd23456789"}}
        if action == "stop":
            return {"ok": True, "result": {"active": False}}
        return {"ok": False, "error": "busy", "message": "déjà en cours"}

    con, out, calls = make(path, ["2", "o", "3", "4", "o", "1", "", "0", "", "", ""], module=module)
    con.diffusion()
    text = "\n".join(out)
    assert [c[0] for c in calls] == ["stop", "reveal", "listener", "start"]
    assert calls[2][1] == {"generate": True} and calls[3][1]["hours"] is None          # 0 = sans limite
    assert "Diffusion arrêtée" in text and "Abcd23456789" in text and "Neuf23456789" in text
    assert "Refusé : déjà en cours" in text


def test_secrets_are_written_0600_and_never_shown(tmp_path):
    path = station(tmp_path)
    (tmp_path / "etat" / "diffusion").mkdir(parents=True)
    con, out, _ = make(path, ["6", "MotSource42", "XYZ", "6", "MotSource42", KEY.upper(), ""],
                       module=lambda a, g: {"ok": True, "result": {"listener_user": "amis",
                                                                    "listener_password": "Garde2345678"}})
    con.diffusion()
    text = "\n".join(out)
    assert "Secrets refusés" in text and "Secrets enregistrés" in text
    assert "MotSource42" not in text and KEY not in text
    sec = keyfile.read(tmp_path / "etat" / "diffusion" / "diffusion.key")
    assert (sec.source_password, sec.meta_key, sec.listener_user, sec.listener_password) == (
        "MotSource42", KEY, "amis", "Garde2345678")                   # identifiants des auditeurs gardés


def test_module_answers_console_requests_with_a_forced_operator(tmp_path):
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    service = DiffusionService(cfg, tmp_path / "station.toml")
    state = Path(cfg.supervisor.state_dir)
    state.mkdir(parents=True)

    def request(action, args, at=None):
        (state / CONSOLE_REQUEST).write_text(json.dumps({"id": action, "action": action, "args": args,
                                                         "at": at or time.time()}), encoding="utf-8")
        asyncio.run(service.check_console())
        return json.loads((state / "diffusion" / CONSOLE_REPLY).read_text(encoding="utf-8"))

    reply = request("status", {})
    assert reply["ok"] and reply["result"]["active"] is False and not (state / CONSOLE_REQUEST).exists()
    reply = request("start", {"access": "prive"})
    assert reply["ok"] is False and reply["error"] == "disabled"   # [diffusion] hors service
    (state / "diffusion" / CONSOLE_REPLY).unlink()
    (state / CONSOLE_REQUEST).write_text(json.dumps({"id": "vieux", "action": "status", "args": {}, "at": 1}),
                                         encoding="utf-8")
    asyncio.run(service.check_console())
    assert not (state / "diffusion" / CONSOLE_REPLY).exists()      # demande trop ancienne : ignorée


def test_gateway_alerts_at_start_and_stop():
    alerts = []
    states = iter([{"active": False}, {"active": True, "operator": "BOB", "access": "public", "remaining_s": 3598,
                                       "voice": False, "started": time.time() - 600},
                   {"active": True, "operator": "BOB", "remaining_s": 3500, "started": time.time() - 640},
                   {"active": False, "last_stop": {"cause": "overload"}}])

    async def call(data):
        return next(states)

    out = DiffusionOut(47999, au.audio_token("s"), None, TxTap(), lambda: False, call,
                       alert=lambda code, **kw: alerts.append((code, kw)))
    out._feed_loop = lambda: asyncio.sleep(0)                       # pas de son dans ce test

    async def go():
        for _ in range(4):
            await out.poll()
        await out.close_feed()
    asyncio.run(go())
    assert [a[0] for a in alerts] == [codes.ORT_6101, codes.ORT_6102]
    assert alerts[0][1] == {"operateur": "BOB", "acces": "publique", "duree": "1 h 00 min", "voix": "non"}
    assert alerts[1][1]["cause"] == "station surchargée" and alerts[1][1]["duree"] == "10 min"
