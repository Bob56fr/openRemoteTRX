# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Historique des 24 dernières heures : une mesure par minute, regroupée en 96 quarts d'heure pour la page.

Gardé en mémoire et recopié sur disque (écriture atomique) pour survivre à un redémarrage du programme.
Pas de valeur inventée : un quart d'heure sans mesure reste vide (trou dans la courbe).
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path

DAY_S = 24 * 3600
BUCKETS = 96                      # 96 × 15 min
BUCKET_S = DAY_S // BUCKETS
KEYS = ("cpu", "mem", "temp", "net")


class History:
    def __init__(self, path: Path | None = None, clock=time.time):
        self.path, self.clock = path, clock
        self.samples: deque[dict] = deque()      # {"t", "cpu", "mem", "temp", "net"} ; net = 1 / 0 / None
        self.alerts: deque[dict] = deque()       # {"t", "level", "text", "key"}
        self._alert_keys: set[str] = set()

    # ------------------------------------------------------------------ écriture

    def add_sample(self, cpu: float | None, mem: float | None, temp: float | None, net: bool | None) -> None:
        self.samples.append({"t": self.clock(), "cpu": _r(cpu), "mem": _r(mem), "temp": _r(temp),
                             "net": None if net is None else int(bool(net))})
        self._trim()

    def add_alert(self, key: str, level: str, text: str, t: float | None = None) -> bool:
        """Une alerte compte une fois (clé unique : code et heure de l'événement). Vrai si elle est nouvelle."""
        if key in self._alert_keys:
            return False
        self._alert_keys.add(key)
        self.alerts.append({"t": t if t is not None else self.clock(), "level": "crit" if level == "crit" else "warn",
                            "text": text, "key": key})
        self._trim()
        return True

    def _trim(self) -> None:
        limit = self.clock() - DAY_S
        while self.samples and self.samples[0]["t"] < limit:
            self.samples.popleft()
        while self.alerts and self.alerts[0]["t"] < limit:
            self._alert_keys.discard(self.alerts.popleft()["key"])

    # ------------------------------------------------------------------ lecture pour la page

    def view(self) -> dict:
        self._trim()
        now = self.clock()
        start = now - DAY_S
        groups: list[list[dict]] = [[] for _ in range(BUCKETS)]
        for s in self.samples:
            i = min(BUCKETS - 1, int((s["t"] - start) // BUCKET_S))      # « maintenant » tombe dans le dernier
            if 0 <= i:
                groups[i].append(s)

        def agg(key: str, how) -> list:
            out = []
            for g in groups:
                vals = [s[key] for s in g if s[key] is not None]
                out.append(round(how(vals), 1) if vals else None)
            return out

        alerts = []
        for a in self.alerts:
            i = min(BUCKETS - 1, int((a["t"] - start) // BUCKET_S))
            if 0 <= i:
                alerts.append({"i": i, "level": a["level"]})
        return {
            "n": BUCKETS, "step_s": BUCKET_S,
            "cpu": agg("cpu", max),                                # le pic compte plus que la moyenne
            "mem": agg("mem", lambda v: sum(v) / len(v)),
            "temp": agg("temp", max),
            "internet": agg("net", lambda v: sum(v) / len(v)),     # part du quart d'heure avec Internet
            "alerts": alerts,
        }

    def internet_pct(self) -> float | None:
        vals = [s["net"] for s in self.samples if s["net"] is not None]
        return 100.0 * sum(vals) / len(vals) if vals else None

    def alert_counts(self) -> tuple[int, int]:
        crit = sum(1 for a in self.alerts if a["level"] == "crit")
        return len(self.alerts) - crit, crit

    # ------------------------------------------------------------------ disque

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for s in data.get("samples", []):
                if isinstance(s, dict) and isinstance(s.get("t"), (int, float)):
                    self.samples.append({"t": s["t"], **{k: s.get(k) for k in KEYS}})
            for a in data.get("alerts", []):
                if isinstance(a, dict) and isinstance(a.get("t"), (int, float)) and a.get("key"):
                    self.add_alert(str(a["key"]), str(a.get("level")), str(a.get("text", "")), a["t"])
        except (OSError, ValueError):
            return                                  # fichier abîmé : on repart d'un historique vide
        self._trim()

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"v": 1, "samples": list(self.samples), "alerts": list(self.alerts)}),
                       encoding="utf-8")
        os.replace(tmp, self.path)


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)
