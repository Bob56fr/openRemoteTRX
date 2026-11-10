# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Requêtes signées au relais, filtres du pseudo, du texte libre et du mode (docs/protocole-presence.md § 3).

Chaque requête est un POST JSON. En-têtes :
- `X-Orx-Station` : identifiant de la station (32 caractères hexadécimaux) ;
- `X-Orx-Signature` : base64url de la signature Ed25519 de
  `"orx-relay v1\\n" || "POST" || "\\n" || chemin || "\\n" || corps` (le corps tel qu'envoyé, octet pour octet).
Le corps contient `t` (secondes Unix, tolérance ±600 s) et `n` (compteur strictement croissant par station :
millisecondes Unix, ou le dernier + 1 si l'horloge recule).
"""
from __future__ import annotations

import re
import time

from . import crypto
from .codec import Malformed, b64d, b64e, cjson, parse_json

REQ_DOMAIN = b"orx-relay v1\n"
CLOCK_TOLERANCE_S = 600
MAX_BODY = 16 * 1024
MAX_COUNTER = 2**53 - 1

PSEUDO_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9 ./_-]{0,14}[A-Za-z0-9./_-])?")
TEXT_RE = re.compile(r"[A-Za-z0-9./-](?:[A-Za-z0-9 ./-]{0,14}[A-Za-z0-9./-])?")
MODE_RE = re.compile(r"[A-Z0-9-]{1,12}")
MIN_FREQ_HZ, MAX_FREQ_HZ = 100_000, 3_000_000_000     # comme le QSY des modules (gateway_bridge)


class RequestRefused(ValueError):
    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


def signed_bytes(path: str, body: bytes) -> bytes:
    if not path.startswith("/") or "\n" in path:
        raise ValueError("chemin invalide")
    return REQ_DOMAIN + b"POST\n" + path.encode("ascii") + b"\n" + body


class Counter:
    """Compteur des requêtes et des états : millisecondes Unix, toujours plus grand que le précédent."""

    def __init__(self, last: int = 0, clock=time.time) -> None:
        self.last = last
        self._clock = clock

    def next(self) -> int:
        self.last = max(self.last + 1, int(self._clock() * 1000))
        return self.last


def build_request(identity, path: str, fields: dict, *, t: int, n: int) -> tuple[bytes, dict[str, str]]:
    """Corps et en-têtes d'une requête signée."""
    body = cjson({**fields, "t": t, "n": n})
    if len(body) > MAX_BODY:
        raise ValueError("requête trop grande")
    sig = identity.sign(signed_bytes(path, body))
    return body, {"Content-Type": "application/json", "X-Orx-Station": identity.station_id,
                  "X-Orx-Signature": b64e(sig)}


def verify_request(ed_pub: bytes, path: str, body: bytes, signature: str, *, now: float, last_n: int) -> dict:
    """Ce que fait le relais (en PHP) : taille, signature, horloge, rejeu. Renvoie le corps lu."""
    if len(body) > MAX_BODY:
        raise RequestRefused("too_large")
    try:
        sig = b64d(signature, crypto.SIG_SIZE)
    except Malformed as exc:
        raise RequestRefused("bad_signature") from exc
    if not crypto.ed_verify(ed_pub, sig, signed_bytes(path, body)):
        raise RequestRefused("bad_signature")
    try:
        obj = parse_json(body)
    except Malformed as exc:
        raise RequestRefused("malformed") from exc
    t, n = obj.get("t"), obj.get("n")
    for value in (t, n):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_COUNTER:
            raise RequestRefused("malformed")
    if abs(t - now) > CLOCK_TOLERANCE_S:
        raise RequestRefused("clock")
    if n <= last_n:
        raise RequestRefused("replay")
    return obj


# ------------------------------------------------------------------ filtres
def _squeeze(text: str) -> str:
    return " ".join(text.split())


def clean_pseudo(text: object) -> str | None:
    """Pseudo accepté (espaces multiples réduits) ou None : 1 à 16 caractères, lettres sans accent, chiffres,
    espace, `.`, `/`, `_`, `-` ; commence par une lettre ou un chiffre."""
    if not isinstance(text, str):
        return None
    text = _squeeze(text)
    return text if PSEUDO_RE.fullmatch(text) else None


def clean_text(text: object) -> str | None:
    """Texte libre accepté ou None : 1 à 16 caractères, lettres sans accent, chiffres, espace, `.`, `/`, `-`."""
    if not isinstance(text, str):
        return None
    text = _squeeze(text)
    return text if TEXT_RE.fullmatch(text) else None


def mode_ok(mode: object) -> bool:
    return isinstance(mode, str) and MODE_RE.fullmatch(mode) is not None


def freq_ok(freq: object) -> bool:
    return not isinstance(freq, bool) and isinstance(freq, int) and MIN_FREQ_HZ <= freq <= MAX_FREQ_HZ
