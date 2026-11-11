# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Son du poste (int16, 48 / 16 / 8 kHz) vers l'entrée de radae_rx : complexe float32 à 8 kHz.

Mise à l'échelle relevée à l'investigation F0 : réel = int16 / 8192 (soit int16 * 2 / 16384,
comme rade_rx_wav), partie imaginaire nulle ; radae_rx n'a pas besoin du signal analytique.
Filtre passe-bas à fenêtre (coupure 3,4 kHz) avec mémoire entre morceaux : aucun clic aux jonctions.
"""
from __future__ import annotations

import numpy as np

OUT_RATE = 8000
SCALE = 1.0 / 8192.0


def lowpass_taps(rate: int, cutoff: float = 3400.0, ntaps: int = 97) -> np.ndarray:
    n = np.arange(ntaps) - (ntaps - 1) / 2
    h = 2 * cutoff / rate * np.sinc(2 * cutoff / rate * n) * np.blackman(ntaps)
    return h / h.sum()


class ToRadaeIQ:
    def __init__(self, in_rate: int) -> None:
        if in_rate % OUT_RATE or in_rate < OUT_RATE:
            raise ValueError(f"fréquence d'échantillonnage {in_rate} Hz : multiple de 8000 Hz exigé")
        self.factor = in_rate // OUT_RATE
        self.taps = lowpass_taps(in_rate) if self.factor > 1 else np.ones(1)
        self._hist = np.zeros(len(self.taps) - 1)
        self._phase = 0        # indice, dans le prochain bloc filtré, du prochain échantillon gardé

    def process(self, pcm: bytes) -> bytes:
        x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float64)
        if not len(x):
            return b""
        buf = np.concatenate([self._hist, x])
        y = np.convolve(buf, self.taps, mode="valid")          # len(y) == len(x)
        self._hist = buf[len(buf) - (len(self.taps) - 1):]
        kept = y[self._phase :: self.factor]
        self._phase = (self._phase - len(y)) % self.factor
        iq = np.zeros(2 * len(kept), dtype="<f4")
        iq[0::2] = kept * SCALE
        return iq.tobytes()
