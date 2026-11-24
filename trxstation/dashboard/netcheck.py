# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Accès à Internet : ouverture d'une connexion TCP vers quelques adresses connues, sans rien envoyer.

Internet est « joignable » si au moins une adresse répond ; la latence est celle de la plus rapide.
"""
from __future__ import annotations

import asyncio
import time


def parse_target(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"adresse Internet à tester invalide : {text!r} (attendu hôte:port)")
    return host.strip("[]"), int(port)


async def probe_one(host: str, port: int, timeout: float) -> float | None:
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    elapsed = (time.monotonic() - start) * 1000
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return elapsed


async def probe(targets: list[tuple[str, int]], timeout: float = 3.0) -> dict:
    results = await asyncio.gather(*(probe_one(h, p, timeout) for h, p in targets))
    ok = [r for r in results if r is not None]
    return {"up": bool(ok), "ms": min(ok) if ok else None, "at": time.time()}


class InternetWatch:
    """Sonde périodique ; `last` garde le dernier résultat (None avant la première mesure)."""

    def __init__(self, targets: list[str], every_s: float = 30.0, timeout_s: float = 3.0):
        self.targets = [parse_target(t) for t in targets]
        self.every_s, self.timeout_s = every_s, timeout_s
        self.last: dict | None = None

    async def run(self) -> None:
        while True:
            self.last = await probe(self.targets, self.timeout_s)
            await asyncio.sleep(self.every_s)
