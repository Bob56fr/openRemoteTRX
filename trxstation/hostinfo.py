# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Santé et matériel de la machine de la station (PC Debian, PC Windows, Raspberry Pi) : stdlib seule.

Inspiré d'OpenHardwareMonitor pour ce qu'on MONTRE, sans l'intégrer : il lit les capteurs par le pilote noyau
WinRing0 (faille connue, signalé par les antivirus). Sous Windows : charge, mémoire, disque, durée de marche ; la
température du processeur reste « — » (pas de lecture fiable sans pilote ni droits d'administrateur).

Deux vues, pour les OPÉRATEURS seulement (jamais vers un visiteur, voir gateway/api/session.py) :
  - `HostMonitor.summary()` : quelques nombres pour le petit bargraph (state.host), recalculés toutes les 2 s ;
  - `host_details()` : la synthèse (commande host_info), en rubriques de lignes « libellé : valeur » déjà rédigées
    en français, que la page et l'application affichent telles quelles.
Jamais de numéro de série, d'adresse IP ou MAC, ni de chemin de port série (le nom by-id contient le numéro de série
de l'interface).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .cpu_temp import read_cpu_temp

REFRESH_S = 2.0                      # résumé recalculé au plus toutes les 2 s (l'état part 4 fois par seconde)
THROTTLE_REFRESH_S = 30.0            # vcgencmd est un programme : rarement
# Seuils « orange » et « rouge » de chaque mesure. Le bargraph montre la mesure la plus proche de son seuil rouge,
# ramenée pour que le rouge tombe à 90 % de la barre. Mêmes ordres de grandeur que la protection contre la surcharge
# des visiteurs (gateway/api/overload.py : 85 °C, 90 % de processeur, 10 % de mémoire libre).
LIMITS = {"cpu": (75.0, 90.0), "mem": (80.0, 90.0), "disk": (85.0, 95.0), "temp": (75.0, 85.0)}
BAR_RED = 0.9
NAMES = {"cpu": "processeur", "mem": "mémoire", "disk": "disque", "temp": "température", "power": "alimentation du Pi"}
THROTTLE_BITS = {0: "sous-tension", 1: "fréquence bridée", 2: "ralenti", 3: "limite de température"}


def _windows() -> bool:
    return sys.platform.startswith("win")


# ---------------------------------------------------------------------- mesures élémentaires

class CpuMeter:
    """Charge de tous les cœurs entre deux lectures (None à la première ou si illisible)."""

    def __init__(self, proc: Path = Path("/proc")):
        self.proc, self._prev = proc, None

    def _times(self) -> tuple[int, int] | None:
        """(inactif, total) cumulés depuis le démarrage."""
        if _windows():
            return _windows_cpu_times()
        try:
            with open(self.proc / "stat", encoding="ascii") as handle:
                values = [int(v) for v in handle.readline().split()[1:]]
        except (OSError, ValueError):
            return None
        return values[3] + (values[4] if len(values) > 4 else 0), sum(values)

    def read(self) -> float | None:
        now = self._times()
        if now is None:
            return None
        prev, self._prev = self._prev, now
        if prev is None or now[1] <= prev[1]:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - (now[0] - prev[0]) / (now[1] - prev[1]))))


def _windows_cpu_times() -> tuple[int, int] | None:
    import ctypes
    from ctypes import wintypes
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    value = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime           # noqa: E731
    return value(idle), value(kernel) + value(user)                         # le temps noyau compte déjà l'inactif


def memory() -> tuple[float, int] | None:
    """(pourcentage utilisé, octets au total) ; None si illisible."""
    if _windows():
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) or not status.ullTotalPhys:
            return None
        return 100.0 * (1 - status.ullAvailPhys / status.ullTotalPhys), int(status.ullTotalPhys)
    return memory_linux()


def memory_linux(path: Path = Path("/proc/meminfo")) -> tuple[float, int] | None:
    try:
        info = {}
        for line in path.read_text(encoding="ascii").splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) * 1024
        return 100.0 * (1 - info["MemAvailable"] / info["MemTotal"]), info["MemTotal"]
    except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError):
        return None


def disk(path: str | Path) -> tuple[float, int, int] | None:
    """(pourcentage utilisé, octets libres, octets au total) du disque qui porte `path`."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return (100.0 * usage.used / usage.total if usage.total else 0.0), usage.free, usage.total


def uptime_s(proc: Path = Path("/proc")) -> float | None:
    if _windows():
        import ctypes
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    try:
        return float((proc / "uptime").read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def parse_throttled(text: str) -> int | None:
    match = re.search(r"throttled=(0x[0-9a-fA-F]+)", text)
    return int(match.group(1), 16) if match else None


def read_throttled() -> int | None:
    """Drapeaux de `vcgencmd get_throttled` (Raspberry Pi) ; None ailleurs."""
    tool = shutil.which("vcgencmd")
    if tool is None:
        return None
    try:
        done = subprocess.run([tool, "get_throttled"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_throttled(done.stdout)


def describe_throttled(value: int) -> str:
    now = [label for bit, label in THROTTLE_BITS.items() if value & (1 << bit)]
    since = [label for bit, label in THROTTLE_BITS.items() if value & (1 << (bit + 16))]
    if not now and not since:
        return "normale"
    parts = (["EN CE MOMENT : " + ", ".join(now)] if now else []) + (["depuis le démarrage : " + ", ".join(since)] if since else [])
    return " ; ".join(parts)


# ---------------------------------------------------------------------- résumé (bargraph)

def health(values: dict[str, float | None], throttled_now: bool = False) -> tuple[float, str, str]:
    """(fraction de la barre 0-1, niveau ok|warn|bad, mesure la plus chargée). Une mesure illisible ne compte pas."""
    if throttled_now:
        return 1.0, "bad", "power"
    worst, fraction, level = "", 0.0, "ok"
    for key, (warn, red) in LIMITS.items():
        value = values.get(key)
        if value is None:
            continue
        f = min(1.0, max(0.0, value / red * BAR_RED))
        if f > fraction:
            worst, fraction = key, f
        rank = "bad" if value >= red else "warn" if value >= warn else "ok"
        if (rank, level) in (("bad", "ok"), ("bad", "warn"), ("warn", "ok")):
            level = rank
    return round(fraction, 3), level, worst


class HostMonitor:
    """Résumé de santé de la machine, mis en cache (appelé à chaque état envoyé : 4 fois par seconde et par client)."""

    def __init__(self, disk_path: str | Path | None = None, clock: Callable[[], float] = time.monotonic,
                 throttled: Callable[[], int | None] = read_throttled):
        self.disk_path = disk_path or (Path(sys.prefix).anchor or "/")
        self.clock, self.read_throttled = clock, throttled
        self.cpu = CpuMeter()
        self._summary: dict | None = None
        self._at = -1e9
        self._throttled: int | None = None
        self._throttled_at = -1e9
        self.cpu.read()                                  # première lecture : la suivante donne une charge

    def throttled(self) -> int | None:
        if self.clock() - self._throttled_at >= THROTTLE_REFRESH_S:
            self._throttled_at = self.clock()
            self._throttled = self.read_throttled()
        return self._throttled

    def summary(self) -> dict:
        if self._summary is not None and self.clock() - self._at < REFRESH_S:
            return self._summary
        mem, used = memory(), disk(self.disk_path)
        temp = read_cpu_temp()
        throttled = self.throttled()
        values = {"cpu": self.cpu.read(), "mem": mem[0] if mem else None, "disk": used[0] if used else None,
                  "temp": temp.celsius if temp else None}
        fraction, level, worst = health(values, bool(throttled is not None and throttled & 0xF))
        self._summary = {
            "cpu_pct": _round(values["cpu"]), "mem_pct": _round(values["mem"]), "disk_pct": _round(values["disk"]),
            "temp_c": _round(values["temp"]), "throttled": None if throttled is None else bool(throttled & 0xF),
            "load": fraction, "level": level, "worst": worst,
        }
        self._at = self.clock()
        return self._summary


def _round(value: float | None) -> int | None:
    return None if value is None else int(round(value))


_shared: HostMonitor | None = None


def shared_monitor() -> HostMonitor:
    """Un seul moniteur pour toute la passerelle (toutes les sessions lisent le même résumé)."""
    global _shared
    if _shared is None:
        _shared = HostMonitor()
    return _shared


# ---------------------------------------------------------------------- synthèse (commande host_info)

def _gb(octets: int) -> str:
    return f"{octets / 1024 ** 3:.1f} Go".replace(".", ",")


def format_uptime(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, hours, mins = minutes // 1440, minutes // 60 % 24, minutes % 60
    return (f"{days} j " if days else "") + f"{hours} h {mins:02d} min"


def os_name() -> str:
    if _windows():
        release, version = platform.release(), platform.version()
        if release == "10" and version.split(".")[-1].isdigit() and int(version.split(".")[-1]) >= 22000:
            release = "11"                               # Windows 11 se présente encore comme « 10 »
        return f"Windows {release} ({version})"
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"') + f" (noyau {platform.release()})"
    except OSError:
        pass
    return f"{platform.system()} {platform.release()}"


def machine_model() -> str:
    """Modèle de la machine (« Raspberry Pi 4 Model B Rev 1.5 », nom de produit du PC) ; jamais le numéro de série."""
    if _windows():
        return _registry(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName") or platform.machine()
    for path in (Path("/proc/device-tree/model"), Path("/sys/firmware/devicetree/base/model")):
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
        except OSError:
            pass
    vendor = _read("/sys/class/dmi/id/sys_vendor")
    product = _read("/sys/class/dmi/id/product_name")
    found = " ".join(part for part in (vendor, product) if part and "filled" not in part.lower())
    return found or platform.machine()


def cpu_model() -> str:
    if _windows():
        name = _registry(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
    else:
        name = ""
        text = _read("/proc/cpuinfo") or ""
        for key in ("model name", "Model", "Hardware"):
            match = re.search(rf"^{key}\s*:\s*(.+)$", text, re.MULTILINE)
            if match:
                name = match.group(1).strip()
                break
    cores = os.cpu_count() or 0
    return f"{name or platform.processor() or platform.machine()} ({cores} cœur{'s' if cores > 1 else ''})"


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _registry(key: str, name: str) -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            return str(winreg.QueryValueEx(handle, name)[0]).strip()
    except (OSError, ImportError):
        return ""


def process_memory() -> int | None:
    """Mémoire occupée par CE processus (la passerelle), en octets."""
    if _windows():
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        try:
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        except (AttributeError, OSError):
            return None
        return int(counters.WorkingSetSize) if ok else None
    match = re.search(r"^VmRSS:\s*(\d+)\s*kB", _read("/proc/self/status"), re.MULTILINE)
    return int(match.group(1)) * 1024 if match else None


def host_details(monitor: HostMonitor, cfg=None, capabilities=None, hamlib_version: str = "") -> list[dict]:
    """Synthèse du matériel de la station : [{title, rows: [[libellé, valeur], ...]}], déjà rédigée."""
    summary = monitor.summary()
    mem, used, up, temp = memory(), disk(monitor.disk_path), uptime_s(), read_cpu_temp()
    machine = [["Système", os_name()], ["Machine", machine_model()], ["Processeur", cpu_model()]]
    if mem:
        machine.append(["Mémoire", _gb(mem[1])])
    if up is not None:
        machine.append(["En marche depuis", format_uptime(up)])

    def pct(key: str) -> str:
        return "—" if summary.get(key) is None else f"{summary[key]} %"
    load = [["Processeur", pct("cpu_pct")],
            ["Mémoire", pct("mem_pct") + (f" ({_gb(int(mem[1] * (1 - mem[0] / 100)))} libres)" if mem else "")],
            ["Disque", pct("disk_pct") + (f" ({_gb(used[1])} libres sur {_gb(used[2])})" if used else "")]]
    if temp is not None:
        load.append(["Température du processeur", f"{round(temp.celsius)} °C"])
    else:
        load.append(["Température du processeur",
                     "— (non lisible sous Windows sans pilote)" if _windows() else "— (aucun capteur du processeur)"])
    throttled = monitor.throttled()
    if throttled is not None:
        load.append(["Alimentation et fréquence (Pi)", describe_throttled(throttled)])
    load.append(["État", {"ok": "normal", "warn": "chargé", "bad": "SURCHARGÉ"}[summary["level"]]
                 + (f" ({NAMES[summary['worst']]})" if summary["level"] != "ok" and summary["worst"] else "")])

    station = [["TRX distant", __version__], ["Python", platform.python_version()]]
    if hamlib_version:
        station.append(["Hamlib", hamlib_version])
    if capabilities is not None and getattr(capabilities, "model_name", ""):
        station.append(["Poste", f"{capabilities.manufacturer} {capabilities.model_name} (Hamlib {capabilities.model})".strip()])
    elif cfg is not None:
        station.append(["Poste", f"modèle Hamlib {cfg.rig.model}"])
    if cfg is not None:
        station.append(["Commande du PTT", {"RIG": "CAT", "NONE": "aucune"}.get(cfg.rig.ptt_type, cfg.rig.ptt_type)])
        station.append(["Spectre HF", "second port du poste" if cfg.spectrum.enabled else "non configuré"])
        audio = [["Son reçu du poste", cfg.audio.capture_device or "carte par défaut"],
                 ["Son envoyé au poste", cfg.audio.playback_device or "carte par défaut"]]
    else:
        audio = []
    rss = process_memory()
    if rss is not None:
        station.append(["Mémoire de la passerelle", f"{rss / 1024 ** 2:.0f} Mo"])
    sections = [{"title": "Machine", "rows": machine}, {"title": "Charge en ce moment", "rows": load},
                {"title": "Station", "rows": station}]
    if audio:
        sections.append({"title": "Son", "rows": audio})
    return sections


def hamlib_version(hamlib_dir: str = "") -> str:
    """« 4.7.2 » d'après `rigctld --version` ; "" si introuvable (ne bloque jamais plus de 3 s)."""
    from .hamlib import find_tool
    tool = find_tool("rigctld", hamlib_dir)
    if not tool:
        return ""
    try:
        out = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.search(r"Hamlib\s+([\w.~+-]+)", out)
    return match.group(1) if match else ""
