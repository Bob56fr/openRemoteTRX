"""Lignes reçues -> spots du cache, avec compteurs (reçus par minute, mal formés, filtrés...)."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

from .cache import Spot, SpotCache
from .clusterdx import WebSpot
from .feed import Source
from .parse import is_dx_line, parse_dx_line


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
