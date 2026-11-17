# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Serveur local de la console web (`trx-console --web`).

Sécurité (cahier § 2, décisions de l'utilisateur du 2026-11-17) :
  * 127.0.0.1 seulement (jamais une autre adresse) ; depuis un autre PC : tunnel SSH vers le même port ;
  * jeton à usage unique dans l'adresse ouverte, échangé contre un cookie de session (HttpOnly, SameSite=Strict) ;
  * en-tête Host vérifié à chaque requête (pas de « DNS rebinding ») ; Origin vérifié pour toute action et pour le
    terminal (pas de requête depuis un autre site ouvert dans le navigateur) ;
  * arrêt après 30 minutes sans page ouverte ; le mot de passe sudo ne fait que traverser le terminal (jamais gardé).
La page ne fait que ce que fait TRX Console, qui ne peut jamais déclencher d'émission.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import sys
import time
import webbrowser
from collections import deque
from collections.abc import Callable
from pathlib import Path

from aiohttp import WSMsgType, web

from .. import __version__
from ..console import MENU_THEMES, Console, load_help, menu_number
from .terminal import IDLE_MARK, Terminal, make_terminal

DEFAULT_PORT = 8765
COOKIE = "trx_console"
IDLE_EXIT_S = 30 * 60              # plus aucune page ouverte depuis 30 min : le serveur s'arrête
SCROLLBACK_CHARS = 200_000         # sortie du terminal rejouée à une page qui se (re)connecte
STATIC = Path(__file__).with_name("static")
STATIC_FILES = {"app.js": "application/javascript", "app.css": "text/css",
                "vendor/xterm.js": "application/javascript", "vendor/xterm.css": "text/css",
                "vendor/addon-fit.js": "application/javascript"}
THEME_ICONS = {"station": "📡", "hardware": "📻", "safety": "🚨", "access": "🔑", "features": "✨",
               "troubleshooting": "🔧", "updates": "🔄", "expert": "🔬"}
THEME_COLORS = {"station": "#2fd3c0", "hardware": "#5aa9ff", "safety": "#ff6b5e", "access": "#ffb340",
                "features": "#c084fc", "troubleshooting": "#4ade80", "updates": "#38bdf8", "expert": "#94a3b8"}
# style-src 'unsafe-inline' : xterm.js pose ses propres styles (grille du terminal) ; AUCUN script en ligne permis.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class WebConsole:
    def __init__(self, config: Path, *, port: int = DEFAULT_PORT,
                 terminal_factory: Callable[..., Terminal] = make_terminal,
                 console_factory: Callable[[Path], Console] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.config, self.port = config, port
        self.token: str | None = secrets.token_urlsafe(32)
        self.sessions: set[str] = set()
        self.terminal_factory, self.clock = terminal_factory, clock
        self.console_factory = console_factory or (lambda path: Console(path, ask=lambda _p: "", say=lambda _t: None))
        self.terminal: Terminal | None = None
        self.scrollback: deque[str] = deque()
        self.scroll_len = 0
        self.clients: set[web.WebSocketResponse] = set()
        self.idle = False                                # la console attend au menu : un menu peut être ouvert
        self.last_client = clock()
        self.stop = asyncio.Event()

    # ------------------------------------------------------------------ application

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.guard])
        app.router.add_get("/", self.index)
        app.router.add_get("/static/{name:.+}", self.static)
        app.router.add_get("/api/state", self.state)
        app.router.add_post("/api/open", self.open_menu)
        app.router.add_get("/ws", self.websocket)
        return app

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    @web.middleware
    async def guard(self, request: web.Request, handler):
        if request.host not in self.allowed_hosts():     # DNS rebinding : nom étranger qui pointe vers 127.0.0.1
            return web.Response(status=403, text="Adresse refusée.")
        response = await handler(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    def has_session(self, request: web.Request) -> bool:
        value = request.cookies.get(COOKIE, "")
        return any(hmac.compare_digest(value, s) for s in self.sessions)

    def same_origin(self, request: web.Request) -> bool:
        origin = request.headers.get("Origin", "")
        return origin in {f"http://{h}" for h in self.allowed_hosts()}

    async def index(self, request: web.Request) -> web.StreamResponse:
        token = request.query.get("t")
        if token is not None:
            if self.token is None or not hmac.compare_digest(token, self.token):
                return web.Response(status=403, content_type="text/html", text=EXPIRED_PAGE)
            self.token = None                             # usage unique
            session = secrets.token_urlsafe(32)
            self.sessions.add(session)
            response = web.HTTPFound("/")
            response.set_cookie(COOKIE, session, httponly=True, samesite="Strict", path="/")
            raise response
        if not self.has_session(request):
            return web.Response(status=403, content_type="text/html", text=EXPIRED_PAGE)
        return web.FileResponse(STATIC / "index.html", headers={"Content-Type": "text/html; charset=utf-8"})

    async def static(self, request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        if name not in STATIC_FILES:                      # liste fermée : rien d'autre n'est servi
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC / name, headers={"Content-Type": f"{STATIC_FILES[name]}; charset=utf-8"})

    # ------------------------------------------------------------------ état et menus

    def describe(self) -> dict:
        con = self.console_factory(self.config)
        t = con.t
        texts = load_help(t.lang)
        items = {key: (label, fn.__name__) for key, label, fn in con.items}
        themes = []
        for number, theme_id, methods in MENU_THEMES:
            entries = []
            for n in range(1, len(methods) + 1):
                key = f"{number}.{n}"
                label, method = items[key]
                help_ = texts.get(method, {})
                entries.append({"key": key, "label": label, "short": label.split(" (", 1)[0],
                                "role": help_.get("role", ""), "when": help_.get("quand", ""),
                                "changes": help_.get("modifie", ""), "admin": bool(help_.get("admin"))})
            themes.append({"number": number, "id": theme_id, "title": t(f"theme.{theme_id}"),
                           "summary": t(f"theme.{theme_id}.desc"), "icon": THEME_ICONS.get(theme_id, "•"),
                           "color": THEME_COLORS.get(theme_id, "#94a3b8"), "items": entries})
        status = con._gateway_status() if con.config.exists() else None
        rig = status.rig if status is not None and isinstance(status.rig, dict) else {}
        ptt = status.ptt if status is not None and isinstance(status.ptt, dict) else {}
        levels = rig.get("levels") if isinstance(rig.get("levels"), dict) else {}
        release = con.offered(con.update_state())
        return {"version": __version__, "lang": t.lang, "configured": con.config.exists(),
                "running": bool(con.config.exists() and con.station_running()),
                "rig": {"connected": bool(rig.get("connected")), "frequency_hz": rig.get("frequency_hz"),
                        "mode": rig.get("mode"), "strength_db": rig.get("strength_db"), "vd": levels.get("VD_METER")},
                "ptt": ptt.get("state") or "RX", "update": release.version if release is not None else None,
                "idle": self.idle and self.terminal is not None and self.terminal.alive,
                "assistant": menu_number("assistant"), "ui": {k: t(k) for k in UI_KEYS}, "themes": themes}

    async def state(self, request: web.Request) -> web.StreamResponse:
        if not self.has_session(request):
            raise web.HTTPForbidden()
        return web.json_response(await asyncio.to_thread(self.describe))

    async def open_menu(self, request: web.Request) -> web.StreamResponse:
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        try:
            key = str((await request.json()).get("key", ""))
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest()
        valid = {"0"} | {f"{n}.{i}" for n, _, ms in MENU_THEMES for i in range(1, len(ms) + 1)}
        if key not in valid:
            raise web.HTTPBadRequest()
        self.ensure_terminal()
        if not self.idle:                                 # un menu est en cours : ne jamais taper dans ses questions
            return web.json_response({"ok": False, "busy": True}, status=409)
        self.idle = False
        self.terminal.write(key + "\r")
        return web.json_response({"ok": True})

    # ------------------------------------------------------------------ terminal

    def ensure_terminal(self) -> None:
        if self.terminal is not None and self.terminal.alive:
            return
        env = dict(os.environ, TRX_CONSOLE_WEB="1", TERM="xterm-256color", COLORTERM="truecolor")
        cmd = [sys.executable, "-m", "trxstation.console", "--texte", "--config", str(self.config)]
        self.idle = False
        self.terminal = self.terminal_factory(cmd, env, self.on_output, self.on_exit)
        self.terminal.start(asyncio.get_running_loop())

    def on_output(self, text: str) -> None:
        if IDLE_MARK in text:
            self.idle = True
            text = text.replace(IDLE_MARK, "")
        if not text:
            return
        self.scrollback.append(text)
        self.scroll_len += len(text)
        while self.scroll_len > SCROLLBACK_CHARS and len(self.scrollback) > 1:
            self.scroll_len -= len(self.scrollback.popleft())
        for ws in list(self.clients):
            asyncio.ensure_future(self._send(ws, {"type": "output", "data": text}))

    def on_exit(self) -> None:
        self.idle = False
        self.on_output("\r\n[TRX Console terminée : actualiser la page pour la relancer]\r\n")

    async def _send(self, ws: web.WebSocketResponse, message: dict) -> None:
        try:
            await ws.send_str(json.dumps(message))
        except (ConnectionError, RuntimeError):
            self.clients.discard(ws)

    async def websocket(self, request: web.Request) -> web.StreamResponse:
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024)
        await ws.prepare(request)
        self.ensure_terminal()
        self.clients.add(ws)
        await self._send(ws, {"type": "output", "data": "".join(self.scrollback)})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if data.get("type") == "input" and isinstance(data.get("data"), str) and self.terminal is not None:
                    self.idle = False                     # quelqu'un tape : la console n'attend plus au menu
                    self.terminal.write(data["data"][:4096])
                elif data.get("type") == "resize" and self.terminal is not None:
                    rows, cols = data.get("rows"), data.get("cols")
                    if isinstance(rows, int) and isinstance(cols, int) and 5 <= rows <= 300 and 20 <= cols <= 500:
                        self.terminal.resize(rows, cols)
        finally:
            self.clients.discard(ws)
            self.last_client = self.clock()
        return ws

    async def watchdog(self) -> None:
        while not self.stop.is_set():
            await asyncio.sleep(30)
            if not self.clients and self.clock() - self.last_client > IDLE_EXIT_S:
                self.stop.set()

    # ------------------------------------------------------------------ lancement

    async def serve(self, *, open_browser: bool = True, announce: Callable[[str], None] = print,
                    fixed_port: bool = False) -> None:
        """fixed_port (raccourci « Console de la station », étape 230) : le tunnel SSH du PC vise CE port ; un autre
        port ne mènerait nulle part. L'adresse est aussi écrite sur une ligne `URL_MARK` lue par le lanceur."""
        from ..asyncio_noise import install_quiet_handler
        install_quiet_handler(asyncio.get_running_loop())   # Windows : page fermée brutalement = bruit, pas une panne
        runner = web.AppRunner(self.app(), access_log=None)
        await runner.setup()
        site = None
        for port in range(self.port, self.port + (1 if fixed_port else 20)):    # port occupé : le suivant
            try:
                site = web.TCPSite(runner, "127.0.0.1", port)
                await site.start()
                self.port = port
                break
            except OSError:
                site = None
        if site is None and fixed_port:
            announce(PORT_TAKEN.format(port=self.port))
            return
        if site is None:
            announce("Aucun port libre entre {} et {} : console web non lancée.".format(self.port, self.port + 19))
            return
        url = f"http://127.0.0.1:{self.port}/?t={self.token}"
        announce(UI_START.format(url=url, port=self.port))
        if fixed_port:
            announce(f"{URL_MARK} {url}")
        if open_browser and not os.environ.get("SSH_CONNECTION"):
            try:
                webbrowser.open(url)
            except Exception:
                pass
        watchdog = asyncio.create_task(self.watchdog())
        try:
            await self.stop.wait()
        finally:
            watchdog.cancel()
            if self.terminal is not None:
                self.terminal.close()
            await runner.cleanup()


UI_KEYS = ("web.title", "web.search", "web.expand", "web.collapse", "web.language", "web.open", "web.busy",
           "web.running", "web.stopped", "web.not_configured", "web.tx", "web.rx", "web.update", "web.role",
           "web.when", "web.changes", "web.admin", "web.terminal", "web.hide", "web.show", "web.click_open",
           "web.tap_open", "web.no_rig", "web.first_use")

UI_START = ("\nConsole web de la station : {url}\n"
            "  Adresse à usage unique, à ouvrir sur CETTE machine (navigateur ouvert tout seul s'il y en a un).\n"
            "  Depuis un autre PC : ssh -L {port}:127.0.0.1:{port} <compte>@<station>, puis cette adresse.\n"
            "  Ctrl+C pour arrêter ; arrêt seul après 30 minutes sans page ouverte.\n")

EXPIRED_PAGE = ("<!doctype html><meta charset=utf-8><title>TRX Console</title>"
                "<p style='font-family:sans-serif;margin:2em'>Lien expiré ou déjà utilisé. Relancer "
                "<code>trx-console --web</code> sur la station et ouvrir la nouvelle adresse.</p>")


URL_MARK = "TRX-CONSOLE-URL"
PORT_TAKEN = ("\nLa console web est déjà ouverte sur cette station (port {port} pris) : ferme l'autre fenêtre « Console "
              "de la station », ou attends 30 minutes qu'elle s'arrête seule.\n")


def run(config: Path, port: int = DEFAULT_PORT, *, fixed_port: bool = False) -> int:
    try:
        asyncio.run(WebConsole(config, port=port).serve(fixed_port=fixed_port))
    except KeyboardInterrupt:
        pass
    return 0
