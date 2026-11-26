# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Tonalité CW recréée par la station (cahier § 4), à l'échantillon près, sans minuterie.

Le temps est compté en ÉCHANTILLONS depuis la création (position absolue) : un front demandé pour l'échantillon n
commence exactement à n, quelle que soit la découpe des blocs. Sinusoïde de phase continue (calculée depuis la
position absolue), enveloppe en cosinus surélevé de `edge_ms` ; un front qui arrive pendant un autre repart du
niveau atteint (jamais de saut de niveau, donc pas de clic).
"""
from __future__ import annotations

import math

import numpy as np

from ..gateway.audio.pcm import SAMPLE_RATE

TONE_MIN_HZ = 300.0
TONE_MAX_HZ = 1200.0
EDGE_MIN_MS = 3.0
EDGE_MAX_MS = 8.0
DEFAULT_LEVEL = 0.5                  # crête de la tonalité (-6 dBFS) ; le niveau d'émission se dose au poste


class ToneRenderer:
    def __init__(self, tone_hz: float = 700.0, edge_ms: float = 5.0, level: float = DEFAULT_LEVEL,
                 sample_rate: int = SAMPLE_RATE) -> None:
        if not TONE_MIN_HZ <= tone_hz <= TONE_MAX_HZ:
            raise ValueError("tonalité hors limites")
        if not EDGE_MIN_MS <= edge_ms <= EDGE_MAX_MS:
            raise ValueError("durée de front hors limites")
        if not 0.0 < level <= 1.0:
            raise ValueError("niveau hors limites")
        self.fs = sample_rate
        self.tone_hz = tone_hz
        self.level = level
        self.edge_samples = max(1, round(edge_ms * sample_rate / 1000))
        self.pos = 0                                 # prochain échantillon à produire
        self._from = 0.0                             # front en cours : niveau de départ, d'arrivée, début
        self._to = 0.0
        self._start = -self.edge_samples              # aucun front en cours au départ

    # --- enveloppe -------------------------------------------------------------------------------------------
    def _env(self, idx: np.ndarray) -> np.ndarray:
        frac = np.clip((idx - self._start) / self.edge_samples, 0.0, 1.0)
        return self._from + (self._to - self._from) * 0.5 * (1.0 - np.cos(math.pi * frac))

    def level_at(self, sample: int) -> float:
        return float(self._env(np.array([sample], dtype=np.float64))[0])

    @property
    def target_on(self) -> bool:
        return self._to > 0.0

    @property
    def silent(self) -> bool:
        """Tonalité nulle à la position courante et aucun front montant en cours."""
        return self._to == 0.0 and self.pos >= self._start + self.edge_samples

    def set_key(self, sample: int, on: bool) -> None:
        """Front à l'échantillon `sample` (jamais dans le passé : ramené à la position courante)."""
        sample = max(sample, self.pos)
        to = 1.0 if on else 0.0
        if to == self._to:
            return
        self._from = self.level_at(sample)
        self._to = to
        self._start = sample

    # --- rendu -------------------------------------------------------------------------------------------------
    def render(self, n: int) -> np.ndarray:
        """`n` échantillons flottants (-level..level) à partir de la position courante, sans changer de front."""
        idx = np.arange(self.pos, self.pos + n, dtype=np.float64)
        env = self._env(idx)
        out = self.level * env * np.sin(2.0 * math.pi * self.tone_hz * idx / self.fs) if env.any() \
            else np.zeros(n, dtype=np.float64)
        self.pos += n
        if self.pos >= self._start + self.edge_samples:
            self._from = self._to                    # front terminé : niveau figé (calcul plus court)
        return out


def to_pcm16(samples: np.ndarray) -> bytes:
    """Flottants -1..1 -> s16 petit-boutiste mono (format de la sortie d'émission)."""
    return np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
