# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Tampon circulaire d'octets, sûr entre fils (le callback PortAudio tourne dans un autre fil)."""
from __future__ import annotations

import threading


class RingBuffer:
    """`prefill_bytes` > 0 : réserve contre la gigue du réseau. La lecture rend du silence tant que le tampon n'a pas
    atteint la réserve (au départ, après `clear()` et après un trou) ; ensuite elle suit le flux. Un trou en plein flux
    (tampon vidé) compte dans `underruns` : c'est un vrai trou dans le son."""

    def __init__(self, capacity_bytes: int, prefill_bytes: int = 0):
        self.capacity = capacity_bytes
        self.prefill = min(prefill_bytes, capacity_bytes)
        self._data = bytearray()
        self._lock = threading.Lock()
        self._waiting = self.prefill > 0
        self.overruns = 0     # octets perdus faute de place (le plus ancien est jeté : on garde le temps réel)
        self.underruns = 0    # lectures complétées par du silence (en plein flux)

    def write(self, data: bytes) -> None:
        with self._lock:
            self._data += data
            excess = len(self._data) - self.capacity
            if excess > 0:
                del self._data[:excess]
                self.overruns += 1

    def read(self, size: int) -> bytes:
        with self._lock:
            if self._waiting:
                if len(self._data) < self.prefill:
                    return bytes(size)                     # réserve en cours de remplissage : silence, pas un trou
                self._waiting = False
            chunk = bytes(self._data[:size])
            del self._data[:size]
            if len(chunk) < size:
                self.underruns += 1
                self._waiting = self.prefill > 0           # trou : on reconstitue la réserve avant de reprendre
        if len(chunk) < size:
            chunk += bytes(size - len(chunk))
        return chunk

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._waiting = self.prefill > 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
