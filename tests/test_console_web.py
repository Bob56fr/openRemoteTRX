# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Console web (étape 229) : jeton à usage unique, cookie, Host et Origin vérifiés, liste fermée des fichiers, état
et menus, « Ouvrir le menu » seulement quand la console attend au menu, terminal intégré (faux, puis vrais pty)."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys

import pytest
from aiohttp.test_utils import TestClient, TestServer

from trxstation import config as cfgmod
from trxstation.console import Console
from trxstation.console_web.server import COOKIE, WebConsole
from trxstation.console_web.terminal import IDLE_MARK, Terminal
from trxstation.setup_wizard import dummy_config


class FakeTerminal(Terminal):
    made: list[FakeTerminal] = []

    def __init__(self, cmd, env, on_output, on_exit, **kw):
        super().__init__(cmd, env, on_output, on_exit)
        self.written: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        FakeTerminal.made.append(self)

    def start(self, loop):
        self.alive = True

    def write(self, data):
        self.written.append(data)

    def resize(self, rows, cols):
        self.sizes.append((rows, cols))

    def close(self):
        self.alive = False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make(tmp_path):
    path = tmp_path / "station.toml"
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    FakeTerminal.made.clear()
    return WebConsole(path, port=free_port(), terminal_factory=FakeTerminal,
                      console_factory=lambda p: Console(p, ask=lambda _q: "", say=lambda _t: None, installed="0.175.0"))


def scenario(tmp_path, body):
    async def run():
        wc = make(tmp_path)
        server = TestServer(wc.app(), host="127.0.0.1", port=wc.port)
        async with TestClient(server) as client:
            await body(wc, client)
    asyncio.run(run())


async def login(wc, client):
    r = await client.get(f"/?t={wc.token}", allow_redirects=False)
    assert r.status == 302 and COOKIE in r.cookies
    return {"Origin": f"http://127.0.0.1:{wc.port}"}


def test_one_time_token_then_cookie_and_every_door_is_closed_without_them(tmp_path):
    async def body(wc, client):
        token = wc.token
        assert (await client.get("/")).status == 403                     # sans cookie
        origin = await login(wc, client)
        r = await client.get("/")
        assert r.status == 200 and "openRemoteTRX Console" in await r.text()
        assert "script-src 'self'" in r.headers["Content-Security-Policy"]
        assert wc.token is None and token                                 # jeton consommé
        import aiohttp
        async with aiohttp.ClientSession() as other:                       # autre navigateur, sans le cookie
            r = await other.get(client.make_url(f"/?t={token}"), allow_redirects=False)
            assert r.status == 403                                        # jeton réutilisé
            assert (await other.get(client.make_url("/api/state"))).status == 403
        assert (await client.get("/api/state", headers={"Host": "evil.example:80"})).status == 403   # rebinding
        assert (await client.post("/api/open", json={"key": "1.1"})).status == 403                  # sans Origin
        assert (await client.post("/api/open", json={"key": "1.1"},
                                  headers={"Origin": "http://evil.example"})).status == 403
        assert (await client.get("/static/../server.py")).status in (403, 404)
        assert (await client.get("/static/server.py")).status == 404
        assert (await client.get("/static/vendor/xterm.js")).status == 200
        assert origin
    scenario(tmp_path, body)


def test_state_lists_the_eight_themes_with_icons_and_help(tmp_path):
    async def body(wc, client):
        await login(wc, client)
        data = await (await client.get("/api/state")).json()
        assert [t["number"] for t in data["themes"]] == [str(n) for n in range(1, 9)]
        assert all(t["icon"] and t["color"].startswith("#") for t in data["themes"])
        assist = data["themes"][1]["items"][0]
        assert assist["key"] == "2.1" and assist["role"] and assist["admin"] is True
        assert data["version"] and data["configured"] is True and data["idle"] is False
        assert data["ui"]["web.open"] == "Ouvrir le menu"
    scenario(tmp_path, body)


def test_state_gives_the_web_app_link_under_the_station_state(tmp_path):
    """Lien vers l'application web sous « Station en marche » (étape 343) : schéma et port de la passerelle, la page y
    met le nom de machine par lequel la console a été ouverte ; « local » si la passerelle n'écoute que sur 127.0.0.1."""
    async def body(wc, client):
        await login(wc, client)
        cfg, _ = cfgmod.load_unchecked(wc.config)
        data = await (await client.get("/api/state")).json()
        n = cfg.network
        dash = {"scheme": "http", "port": cfg.dashboard.port, "hosts": []} if cfg.dashboard.enabled else None
        assert data["webapp"] == {"scheme": "https" if n.tls_cert else "http", "port": n.gateway_port,
                                  "local": n.gateway_bind in ("", "127.0.0.1", "localhost", "::1"),
                                  "dashboard": dash}                # tableau de bord (étape 385), 127.0.0.1 par défaut
        assert data["ui"]["web.webapp"] == "Application Web : {url}" and data["ui"]["web.webapp_open"]
        assert data["ui"]["web.dashboard"] == "Tableau de bord Web : {url}" and data["ui"]["web.dashboard_open"]
        wc.config.unlink()                                                  # station pas encore configurée
        assert (await (await client.get("/api/state")).json())["webapp"] is None
    scenario(tmp_path, body)


def test_open_types_the_menu_only_when_the_console_waits_at_the_menu(tmp_path):
    async def body(wc, client):
        origin = await login(wc, client)
        r = await client.post("/api/open", json={"key": "2.1", "terminal": True}, headers=origin)
        assert r.status == 409 and (await r.json())["busy"]              # pas encore au menu : rien tapé
        term = FakeTerminal.made[-1]
        assert term.cmd[-3:-1] == ["--texte", "--config"] and term.env["TRX_CONSOLE_WEB"] == "1"
        assert term.written == []
        wc.on_output("menu…" + IDLE_MARK)                               # la console attend au menu
        r = await client.post("/api/open", json={"key": "2.1", "terminal": True}, headers=origin)
        assert r.status == 200 and (await r.json())["mode"] == "terminal"
        assert term.written == ["2.1\r"]
        assert (await client.post("/api/open", json={"key": "3.3"}, headers=origin)).status == 409   # 2.1 en cours
        assert (await client.post("/api/open", json={"key": "9.9"}, headers=origin)).status == 400
        assert "".join(wc.scrollback) == "menu…" and IDLE_MARK not in "".join(wc.scrollback)
    scenario(tmp_path, body)


def test_websocket_replays_the_screen_forwards_keys_and_size(tmp_path):
    async def body(wc, client):
        origin = await login(wc, client)
        with pytest.raises(Exception):
            await client.ws_connect("/ws")                               # sans Origin : refusé
        ws = await client.ws_connect("/ws", headers=origin)
        wc.on_output("Bonjour" + IDLE_MARK)
        first = json.loads((await ws.receive()).data)
        assert first["type"] == "output"
        await ws.send_str(json.dumps({"type": "input", "data": "1.2\r"}))
        await ws.send_str(json.dumps({"type": "resize", "rows": 40, "cols": 120}))
        await ws.send_str(json.dumps({"type": "resize", "rows": 4000, "cols": 1}))   # refusé
        await asyncio.sleep(0.2)
        term = FakeTerminal.made[-1]
        assert term.written == ["1.2\r"] and term.sizes == [(40, 120)] and wc.idle is False
        await ws.close()
    scenario(tmp_path, body)


def test_console_marks_the_menu_prompt_only_in_web_mode(tmp_path, monkeypatch, capsys):
    import trxstation.console as module
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    answers = iter(["q"])
    con = Console(path, ask=lambda _q: next(answers), say=lambda _t: None)
    con.loop()
    assert IDLE_MARK not in capsys.readouterr().out
    monkeypatch.setattr(module, "WEB_MODE", True)
    answers = iter(["q"])
    con = Console(path, ask=lambda _q: next(answers), say=lambda _t: None)
    con.loop()
    assert IDLE_MARK in capsys.readouterr().out


def test_web_option_starts_the_local_server(tmp_path, monkeypatch):
    import trxstation.console as module
    import trxstation.console_web.server as server
    started = []
    monkeypatch.setattr(server, "run", lambda config, port: started.append((config.name, port)) or 0)
    assert module.main(["--config", str(tmp_path / "station.toml"), "--web", "--port", "8800"]) == 0
    assert started == [("station.toml", 8800)]


@pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminal Debian")
def test_posix_terminal_gives_a_controlling_tty(tmp_path):
    from trxstation.console_web.terminal import PosixTerminal
    out = []

    async def run():
        done = asyncio.Event()
        term = PosixTerminal(["sh", "-c", "tty; read r; echo r=$r"], dict(os.environ), out.append, done.set)
        term.start(asyncio.get_running_loop())
        await asyncio.sleep(0.3)
        term.write("ok\r")
        await asyncio.wait_for(done.wait(), 10)
    asyncio.run(run())
    text = "".join(out)
    assert "/dev/pts/" in text and "r=ok" in text


@pytest.mark.skipif(sys.platform != "win32", reason="ConPTY : Windows")
def test_windows_terminal_runs_a_console_program(tmp_path):
    pytest.importorskip("winpty")
    from trxstation.console_web.terminal import WindowsTerminal
    out = []

    async def run():
        done = asyncio.Event()
        term = WindowsTerminal(["cmd", "/c", "echo fenetre-ok"], dict(os.environ), out.append, done.set)
        term.start(asyncio.get_running_loop())
        await asyncio.wait_for(done.wait(), 20)
    asyncio.run(run())
    assert "fenetre-ok" in "".join(out)


def test_state_follows_the_display_level_and_the_page_can_change_it(tmp_path, monkeypatch):
    """Étape 234 : chaque menu porte son niveau ; la page enregistre le niveau choisi (mêmes préférences que le menu 0)."""
    import trxstation.console_web.server as server
    prefs = tmp_path / "prefs" / "console.json"
    monkeypatch.setattr(server, "prefs_path", lambda: prefs)

    async def body(wc, client):
        wc.console_factory = lambda p: Console(p, ask=lambda _q: "", say=lambda _t: None, installed="0.179.0",
                                               level="basic")
        origin = await login(wc, client)
        data = await (await client.get("/api/state")).json()
        assert data["level"] == "basic" and data["ui"]["level.expert"] == "Expert"
        items = {it["key"]: it for th in data["themes"] for it in th["items"]}
        assert items["2.1"]["visible"] is True and items["3.1"]["level"] == "expert" and items["3.1"]["visible"] is False
        assert items["5.1"]["visible"] is False and items["5.1"]["level"] == "normal"
        assert (await client.post("/api/level", json={"level": "expert"})).status == 403          # sans Origin
        assert (await client.post("/api/level", json={"level": "root"}, headers=origin)).status == 400
        assert (await client.post("/api/level", json={"level": "expert"}, headers=origin)).status == 200
        assert json.loads(prefs.read_text(encoding="utf-8"))["level"] == "expert"
    scenario(tmp_path, body)


def test_state_gives_the_documentation_tiles_in_the_console_language(tmp_path):
    """Tuiles « Guides » et « Références » (étape 349) : sans numéro, mode d'emploi de la console en tête, liens publics
    en https ; une documentation pas encore traduite mène au français ; langues publiées = celles des fabriques."""
    import importlib.util
    from pathlib import Path

    from trxstation.console_web import docs

    async def body(wc, client):
        await login(wc, client)
        data = await (await client.get("/api/state")).json()
        groups = data["docs"]
        assert [g["id"] for g in groups] == ["guides", "refs"]
        assert groups[0]["links"][0]["key"] == "console" and groups[0]["title"] == "Guides"
        for group in groups:
            for link in group["links"]:
                assert link["url"].startswith("https://") and link["label"] and not link["label"].startswith("web.")
    scenario(tmp_path, body)
    english = {d["id"]: {l["key"]: l["url"] for l in d["links"]} for d in docs.doc_tiles(lambda k: k, "en")}
    assert english["guides"]["console"].endswith("/console/en/")
    assert english["guides"]["guide"] == docs.SITE + "guide/"                           # guide encore en français
    assert english["guides"]["pdf"].endswith("guide-openRemoteTRX-fr.pdf")
    root = Path(__file__).resolve().parents[1] / "scripts"
    for name, langs in (("build_user_guide", docs.GUIDE_LANGS), ("build_console_doc", docs.CONSOLE_LANGS)):
        spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert tuple(module.LANGS) == langs, name


def test_troubleshooting_report_is_downloadable_and_nothing_else(tmp_path, monkeypatch):
    """Étape 359 : rapport du menu 6.3 téléchargé depuis la page ; session exigée, nom du rapport seulement, Bureau
    seulement."""
    desktop = tmp_path / "Bureau"
    desktop.mkdir()
    (desktop / "trx-remote-rapport-20261122-1259.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    (desktop / "secret.txt").write_text("non")
    (tmp_path / "trx-remote-rapport-20261122-1300.zip").write_bytes(b"ailleurs")
    monkeypatch.setattr("trxstation.report.desktop_dir", lambda *a, **k: desktop)

    async def body(wc, client):
        url = "/api/report/trx-remote-rapport-20261122-1259.zip"
        assert (await client.get(url)).status == 403                                     # sans session
        await login(wc, client)
        r = await client.get(url)
        assert r.status == 200 and r.headers["Content-Type"] == "application/zip"
        assert "attachment" in r.headers["Content-Disposition"] and (await r.read()).startswith(b"PK")
        for bad in ("secret.txt", "trx-remote-rapport-20261122-9999.zip", "..%2Ftrx-remote-rapport-20261122-1300.zip",
                    "trx-remote-rapport-20261122-1259.zip.txt"):
            assert (await client.get("/api/report/" + bad)).status == 404, bad
    scenario(tmp_path, body)
