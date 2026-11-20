# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Requêtes signées de la station vers le serveur de diffusion (docs/protocole-diffusion.md § 3), par aiohttp.

aiohttp et non urllib : bascule IPv4 / IPv6 (piège de l'étape 208). Réponses = données non fiables.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

import aiohttp

from ..httpread import read_capped
from . import protocol as p

TIMEOUT_S = 10.0


class MetaClient:
    def __init__(self, base_url: str, station: str, key: bytes, clock: Callable[[], float] = time.time) -> None:
        self.base_url = base_url.rstrip("/")
        self.station = p.check_station(station)
        self.key = key
        self.clock = clock
        self._last_ts = 0
        self._session: aiohttp.ClientSession | None = None

    def _ts(self) -> int:
        self._last_ts = p.next_ts_ms(int(self.clock() * 1000), self._last_ts)
        return self._last_ts

    async def _post(self, action: str, body: bytes) -> tuple[int | None, Any]:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT_S))
        path = p.api_path(self.station, action)
        try:
            async with self._session.post(self.base_url + path, data=body,
                                          headers=p.signed_headers(self.key, path, body)) as rep:
                raw = await read_capped(rep.content, p.MAX_BODY)
                try:
                    obj = json.loads(raw) if raw else None
                except ValueError:
                    obj = None
                return rep.status, obj
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return None, None

    async def send_meta(self, access: str, meta: dict[str, Any],
                        silence: str | None = None) -> tuple[int | None, dict[str, int] | None]:
        """Envoie les métadonnées ; renvoie (statut HTTP ou None, nombre d'auditeurs vérifié ou None)."""
        status, obj = await self._post("meta", p.meta_body(self.station, self._ts(), access, meta, silence))
        return status, (p.parse_meta_reply(obj) if status == 200 else None)

    async def send_listener(self, user: str, password: str) -> int | None:
        status, _ = await self._post("auditeur", p.listener_body(self.station, self._ts(), user, password))
        return status

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
