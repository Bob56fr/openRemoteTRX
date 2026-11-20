# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""openRemoteTRX-Autotest, mode B : le programme local SERT la page (la même que le mode A, `autotest/web/`) et lui
ouvre une petite API vers SON rigctld (docs/prequalif-web-cahier-des-charges.md § 2, § 8).

Pourquoi servir la page : une page publique qui appellerait 127.0.0.1 déclencherait la demande « accès au réseau
local » de Chrome, incompréhensible pour l'opérateur.

Protections (comme la page de la valise, `qualif/page/server.py`) : 127.0.0.1 SEULEMENT ; jeton à usage unique dans
l'adresse ouverte, échangé contre un cookie de session ; en-tête Host vérifié (DNS rebinding) ; Origin vérifié pour
toute requête de l'API ; CSP stricte ; fichiers servis en liste fermée ; commandes rigctld en liste fermée
(`rig.check_command`).

GARDE D'ÉMISSION DU PROGRAMME, indépendante de la page (§ 5) : dès qu'un « T 1 » est passé, « T 0 » est envoyé par
une connexion à part si l'émission dure plus de `MAX_TX_S`, si la page ne fait plus aucune requête pendant
`SILENCE_S`, à l'arrêt du programme et à la déconnexion. La page garde ses propres coupures (10 s, STOP, Échap…).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import time
from pathlib import Path

from aiohttp import web

from . import rig as rg

DEFAULT_PORT = 8767
COOKIE = "trx_autotest"
MAX_TX_S = 12.0          # la page coupe à 10 s ; le programme, au plus tard ici
SILENCE_S = 3.0          # pendant une émission, plus aucune requête de la page => « T 0 »
WATCH_S = 0.2
WEB_SUFFIXES = {".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".jpg": "image/jpeg",
                ".png": "image/png", ".svg": "image/svg+xml"}
CSP = ("default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "media-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
EXPIRED_PAGE = ("<!doctype html><meta charset=utf-8><title>Autotest</title>"
                "<p style='font-family:sans-serif;margin:2em'>Lien expiré ou déjà utilisé : relancez "
                "openRemoteTRX-Autotest.<br>Link expired or already used: start openRemoteTRX-Autotest again.</p>")
MODE_META = '<meta name="autotest-mode" content="hamlib">'


def default_web_dir() -> Path:
    """Page du mode A : dans le dépôt (`autotest/web`), ou copiée à côté du paquet (fabrication de l'EXE)."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "web", here.parents[1] / "autotest" / "web"):
        if (candidate / "index.html").is_file():
            return candidate
    return here.parents[1] / "autotest" / "web"


def page_for_mode_b(html: str) -> str:
    """index.html du mode A adapté : l'API locale permise (connect-src) et le mode annoncé à la page."""
    html = html.replace("connect-src 'none'", "connect-src 'self'")
    return html.replace("<title>", MODE_META + "\n<title>", 1)


class AutotestServer:
    def __init__(self, *, port: int = DEFAULT_PORT, web_dir: Path | None = None, hamlib_dir: str = "",
                 rigctld_factory=None, clock=time.monotonic) -> None:
        self.port, self.hamlib_dir, self.clock = port, hamlib_dir, clock
        self.web_dir = web_dir or default_web_dir()
        self.files = {p.name: WEB_SUFFIXES[p.suffix] for p in self.web_dir.iterdir()
                      if p.is_file() and p.suffix in WEB_SUFFIXES}
        self.token: str | None = secrets.token_urlsafe(32)
        self.session: str | None = None
        self.rig: rg.Rigctld | None = None
        self.rigctld_factory = rigctld_factory or (lambda settings: rg.Rigctld(settings, hamlib_dir=hamlib_dir))
        self.profile: dict = {}
        self.tx_since: float | None = None       # « T 1 » passé, pas encore de « T 0 »
        self.last_request = clock()
        self.pending = 0
        self.cuts: list[dict] = []               # coupures faites par la garde du programme
        self._models: list[dict] | None = None
        self._watch: asyncio.Task | None = None

    # ------------------------------------------------------------------ application

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.guard], client_max_size=64 * 1024)
        app.router.add_get("/", self.index)
        app.router.add_get("/api/info", self.info)
        app.router.add_get("/api/ports", self.ports)
        app.router.add_get("/api/models", self.models)
        app.router.add_post("/api/connect", self.connect)
        app.router.add_post("/api/cmd", self.cmd)
        app.router.add_post("/api/ptt_off", self.ptt_off_route)
        app.router.add_post("/api/disconnect", self.disconnect)
        app.router.add_get("/{name}", self.static)
        app.on_startup.append(self._start_watch)
        app.on_cleanup.append(self._cleanup)
        return app

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    @web.middleware
    async def guard(self, request: web.Request, handler):
        if request.host not in self.allowed_hosts():
            return web.Response(status=403, text="Adresse refusée.")
        api = request.path.startswith("/api/")
        if api:
            if not self.has_session(request) or not self.same_origin(request):
                return web.json_response({"erreur": "refuse"}, status=403)
            self.pending += 1
            self.last_request = self.clock()
        try:
            response = await handler(request)
        finally:
            if api:
                self.pending -= 1
                self.last_request = self.clock()
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    def has_session(self, request: web.Request) -> bool:
        value = request.cookies.get(COOKIE, "")
        return self.session is not None and bool(value) and hmac.compare_digest(value, self.session)

    def same_origin(self, request: web.Request) -> bool:
        origin = request.headers.get("Origin")
        if origin is None:                       # GET du même site : Chrome n'envoie pas toujours Origin
            return request.method == "GET" and request.headers.get("Sec-Fetch-Site", "same-origin") == "same-origin"
        return origin in {f"http://{h}" for h in self.allowed_hosts()}

    async def index(self, request: web.Request) -> web.StreamResponse:
        token = request.query.get("t")
        if token is not None:
            if self.token is None or not hmac.compare_digest(token, self.token):
                return web.Response(status=403, content_type="text/html", text=EXPIRED_PAGE)
            self.token = None                                   # usage unique
            self.session = secrets.token_urlsafe(32)            # une seule session
            keep = {k: v for k, v in request.query.items() if k == "lang" and v in ("fr", "en")}
            response = web.HTTPFound("/" + (f"?lang={keep['lang']}" if keep else ""))
            response.set_cookie(COOKIE, self.session, httponly=True, samesite="Strict", path="/")
            raise response
        if not self.has_session(request):
            return web.Response(status=403, content_type="text/html", text=EXPIRED_PAGE)
        html = page_for_mode_b((self.web_dir / "index.html").read_text(encoding="utf-8"))
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def static(self, request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        if name not in self.files or name == "index.html":
            raise web.HTTPNotFound()
        if not self.has_session(request):
            raise web.HTTPForbidden()
        kind = self.files[name]
        charset = "; charset=utf-8" if kind.startswith(("text/", "application/javascript")) else ""
        return web.FileResponse(self.web_dir / name, headers={"Content-Type": kind + charset})

    # ------------------------------------------------------------------ API

    async def info(self, request: web.Request) -> web.StreamResponse:
        from ..qualif.profile import hamlib_version
        version = await asyncio.to_thread(hamlib_version, self.hamlib_dir)
        return web.json_response({"mode": "hamlib", "hamlib": version, "connecte": self.rig is not None})

    async def ports(self, request: web.Request) -> web.StreamResponse:
        return web.json_response({"ports": await asyncio.to_thread(rg.serial_ports)})

    async def models(self, request: web.Request) -> web.StreamResponse:
        if self._models is None:
            self._models = await asyncio.to_thread(rg.rig_models, self.hamlib_dir)
        return web.json_response({"postes": self._models})

    async def _json(self, request: web.Request) -> dict:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise web.HTTPBadRequest()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()
        return data

    async def connect(self, request: web.Request) -> web.StreamResponse:
        data = await self._json(request)
        speed = data.get("vitesse")
        settings = rg.RigSettings(model=data.get("modele") if isinstance(data.get("modele"), int) else 0,
                                  port=str(data.get("port") or "").strip(),
                                  speed=speed if isinstance(speed, int) and speed else None)
        problems = settings.problems()
        if problems:
            return web.json_response({"ok": False, "erreur": "reglage", "detail": problems}, status=400)
        await self._close_rig()
        rig = self.rigctld_factory(settings)
        try:
            await rig.start()
        except rg.RigError as exc:
            return web.json_response({"ok": False, "erreur": exc.key, "detail": exc.detail})
        first = await rig.query("f")
        if first.get("rprt") != 0:
            await rig.stop()
            return web.json_response({"ok": False, "erreur": "silence", "detail": first.get("erreur") or first.get("rprt")})
        self.rig = rig
        self.profile = await asyncio.to_thread(rg.rig_profile, settings.model, self.hamlib_dir)
        return web.json_response({"ok": True, "profil": self.profile, "vitesse": settings.speed})

    async def cmd(self, request: web.Request) -> web.StreamResponse:
        data = await self._json(request)
        line = rg.check_command(data.get("c"))
        if line is None:
            return web.json_response({"erreur": "hors_liste"}, status=400)
        if self.rig is None:
            return web.json_response({"erreur": "non_connecte"}, status=409)
        if line == "T 1" and self.tx_since is None:
            self.tx_since = self.clock()         # garde armée AVANT l'ordre (un accusé perdu reste couvert)
        answer = await self.rig.query(line)
        if line == "T 0" and answer.get("rprt") == 0:
            self.tx_since = None
        return web.json_response(answer)

    async def ptt_off_route(self, request: web.Request) -> web.StreamResponse:
        return web.json_response({"rx": await self.ptt_off("page")})

    async def disconnect(self, request: web.Request) -> web.StreamResponse:
        await self._close_rig()
        return web.json_response({"ok": True})

    # ------------------------------------------------------------------ garde d'émission du programme

    async def ptt_off(self, reason: str) -> bool:
        if self.rig is None:
            return False
        rx = await self.rig.ptt_off()
        if rx:
            self.tx_since = None
        if reason not in ("page",):
            self.cuts.append({"raison": reason, "rx": rx})
        return rx

    async def check_tx(self) -> str | None:
        """Une passe de la garde : rend la raison d'une coupure faite, sinon None."""
        if self.tx_since is None or self.rig is None:
            return None
        now = self.clock()
        reason = None
        if now - self.tx_since > MAX_TX_S:
            reason = "duree_max"
        elif self.pending == 0 and now - self.last_request > SILENCE_S:
            reason = "page_muette"
        if reason:
            await self.ptt_off(reason)
        return reason

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(WATCH_S)
            try:
                await self.check_tx()
            except Exception:                    # noqa: BLE001 : la garde ne s'arrête jamais
                pass

    async def _start_watch(self, app: web.Application) -> None:
        self._watch = asyncio.ensure_future(self._watch_loop())

    async def _close_rig(self) -> None:
        rig, self.rig = self.rig, None
        if rig is None:
            return
        await rig.ptt_off()                      # toujours, même sans émission connue : ne peut que couper
        self.tx_since = None
        await rig.stop()

    async def _cleanup(self, app: web.Application) -> None:
        if self._watch is not None:
            self._watch.cancel()
        await self._close_rig()

