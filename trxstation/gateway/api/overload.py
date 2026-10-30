# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Protection de la station contre la charge des VISITEURS (docs/visiteurs-cahier-des-charges.md § 10, décision de
l'utilisateur du 2026-10-30). L'opérateur passe toujours avant les visiteurs.

Coupure : une des conditions dure HOLD_S (10 s) :
  * processeur >= temp_c (85 °C ; ignoré si la température est inconnue : cpu_temp.py) ;
  * charge de tous les cœurs >= cpu_pct (90 %) ;
  * retard de la boucle de la passerelle > lag_ms (100 ms) : l'audio et la sécurité d'émission en souffrent ;
  * mémoire libre < mem_pct (10 %).
=> visiteurs déconnectés avec un message précis, nouvelles connexions refusées (motif `station_overload`).

Réouverture : TOUT est repassé sous les seuils de retour (temp_c - 10, 70 %, lag_ms / 2, mem_pct + 5) sans
interruption pendant REOPEN_S (5 min). Après MAX_PER_HOUR (3) coupures en une heure ayant déconnecté des visiteurs :
fermé jusqu'à une réouverture À LA MAIN (console menu 20, page de l'opérateur), acceptée seulement au vert.
Pur Python, horloge et mesures injectables. Ne touche JAMAIS au poste ni à l'émission.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

HOLD_S = 10.0
REOPEN_S = 300.0
MAX_PER_HOUR = 3


@dataclass
class Sample:
    temp_c: float | None = None
    cpu_pct: float | None = None
    lag_ms: float | None = None
    mem_free_pct: float | None = None


@dataclass
class Limits:
    temp_c: float = 85.0
    cpu_pct: float = 90.0
    lag_ms: float = 100.0
    mem_pct: float = 10.0

    def over(self, s: Sample) -> str:
        """Premier dépassement (texte pour l'humain), ou vide."""
        if s.temp_c is not None and s.temp_c >= self.temp_c:
            return f"processeur à {s.temp_c:.0f} °C"
        if s.cpu_pct is not None and s.cpu_pct >= self.cpu_pct:
            return f"processeur occupé à {s.cpu_pct:.0f} %"
        if s.lag_ms is not None and s.lag_ms > self.lag_ms:
            return f"passerelle en retard de {s.lag_ms:.0f} ms"
        if s.mem_free_pct is not None and s.mem_free_pct < self.mem_pct:
            return f"mémoire libre à {s.mem_free_pct:.0f} %"
        return ""

    def green(self, s: Sample) -> bool:
        """Nettement sous les seuils (écart : pas de bascule permanente autour d'une valeur)."""
        return ((s.temp_c is None or s.temp_c <= self.temp_c - 10) and (s.cpu_pct is None or s.cpu_pct <= 70)
                and (s.lag_ms is None or s.lag_ms <= self.lag_ms / 2)
                and (s.mem_free_pct is None or s.mem_free_pct >= self.mem_pct + 5))


@dataclass
class _State:
    reason: str = ""                 # dépassement qui a fermé l'écoute ; vide = ouverte
    since: float = 0.0
    green_since: float | None = None
    locked: bool = False             # trop de coupures : réouverture à la main seulement
    over_since: float | None = None
    cuts: deque = field(default_factory=deque)


class OverloadGuard:
    def __init__(self, sample: Callable[[], Sample], limits: Limits | None = None, *,
                 clock: Callable[[], float] = time.monotonic):
        self.sample, self.limits, self.clock = sample, limits or Limits(), clock
        self._s = _State()
        self.last = Sample()

    @property
    def suspended(self) -> bool:
        return bool(self._s.reason)

    def message(self) -> str:
        if not self._s.reason:
            return ""
        tail = (" Trop de coupures en une heure : l'opérateur doit la rouvrir." if self._s.locked
                else " Réouverture automatique après 5 minutes de fonctionnement normal.")
        return f"Station surchargée ({self._s.reason}) : écoute des visiteurs suspendue pour protéger la station.{tail}"

    def step(self, listeners: int) -> bool:
        """Une mesure par seconde. Vrai = il faut déconnecter les visiteurs MAINTENANT (passage en surcharge)."""
        now, s = self.clock(), self._s
        self.last = sample = self.sample()
        over = self.limits.over(sample)
        if not s.reason:
            if not over:
                s.over_since = None
                return False
            if s.over_since is None:
                s.over_since = now
            if now - s.over_since < HOLD_S:
                return False
            s.reason, s.since, s.green_since, s.over_since = over, now, None, None
            if listeners:
                s.cuts.append(now)
                while s.cuts and now - s.cuts[0] > 3600:
                    s.cuts.popleft()
                s.locked = len(s.cuts) >= MAX_PER_HOUR
            return listeners > 0
        if over and listeners:                       # coupé mais des visiteurs encore là (réouverture à la main trop tôt)
            return True
        if self.limits.green(sample):
            if s.green_since is None:
                s.green_since = now
            if not s.locked and now - s.green_since >= REOPEN_S:
                s.reason = ""
        else:
            s.green_since = None
        return False

    def reopen(self) -> str:
        """Réouverture à la main. Rend le refus (texte) ou vide si l'écoute est rouverte."""
        if not self._s.reason:
            return ""
        if not self.limits.green(self.last):
            return "Refusé : la station n'est pas encore revenue à la normale (" + (self.limits.over(self.last) or
                                                                                     "pas assez sous les seuils") + ")."
        self._s = _State(cuts=self._s.cuts)
        return ""

    def status(self) -> dict | None:
        s = self._s
        if not s.reason:
            return None
        remaining = None
        if not s.locked:
            remaining = round(REOPEN_S - (self.clock() - s.green_since)) if s.green_since is not None else round(REOPEN_S)
        return {"reason": s.reason, "message": self.message(), "since_s": int(self.clock() - s.since),
                "locked": s.locked, "reopen_in_s": remaining}


# ---------------------------------------------------------------------- mesures réelles (Linux ; None ailleurs)

class LagMeter:
    """Pire retard d'un réveil de 50 ms de la boucle asyncio de la passerelle, depuis la dernière lecture."""

    def __init__(self, tick_s: float = 0.05):
        self.tick_s, self.worst = tick_s, 0.0

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            start = time.perf_counter()
            await asyncio.sleep(self.tick_s)
            self.worst = max(self.worst, time.perf_counter() - start - self.tick_s)

    def take_ms(self) -> float:
        worst, self.worst = self.worst, 0.0
        return 1000.0 * worst


class CpuLoad:
    """Charge de tous les cœurs entre deux lectures de /proc/stat (None si illisible)."""

    def __init__(self, path: str = "/proc/stat"):
        self.path, self._prev = path, None

    def read(self) -> float | None:
        try:
            with open(self.path, encoding="ascii") as handle:
                values = [int(v) for v in handle.readline().split()[1:]]
        except (OSError, ValueError):
            return None
        idle, total = values[3] + (values[4] if len(values) > 4 else 0), sum(values)
        prev, self._prev = self._prev, (idle, total)
        if prev is None or total <= prev[1]:
            return None
        return 100.0 * (1.0 - (idle - prev[0]) / (total - prev[1]))


def mem_free_pct(path: str = "/proc/meminfo") -> float | None:
    try:
        info = {}
        with open(path, encoding="ascii") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
        return 100.0 * info["MemAvailable"] / info["MemTotal"]
    except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError):
        return None


def system_sampler(lag: LagMeter) -> Callable[[], Sample]:
    from ...cpu_temp import cpu_celsius
    cpu = CpuLoad()

    def sample() -> Sample:
        return Sample(cpu_celsius(), cpu.read(), lag.take_ms(), mem_free_pct())
    return sample
