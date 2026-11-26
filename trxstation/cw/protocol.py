# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Paquets du canal `cw` (cahier § 5.2) : validation stricte de l'entrée réseau.

{"type":"cw","seq":3,"edges":[[41,1,1532],[42,0,1592]],"lease":1610}
`edges` = [id, état 1 (clé fermée) / 0 (clé ouverte), ts], ts en ms depuis le début de la séquence (horloge du
client) ; `lease` = jusqu'où (ts) le client garantit l'état de la clé, donc jamais avant le dernier front annoncé.
Tout paquet mal formé lève ValueError : la passerelle l'ignore (jamais une raison de quitter).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MAX_EDGES = 32                       # fenêtre des fronts récents, au plus 32 (§ 5.1)
MAX_ID = 2 ** 31 - 1
MAX_SEQ = 2 ** 31 - 1
MAX_TS_MS = 6 * 3600 * 1000.0        # une séquence de plus de 6 h est une erreur


@dataclass(frozen=True)
class Edge:
    id: int
    down: bool                       # True = clé fermée (tonalité)
    ts: float                        # ms depuis le début de la séquence


@dataclass(frozen=True)
class CwPacket:
    seq: int
    edges: tuple[Edge, ...]
    lease: float                     # ms, même horloge que ts


def _int(value: object, name: str, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= high:
        raise ValueError(f"{name} invalide")
    return value


def _ms(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} invalide")
    v = float(value)
    if not math.isfinite(v) or not 0.0 <= v <= MAX_TS_MS:
        raise ValueError(f"{name} hors limites")
    return v


def parse_packet(msg: object) -> CwPacket:
    if not isinstance(msg, dict) or msg.get("type") != "cw":
        raise ValueError("pas un paquet cw")
    seq = _int(msg.get("seq"), "seq", MAX_SEQ)
    raw = msg.get("edges", [])
    if not isinstance(raw, list) or len(raw) > MAX_EDGES:
        raise ValueError("edges invalide")
    edges: list[Edge] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError("front invalide")
        state = item[1]
        if isinstance(state, bool) or state not in (0, 1):
            raise ValueError("état de front invalide")
        edges.append(Edge(_int(item[0], "id", MAX_ID), state == 1, _ms(item[2], "ts")))
    ids = [e.id for e in edges]
    if len(set(ids)) != len(ids):
        raise ValueError("id en double dans un paquet")
    if any(b.ts < a.ts for a, b in zip(edges, edges[1:])):
        raise ValueError("fronts non rangés")
    lease = _ms(msg.get("lease"), "lease")
    if edges and lease < edges[-1].ts:
        raise ValueError("bail avant le dernier front")
    return CwPacket(seq, tuple(edges), lease)
