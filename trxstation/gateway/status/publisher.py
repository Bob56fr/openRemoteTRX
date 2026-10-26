"""StatusPublisher : écrit l'état de la passerelle plusieurs fois par seconde.

Il tourne DANS la boucle asyncio de la passerelle : si la boucle se fige ou si le processus
est suspendu, `seq` cesse d'avancer, et c'est exactement ce que le superviseur détecte.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from ...status import GatewayStatus, write_status
from ..cat import CatLink
from ..safety import PttController

log = logging.getLogger(__name__)


class StatusPublisher:
    def __init__(self, path: str | Path, link: CatLink, controller: PttController, interval_s: float = 0.25,
                 pipeline=None):
        self.path = Path(path)
        self.link, self.controller, self.interval_s = link, controller, interval_s
        self.pipeline = pipeline
        self._seq = 0
        self._stop = asyncio.Event()
        self._failures = 0                # écritures refusées de suite (journal limité : pas une ligne par refus)

    def build(self) -> GatewayStatus:
        self._seq += 1
        return GatewayStatus(pid=os.getpid(), seq=self._seq, written_at=time.time(),
                             ptt=self.controller.snapshot().to_dict(), rig=self.link.state.to_dict(),
                             clients=self.controller.clients,
                             audio=self.pipeline.stats() if self.pipeline is not None else {})

    def stop(self) -> None:
        self._stop.set()

    def write_once(self) -> bool:
        """Une écriture ; un échec est journalisé à la 1re occurrence puis toutes les ~5 s (20 écritures)."""
        try:
            write_status(self.path, self.build())
        except OSError as exc:  # disque plein, droits, fichier tenu ouvert... : on continue d'essayer
            self._failures += 1
            if self._failures == 1:
                log.warning("écriture de l'état refusée : %s", exc)
            elif self._failures % 20 == 0:
                log.error("écriture de l'état impossible depuis %d essais : %s "
                          "(le superviseur jugera la passerelle muette)", self._failures, exc)
            return False
        if self._failures:
            if self._failures > 1:
                log.info("écriture de l'état rétablie après %d refus", self._failures)
            self._failures = 0
        return True

    async def run(self) -> None:
        while not self._stop.is_set():
            self.write_once()
            try:
                await asyncio.wait_for(self._stop.wait(), self.interval_s)
            except asyncio.TimeoutError:
                pass
