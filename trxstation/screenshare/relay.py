# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Transport de l'écran partagé vers le relais (docs/protocole-ecran.md § 4) : POST JSON sur `/v1/screen/<route>`.

Le partage et la visualisation sont des boucles SYNCHRONES (terminal) : `ScreenRelay.call()` attend la réponse d'une
requête aiohttp lancée dans une boucle asyncio à part (un fil). aiohttp essaie IPv6 et IPv4 (étape 208 : urllib ne
rebascule pas). `RelayRefused` (code HTTP, motif) quand le relais refuse ; `RelayUnavailable` quand il ne répond pas.
"""
from __future__ import annotations

import asyncio
import json
import threading
from urllib.parse import urlsplit

from ..httpread import read_capped

ROUTES = ("open", "put", "get", "close")
MAX_REPLY = 1024 * 1024
TIMEOUT_S = 20.0


class RelayUnavailable(Exception):
    """Relais injoignable ou réponse illisible."""


class RelayRefused(Exception):
    def __init__(self, status: int, reason: str, message: str = "", reply: dict | None = None) -> None:
        super().__init__(f"{status} {reason} {message}".strip())
        self.status, self.reason, self.reply = status, reason, reply or {}


def endpoint(relay_url: str, route: str) -> str:
    if route not in ROUTES:
        raise ValueError(f"route inconnue : {route}")
    parts = urlsplit(relay_url)
    if parts.scheme not in ("https", "http") or not parts.netloc:
        raise ValueError(f"adresse du relais invalide : {relay_url}")
    return relay_url.rstrip("/") + "/v1/screen/" + route


class ScreenRelay:
    def __init__(self, relay_url: str, *, version: str = "", timeout: float = TIMEOUT_S) -> None:
        endpoint(relay_url, "get")                   # vérifie l'adresse tout de suite
        self.relay_url = relay_url
        self.timeout = timeout
        self.user_agent = f"openRemoteTRX-screen/{version or '0'}"
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="screen-relay", daemon=True)
        self._thread.start()
        self._session = None

    async def _post(self, route: str, fields: dict) -> tuple[int, dict]:
        import aiohttp                               # module de la station (paquet [station])
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout),
                                                  headers={"User-Agent": self.user_agent})
        body = json.dumps(fields, separators=(",", ":")).encode("ascii")
        async with self._session.post(endpoint(self.relay_url, route), data=body,
                                      headers={"Content-Type": "application/json"}, allow_redirects=False) as resp:
            raw = await read_capped(resp.content, MAX_REPLY)
            status = resp.status
        if len(raw) > MAX_REPLY:
            raise RelayUnavailable("réponse trop grande")
        try:
            reply = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RelayUnavailable(f"réponse illisible (HTTP {status})") from exc
        if not isinstance(reply, dict):
            raise RelayUnavailable(f"réponse inattendue (HTTP {status})")
        return status, reply

    def call(self, route: str, fields: dict) -> dict:
        future = asyncio.run_coroutine_threadsafe(self._post(route, fields), self._loop)
        try:
            status, reply = future.result(self.timeout + 5)
        except RelayUnavailable:
            raise
        except Exception as exc:                     # réseau, DNS, TLS, délai
            future.cancel()
            raise RelayUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if status != 200:
            raise RelayRefused(status, str(reply.get("error", "?")), str(reply.get("message", "")), reply)
        return reply

    def close(self) -> None:
        async def _close() -> None:
            if self._session is not None:
                await self._session.close()
                self._session = None
        if self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(_close(), self._loop).result(5)
            except Exception:                        # fermeture : rien à faire de plus
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(5)
