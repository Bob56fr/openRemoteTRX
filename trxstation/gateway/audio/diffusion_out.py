# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Son de la diffusion en direct : la passerelle le donne au module « diffusion » (docs/diffusion-cahier-des-charges.md
§ 3, lot D1b). L'inverse du son du SDR (sdr_audio.py).

- Le MÊME son que celui des visiteurs (`ListenerMix` : son du poste, voix de l'opérateur pendant ses émissions), mais
  SANS le silence hors bandes des visiteurs : la diffusion ne filtre pas les bandes (décision § 1.1, responsabilité
  de l'opérateur).
- Voix émise : seulement si l'opérateur l'a demandé au lancement (option `voice`) ; sinon SILENCE pendant TOUTE
  émission (client, micro du poste, SELCALL, TOS). Décidé ICI, sur l'état du PTT de la passerelle.
- Rien n'est envoyé hors diffusion : la passerelle demande l'état du module toutes les 2 s.
- Station surchargée (même garde que les visiteurs) : la passerelle arrête la diffusion (cause « overload »).
Le module ne peut rien demander d'autre : il n'a aucun droit sur le poste.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable

from ...diffusion import audio as au
from .listeners import ListenerMix

log = logging.getLogger("trx.diffusion.out")

POLL_S = 2.0


class DiffusionOut:
    def __init__(self, port: int, token: bytes, hub, tap, transmitting: Callable[[], bool],
                 call: Callable[[dict], Awaitable], overloaded: Callable[[], bool] = lambda: False) -> None:
        self.port, self.token, self.hub, self.tap = port, token, hub, tap
        self.transmitting = transmitting          # () -> bool : émission en cours (n'importe laquelle)
        self.call = call                          # (data) -> coroutine : commande vers le module
        self.overloaded = overloaded              # () -> bool : garde de surcharge des visiteurs déclenchée
        self.voice = False
        self.packets = 0
        self._feed: asyncio.Task | None = None

    async def poll(self) -> None:
        """Un tour : état du module, arrêt en surcharge, envoi du son ouvert ou fermé."""
        try:
            status = await self.call({"action": "status"})
        except Exception:                          # module absent, relancé ou lent : on n'envoie rien
            status = None
        active = isinstance(status, dict) and status.get("active") is True
        if active and self.overloaded():
            try:
                await self.call({"action": "stop", "args": {"cause": "overload"}})
            except Exception:
                pass
            active = False
        self.voice = active and status.get("voice") is True
        if active and self._feed is None:
            self._feed = asyncio.ensure_future(self._feed_loop())
        elif not active and self._feed is not None:
            await self.close_feed()

    async def close_feed(self) -> None:
        feed, self._feed = self._feed, None
        if feed is not None:
            feed.cancel()
            try:
                await feed
            except (asyncio.CancelledError, Exception):
                pass

    def frame(self, mix: ListenerMix, rx: bytes) -> bytes:
        out = mix.next(rx)
        if not self.voice and (mix.transmitting or self.transmitting()):
            return au.SILENCE
        return out

    async def _feed_loop(self) -> None:
        queue = self.hub.subscribe()
        mix = ListenerMix(self.tap, None)          # pas de silence hors bandes (cahier § 1.1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        seq = 0
        try:
            while True:
                pcm = self.frame(mix, await queue.get())
                try:
                    sock.sendto(au.pack(self.token, seq, pcm), ("127.0.0.1", self.port))
                    self.packets += 1
                except OSError:                    # module absent : paquet perdu, rien d'autre
                    pass
                seq += 1
        finally:
            self.hub.unsubscribe(queue)
            mix.close()
            sock.close()

    async def run(self, stop: asyncio.Event) -> None:
        try:
            while not stop.is_set():
                await self.poll()
                try:
                    await asyncio.wait_for(stop.wait(), POLL_S)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.close_feed()
