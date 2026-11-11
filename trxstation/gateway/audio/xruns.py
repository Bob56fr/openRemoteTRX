# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Surveillance des décrochages de la carte son du poste (xruns) : événement ORT-3010 quand ils deviennent fréquents.

La capture compte ses décrochages (`xruns` : PortAudio signale un sous- ou sur-débit) et ses trames jetées faute
d'être lues à temps (`overruns`). Toutes les PERIOD_S, on regarde la somme sur WINDOW_S : au-delà de THRESHOLD,
un événement (journal, abonnés du catalogue), au plus un par COOLDOWN_S. Aucune alerte ntfy, aucune action :
mesure seulement. Une source sans compteurs (fichier, son de synthèse) n'est jamais signalée.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

from ...errors import codes
from ...errors.emit import emit_event

WINDOW_S = 300.0
PERIOD_S = 30.0
THRESHOLD = 50          # 50 décrochages en 5 min (~0,3 % des 15 000 trames) : audible, à signaler
COOLDOWN_S = 1800.0


class XrunWatch:
    def __init__(self, source, *, clock: Callable[[], float] = time.monotonic,
                 emit: Callable[..., object] = emit_event):
        self.source, self.clock, self.emit = source, clock, emit
        self._samples: deque[tuple[float, int, int]] = deque()
        self._last_event: float | None = None

    def _counts(self) -> tuple[int, int] | None:
        xruns, overruns = getattr(self.source, "xruns", None), getattr(self.source, "overruns", None)
        if not isinstance(xruns, int) or not isinstance(overruns, int):
            return None
        return xruns, overruns

    def check(self) -> bool:
        """Un relevé ; True si un événement vient d'être émis."""
        counts = self._counts()
        if counts is None:
            return False
        now = self.clock()
        self._samples.append((now, *counts))
        while len(self._samples) > 1 and now - self._samples[0][0] > WINDOW_S:
            self._samples.popleft()
        t0, x0, o0 = self._samples[0]
        xruns, lost = counts[0] - x0, counts[1] - o0
        if xruns + lost < THRESHOLD:
            return False
        if self._last_event is not None and now - self._last_event < COOLDOWN_S:
            return False
        self._last_event = now
        self.emit(codes.ORT_3010, xruns=xruns, perdues=lost, duree_min=max(1, round((now - t0) / 60)))
        return True

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                self.check()
            except Exception:                      # mesure seulement : jamais d'arrêt de la passerelle
                pass
            try:
                await asyncio.wait_for(stop.wait(), PERIOD_S)
            except asyncio.TimeoutError:
                pass
