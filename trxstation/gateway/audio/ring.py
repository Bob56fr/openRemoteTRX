"""Tampon circulaire d'octets, sûr entre fils (le callback PortAudio tourne dans un autre fil)."""
from __future__ import annotations

import threading


class RingBuffer:
    def __init__(self, capacity_bytes: int):
        self.capacity = capacity_bytes
        self._data = bytearray()
        self._lock = threading.Lock()
        self.overruns = 0     # octets perdus faute de place (le plus ancien est jeté : on garde le temps réel)
        self.underruns = 0    # lectures complétées par du silence

    def write(self, data: bytes) -> None:
        with self._lock:
            self._data += data
            excess = len(self._data) - self.capacity
            if excess > 0:
                del self._data[:excess]
                self.overruns += 1

    def read(self, size: int) -> bytes:
        with self._lock:
            chunk = bytes(self._data[:size])
            del self._data[:size]
        if len(chunk) < size:
            self.underruns += 1
            chunk += bytes(size - len(chunk))
        return chunk

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
