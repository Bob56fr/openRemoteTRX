# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lignes reçues -> spots du cache, avec compteurs (reçus par minute, mal formés, filtrés...)."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

from .cache import Spot, SpotCache
from .clusterdx import WebSpot
from .feed import Source
from .parse import is_dx_line, parse_dx_line

SOURCE_WINDOW_S = 600.0        # fenêtre du débit affiché par flux (10 minutes : utile pour les flux lents comme rapides)


class Engine:
    def __init__(self, cache: SpotCache, *, clock: Callable[[], float] = time.monotonic,
                 on_spot: Callable[[Spot, bool], None] | None = None) -> None:
        self.cache = cache
        self.clock = clock
        self.on_spot = on_spot
        self.malformed = 0
        self.other_lines = 0
        self.last_spot_at: float | None = None
        self._recent: deque[float] = deque()
        self._by_source: dict[str, dict] = {}      # par flux : reçus, dernier spot, instants des 10 dernières minutes

    def _count(self, name: str, at: float) -> None:
        stats = self._by_source.setdefault(name, {"received": 0, "last_at": None, "recent": deque()})
        stats["received"] += 1
        stats["last_at"] = at if stats["last_at"] is None else max(stats["last_at"], at)
        stats["recent"].append(self.clock())

    def source_stats(self, name: str) -> dict:
        """Ce que ce flux a livré (avant filtrage) : total, 10 dernières minutes, âge du dernier spot."""
        stats = self._by_source.get(name)
        if stats is None:
            return {"received": 0, "last_10min": 0, "last_spot_age_s": None}
        limit = self.clock() - SOURCE_WINDOW_S
        while stats["recent"] and stats["recent"][0] < limit:
            stats["recent"].popleft()
        age = None if stats["last_at"] is None else round(max(0.0, self.clock() - stats["last_at"]), 1)
        return {"received": stats["received"], "last_10min": len(stats["recent"]), "last_spot_age_s": age}

    def handle_line(self, src: Source, line: str) -> None:
        if not is_dx_line(line):
            self.other_lines += 1
            return
        raw = parse_dx_line(line)
        if raw is None:
            self.malformed += 1
            return
        now = self.clock()
        self.last_spot_at = now
        self._recent.append(now)
        self._count(src.name, now)
        kind = "rbn" if (src.kind == "rbn" or raw.skimmer) else src.spot_kind
        result = self.cache.add(raw, source=src.name, kind=kind, now=now)
        if result is not None and self.on_spot is not None:
            self.on_spot(*result)

    def handle_web(self, src: Source, spots: list[WebSpot], bad: int) -> None:
        """Spots d'une source web (clusterdx.org) : âge exact fourni par la page."""
        self.malformed += bad
        now = self.clock()
        for ws in spots:
            if ws.age_s < 60.0:
                self.last_spot_at = now - ws.age_s
                self._recent.append(now)
            self._count(src.name, now - ws.age_s)              # âge réel du spot (page relevée toutes les minutes)
            result = self.cache.add(ws.raw, source=src.name, kind=src.spot_kind, now=now, age_s=ws.age_s)
            if result is not None and self.on_spot is not None:
                self.on_spot(*result)

    def spots_per_minute(self) -> int:
        limit = self.clock() - 60.0
        while self._recent and self._recent[0] < limit:
            self._recent.popleft()
        return len(self._recent)

    def last_spot_age(self) -> float | None:
        return None if self.last_spot_at is None else self.clock() - self.last_spot_at

    def counters(self) -> dict:
        c = self.cache.counters
        return {"received": c["received"], "per_minute": self.spots_per_minute(),
                "malformed": self.malformed, "filtered": c["filtered"], "duplicates": c["duplicates"],
                "cache": len(self.cache), "expired": c["expired"], "evicted": c["evicted"],
                "last_spot_age_s": None if self.last_spot_at is None else round(self.last_spot_age(), 1)}
