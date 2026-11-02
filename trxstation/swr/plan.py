# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Calculs purs de la mesure de TOS (docs/tos-cahier-des-charges.md § 5 et § 9), sans rien envoyer au poste :
plage, pas arrondi à une valeur lisible, points, bande de la table interne, échelle et couleurs du graphique.

MÊMES calculs dans la page (static/swr.js) et l'application (logic/Swr.kt) : exemples partagés
tests/protocol/swr_plans.json (table des bandes comprise).

La table des bandes sert à proposer la plage par défaut (la bande où se trouve le poste) et à AVERTIR quand la plage
sort des bandes radioamateur. Elle n'autorise JAMAIS une émission : c'est le rôle de `[[bands]]` de station.toml
(si `enforce_bands`) et du PttController, comme pour toute émission.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

NICE_STEPS_HZ = (1_000, 2_000, 5_000, 10_000, 25_000, 50_000, 75_000, 100_000, 150_000, 200_000, 250_000, 500_000,
                 1_000_000)
MAX_POINTS = 50                       # défaut de `[swr] max_points`
SCALE_KNEE = 0.7                      # TOS 2 aux 7/10 de la hauteur : 1 à 2 étiré, 2 à 5 resserré
SCALE_MAX = 5.0
GRID = (1.2, 1.3, 1.4, 1.5, 1.8, 2.0)  # lignes horizontales demandées par l'utilisateur


@dataclass(frozen=True)
class TableBand:
    name: str
    kind: str                         # amateur, cb, 45m, marine
    low_hz: int
    high_hz: int


# Ordre = priorité (le radioamateur d'abord : 28,000 MHz est du 10 m, pas de la CB).
BANDS: tuple[TableBand, ...] = (
    # radioamateur, IARU Région 1 (comme DEFAULT_BANDS_R1, plus le 6 m)
    TableBand("160m", "amateur", 1_810_000, 2_000_000), TableBand("80m", "amateur", 3_500_000, 3_800_000),
    TableBand("60m", "amateur", 5_351_500, 5_366_500), TableBand("40m", "amateur", 7_000_000, 7_200_000),
    TableBand("30m", "amateur", 10_100_000, 10_150_000), TableBand("20m", "amateur", 14_000_000, 14_350_000),
    TableBand("17m", "amateur", 18_068_000, 18_168_000), TableBand("15m", "amateur", 21_000_000, 21_450_000),
    TableBand("12m", "amateur", 24_890_000, 24_990_000), TableBand("10m", "amateur", 28_000_000, 29_700_000),
    TableBand("6m", "amateur", 50_000_000, 52_000_000), TableBand("2m", "amateur", 144_000_000, 146_000_000),
    TableBand("70cm", "amateur", 430_000_000, 440_000_000),
    # CB (décision de l'utilisateur : 26 à 28 MHz), « 45 m » et « 85 m » (6 660 et 3 450 kHz ± 40 kHz)
    TableBand("CB", "cb", 26_000_000, 28_000_000),
    TableBand("45m", "45m", 6_620_000, 6_700_000), TableBand("85m", "45m", 3_410_000, 3_490_000),
    # service mobile maritime HF (UIT, appendice 17)
    TableBand("marine 4 MHz", "marine", 4_063_000, 4_438_000), TableBand("marine 6 MHz", "marine", 6_200_000, 6_525_000),
    TableBand("marine 8 MHz", "marine", 8_195_000, 8_815_000), TableBand("marine 12 MHz", "marine", 12_230_000, 13_200_000),
    TableBand("marine 16 MHz", "marine", 16_360_000, 17_410_000), TableBand("marine 18 MHz", "marine", 18_780_000, 18_900_000),
    TableBand("marine 19 MHz", "marine", 19_680_000, 19_800_000), TableBand("marine 22 MHz", "marine", 22_000_000, 22_855_000),
    TableBand("marine 25 MHz", "marine", 25_070_000, 25_210_000), TableBand("marine 26 MHz", "marine", 26_100_000, 26_175_000),
)


class PlanError(ValueError):
    """Plage ou nombre de points impossible ; `code` = motif du protocole (swr_*)."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def band_at(hz: int) -> TableBand | None:
    """Bande de la table qui contient `hz` (radioamateur d'abord), ou None."""
    return next((b for b in BANDS if b.low_hz <= hz <= b.high_hz), None)


def is_amateur(hz: int) -> bool:
    return any(b.kind == "amateur" and b.low_hz <= hz <= b.high_hz for b in BANDS)


def range_from_center(center_hz: int, width_hz: int) -> tuple[int, int]:
    """FreqBasse et FreqHaute d'une fréquence centrale et d'une largeur (affichées à l'opérateur)."""
    if center_hz <= 0 or width_hz <= 0:
        raise PlanError("swr_bad_range", "fréquence centrale et largeur doivent être positives")
    half = width_hz // 2
    return center_hz - half, center_hz + (width_hz - half)


def nice_step(raw_hz: float) -> int:
    """Valeur lisible la plus proche du pas brut (à égalité, la plus petite)."""
    return min(NICE_STEPS_HZ, key=lambda s: (abs(s - raw_hz), s))


def plan(low_hz: int, high_hz: int, points: int, max_points: int = MAX_POINTS) -> dict:
    """Points de la mesure : pas lisible le plus proche de (largeur / (points - 1)), points ronds de FreqBasse (arrondie
    au pas supérieur) à FreqHaute. Trop de points : pas lisible suivant. Lève PlanError si c'est impossible."""
    if not isinstance(points, int) or isinstance(points, bool) or points < 2:
        raise PlanError("swr_bad_range", "au moins 2 points")
    if low_hz <= 0 or high_hz <= low_hz:
        raise PlanError("swr_bad_range", "FreqHaute doit dépasser FreqBasse")
    step = nice_step((high_hz - low_hz) / (points - 1))
    index = NICE_STEPS_HZ.index(step)
    while True:
        first = math.ceil(low_hz / step) * step
        freqs = list(range(first, high_hz + 1, step))
        if len(freqs) <= max_points:
            break
        if index + 1 >= len(NICE_STEPS_HZ):
            raise PlanError("swr_too_many_points", f"plus de {max_points} points")
        index += 1
        step = NICE_STEPS_HZ[index]
    if len(freqs) < 2:
        raise PlanError("swr_bad_range", f"plage trop étroite pour un pas de {step // 1000} kHz")
    return {"low_hz": low_hz, "high_hz": high_hz, "step_hz": step, "freqs": freqs,
            "amateur_only": all(is_amateur(f) for f in freqs)}


def scale_y(swr: float) -> float:
    """Hauteur (0 à 1) d'un TOS sur l'axe vertical non linéaire, plafonné à 5."""
    if not math.isfinite(swr) or swr <= 1:
        return 0.0
    if swr <= 2:
        return round(SCALE_KNEE * (swr - 1), 6)
    return round(min(1.0, SCALE_KNEE + (1 - SCALE_KNEE) * (swr - 2) / (SCALE_MAX - 2)), 6)


def level(swr: float) -> str:
    """good jusqu'à 1,5 (vert), fair jusqu'à 2 (orange), bad au-dessus de 2 (rouge)."""
    return "good" if swr <= 1.5 else "fair" if swr <= 2 else "bad"
