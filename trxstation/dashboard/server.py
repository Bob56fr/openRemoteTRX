# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Serveur web en LECTURE SEULE : la page, /api/state, /api/history. Aucune commande vers la station.

Pas de clé d'accès (décision de l'utilisateur du 2026-11-24 : rien de vital, la clé gênait les opérateurs) : la page
est ouverte à qui joint les adresses écoutées (127.0.0.1, réseau local, VPN de la box). L'en-tête Host reste vérifié
(liste fermée) pour qu'une page web malveillante ne puisse pas lire l'état par « DNS rebinding » au travers d'un
navigateur de la maison ; seuls trois fichiers sont servis.
"""
from __future__ import annotations

import ipaddress
import ssl
from pathlib import Path
from typing import Callable

from aiohttp import web

STATIC = Path(__file__).parent / "static"
STATIC_FILES = {"index.html": "text/html", "app.css": "text/css", "app.js": "text/javascript"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
                               "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def is_loopback(remote: str | None) -> bool:
    try:
        return remote is not None and ipaddress.ip_address(remote.split("%")[0]).is_loopback
    except ValueError:
        return False


def allowed_hosts(listen: list[str], port: int, extra: list[str]) -> set[str]:
    names = {"localhost", "127.0.0.1", "[::1]", *listen, *extra}
    hosts = set()
    for n in names:
        n = f"[{n}]" if ":" in n and not n.startswith("[") else n
        hosts |= {n.lower(), f"{n}:{port}".lower()}
    return hosts


def make_app(get_state: Callable[[], dict], get_history: Callable[[], dict], *, hosts: set[str]) -> web.Application:

    @web.middleware
    async def guard(request: web.Request, handler):
        if request.host.lower() not in hosts:
            return web.Response(status=421, text="Hôte non reconnu")
        resp = await handler(request)
        resp.headers.update(SECURITY_HEADERS)
        return resp

    async def static(request: web.Request) -> web.StreamResponse:
        name = request.match_info.get("name") or "index.html"
        if name not in STATIC_FILES:                  # liste fermée : rien d'autre n'est servi
            raise web.HTTPNotFound()
        return web.Response(body=(STATIC / name).read_bytes(), content_type=STATIC_FILES[name], charset="utf-8")

    async def state(_: web.Request) -> web.Response:
        return web.json_response(get_state())

    async def history(_: web.Request) -> web.Response:
        return web.json_response(get_history())

    app = web.Application(middlewares=[guard])
    app.router.add_get("/", static)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/history", history)
    app.router.add_get("/{name}", static)
    return app


def ssl_context(cert: str, key: str) -> ssl.SSLContext | None:
    if not cert:
        return None
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key or None)
    return ctx
