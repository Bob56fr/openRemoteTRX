# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Ports série : liste et présence, sous Linux/Pi et sous Windows (sans dépendance).

Sous Windows, les ports COM sont lus dans le registre (winreg, bibliothèque standard).
"""
from __future__ import annotations

import glob
import os
import re
import sys
from collections.abc import Callable


def _natural(name: str) -> tuple[str, int]:
    match = re.search(r"(\d+)$", name)
    return re.sub(r"\d+$", "", name).upper(), int(match.group(1)) if match else 0


def _registry_com_ports() -> list[str]:
    import winreg  # type: ignore[import-not-found]  # Windows uniquement
    found: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
            index = 0
            while True:
                try:
                    found.append(str(winreg.EnumValue(key, index)[1]))
                except OSError:
                    break
                index += 1
    except OSError:
        pass
    return found


def windows_com_ports(registry: Callable[[], list[str]] | None = None) -> list[str]:
    values = (registry or _registry_com_ports)()
    return sorted({v.upper() for v in values if re.fullmatch(r"COM\d+", v, re.IGNORECASE)}, key=_natural)


def list_serial_ports(platform: str | None = None, *, registry: Callable[[], list[str]] | None = None,
                      globber: Callable[[str], list[str]] = glob.glob) -> list[str]:
    plat = platform or sys.platform
    if plat == "win32":
        return windows_com_ports(registry)
    by_id = sorted(globber("/dev/serial/by-id/*"))       # noms stables après un redémarrage
    if by_id:
        return by_id
    patterns = ["/dev/ttyUSB*", "/dev/ttyACM*"]
    if plat == "darwin":
        patterns += ["/dev/cu.usbserial*", "/dev/cu.usbmodem*"]
    return sorted(p for pattern in patterns for p in globber(pattern))


def port_present(port: str, platform: str | None = None, *,
                 registry: Callable[[], list[str]] | None = None) -> bool:
    if (platform or sys.platform) == "win32":
        name = port.upper().removeprefix("\\\\.\\")      # accepte aussi \\.\COM10
        return name in windows_com_ports(registry)
    return os.path.exists(port)
