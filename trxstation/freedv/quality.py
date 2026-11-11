# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Synchro confirmée et note de qualité d'une séquence reçue (calculs purs, sans horloge propre).

Seuils tirés du banc SNR de l'investigation F0 (2026-11-10, RADE V1, SNR dans 3 kHz) :
  - bruit seul : synchro tenue dès -4 dB, bonne qualité dès +1 dB ;
  - évanouissements HF moyens (MPP) : sans coupure dès +1 dB, bonne qualité dès +6 dB ;
  - le SNR ESTIMÉ par RADE est 2 à 3 dB sous le vrai en évanouissements.
En direct, une fausse synchro sur le bruit dure environ 1 s : la synchro n'est « confirmée »
qu'après min_sync_s de synchro continue.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class SyncFilter:
    """Synchro confirmée après min_sync_s de synchro continue ; perdue après hold_s hors synchro.

    Les pertes brèves (< hold_s) d'un vrai signal ne la font pas tomber.
    """

    def __init__(self, min_sync_s: float = 2.0, hold_s: float = 1.0) -> None:
        self.min_sync_s, self.hold_s = min_sync_s, hold_s
        self.confirmed = False
        self._sync_since: float | None = None
        self._unsync_since: float | None = None

    def reset(self) -> None:
        self.confirmed = False
        self._sync_since = self._unsync_since = None

    def update(self, state: str, t: float) -> bool:
        if state == "sync":
            self._unsync_since = None
            if self._sync_since is None:
                self._sync_since = t
            if not self.confirmed and t - self._sync_since >= self.min_sync_s:
                self.confirmed = True
        else:
            self._sync_since = None
            if self._unsync_since is None:
                self._unsync_since = t
            if self.confirmed and t - self._unsync_since >= self.hold_s:
                self.confirmed = False
        return self.confirmed


def quality_note(samples: list[tuple[bool, float]], resyncs: int, duration_s: float) -> tuple[int, str]:
    """Note de 1 à 5 d'une séquence ; samples = [(synchronisé, SNR estimé)]."""
    sy = sorted(s for ok, s in samples if ok)
    if not samples or not sy:
        return 1, "jamais synchronisé"
    m = sy[len(sy) // 2]
    f = len(sy) / len(samples)
    n = 5 if m >= 6 else 4 if m >= 3 else 3 if m >= 0 else 2 if m >= -3 else 1
    if f < 0.5:
        n -= 2
    elif f < 0.8:
        n -= 1
    if duration_s > 0 and resyncs / max(duration_s / 60, 0.5) > 3:
        n -= 1
    if duration_s < 3:
        n = min(n, 2)
    n = max(1, min(5, n))
    return n, f"SNR médian {m:+.1f} dB, synchro {round(100 * f)} %, {resyncs} perte(s) de synchro"


@dataclass
class Sequence:
    """Une séquence de voix décodée : de la première voix à end_after_s sans voix."""
    start: float
    voice_s: float = 0.0
    samples: list[tuple[bool, float]] = field(default_factory=list)
    resyncs: int = 0
    callsigns: list[str] = field(default_factory=list)
    _prev_ok: bool = True
    _last_sample: float = -1e9

    def sample(self, t: float, synced: bool, snr: float | None, every_s: float = 0.5) -> None:
        if t - self._last_sample < every_s:
            return
        self._last_sample = t
        if synced and not self._prev_ok:
            self.resyncs += 1
        self._prev_ok = synced
        self.samples.append((synced, snr if snr is not None else 0.0))

    def note(self) -> tuple[int, str]:
        return quality_note(self.samples, self.resyncs, self.voice_s)
