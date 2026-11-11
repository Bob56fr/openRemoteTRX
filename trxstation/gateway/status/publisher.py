# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
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
                 pipeline=None, spectrum=None, presence=None):
        self.path = Path(path)
        self.spectrum = spectrum
        self.link, self.controller, self.interval_s = link, controller, interval_s
        self.pipeline = pipeline
        self.presence = presence          # () -> dict : connexions (opérateurs, visiteurs) pour la console et trx-monitor
        self.swr_status = None            # () -> dict : mesure de TOS en cours (branché par gateway/main une fois créée)
        self.net_status = None            # () -> dict : sonde réseau (NetProbeHub.summary), branchée par gateway/main
        self._seq = 0
        self._stop = asyncio.Event()
        self._failures = 0                # écritures refusées de suite (journal limité : pas une ligne par refus)

    def build(self) -> GatewayStatus:
        self._seq += 1
        return GatewayStatus(pid=os.getpid(), seq=self._seq, written_at=time.time(),
                             ptt=self.controller.snapshot().to_dict(), rig=self.link.state.to_dict(),
                             clients=self.controller.clients,
                             audio=self.pipeline.stats() if self.pipeline is not None else {},
                             spectrum=self.spectrum.stats() if self.spectrum is not None else {},
                             presence=self.presence() if self.presence is not None else {},
                             swr=self.swr_status() if self.swr_status is not None else {},
                             breizh=self.pipeline.route.snapshot()
                             if getattr(self.pipeline, "route", None) is not None else {},
                             net=self._net(), selcall=self._selcall(), freedv=self._freedv())

    def _net(self) -> dict:
        if self.net_status is None:
            return {}
        try:
            return self.net_status()
        except Exception:                 # la sonde ne doit jamais empêcher l'écriture de l'état (superviseur)
            log.exception("état de la sonde réseau")
            return {}

    def _selcall(self) -> dict:
        receiver = getattr(self.pipeline, "selcall", None)
        if receiver is None:              # [selcall] enabled = false
            return {}
        try:
            return receiver.summary()
        except Exception:                 # jamais d'obstacle à l'écriture de l'état (superviseur)
            log.exception("état SELCALL")
            return {}

    def _freedv(self) -> dict:
        service = getattr(self.pipeline, "freedv", None)
        if service is None:               # [freedv] enabled = false
            return {}
        try:
            return service.summary()
        except Exception:                 # jamais d'obstacle à l'écriture de l'état (superviseur)
            log.exception("état FreeDV")
            return {}

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
