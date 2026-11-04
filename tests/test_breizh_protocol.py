# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Protocole Breizh v1 (docs/breizh-cahier-des-charges.md § 5) : paquets, HMAC, session, rejeu, vecteurs partagés."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from trxstation.breizh import protocol as p
from trxstation.breizh import vectors

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "protocol" / "breizh_vectors.json"
KEY = bytes(range(32))
SKEY = bytes(range(100, 132))
BLOCK = bytes(range(256)) * 3 + bytes(192)


def test_header_is_28_bytes_and_block_is_10_ms():
    assert p.HEADER_SIZE == 28
    assert p.BLOCK_SAMPLES * 1000 // p.RATE == 10
    assert p.HEADER_SIZE + p.BLOCK_BYTES + p.TAG_SIZE + 28 < 1500      # un paquet, sans fragmentation (IP + UDP)


@pytest.mark.parametrize("kind,payload,key", [
    (p.Type.HELLO, p.hello_payload(b"n" * 16, "0.99.0"), KEY),
    (p.Type.HELLO_ACK, p.hello_ack_payload(b"m" * 16, "Breizh"), KEY),
    (p.Type.ERROR, p.error_payload("busy"), KEY),
    (p.Type.AUDIO, BLOCK, SKEY), (p.Type.AUDIO_RET, BLOCK, SKEY),
    (p.Type.PING, b"", SKEY), (p.Type.PONG, b"", SKEY), (p.Type.BYE, p.bye_payload("mode_off"), SKEY),
])
def test_round_trip_of_every_type(kind, payload, key):
    packet = p.Packet(kind, 2 ** 64 - 1, p.U32, 7, payload, p.FLAG_START)
    assert p.decode(p.encode(packet, key), KEY, SKEY) == packet


def test_every_altered_byte_is_refused():
    data = p.encode(p.Packet(p.Type.AUDIO_RET, 42, 3, 9, BLOCK), SKEY)
    for i in range(len(data)):
        bad = data[:i] + bytes([data[i] ^ 0x01]) + data[i + 1:]
        with pytest.raises(p.PacketError):
            p.decode(bad, KEY, SKEY)


def test_pairing_types_use_the_pairing_key_and_the_others_the_session_key():
    hello = p.encode(p.Packet(p.Type.HELLO, 1, 1, 0, p.hello_payload(b"n" * 16, "x")), KEY)
    assert p.decode(hello, KEY).type == p.Type.HELLO                       # pas besoin de session
    with pytest.raises(p.PacketError) as err:
        p.decode(p.encode(p.Packet(p.Type.HELLO, 1, 1, 0, p.hello_payload(b"n" * 16, "x")), SKEY), KEY, SKEY)
    assert err.value.reason == "tag"
    audio = p.encode(p.Packet(p.Type.AUDIO, 1, 2, 0, BLOCK), SKEY)
    with pytest.raises(p.PacketError) as err:
        p.decode(audio, KEY)
    assert err.value.reason == "no_session"
    with pytest.raises(p.PacketError) as err:
        p.decode(audio, KEY, bytes(32))                                     # session précédente
    assert err.value.reason == "tag"


def test_encode_refuses_what_decode_would_refuse():
    with pytest.raises(p.PacketError):
        p.encode(p.Packet(p.Type.AUDIO, 1, 1, 0, BLOCK[:-2]), SKEY)
    with pytest.raises(p.PacketError):
        p.encode(p.Packet(p.Type.PING, 1, 1, 0, b"x"), SKEY)
    with pytest.raises(ValueError):
        p.encode(p.Packet(p.Type.PING, 1, 1, 0, b"", 0x8), SKEY)
    with pytest.raises(ValueError):
        p.encode(p.Packet(p.Type.PING, 1, p.U32 + 1), SKEY)


def test_session_key_depends_on_every_input():
    base = p.session_key(KEY, 5, b"a" * 16, b"b" * 16)
    assert len(base) == 32
    assert base != p.session_key(KEY, 6, b"a" * 16, b"b" * 16)
    assert base != p.session_key(KEY, 5, b"c" * 16, b"b" * 16)
    assert base != p.session_key(KEY, 5, b"a" * 16, b"c" * 16)
    assert base != p.session_key(SKEY, 5, b"a" * 16, b"b" * 16)


def test_seq_guard_refuses_replays_and_disorder():
    guard = p.SeqGuard()
    assert guard.accept(1) and guard.accept(2) and guard.accept(10)
    assert not guard.accept(10) and not guard.accept(3) and not guard.accept(0)
    assert guard.accept(11)


def test_hello_ack_refusals():
    nonce = b"z" * 16
    assert p.parse_hello_ack(p.hello_ack_payload(nonce, "B", latency_ms=50)).latency_ms == 50
    cases = {"cat_on": p.hello_ack_payload(nonce, "B", cat_off=False),
             "proto": p.hello_ack_payload(nonce, "B", proto=2),
             "latency": p.hello_ack_payload(nonce, "B", latency_ms=51),
             "nonce": p.hello_ack_payload(b"short", "B"),
             "json": b"[1,2]"}
    for reason, payload in cases.items():
        with pytest.raises(p.PacketError) as err:
            p.parse_hello_ack(payload)
        assert err.value.reason == reason
    with pytest.raises(p.PacketError) as err:
        p.parse_hello_ack(b'{"proto":1,"nonce":"' + b"A" * 22 + b'==","cat_off":"true","latency_ms":5}')
    assert err.value.reason == "cat_on"                                    # « true » en texte n'est pas true


def test_hello_refusals_and_error_codes():
    good = json.loads(p.hello_payload(b"n" * 16, "0.99.0"))
    assert p.parse_hello(p.hello_payload(b"n" * 16, "0.99.0")).station == "0.99.0"
    for change, reason in (({"proto": 2}, "proto"), ({"block": 256}, "format"), ({"rate": 44100}, "format"),
                           ({"format": "f32le"}, "format"), ({"station": "a\nb"}, "json")):
        with pytest.raises(p.PacketError) as err:
            p.parse_hello(json.dumps({**good, **change}).encode())
        assert err.value.reason == reason
    assert [p.parse_error(p.error_payload(c)) for c in p.ERROR_CODES] == list(p.ERROR_CODES)
    with pytest.raises(p.PacketError):
        p.parse_error(p.error_payload("autre"))
    assert p.parse_bye(p.bye_payload("x")) == "unknown"


def test_pairing_key_text():
    key = p.new_key()
    text = p.key_to_text(key)
    assert len(text) == 43 and "=" not in text
    assert p.key_from_text(f"  {text}\n") == key
    for bad in ("", text[:-1], text + "A", text[:-1] + "+", text[:-1] + "é"):
        with pytest.raises(ValueError):
            p.key_from_text(bad)


def test_shared_vectors_are_up_to_date():
    """Le fichier relu par Breizh est exactement celui que fabrique le code (sinon : python -m trxstation.breizh.vectors)."""
    assert VECTORS.read_text(encoding="utf-8") == vectors.render()


def test_shared_vectors_decode_and_refuse_as_documented():
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    key = bytes.fromhex(data["pair_key_hex"])
    assert p.key_from_text(data["pair_key_text"]) == key
    skey = p.session_key(key, int(data["session_hex"], 16), bytes.fromhex(data["nonce_station_hex"]),
                         bytes.fromhex(data["nonce_breizh_hex"]))
    assert skey.hex() == data["session_key_hex"]
    for v in data["valid"]:
        packet = p.decode(bytes.fromhex(v["packet_hex"]), key, skey)
        assert (packet.type, packet.seq, packet.ref, packet.flags, packet.payload.hex()) == (
            v["type"], v["seq"], v["ref"], v["flags"], v["payload_hex"]), v["name"]
        assert p.encode(packet, key if v["key"] == "pair" else skey).hex() == v["packet_hex"]
    for v in data["invalid"]:
        with pytest.raises(p.PacketError) as err:
            p.decode(bytes.fromhex(v["packet_hex"]), key, skey if v["with_session_key"] else None)
        assert err.value.reason == v["reason"], v["name"]


def test_breizh_package_never_touches_the_ptt_nor_the_cat():
    """Breizh ne peut que fournir le son d'un bloc demandé : son paquet n'importe ni la sécurité d'émission ni le CAT."""
    forbidden = ("safety", "cat", "rigctl", "ptt", "gateway")
    for path in (ROOT / "trxstation" / "breizh").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            for name in names:
                assert not any(part in forbidden for part in name.split(".")), f"{path.name} importe {name}"
