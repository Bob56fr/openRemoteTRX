# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Témoin de marche du superviseur : savoir si l'arrêt PRÉCÉDENT de la station était propre (étape 355).

Le superviseur écrit `<state_dir>/en-marche.json` à son démarrage, le rafraîchit chaque minute (« dernier signe de vie »)
et l'efface à l'arrêt propre. S'il le retrouve en démarrant, la station s'est arrêtée sans passer par son arrêt :
- démarrage du système différent (heure de démarrage de la machine changée) : la MACHINE s'est arrêtée brutalement
  (coupure de courant, plantage, bouton) -> ORT-8030 ; Linux seulement : sous Windows, une extinction normale du PC tue
  la station sans prévenir, ce serait une fausse alerte à chaque arrêt ;
- même démarrage du système : le SUPERVISEUR seul est mort (tué, planté) -> ORT-8031.
Jamais bloquant : un témoin illisible ou impossible à écrire ne gêne pas la station. Lecture et écriture seulement :
rien ne touche au poste.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

MARK_FILE = "en-marche.json"
REFRESH_S = 60.0
SAME_BOOT_S = 120.0          # deux heures de démarrage du système plus proches que ça : même démarrage


def boot_time() -> float | None:
    """Heure (epoch) du démarrage de la machine : `btime` de /proc/stat (Linux), sinon maintenant - durée de marche."""
    try:
        for line in Path("/proc/stat").read_text(encoding="ascii").splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    try:
        from ..hostinfo import uptime_s
        up = uptime_s()
        return time.time() - up if up is not None else None
    except Exception:
        return None


@dataclass(frozen=True)
class UncleanStop:
    last_seen: float           # dernier signe de vie (epoch)
    machine: bool              # True : la machine elle-même s'est arrêtée (démarrage du système différent)


class RunMark:
    def __init__(self, state_dir: str | Path, *, clock=time.time, boot=boot_time, platform: str = sys.platform):
        self.path = Path(state_dir) / MARK_FILE
        self.clock, self.boot, self.platform = clock, boot, platform
        self._boot: float | None = None
        self._written = -1e18

    def start(self) -> UncleanStop | None:
        """Lit le témoin d'une session précédente (arrêt non propre s'il est là) puis pose le sien."""
        previous = None
        try:
            previous = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            previous = {}                                   # illisible (écriture coupée) : arrêt non propre quand même
        self._boot = self.boot()
        self.refresh(force=True)
        if previous is None:
            return None
        seen = previous.get("vu") if isinstance(previous, dict) else None
        seen = float(seen) if isinstance(seen, (int, float)) else (self.path_mtime() or self.clock())
        old_boot = previous.get("demarrage_systeme") if isinstance(previous, dict) else None
        machine = (isinstance(old_boot, (int, float)) and self._boot is not None
                   and abs(self._boot - old_boot) > SAME_BOOT_S)
        if machine and not self.platform.startswith("linux"):
            return None                                     # Windows : extinction normale indiscernable (voir en tête)
        return UncleanStop(last_seen=seen, machine=machine)

    def path_mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def refresh(self, force: bool = False) -> None:
        """Dernier signe de vie, au plus une écriture par minute (carte SD d'un Pi ménagée)."""
        now = self.clock()
        if not force and now - self._written < REFRESH_S:
            return
        self._written = now
        data = {"pid": os.getpid(), "vu": now, "demarrage_systeme": self._boot}
        try:
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass                                            # jamais bloquant

    def clean_stop(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
