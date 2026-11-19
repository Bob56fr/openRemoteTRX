# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Indicateur de niveau (dBFS) : attaque instantanée, retombée lente, pour un affichage stable."""
from __future__ import annotations

import time
from collections.abc import Callable

from .pcm import FLOOR_DB, rms_dbfs


class LevelMeter:
    def __init__(self, release_db_per_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.release, self._clock = release_db_per_s, clock
        self._level, self._last = FLOOR_DB, None

    def update(self, pcm: bytes, offset_db: float = 0.0) -> float:
        """`offset_db` : gain pas encore appliqué à `pcm` (le niveau peut alors dépasser 0 dBFS : saturation)."""
        now = self._clock()
        instant = rms_dbfs(pcm)
        if instant > FLOOR_DB:
            instant += offset_db
        decayed = self._level if self._last is None else self._level - self.release * (now - self._last)
        self._level = max(instant, decayed, FLOOR_DB)
        self._last = now
        return self._level

    @property
    def value(self) -> float:
        return self._level

    def reset(self) -> None:
        self._level, self._last = FLOOR_DB, None
