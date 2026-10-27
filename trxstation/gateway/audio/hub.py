# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""RxHub : distribue le son reçu du poste à tous les clients connectés (diffusion)."""
from __future__ import annotations

import asyncio
import logging

from .levels import LevelMeter
from .pcm import apply_gain

log = logging.getLogger(__name__)


class RxHub:
    def __init__(self, source, meter: LevelMeter | None = None, gain_db: float = 0.0):
        self.source, self.meter, self.gain_db = source, meter or LevelMeter(), gain_db
        self._subscribers: set[asyncio.Queue] = set()
        self.frames = self.dropped = 0

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
        pcm = apply_gain(pcm, self.gain_db)
        self.meter.update(pcm)
        self.frames += 1
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
