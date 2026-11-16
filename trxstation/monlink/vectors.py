# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Vecteurs du monitoring inter-stations (tests/protocol/monlink_vectors.json).

Graines, code, nonces et heures FIXES : relus par les tests de la station et à reprendre tels quels dans le dépôt du
relais (PHP 8.2 + sodium) : mêmes identifiants, mêmes octets signés, mêmes refus avec le même motif. La partie
« station » (invitation, appairage, empreinte, clé de liaison, message) sert à toute autre mise en œuvre future.
Refabriquer : python -m trxstation.monlink.vectors
"""
from __future__ import annotations

import json
from pathlib import Path

from ..presence.codec import b64e
from ..presence.wire import signed_bytes
from . import envelope, invite, pairing, wire
from .identity import Identity

OUTPUT = Path(__file__).resolve().parents[2] / "tests" / "protocol" / "monlink_vectors.json"
NOW = 1_794_800_000                    # 2026-11-20 (environ), heure de référence des vecteurs
CODE_RAND = bytes.fromhex("5a3c9e01f27b44")
HELPER_PSEUDO = "Dev 56"
AIDED_PSEUDO = "F4XYZ shack"


def identities() -> dict[str, Identity]:
    """`helper` : la station qui aide (receveur) ; `aided` : la station surveillée (émetteur) ; `other` : un tiers."""
    return {name: Identity(bytes([seed]) * 32, bytes([seed + 1]) * 32)
            for name, seed in (("helper", 0x31), ("aided", 0x41), ("other", 0x51))}


def build() -> dict:
    ids = identities()
    helper, aided, other = ids["helper"], ids["aided"], ids["other"]
    out: dict = {"comment": "Monitoring inter-stations, mode R (docs/protocole-monlink.md). Fabriqué par "
                            "python -m trxstation.monlink.vectors : ne pas modifier à la main.",
                 "now": NOW}
    out["identities"] = [{"name": n, "ed_seed": b64e(i.ed_seed), "x_seed": b64e(i.x_seed), "ed_pub": b64e(i.ed_pub),
                          "x_pub": b64e(i.x_pub), "station_id": i.station_id} for n, i in ids.items()]

    # -------------------------------------------------------------- code et invitation
    code = invite.new_code(CODE_RAND)
    keys = invite.derive(code)
    inv = invite.seal_invitation(helper, HELPER_PSEUDO, keys, now=NOW, nonce=bytes(range(0x10, 0x28)))
    out["invite"] = {"rand_hex": CODE_RAND.hex(), "code": code, "display": invite.display_code(code),
                     "typed_variants": [invite.display_code(code).lower(), " " + code[:3] + " " + code[3:] + " "],
                     "address": keys.address, "key_hex": keys.key.hex(), "deposit": inv}

    # -------------------------------------------------------------- appairage
    inviter = invite.open_invitation(keys, inv["box"], now=NOW + 30)
    req = pairing.pair_request(inviter, keys, aided, AIDED_PSEUDO, now=NOW + 60, eph_seed=bytes([0x77]) * 32,
                               nonce=bytes(range(0x30, 0x48)))
    out["pair"] = {"request": req, "fingerprint": pairing.fingerprint(helper.ed_pub, aided.ed_pub)}

    # -------------------------------------------------------------- liaison et message
    key = pairing.link_key(aided, helper.station_id, helper.x_pub)
    msg = envelope.seal_message(key, aided.station_id, helper.station_id, "hb", 1,
                                {"v": "0.158.0", "up": 3600, "safe": False},
                                nonce=bytes(range(0x50, 0x68)))
    out["link"] = {"key_hex": key.hex(), "message": msg,
                   "content": {"v": "0.158.0", "up": 3600, "safe": False},
                   "from_emitter": sorted(envelope.FROM_EMITTER), "from_receiver": sorted(envelope.FROM_RECEIVER)}

    # -------------------------------------------------------------- requêtes signées (ce que vérifie le relais)
    # Dans l'ordre où le relais peut les rejouer après l'appairage : autorisation, dépôt, relève.
    reqs = []
    for name, ident, route, fields, n in (
            ("allow", helper, "allow", {"peer": aided.station_id}, NOW * 1000 + 1),
            ("put", aided, "put", {"msg": msg}, NOW * 1000 + 2),
            ("get", helper, "get", {"after": 0}, NOW * 1000 + 3)):
        path, body, headers = wire.build_request(ident, route, fields, t=NOW, n=n)
        reqs.append({"name": name, "station": ident.station_id, "path": path, "body": body.decode("ascii"),
                     "signed_hex": signed_bytes(path, body).hex(), "headers": headers})
    out["requests"] = reqs
    base = next(r for r in reqs if r["name"] == "put")
    out["refusals"] = [
        {"case": "signature d'une autre station", "ed_pub": b64e(other.ed_pub), "path": base["path"],
         "body": base["body"], "signature": base["headers"]["X-Orx-Signature"], "last_n": 0, "reason": "bad_signature"},
        {"case": "corps modifié", "ed_pub": b64e(aided.ed_pub), "path": base["path"],
         "body": base["body"].replace('"t":', '"t" :'), "signature": base["headers"]["X-Orx-Signature"],
         "last_n": 0, "reason": "bad_signature"},
        {"case": "compteur déjà vu", "ed_pub": b64e(aided.ed_pub), "path": base["path"], "body": base["body"],
         "signature": base["headers"]["X-Orx-Signature"], "last_n": NOW * 1000 + 2, "reason": "replay"},
        {"case": "route inconnue", "ed_pub": b64e(aided.ed_pub), "path": "/v1/mon/shell", "body": base["body"],
         "signature": base["headers"]["X-Orx-Signature"], "last_n": 0, "reason": "unknown_route"},
    ]
    return out


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


def main() -> None:
    OUTPUT.write_bytes(render().encode("utf-8"))
    print(f"Écrit : {OUTPUT}")


if __name__ == "__main__":
    main()
