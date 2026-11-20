# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Avis sur le niveau du son reçu (étape 301) : trop fort, trop faible ou correct, jugé sur 30 s et non sur un instant
(la BLU a des silences entre les mots, le squelch coupe le son). Affiché par trx-monitor et le tableau de bord de la
console (menu 1.3), qui renvoient au menu 2.9 « Gain audio de réception ». Calcul pur, horloge fournie par l'appelant ;
n'agit sur rien.

Règles (niveau mesuré APRÈS `[audio] rx_gain_db`, avant le limiteur, comme `rx_db`) :
- échantillon d'au plus une seconde ; seuls comptent ceux où il y a du son (au-dessus de SOUND_DBFS) ;
- moins de MIN_SOUND_S secondes de son sur la fenêtre : pas d'avis (None) ;
- niveau typique = médiane des échantillons avec du son ;
- « high » : limiteur du son reçu au travail sur au moins LIMITED_PCT % des trames de la fenêtre, ou niveau typique
  au-dessus de TARGET_DBFS + HIGH_MARGIN_DB ;
- « low » : niveau typique en dessous de TARGET_DBFS - LOW_MARGIN_DB ;
- sinon « ok ».
"""
from __future__ import annotations

from collections import deque
from statistics import median

TARGET_DBFS = -20            # même cible que le menu 2.9 (console.RX_TARGET_DBFS)
HIGH_MARGIN_DB = 12          # typique > -8 dBFS : trop fort
LOW_MARGIN_DB = 20           # typique < -40 dBFS : trop faible
SOUND_DBFS = -85             # en dessous : pas de son (station muette, squelch fermé)
WINDOW_S = 30.0
MIN_SOUND_S = 10
LIMITED_PCT = 2.0
SAMPLE_EVERY_S = 1.0


class RxAdvice:
    def __init__(self) -> None:
        self._samples: deque[tuple[float, float, int, int]] = deque()   # (t, niveau, trames limitées, trames)
        self._last: float | None = None

    def feed(self, now: float, level_db: float, limited: int, frames: int) -> None:
        """Un appel par publication de l'état ; au plus un échantillon par seconde."""
        if self._last is not None and now - self._last < SAMPLE_EVERY_S:
            return
        self._last = now
        if self._samples and frames < self._samples[-1][3]:             # compteurs remis à zéro (audio relancé)
            self._samples.clear()
        self._samples.append((now, float(level_db), int(limited), int(frames)))
        while self._samples and now - self._samples[0][0] > WINDOW_S:
            self._samples.popleft()

    def verdict(self) -> dict | None:
        """{"verdict": "high" | "low" | "ok", "typical_db": int, "limited_pct": float} ou None (pas assez de son)."""
        sound = [s[1] for s in self._samples if s[1] > SOUND_DBFS]
        if len(sound) < MIN_SOUND_S:
            return None
        typical = median(sound)
        first, last = self._samples[0], self._samples[-1]
        frames = last[3] - first[3]
        pct = 100.0 * (last[2] - first[2]) / frames if frames > 0 else 0.0
        if pct >= LIMITED_PCT or typical > TARGET_DBFS + HIGH_MARGIN_DB:
            verdict = "high"
        elif typical < TARGET_DBFS - LOW_MARGIN_DB:
            verdict = "low"
        else:
            verdict = "ok"
        return {"verdict": verdict, "typical_db": round(typical), "limited_pct": round(pct, 1)}
