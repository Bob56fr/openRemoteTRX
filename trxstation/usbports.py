# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Identité USB d'un port série (bibliothèque standard seulement) : « 10C4:EA70 SN=01D0F21E IF=00 ».

Sert à vérifier, avant un allumage à distance, que le port de station.toml est TOUJOURS celui du poste
(docs/alimentation-poste-cahier-des-charges.md § 4.1) : sous Windows, un numéro COM peut changer avec la prise USB ;
un poste à deux ports (CP2105 du FTDX10 : interface 00 « Enhanced », 01 « Standard ») ne doit jamais être confondu.
Ce module ne fait que LIRE (registre de Windows, /sys de Linux) : il n'ouvre jamais un port (ouvrir un port série
peut lever RTS / DTR, donc un PTT).

Identité : fabricant:produit en hexadécimal majuscule, numéro de série du périphérique USB s'il en a un (stable d'une
prise à l'autre), numéro d'interface pour un périphérique composite. Sans numéro de série, l'identité reste partielle
(deux adaptateurs identiques ne se distinguent pas) : `same_device` le dit.
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

IDENTITY_RE = re.compile(r"^(?P<vid>[0-9A-F]{4}):(?P<pid>[0-9A-F]{4})(?: SN=(?P<sn>[A-Za-z0-9_.&-]{1,64}))?"
                         r"(?: IF=(?P<iface>[0-9A-F]{2}))?$")
_WIN_ID_RE = re.compile(r"^VID_(?P<vid>[0-9A-F]{4})&PID_(?P<pid>[0-9A-F]{4})(?:&MI_(?P<iface>[0-9A-F]{2}))?$", re.I)


@dataclass(frozen=True)
class UsbIdentity:
    vid: str
    pid: str
    serial: str = ""
    interface: str = ""

    def __str__(self) -> str:
        text = f"{self.vid}:{self.pid}"
        if self.serial:
            text += f" SN={self.serial}"
        if self.interface:
            text += f" IF={self.interface}"
        return text


def parse_identity(text: str) -> UsbIdentity | None:
    match = IDENTITY_RE.fullmatch((text or "").strip())
    if match is None:
        return None
    return UsbIdentity(match["vid"], match["pid"], match["sn"] or "", match["iface"] or "")


def _clean_serial(serial: str) -> str:
    """Numéro de série gardé tel quel s'il est sûr ; « & » de Windows = identifiant fabriqué par Windows, pas un numéro."""
    serial = re.sub(r"\s+", "_", (serial or "").strip())   # IC-7300MK2 : « IC-7300MK2 13003336 » (sysfs, 2026-11-19)
    if not serial or "&" in serial or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", serial):
        return ""
    return serial


# ------------------------------------------------------------------ Windows (registre)

def _windows_entries(registry: Callable[[], list[tuple[str, str, str, str]]] | None = None) -> list[tuple[str, str, str, str]]:
    """(identifiant du matériel, instance, PortName, ParentIdPrefix) de chaque entrée HKLM\\…\\Enum\\USB."""
    if registry is not None:
        return registry()
    import winreg  # type: ignore[import-not-found]  # Windows uniquement
    found: list[tuple[str, str, str, str]] = []
    base = r"SYSTEM\CurrentControlSet\Enum\USB"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return found
    with root:
        i = 0
        while True:
            try:
                hardware = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                hkey = winreg.OpenKey(root, hardware)
            except OSError:
                continue
            with hkey:
                j = 0
                while True:
                    try:
                        instance = winreg.EnumKey(hkey, j)
                    except OSError:
                        break
                    j += 1
                    port = prefix = ""
                    try:
                        with winreg.OpenKey(hkey, instance) as ikey:
                            try:
                                prefix = str(winreg.QueryValueEx(ikey, "ParentIdPrefix")[0])
                            except OSError:
                                pass
                            try:
                                with winreg.OpenKey(ikey, "Device Parameters") as dkey:
                                    port = str(winreg.QueryValueEx(dkey, "PortName")[0])
                            except OSError:
                                pass
                    except OSError:
                        continue
                    found.append((hardware, instance, port, prefix))
    return found


def _windows_identity(port: str, entries: list[tuple[str, str, str, str]]) -> UsbIdentity | None:
    name = port.upper().removeprefix("\\\\.\\")
    for hardware, instance, port_name, _ in entries:
        if port_name.upper() != name:
            continue
        match = _WIN_ID_RE.fullmatch(hardware)
        if match is None:
            continue
        vid, pid, iface = match["vid"].upper(), match["pid"].upper(), (match["iface"] or "").upper()
        serial = _clean_serial(instance)
        if iface:                                   # composite : le numéro est celui du périphérique parent
            serial = ""
            for parent_hw, parent_instance, _, parent_prefix in entries:
                parent = _WIN_ID_RE.fullmatch(parent_hw)
                if (parent is not None and not parent["iface"] and parent["vid"].upper() == vid
                        and parent["pid"].upper() == pid and parent_prefix
                        and instance.lower().startswith(parent_prefix.lower() + "&")):
                    serial = _clean_serial(parent_instance)
                    break
        return UsbIdentity(vid, pid, serial, iface)
    return None


# ------------------------------------------------------------------ Linux (sysfs)

def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _linux_identity(port: str, sys_root: Path) -> UsbIdentity | None:
    try:
        tty = os.path.basename(os.path.realpath(port))          # /dev/serial/by-id/… -> ttyUSB0
    except OSError:
        return None
    device = sys_root / "class" / "tty" / tty / "device"
    try:
        node = Path(os.path.realpath(device))
    except OSError:
        return None
    iface = ""
    for candidate in (node, *node.parents):                      # remonte jusqu'au périphérique USB (idVendor)
        if not iface and (candidate / "bInterfaceNumber").exists():
            iface = _read(candidate / "bInterfaceNumber").upper().zfill(2)[-2:]
        vid = _read(candidate / "idVendor")
        if vid:
            pid = _read(candidate / "idProduct")
            if not re.fullmatch(r"[0-9a-fA-F]{4}", vid) or not re.fullmatch(r"[0-9a-fA-F]{4}", pid):
                return None
            return UsbIdentity(vid.upper(), pid.upper(), _clean_serial(_read(candidate / "serial")), iface)
        if candidate == sys_root:
            break
    return None


# ------------------------------------------------------------------ API

def identity(port: str, platform: str | None = None, *,
             registry: Callable[[], list[tuple[str, str, str, str]]] | None = None,
             sys_root: str | Path = "/sys") -> UsbIdentity | None:
    """Identité USB du port `port` (COM6, /dev/serial/by-id/…), ou None (port absent, pas USB, illisible)."""
    if not port:
        return None
    plat = platform or sys.platform
    try:
        if plat == "win32":
            return _windows_identity(port, _windows_entries(registry))
        return _linux_identity(port, Path(sys_root))
    except Exception:                                  # lecture du système : jamais d'exception vers l'appelant
        return None


def same_device(expected: UsbIdentity, found: UsbIdentity | None) -> bool:
    """Même périphérique : fabricant, produit, interface, et numéro de série quand l'identité relevée en a un."""
    if found is None:
        return False
    if (expected.vid, expected.pid, expected.interface) != (found.vid, found.pid, found.interface):
        return False
    return not expected.serial or expected.serial == found.serial


def locate(expected: UsbIdentity, ports: list[str], platform: str | None = None, *,
           registry: Callable[[], list[tuple[str, str, str, str]]] | None = None,
           sys_root: str | Path = "/sys") -> list[str]:
    """Ports présents (`ports`, ex. ports.list_serial_ports()) qui portent l'identité attendue ; lecture seule."""
    if not expected.serial:
        return []                                      # identité partielle : aucun port ne peut être désigné sûrement
    found = []
    entries = None
    if (platform or sys.platform) == "win32":
        try:
            entries = _windows_entries(registry)
        except Exception:
            return []
    for port in ports:
        if entries is not None:
            ident = _windows_identity(port, entries)
        else:
            ident = identity(port, platform, sys_root=sys_root)
        if same_device(expected, ident):
            found.append(port)
    return found
