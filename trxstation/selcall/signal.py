# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Générateur de la trame SELCALL (cahier des charges § 3) : tons à phase continue, rampe en cosinus de 5 ms au
début et à la fin de chaque ton. Sert à l'émission (lot 3) et aux essais (fichiers WAV synthétiques)."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from . import protocol as p


def synthesize(code: str, rate: int = 8000, *, offset_hz: float = 0.0, level_dbfs: float = p.TX_LEVEL_DBFS,
               drift_hz: float = 0.0) -> np.ndarray:
    """Trame en float32 (-1..1). `drift_hz` : dérive linéaire de la fréquence sur toute la trame (essais)."""
    plan = p.tones(code, offset_hz)
    total = sum(int(round(d * rate)) for _, d in plan)
    out = np.empty(total, dtype=np.float64)
    amp = 10 ** (level_dbfs / 20)
    ramp_n = max(1, int(round(p.RAMP_S * rate)))
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp_n) / ramp_n)
    phase, pos = 0.0, 0
    for hz, dur in plan:
        n = int(round(dur * rate))
        t = (pos + np.arange(n)) / total                               # avancement dans la trame (dérive)
        inst = hz + drift_hz * t
        ph = phase + 2 * np.pi * np.cumsum(inst) / rate
        tone = amp * np.sin(ph)
        tone[:ramp_n] *= ramp
        tone[-ramp_n:] *= ramp[::-1]
        out[pos:pos + n] = tone
        phase = float(ph[-1]) % (2 * np.pi)
        pos += n
    return out.astype(np.float32)


def write_wav(path: str | Path, samples: np.ndarray, rate: int = 8000) -> None:
    """WAV mono 16 bits (essais, étape trx-hwtest)."""
    pcm = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
