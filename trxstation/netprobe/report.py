# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Validation des messages de la sonde envoyés par les clients (docs/netprobe-cahier-des-charges.md § 4.6, § 11).

Un client ne peut rien imposer à la station : chaque champ est vérifié (type, bornes) et tout champ inconnu est
ignoré (un client plus récent peut en envoyer de nouveaux). Une valeur hors bornes refuse le message entier.
"""
from __future__ import annotations

import ipaddress
import math
import re

NET_TYPES = ("lan", "wifi", "4g", "5g", "mobile", "unknown")
MAX_BACKLOG = 90                                 # 15 min de résumés de 10 s
EPOCH_MIN_MS, EPOCH_MAX_MS = 1_600_000_000_000, 4_102_444_800_000      # 2020 .. 2100
DEVICE_RE = re.compile(r"^[0-9a-f]{32}$")
AGENT_RE = re.compile(r"^[\w .,()/+:-]{1,48}$")
ICE_STATES = ("new", "checking", "connected", "completed", "disconnected", "failed", "closed")

# champ -> (bas, haut) ; None accepté (mesure absente)
_NUMBERS = {"loss_pct": (0, 100), "rtt_mean_ms": (0, 60_000), "rtt_p95_ms": (0, 60_000), "jitter_ms": (0, 60_000),
            "rsrp_dbm": (-160, -20), "sinr_db": (-30, 50), "concealed_pct": (0, 100), "signal_level": (0, 4)}
_COUNTS = ("health_ok", "health_fail")
_FLAGS = ("degraded", "cell_changed", "net_switched")


class ReportInvalid(ValueError):
    pass


def _number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def int_field(data: dict, name: str, low: int, high: int, required: bool = True) -> int | None:
    value = data.get(name)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ReportInvalid(f"{name} : entier entre {low} et {high} attendu")
    return value


def clean_report(data) -> dict:
    """Résumé de 10 s d'un client (net_report, éléments de net_backlog) : dictionnaire propre ou ReportInvalid."""
    if not isinstance(data, dict):
        raise ReportInvalid("report : objet attendu")
    out: dict = {"t": int_field(data, "t", EPOCH_MIN_MS, EPOCH_MAX_MS)}
    net_type = data.get("net_type")
    if net_type is not None and net_type not in NET_TYPES:
        raise ReportInvalid("net_type : " + ", ".join(NET_TYPES) + " ou null")
    out["net_type"] = net_type
    for name, (low, high) in _NUMBERS.items():
        value = data.get(name)
        if value is not None and (not _number(value) or not low <= value <= high):
            raise ReportInvalid(f"{name} : nombre entre {low} et {high} ou null")
        out[name] = value
    for name in _COUNTS:
        out[name] = int_field(data, name, 0, 100, required=False) or 0
    for name in _FLAGS:
        value = data.get(name, False)
        if not isinstance(value, bool):
            raise ReportInvalid(f"{name} : true ou false")
        out[name] = value
    ice = data.get("ice")
    if ice is not None and ice not in ICE_STATES:
        raise ReportInvalid("ice : état ICE inconnu")
    out["ice"] = ice
    return out


def clean_backlog(items) -> list[dict]:
    if not isinstance(items, list) or len(items) > MAX_BACKLOG:
        raise ReportInvalid(f"reports : liste de {MAX_BACKLOG} résumés au plus")
    return [clean_report(item) for item in items]


def clean_device(value) -> str:
    """Identifiant d'appareil tiré au hasard par le client (128 bits en hexadécimal) ; "" = inconnu."""
    return value if isinstance(value, str) and DEVICE_RE.fullmatch(value) else ""


def clean_agent(value) -> str:
    """« page Windows », « android 0.53.0 »... : affiché à l'opérateur, jamais interprété."""
    return value if isinstance(value, str) and AGENT_RE.fullmatch(value) else ""


def clean_address(value) -> str:
    if not isinstance(value, str) or len(value) > 45:
        raise ReportInvalid("address : adresse IP attendue")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise ReportInvalid("address : adresse IP attendue") from None


def clean_thresholds(data: dict) -> dict:
    """Seuils choisis par l'opérateur pour un type de réseau (net_thresholds) : {net_type, reset} ou les quatre seuils."""
    net_type = data.get("net_type")
    if net_type not in NET_TYPES:
        raise ReportInvalid("net_type : " + ", ".join(NET_TYPES))
    if data.get("reset") is True:
        return {"net_type": net_type, "reset": True}
    out = {"net_type": net_type}
    for name, (low, high) in (("rtt_warn", (20, 5000)), ("rtt_alert", (20, 5000)),
                              ("loss_warn", (0.1, 100)), ("loss_alert", (0.1, 100))):
        value = data.get(name)
        if not _number(value) or not low <= value <= high:
            raise ReportInvalid(f"{name} : nombre entre {low} et {high}")
        out[name] = value
    if out["rtt_warn"] >= out["rtt_alert"] or out["loss_warn"] >= out["loss_alert"]:
        raise ReportInvalid("le seuil orange doit être plus petit que le seuil rouge")
    return out
