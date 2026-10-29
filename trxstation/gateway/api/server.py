# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Signalisation HTTP (aiohttp) : POST /offer {client_id, password, sdp, type} -> réponse SDP ; GET /config ; page web.

Le mot de passe protège la commande de l'émetteur. Sur autre chose que la boucle locale, l'API doit être servie en
HTTPS (tls_cert/tls_key, ou proxy HTTPS devant) : voir docs/acces-distant.md.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Iterable
from pathlib import Path

from aiohttp import web

from .auth import DEFAULT_PROXIES, ClientRegistry, client_source
from .protocol import PROTOCOL_VERSION
from .webrtc import PeerLimitError, PeerManager

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
WEB_FILES = {"/": ("index.html", "text/html"), "/client.js": ("client.js", "text/javascript"),
             "/client.css": ("client.css", "text/css"), "/ui.js": ("ui.js", "text/javascript"),
             "/waterfall.js": ("waterfall.js", "text/javascript"), "/layout.js": ("layout.js", "text/javascript"), "/theme.js": ("theme.js", "text/javascript"), "/hfscope.js": ("hfscope.js", "text/javascript"), "/spots.js": ("spots.js", "text/javascript"), "/voice.js": ("voice.js", "text/javascript"), "/selcall.js": ("selcall.js", "text/javascript"), "/scrambler.js": ("scrambler.js", "text/javascript"), "/splash.webp": ("splash.webp", "image/webp")}
SECURITY_HEADERS = {
    # aucune ressource externe, aucun script ni style en ligne : une page injectée ne pourrait pas lire le jeton
    "Content-Security-Policy": "default-src 'self'; media-src 'self' blob:; connect-src 'self'; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
}


def make_app(registry: ClientRegistry, manager: PeerManager, *, web_client: bool = True,
             trusted_proxies: Iterable[str] = DEFAULT_PROXIES, ice_servers: Iterable[str] = (),
             rig_audio: Iterable[str] = ()) -> web.Application:
    proxies, ice, rig = tuple(trusted_proxies), list(ice_servers), list(rig_audio)
    hashing = asyncio.Semaphore(2)          # au plus 2 vérifications de mot de passe (~100 ms de calcul) en parallèle

    async def offer(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "bad_request"}, status=400)
        if not isinstance(data, dict):
            return web.json_response({"error": "bad_request"}, status=400)
        secret = data.get("password", data.get("token"))                       # « token » : ancien nom, toujours accepté
        fields = [data.get("client_id"), secret, data.get("sdp"), data.get("type")]
        if not all(isinstance(f, str) for f in fields):
            return web.json_response({"error": "bad_request"}, status=400)
        client_id, secret, sdp, sdp_type = fields
        source = client_source(request.remote, request.headers.get("X-Forwarded-For"), proxies)
        async with hashing:
            # scrypt est CPU-bound : hors de la boucle, pour ne jamais retarder la surveillance de l'émission
            allowed = await asyncio.to_thread(registry.verify, client_id, secret, source)
        if not allowed:
            log.warning("connexion refusée pour « %s » depuis %s", client_id[:32], source[:64])
            return web.json_response({"error": "unauthorized"}, status=401)    # même réponse quelle que soit la cause
        try:
            return web.json_response(await manager.handle_offer(client_id, sdp, sdp_type))
        except PeerLimitError:
            return web.json_response({"error": "busy"}, status=503)
        except Exception:
            log.exception("offre de %s en erreur", client_id)
            return web.json_response({"error": "server_error"}, status=500)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})                                # n'expose aucun état

    async def config(_: web.Request) -> web.Response:
        return web.json_response({"protocol": PROTOCOL_VERSION, "ice_servers": ice, "rig_audio": rig}, headers=SECURITY_HEADERS)

    def static_handler(filename: str, content_type: str):
        body = (STATIC_DIR / filename).read_bytes()

        async def handler(_: web.Request) -> web.Response:
            return web.Response(body=body, content_type=content_type, charset="utf-8", headers=SECURITY_HEADERS)
        return handler

    app = web.Application(client_max_size=64 * 1024)
    if web_client:
        for url, (filename, content_type) in WEB_FILES.items():
            app.router.add_get(url, static_handler(filename, content_type))
    app.router.add_get("/config", config)
    app.router.add_post("/offer", offer)
    app.router.add_get("/health", health)
    return app


async def start_server(app: web.Application, host: str, port: int,
                       ssl_context: ssl.SSLContext | None = None) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, host, port, ssl_context=ssl_context).start()
    except BaseException:
        await runner.cleanup()                     # port refusé : rien ne doit rester ouvert à moitié
        raise
    return runner
