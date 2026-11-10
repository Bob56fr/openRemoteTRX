# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Preuve de travail demandée à l'enregistrement d'une station (hashcash SHA-256).

Valide si `SHA-256("orx-presence pow v1\\0" || station_id || "\\0" || décimal(nonce))` commence par au moins
`bits` bits nuls. Le relais choisit `bits` (20 par défaut : quelques secondes sur un Pi 4) ; vérifier coûte un
seul calcul.
"""
from __future__ import annotations

import hashlib

POW_DOMAIN = b"orx-presence pow v1\0"
DEFAULT_BITS = 20
MAX_BITS = 32
MAX_NONCE = 2**53 - 1          # entier exact en JSON comme en PHP


def pow_hash(station_id: str, nonce: int) -> bytes:
    return hashlib.sha256(POW_DOMAIN + station_id.encode("ascii") + b"\0" + str(nonce).encode("ascii")).digest()


def leading_zero_bits(digest: bytes) -> int:
    count = 0
    for byte in digest:
        if byte:
            return count + 8 - byte.bit_length()
        count += 8
    return count


def pow_ok(station_id: str, nonce: int, bits: int) -> bool:
    if isinstance(nonce, bool) or not isinstance(nonce, int) or not 0 <= nonce <= MAX_NONCE:
        return False
    return leading_zero_bits(pow_hash(station_id, nonce)) >= bits


def pow_solve(station_id: str, bits: int, start: int = 0) -> int:
    if not 0 <= bits <= MAX_BITS:
        raise ValueError("difficulté hors bornes")
    nonce = start
    while leading_zero_bits(pow_hash(station_id, nonce)) < bits:
        nonce += 1
    return nonce
