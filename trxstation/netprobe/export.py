# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Rapport lisible et export anonyme de la sonde réseau (docs/netprobe-cahier-des-charges.md § 10.3, EF10).

Un seul rapport pour trois usages : `trx-netreport`, TRX Console (menu 23) et le bouton « Exporter » de la page et
de l'application (commande `net_export`). L'export est un zip :
  rapport.html   la synthèse, lisible hors ligne ;
  donnees.json   coupures et résumés horaires des `days` derniers jours, résumés de 10 s des dernières 24 h,
                 version, identifiant de station, réglages [netprobe] sans adresse, seuils choisis.
ANONYME : identifiants d'appareils remplacés par appareil-1, -2… ; aucun nom de compte, aucune adresse IP, aucune
position (il n'en existe pas) ; les identifiants de cellules ne sont pas relevés par la station.
"""
from __future__ import annotations

import html
import io
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .store import DAY_MS, NetStore

DIAGNOSIS_TEXT = {
    "app_station": "application ou machine de la station", "lan": "réseau local ou machine de la station",
    "box_internet": "connexion Internet de la box", "webrtc": "WebRTC ou passerelle", "phone_radio": "radio du téléphone",
    "vpn_shared": "profil VPN probablement partagé", "mobile_or_tunnel": "téléphone, réseau mobile ou tunnel",
    "unknown": "indéterminé",
}
NET_TYPES = {"lan": "réseau local", "wifi": "Wi-Fi", "4g": "4G", "5g": "5G", "mobile": "mobile", "unknown": "inconnu"}
MAX_EXPORT_BYTES = 2_000_000
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")     # IPv4 ; les avertissements (seuls à porter des adresses) ne partent pas


def duration(seconds: float | None) -> str:
    s = int(round(seconds or 0))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d}"


def report_text(stats: dict, title: str = "") -> str:
    """Synthèse lisible de `NetStore.stats` (trx-netreport, console, rapport.html)."""
    s = stats["summary"]
    days = stats["days"]
    out = [title or f"Qualité du réseau : {'24 dernières heures' if days == 1 else f'{days} derniers jours'}", ""]
    out.append(f"  Coupures            : {s['outages']}  (durée cumulée {duration(s['outage_s'])}, "
               f"la plus longue {duration(s['longest_s'])})")
    out.append(f"  Temps connecté      : {duration(s['connected_s'])}"
               + (f"  (disponibilité {s['availability_pct']} %)" if s.get("availability_pct") is not None else ""))
    if s.get("loss_pct") is not None:
        out.append(f"  Perte moyenne       : {s['loss_pct']} % des battements")
    if stats["by_diagnosis"]:
        out += ["", "  Tronçon probable des coupures :"]
        total = sum(stats["by_diagnosis"].values())
        for code, n in sorted(stats["by_diagnosis"].items(), key=lambda kv: -kv[1]):
            out.append(f"    {n:4d}  ({round(100 * n / total):3d} %)  {DIAGNOSIS_TEXT.get(code, code)}")
    hours = [0] * 24
    for d in stats["per_day"]:
        for h, n in enumerate(d.get("hours", [])[:24]):
            hours[h] += n
    if any(hours):
        top = sorted(range(24), key=lambda h: -hours[h])[:3]
        out += ["", "  Heures les plus touchées : " + ", ".join(f"{h} h ({hours[h]})" for h in top if hours[h])]
    if stats["per_day"]:
        out += ["", "  Par jour :"]
        for d in stats["per_day"]:
            extra = []
            if d.get("loss_pct") is not None:
                extra.append(f"perte {d['loss_pct']} %")
            if d.get("rtt_p95_ms") is not None:
                extra.append(f"aller-retour p95 {d['rtt_p95_ms']} ms")
            out.append(f"    {d['date']}  {d['outages']:3d} coupure(s), {duration(d['outage_s'])}"
                       + ("  · " + " · ".join(extra) if extra else ""))
    if stats["by_net_type"]:
        out += ["", "  Par réseau :"]
        for k, v in stats["by_net_type"].items():
            out.append(f"    {NET_TYPES.get(k, k):12s} {duration(v['windows'] * 10)} mesurés, {v['outages']} coupure(s)"
                       + (f", perte {v['loss_pct']} %" if v.get("loss_pct") is not None else ""))
    if stats["outages_list"]:
        out += ["", "  Dernières coupures :"]
        for o in stats["outages_list"][:10]:
            when = datetime.fromtimestamp(o["start_ms"] / 1000).strftime("%d/%m %H:%M:%S")
            out.append(f"    {when}  {duration((o.get('duration_ms') or 0) / 1000):>9}  "
                       f"{DIAGNOSIS_TEXT.get(o.get('diagnosis'), 'en cours de diagnostic')}"
                       + (f"  ({o['agent']})" if o.get("agent") else ""))
    return "\n".join(out) + "\n"


def _anonymous(items: list[dict], devices: dict[str, str]) -> list[dict]:
    out = []
    for item in items:
        clean = {k: v for k, v in item.items() if k not in ("client", "source", "address", "warning")}
        if "device" in clean:
            clean["device"] = devices.setdefault(str(clean["device"]), f"appareil-{len(devices) + 1}")
        out.append(clean)
    return out


def _scrub(text: str) -> str:
    """Dernier filet : toute adresse IP restée dans un texte est masquée."""
    return IP_RE.sub("adresse-masquée", text)


def build_export(store: NetStore, days: int, *, version: str, station_id: str = "", settings: dict | None = None) -> bytes:
    """Zip anonyme (rapport.html + donnees.json) ; au plus MAX_EXPORT_BYTES (résumés de 10 s coupés au besoin)."""
    store.flush()
    now = store.wall_ms()
    stats = store.stats(days, "", {})
    devices: dict[str, str] = {}
    outages = _anonymous(store.outages(now - days * DAY_MS), devices)
    hours = _anonymous(store.hours(now - days * DAY_MS), devices)
    recent: list[dict] = []
    for name in sorted({datetime.fromtimestamp((now - k * DAY_MS) / 1000, timezone.utc).strftime("%Y-%m-%d") for k in (1, 0)}):
        recent += [r for r in store._read(name + ".jsonl") if r.get("ts", 0) >= now - DAY_MS]
    recent = _anonymous([r for r in recent if r.get("src") != "sonde" or "lan" in r or "internet" in r], devices)
    for r in recent:                                    # sondes : nom de la cible gardé, adresse retirée
        for key in ("lan", "internet"):
            if isinstance(r.get(key), dict):
                r[key] = {k: v for k, v in r[key].items() if k != "address"}
    safe_settings = {k: v for k, v in (settings or {}).items() if k not in ("lan_target", "internet_target")}
    stats_public = dict(stats, devices=[{"device": devices.setdefault(d["device"], f"appareil-{len(devices) + 1}"),
                                         "agent": d["agent"], "last_ms": d["last_ms"]} for d in stats["devices"]])
    data = {"format": 1, "made_at": datetime.now().astimezone().isoformat(timespec="seconds"), "version": version,
            "station_id": station_id, "days": days, "settings": safe_settings, "thresholds_chosen": store.thresholds(),
            "stats": stats_public, "outages": outages, "hours": hours, "last_24h": recent}
    text = report_text(stats)
    page = ("<!doctype html>\n<html lang=\"fr\"><meta charset=\"utf-8\"><title>Qualité du réseau OpenRemoteTRX</title>"
            "<style>body{font-family:system-ui,sans-serif;margin:1.5rem;color:#1b2430}pre{font-size:.9rem;line-height:1.35}"
            "</style><h1>Qualité du réseau : rapport anonyme</h1>"
            f"<p>Station {html.escape(version)} · {html.escape(data['made_at'])} · identifiant {html.escape(station_id or '—')}</p>"
            f"<pre>{html.escape(text)}</pre><p>Données détaillées : donnees.json (même zip).</p></html>\n")
    while True:
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("rapport.html", _scrub(page))
            z.writestr("donnees.json", _scrub(json.dumps(data, ensure_ascii=False, indent=1)))
        blob = raw.getvalue()
        if len(blob) <= MAX_EXPORT_BYTES or not data["last_24h"]:
            return blob
        data["last_24h"] = data["last_24h"][len(data["last_24h"]) // 2:]     # trop gros : la moitié la plus ancienne part


def export_name(now: float | None = None) -> str:
    return "openremotetrx-reseau-" + time.strftime("%Y%m%d-%H%M", time.localtime(now)) + ".zip"


def store_of(state_dir: str | Path, cfg=None) -> NetStore:
    """Journal de la station en LECTURE (trx-netreport, console) : rien n'y est écrit."""
    if cfg is None:
        return NetStore(Path(state_dir) / "netprobe")
    return NetStore(Path(state_dir) / "netprobe", cfg.log_retention_days, cfg.stats_retention_days)
