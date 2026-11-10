# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Vecteurs de la présence de groupe (tests/protocol/presence_vectors.json).

Graines, nonces et heures FIXES : relus par les tests de la station et à reprendre tels quels dans le dépôt du relais
(PHP 8.2 + sodium) : mêmes identifiants, mêmes octets signés, mêmes refus avec le même motif.
Refabriquer : python -m trxstation.presence.vectors
"""
from __future__ import annotations

import json
from pathlib import Path

from . import crypto, invite, pow as pw, roster as ro, state as st, status as stt, wire
from .codec import b64e
from .identity import Identity

OUTPUT = Path(__file__).resolve().parents[2] / "tests" / "protocol" / "presence_vectors.json"
NOW = 1_794_000_000                    # 2026-11-11 (environ), heure de référence des vecteurs
RELAY = "https://api.rf-diy.com"
GROUP = "00112233445566778899aabbccddeeff"
GROUP_KEY = bytes(range(0x20, 0x40))
TOKEN = bytes(range(0x60, 0x70))
POW_BITS = 12


def identities() -> dict[str, Identity]:
    return {name: Identity(bytes([seed]) * 32, bytes([seed + 1]) * 32)
            for name, seed in (("admin", 0x01), ("member", 0x11), ("other", 0x21))}


def first_roster(ids: dict[str, Identity]) -> ro.Roster:
    a, m = ids["admin"], ids["member"]
    return ro.Roster(GROUP, 1, "", NOW - 3600, 1,
                     (ro.new_member(a.ed_pub, a.x_pub, "a", NOW - 3600), ro.new_member(m.ed_pub, m.x_pub, "m", NOW - 60)))


def _pow_fail(sid: str, bits: int) -> int:
    nonce = 0
    while pw.pow_ok(sid, nonce, bits):
        nonce += 1
    return nonce


def build() -> dict:
    ids = identities()
    admin, member = ids["admin"], ids["member"]
    out: dict = {"comment": "Présence de groupe v1 (docs/protocole-presence.md). Fabriqué par "
                            "python -m trxstation.presence.vectors : ne pas modifier à la main.",
                 "now": NOW}

    out["identities"] = [{"name": n, "ed_seed": b64e(i.ed_seed), "x_seed": b64e(i.x_seed), "ed_pub": b64e(i.ed_pub),
                          "x_pub": b64e(i.x_pub), "station_id": i.station_id} for n, i in ids.items()]

    out["xchacha"] = {
        "hchacha20": {"key_hex": bytes(range(32)).hex(), "nonce_hex": "000000090000004a0000000031415927",
                      "out_hex": crypto.hchacha20(bytes(range(32)), bytes.fromhex("000000090000004a0000000031415927")).hex()},
        "aead": {"key_hex": bytes(range(0x80, 0xA0)).hex(), "nonce_hex": bytes(range(0x40, 0x58)).hex(),
                 "aad_hex": "50515253c0c1c2c3c4c5c6c7", "plaintext": SUNSCREEN,
                 "ciphertext_hex": crypto.xchacha_encrypt(bytes(range(0x80, 0xA0)), bytes(range(0x40, 0x58)),
                                                          SUNSCREEN.encode(), bytes.fromhex("50515253c0c1c2c3c4c5c6c7")).hex()},
    }

    sid = admin.station_id
    ok = pw.pow_solve(sid, POW_BITS)
    bad = _pow_fail(sid, POW_BITS)
    out["pow"] = {"station_id": sid, "bits": POW_BITS,
                  "valid": {"nonce": ok, "sha256_hex": pw.pow_hash(sid, ok).hex()},
                  "invalid": {"nonce": bad, "sha256_hex": pw.pow_hash(sid, bad).hex()}}

    path = "/v1/sync"
    body, headers = wire.build_request(admin, path, {"states": []}, t=NOW, n=NOW * 1000)
    altered = body.replace(b"[]", b"[ ]")
    out["requests"] = {
        "path": path, "body": body.decode("ascii"), "headers": headers,
        "signed_hex": wire.signed_bytes(path, body).hex(), "ed_pub": b64e(admin.ed_pub),
        "valid": [{"now": NOW, "last_n": 0}, {"now": NOW + 599, "last_n": NOW * 1000 - 1}],
        "refused": [
            {"name": "corps changé", "body": altered.decode("ascii"), "now": NOW, "last_n": 0, "reason": "bad_signature"},
            {"name": "horloge en avance", "body": body.decode("ascii"), "now": NOW - 601, "last_n": 0, "reason": "clock"},
            {"name": "rejeu", "body": body.decode("ascii"), "now": NOW, "last_n": NOW * 1000, "reason": "replay"},
        ],
    }

    out["pseudo"] = [{"in": i, "out": wire.clean_pseudo(i)} for i in PSEUDO_CASES]
    out["text"] = [{"in": i, "out": wire.clean_text(i)} for i in TEXT_CASES]
    out["format_age"] = [{"s": s, "out": stt.format_age(s)} for s in (0, 59, 60, 3599, 3600, 86399, 86400, 400000)]
    out["display"] = [{"st": s, "age": a, "out": stt.display_code(s, a)}
                      for s, a in (("R", 10), ("R", 240), ("R", 241), ("H", 5), (None, None), ("Q", 0), ("?", 1))]

    roster = first_roster(ids)
    env = ro.sign(roster, admin)
    out["roster"] = {"envelope": env, "payload": roster.payload().decode("ascii"), "digest": roster.digest()}

    status = stt.Status("R", NOW - 120, NOW - 900, None)
    content = st.content(status, st.Share("f"), n=NOW * 1000, t=NOW, freq=14_205_000, mode="USB")
    nonce = bytes(range(0xC0, 0xD8))
    blob = st.seal_state(member, GROUP, GROUP_KEY, 1, content, nonce=nonce)
    out["state"] = {"group": GROUP, "key": b64e(GROUP_KEY), "kv": 1, "station_id": member.station_id,
                    "nonce_hex": nonce.hex(), "content": content, "blob": blob, "size": st.BLOB_SIZE}

    box = invite.key_box(admin, roster, member.station_id, GROUP_KEY, eph_seed=bytes([0x77]) * 32,
                         nonce=bytes(range(0xE0, 0xF8)))
    out["key_box"] = box

    inv = invite.new_invitation(RELAY, GROUP, GROUP_KEY, 1, admin.station_id, now=NOW, token=TOKEN)
    out["invitation"] = {"url": inv.to_url(), "expires": inv.expires}
    out["join"] = invite.join_request(inv, ids["other"], "F4XYZ/P")
    return out


SUNSCREEN = ("Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, "
             "sunscreen would be it.")
PSEUDO_CASES = ("F4ABC", "  F4ABC   Bob ", "F4ABC/P", "-F4", "Élodie", "A" * 16, "A" * 17, "", "x y_z.1", "F4 ")
TEXT_CASES = ("Mobile", "Test  antenne", "QRV 7.074", "Test antenne 2026", "café", "a/b-c", "<b>", "")


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"écrit : {OUTPUT}")
