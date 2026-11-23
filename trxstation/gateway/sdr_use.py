# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Usage du SDR vu par la passerelle, pour la VEILLE du module « sdr » (étape 380).

Le SDR est « utilisé » quand au moins un opérateur affiche sa rubrique (`sdr_view`) ou l'écoute (`sdr_listen`). La
passerelle le dit au module par l'action « use » : tout de suite à chaque changement, puis toutes les REPEAT_S tant qu'il
est utilisé (le module tient un « on » pour valable 30 s : une passerelle arrêtée ne le garde pas éveillé pour toujours,
un module relancé l'apprend vite). Sans usage depuis 60 s, le module arrête sdr-core ; un « on » le réveille.
Les visiteurs ne comptent jamais (ils n'ont pas la rubrique SDR).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)

TICK_S = 0.5           # ouverture de la rubrique vue en une demi-seconde au plus
REPEAT_S = 10.0


def in_use(sessions: Iterable) -> bool:
    return any((getattr(s, "sdr_view", False) or getattr(s, "sdr_listen", False)) and not getattr(s, "listener", True)
               for s in sessions)


class SdrUse:
    def __init__(self, sessions: Callable[[], Iterable], call: Callable[[dict], object],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.sessions, self.call, self.clock = sessions, call, clock
        self.used: bool | None = None          # inconnu au départ : le premier passage le dit toujours
        self._said_at = -1e9

    def tick(self) -> bool:
        """Un passage : vrai si « use » a été envoyé."""
        used = in_use(list(self.sessions()))
        now = self.clock()
        if used == self.used and not (used and now - self._said_at >= REPEAT_S):
            return False
        self.used, self._said_at = used, now
        try:
            result = self.call({"action": "use", "args": {"on": used}})
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result).add_done_callback(_quiet)
        except Exception as exc:                   # module absent ou bus coupé : redit au prochain changement
            log.info("usage du SDR non transmis au module : %s", exc)   # redit dans REPEAT_S pendant l'usage
        return True


def _quiet(task: asyncio.Future) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.info("usage du SDR non transmis au module : %s", task.exception())


async def run(use: SdrUse, stop: asyncio.Event) -> None:
    while not stop.is_set():
        use.tick()
        try:
            await asyncio.wait_for(stop.wait(), TICK_S)
        except asyncio.TimeoutError:
            pass
