# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Calculs purs de la sonde de qualité réseau (docs/netprobe-cahier-des-charges.md § 4.4, 4.5, 7, 8.3, 9.1, 9.6).

MÊMES calculs dans la page (static/netprobe.js) et l'application (logic/NetProbe.kt) : exemples partagés
tests/protocol/netprobe_vectors.json. Toutes les durées sont des entiers en ms, mesurés sur l'horloge MONOTONE de
celui qui envoie le battement : les horloges des deux côtés ne sont jamais comparées entre elles.

Rien ici n'agit sur le poste : la sonde mesure et affiche, elle ne coupe ni ne déclenche jamais une émission.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LATE_MS = 5_000                          # net_pong arrivé après 5 s : perdu ET « tardif »
WINDOWS_MS = (10_000, 60_000)            # fenêtres glissantes des indicateurs
MIN_MEASURED_MS = 10_000                 # indicateur gris avant 10 s de mesures
RECENT_OUTAGE_MS = 120_000               # coupure close depuis moins de 2 min : au moins orange

# Cases des histogrammes (§ 9.6) : case i = valeurs < EDGES[i] ; la dernière = au-delà.
RTT_EDGES_MS = (50, 100, 150, 200, 250, 300, 400, 600, 800, 1000)
LOSS_EDGES_PCT = (0.5, 1, 2, 5, 10, 20)
PROPOSE_MIN_WINDOWS = 2_000              # fenêtres de 10 s d'un type de réseau avant toute proposition
PROPOSE_MIN_DAYS = 7
PROPOSE_MIN_BUCKET = 20                  # une case trop peu remplie ne décide rien
PROPOSE_WARN_RATIO = 0.05                # son dégradé dans plus de 5 % des fenêtres de la case : orange
PROPOSE_ALERT_RATIO = 0.25               # plus de 25 % : rouge

# Motif régulier des coupures (§ 8.3), signature d'un profil VPN partagé
PATTERN_WINDOW_MS = 600_000
PATTERN_MIN_OUTAGES = 4
PATTERN_MIN_PERIOD_MS = 10_000
PATTERN_MAX_PERIOD_MS = 150_000
PATTERN_MAX_PERIOD_CV = 0.25
PATTERN_MAX_DURATION_CV = 0.5

# Diagnostic (§ 7), dans l'ordre des règles
DIAGNOSES = ("app_station", "lan", "box_internet", "webrtc", "phone_radio", "vpn_shared", "mobile_or_tunnel", "unknown")


def round1(value: float) -> float:
    """Arrondi au dixième, moitié vers le haut : le même dans les trois codes (pas l'arrondi bancaire de Python)."""
    return math.floor(value * 10 + 0.5) / 10


@dataclass(frozen=True)
class Beat:
    """Un net_ping envoyé : son numéro, son heure d'envoi et l'heure d'arrivée de son net_pong (None : pas encore)."""
    seq: int
    sent_ms: int
    pong_ms: int | None = None


def window_stats(beats: list[Beat], now_ms: int, window_ms: int) -> dict:
    """Indicateurs d'une fenêtre glissante (§ 4.4), vus par celui qui envoie les net_ping.

    Comptés : les battements envoyés dans ]now - fenêtre, now]. Un battement sans écho depuis moins de LATE_MS est EN
    ATTENTE (ni reçu ni perdu) ; sans écho depuis LATE_MS, ou avec un écho arrivé après LATE_MS (« tardif »), il est
    perdu. Gigue : formule de la RFC 3550 (J += (|D| - J) / 16) appliquée aux temps aller-retour successifs, dans
    l'ordre des numéros : elle ne dépend que de l'horloge de l'émetteur. Hors séquence : échos arrivés après un écho
    de numéro plus grand.
    """
    inside = [b for b in beats if now_ms - window_ms < b.sent_ms <= now_ms]
    received: list[Beat] = []
    lost = late = 0
    for b in inside:
        if b.pong_ms is not None and b.pong_ms <= now_ms:
            if b.pong_ms - b.sent_ms >= LATE_MS:
                lost += 1
                late += 1
            else:
                received.append(b)
        elif now_ms - b.sent_ms >= LATE_MS:
            lost += 1
    expected = len(received) + lost
    rtts = [b.pong_ms - b.sent_ms for b in sorted(received, key=lambda b: b.seq)]
    jitter = 0.0
    for previous, current in zip(rtts, rtts[1:]):
        jitter += (abs(current - previous) - jitter) / 16
    out_of_order = 0
    highest = None
    for b in sorted(received, key=lambda b: (b.pong_ms, b.seq)):
        if highest is not None and b.seq < highest:
            out_of_order += 1
        highest = b.seq if highest is None else max(highest, b.seq)
    ordered = sorted(rtts)
    return {
        "expected": expected,
        "received": len(received),
        "lost": lost,
        "late": late,
        "loss_pct": round1(100 * lost / expected) if expected else None,
        "rtt_mean_ms": round1(sum(rtts) / len(rtts)) if rtts else None,
        "rtt_p95_ms": ordered[(95 * len(ordered) + 99) // 100 - 1] if ordered else None,   # rang le plus proche, en entiers
        "rtt_max_ms": ordered[-1] if ordered else None,
        "jitter_ms": round1(jitter) if len(rtts) > 1 else None,
        "out_of_order": out_of_order,
    }


class OutageDetector:
    """Coupures (§ 4.5) : une coupure commence quand `missed` battements envoyés depuis le dernier écho reçu sont restés
    sans réponse pendant au moins un intervalle chacun ; elle commence à l'envoi du PREMIER d'entre eux et finit au
    premier écho reçu, quel que soit son numéro (même un écho tardif prouve que le lien est revenu)."""

    def __init__(self, missed: int = 3, interval_ms: int = 1_000) -> None:
        self.missed = missed
        self.interval_ms = interval_ms
        self._pending: dict[int, int] = {}      # numéro -> heure d'envoi, battements envoyés depuis le dernier écho
        self.start_ms: int | None = None        # coupure en cours (None : aucune)

    def ping(self, seq: int, now_ms: int) -> list[dict]:
        events = self.tick(now_ms)
        self._pending[seq] = now_ms
        return events

    def pong(self, seq: int, now_ms: int) -> list[dict]:
        self._pending.clear()                   # les battements d'avant cet écho ne comptent plus
        if self.start_ms is None:
            return []
        start, self.start_ms = self.start_ms, None
        return [{"type": "end", "start_ms": start, "end_ms": now_ms, "duration_ms": now_ms - start}]

    def tick(self, now_ms: int) -> list[dict]:
        if self.start_ms is not None:
            return []
        missed = sorted(t for t in self._pending.values() if now_ms - t >= self.interval_ms)
        if len(missed) < self.missed:
            return []
        self.start_ms = missed[0]
        return [{"type": "start", "start_ms": missed[0], "detected_ms": now_ms}]


def level(measured_ms: int, loss_pct: float | None, rtt_p95_ms: float | None, outage_active: bool,
          since_outage_end_ms: int | None, rsrp_dbm: float | None, sinr_db: float | None, th: dict) -> str:
    """Niveau de l'indicateur (§ 9.1) : gray, green, orange ou red. Seuils `th` : loss_warn, loss_alert, rtt_warn,
    rtt_alert, rsrp_warn, rsrp_alert, sinr_warn, sinr_alert. Un palier est atteint à partir de sa valeur (>=) ; un signal
    est faible strictement SOUS son seuil. Les champs radio absents (None) ne comptent pas."""
    if outage_active:
        return "red"
    if measured_ms < MIN_MEASURED_MS:
        return "gray"
    if (loss_pct is not None and loss_pct >= th["loss_alert"]) or (rtt_p95_ms is not None and rtt_p95_ms >= th["rtt_alert"]) \
            or (rsrp_dbm is not None and rsrp_dbm < th["rsrp_alert"]) or (sinr_db is not None and sinr_db < th["sinr_alert"]):
        return "red"
    if (since_outage_end_ms is not None and since_outage_end_ms < RECENT_OUTAGE_MS) \
            or (loss_pct is not None and loss_pct >= th["loss_warn"]) or (rtt_p95_ms is not None and rtt_p95_ms >= th["rtt_warn"]) \
            or (rsrp_dbm is not None and rsrp_dbm < th["rsrp_warn"]) or (sinr_db is not None and sinr_db < th["sinr_warn"]):
        return "orange"
    return "green"


def diagnose(facts: dict) -> str:
    """Tronçon probable d'une coupure (§ 7) : la PREMIÈRE règle qui convient. Faits (absents = inconnus) :
    station_restarted, lan_probe_down, internet_probe_down (sondes de la station), backlog (le client a remis ses
    10 minutes), health_ok (/health a répondu pendant la coupure), radio_weak, cell_changed, network_switched (dans les
    10 s d'avant), regular_pattern (§ 8.3)."""
    if facts.get("station_restarted"):
        return "app_station"
    if facts.get("lan_probe_down"):
        return "lan"
    if facts.get("internet_probe_down"):
        return "box_internet"
    if not facts.get("backlog"):
        return "unknown"                       # sans les 10 minutes du client, rien de plus n'est sûr
    if facts.get("health_ok"):
        return "webrtc"
    if facts.get("radio_weak") or facts.get("cell_changed") or facts.get("network_switched"):
        return "phone_radio"
    if facts.get("regular_pattern"):
        return "vpn_shared"
    if facts.get("health_ok") is False:
        return "mobile_or_tunnel"
    return "unknown"


def _cv(values: list[float]) -> float:
    mean = sum(values) / len(values)
    if mean <= 0:
        return math.inf
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) / mean


def regular_pattern(outages: list[dict], now_ms: int) -> dict:
    """Motif régulier (§ 8.3) : au moins 4 coupures commencées dans les 10 dernières minutes, intervalles entre débuts
    réguliers (coefficient de variation < 0,25, moyenne de 10 à 150 s) et durées voisines (CV < 0,5). La radio est
    vérifiée à part (règle 5 du diagnostic avant celle-ci). `outages` : {start_ms, duration_ms}."""
    recent = sorted((o for o in outages if now_ms - PATTERN_WINDOW_MS < o["start_ms"] <= now_ms), key=lambda o: o["start_ms"])
    if len(recent) < PATTERN_MIN_OUTAGES:
        return {"regular": False, "period_ms": None}
    gaps = [b["start_ms"] - a["start_ms"] for a, b in zip(recent, recent[1:])]
    period = sum(gaps) / len(gaps)
    regular = (PATTERN_MIN_PERIOD_MS <= period <= PATTERN_MAX_PERIOD_MS and _cv(gaps) < PATTERN_MAX_PERIOD_CV
               and _cv([o["duration_ms"] for o in recent]) < PATTERN_MAX_DURATION_CV)
    return {"regular": regular, "period_ms": math.floor(period + 0.5) if regular else None}


def bucket(value: float, edges: tuple) -> int:
    """Case d'histogramme (§ 9.6) : premier i tel que value < edges[i], sinon len(edges)."""
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


def lower_edge(index: int, edges: tuple) -> float:
    return 0 if index == 0 else edges[index - 1]


def propose(hist: list[dict], edges: tuple, days: float) -> dict | None:
    """Seuils proposés pour UN type de réseau et UNE mesure (aller-retour ou perte), § 9.6. `hist` : une case par
    entrée {n, degraded} (fenêtres de 10 s, et parmi elles celles au son dégradé). Orange = bas de la première case
    (assez remplie) où le son est dégradé dans plus de 5 % des fenêtres, rouge = plus de 25 % ; jamais sous le bas de
    la case du p75 habituel ni sous la première limite. None : pas assez de mesures, ou aucune case parlante."""
    total = sum(h["n"] for h in hist)
    if total < PROPOSE_MIN_WINDOWS or days < PROPOSE_MIN_DAYS:
        return None
    seen = 0
    p75 = len(hist) - 1
    for i, h in enumerate(hist):
        seen += h["n"]
        if seen >= 0.75 * total:
            p75 = i
            break
    floor_value = max(lower_edge(p75, edges), edges[0])

    def first(ratio: float) -> float | None:
        for i, h in enumerate(hist):
            if h["n"] >= PROPOSE_MIN_BUCKET and h["degraded"] > ratio * h["n"]:
                return max(lower_edge(i, edges), floor_value)
        return None

    warn, alert = first(PROPOSE_WARN_RATIO), first(PROPOSE_ALERT_RATIO)
    if warn is None:
        return None
    if alert is None or alert <= warn:
        above = [e for e in edges if e > warn]
        alert = above[0] if above else None
    return {"warn": warn, "alert": alert}


def simulate(hist: list[dict], edges: tuple, warn: float, alert: float) -> dict:
    """Ce qu'auraient donné des seuils sur l'historique (curseurs du § 9.6), sans rien changer sur la station : une
    case dont le bas atteint `alert` compte rouge, `warn` orange, sinon vert."""
    total = sum(h["n"] for h in hist)
    counts = {"green": [0, 0], "orange": [0, 0], "red": [0, 0]}
    for i, h in enumerate(hist):
        low = lower_edge(i, edges)
        color = "red" if low >= alert else "orange" if low >= warn else "green"
        counts[color][0] += h["n"]
        counts[color][1] += h["degraded"]

    def pct(part: int, whole: int) -> float | None:
        return round1(100 * part / whole) if whole else None

    return {
        "orange_pct": pct(counts["orange"][0], total),
        "red_pct": pct(counts["red"][0], total),
        "degraded_red_pct": pct(counts["red"][1], counts["red"][0]),
        "degraded_green_pct": pct(counts["green"][1], counts["green"][0]),
    }
