# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Limiteur final de la station : dernier traitement du micro avant la porte d'émission, TOUJOURS actif
(route directe comme route par Breizh Audio Box : docs/breizh-cahier-des-charges.md § 4.2, décision 2 de la v1).

Crête plafonnée à −1 dBFS. Gain calculé par bloc : baisse immédiate (glissée sur le bloc depuis le gain précédent),
remontée lente (20 dB/s) ; un écrêtage au plafond derrière garantit la crête même pendant la baisse.
Le gain demandé (gain d'émission, volume retour, gain de repli) est appliqué ici, en une seule passe numpy.
"""
from __future__ import annotations

import numpy as np

from .pcm import SAMPLE_RATE

CEILING_DBFS = -1.0
RELEASE_DB_PER_S = 20.0


class PeakLimiter:
    def __init__(self, ceiling_dbfs: float = CEILING_DBFS, release_db_per_s: float = RELEASE_DB_PER_S) -> None:
        self.ceiling = 32768.0 * 10 ** (ceiling_dbfs / 20)
        self.release_db_per_s = release_db_per_s
        self.gain = 1.0                     # gain de limitation en cours (1 = rien)

    def reset(self) -> None:
        self.gain = 1.0

    def process(self, pcm: bytes, gain_db: float = 0.0) -> bytes:
        """s16 petit-boutiste mono -> même format, `gain_db` appliqué puis crête plafonnée."""
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
        if samples.size == 0:
            return pcm
        if gain_db:
            samples *= 10 ** (gain_db / 20)
        peak = float(np.max(np.abs(samples)))
        wanted = min(1.0, self.ceiling / peak) if peak > 0 else 1.0
        if wanted < self.gain:
            target = wanted                                       # baisse : immédiate
        else:
            step = 10 ** (self.release_db_per_s * samples.size / SAMPLE_RATE / 20)
            target = min(wanted, self.gain * step)                # remontée : lente
        if target != 1.0 or self.gain != 1.0:
            samples *= np.linspace(self.gain, target, samples.size, endpoint=False) if target != self.gain else target
        self.gain = target
        np.clip(samples, -self.ceiling, self.ceiling, out=samples)
        return np.round(samples).astype("<i2").tobytes()
