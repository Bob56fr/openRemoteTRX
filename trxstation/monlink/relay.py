# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Transport vers le relais du monitoring (docs/protocole-monlink.md § 3 et § 4) : POST JSON signé.

`call(route, champs)` renvoie la réponse JSON d'un succès ; `RelayRefused` (code HTTP, motif) si le relais refuse ;
`RelayUnavailable` s'il ne répond pas (réseau, DNS, TLS, réponse illisible). Une coupure de connexion est réessayée
UNE fois après 2 s (étape 208 : la route IPv6 vers OVH perdait ~40 % des connexions) ; aiohttp essaie IPv6 et IPv4
(« happy eyeballs »), contrairement à urllib. Les tests remplacent cet objet par devtools/fake_monlink_relay.py.
"""
from __future__ import annotations

import asyncio
import json
import time

from ..presence.wire import Counter
from . import wire

MAX_REPLY = 1024 * 1024
TIMEOUT_S = 30.0
RETRY_DELAY_S = 2.0


class RelayUnavailable(Exception):
    """Relais injoignable ou réponse illisible : la station réessaie au cycle suivant."""


class RelayRefused(Exception):
    def __init__(self, status: int, reason: str, message: str = "", reply: dict | None = None) -> None:
        super().__init__(f"{status} {reason} {message}".strip())
        self.status, self.reason, self.reply = status, reason, reply or {}


def check(status: int, reply: dict) -> dict:
    if status == 200:
        return reply
    raise RelayRefused(status, str(reply.get("error", "?")), str(reply.get("message", "")), reply)


class HttpRelay:
    def __init__(self, base_url: str, identity, *, counter: Counter | None = None, version: str = "") -> None:
        self.prefix = wire.base_prefix(base_url)
        self.origin = base_url.rstrip("/")[:len(base_url.rstrip("/")) - len(self.prefix)]
        self.identity = identity
        self.counter = counter or Counter()
        self.user_agent = f"openRemoteTRX-monlink/{version or '0'}"
        self._session = None

    async def _http(self):
        if self._session is None:
            import aiohttp                           # module de la station (paquet [station])
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
                                                  headers={"User-Agent": self.user_agent})
        return self._session

    async def _post_once(self, route: str, fields: dict) -> tuple[int, dict]:
        path, body, headers = wire.build_request(self.identity, route, fields, t=int(time.time()),
                                                 n=self.counter.next(), prefix=self.prefix)
        session = await self._http()
        async with session.post(self.origin + path, data=body, headers=headers, allow_redirects=False) as resp:
            raw = await resp.content.read(MAX_REPLY + 1)
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

    async def call(self, route: str, fields: dict) -> dict:
        for attempt in (1, 2):
            try:
                return check(*await self._post_once(route, fields))
            except (asyncio.CancelledError, RelayRefused, RelayUnavailable):
                raise
            except Exception as exc:                 # réseau, DNS, TLS, délai : un nouvel essai, puis abandon
                if attempt == 2:
                    raise RelayUnavailable(f"{type(exc).__name__}: {exc}") from exc
                await asyncio.sleep(RETRY_DELAY_S)
        raise RelayUnavailable("inaccessible")       # jamais atteint

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
