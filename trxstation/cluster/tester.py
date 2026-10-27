# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Test d'une source avant enregistrement : connexion, identification, au moins un spot en 60 s.

Compte rendu : OK, serveur injoignable, indicatif refusé, mot de passe refusé
(ou demandé), aucun spot reçu, page changée. Mêmes envois qu'en service
(indicatif et mot de passe seulement), une seule connexion.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from . import clusterdx, telnet
from .feed import Source
from .parse import is_dx_line

CHECK_TIMEOUT_S = 60.0

OK = "ok"
NO_SPOT = "no_spot"
FORMAT = "format"
TEXTS = {
    OK: "OK",
    telnet.UNREACHABLE: "serveur injoignable",
    telnet.CALL_REFUSED: "indicatif refusé",
    telnet.PASSWORD_REFUSED: "mot de passe refusé",
    telnet.PASSWORD_REQUIRED: "le serveur demande un mot de passe",
    telnet.OK_CLOSED: "connexion fermée par le serveur avant le premier spot",
    telnet.IDLE: "aucun spot reçu",
    NO_SPOT: "aucun spot reçu en 60 s",
    FORMAT: "page illisible (le site a changé ?)",
}


@dataclass
class SourceReport:
    code: str
    detail: str = ""
    spots: int = 0
    cluster_type: str | None = None
    sample: str = ""

    @property
    def ok(self) -> bool:
        return self.code == OK

    @property
    def message(self) -> str:
        text = TEXTS.get(self.code, self.code)
        if self.ok:
            kind = f", logiciel {self.cluster_type}" if self.cluster_type and self.cluster_type != "web" else ""
            text = f"OK ({self.spots} spot(s) reçu(s){kind})"
        return f"{text} — {self.detail}" if self.detail and not self.ok else text


async def check_source(src: Source, call: str, password: str | None = None, *, timeout: float = CHECK_TIMEOUT_S,
                      session=telnet.run_session,
                      fetch: Callable[[str], tuple[str, datetime]] = clusterdx.fetch) -> SourceReport:
    if src.kind == "web":
        try:
            page, now = await asyncio.to_thread(fetch, src.url)
            spots, _ = clusterdx.parse_page(page, now)
        except clusterdx.FormatError as exc:
            return SourceReport(FORMAT, str(exc)[:160])
        except Exception as exc:
            return SourceReport(telnet.UNREACHABLE, (str(exc) or type(exc).__name__)[:160])
        if not spots:
            return SourceReport(NO_SPOT, "la page ne contient aucun spot")
        first = spots[0].raw
        return SourceReport(OK, spots=len(spots), cluster_type="web",
                          sample=f"{first.freq_khz:.1f} {first.dx} de {first.spotter}")

    stop = asyncio.Event()
    seen: list[str] = []

    def on_line(line: str) -> None:
        if is_dx_line(line):
            seen.append(line)
            stop.set()                                       # un spot suffit

    async def deadline() -> None:
        await asyncio.sleep(timeout)
        stop.set()

    timer = asyncio.ensure_future(deadline())
    try:
        res = await session(src.host, src.port, src.call or call, password=password, on_line=on_line, stop=stop)
    except ValueError as exc:                                # indicatif ou mot de passe invalide
        return SourceReport(telnet.CALL_REFUSED, str(exc))
    finally:
        timer.cancel()
    if seen:
        return SourceReport(OK, spots=len(seen), cluster_type=res.cluster_type, sample=seen[0][:80])
    if res.code == telnet.STOPPED:
        return SourceReport(NO_SPOT, cluster_type=res.cluster_type)
    return SourceReport(res.code, res.detail, cluster_type=res.cluster_type)
