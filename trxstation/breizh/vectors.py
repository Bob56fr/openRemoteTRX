# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Vecteurs de test du protocole Breizh (tests/protocol/breizh_vectors.json).

Clé, nonces et paquets complets FIXES : relus par les tests de la station et à reprendre tels quels dans le dépôt de
Breizh Audio Box (ses paquets doivent être identiques octet pour octet, ses refus avoir le même motif).
Refabriquer : python -m trxstation.breizh.vectors
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from . import protocol as p

PAIR_KEY = bytes(range(32))
SESSION = 0x0123456789ABCDEF
NONCE_STATION = bytes(range(0xA0, 0xB0))
NONCE_BREIZH = bytes(range(0xB0, 0xC0))
AUDIO = struct.pack("<480h", *(i * 64 - 15360 for i in range(p.BLOCK_SAMPLES)))     # rampe
PROCESSED = struct.pack("<480h", *(i * 32 - 7680 for i in range(p.BLOCK_SAMPLES)))  # la même à −6 dB
OUTPUT = Path(__file__).resolve().parents[2] / "tests" / "protocol" / "breizh_vectors.json"


def _raw(kind: int, payload: bytes, key: bytes, *, flags: int = 0, seq: int = 1, ref: int = 0, version: int = 1,
         magic: bytes = p.MAGIC, reserved: int = 0, size: int | None = None) -> bytes:
    """Paquet fabriqué SANS contrôle (pour les vecteurs refusés), étiquette juste avec `key`."""
    head = p.HEADER.pack(magic, version, kind, flags, SESSION, seq, ref, len(payload) if size is None else size, reserved)
    return head + payload + p.tag(key, head + payload)


def build() -> dict:
    skey = p.session_key(PAIR_KEY, SESSION, NONCE_STATION, NONCE_BREIZH)
    valid = [
        ("hello", p.Type.HELLO, "pair", 1, 0, 0, p.hello_payload(NONCE_STATION, "0.99.0")),
        ("hello_ack", p.Type.HELLO_ACK, "pair", 1, 0, 0, p.hello_ack_payload(NONCE_BREIZH, "Breizh 2.0.0", latency_ms=5)),
        ("audio_start", p.Type.AUDIO, "session", 2, 0, p.FLAG_START, AUDIO),
        ("audio_ret", p.Type.AUDIO_RET, "session", 2, 0, 0, PROCESSED),
        ("audio_gap", p.Type.AUDIO, "session", 3, 5, p.FLAG_GAP, AUDIO),
        ("ping", p.Type.PING, "session", 4, 0, 0, b""),
        ("pong", p.Type.PONG, "session", 3, 4, 0, b""),
        ("bye", p.Type.BYE, "session", 5, 0, 0, p.bye_payload("shutdown")),
        ("error", p.Type.ERROR, "pair", 1, 0, 0, p.error_payload("mode_off")),
    ]
    out_valid = []
    for name, kind, which, seq, ref, flags, payload in valid:
        key = PAIR_KEY if which == "pair" else skey
        packet = p.encode(p.Packet(kind, SESSION, seq, ref, payload, flags), key)
        out_valid.append({"name": name, "type": int(kind), "key": which, "seq": seq, "ref": ref, "flags": flags,
                          "payload_hex": payload.hex(), "packet_hex": packet.hex()})
    ping = p.encode(p.Packet(p.Type.PING, SESSION, 9), skey)
    invalid = [
        ("tag_altered", ping[:-1] + bytes([ping[-1] ^ 1]), "tag", True),
        ("payload_altered", (lambda a: a[:40] + bytes([a[40] ^ 0x80]) + a[41:])(
            p.encode(p.Packet(p.Type.AUDIO_RET, SESSION, 7, 3, PROCESSED), skey)), "tag", True),
        ("hello_signed_with_session_key", _raw(p.Type.HELLO, p.hello_payload(NONCE_STATION, "0.99.0"), skey), "tag", True),
        ("audio_signed_with_pair_key", _raw(p.Type.AUDIO, AUDIO, PAIR_KEY), "tag", True),
        ("audio_without_session", p.encode(p.Packet(p.Type.AUDIO, SESSION, 2, 0, AUDIO), skey), "no_session", False),
        ("short", ping[:p.HEADER_SIZE + p.TAG_SIZE - 1], "short", True),
        ("magic", _raw(p.Type.PING, b"", skey, magic=b"ORTX"), "magic", True),
        ("version_2", _raw(p.Type.PING, b"", skey, version=2), "version", True),
        ("type_9", _raw(9, b"", skey), "type", True),
        ("flags_unknown", _raw(p.Type.AUDIO, AUDIO, skey, flags=0x0004), "flags", True),
        ("reserved_not_zero", _raw(p.Type.PING, b"", skey, reserved=1), "reserved", True),
        ("length_mismatch", ping + b"\x00", "length", True),
        ("audio_958_bytes", _raw(p.Type.AUDIO, AUDIO[:-2], skey), "length", True),
        ("ping_with_payload", _raw(p.Type.PING, b"x", skey), "length", True),
    ]
    return {
        "comment": "Protocole Breizh v1 (docs/breizh-cahier-des-charges.md § 5). Fabriqué par "
                   "python -m trxstation.breizh.vectors : ne pas modifier à la main.",
        "pair_key_hex": PAIR_KEY.hex(), "pair_key_text": p.key_to_text(PAIR_KEY),
        "session_hex": f"{SESSION:016x}",      # 64 bits : en hexadécimal (un nombre JSON perdrait des chiffres en JavaScript)
        "nonce_station_hex": NONCE_STATION.hex(), "nonce_breizh_hex": NONCE_BREIZH.hex(), "session_key_hex": skey.hex(),
        "valid": out_valid,
        "invalid": [{"name": n, "packet_hex": d.hex(), "reason": r, "with_session_key": w} for n, d, r, w in invalid],
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"écrit : {OUTPUT}")
