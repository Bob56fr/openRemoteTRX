# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sources de données de trx-monitor : fichier d'état de la passerelle, mode sûr, matériel.

Lecture seule. La fraîcheur de la passerelle se juge sur le changement de `seq`
(horloge monotone locale), comme dans le superviseur.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from ..status import GatewayWatch, read_status
from ..supervisor.state import StateStore
from .model import Snapshot, SystemInfo


def _read_float(path: Path, scale: float = 1.0) -> float | None:
    try:
        return float(path.read_text().split()[0]) / scale
    except (OSError, ValueError, IndexError):
        return None


def read_system_info(proc: str = "/proc", thermal: str = "/sys/class/thermal/thermal_zone0/temp") -> SystemInfo:
    """Température, charge, mémoire libre, disponibilité (Linux ; champs None ailleurs)."""
    mem = None
    try:
        for line in (Path(proc) / "meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                mem = int(line.split()[1]) / 1024.0
                break
    except (OSError, ValueError, IndexError):
        pass
    return SystemInfo(temp_c=_read_float(Path(thermal), 1000.0), load1=_read_float(Path(proc) / "loadavg"),
                      mem_available_mb=mem, uptime_s=_read_float(Path(proc) / "uptime"))


class StatusSource:
    def __init__(self, status_path: str | Path, state_dir: str | Path, stale_after_s: float = 2.0, *,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 system_reader: Callable[[], SystemInfo] = read_system_info):
        self.status_path = Path(status_path)
        self.store = StateStore(state_dir)           # utilisé en lecture seule (safe_mode())
        self.watch = GatewayWatch(stale_after_s)
        self.clock, self.sleep, self.system_reader = clock, sleep, system_reader

    def poll(self) -> Snapshot:
        status = read_status(self.status_path)
        now = self.clock()
        self.watch.update(status, now)
        return Snapshot(status=status, gateway_fresh=self.watch.fresh(now),
                        stale_s=self.watch.age(now) if status is not None else None,
                        safe_mode=self.store.safe_mode(), system=self.system_reader())

    def poll_once(self, wait_s: float = 0.6) -> Snapshot:
        """Pour une capture unique (--once) : deux lectures espacées ; figée si `seq` n'a pas bougé."""
        first = self.poll()
        if first.status is None:
            return first
        self.sleep(wait_s)
        second = self.poll()
        if second.status is not None and second.status.seq != first.status.seq:
            return second
        return Snapshot(status=second.status, gateway_fresh=False, stale_s=wait_s,
                        safe_mode=second.safe_mode, system=second.system)
