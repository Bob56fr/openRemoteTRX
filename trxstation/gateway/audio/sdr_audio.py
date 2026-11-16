# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Son démodulé du module SDR (lot S1b, docs/sdr-cahier-des-charges.md § 13) : réception et distribution.

- Le module envoie des paquets UDP à 127.0.0.1:[sdr] audio_port : « ORSA », jeton (16 octets, dérivé du secret du
  module), numéro (uint32), 960 échantillons int16 (20 ms à 48 kHz). Un paquet sans le bon jeton est ignoré.
- Chaque opérateur qui ÉCOUTE le SDR a un abonnement (petite file : 160 ms au plus, 40 ms d'avance au départ).
- COUPURE PENDANT TOUTE ÉMISSION (client, micro du poste, SELCALL, TOS) : fondu de 50 ms vers le silence, reprise
  0,5 s après le retour en réception, en fondu. Décidé ICI, par la passerelle, sur l'état du PTT : jamais d'attente
  du module.
- Le module ne démodule que si quelqu'un écoute : la passerelle lui dit « audio » on / off (et le redit toutes les
  5 s tant qu'on écoute sans recevoir de son : module relancé entre-temps).
Calculs purs ici (aucun accès à aiortc) : la piste WebRTC est dans gateway/api/webrtc.py (SdrTrack).
"""
from __future__ import annotations

import array
import asyncio
import hmac
import logging
import time
from collections import deque
from collections.abc import Callable

log = logging.getLogger("trx.sdr.audio")

MAGIC = b"ORSA"
TOKEN_BYTES = 16
BLOCK = 960
PACKET_BYTES = 4 + TOKEN_BYTES + 4 + 2 * BLOCK
QUEUE_MAX = 8              # 160 ms au plus en attente par écoutant
PREBUFFER = 2              # 40 ms d'avance après un manque
FADE_S = 0.05
RELEASE_S = 0.5            # après l'émission : le temps que l'AGC du SDR se reprenne
REASSERT_S = 5.0
SILENCE = bytes(2 * BLOCK)


class Subscriber:
    """File d'un écoutant, avec son gain de fondu."""

    def __init__(self) -> None:
        self.queue: deque[bytes] = deque(maxlen=QUEUE_MAX)
        self.ready = False
        self.gain = 1.0

    def take(self) -> bytes | None:
        if not self.ready:
            if len(self.queue) < PREBUFFER:
                return None
            self.ready = True
        if not self.queue:
            self.ready = False                       # manque : on attend de nouveau un peu d'avance
            return None
        return self.queue.popleft()


def apply_gain(pcm: bytes, start: float, end: float) -> bytes:
    """Gain linéaire de start à end sur le bloc (fondu sans clic)."""
    if start == end == 1.0:
        return pcm
    if start == end == 0.0:
        return SILENCE
    samples = array.array("h")
    samples.frombytes(pcm)
    n = len(samples)
    for i in range(n):
        g = start + (end - start) * (i + 1) / n
        samples[i] = int(samples[i] * g)
    return samples.tobytes()


class SdrAudio:
    def __init__(self, port: int, token: bytes, transmitting: Callable[[], bool], *,
                 request_audio: Callable[[bool], object] | None = None, clock=time.monotonic) -> None:
        self.port, self.token = port, token
        self.transmitting = transmitting          # () -> bool : émission en cours (n'importe laquelle)
        self.request_audio = request_audio        # (on) -> coroutine : action « audio » vers le module
        self.clock = clock
        self.subscribers: set[Subscriber] = set()
        self.listeners = 0
        self.packets = self.refused = 0
        self.last_packet = -1e9
        self._muted_until = -1e9                  # fin du maintien du silence après une émission
        self._transport = None
        self._last_assert = -1e9

    # ------------------------------------------------------------- réception
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self),
                                                                 local_addr=("127.0.0.1", self.port))
        log.info("son du SDR attendu en UDP sur 127.0.0.1:%d", self.port)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def on_packet(self, data: bytes) -> bool:
        if (len(data) != PACKET_BYTES or data[:4] != MAGIC
                or not hmac.compare_digest(data[4:4 + TOKEN_BYTES], self.token)):
            self.refused += 1
            return False
        self.packets += 1
        self.last_packet = self.clock()
        pcm = data[4 + TOKEN_BYTES + 4:]
        for sub in list(self.subscribers):
            sub.queue.append(pcm)                   # file pleine : le plus ancien part (retard borné)
        return True

    # ------------------------------------------------------------- écoutants
    def subscribe(self) -> Subscriber:
        sub = Subscriber()
        self.subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self.subscribers.discard(sub)

    def set_listeners(self, count: int) -> None:
        """Nombre d'opérateurs qui écoutent : le module ne démodule que s'il y en a."""
        was, self.listeners = self.listeners, max(0, count)
        if (was > 0) != (self.listeners > 0):
            self._ask(self.listeners > 0)

    def tick(self) -> None:
        """Toutes les secondes : on écoute mais rien n'arrive (module relancé) -> redemander le son."""
        now = self.clock()
        if self.listeners and now - self.last_packet > 2.0 and now - self._last_assert >= REASSERT_S:
            self._ask(True)

    def _ask(self, on: bool) -> None:
        self._last_assert = self.clock()
        if self.request_audio is None:
            return
        try:
            result = self.request_audio(on)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result).add_done_callback(_log_failure)
        except Exception as exc:                      # module absent : la page le voit dans l'état du SDR
            log.info("demande de son au module impossible : %s", exc)

    # ------------------------------------------------------------- un bloc de 20 ms pour un écoutant
    def next_block(self, sub: Subscriber, listening: bool) -> bytes:
        """Bloc suivant pour CE client : son du SDR, ou silence (pas d'écoute, manque, émission en cours)."""
        now = self.clock()
        if self.transmitting():
            self._muted_until = now + RELEASE_S
        target = 0.0 if now < self._muted_until or not listening else 1.0
        step = 0.02 / FADE_S
        start = sub.gain
        end = min(target, start + step) if target > start else max(target, start - step)
        sub.gain = end
        pcm = sub.take()
        if not listening:
            sub.queue.clear()
            sub.ready = False
        if pcm is None or (start == 0.0 and end == 0.0):
            return SILENCE
        return apply_gain(pcm, start, end)


def _log_failure(task: asyncio.Future) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.info("demande de son au module : %s", task.exception())


async def run_ticks(audio: SdrAudio, stop: asyncio.Event) -> None:
    while not stop.is_set():
        audio.tick()
        try:
            await asyncio.wait_for(stop.wait(), 1.0)
        except asyncio.TimeoutError:
            pass


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, owner: SdrAudio) -> None:
        self.owner = owner

    def datagram_received(self, data: bytes, addr) -> None:
        if addr and addr[0] != "127.0.0.1":
            return
        self.owner.on_packet(data)
