"""Outils PCM en Python pur (sans numpy) : mono, 48 kHz, 16 bits, trames de 20 ms."""
from __future__ import annotations

import math
import sys
from array import array

SAMPLE_RATE = 48000
FRAME_S = 0.02
FRAME_SAMPLES = 960                    # 20 ms à 48 kHz
FRAME_BYTES = FRAME_SAMPLES * 2
FLOOR_DB = -90.0


def to_samples(pcm: bytes) -> array:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def to_bytes(samples: array) -> bytes:
    if sys.byteorder == "big":
        samples = array("h", samples)
        samples.byteswap()
    return samples.tobytes()


def rms_dbfs(pcm: bytes) -> float:
    samples = to_samples(pcm)
    if not samples:
        return FLOOR_DB
    mean_square = sum(s * s for s in samples) / len(samples)
    if mean_square <= 0:
        return FLOOR_DB
    return max(FLOOR_DB, 10 * math.log10(mean_square / (32768.0 ** 2)))


def apply_gain(pcm: bytes, db: float) -> bytes:
    if db == 0:
        return pcm
    gain = 10 ** (db / 20)
    return to_bytes(array("h", (max(-32768, min(32767, int(s * gain))) for s in to_samples(pcm))))


def silence(samples: int = FRAME_SAMPLES) -> bytes:
    return bytes(samples * 2)


def tone(freq_hz: float, level_db: float = -20.0, start_sample: int = 0, samples: int = FRAME_SAMPLES) -> bytes:
    amplitude = 32767 * 10 ** (level_db / 20)
    step = 2 * math.pi * freq_hz / SAMPLE_RATE
    return to_bytes(array("h", (int(amplitude * math.sin(step * (start_sample + i))) for i in range(samples))))


def downmix_stereo(pcm: bytes) -> bytes:
    samples = to_samples(pcm)
    return to_bytes(array("h", ((samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples) - 1, 2))))


class FrameAssembler:
    """Recoupe un flux d'octets PCM en trames de 20 ms exactes (le reste attend la suite)."""

    def __init__(self, max_backlog_frames: int = 25):
        self._buffer = bytearray()
        self._max = max_backlog_frames * FRAME_BYTES

    def feed(self, pcm: bytes) -> list[bytes]:
        self._buffer += pcm
        if len(self._buffer) > self._max:                      # retard anormal : on garde le plus récent
            del self._buffer[: len(self._buffer) - self._max]
        frames = []
        while len(self._buffer) >= FRAME_BYTES:
            frames.append(bytes(self._buffer[:FRAME_BYTES]))
            del self._buffer[:FRAME_BYTES]
        return frames
