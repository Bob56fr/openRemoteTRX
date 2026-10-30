# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Charge de la station en marche, sous Linux (essai Raspberry Pi, docs/essai-raspberry-pi.md) :
`/opt/trx-remote/venv/bin/python -m trxstation.devtools.station_load [--minutes 10] [--interval 5] [--csv F]`.

Lecture seule de /proc et /sys, aucun droit particulier, aucune commande envoyée à la station. Relève à chaque
intervalle : processeur de toute la machine et de chaque service (en % d'UN cœur : 100 % = un cœur plein),
température du processeur, fréquence, mémoire disponible, écritures sur les disques (usure de la carte SD) et,
sur un Raspberry Pi, les drapeaux de `vcgencmd get_throttled` (alimentation trop faible, fréquence bridée).
Le bilan final donne les moyennes, les pires valeurs et les Mo écrits par heure.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..cpu_temp import cpu_celsius

# Services de la station, reconnus à leur ligne de commande (units systemd/*.service).
SERVICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rigctld", ("trxstation.run_rigctld", "rigctld")),
    ("passerelle", ("trxstation.gateway.main",)),
    ("superviseur", ("trxstation.supervisor.main",)),
    ("autres trx", ("trxstation.",)),          # modules (Cluster DX…), trx-monitor, TRX Console
)
WHOLE_DISK = re.compile(r"^(mmcblk\d+|sd[a-z]+|nvme\d+n\d+|vd[a-z]+)$")
# Bits de `vcgencmd get_throttled` (documentation Raspberry Pi) : 0-3 en ce moment, 16-19 depuis le démarrage.
THROTTLE_BITS = {0: "sous-tension", 1: "fréquence bridée", 2: "ralenti", 3: "limite de température"}


@dataclass
class Snapshot:
    when: float
    cpu_busy: int                     # jiffies de toute la machine (tous cœurs)
    cpu_total: int
    services: dict[str, int]          # jiffies (utime + stime) cumulés par service
    sectors_written: int              # secteurs de 512 octets écrits sur les disques entiers
    mem_available_mb: float | None
    temp_c: float | None
    freq_mhz: float | None
    throttled: int | None


@dataclass
class Sample:
    cpu_pct: float                    # % de toute la machine
    services_pct: dict[str, float]    # % d'un cœur
    write_kb_s: float
    mem_available_mb: float | None
    temp_c: float | None
    freq_mhz: float | None
    throttled: int | None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_cpu(proc: Path) -> tuple[int, int]:
    """(occupé, total) en jiffies, ligne « cpu » de /proc/stat ; iowait compte comme repos."""
    text = _read(proc / "stat") or ""
    for line in text.splitlines():
        if line.startswith("cpu "):
            values = [int(v) for v in line.split()[1:]]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values[:8])
            return total - idle, total
    return 0, 0


def service_of(cmdline: list[str]) -> str | None:
    if not cmdline:
        return None
    joined = " ".join(cmdline)
    program = Path(cmdline[0]).name
    for name, markers in SERVICES:
        for marker in markers:
            # « rigctld » : le programme lui-même ; les autres : module Python dans la ligne de commande
            if marker == program or ("." in marker and marker in joined):
                return name
    return None


def read_services(proc: Path, skip_pid: int | None = None) -> dict[str, int]:
    """Jiffies cumulés par service ; skip_pid : l'outil de mesure lui-même (sinon compté dans « autres trx »)."""
    found = {name: 0 for name, _ in SERVICES}
    try:
        entries = [p for p in proc.iterdir() if p.name.isdigit() and p.name != str(skip_pid)]
    except OSError:
        return found
    for entry in entries:
        raw = _read(entry / "cmdline")
        name = service_of([part for part in (raw or "").split("\0") if part])
        stat = _read(entry / "stat") if name else None
        if not stat:
            continue
        fields = stat[stat.rfind(")") + 2:].split()      # après « (nom) » : le nom peut contenir des espaces
        try:
            found[name] += int(fields[11]) + int(fields[12])   # utime, stime (champs 14 et 15)
        except (IndexError, ValueError):
            continue
    return found


def read_sectors_written(proc: Path) -> int:
    total = 0
    for line in (_read(proc / "diskstats") or "").splitlines():
        parts = line.split()
        if len(parts) > 9 and WHOLE_DISK.match(parts[2]):
            try:
                total += int(parts[9])
            except ValueError:
                pass
    return total


def read_mem_available_mb(proc: Path) -> float | None:
    for line in (_read(proc / "meminfo") or "").splitlines():
        if line.startswith("MemAvailable:"):
            try:
                return int(line.split()[1]) / 1024.0
            except (IndexError, ValueError):
                return None
    return None


def read_freq_mhz(sys_root: Path) -> float | None:
    text = _read(sys_root / "devices" / "system" / "cpu" / "cpu0" / "cpufreq" / "scaling_cur_freq")
    try:
        return int(text) / 1000.0 if text else None
    except ValueError:
        return None


def parse_throttled(text: str) -> int | None:
    match = re.search(r"throttled=(0x[0-9a-fA-F]+)", text)
    return int(match.group(1), 16) if match else None


def read_throttled() -> int | None:
    tool = shutil.which("vcgencmd")
    if tool is None:
        return None
    try:
        done = subprocess.run([tool, "get_throttled"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_throttled(done.stdout)


def describe_throttled(value: int | None) -> str:
    if value is None:
        return "illisible (pas un Raspberry Pi ?)"
    now = [label for bit, label in THROTTLE_BITS.items() if value & (1 << bit)]
    since = [label for bit, label in THROTTLE_BITS.items() if value & (1 << (bit + 16))]
    if not now and not since:
        return "aucun ralentissement"
    parts = []
    if now:
        parts.append("EN CE MOMENT : " + ", ".join(now))
    if since:
        parts.append("depuis le démarrage : " + ", ".join(since))
    return " ; ".join(parts)


def snapshot(proc: Path = Path("/proc"), sys_root: Path = Path("/sys"), throttled: int | None = None) -> Snapshot:
    busy, total = read_cpu(proc)
    return Snapshot(time.monotonic(), busy, total, read_services(proc, os.getpid()), read_sectors_written(proc),
                    read_mem_available_mb(proc), cpu_celsius(sys_root), read_freq_mhz(sys_root), throttled)


def delta(before: Snapshot, after: Snapshot, clk_tck: int) -> Sample:
    dt = max(after.when - before.when, 1e-6)
    d_total = after.cpu_total - before.cpu_total
    cpu = 100.0 * (after.cpu_busy - before.cpu_busy) / d_total if d_total > 0 else 0.0
    services = {name: max(0.0, 100.0 * (after.services.get(name, 0) - before.services.get(name, 0)) / clk_tck / dt)
                for name in after.services}
    write = max(0, after.sectors_written - before.sectors_written) * 512 / 1024.0 / dt
    return Sample(cpu, services, write, after.mem_available_mb, after.temp_c, after.freq_mhz, after.throttled)


@dataclass
class Summary:
    samples: list[Sample] = field(default_factory=list)
    seconds: float = 0.0

    def text(self) -> str:
        s = self.samples
        if not s:
            return "Aucune mesure."

        def avg_max(values: list[float]) -> str:
            return f"moyenne {sum(values) / len(values):5.1f} %   pire {max(values):5.1f} %"

        lines = [f"Bilan sur {self.seconds / 60:.1f} min ({len(s)} mesures)",
                 f"  processeur, toute la machine : {avg_max([x.cpu_pct for x in s])}"]
        for name in s[0].services_pct:
            lines.append(f"  {name:<12} (% d'un cœur) : {avg_max([x.services_pct[name] for x in s])}")
        temps = [x.temp_c for x in s if x.temp_c is not None]
        lines.append(f"  température du processeur : " + (f"moyenne {sum(temps) / len(temps):.1f} °C   pire {max(temps):.1f} °C"
                                                         if temps else "illisible"))
        freqs = [x.freq_mhz for x in s if x.freq_mhz is not None]
        if freqs:
            lines.append(f"  fréquence du processeur : {min(freqs):.0f} à {max(freqs):.0f} MHz")
        mems = [x.mem_available_mb for x in s if x.mem_available_mb is not None]
        if mems:
            lines.append(f"  mémoire disponible : au plus bas {min(mems):.0f} Mo")
        written_mb = sum(x.write_kb_s for x in s) / len(s) * 3600 / 1024.0
        lines.append(f"  écritures sur les disques : {written_mb:.1f} Mo par heure")
        lines.append(f"  vcgencmd get_throttled : {describe_throttled(s[-1].throttled)}")
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Charge de la station en marche (lecture seule, Linux).")
    ap.add_argument("--minutes", type=float, default=10.0, help="durée de la mesure (défaut 10)")
    ap.add_argument("--interval", type=float, default=5.0, help="secondes entre deux mesures (défaut 5)")
    ap.add_argument("--csv", type=Path, default=None, help="enregistre chaque mesure dans ce fichier")
    args = ap.parse_args(argv)
    if not Path("/proc/stat").exists():
        print("Outil réservé à Linux (/proc absent).")
        return 2
    model = (_read(Path("/proc/device-tree/model")) or "").strip("\0\n ")
    if model:
        print(f"Machine : {model}")
    clk_tck = os.sysconf("SC_CLK_TCK")
    summary = Summary()
    writer = None
    handle = None
    if args.csv is not None:
        handle = args.csv.open("w", newline="", encoding="utf-8")
        writer = csv.writer(handle)
    before = snapshot(throttled=read_throttled())
    start = before.when
    print(f"Mesure pendant {args.minutes:g} min, une ligne toutes les {args.interval:g} s (Ctrl+C : bilan tout de suite).")
    try:
        while time.monotonic() - start < args.minutes * 60:
            time.sleep(args.interval)
            after = snapshot(throttled=read_throttled())
            sample = delta(before, after, clk_tck)
            before = after
            summary.samples.append(sample)
            summary.seconds = after.when - start
            per = "  ".join(f"{k} {v:5.1f}" for k, v in sample.services_pct.items())
            temp = f"{sample.temp_c:.1f} °C" if sample.temp_c is not None else "? °C"
            print(f"machine {sample.cpu_pct:5.1f} %  {per}  {temp}  écrit {sample.write_kb_s:6.1f} ko/s"
                  + (f"  throttled=0x{sample.throttled:x}" if sample.throttled else ""))
            if writer is not None:
                if len(summary.samples) == 1:
                    writer.writerow(["secondes", "machine_pct", *sample.services_pct, "temp_c", "freq_mhz",
                                     "mem_dispo_mo", "ecrit_ko_s", "throttled"])
                writer.writerow([f"{summary.seconds:.0f}", f"{sample.cpu_pct:.1f}",
                                 *(f"{v:.1f}" for v in sample.services_pct.values()),
                                 "" if sample.temp_c is None else f"{sample.temp_c:.1f}",
                                 "" if sample.freq_mhz is None else f"{sample.freq_mhz:.0f}",
                                 "" if sample.mem_available_mb is None else f"{sample.mem_available_mb:.0f}",
                                 f"{sample.write_kb_s:.1f}",
                                 "" if sample.throttled is None else f"0x{sample.throttled:x}"])
                handle.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if handle is not None:
            handle.close()
    print()
    print(summary.text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
