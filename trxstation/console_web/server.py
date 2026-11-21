# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Serveur de la console web : `trx-console --web` (cette machine) ou `trx-console --reseau` (réseau, étape 233).

Sécurité (cahier § 2 et § 5 ter, décisions de l'utilisateur du 2026-11-17) :
  * mode local : 127.0.0.1 seulement, jeton à usage unique dans l'adresse ouverte, échangé contre un cookie de
    session ; en-tête Host vérifié (pas de « DNS rebinding ») ; arrêt après 30 minutes sans page ouverte ;
  * mode réseau : HTTPS avec le certificat de la station, adresses privées / VPN seulement, connexion avec un compte
    OPÉRATEUR marqué `admin` (relu dans station.toml à chaque connexion), UNE session à la fois (une nouvelle connexion
    ferme l'ancienne et son terminal : jamais de sudo hérité), fermée après `idle_min` sans action et 8 h au plus,
    5 échecs par adresse = blocage 15 minutes, alerte ntfy à chaque connexion ;
  * dans les deux : Origin vérifié pour toute action et pour le terminal ; cookie HttpOnly, SameSite=Strict ; le mot de
    passe sudo ne fait que traverser le terminal (jamais gardé).
La page ne fait que ce que fait TRX Console, qui ne peut jamais déclencher d'émission.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import os
import secrets
import ssl
import sys
import time
import webbrowser
from collections import deque
from collections.abc import Callable
from pathlib import Path

from aiohttp import WSMsgType, web

from .. import __version__
from ..packaging import python_executable
from ..console import MENU_THEMES, Console, load_help, menu_level, menu_number
from ..i18n import LANGS, LEVELS, NAMES, load_lang, load_level, prefs_path, save_lang, save_level
from ..errors import codes
from ..errors.emit import emit_event
from .flow import Flow
from .terminal import IDLE_MARK, Terminal, make_terminal

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765
COOKIE = "trx_console"
IDLE_EXIT_S = 30 * 60              # plus aucune page ouverte depuis 30 min : le serveur s'arrête
SCROLLBACK_CHARS = 200_000         # sortie du terminal rejouée à une page qui se (re)connecte
STATIC = Path(__file__).with_name("static")
NET_SESSION_MAX_S = 8 * 3600       # réseau : session fermée après 8 h, même active
FAIL_LIMIT, FAIL_WINDOW_S, BLOCK_S = 5, 15 * 60, 15 * 60     # 5 échecs en 15 min = adresse bloquée 15 min
GLOBAL_FAIL_LIMIT = 30             # échecs toutes adresses confondues en 15 min : connexions suspendues 15 min
STATIC_FILES = {"app.js": "application/javascript", "app.css": "text/css", "login.js": "application/javascript",
                "vendor/xterm.js": "application/javascript", "vendor/xterm.css": "text/css",
                "vendor/addon-fit.js": "application/javascript", "flow.js": "application/javascript",
                "dash.js": "application/javascript"}
THEME_ICONS = {"station": "📡", "hardware": "📻", "safety": "🚨", "access": "🔑", "features": "✨",
               "troubleshooting": "🔧", "updates": "🔄", "expert": "🔬"}
THEME_COLORS = {"station": "#2fd3c0", "hardware": "#5aa9ff", "safety": "#ff6b5e", "access": "#ffb340",
                "features": "#c084fc", "troubleshooting": "#4ade80", "updates": "#38bdf8", "expert": "#94a3b8"}
# Menus qui dessinent tout l'écran (tableau de bord, éditeur de texte) : toujours dans le terminal (étape 235)
# Menus qui ne s'ouvrent qu'au terminal intégré : plus aucun depuis l'étape 238 (lot W3c). Le tableau de bord (1.3)
# est dessiné par la page elle-même (DASHBOARD) ; station.toml (8.1) se modifie dans un champ de la page.
TERMINAL_MENUS: frozenset[str] = frozenset()
DASHBOARD = "monitor"
MAX_EDIT = 512 * 1024                            # station.toml modifiée dans la page : taille maximale
DASH_LOG = 100                                   # lignes du journal du tableau de bord envoyées à la page
# style-src 'unsafe-inline' : xterm.js pose ses propres styles (grille du terminal) ; AUCUN script en ligne permis.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class WebConsole:
    def __init__(self, config: Path, *, port: int = DEFAULT_PORT,
                 terminal_factory: Callable[..., Terminal] = make_terminal,
                 console_factory: Callable[[Path], Console] | None = None,
                 clock: Callable[[], float] = time.monotonic, network: bool = False, idle_s: float = 30 * 60,
                 notify: Callable[..., object] | None = None):
        self.config, self.port, self.network, self.idle_s = config, port, network, idle_s
        self.token: str | None = None if network else secrets.token_urlsafe(32)
        self.sessions: set[str] = set()
        self.session: dict | None = None                 # réseau : la session ouverte (une seule à la fois)
        self.failures: dict[str, deque[float]] = {}
        self.all_failures: deque[float] = deque()
        self.blocked: dict[str, float] = {}
        self.notify = notify or (lambda *a, **k: None)
        self.terminal_factory, self.clock = terminal_factory, clock
        # Langue et niveau du compte (menu 0, mêmes préférences que la console texte de la page)
        self.console_factory = console_factory or (lambda path: Console(
            path, ask=lambda _p: "", say=lambda _t: None, lang=load_lang(prefs_path()),
            level=load_level(prefs_path(), path.exists())))
        self.terminal: Terminal | None = None
        self.scrollback: deque[str] = deque()
        self.scroll_len = 0
        self.clients: set[web.WebSocketResponse] = set()
        self.idle = False                                # la console attend au menu : un menu peut être ouvert
        self.last_client = clock()
        self.stop = asyncio.Event()
        self.flow: Flow | None = None                    # menu ouvert en formulaires (étape 235)
        self.flow_factory: Callable[..., Flow] = Flow
        self.sudo_password: str | None = None            # mot de passe sudo de la session, en mémoire seulement
        self.sudo_pending: str | None = None
        self.dash_source = None                          # tableau de bord natif (étape 238) : lecteur du bus d'état
        self.dash_log = None

    # ------------------------------------------------------------------ application

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.guard])
        app.router.add_get("/", self.index)
        app.router.add_get("/static/{name:.+}", self.static)
        app.router.add_get("/api/state", self.state)
        app.router.add_post("/api/open", self.open_menu)
        app.router.add_post("/api/level", self.set_level)
        app.router.add_post("/api/lang", self.set_lang)
        app.router.add_get("/api/dashboard", self.dashboard)
        app.router.add_post("/api/stop_tx", self.stop_tx)
        app.router.add_get("/ws", self.websocket)
        if self.network:
            app.router.add_post("/api/login", self.login)
            app.router.add_get("/api/login", self.login_texts)
            app.router.add_post("/api/logout", self.logout)
        return app

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def host_ok(self, request: web.Request) -> bool:
        if self.network:                                  # adresse de la station telle que l'appareil la connaît
            return request.host.endswith(f":{self.port}")
        return request.host in self.allowed_hosts()       # DNS rebinding : nom étranger qui pointe vers 127.0.0.1

    @web.middleware
    async def guard(self, request: web.Request, handler):
        if not self.host_ok(request) or (self.network and not private_source(request.remote)):
            return web.Response(status=403, text="Adresse refusée.")
        response = await handler(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    def has_session(self, request: web.Request) -> bool:
        value = request.cookies.get(COOKIE, "")
        if self.network:
            return self.session is not None and bool(value) and hmac.compare_digest(value, self.session["id"]) \
                and not self.session_expired()
        return any(hmac.compare_digest(value, s) for s in self.sessions)

    def same_origin(self, request: web.Request) -> bool:
        origin = request.headers.get("Origin", "")
        if self.network:
            return origin == f"https://{request.host}"
        return origin in {f"http://{h}" for h in self.allowed_hosts()}

    def touch(self) -> None:
        """Action de l'utilisateur (menu ouvert, touche tapée) : la session reste ouverte."""
        if self.session is not None:
            self.session["last"] = self.clock()

    def session_expired(self) -> bool:
        s, now = self.session, self.clock()
        return s is None or now - s["last"] > self.idle_s or now - s["created"] > NET_SESSION_MAX_S

    def close_session(self, reason: str) -> None:
        """Session fermée : terminal (et donc le sudo qu'il retenait) fermé, pages prévenues."""
        if self.session is None:
            return
        log.info("TRX Console sur le réseau : session de %s fermée (%s)", self.session["account"], reason)
        self.session = None
        if self.terminal is not None:
            self.terminal.close()
        self.terminal, self.idle = None, False
        self.stop_flow()
        self.flow = None
        self.sudo_password = self.sudo_pending = None
        self.scrollback.clear()
        self.scroll_len = 0
        for ws in list(self.clients):
            asyncio.ensure_future(self._send(ws, {"type": "expired"}))
            asyncio.ensure_future(ws.close())

    # ------------------------------------------------------------------ connexion (réseau)

    def _blocked_for(self, source: str) -> float:
        now = self.clock()
        until = max(self.blocked.get(source, 0.0), self.blocked.get("*", 0.0))
        return max(0.0, until - now)

    def _failed(self, source: str) -> None:
        now = self.clock()
        for key, queue in ((source, self.failures.setdefault(source, deque())), ("*", self.all_failures)):
            queue.append(now)
            while queue and now - queue[0] > FAIL_WINDOW_S:
                queue.popleft()
            limit = FAIL_LIMIT if key != "*" else GLOBAL_FAIL_LIMIT
            if len(queue) >= limit and self.blocked.get(key, 0.0) <= now:
                self.blocked[key] = now + BLOCK_S
                queue.clear()
                self.notify(codes.ORT_4023, source="toutes" if key == "*" else key, minutes=BLOCK_S // 60)

    def _check_account(self, login: str, password: str) -> str | None:
        """Compte opérateur ADMINISTRATEUR, actif, non expiré, mot de passe juste : son identifiant, sinon None.
        station.toml est relu à chaque connexion : un compte retiré ou désactivé ne se connecte plus."""
        from datetime import date

        from .. import config as cfgmod
        from ..passwords import verify_password
        try:
            cfg = cfgmod.load(self.config)
        except (OSError, cfgmod.ConfigError):
            verify_password(password, _dummy_hash())
            return None
        client = next((c for c in cfg.clients if c.id.casefold() == login.strip().casefold()), None)   # majuscules indifférentes
        usable = (client is not None and cfg.remote_console.enabled is True and client.admin is True
                  and client.role == "operator" and client.enabled is True and bool(client.password_hash)
                  and not client.expired(date.today()))
        ok = verify_password(password, client.password_hash if usable else _dummy_hash())   # même durée dans tous les cas
        return client.id if usable and ok else None

    async def login(self, request: web.Request) -> web.StreamResponse:
        if not self.same_origin(request):
            raise web.HTTPForbidden()
        source = request.remote or "?"
        wait = self._blocked_for(source)
        if wait > 0:
            return web.json_response({"ok": False, "blocked_min": -(-int(wait) // 60)}, status=429)
        try:
            data = await request.json()
            login, password = str(data.get("id", ""))[:64], str(data.get("password", ""))[:256]
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest()
        account = await asyncio.to_thread(self._check_account, login, password)
        if account is None:
            self._failed(source)
            emit_event(codes.ORT_4021, logger=log, compte=login[:32], source=source,
                       detail="TRX Console sur le réseau : identifiant, mot de passe ou droit d'administration refusé")
            return web.json_response({"ok": False}, status=401)
        self.close_session("nouvelle connexion")
        self.failures.pop(source, None)
        now = self.clock()
        self.session = {"id": secrets.token_urlsafe(32), "account": account, "created": now, "last": now,
                        "source": source}
        self.notify(codes.ORT_4022, compte=account, source=source)
        response = web.json_response({"ok": True})
        response.set_cookie(COOKIE, self.session["id"], httponly=True, secure=True, samesite="Strict", path="/")
        return response

    async def login_texts(self, request: web.Request) -> web.StreamResponse:
        t = self.console_factory(self.config).t
        return web.json_response({"lang": t.lang, "ui": {k: t(k) for k in LOGIN_KEYS}})

    async def logout(self, request: web.Request) -> web.StreamResponse:
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        self.close_session("déconnexion")
        response = web.json_response({"ok": True})
        response.del_cookie(COOKIE, path="/")
        return response

    async def index(self, request: web.Request) -> web.StreamResponse:
        if self.network:
            page = "index.html" if self.has_session(request) else "login.html"
            return web.FileResponse(STATIC / page, headers={"Content-Type": "text/html; charset=utf-8"})
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
                                "mode": ("dashboard" if method == DASHBOARD else
                                         "terminal" if method in TERMINAL_MENUS else "form"),
                                "level": menu_level(method), "visible": con.visible(method),
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
        return {"webapp": self.webapp(con), "version": __version__, "lang": t.lang, "configured": con.config.exists(),
                "running": bool(con.config.exists() and con.station_running()),
                "rig": {"connected": bool(rig.get("connected")), "frequency_hz": rig.get("frequency_hz"),
                        "mode": rig.get("mode"), "strength_db": rig.get("strength_db"), "vd": levels.get("VD_METER")},
                "ptt": ptt.get("state") or "RX", "update": release.version if release is not None else None,
                "idle": self.idle and self.terminal is not None and self.terminal.alive,
                "assistant": menu_number("assistant"), "update_menu": menu_number("update"), "ui": {k: t(k) for k in UI_KEYS}, "themes": themes,
                "level": con.level, "langs": [[code, NAMES[code]] for code in LANGS],
                "network": self.network}

    @staticmethod
    def webapp(con: Console) -> dict | None:
        """Lien vers l'application web de la station (page de pilotage), sous l'état de la station (étape 343) : le
        schéma et le port seulement ; la page y met le NOM par lequel la console a été ouverte (l'adresse qui marche
        depuis cet appareil). `local` : passerelle sur 127.0.0.1, injoignable d'un autre appareil."""
        if not con.config.exists():
            return None
        from .. import config as cfgmod
        try:
            cfg, _ = cfgmod.load_unchecked(con.config)
        except (cfgmod.ConfigError, OSError):
            return None
        n = cfg.network
        return {"scheme": "https" if n.tls_cert else "http", "port": n.gateway_port,
                "local": n.gateway_bind in ("", "127.0.0.1", "localhost", "::1")}

    async def state(self, request: web.Request) -> web.StreamResponse:
        if not self.has_session(request):
            raise web.HTTPForbidden()
        return web.json_response(await asyncio.to_thread(self.describe))

    async def set_level(self, request: web.Request) -> web.StreamResponse:
        """Niveau d'affichage (étape 234) : le même fichier de préférences que le menu 0 de la console."""
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        try:
            level = str((await request.json()).get("level", ""))
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest()
        if level not in LEVELS:
            raise web.HTTPBadRequest()
        self.touch()
        return web.json_response({"ok": save_level(prefs_path(), level)})

    async def set_lang(self, request: web.Request) -> web.StreamResponse:
        """Langue choisie dans la page (étape 235) : le même fichier de préférences que le menu 0. La console du
        terminal, si elle attend à son menu, est relancée dans la nouvelle langue."""
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        try:
            lang = str((await request.json()).get("lang", ""))
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest()
        if lang not in LANGS:
            raise web.HTTPBadRequest()
        self.touch()
        saved = save_lang(prefs_path(), lang)
        if self.terminal is not None and self.terminal.alive and self.idle:
            self.terminal.close()
            self.terminal, self.idle = None, False
            self.scrollback.clear()
            self.scroll_len = 0
            self.broadcast({"type": "output", "data": "\x1bc"})          # écran du terminal effacé
        return web.json_response({"ok": saved})

    async def open_menu(self, request: web.Request) -> web.StreamResponse:
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        try:
            data = await request.json()
            key, in_terminal = str(data.get("key", "")), data.get("terminal") is True
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest()
        methods = {"0": "language"} | {f"{n}.{i}": m for n, _, ms in MENU_THEMES for i, m in enumerate(ms, 1)}
        if key not in methods:
            raise web.HTTPBadRequest()
        if methods[key] == DASHBOARD and not in_terminal:  # lecture seule : jamais en conflit avec un menu en cours
            self.touch()
            return web.json_response({"ok": True, "mode": "dashboard"})
        if self.flow is not None and self.flow.alive:     # un seul menu à la fois, formulaires ou terminal
            return web.json_response({"ok": False, "busy": "flow"}, status=409)
        if in_terminal or methods[key] in TERMINAL_MENUS:
            self.ensure_terminal()
            if not self.idle:                             # un menu est en cours : ne jamais taper dans ses questions
                return web.json_response({"ok": False, "busy": True}, status=409)
            self.idle = False
            self.touch()
            self.terminal.write(key + "\r")
            return web.json_response({"ok": True, "mode": "terminal", "full": methods[key] == "monitor"})
        if self.terminal is not None and self.terminal.alive and not self.idle:
            return web.json_response({"ok": False, "busy": True}, status=409)
        self.touch()
        await self.start_flow(key)
        return web.json_response({"ok": True, "mode": "form"})

    # ------------------------------------------------------------------ tableau de bord natif (étape 238)

    def dash_snapshot(self, net_detail: bool) -> dict:
        """Mêmes panneaux et même journal que trx-monitor (`monitor/model.py`), en données pour la page."""
        from .. import config as cfgmod
        from ..monitor.model import EventLog, build_panels
        from ..monitor.source import StatusSource
        if self.dash_source is None:
            try:
                cfg = cfgmod.load(self.config)
            except (cfgmod.ConfigError, OSError) as exc:
                problems = getattr(exc, "problems", None) or [str(exc)]
                return {"ok": False, "error": "; ".join(problems)[:500]}
            self.dash_source = StatusSource(cfg.supervisor.status_path, cfg.supervisor.state_dir,
                                            cfg.supervisor.stale_after_s)
            self.dash_log = EventLog()
        snap = self.dash_source.poll()
        t = self.dash_translator()                       # langue de la page (lot L3), relue à chaque appel
        self.dash_log.t = t
        self.dash_log.observe(snap)
        ptt = snap.status.ptt.get("state") if snap.status is not None and isinstance(snap.status.ptt, dict) else None
        panels = [{"key": p.key, "title": p.title, "rows": [[r.label, r.text, r.level] for r in p.rows]}
                  for p in build_panels(snap, net_detail, t=t)]
        for p in panels:                                  # la console elle-même : qui la tient en ce moment
            if p["key"] == "connexion":
                p["rows"].append(self.console_row(t))
        return {"ok": True, "fresh": snap.gateway_fresh, "ptt": ptt or "", "safe_mode": snap.safe_mode or "",
                "panels": panels,
                "log": self.dash_log.entries()[-DASH_LOG:]}          # [{text, level}] : rouge = level bad

    def console_row(self, t) -> list:
        """Ligne « Console » : session réseau (compte, adresse, durée) ou navigateur de la station (mode local)."""
        s = self.session
        if self.network and s is not None:
            since = int(self.clock() - s["created"])
            duration = f"{since // 3600:02d}:{since % 3600 // 60:02d}"
            return [t("label.console"), t("console.network", account=s["account"], source=s.get("source", "?"),
                                          duration=duration), "info"]
        return [t("label.console"), t("console.local"), "info"]

    @staticmethod
    def dash_translator():
        from ..i18n import Translator
        return Translator(load_lang(prefs_path()), "monitor")

    async def dashboard(self, request: web.Request) -> web.StreamResponse:
        """Lecture seule, rafraîchie par la page. Ne prolonge pas la session : seule une action le fait."""
        if not self.has_session(request):
            raise web.HTTPForbidden()
        return web.json_response(await asyncio.to_thread(self.dash_snapshot, request.query.get("net") == "1"))

    async def stop_tx(self, request: web.Request) -> web.StreamResponse:
        """STOP TX du tableau de bord : « T 0 » direct à rigctld (`monitor/actions.py`), comme la touche s de
        trx-monitor. Ne peut que COUPER une émission, jamais en déclencher une."""
        if not self.has_session(request) or not self.same_origin(request):
            raise web.HTTPForbidden()
        from .. import config as cfgmod
        from ..monitor.actions import stop_tx
        self.touch()
        try:
            cfg = cfgmod.load(self.config)
        except (cfgmod.ConfigError, OSError):
            return web.json_response({"ok": False, "message": "station.toml illisible : STOP TX impossible d'ici "
                                                              "(bouton STOP de la page de pilotage)"})
        t = self.dash_translator()
        ok, message = await asyncio.to_thread(stop_tx, cfg, t)
        if self.dash_log is not None:
            self.dash_log.record(t("app.stop_line", message=message), "bad")   # toujours bien visible
        return web.json_response({"ok": ok, "message": message})

    # ------------------------------------------------------------------ menus en formulaires (étape 235)

    async def start_flow(self, key: str) -> None:
        con = self.console_factory(self.config)
        label = con.t("menu.language") if key == "0" else next(lbl for k, lbl, _ in con.items if k == key)
        self.flow = self.flow_factory(key, label, self.config, self.on_flow_event, network=self.network)
        self.broadcast({"type": "flow_start", "flow": self.flow.summary()})
        await self.flow.start()

    def stop_flow(self) -> None:
        if self.flow is not None:
            self.flow.stop()

    def on_flow_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "sudo":
            if event.get("retry") == 0 and self.sudo_password is not None and self.flow is not None:
                self.flow.password(self.sudo_password)     # déjà donné dans cette session : pas redemandé
                return
            self.sudo_password = None
        elif kind == "sudo_ok":
            if self.sudo_pending is not None:
                self.sudo_password, self.sudo_pending = self.sudo_pending, None
            return
        elif kind == "sudo_bad":
            self.sudo_password = self.sudo_pending = None
        if kind in ("sudo", "sudo_bad") and self.flow is not None:
            self.flow.events.append(event)               # rejoué à une page qui se reconnecte (aucun secret)
        self.broadcast({"type": "flow", "event": event})

    def broadcast(self, message: dict) -> None:
        for ws in list(self.clients):
            asyncio.ensure_future(self._send(ws, message))

    def flow_message(self, data: dict) -> None:
        flow = self.flow
        if flow is None:
            return
        kind = data.get("type")
        if kind == "flow_stop":
            self.touch()
            flow.stop()
            return
        if not flow.alive:
            return
        if kind == "flow_answer" and isinstance(data.get("value"), str):
            self.touch()
            label = data.get("label") if isinstance(data.get("label"), str) else ""
            flow.answer(data["value"][:4096], label[:200])
        elif kind == "flow_edit":                          # éditeur de station.toml dans la page (8.1)
            self.touch()
            text = data.get("text")
            flow.edit(text[:MAX_EDIT] if isinstance(text, str) and data.get("cancel") is not True else None)
        elif kind == "flow_stdin" and isinstance(data.get("data"), str):
            self.touch()
            flow.stdin(data["data"][:4096])
        elif kind == "flow_password" and isinstance(data.get("value"), str):
            self.touch()
            self.sudo_pending = data["value"][:256]
            flow.password(self.sudo_pending)
            flow.record({"type": "sudo_sent"})            # la question du mot de passe est close (jamais la valeur)

    # ------------------------------------------------------------------ terminal

    def ensure_terminal(self) -> None:
        if self.terminal is not None and self.terminal.alive:
            return
        env = dict(os.environ, TRX_CONSOLE_WEB="1", TERM="xterm-256color", COLORTERM="truecolor")
        cmd = [python_executable(windowed=False), "-m", "trxstation.console", "--texte", "--config", str(self.config)]
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
        self.on_output("\r\n[TRX Console terminée : actualiser la page pour la relancer en faisant F5 dans votre navigateur web]\r\n")

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
        if self.flow is not None:
            await self._send(ws, {"type": "flow_start", "flow": self.flow.summary()})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if str(data.get("type", "")).startswith("flow_"):
                    self.flow_message(data)
                elif data.get("type") == "input" and isinstance(data.get("data"), str) and self.terminal is not None:
                    self.idle = False                     # quelqu'un tape : la console n'attend plus au menu
                    self.touch()
                    self.terminal.write(data["data"][:4096])
                elif data.get("type") == "resize" and self.terminal is not None:
                    rows, cols = data.get("rows"), data.get("cols")
                    if isinstance(rows, int) and isinstance(cols, int) and 5 <= rows <= 300 and 20 <= cols <= 500:
                        self.terminal.resize(rows, cols)
        finally:
            self.clients.discard(ws)
            self.last_client = self.clock()
        return ws

    async def watchdog(self, period_s: float = 30) -> None:
        while not self.stop.is_set():
            await asyncio.sleep(period_s)
            if self.network:                              # service permanent : seule la session se ferme
                if self.session is not None and self.session_expired():
                    self.close_session("inactivité")
            elif not self.clients and self.clock() - self.last_client > IDLE_EXIT_S:
                self.stop.set()

    # ------------------------------------------------------------------ lancement

    async def serve(self, *, open_browser: bool = True, announce: Callable[[str], None] = print,
                    bind: str = "127.0.0.1", ssl_context: ssl.SSLContext | None = None) -> bool:
        """Mode local : 127.0.0.1, port suivant si le sien est pris. Mode réseau : `bind` et `ssl_context` donnés par
        `run_network`, port fixe (celui que la page de pilotage annonce). Faux si la console n'a pas démarré."""
        from ..asyncio_noise import install_quiet_handler
        install_quiet_handler(asyncio.get_running_loop())   # Windows : page fermée brutalement = bruit, pas une panne
        runner = web.AppRunner(self.app(), access_log=None)
        await runner.setup()
        site = None
        for port in range(self.port, self.port + (1 if self.network else 20)):
            try:
                site = web.TCPSite(runner, bind, port, ssl_context=ssl_context)
                await site.start()
                self.port = port
                break
            except OSError:
                site = None
        if site is None:
            if self.network:
                emit_event(codes.ORT_4024, logger=log, raison=f"port {self.port} déjà pris sur {bind}")
            else:
                announce("Aucun port libre entre {} et {} : console web non lancée.".format(self.port, self.port + 19))
            await runner.cleanup()
            return False
        if self.network:
            log.info("TRX Console sur le réseau : https://%s:%d/", bind, self.port)
        else:
            url = f"http://127.0.0.1:{self.port}/?t={self.token}"
            announce(UI_START.format(url=url, port=self.port))
            if open_browser and not os.environ.get("SSH_CONNECTION"):
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
        if os.name == "posix":                              # arrêt du service (systemd) : terminal fermé proprement
            import signal
            for sig in (signal.SIGHUP, signal.SIGTERM):
                try:
                    asyncio.get_running_loop().add_signal_handler(sig, self.stop.set)
                except (NotImplementedError, RuntimeError, ValueError):
                    pass
        watchdog = asyncio.create_task(self.watchdog())
        try:
            await self.stop.wait()
        finally:
            watchdog.cancel()
            if self.terminal is not None:
                self.terminal.close()
            self.stop_flow()
            await runner.cleanup()
        return True


UI_KEYS = ("web.title", "web.search", "web.expand", "web.collapse", "web.language", "web.open", "web.busy",
           "web.running", "web.stopped", "web.not_configured", "web.tx", "web.rx", "web.update", "web.role",
           "web.when", "web.changes", "web.admin", "web.terminal", "web.hide", "web.show", "web.click_open",
           "web.tap_open", "web.no_rig", "web.first_use", "web.logout", "web.level", "level.basic", "level.normal",
           "level.expert", "level.basic.desc", "level.normal.desc", "level.expert.desc", "web.flow.close",
           "web.flow.stop", "web.flow.send", "web.flow.free", "web.flow.yes", "web.flow.no", "web.flow.continue",
           "web.flow.generate", "web.flow.confirm", "web.flow.cancel", "web.flow.keep", "web.flow.sudo",
           "web.flow.sudo_bad", "web.flow.input", "web.flow.done", "web.flow.running", "web.flow.terminal", "web.max",
           "web.flow.busy", "web.flow.tab", "web.version", "web.update_open", "web.dash.stop", "web.dash.net", "web.dash.close", "web.dash.stale",
           "web.dash.log", "web.edit.save", "web.edit.cancel", "web.edit.hint", "web.webapp", "web.webapp_open")

UI_START = ("\nConsole web de la station : {url}\n"
            "  Adresse à usage unique, à ouvrir sur CETTE machine (navigateur ouvert tout seul s'il y en a un).\n"
            "  Depuis un autre PC : ssh -L {port}:127.0.0.1:{port} <compte>@<station>, puis cette adresse.\n"
            "  Ctrl+C pour arrêter ; arrêt seul après 30 minutes sans page ouverte.\n")

EXPIRED_PAGE = ("<!doctype html><meta charset=utf-8><title>TRX Console</title>"
                "<p style='font-family:sans-serif;margin:2em'>Lien expiré ou déjà utilisé. Relancer "
                "<code>trx-console --web</code> sur la station et ouvrir la nouvelle adresse.</p>")


LOGIN_KEYS = ("web.login.title", "web.login.id", "web.login.password", "web.login.submit", "web.login.bad",
              "web.login.blocked", "web.login.note")


_DUMMY: list[str] = []


def _dummy_hash() -> str:
    """Empreinte d'un mot de passe au hasard : un compte inconnu coûte le même calcul qu'un vrai (pas d'indice)."""
    if not _DUMMY:
        from ..passwords import hash_password
        _DUMMY.append(hash_password(secrets.token_hex(16)))
    return _DUMMY[0]


def private_source(remote: str | None) -> bool:
    """Réseau local, VPN (dont 100.64.0.0/10 des VPN maillés) ou cette machine : jamais une adresse publique."""
    try:
        ip = ipaddress.ip_address((remote or "").split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    cgnat = ipaddress.ip_network("100.64.0.0/10")
    return ip.is_private or ip.is_loopback or ip.is_link_local or (ip.version == 4 and ip in cgnat)


def run(config: Path, port: int = DEFAULT_PORT) -> int:
    try:
        asyncio.run(WebConsole(config, port=port).serve())
    except KeyboardInterrupt:
        pass
    return 0


def run_network(config: Path) -> int:
    """`trx-console --reseau` : service permanent (systemd sous Debian, superviseur sous Windows)."""
    from .. import config as cfgmod
    from ..logsetup import setup_logging
    from ..supervisor.notify import Notifier
    setup_logging("console-reseau")
    try:
        cfg = cfgmod.load(config)
    except (OSError, cfgmod.ConfigError) as exc:
        emit_event(codes.ORT_4024, logger=log, raison=f"configuration illisible ({exc})")
        return 2
    rc, net = cfg.remote_console, cfg.network
    if rc.enabled is not True:
        emit_event(codes.ORT_4024, logger=log, raison="[remote_console] enabled = false (menu 4.6)")
        return 2
    if not (net.tls_cert and net.tls_key):
        emit_event(codes.ORT_4024, logger=log, raison="pas de certificat ([network] tls_cert, tls_key : menu 4.4)")
        return 2
    try:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(net.tls_cert, net.tls_key)
    except (OSError, ssl.SSLError) as exc:
        emit_event(codes.ORT_4024, logger=log, raison=f"certificat illisible ({exc})")
        return 2
    notifier = Notifier(cfg.supervisor.notify_url, lang=cfg.supervisor.notify_lang, min_interval_s=0)
    console = WebConsole(config, port=rc.port, network=True, idle_s=rc.idle_min * 60,
                         notify=lambda code, **ctx: notifier.alert(code, key=str(ctx.get("source", "")), **ctx))
    try:
        started = asyncio.run(console.serve(bind=net.gateway_bind, ssl_context=context))
    except KeyboardInterrupt:
        started = True
    return 0 if started else 2
