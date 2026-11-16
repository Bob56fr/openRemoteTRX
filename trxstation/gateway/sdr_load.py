# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""La passerelle bride le module SDR quand ELLE souffre (docs/sdr-cahier-des-charges.md § 2.3, lot S1b-2).

Mesures (une par seconde) : température du processeur, charge de tous les cœurs, retard de la boucle asyncio,
mémoire libre (overload.py), et décrochages de la carte son du POSTE (xruns, comme ORT-3010). Seuils un cran
SOUS ceux de la protection des visiteurs ([access] overload_*) : le SDR, purement accessoire, cède le premier.
Échelle graduée (trxstation/sdr/load.py) : le niveau 1 (son du SDR coupé) est appliqué ici ; tout niveau est
envoyé au module par le bus (action « load », jamais acceptée d'un client), renvoyé toutes les RESEND_S tant qu'il
n'est pas nul (module relancé entre-temps). Ne touche JAMAIS au poste ni à l'émission.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable

from ..errors import codes
from ..errors.emit import emit_event
from ..sdr.load import LEVEL_TEXT, Ladder
from .api.overload import Limits, Sample

log = logging.getLogger("trx.sdr.load")

RESEND_S = 30.0
XRUN_WINDOW = 10               # secondes
XRUN_LIMIT = 5                 # décrochages (ou trames perdues) en XRUN_WINDOW s : la carte son du poste souffre


def limits_from_access(a) -> Limits:
    """Seuils du SDR : un cran sous ceux des visiteurs ([access] overload_*)."""
    return Limits(temp_c=max(40.0, a.overload_temp_c - 5), cpu_pct=max(30.0, a.overload_cpu_pct - 5),
                  lag_ms=max(20.0, a.overload_lag_ms * 0.6), mem_pct=min(50.0, a.overload_mem_pct + 2))


class SdrGovernor:
    def __init__(self, sample: Callable[[], Sample], limits: Limits, send: Callable[[int, str], object], *,
                 audio=None, xrun_source=None, ladder: Ladder | None = None, emit=emit_event,
                 clock: Callable[[], float] | None = None):
        self.sample, self.limits, self.send = sample, limits, send
        self.audio, self.xrun_source, self.emit = audio, xrun_source, emit
        self.ladder = ladder or (Ladder(clock=clock) if clock else Ladder())
        self.clock = self.ladder.clock
        self._sent: int | None = None          # dernier niveau ACCEPTÉ par le module
        self._sent_at = -1e9
        self._xruns: deque[int] = deque(maxlen=XRUN_WINDOW + 1)

    def _xrun_reason(self) -> str:
        src = self.xrun_source
        x, o = getattr(src, "xruns", None), getattr(src, "overruns", None)
        if not isinstance(x, int) or not isinstance(o, int):
            return ""
        self._xruns.append(x + o)
        n = self._xruns[-1] - self._xruns[0]
        return f"{n} décrochages de la carte son du poste en {len(self._xruns) - 1} s" if n >= XRUN_LIMIT else ""

    def measure(self) -> bool:
        """Une mesure ; vrai si le niveau change."""
        s = self.sample()
        xr = self._xrun_reason()
        over = self.limits.over(s) or xr
        changed = self.ladder.step(over, self.limits.green(s) and not xr)
        if changed:
            level = self.ladder.level
            if self.audio is not None:
                self.audio.set_blocked(level >= 1)
            if level:
                self.emit(codes.ORT_6006, logger=log, niveau=level, effet=LEVEL_TEXT[level], cause=self.ladder.reason)
            else:
                self.emit(codes.ORT_6007, logger=log)
        return changed

    async def push(self) -> None:
        """Envoie le niveau au module s'il a changé (ou périodiquement tant qu'il n'est pas nul)."""
        level, now = self.ladder.level, self.clock()
        if level == self._sent and (level == 0 or now - self._sent_at < RESEND_S):
            return
        try:
            result = self.send(level, self.ladder.reason)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:                # module absent ou relancé : nouvel essai à la mesure suivante
            log.debug("niveau de charge non transmis au module SDR : %s", exc)
            return
        self._sent, self._sent_at = level, now

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                self.measure()
                await self.push()
            except Exception as exc:            # mesure seulement : jamais d'arrêt de la passerelle
                log.debug("mesure de charge du SDR : %s", exc)
            try:
                await asyncio.wait_for(stop.wait(), 1.0)
            except asyncio.TimeoutError:
                pass
