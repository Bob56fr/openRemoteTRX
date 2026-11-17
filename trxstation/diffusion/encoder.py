# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Encodage du son de la diffusion par PyAV (installé avec aiortc : aucune dépendance nouvelle).

Opus 32 kb/s mono en Ogg, pages de 100 ms (retard ≈ 1 s au lieu de 5 s, POC du cahier § 2), ou MP3 64 kb/s.
Entrée : PCM 16 bits mono 48 kHz, par blocs de taille quelconque ; sortie : octets du flux, à envoyer tels quels.
"""
from __future__ import annotations

import numpy as np

import av

RATE = 48000
SETTINGS = {
    # codec : (format du conteneur, codec PyAV, débit, options du conteneur)
    "opus": ("ogg", "libopus", 32_000, {"page_duration": "100000"}),
    "mp3": ("mp3", "libmp3lame", 64_000, {}),
}


class _Sink:
    """Objet fichier qui recueille les octets écrits par le multiplexeur."""

    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, b: bytes) -> int:
        self.data += b
        return len(b)

    def flush(self) -> None:
        pass


class Encoder:
    def __init__(self, codec: str = "opus") -> None:
        if codec not in SETTINGS:
            raise ValueError(f"codec inconnu : {codec}")
        fmt, name, bitrate, options = SETTINGS[codec]
        self._sink = _Sink()
        self._out = av.open(self._sink, "w", format=fmt, buffer_size=512, options=options,
                            container_options={"flush_packets": "1"})
        self._stream = self._out.add_stream(name, rate=RATE, layout="mono")
        self._stream.bit_rate = bitrate
        self._frame = 960 if codec == "opus" else 1152       # 20 ms en Opus, trame MP3
        self._pending = np.zeros(0, dtype=np.int16)
        self._pts = 0
        self._closed = False

    def push(self, pcm: bytes | np.ndarray) -> bytes:
        """Ajoute du PCM (int16 mono 48 kHz) ; renvoie les octets du flux produits (souvent vides : réserve)."""
        if self._closed:
            return b""
        samples = np.frombuffer(pcm, dtype=np.int16) if isinstance(pcm, (bytes, bytearray, memoryview)) else \
            np.asarray(pcm, dtype=np.int16)
        self._pending = np.concatenate((self._pending, samples)) if self._pending.size else samples.copy()
        while self._pending.size >= self._frame:
            chunk, self._pending = self._pending[:self._frame], self._pending[self._frame:]
            frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = RATE
            frame.pts = self._pts
            self._pts += self._frame
            for packet in self._stream.encode(frame):
                self._out.mux(packet)
        return self._take()

    def close(self) -> bytes:
        if self._closed:
            return b""
        self._closed = True
        for packet in self._stream.encode(None):
            self._out.mux(packet)
        self._out.close()
        return self._take()

    def _take(self) -> bytes:
        data = bytes(self._sink.data)
        self._sink.data.clear()
        return data
