"""Calculs de la mesure de latence (sans dépendance réseau, donc testables)."""
from __future__ import annotations

import statistics


def latencies(emitted: list[float], arrived: list[float]) -> list[float]:
    """Pour chaque arrivée : délai depuis la dernière salve émise avant elle."""
    out = []
    for t in arrived:
        before = [e for e in emitted if e <= t]
        if before and t - before[-1] < 1.0:
            out.append(t - before[-1])
    return out


def describe(name: str, values: list[float]) -> str:
    if not values:
        return f"{name} : aucune mesure"
    values = sorted(values)
    p95 = values[min(len(values) - 1, int(0.95 * len(values)))]
    return (f"{name} : médiane {statistics.median(values) * 1000:.0f} ms, "
            f"p95 {p95 * 1000:.0f} ms, max {values[-1] * 1000:.0f} ms ({len(values)} mesures)")
