# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Statistiques de l'administrateur (cahier § 11), calculées sur SA station à partir des états reçus.

Agrégées par jour seulement (pas d'emploi du temps) : secondes vues « En QSO » et « En RX », jour actif ; 6 mois
gardés. Les heures où la station de l'administrateur était éteinte ne sont pas comptées (« non observé »).
Données : `{groupe: {membre: {"AAAA-MM-JJ": [secondes Q, secondes R]}}}`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo

RETENTION_DAYS = 183
MAX_STEP_S = 300          # un état ne compte pas plus de 5 min (relais muet, station de l'admin endormie)


def record(stats: dict, group: str, member: str, code: str, elapsed_s: float, now: float, tz: tzinfo) -> None:
    if code not in ("Q", "R") or elapsed_s <= 0:
        return
    day = datetime.fromtimestamp(now, tz).date().isoformat()
    cell = stats.setdefault(group, {}).setdefault(member, {}).setdefault(day, [0, 0])
    cell[0 if code == "Q" else 1] += int(min(elapsed_s, MAX_STEP_S))


def prune(stats: dict, now: float, tz: tzinfo, groups: set[str] | None = None) -> None:
    """Retire les jours trop vieux, et les groupes que la station n'administre plus (`groups`)."""
    limit = (datetime.fromtimestamp(now, tz).date() - timedelta(days=RETENTION_DAYS)).isoformat()
    for g in list(stats):
        if groups is not None and g not in groups:
            del stats[g]
            continue
        for member in list(stats[g]):
            days = {d: v for d, v in stats[g][member].items() if d >= limit}
            if days:
                stats[g][member] = days
            else:
                del stats[g][member]


def summary(stats: dict, group: str, now: float, tz: tzinfo) -> dict[str, dict]:
    """Par membre : dernier jour actif, jours actifs du mois en cours, minutes Q / R des 4 dernières semaines."""
    today = datetime.fromtimestamp(now, tz).date()
    out: dict[str, dict] = {}
    for member, days in stats.get(group, {}).items():
        active = sorted(d for d, (q, r) in days.items() if q + r > 0)
        weeks = []
        for back in range(4):
            start = today - timedelta(days=today.weekday() + 7 * back)
            span = {(start + timedelta(days=i)).isoformat() for i in range(7)}
            q = sum(v[0] for d, v in days.items() if d in span)
            r = sum(v[1] for d, v in days.items() if d in span)
            weeks.append({"week": start.isoformat(), "qso_min": q // 60, "rx_min": r // 60})
        month = today.strftime("%Y-%m")
        out[member] = {"last_active": active[-1] if active else None,
                       "active_days_month": sum(1 for d in active if d.startswith(month)),
                       "weeks": weeks}
    return out
