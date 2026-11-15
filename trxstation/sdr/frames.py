# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Trames écrites par sdr-core sur sa sortie standard (docs/protocole.md § 18, lot S1a du module SDR).

Chaque trame : en-tête de 12 octets « ORS1 », type (uint32 petit-boutiste), longueur (uint32), puis la charge.
- type 1, ligne de waterfall : centre (float64, Hz), largeur (float64, Hz), cases (uint16), réservé (uint16),
  puis une valeur uint8 par case, de la fréquence la plus basse à la plus haute ;
  niveau en dBFS = DB_MIN + valeur × DB_STEP (0 = -150 dBFS, 255 = -22,5 dBFS) ;
- type 2, objet JSON (UTF-8) : « started », « status », « event », « error », « stopped ».
Calculs purs : aucun accès au matériel ni au réseau.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass

MAGIC = b"ORS1"
HEADER = struct.Struct("<4sII")
LINE_HEAD = struct.Struct("<ddHH")
TYPE_LINE, TYPE_JSON = 1, 2
MAX_PAYLOAD = 1 << 16          # une ligne de 16 384 cases + son en-tête tient largement
DB_MIN, DB_STEP = -150.0, 0.5


class FrameError(ValueError):
    """Flux illisible : sdr-core et le module ne se comprennent plus (le module relance le cœur)."""


@dataclass(frozen=True)
class Line:
    center_hz: float
    span_hz: float
    values: bytes              # une valeur uint8 par case

    @property
    def bins(self) -> int:
        return len(self.values)


def level_db(value: int) -> float:
    return DB_MIN + value * DB_STEP


def parse_payload(kind: int, payload: bytes) -> Line | dict:
    if kind == TYPE_LINE:
        if len(payload) < LINE_HEAD.size:
            raise FrameError("ligne trop courte")
        center, span, bins, _ = LINE_HEAD.unpack_from(payload)
        values = payload[LINE_HEAD.size:]
        if bins != len(values) or not bins:
            raise FrameError(f"ligne de {len(values)} cases annoncée {bins}")
        return Line(center, span, bytes(values))
    if kind == TYPE_JSON:
        try:
            obj = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrameError(f"JSON illisible : {exc}") from None
        if not isinstance(obj, dict) or not isinstance(obj.get("t"), str):
            raise FrameError("objet JSON sans champ « t »")
        return obj
    raise FrameError(f"type de trame inconnu : {kind}")


class FrameReader:
    """Découpe un flux d'octets en trames (les octets arrivent par morceaux quelconques)."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[Line | dict]:
        self._buf += data
        out: list[Line | dict] = []
        while len(self._buf) >= HEADER.size:
            magic, kind, length = HEADER.unpack_from(self._buf)
            if magic != MAGIC:
                raise FrameError("en-tête de trame invalide")
            if length > MAX_PAYLOAD:
                raise FrameError(f"trame trop longue ({length} octets)")
            if len(self._buf) < HEADER.size + length:
                break
            payload = bytes(self._buf[HEADER.size:HEADER.size + length])
            del self._buf[:HEADER.size + length]
            out.append(parse_payload(kind, payload))
        return out


def encode_frame(kind: int, payload: bytes) -> bytes:
    """Trame comme l'écrit sdr-core (faux cœur des essais, vecteurs de test)."""
    return HEADER.pack(MAGIC, kind, len(payload)) + payload


def encode_line(center_hz: float, span_hz: float, values: bytes) -> bytes:
    return encode_frame(TYPE_LINE, LINE_HEAD.pack(center_hz, span_hz, len(values), 0) + bytes(values))


def encode_json(obj: dict) -> bytes:
    return encode_frame(TYPE_JSON, json.dumps(obj, separators=(",", ":")).encode("utf-8"))
