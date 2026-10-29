# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Son des VISITEURS (docs/visiteurs-cahier-des-charges.md § 5) : en réception, le son du poste ; pendant une
émission de la station, ce qui part vers le poste (voix du propriétaire après la porte, bips et trame SELCALL de fin).

  * TxTap : copie de chaque trame écrite vers le poste, distribuée aux visiteurs par des files bornées qui jettent la
    plus ancienne (jamais d'attente : la porte d'émission n'est jamais ralentie par un visiteur) ;
  * TapSink : enveloppe le puits du poste (porte d'émission, bips) et alimente le TxTap ; tout le reste est délégué ;
  * ListenerMix : pour UN visiteur, à chaque trame reçue du poste (horloge : 20 ms), choisit la source ; à chaque
    bascule, fondu enchaîné sur une trame (20 ms) : pas de clic.
Les opérateurs ne reçoivent JAMAIS ce mélange (ils ne s'entendent pas eux-mêmes) : leurs pistes restent sur le RxHub.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from .pcm import FRAME_BYTES, FRAME_SAMPLES, silence, to_bytes, to_samples

SILENCE = silence()
TX_HOLD_S = 0.12              # sans trame d'émission depuis ce délai : retour au son du poste
TAP_FRAMES = 10               # 200 ms au plus en attente par visiteur


class TxTap:
    def __init__(self):
        self._subscribers: list[deque] = []           # une deque n'est pas hachable
        self.frames = 0

    def subscribe(self, maxlen: int = TAP_FRAMES) -> deque:
        queue: deque = deque(maxlen=maxlen)       # pleine : la plus ancienne tombe d'elle-même
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: deque) -> None:
        self._subscribers = [q for q in self._subscribers if q is not queue]

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)

    def publish(self, pcm: bytes) -> None:
        if not self._subscribers:
            return
        self.frames += 1
        for start in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):   # trames de 20 ms (les bips en sont)
            chunk = pcm[start:start + FRAME_BYTES]
            for queue in self._subscribers:
                queue.append(chunk)


class TapSink:
    """Puits du poste vu par la porte d'émission et les bips de fin : écrit vers le poste PUIS copie vers les
    visiteurs. Une erreur de copie n'empêche jamais l'écriture vers le poste."""

    def __init__(self, sink, tap: TxTap):
        self._sink, self.tap = sink, tap

    def write(self, pcm: bytes) -> None:
        self._sink.write(pcm)
        try:
            self.tap.publish(pcm)
        except Exception:                          # noqa: BLE001 - les visiteurs ne gênent jamais l'émission
            pass

    def __getattr__(self, name):                    # flush, close, PREFILL_S, underruns, overruns, frames (tests)...
        return getattr(self._sink, name)


def crossfade(a: bytes, b: bytes) -> bytes:
    """Passe linéairement de `a` à `b` sur une trame."""
    sa, sb = to_samples(a), to_samples(b)
    n = min(len(sa), len(sb))
    out = sb[:]
    for i in range(n):
        k = i / n
        out[i] = int(sa[i] * (1.0 - k) + sb[i] * k)
    return to_bytes(out)


class ListenerMix:
    def __init__(self, tap: TxTap, muted: Callable[[], bool] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.tap, self.muted, self.clock = tap, muted, clock
        self._queue = tap.subscribe()
        self._last_tx = float("-inf")
        self._tx_mode = False

    def close(self) -> None:
        self.tap.unsubscribe(self._queue)

    @property
    def transmitting(self) -> bool:
        return self._tx_mode

    def next(self, rx: bytes) -> bytes:
        """Trame à envoyer au visiteur pour cette trame reçue du poste. Le silence hors bandes ne touche que le son
        du poste : la voix de l'opérateur n'est émise que dans une bande autorisée."""
        if len(rx) != FRAME_BYTES:
            rx = (rx + SILENCE)[:FRAME_BYTES]
        if self.muted is not None and self.muted():
            rx = SILENCE
        now = self.clock()
        tx = self._queue.popleft() if self._queue else None
        if tx is not None:
            self._last_tx = now
        tx_mode = tx is not None or now - self._last_tx < TX_HOLD_S
        voice = tx if tx is not None and len(tx) == FRAME_BYTES else SILENCE
        out = voice if tx_mode else rx
        if tx_mode != self._tx_mode:                    # bascule : fondu entre les deux sources de CETTE trame
            out = crossfade(rx if tx_mode else voice, out)
            self._tx_mode = tx_mode
        return out


assert FRAME_BYTES == FRAME_SAMPLES * 2
