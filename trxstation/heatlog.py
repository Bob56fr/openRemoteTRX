# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Historique de chauffe de la station (Linux) : d'où vient une température élevée du processeur (étape 377).

Le superviseur appelle `HeatLog.tick` à chaque passage ; un relevé est écrit toutes les EVERY_S (10 s) dans
`<state_dir>/chauffe.jsonl` (une ligne JSON par relevé, fichier tourné à MAX_BYTES, KEEP anciens gardés) :
température du processeur et son capteur, charge moyenne, fréquence la plus haute des cœurs, processeur utilisé en %,
et les programmes qui l'ont le plus occupé DEPUIS LE RELEVÉ PRÉCÉDENT (temps processeur de /proc/<pid>/stat entre deux
relevés, en % d'un cœur comme `top` ; un programme né entre deux relevés compte pour tout son temps, un programme déjà
terminé n'est pas vu). Au-dessus du seuil d'alerte (`chaud`), la ligne porte en plus tous les capteurs,
l'occupation de chaque cœur logique et plus de programmes ; un relevé est alors fait sans attendre les 10 s (dès que le précédent date d'au moins HOT_MIN_GAP_S).

Rien ne bloque : deux lectures de /proc à 10 s d'écart, jamais d'attente d'une seconde dans la boucle du superviseur.
Seulement le NOM des programmes (jamais leur ligne de commande ni leur compte) ; pour un interpréteur (python…), le nom du
module (`-m x.y`) ou du script (nom de fichier seul). Bibliothèque standard seulement. Hors Linux (pas de /proc) : rien.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .cpu_temp import HWMON_CHIPS, read_cpu_temp

FILE_NAME = "chauffe.jsonl"
EVERY_S = 10.0          # un relevé toutes les 10 s (décision de l'utilisateur, 2026-11-23)
HOT_MIN_GAP_S = 1.0     # relevé immédiat au passage du seuil, si le précédent date d'au moins ce délai
MAX_BYTES = 4_000_000   # ~3 jours de relevés ordinaires ; puis chauffe.jsonl.1, .2
KEEP = 2
TOP = 3                 # programmes d'une ligne ordinaire
TOP_HOT = 8             # programmes d'une ligne au-dessus du seuil
MIN_PCT = 0.5           # un programme sous ce seuil n'est pas cité
KWORKER = "noyau (kworker)"
INTERPRETERS = ("python", "sh", "bash", "dash", "node", "java", "perl", "ruby", "php")


@dataclass
class ProcSnap:
    wall: float
    procs: dict[int, tuple[str, int]] = field(default_factory=dict)   # pid -> (nom, tics utilisateur + système)
    cores: list[tuple[int, int]] = field(default_factory=list)        # par cœur logique : (tics occupés, tics totaux)
    total: tuple[int, int] = (0, 0)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _busy_total(fields: list[str]) -> tuple[int, int]:
    values = [int(v) for v in fields[:8]]          # user nice system idle iowait irq softirq steal
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return total - idle, total


def program_name(comm: str, cmdline: bytes) -> str:
    """Nom lisible d'un programme : `comm`, ou pour un interpréteur « python:module » / « python:script » ; les fils
    du noyau `kworker/…` (nom qui change avec la tâche en cours) sont regroupés sous KWORKER."""
    if comm.startswith("kworker/"):
        return KWORKER
    base = comm.split(".")[0].rstrip("0123456789") if comm.startswith("python") else comm
    if base not in INTERPRETERS:
        return comm
    args = [a.decode("utf-8", "replace") for a in cmdline.split(b"\0") if a]
    for i, arg in enumerate(args[1:], start=1):
        if arg == "-m" and i + 1 < len(args):
            return f"{base}:{args[i + 1]}"
        if arg == "-c":
            return f"{base}:-c"
        if not arg.startswith("-"):
            return f"{base}:{os.path.basename(arg)}"
    return comm


def read_proc(proc_root: Path, wall: float) -> ProcSnap | None:
    stat = _read(proc_root / "stat")
    if stat is None:
        return None
    snap = ProcSnap(wall)
    for line in stat.splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith("cpu"):
            continue
        try:
            pair = _busy_total(parts[1:])
        except ValueError:
            continue
        if parts[0] == "cpu":
            snap.total = pair
        else:
            snap.cores.append(pair)
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return snap
    for entry in entries:
        if not entry.name.isdigit():
            continue
        text = _read(entry / "stat")
        if text is None:
            continue                                # programme terminé entre-temps
        try:
            close = text.rindex(")")
            comm = text[text.index("(") + 1:close]
            rest = text[close + 2:].split()
            ticks = int(rest[11]) + int(rest[12])   # utime, stime (champs 14 et 15)
        except (ValueError, IndexError):
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            cmdline = b""
        snap.procs[int(entry.name)] = (program_name(comm, cmdline), ticks)
    return snap


def read_sensors(sys_root: Path) -> dict[str, float]:
    """Tous les capteurs hwmon : « coretemp Core 5 » -> 84.0 (processeur, disque NVMe, Wi-Fi, carte mère…)."""
    found: dict[str, float] = {}
    try:
        chips = sorted((sys_root / "class" / "hwmon").iterdir())
    except OSError:
        return found
    for chip in chips:
        name = (_read(chip / "name") or chip.name).strip()
        for sensor in sorted(chip.glob("temp*_input")):
            try:
                value = int((_read(sensor) or "").strip()) / 1000.0
            except ValueError:
                continue
            if not -40.0 <= value <= 150.0:
                continue
            label = (_read(sensor.with_name(sensor.name.replace("_input", "_label"))) or sensor.name).strip()
            key = f"{name} {label}"
            while key in found:                     # deux puces du même nom (deux disques NVMe)
                key += "'"
            found[key] = round(value, 1)
    return found


def hottest_cpu_sensor(sensors: dict[str, float]) -> tuple[str, float] | None:
    cpu = [(k, v) for k, v in sensors.items() if k.split(" ", 1)[0] in HWMON_CHIPS]
    return max(cpu, key=lambda kv: kv[1]) if cpu else None


def max_freq_mhz(sys_root: Path) -> int | None:
    best = None
    for path in (sys_root / "devices" / "system" / "cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq"):
        try:
            khz = int((_read(path) or "").strip())
        except ValueError:
            continue
        best = khz if best is None else max(best, khz)
    return None if best is None else round(best / 1000)


def load_1min(proc_root: Path) -> float | None:
    try:
        return float((_read(proc_root / "loadavg") or "").split()[0])
    except (ValueError, IndexError):
        return None


def _pct(busy: int, total: int) -> float:
    return round(100.0 * busy / total, 1) if total > 0 else 0.0


def top_programs(before: ProcSnap, after: ProcSnap, hz: int, count: int) -> list[list]:
    """[[nom, % d'un cœur, nombre de processus], …] des programmes qui ont le plus occupé le processeur entre deux
    relevés, regroupés par nom (100 % = un cœur entier, comme `top`)."""
    elapsed = after.wall - before.wall
    if elapsed <= 0:
        return []
    ticks_by: dict[str, int] = {}
    count_by: dict[str, int] = {}
    for pid, (name, ticks) in after.procs.items():
        old = before.procs.get(pid)
        # même pid dont le temps n'a pas reculé : même processus (un fil du noyau change de nom) ; sinon né entre les
        # deux relevés (pid neuf ou réutilisé) : tout son temps est dans l'intervalle (programmes relancés souvent)
        delta = ticks - old[1] if old is not None and ticks >= old[1] else ticks
        if delta > 0:
            ticks_by[name] = ticks_by.get(name, 0) + delta
            count_by[name] = count_by.get(name, 0) + 1
    used = [[name, round(100.0 * t / hz / elapsed, 1), count_by[name]] for name, t in ticks_by.items()]
    used = [u for u in used if u[1] >= MIN_PCT]
    used.sort(key=lambda u: (-u[1], u[0]))
    return used[:count]


@dataclass
class HotPeriod:
    """Relevés chauds de suite : temps processeur cumulé par programme, maximums de température et de charge."""
    seconds: float = 0.0
    cpu_s: float = 0.0                                  # % de la machine × secondes
    programs: dict[str, float] = field(default_factory=dict)   # nom -> % d'un cœur × secondes
    temp_max: float | None = None
    hottest: list | None = None                         # [capteur, °C] le plus chaud vu pendant la période
    core_max: float | None = None

    def add(self, line: dict, programs: list[list], seconds: float) -> None:
        if seconds <= 0:
            return
        self.seconds += seconds
        self.cpu_s += line.get("cpu_pct", 0.0) * seconds
        for name, pct, _ in programs:
            self.programs[name] = self.programs.get(name, 0.0) + pct * seconds
        temp = line.get("temp_c")
        if temp is not None and (self.temp_max is None or temp > self.temp_max):
            self.temp_max = temp
        hot = line.get("plus_chaud")
        if hot and (self.hottest is None or hot[1] > self.hottest[1]):
            self.hottest = list(hot)
        cores = line.get("coeurs_pct")
        if cores:
            self.core_max = max(cores) if self.core_max is None else max(self.core_max, max(cores))

    def summary(self, count: int = 5) -> str:
        if self.seconds <= 0:
            return ""
        parts = []
        if self.hottest:
            parts.append(f"capteur le plus chaud : {self.hottest[0]} (jusqu'à {self.hottest[1]:.0f} °C)")
        load = f"processeur occupé à {self.cpu_s / self.seconds:.0f} % en moyenne"
        if self.core_max is not None:
            load += f" (cœur le plus chargé : jusqu'à {self.core_max:.0f} %)"
        parts.append(load)
        ranked = sorted(self.programs.items(), key=lambda kv: (-kv[1], kv[0]))[:count]
        shown = [f"{name} {total / self.seconds:.0f} %" for name, total in ranked if total / self.seconds >= MIN_PCT]
        if shown:
            parts.append(f"programmes en moyenne sur {self.seconds:.0f} s : " + ", ".join(shown))
        return " ; ".join(parts)


class HeatLog:
    def __init__(self, path: str | Path, *, proc_root: str | Path = "/proc", sys_root: str | Path = "/sys",
                 wall: Callable[[], float] = time.time, every_s: float = EVERY_S, max_bytes: int = MAX_BYTES):
        self.path = Path(path)
        self.proc_root, self.sys_root = Path(proc_root), Path(sys_root)
        self.wall, self.every_s, self.max_bytes = wall, every_s, max_bytes
        try:
            self.hz = os.sysconf("SC_CLK_TCK")
        except (AttributeError, ValueError, OSError):
            self.hz = 100
        self._prev: ProcSnap | None = None
        self._at = -1e18
        self._was_hot = False
        self.last: dict | None = None               # dernier relevé écrit (résumé de l'alerte ORT-1010)
        self.hot_period = HotPeriod()               # relevés chauds de suite : cause de la chauffe (étape 378)

    @property
    def available(self) -> bool:
        return (self.proc_root / "stat").exists()

    def tick(self, now: float, hot: bool = False) -> dict | None:
        """Relevé si EVERY_S est passé, ou tout de suite au passage du seuil (`hot`). Retourne la ligne écrite."""
        if not hot:
            self.hot_period = HotPeriod()           # sous le seuil : la période chaude est finie
        due = now - self._at >= self.every_s or (hot and not self._was_hot and now - self._at >= HOT_MIN_GAP_S)
        if not due:
            self._was_hot = self._was_hot and hot      # passage du seuil trop proche : relevé chaud au passage suivant
            return None
        self._was_hot = hot
        self._at = now
        snap = read_proc(self.proc_root, self.wall())
        if snap is None:
            return None
        prev, self._prev = self._prev, snap
        if prev is None:
            return None                             # premier relevé : référence, rien à comparer encore
        programs = top_programs(prev, snap, self.hz, 10**6)
        line = self.sample(prev, snap, hot, programs)
        if hot:
            self.hot_period.add(line, programs, snap.wall - prev.wall)
        self.write(line)
        self.last = line
        return line

    def sample(self, prev: ProcSnap, snap: ProcSnap, hot: bool, programs: list[list] | None = None) -> dict:
        cpu = read_cpu_temp(self.sys_root)
        line: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(snap.wall)),
                      "temp_c": round(cpu.celsius, 1) if cpu else None,
                      "capteur": cpu.source if cpu else None,
                      "charge_1min": load_1min(self.proc_root),
                      "mhz_max": max_freq_mhz(self.sys_root),
                      "cpu_pct": _pct(snap.total[0] - prev.total[0], snap.total[1] - prev.total[1]),
                      "top": (programs if programs is not None
                              else top_programs(prev, snap, self.hz, 10**6))[:TOP_HOT if hot else TOP]}
        if hot:
            sensors = read_sensors(self.sys_root)
            line["chaud"] = True
            line["capteurs"] = sensors
            hottest = hottest_cpu_sensor(sensors)
            line["plus_chaud"] = list(hottest) if hottest else None
            if len(prev.cores) == len(snap.cores):
                line["coeurs_pct"] = [_pct(b - pb, t - pt) for (b, t), (pb, pt) in zip(snap.cores, prev.cores)]
        return line

    def write(self, line: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.stat().st_size >= self.max_bytes:
                for n in range(KEEP, 0, -1):
                    older = self.path.with_name(f"{self.path.name}.{n}")
                    newer = self.path.with_name(f"{self.path.name}.{n - 1}") if n > 1 else self.path
                    if newer.exists():
                        os.replace(newer, older)
        except FileNotFoundError:
            pass
        new = not self.path.exists()
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
        if new:
            try:
                os.chmod(self.path, 0o644)          # lu par le compte du bureau (rapport du menu 6.3)
            except OSError:
                pass

    def hot_summary(self) -> str:
        """Résumé de TOUTE la période chaude en cours (alerte après une chauffe durable), sinon du dernier relevé."""
        return self.hot_period.summary() or self.summary()

    def summary(self) -> str:
        """Résumé du dernier relevé pour l'alerte : capteur le plus chaud, charge, programmes."""
        line = self.last
        if not line:
            return ""
        parts = []
        hottest = line.get("plus_chaud")
        if hottest:
            parts.append(f"capteur le plus chaud : {hottest[0]} ({hottest[1]:.0f} °C)")
        cores = line.get("coeurs_pct") or []
        load = f"processeur occupé à {line.get('cpu_pct', 0):.0f} %"
        if cores:
            load += f" (cœur le plus chargé : {max(cores):.0f} %)"
        parts.append(load)
        if line.get("top"):
            parts.append("programmes : " + ", ".join(f"{name} {pct:.0f} %" for name, pct, _ in line["top"][:5]))
        return " ; ".join(parts)
