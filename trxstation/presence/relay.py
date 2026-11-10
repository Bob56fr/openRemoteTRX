# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Transport vers le relais (docs/protocole-presence.md § 3) : POST JSON signé, réponse lue à 1 Mo au plus.

`post(route, champs)` renvoie (code HTTP, réponse JSON) ; `RelayUnavailable` si le relais ne répond pas (réseau,
DNS, TLS, réponse illisible). Les tests remplacent cet objet par un faux relais (devtools/fake_presence_relay.py).
"""
from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit

from .wire import Counter, build_request

MAX_REPLY = 1024 * 1024
TIMEOUT_S = 20.0


class RelayUnavailable(Exception):
    """Relais injoignable ou réponse illisible : la station réessaie plus tard, sans alerte."""


class HttpRelay:
    def __init__(self, base_url: str, identity, *, counter: Counter | None = None, version: str = "") -> None:
        parts = urlsplit(base_url)
        self.base = f"{parts.scheme}://{parts.netloc}"
        self.prefix = parts.path.rstrip("/")
        self.identity = identity
        self.counter = counter or Counter()
        self.user_agent = f"openRemoteTRX-presence/{version or '0'}"
        self._session = None

    async def _http(self):
        if self._session is None:
            import aiohttp                           # module de la station (paquet [station])
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
                                                  headers={"User-Agent": self.user_agent})
        return self._session

    async def post(self, route: str, fields: dict) -> tuple[int, dict]:
        path = f"{self.prefix}/v1/{route}"
        body, headers = build_request(self.identity, path, fields, t=int(time.time()), n=self.counter.next())
        try:
            session = await self._http()
            async with session.post(self.base + path, data=body, headers=headers, allow_redirects=False) as resp:
                raw = await resp.content.read(MAX_REPLY + 1)
                status = resp.status
        except asyncio.CancelledError:
            raise
        except Exception as exc:                      # réseau, DNS, TLS, délai : jamais fatal
            raise RelayUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if len(raw) > MAX_REPLY:
            raise RelayUnavailable("réponse trop grande")
        try:
            reply = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RelayUnavailable(f"réponse illisible (HTTP {status})") from exc
        if not isinstance(reply, dict):
            raise RelayUnavailable(f"réponse inattendue (HTTP {status})")
        return status, reply

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
