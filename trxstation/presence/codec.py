# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Encodages communs de la présence de groupe (station et relais)."""
from __future__ import annotations

import base64
import json
import re
import struct
from typing import Any

_B64_RE = re.compile(r"[A-Za-z0-9_-]*")
STATION_ID_RE = re.compile(r"[0-9a-f]{32}")
GROUP_ID_RE = re.compile(r"[0-9a-f]{32}")


class Malformed(ValueError):
    """Donnée reçue illisible ou hors format."""


def b64e(data: bytes) -> str:
    """base64url sans remplissage (`=`)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(text: Any, size: int | None = None) -> bytes:
    """Décode du base64url sans remplissage ; `size` : longueur exigée en octets."""
    if not isinstance(text, str) or not _B64_RE.fullmatch(text) or len(text) % 4 == 1:
        raise Malformed("base64url invalide")
    data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if b64e(data) != text:                    # refuse les écritures non canoniques (bits de fin non nuls)
        raise Malformed("base64url non canonique")
    if size is not None and len(data) != size:
        raise Malformed(f"longueur {len(data)} au lieu de {size}")
    return data


def cjson(obj: Any) -> bytes:
    """JSON compact, clés triées, ASCII seul : les octets SIGNÉS sont transmis tels quels (jamais refabriqués)."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def parse_json(data: bytes) -> dict:
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Malformed("JSON illisible") from exc
    if not isinstance(obj, dict):
        raise Malformed("objet JSON attendu")
    return obj


def u32(value: int) -> bytes:
    return struct.pack(">I", value)


def want_int(obj: dict, key: str, lo: int, hi: int, *, optional: bool = False) -> int | None:
    value = obj.get(key)
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise Malformed(f"champ {key!r} invalide")
    return value


def want_str(obj: dict, key: str, pattern: re.Pattern[str], *, optional: bool = False) -> str | None:
    value = obj.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise Malformed(f"champ {key!r} invalide")
    return value


def station_id_ok(text: Any) -> bool:
    return isinstance(text, str) and STATION_ID_RE.fullmatch(text) is not None


def group_id_ok(text: Any) -> bool:
    return isinstance(text, str) and GROUP_ID_RE.fullmatch(text) is not None
