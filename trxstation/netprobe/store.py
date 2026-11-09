# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Journal et statistiques de la sonde réseau (docs/netprobe-cahier-des-charges.md § 6, § 9.6, § 10).

Tout est dans state_dir/netprobe/ (jamais dans station.toml : la passerelle n'y écrit pas) :
  AAAA-MM-JJ.jsonl  résumés de 10 s et événements, gardés `log_days` ;
  coupures.jsonl    une ligne par coupure avec son diagnostic, gardée `stats_days` ;
  heures.jsonl      un résumé par heure, appareil et type de réseau (histogrammes compris), gardé `stats_days` ;
  seuils.json       seuils choisis par l'opérateur par type de réseau (« Tout effacer » ne les efface pas) ;
  vpn.json          appareils vus par adresse et avertissements ignorés (profil VPN partagé).
Une écriture ratée (disque plein, droits) est journalisée et oubliée : la sonde ne gêne jamais la station.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from ..status import replace_atomic
from . import calc
from .report import NET_TYPES

log = logging.getLogger(__name__)
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
WINDOW_S = 10


def _utc_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _local(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000)


def _empty_hist(edges: tuple) -> list[list[int]]:
    return [[0, 0] for _ in range(len(edges) + 1)]


class NetStore:
    def __init__(self, folder: str | Path, log_days: int = 7, stats_days: int = 30,
                 wall_ms=lambda: int(time.time() * 1000)) -> None:
        self.folder = Path(folder)
        self.log_days, self.stats_days, self.wall_ms = log_days, stats_days, wall_ms
        self._hours: dict[tuple, dict] = {}         # (heure, appareil, type de réseau) -> résumé en cours
        self._failed = False
        self._pruned_day = ""

    # ------------------------------------------------------------------ écriture

    def _append(self, name: str, record: dict) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with open(self.folder / name, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._failed = False
        except OSError as exc:
            if not self._failed:
                log.warning("journal de la sonde réseau non écrit (%s) : les mesures continuent sans lui", exc)
            self._failed = True

    def log(self, record: dict) -> None:
        """Résumé de 10 s ou événement : dans le fichier du jour (UTC)."""
        self._append(_utc_day(record["ts"]) + ".jsonl", record)

    def add_outage(self, outage: dict) -> None:
        self._append("coupures.jsonl", outage)
        self.log({"ts": outage["end_ms"], "src": "passerelle", "kind": "coupure", **outage})

    def add_window(self, ts_ms: int, device: str, agent: str, net_type: str, stats: dict, degraded: bool) -> None:
        """Une fenêtre de 10 s dans le résumé horaire (histogrammes du § 9.6)."""
        hour = ts_ms - ts_ms % HOUR_MS
        for key in list(self._hours):
            if key[0] != hour:
                self._flush(key)
        key = (hour, device, net_type)
        h = self._hours.get(key)
        if h is None:
            h = self._hours[key] = {"hour_ms": hour, "device": device, "agent": agent, "net_type": net_type,
                                    "windows": 0, "degraded": 0, "lost": 0, "expected": 0, "rtt_p95_sum": 0,
                                    "rtt_count": 0, "rtt_hist": _empty_hist(calc.RTT_EDGES_MS),
                                    "loss_hist": _empty_hist(calc.LOSS_EDGES_PCT)}
        h["agent"] = agent or h["agent"]
        h["windows"] += 1
        h["degraded"] += int(degraded)
        h["lost"] += stats["lost"]
        h["expected"] += stats["expected"]
        if stats["rtt_p95_ms"] is not None:
            h["rtt_p95_sum"] += stats["rtt_p95_ms"]
            h["rtt_count"] += 1
            cell = h["rtt_hist"][calc.bucket(stats["rtt_p95_ms"], calc.RTT_EDGES_MS)]
            cell[0] += 1
            cell[1] += int(degraded)
        if stats["loss_pct"] is not None:
            cell = h["loss_hist"][calc.bucket(stats["loss_pct"], calc.LOSS_EDGES_PCT)]
            cell[0] += 1
            cell[1] += int(degraded)

    def _flush(self, key: tuple) -> None:
        record = self._hours.pop(key, None)
        if record is not None and record["windows"]:
            self._append("heures.jsonl", record)

    def flush(self) -> None:
        for key in list(self._hours):
            self._flush(key)

    # ------------------------------------------------------------------ lecture

    def _read(self, name: str) -> list[dict]:
        try:
            lines = (self.folder / name).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            log.warning("lecture de %s impossible : %s", name, exc)
            return []
        out = []
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue                                # ligne coupée par un arrêt brutal : ignorée
            if isinstance(item, dict):
                out.append(item)
        return out

    def outages(self, since_ms: int = 0) -> list[dict]:
        return [o for o in self._read("coupures.jsonl") if o.get("end_ms", 0) >= since_ms]

    def hours(self, since_ms: int = 0) -> list[dict]:
        done = [h for h in self._read("heures.jsonl") if h.get("hour_ms", 0) + HOUR_MS > since_ms]
        current = [dict(h, rtt_hist=[list(c) for c in h["rtt_hist"]], loss_hist=[list(c) for c in h["loss_hist"]])
                   for h in self._hours.values() if h["windows"]]
        return done + current

    # ------------------------------------------------------------------ fichiers JSON

    def _load_json(self, name: str) -> dict:
        try:
            data = json.loads((self.folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_json(self, name: str, data: dict) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / (name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            replace_atomic(tmp, self.folder / name)
        except OSError as exc:
            log.warning("%s non enregistré : %s", name, exc)

    def thresholds(self) -> dict:
        """Seuils choisis par l'opérateur : {type de réseau: {rtt_warn, rtt_alert, loss_warn, loss_alert}}."""
        data = self._load_json("seuils.json")
        return {k: v for k, v in data.items() if k in NET_TYPES and isinstance(v, dict)}

    def set_thresholds(self, net_type: str, values: dict | None) -> dict:
        data = self.thresholds()
        if values is None:
            data.pop(net_type, None)
        else:
            data[net_type] = {k: values[k] for k in ("rtt_warn", "rtt_alert", "loss_warn", "loss_alert")}
        self._save_json("seuils.json", data)
        return data

    def vpn(self) -> dict:
        return self._load_json("vpn.json")

    def save_vpn(self, data: dict) -> None:
        self._save_json("vpn.json", data)

    # ------------------------------------------------------------------ entretien

    def clear(self) -> None:
        """« Tout effacer » : journal, coupures, heures, appareils vus, avertissements ignorés. PAS les seuils choisis."""
        self._hours.clear()
        if not self.folder.is_dir():
            return
        for path in self.folder.iterdir():
            if path.name != "seuils.json" and path.suffix in (".jsonl", ".json", ".tmp"):
                try:
                    path.unlink()
                except OSError as exc:
                    log.warning("%s non effacé : %s", path.name, exc)

    def prune(self) -> None:
        """Une fois par jour : fichiers du jour trop anciens effacés, coupures et heures trop anciennes retirées."""
        now = self.wall_ms()
        today = _utc_day(now)
        if today == self._pruned_day or not self.folder.is_dir():
            return
        self._pruned_day = today
        oldest_log = _utc_day(now - self.log_days * DAY_MS)
        for path in self.folder.glob("????-??-??.jsonl"):
            if path.stem < oldest_log:
                try:
                    path.unlink()
                except OSError as exc:
                    log.warning("%s non effacé : %s", path.name, exc)
        limit = now - self.stats_days * DAY_MS
        for name, key in (("coupures.jsonl", "end_ms"), ("heures.jsonl", "hour_ms")):
            items = self._read(name)
            kept = [i for i in items if i.get(key, 0) >= limit]
            if len(kept) != len(items):
                try:
                    tmp = self.folder / (name + ".tmp")
                    tmp.write_text("".join(json.dumps(i, ensure_ascii=False, separators=(",", ":")) + "\n" for i in kept),
                                   encoding="utf-8")
                    replace_atomic(tmp, self.folder / name)
                except OSError as exc:
                    log.warning("%s non nettoyé : %s", name, exc)

    # ------------------------------------------------------------------ statistiques (net_stats)

    def stats(self, days: int, device: str, start_thresholds: dict) -> dict:
        """Vue « Qualité du réseau » (§ 10.1) des `days` derniers jours, tous appareils ("") ou un seul.
        `start_thresholds` : seuils de station.toml {rtt_warn, rtt_alert, loss_warn, loss_alert}."""
        now = self.wall_ms()
        since = now - days * DAY_MS
        outages = [o for o in self.outages(since) if not device or o.get("device") == device]
        all_hours = self.hours(since)
        hours = [h for h in all_hours if not device or h.get("device") == device]
        devices: dict[str, dict] = {}
        for h in all_hours:
            d = devices.setdefault(h.get("device", ""), {"device": h.get("device", ""), "agent": "", "last_ms": 0})
            if h["hour_ms"] >= d["last_ms"]:
                d["last_ms"], d["agent"] = h["hour_ms"], h.get("agent", "") or d["agent"]
        per_day: dict[str, dict] = {}

        def day(ms: int) -> dict:
            key = _local(ms).strftime("%Y-%m-%d")
            return per_day.setdefault(key, {"date": key, "outages": 0, "outage_s": 0.0, "by_diagnosis": {},
                                            "hours": [0] * 24, "windows": 0, "lost": 0, "expected": 0,
                                            "rtt_p95_sum": 0, "rtt_count": 0})

        by_diag: dict[str, int] = {}
        by_type: dict[str, dict] = {}
        for o in outages:
            d = day(o["start_ms"])
            d["outages"] += 1
            d["outage_s"] += o.get("duration_ms", 0) / 1000
            diag = o.get("diagnosis", "unknown")
            d["by_diagnosis"][diag] = d["by_diagnosis"].get(diag, 0) + 1
            d["hours"][_local(o["start_ms"]).hour] += 1
            by_diag[diag] = by_diag.get(diag, 0) + 1
            t = by_type.setdefault(o.get("net_type") or "unknown", {"windows": 0, "outages": 0, "lost": 0, "expected": 0})
            t["outages"] += 1
        hist: dict[str, dict] = {}
        for h in hours:
            d = day(h["hour_ms"])
            for k in ("windows", "lost", "expected", "rtt_p95_sum", "rtt_count"):
                d[k] += h.get(k, 0)
            net_type = h.get("net_type") or "unknown"
            t = by_type.setdefault(net_type, {"windows": 0, "outages": 0, "lost": 0, "expected": 0})
            for k in ("windows", "lost", "expected"):
                t[k] += h.get(k, 0)
            g = hist.setdefault(net_type, {"rtt": _empty_hist(calc.RTT_EDGES_MS), "loss": _empty_hist(calc.LOSS_EDGES_PCT),
                                           "days": set()})
            g["days"].add(_local(h["hour_ms"]).strftime("%Y-%m-%d"))
            for name in ("rtt", "loss"):
                for i, cell in enumerate(h.get(name + "_hist", [])[:len(g[name])]):
                    g[name][i][0] += cell[0]
                    g[name][i][1] += cell[1]

        def pct(part, whole):
            return calc.round1(100 * part / whole) if whole else None

        days_out = []
        for key in sorted(per_day):
            d = per_day[key]
            days_out.append({"date": key, "outages": d["outages"], "outage_s": round(d["outage_s"]),
                             "by_diagnosis": d["by_diagnosis"], "hours": d["hours"],
                             "loss_pct": pct(d["lost"], d["expected"]),
                             "rtt_p95_ms": round(d["rtt_p95_sum"] / d["rtt_count"]) if d["rtt_count"] else None})
        windows = sum(h.get("windows", 0) for h in hours)
        outage_s = sum(o.get("duration_ms", 0) for o in outages) / 1000
        connected_s = windows * WINDOW_S
        chosen = self.thresholds()
        thresholds = {}
        for net_type in NET_TYPES:
            g = hist.get(net_type)
            if g is None and net_type not in chosen:
                continue
            rtt_h = [{"n": n, "degraded": k} for n, k in (g["rtt"] if g else [])]
            loss_h = [{"n": n, "degraded": k} for n, k in (g["loss"] if g else [])]
            n_days = len(g["days"]) if g else 0
            thresholds[net_type] = {
                "in_force": chosen.get(net_type, start_thresholds), "chosen": net_type in chosen,
                "rtt_hist": g["rtt"] if g else [], "loss_hist": g["loss"] if g else [], "days": n_days,
                "proposed": {"rtt": calc.propose(rtt_h, calc.RTT_EDGES_MS, n_days) if g else None,
                             "loss": calc.propose(loss_h, calc.LOSS_EDGES_PCT, n_days) if g else None},
            }
        recent = sorted(outages, key=lambda o: o["start_ms"], reverse=True)[:50]
        return {
            "days": days, "device": device, "now_ms": now,
            "devices": sorted(devices.values(), key=lambda d: -d["last_ms"]),
            "summary": {"outages": len(outages), "outage_s": round(outage_s),
                        "longest_s": round(max((o.get("duration_ms", 0) for o in outages), default=0) / 1000),
                        "connected_s": connected_s,
                        "availability_pct": pct(connected_s, connected_s + outage_s) if connected_s else None,
                        "loss_pct": pct(sum(h.get("lost", 0) for h in hours), sum(h.get("expected", 0) for h in hours))},
            "per_day": days_out,
            "by_diagnosis": by_diag,
            "by_net_type": {k: {"windows": v["windows"], "outages": v["outages"], "loss_pct": pct(v["lost"], v["expected"])}
                            for k, v in by_type.items()},
            "thresholds": thresholds,
            "edges": {"rtt_ms": list(calc.RTT_EDGES_MS), "loss_pct": list(calc.LOSS_EDGES_PCT)},
            "outages_list": [{k: o.get(k) for k in ("start_ms", "end_ms", "duration_ms", "diagnosis", "basis", "agent",
                                                    "net_type", "kind")} for o in recent],
        }

