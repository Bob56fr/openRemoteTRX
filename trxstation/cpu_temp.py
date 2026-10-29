# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Température du PROCESSEUR de la station (Linux), lue directement dans /sys : stdlib seule, aucun paquet.

lm-sensors (« coretemp-isa-0000 ») ne fait que lire les mêmes fichiers (/sys/class/hwmon). L'ancienne lecture de
thermal_zone0 donnait souvent le capteur ACPI de la carte mère (« acpitz » : 28 °C sur minix-bzh pour un processeur
à 42 °C) : elle n'est plus jamais utilisée seule.

Ordre de recherche :
  1. capteurs hwmon du processeur : coretemp (Intel, « Package id 0 » sinon le cœur le plus chaud), k10temp et
     zenpower (AMD, Tctl/Tdie sinon le plus chaud), cpu_thermal (Raspberry Pi) ;
  2. zones thermiques du processeur : x86_pkg_temp, cpu-thermal, cpu_thermal, soc_thermal ;
  3. rien : None (la valeur est « inconnue », jamais celle de la carte mère).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HWMON_CHIPS = ("coretemp", "k10temp", "zenpower", "cpu_thermal")
PREFERRED_LABELS = ("Package id 0", "Tctl", "Tdie")
THERMAL_TYPES = ("x86_pkg_temp", "cpu-thermal", "cpu_thermal", "soc_thermal")
SANE_C = (-40.0, 150.0)


@dataclass(frozen=True)
class CpuTemp:
    celsius: float
    source: str                     # ex. « coretemp Package id 0 », « thermal x86_pkg_temp »


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _milli(text: str | None) -> float | None:
    try:
        value = int(text) / 1000.0
    except (TypeError, ValueError):
        return None
    return value if SANE_C[0] <= value <= SANE_C[1] else None


def _hwmon(root: Path) -> CpuTemp | None:
    try:
        chips = sorted((root / "class" / "hwmon").iterdir())
    except OSError:
        return None
    found: dict[str, list[tuple[str, float]]] = {}
    for chip in chips:
        name = _read(chip / "name")
        if name not in HWMON_CHIPS:
            continue
        for sensor in sorted(chip.glob("temp*_input")):
            value = _milli(_read(sensor))
            if value is not None:
                label = _read(sensor.with_name(sensor.name.replace("_input", "_label"))) or sensor.name
                found.setdefault(name, []).append((label, value))
    for name in HWMON_CHIPS:
        readings = found.get(name)
        if readings:
            preferred = [(lab, v) for lab, v in readings if lab in PREFERRED_LABELS]
            label, value = preferred[0] if preferred else max(readings, key=lambda r: r[1])
            return CpuTemp(value, f"{name} {label}")
    return None


def _thermal(root: Path) -> CpuTemp | None:
    try:
        zones = sorted((root / "class" / "thermal").glob("thermal_zone*"))
    except OSError:
        return None
    for wanted in THERMAL_TYPES:
        for zone in zones:
            if _read(zone / "type") == wanted:
                value = _milli(_read(zone / "temp"))
                if value is not None:
                    return CpuTemp(value, f"thermal {wanted}")
    return None


def read_cpu_temp(sys_root: str | Path = "/sys") -> CpuTemp | None:
    """Température du processeur, ou None si aucun capteur du processeur n'est lisible (Windows, machine virtuelle)."""
    root = Path(sys_root)
    return _hwmon(root) or _thermal(root)


def cpu_celsius(sys_root: str | Path = "/sys") -> float | None:
    found = read_cpu_temp(sys_root)
    return None if found is None else found.celsius
