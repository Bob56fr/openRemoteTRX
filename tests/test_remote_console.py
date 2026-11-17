# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Raccourci « Console de la station » (étape 230) : réglage [remote_console] validé, annoncé aux opérateurs seulement,
console web en port fixe pour le tunnel, menu 4.6, modèle du lanceur Windows (partie PowerShell lisible)."""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_api import connect, run, station
from test_console_tools import make, write_config

from trxstation import config as cfgmod
from trxstation.config import Access, ClientAuth
from trxstation.console import MENU_THEMES, menu_number
from trxstation.gateway.api.access import AccessControl

STATIC = Path(__file__).parents[1] / "trxstation" / "gateway" / "api" / "static"


def test_setting_is_off_by_default_and_checked():
    cfg = cfgmod.Config()
    assert cfg.remote_console.enabled is False and cfg.remote_console.web_port == 8765
    _, problems = cfgmod.build({"rig": {"model": 1}, "remote_console": {"enabled": True}})
    assert any("sans ssh_user" in p for p in problems)
    _, problems = cfgmod.build({"rig": {"model": 1}, "remote_console": {"enabled": True, "ssh_user": "bob'; calc"}})
    assert any("nom de compte" in p for p in problems)
    _, problems = cfgmod.build({"rig": {"model": 1}, "remote_console": {"ssh_user": "bob", "web_port": 80}})
    assert any("web_port" in p for p in problems)
    cfg, problems = cfgmod.build({"rig": {"model": 1}, "remote_console": {"enabled": True, "ssh_user": "pi"}})
    assert not problems and "[remote_console]" in cfgmod.render_toml(cfg)


def test_hello_offers_the_shortcut_to_operators_only():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            hello = phone.of_type("hello")[0]
            assert hello["remote_console"] is None and "remote_console" not in hello["features"]
            st.ctrl.config.remote_console = cfgmod.RemoteConsole(enabled=True, ssh_user="bob", ssh_port=2222)
            access = AccessControl([ClientAuth("pc", password_hash="x"), ClientAuth("club1", password_hash="y", role="listener")],
                                   Access(max_listeners=1))
            access.switch.open = True
            access.admit("pc")
            pc = await connect(st, "pc", access=access)
            hello = pc.of_type("hello")[0]
            assert hello["remote_console"] == {"user": "bob", "ssh_port": 2222, "web_port": 8765}
            assert "remote_console" in hello["features"]
            access.admit("club1")
            visitor = await connect(st, "club1", role="listener", access=access)
            hello = visitor.of_type("hello")[0]
            assert hello["remote_console"] is None and "remote_console" not in hello["features"]
    run(scenario)


def test_the_launcher_template_is_served_and_its_page_code_tested():
    from trxstation.gateway.api.server import WEB_FILES
    assert WEB_FILES["/console-station.cmd"][0] == "console-station.cmd"
    assert WEB_FILES["/console_link.js"][0] == "console_link.js"
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node absent")
    done = subprocess.run([node, str(Path(__file__).parent / "js" / "console_link_test.js")], capture_output=True,
                          text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
def test_powershell_part_of_the_launcher_parses(tmp_path):
    text = (STATIC / "console-station.cmd").read_text(encoding="utf-8")
    script = text[text.index("#PS-BEGIN#"):].replace("@@HOST@@", "192.168.1.50").replace("@@USER@@", "pi")         .replace("@@SSH_PORT@@", "22").replace("@@WEB_PORT@@", "8765")
    ps1 = tmp_path / "lanceur.ps1"
    ps1.write_bytes(bytes([0xEF, 0xBB, 0xBF]) + script.encode("utf-8"))      # BOM : PowerShell 5.1 lit alors en UTF-8
    check = (f"$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('{ps1}', [ref]$null, "
             "[ref]$e); if ($e) { $e | ForEach-Object { $_.Extent.StartLineNumber }; exit 1 }")
    done = subprocess.run(["powershell", "-NoProfile", "-Command", check], capture_output=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_shortcut_mode_refuses_an_unexpected_socket_name(tmp_path):
    from trxstation.console_web.server import WebConsole
    path = write_config(tmp_path)
    lines: list[str] = []
    for bad in ("/etc/passwd", "/tmp/trx-console-1234.sock", str(tmp_path / "x.sock")):
        lines.clear()
        assert asyncio.run(WebConsole(path, port=8765).serve(open_browser=False, announce=lines.append,
                                                             socket_path=bad)) is False
        assert "socket refusé" in lines[-1]


@pytest.mark.skipif(os.name != "posix", reason="socket Unix (station Debian)")
def test_shortcut_mode_serves_a_private_socket_and_removes_it(tmp_path):
    import secrets
    import stat

    import aiohttp

    from trxstation.console_web.server import URL_MARK, WebConsole
    path = write_config(tmp_path)
    sock = f"/tmp/trx-console-{secrets.token_hex(16)}.sock"
    lines: list[str] = []

    async def scenario():
        wc = WebConsole(path, port=8765)
        token = wc.token
        task = asyncio.create_task(wc.serve(open_browser=False, announce=lines.append, socket_path=sock))
        while not lines:
            await asyncio.sleep(0.05)
        assert lines == [f"{URL_MARK} http://127.0.0.1:8765/?t={token}"]
        assert stat.S_IMODE(os.stat(sock).st_mode) & 0o077 == 0              # privé : ce compte seul
        async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=sock)) as http:
            r = await http.get(f"http://127.0.0.1:8765/?t={token}", allow_redirects=False)
            assert r.status == 302                                          # jeton accepté au bout du socket
        wc.stop.set()
        assert await task is True
        assert not os.path.exists(sock)                                     # effacé à l'arrêt
    asyncio.run(scenario())


def test_shortcut_option_of_the_console(tmp_path, monkeypatch):
    import trxstation.console as module
    import trxstation.console_web.server as server
    started = []
    monkeypatch.setattr(server, "run", lambda config, port, **kw: started.append((port, kw)) or 0)
    sock = "/tmp/trx-console-" + "a" * 32 + ".sock"
    assert module.main(["--config", str(tmp_path / "station.toml"), "--web", "--port", "8800", "--raccourci", sock]) == 0
    assert started == [(8800, {"socket_path": sock})]


def test_menu_4_6_is_last_of_the_access_theme():
    assert dict((n, m) for n, _k, m in MENU_THEMES)["4"][-1] == "remote_console"
    assert menu_number("remote_console") == "4.6"


@pytest.mark.skipif(os.name == "nt", reason="station Debian : serveur SSH")
def test_menu_saves_account_and_port_through_the_validated_path(tmp_path):
    path = write_config(tmp_path)
    con, _, out = make(tmp_path, answers=["o", "Bob", "pi", "2222", "o"])   # « Bob » refusé (majuscule)
    con.remote_console()
    cfg = cfgmod.load(path)
    assert cfg.remote_console.enabled is True and cfg.remote_console.ssh_user == "pi" and cfg.remote_console.ssh_port == 2222
    assert any("n'est pas un nom de compte" in line for line in out)


@pytest.mark.skipif(os.name != "nt", reason="station Windows")
def test_menu_explains_that_a_windows_station_has_no_ssh_server(tmp_path):
    write_config(tmp_path)
    con, _, out = make(tmp_path)
    con.remote_console()
    assert any("TRX distant" in line for line in out)
