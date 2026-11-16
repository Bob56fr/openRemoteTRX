# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Charge du module SDR : échelle de bridage graduée (docs/sdr-cahier-des-charges.md § 2.3, lot S1b-2).

La PASSERELLE juge sa propre qualité de service et envoie au module un niveau (action « load » du bus, jamais d'un
client). Le module applique aussi sa propre échelle quand il dépasse ses plafonds ([sdr] max_cpu_pct, max_mem_mb) ;
le niveau appliqué est le plus haut des deux.

Niveaux (chaque cran garde les précédents) :
  0 normal ;
  1 son du SDR coupé pour les clients (mesure de la passerelle elle-même) ;
  2 waterfall à la moitié de sa cadence ;
  3 waterfall à 1 ligne/s ;
  4 échantillonnage ramené à 2 MHz (s'il était plus large) ;
  5 module suspendu (sdr-core arrêté ; passerelle seulement).

Montée : un cran après HOLD_S de dépassement continu, puis un cran de plus par HOLD_S tant que ça dure.
Descente : un cran après GREEN_S « au vert » sans interruption (nettement sous les seuils), le compteur repart
à chaque cran (pas d'oscillation). Pur Python, horloge injectable.
"""
from __future__ import annotations

import time
from collections.abc import Callable

HOLD_S = 10.0
GREEN_S = 300.0
TOP = 5
LEVEL_TEXT = {0: "normal", 1: "son du SDR coupé", 2: "waterfall ralenti", 3: "waterfall à 1 ligne/s",
              4: "échantillonnage à 2 MHz", 5: "module suspendu"}


class Ladder:
    def __init__(self, top: int = TOP, *, hold_s: float = HOLD_S, green_s: float = GREEN_S,
                 clock: Callable[[], float] = time.monotonic):
        self.top, self.hold_s, self.green_s, self.clock = top, hold_s, green_s, clock
        self.level, self.reason = 0, ""
        self._over_since: float | None = None
        self._green_since: float | None = None

    def step(self, over: str, green: bool) -> bool:
        """Une mesure (over : premier dépassement en clair, vide sinon ; green : nettement sous les seuils).
        Vrai si le niveau vient de changer."""
        now = self.clock()
        if over:
            self._green_since = None
            if self._over_since is None:
                self._over_since = now
            if now - self._over_since >= self.hold_s and self.level < self.top:
                self.level, self.reason, self._over_since = self.level + 1, over, now
                return True
            return False
        self._over_since = None
        if not green or self.level == 0:
            self._green_since = None
            return False
        if self._green_since is None:
            self._green_since = now
        if now - self._green_since >= self.green_s:
            self.level, self._green_since = self.level - 1, now
            if self.level == 0:
                self.reason = ""
            return True
        return False


def waterfall_rate(rate: int, level: int) -> int:
    """Cadence du waterfall appliquée au niveau donné."""
    if level >= 3:
        return 1
    if level == 2:
        return max(1, rate // 2)
    return rate


def sample_rate(configured: int, level: int) -> int:
    """Échantillonnage appliqué au niveau donné (2 MHz au niveau 4, s'il était plus large)."""
    return min(configured, 2_000_000) if level >= 4 else configured
