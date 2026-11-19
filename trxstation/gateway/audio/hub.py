# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""RxHub : distribue le son reçu du poste à tous les clients connectés (diffusion).

Ordre (étape 295) : indicateur de niveau (son du poste + `rx_gain_db`, sans plafond : il montre une saturation)
-> gain `rx_gain_db` et limiteur `rx_limiter` en UNE passe en virgule flottante (crête à -1 dBFS ; un gain appliqué
en 16 bits avant lui écrêterait déjà) -> FreeDV ou traitement SELCALL -> terminaux, visiteurs, diffusion.
Le limiteur ne touche que les crêtes qui auraient saturé : les décodeurs reçoivent le même son qu'avant, sans
écrêtage. Limiteur coupé : gain appliqué en 16 bits, écrêtage possible (comportement d'avant l'étape 295)."""
from __future__ import annotations

import asyncio
import logging

from .levels import LevelMeter
from .limiter import PeakLimiter
from .pcm import apply_gain
from ...errors import codes
from ...errors.emit import emit_event

log = logging.getLogger(__name__)


class RxHub:
    def __init__(self, source, meter: LevelMeter | None = None, gain_db: float = 0.0, limiter: bool = True):
        self.source, self.meter, self.gain_db = source, meter or LevelMeter(), gain_db
        self._subscribers: set[asyncio.Queue] = set()
        self.frames = self.dropped = 0
        self.limiter = PeakLimiter() if limiter else None
        self.limited = 0                                            # trames baissées par le limiteur
        # Traitement facultatif du son reçu avant les clients (SELCALL : retard, squelch, filtrage des tonalités).
        # Une erreur n'arrête jamais la réception : le son passe alors tel quel.
        self.processor = None
        self._processor_failed = False
        # Mode FreeDV (freedv/service.py) : en service, il REMPLACE le traitement ci-dessus (voix décodée, pas de
        # filtrage SELCALL sur elle) ; hors service ou en erreur, le son du poste suit le chemin habituel.
        self.freedv = None
        self._freedv_failed = False

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)

    def subscribe(self, maxsize: int = 10) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)       # 10 trames = 200 ms de retard maximum
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, pcm: bytes) -> None:
        if self.limiter is not None:
            self.meter.update(pcm, self.gain_db)                    # niveau du poste + gain, avant tout traitement
            pcm = self.limiter.process(pcm, self.gain_db)
            if self.limiter.gain < 1.0:
                self.limited += 1
        else:
            pcm = apply_gain(pcm, self.gain_db)
            self.meter.update(pcm)
        self.frames += 1
        freedv = self.freedv
        if freedv is not None and freedv.on:
            try:
                pcm = freedv.process(pcm)
            except Exception:
                if not self._freedv_failed:
                    emit_event(codes.ORT_6567, logger=log, trace=True, erreur="décodage : le son du poste passe tel quel")
                self._freedv_failed = True
        elif self.processor is not None:
            try:
                pcm = self.processor(pcm)
            except Exception:
                if not self._processor_failed:
                    emit_event(codes.ORT_3007, logger=log, trace=True, erreur="le son passe sans traitement")
                self._processor_failed = True
        for queue in self._subscribers:
            if queue.full():                                        # client lent : on jette le plus ancien
                queue.get_nowait()
                self.dropped += 1
            queue.put_nowait(pcm)

    async def run(self) -> None:
        while True:
            pcm = await self.source.read()
            if pcm is None:
                return
            self.publish(pcm)
