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

    def build(self) -> GatewayStatus:
        self._seq += 1
        return GatewayStatus(pid=os.getpid(), seq=self._seq, written_at=time.time(),
                             ptt=self.controller.snapshot().to_dict(), rig=self.link.state.to_dict(),
                             clients=self.controller.clients,
                             audio=self.pipeline.stats() if self.pipeline is not None else {})

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                write_status(self.path, self.build())
            except OSError as exc:  # disque plein, droits... : on continue d'essayer
                log.error("écriture de l'état impossible : %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), self.interval_s)
            except asyncio.TimeoutError:
                pass
