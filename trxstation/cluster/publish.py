# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Spots envoyés aux pages : ceux de la BANDE COURANTE du poste, instantané puis changements.

- Fenêtre : la bande (plan IARU R1, 11 m compris) qui contient la fréquence du
  poste, sinon ±500 kHz (la plus grande largeur du spectre d'un IC-7300).
  Le spectre HF montré par la page est toujours dans cette fenêtre (sauf
  réglage FIX hors bande, rare) ; la page n'affiche que sa plage visible.
- Messages `{"kind": "spots", "scope": "hf_view", "retain": …}` : la passerelle
  ne les envoie qu'aux clients qui affichent la vue HF, et rejoue l'instantané
  et les changements retenus à celui qui l'ouvre.
- `snapshot` : à chaque changement de fenêtre et toutes les 60 s (corrige toute
  dérive) ; `delta` : ajouts, mises à jour et retraits, regroupés (1 s au plus).
- Au plus 150 spots par instantané (les plus récents) : un message reste petit
  (environ 25 ko au pire).
"""

from __future__ import annotations

from .bandplan import BANDS, hamlib_mode
from .cache import Spot, SpotCache

SNAPSHOT_EVERY_S = 60.0
MAX_SPOTS = 150
FALLBACK_HALF_KHZ = 500.0


def window_for(freq_hz: int | float | None) -> tuple[float, float] | None:
    """(début, fin) en kHz de la bande du poste ; None si la fréquence est inconnue."""
    if not freq_hz or freq_hz <= 0:
        return None
    khz = freq_hz / 1000.0
    for _name, lo, hi in BANDS:
        if lo <= khz <= hi:
            return lo, hi
    return khz - FALLBACK_HALF_KHZ, khz + FALLBACK_HALF_KHZ


def compact(s: Spot, now: float) -> dict:
    """Spot pour la page (clés courtes : données mobiles)."""
    out = {"id": s.id, "f": round(s.freq_khz, 2), "dx": s.dx, "de": s.spotter, "m": s.mode or "",
           "k": s.kind, "t": s.time_utc, "n": s.count, "age": max(0, int(now - s.last_seen))}
    if s.mode_guessed:
        out["mg"] = 1
    if s.comment:
        out["c"] = s.comment
    if s.country:
        out["co"] = s.country
    if s.continent:
        out["ct"] = s.continent
    q = hamlib_mode(s.mode or "", s.freq_khz)
    if q:
        out["q"] = q                                   # mode proposé pour le QSY
    return out


class SpotPublisher:
    def __init__(self, cache: SpotCache) -> None:
        self.cache = cache
        self.window: tuple[float, float] | None = None
        self.sent: set[int] = set()
        self._upserts: dict[int, Spot] = {}
        self._need_snapshot = False
        self._last_snapshot = float("-inf")

    def set_frequency(self, freq_hz: int | float | None) -> None:
        win = window_for(freq_hz)
        if win != self.window:
            self.window = win
            self._need_snapshot = True

    def _inside(self, s: Spot) -> bool:
        return self.window is not None and self.window[0] <= s.freq_khz <= self.window[1]

    def on_spot(self, s: Spot, new: bool) -> None:
        if self._inside(s) or s.id in self.sent:       # sorti de la fenêtre : le retrait suivra
            self._upserts[s.id] = s

    def tick(self, now: float) -> dict | None:
        """Message à envoyer maintenant (instantané ou changements), ou None."""
        if self.window is None:
            return None
        if self._need_snapshot or now - self._last_snapshot >= SNAPSHOT_EVERY_S:
            return self._snapshot(now)
        live = {s.id for s in self.cache.spots()}
        upserts = [s for sid, s in self._upserts.items() if sid in live and self._inside(s)]
        removed = sorted((self.sent - live) | {sid for sid, s in self._upserts.items()
                                              if sid in self.sent and (sid not in live or not self._inside(s))})
        self._upserts.clear()
        room = MAX_SPOTS - len(self.sent - set(removed))
        kept = []
        for s in upserts:                              # au-delà de MAX_SPOTS, les nouveaux attendent l'instantané
            if s.id in self.sent or room > 0:
                room -= s.id not in self.sent
                kept.append(s)
        upserts = kept
        if not upserts and not removed:
            return None
        self.sent = (self.sent - set(removed)) | {s.id for s in upserts}
        return {"kind": "spots", "op": "delta", "scope": "hf_view", "retain": "delta",
                "spots": [compact(s, now) for s in upserts], "removed": removed}

    def _snapshot(self, now: float) -> dict:
        lo, hi = self.window
        spots = sorted(self.cache.in_range(lo, hi), key=lambda s: s.last_seen, reverse=True)[:MAX_SPOTS]
        self.sent = {s.id for s in spots}
        self._upserts.clear()
        self._need_snapshot = False
        self._last_snapshot = now
        return {"kind": "spots", "op": "snapshot", "scope": "hf_view", "retain": "snapshot",
                "window": [lo, hi], "spots": [compact(s, now) for s in spots]}
