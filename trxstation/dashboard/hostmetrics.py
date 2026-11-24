# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mesures du PC (Linux, stdlib seule) : processeur, mémoire, disque, température, durée de marche, système.

Hors Linux (poste de développement Windows), chaque mesure vaut None : la page affiche « — ».
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

LINUX = sys.platform.startswith("linux")
# capteurs de température préférés, dans l'ordre (hwmon) : processeur Intel, AMD, puis zone thermique générique
CPU_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_thermal", "acpitz")


class CpuMeter:
    """Charge de tous les cœurs entre deux lectures (None à la première lecture)."""

    def __init__(self, proc: Path = Path("/proc")):
        self.proc, self._prev = proc, None

    def read(self) -> float | None:
        if not LINUX:
            return None
        try:
            with open(self.proc / "stat", encoding="ascii") as handle:
                values = [int(v) for v in handle.readline().split()[1:]]
        except (OSError, ValueError):
            return None
        idle, total = values[3] + (values[4] if len(values) > 4 else 0), sum(values[:8])
        prev, self._prev = self._prev, (idle, total)
        if prev is None or total <= prev[1]:
            return None
        return max(0.0, min(100.0, 100.0 * (1 - (idle - prev[0]) / (total - prev[1]))))


def memory_pct(proc: Path = Path("/proc")) -> float | None:
    if not LINUX:
        return None
    try:
        info = {}
        with open(proc / "meminfo", encoding="ascii") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
        total, avail = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0))
        return 100.0 * (total - avail) / total if total else None
    except (OSError, ValueError, KeyError, IndexError):
        return None


def disk_pct(path: str = "/") -> float | None:
    try:
        usage = shutil.disk_usage(path)
        return 100.0 * usage.used / usage.total if usage.total else None
    except OSError:
        return None


def cpu_temp(sys_root: Path = Path("/sys")) -> float | None:
    """Température du processeur en °C : capteur hwmon reconnu, sinon la zone thermique la plus chaude."""
    if not LINUX:
        return None
    found: dict[str, float] = {}
    for hw in sorted((sys_root / "class/hwmon").glob("hwmon*")):
        try:
            name = (hw / "name").read_text(encoding="ascii").strip()
        except OSError:
            continue
        temps = []
        for t in hw.glob("temp*_input"):
            try:
                temps.append(int(t.read_text(encoding="ascii")) / 1000)
            except (OSError, ValueError):
                pass
        if temps:
            found[name] = max(temps)
    for name in CPU_SENSORS:
        if name in found:
            return found[name]
    zones = []
    for z in (sys_root / "class/thermal").glob("thermal_zone*"):
        try:
            zones.append(int((z / "temp").read_text(encoding="ascii")) / 1000)
        except (OSError, ValueError):
            pass
    return max(zones) if zones else None


def uptime_s(proc: Path = Path("/proc")) -> float | None:
    if not LINUX:
        return None
    try:
        return float((proc / "uptime").read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def os_name() -> str:
    """« Debian 13 », d'après /etc/os-release ; sinon le nom du système."""
    try:
        fields = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            fields[key] = value.strip().strip('"')
        name, version = fields.get("NAME", ""), fields.get("VERSION_ID", "")
        if name:
            return f"{name.split()[0]} {version}".strip()
    except OSError:
        pass
    return platform.system() or os.name


class HostMonitor:
    def __init__(self, disk_path: str = "/"):
        self.cpu, self.disk_path, self.os = CpuMeter(), disk_path, os_name()

    def read(self) -> dict:
        return {"cpu": self.cpu.read(), "mem": memory_pct(), "disk": disk_pct(self.disk_path),
                "temp": cpu_temp(), "uptime_s": uptime_s(), "os": self.os}
