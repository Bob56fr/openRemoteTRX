# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Gigue du canal `cw` et rejeu adaptatif (cahier § 5.3).

Le bail d'un paquet vaut l'heure d'envoi du client (il garantit l'état de la clé jusqu'à « maintenant ») :
transit apparent = arrivée (station) - bail (client). Les deux horloges ont un écart inconnu mais constant :
la gigue d'un paquet = son transit - le plus petit transit vu dans la séquence. Le rejeu adaptatif d'une
séquence = p95 de la gigue des séquences précédentes + 50 ms, dans les bornes ; jamais changé en cours de séquence.
"""
from __future__ import annotations

from collections import deque

import numpy as np

MARGIN_MS = 50.0
HISTORY = 400                        # gigues gardées (toutes séquences confondues)


def p95(values: list[float] | deque[float]) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), 95)) if values else 0.0


class JitterMeter:
    def __init__(self) -> None:
        self.history: deque[float] = deque(maxlen=HISTORY)
        self._transits: list[float] = []

    def start_sequence(self) -> None:
        self._commit()

    def packet(self, arrival_ms: float, lease_ms: float) -> None:
        self._transits.append(arrival_ms - lease_ms)

    def sequence_jitter(self) -> list[float]:
        if not self._transits:
            return []
        low = min(self._transits)
        return [t - low for t in self._transits]

    def _commit(self) -> None:
        self.history.extend(self.sequence_jitter())
        self._transits = []

    def end_sequence(self) -> dict[str, float]:
        jit = self.sequence_jitter()
        stats = {"jitter_mean_ms": float(np.mean(jit)) if jit else 0.0, "jitter_p95_ms": p95(jit),
                 "jitter_max_ms": max(jit) if jit else 0.0, "packets": float(len(jit))}
        self._commit()
        return stats

    def adaptive_delay(self, low_ms: float, high_ms: float, fallback_ms: float) -> float:
        if not self.history:
            return min(max(fallback_ms, low_ms), high_ms)
        return min(max(p95(self.history) + MARGIN_MS, low_ms), high_ms)
