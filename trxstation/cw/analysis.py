# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Analyse du son CW produit (lot CW-0) : fronts retrouvés DANS LE SON, durées, clics, largeur occupée.

Enveloppe = module du signal analytique (une démodulation par moyenne glissante décalait les fronts de 3 à 5
échantillons selon la phase de la sinusoïde) ; un front = passage à 50 % de la crête, interpolé entre deux
échantillons (précision mesurée : 0,04 échantillon).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def envelope(audio: np.ndarray) -> np.ndarray:
    """Module du signal analytique (transformée de Hilbert par FFT) : enveloppe exacte d'une tonalité modulée
    bien plus lentement que sa fréquence, sans retard ni dépendance à la phase de la sinusoïde."""
    n = audio.size
    if n == 0:
        return np.zeros(0)
    h = np.zeros(n)
    h[0] = 1.0
    h[1:(n + 1) // 2] = 2.0
    if n % 2 == 0:
        h[n // 2] = 1.0
    return np.abs(np.fft.ifft(np.fft.fft(audio) * h))


def detect_edges(audio: np.ndarray, fs: int, tone_hz: float, level: float) -> list[tuple[float, bool]]:
    """(instant en échantillons, clé fermée) de chaque passage à 50 % de `level`."""
    env = envelope(audio) - level / 2.0
    above = env > 0
    idx = np.nonzero(above[1:] != above[:-1])[0]
    out: list[tuple[float, bool]] = []
    for i in idx:
        a, b = env[i], env[i + 1]
        frac = a / (a - b) if a != b else 0.0
        out.append((i + frac, bool(above[i + 1])))
    return out


@dataclass
class TimingReport:
    edges_expected: int
    edges_found: int
    errors_ms: list[float]                       # écart de chaque front, ancré sur le premier
    mark_errors_ms: list[float]                  # écart de durée de chaque élément (tonalité)

    @property
    def p95_ms(self) -> float:
        return float(np.percentile(np.abs(self.errors_ms), 95)) if self.errors_ms else math.inf

    @property
    def max_ms(self) -> float:
        return float(np.max(np.abs(self.errors_ms))) if self.errors_ms else math.inf

    @property
    def complete(self) -> bool:
        return self.edges_expected == self.edges_found


def compare(expected: list[tuple[float, bool]], found: list[tuple[float, bool]], fs: int) -> TimingReport:
    """Fronts attendus (ts ms) contre fronts retrouvés dans le son (échantillons), d'une même séquence."""
    errors: list[float] = []
    marks: list[float] = []
    if found and expected and len(found) == len(expected):
        t0 = found[0][0] * 1000.0 / fs
        e0 = expected[0][0]
        for (ts, d1), (s, d2) in zip(expected, found):
            errors.append((s * 1000.0 / fs - t0) - (ts - e0) if d1 == d2 else math.inf)
        for i in range(0, len(expected) - 1, 2):
            want = expected[i + 1][0] - expected[i][0]
            got = (found[i + 1][0] - found[i][0]) * 1000.0 / fs
            marks.append(got - want)
    return TimingReport(len(expected), len(found), errors, marks)


def max_step(audio: np.ndarray) -> float:
    """Plus grand saut entre deux échantillons voisins (un clic = un saut bien plus grand que la sinusoïde)."""
    return float(np.max(np.abs(np.diff(audio)))) if audio.size > 1 else 0.0


def sine_step(level: float, tone_hz: float, fs: int) -> float:
    """Saut maximal d'une sinusoïde pure de crête `level`."""
    return 2.0 * level * math.sin(math.pi * tone_hz / fs)


def out_of_band_db(audio: np.ndarray, fs: int, tone_hz: float, half_width_hz: float) -> float:
    """Énergie hors de tone ± half_width, en dB sous l'énergie totale (plus négatif = plus propre)."""
    spec = np.abs(np.fft.rfft(audio * np.hanning(audio.size))) ** 2
    freqs = np.fft.rfftfreq(audio.size, 1.0 / fs)
    total = float(spec.sum())
    outside = float(spec[np.abs(freqs - tone_hz) > half_width_hz].sum())
    if total <= 0:
        return -math.inf
    return 10.0 * math.log10(max(outside, 1e-30) / total)


def rise_time_ms(audio: np.ndarray, fs: int, tone_hz: float, level: float, around: float) -> float:
    """Durée 10 % -> 90 % du front montant le plus proche de l'échantillon `around`."""
    env = envelope(audio)
    lo, hi = 0.1 * level, 0.9 * level
    start = max(0, int(around) - fs // 50)
    seg = env[start:int(around) + fs // 50]
    a = int(np.argmax(seg > lo))
    b = int(np.argmax(seg > hi))
    return (b - a) * 1000.0 / fs
