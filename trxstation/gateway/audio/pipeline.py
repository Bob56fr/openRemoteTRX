# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""AudioPipeline : source -> RxHub (vers les clients) et porte d'émission -> puits (vers le poste)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from ...config import Audio
from .devices import make_sink, make_source
from .gate import TxAudioGate
from .hub import RxHub
from .levels import LevelMeter

log = logging.getLogger(__name__)


class AudioPipeline:
    def __init__(self, cfg: Audio, *, source=None, sink=None, sd=None,
                 owner_provider: Callable[[], str | None] = lambda: None):
        self.source = source if source is not None else make_source(cfg.capture_device, sd)
        self.sink = sink if sink is not None else make_sink(cfg.playback_device, sd)
        self.rx_meter, self.tx_meter = LevelMeter(), LevelMeter()
        self.hub = RxHub(self.source, self.rx_meter, cfg.rx_gain_db)
        self.gate = TxAudioGate(self.sink, self.tx_meter, cfg.tx_gain_db, owner_provider)
        self._task: asyncio.Task | None = None
        self.selcall = None                       # SelcallReceiver si [selcall] enabled (gateway/main)

    async def start(self) -> None:
        await self.source.start()
        self._task = asyncio.get_running_loop().create_task(self.hub.run())

    async def stop(self) -> None:
        self.gate.set_open(False)
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self.source.stop()
        self.sink.close()

    def stats(self) -> dict:
        """Chiffres publiés dans l'état (fichier d'état, clients, trx-monitor)."""
        return {"rx_db": round(self.rx_meter.value), "tx_db": round(self.tx_meter.value),
                "gate_open": self.gate.is_open, "listeners": self.hub.subscribers,
                "rx_dropped": self.hub.dropped, "tx_dropped_not_owner": self.gate.dropped_not_owner,
                "rx_frames": self.hub.frames,              # trames capturées sur la carte son du poste
                "tx_frames": self.gate.passed,             # trames du micro d'un client passées au poste (porte ouverte)
                "tx_dropped_closed": self.gate.dropped_closed,   # trames jetées porte fermée (normal en réception)
                "tx_underruns": getattr(self.sink, "underruns", 0),   # trous dans le son envoyé au poste (réseau en retard)
                "tx_overruns": getattr(self.sink, "overruns", 0)}     # son jeté car arrivé trop tard
