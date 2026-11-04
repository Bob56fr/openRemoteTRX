# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Protocole UDP station <-> Breizh Audio Box, version 1 (FIGÉ : docs/breizh-cahier-des-charges.md § 5).

Paquet = en-tête de 28 octets (gros-boutiste) + charge utile + étiquette de 16 octets :
    magic "ORTB" | version u8 | type u8 | flags u16 | session u64 | seq u32 | ref u32 | len u16 | reserved u16
étiquette = HMAC-SHA256(clé, tout ce qui précède)[:16] ; clé d'APPAIRAGE pour HELLO, HELLO_ACK et ERROR,
clé de SESSION pour les autres. Son : s16 petit-boutiste, mono, 48 kHz, blocs de 480 échantillons.
Tout paquet invalide lève PacketError (code court dans `reason`) : l'appelant le jette SANS répondre.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import struct
from dataclasses import dataclass
from enum import IntEnum

MAGIC = b"ORTB"
VERSION = 1                     # version de l'en-tête
PROTO = 1                       # version du protocole annoncée dans HELLO / HELLO_ACK
HEADER = struct.Struct(">4sBBHQIIHH")
HEADER_SIZE = HEADER.size       # 28
TAG_SIZE = 16
RATE = 48000
BLOCK_SAMPLES = 480             # 10 ms
BLOCK_BYTES = BLOCK_SAMPLES * 2
FORMAT = "s16le"
KEY_SIZE = 32
NONCE_SIZE = 16
MAX_JSON = 512
MAX_LATENCY_MS = 50             # traitement annoncé par Breizh au-delà duquel la liaison est refusée
SESSION_LABEL = b"ORTB1 session"
U32 = 0xFFFFFFFF

FLAG_START = 0x0001             # premier bloc d'une émission : remettre à zéro l'état du traitement
FLAG_GAP = 0x0002               # des blocs ont manqué avant celui-ci
KNOWN_FLAGS = FLAG_START | FLAG_GAP


class Type(IntEnum):
    HELLO = 1
    HELLO_ACK = 2
    AUDIO = 3
    AUDIO_RET = 4
    PING = 5
    PONG = 6
    BYE = 7
    ERROR = 8


PAIRING_TYPES = frozenset({Type.HELLO, Type.HELLO_ACK, Type.ERROR})     # signés par la clé d'appairage
JSON_TYPES = frozenset({Type.HELLO, Type.HELLO_ACK, Type.BYE, Type.ERROR})
AUDIO_TYPES = frozenset({Type.AUDIO, Type.AUDIO_RET})
ERROR_CODES = ("proto", "format", "mode_off", "busy")
BYE_REASONS = ("mode_off", "shutdown", "disabled")


class PacketError(ValueError):
    """Paquet refusé. `reason` : short, magic, version, type, flags, reserved, length, no_session, tag, json, proto,
    format, nonce, cat_on, latency, code."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason, self.detail = reason, detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class Packet:
    type: Type
    session: int
    seq: int
    ref: int = 0
    payload: bytes = b""
    flags: int = 0


def tag(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()[:TAG_SIZE]


def _check_payload(kind: Type, size: int) -> None:
    if kind in AUDIO_TYPES and size != BLOCK_BYTES:
        raise PacketError("length", f"{kind.name} : {BLOCK_BYTES} octets attendus, {size} reçus")
    if kind in (Type.PING, Type.PONG) and size != 0:
        raise PacketError("length", f"{kind.name} sans charge utile")
    if kind in JSON_TYPES and not 1 <= size <= MAX_JSON:
        raise PacketError("length", f"{kind.name} : 1 à {MAX_JSON} octets")


def encode(packet: Packet, key: bytes) -> bytes:
    kind = Type(packet.type)
    _check_payload(kind, len(packet.payload))
    if packet.flags & ~KNOWN_FLAGS or not 0 <= packet.session < 2 ** 64:
        raise ValueError("flags ou session invalides")
    if not (0 <= packet.seq <= U32 and 0 <= packet.ref <= U32):
        raise ValueError("seq ou ref hors 32 bits")
    head = HEADER.pack(MAGIC, VERSION, kind, packet.flags, packet.session, packet.seq, packet.ref,
                       len(packet.payload), 0)
    body = head + packet.payload
    return body + tag(key, body)


def peek_type(data: bytes) -> Type:
    """Type d'un paquet, SANS le vérifier (pour savoir quelle clé tenter)."""
    if len(data) < HEADER_SIZE + TAG_SIZE:
        raise PacketError("short")
    try:
        return Type(data[5])
    except ValueError:
        raise PacketError("type", str(data[5])) from None


def decode(data: bytes, pair_key: bytes, session_key: bytes | None = None) -> Packet:
    """Vérifie TOUT (structure puis étiquette) et retourne le paquet ; PacketError sinon."""
    if len(data) < HEADER_SIZE + TAG_SIZE:
        raise PacketError("short")
    magic, version, kind, flags, session, seq, ref, size, reserved = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise PacketError("magic")
    if version != VERSION:
        raise PacketError("version", str(version))
    try:
        kind = Type(kind)
    except ValueError:
        raise PacketError("type", str(kind)) from None
    if flags & ~KNOWN_FLAGS:
        raise PacketError("flags", hex(flags))
    if reserved != 0:
        raise PacketError("reserved")
    if len(data) != HEADER_SIZE + size + TAG_SIZE:
        raise PacketError("length", "taille annoncée différente de la taille reçue")
    _check_payload(kind, size)
    key = pair_key if kind in PAIRING_TYPES else session_key
    if key is None:
        raise PacketError("no_session")
    body = data[:HEADER_SIZE + size]
    if not hmac.compare_digest(tag(key, body), data[HEADER_SIZE + size:]):
        raise PacketError("tag")
    return Packet(kind, session, seq, ref, bytes(data[HEADER_SIZE:HEADER_SIZE + size]), flags)


# ---------------------------------------------------------------- clés et session

def new_key() -> bytes:
    return secrets.token_bytes(KEY_SIZE)


def new_nonce() -> bytes:
    return secrets.token_bytes(NONCE_SIZE)


def new_session() -> int:
    return secrets.randbits(64) or 1


def key_to_text(key: bytes) -> str:
    """Clé montrée à l'utilisateur et rangée dans breizh.key : base64url sans « = » (43 caractères)."""
    if len(key) != KEY_SIZE:
        raise ValueError(f"clé de {KEY_SIZE} octets attendue")
    return base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii")


def key_from_text(text: str) -> bytes:
    text = text.strip()
    if len(text) != 43 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in text):
        raise ValueError("clé d'appairage : 43 caractères (lettres, chiffres, - et _) attendus")
    return base64.urlsafe_b64decode(text + "=")


def session_key(pair_key: bytes, session: int, nonce_station: bytes, nonce_breizh: bytes) -> bytes:
    """Clé de session : HMAC-SHA256(clé d'appairage, "ORTB1 session" | session (8 octets) | nonce_s | nonce_b)."""
    return hmac.new(pair_key, SESSION_LABEL + session.to_bytes(8, "big") + nonce_station + nonce_breizh,
                    hashlib.sha256).digest()


class SeqGuard:
    """Anti-rejeu d'un sens : n'accepte que des `seq` strictement croissants (un paquet désordonné est perdu)."""

    def __init__(self) -> None:
        self.last = -1

    def accept(self, seq: int) -> bool:
        if seq <= self.last:
            return False
        self.last = seq
        return True


# ---------------------------------------------------------------- charges utiles JSON

def _dump(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _load(payload: bytes) -> dict:
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise PacketError("json") from None
    if not isinstance(obj, dict):
        raise PacketError("json", "objet attendu")
    return obj


def _nonce(obj: dict) -> bytes:
    value = obj.get("nonce")
    try:
        raw = base64.b64decode(value, validate=True) if isinstance(value, str) else b""
    except (binascii.Error, ValueError):
        raw = b""
    if len(raw) != NONCE_SIZE:
        raise PacketError("nonce")
    return raw


def _text(obj: dict, name: str, limit: int = 64) -> str:
    value = obj.get(name, "")
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise PacketError("json", name)
    return value


@dataclass(frozen=True)
class Hello:
    nonce: bytes
    station: str


@dataclass(frozen=True)
class HelloAck:
    nonce: bytes
    breizh: str
    latency_ms: int


def hello_payload(nonce: bytes, station_version: str) -> bytes:
    return _dump({"proto": PROTO, "rate": RATE, "block": BLOCK_SAMPLES, "format": FORMAT,
                  "station": station_version, "nonce": base64.b64encode(nonce).decode("ascii")})


def parse_hello(payload: bytes) -> Hello:
    obj = _load(payload)
    if obj.get("proto") != PROTO:
        raise PacketError("proto", str(obj.get("proto")))
    if (obj.get("rate"), obj.get("block"), obj.get("format")) != (RATE, BLOCK_SAMPLES, FORMAT):
        raise PacketError("format")
    return Hello(_nonce(obj), _text(obj, "station"))


def hello_ack_payload(nonce: bytes, breizh_version: str, *, cat_off: bool = True, latency_ms: int = 5,
                      proto: int = PROTO) -> bytes:
    return _dump({"proto": proto, "nonce": base64.b64encode(nonce).decode("ascii"), "breizh": breizh_version,
                  "cat_off": cat_off, "latency_ms": latency_ms})


def parse_hello_ack(payload: bytes) -> HelloAck:
    """Refuse (PacketError) un Breizh d'une autre version, qui n'a pas coupé son CAT, ou trop lent."""
    obj = _load(payload)
    if obj.get("proto") != PROTO:
        raise PacketError("proto", str(obj.get("proto")))
    nonce = _nonce(obj)
    if obj.get("cat_off") is not True:
        raise PacketError("cat_on")
    latency = obj.get("latency_ms")
    if isinstance(latency, bool) or not isinstance(latency, int) or not 0 <= latency <= MAX_LATENCY_MS:
        raise PacketError("latency", str(latency))
    return HelloAck(nonce, _text(obj, "breizh"), latency)


def error_payload(code: str) -> bytes:
    return _dump({"code": code})


def parse_error(payload: bytes) -> str:
    code = _load(payload).get("code")
    if code not in ERROR_CODES:
        raise PacketError("code", str(code))
    return code


def bye_payload(reason: str) -> bytes:
    return _dump({"reason": reason})


def parse_bye(payload: bytes) -> str:
    reason = _load(payload).get("reason")
    return reason if reason in BYE_REASONS else "unknown"
