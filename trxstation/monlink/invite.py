# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Code d'invitation et invitation déposée sur le relais (cahier § 17.4, étapes 1 et 2).

Le RECEVEUR (celui qui aide) crée un code de 10 caractères (alphabet base32 de Crockford, 50 bits), lisible au
téléphone, affiché `ABCDE-FGHJK`. scrypt (N = 2^15, r = 8, p = 1, sel de domaine fixe) en tire 48 octets :
- 16 pour l'ADRESSE de l'invitation sur le relais (32 caractères hexadécimaux) ;
- 32 pour la CLÉ qui chiffre son contenu (XChaCha20-Poly1305) et prouve ensuite la connaissance du code.
Le relais ne voit que l'adresse ; retrouver le code demanderait 2^50 calculs scrypt (32 Mo chacun).

L'invitation dure 15 min et sert une seule fois (le relais l'efface à la première lecture). La protection contre une
interception (relais compris) n'est PAS le code mais l'empreinte à 6 chiffres comparée de vive voix (pairing.py).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from ..presence import crypto
from ..presence.codec import Malformed, b64d, b64e, cjson, parse_json, station_id_ok
from ..presence.wire import clean_pseudo
from .identity import station_id_of

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"        # Crockford : ni I, L, O, U
CODE_LEN = 10
INVITE_TTL_S = 15 * 60
SCRYPT_SALT = b"orx-monlink invite v1"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
INVITE_DOMAIN = b"orx-monlink invite v1\0"
_CONFUSABLE = str.maketrans({"O": "0", "I": "1", "L": "1"})


class InviteRefused(ValueError):
    """Motifs : malformed (code ou invitation illisible), decrypt (code faux ou invitation altérée), expired."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ------------------------------------------------------------------ code
def new_code(rand: bytes | None = None) -> str:
    """10 caractères tirés de 50 bits aléatoires (`rand` : 7 octets fixes pour les vecteurs)."""
    value = int.from_bytes(rand if rand is not None else os.urandom(7), "big") >> 6     # 56 - 6 = 50 bits
    return "".join(ALPHABET[(value >> (5 * i)) & 31] for i in reversed(range(CODE_LEN)))


def normalize_code(text: object) -> str:
    """Code tapé -> forme canonique : casse libre, espaces et tirets ignorés, O = 0, I et L = 1."""
    if not isinstance(text, str) or len(text) > 40:
        raise InviteRefused("malformed")
    code = "".join(ch for ch in text.upper() if ch not in " -\t").translate(_CONFUSABLE)
    if len(code) != CODE_LEN or any(ch not in ALPHABET for ch in code):
        raise InviteRefused("malformed")
    return code


def display_code(code: str) -> str:
    return f"{code[:5]}-{code[5:]}"


@dataclass(frozen=True)
class CodeKeys:
    address: str              # adresse de l'invitation sur le relais (32 hex)
    key: bytes                # 32 octets, jamais envoyés

    def __repr__(self) -> str:
        return f"CodeKeys({self.address})"


def derive(code: str) -> CodeKeys:
    out = hashlib.scrypt(normalize_code(code).encode("ascii"), salt=SCRYPT_SALT, n=SCRYPT_N, r=SCRYPT_R,
                         p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=48)
    return CodeKeys(out[:16].hex(), out[16:])


# ------------------------------------------------------------------ invitation
@dataclass(frozen=True)
class Inviter:
    """Le receveur, tel que l'émetteur le lit dans l'invitation."""
    id: str
    ed: bytes
    x: bytes
    pseudo: str
    expires: int


def _aad(address: str) -> bytes:
    return INVITE_DOMAIN + address.encode("ascii")


def seal_invitation(identity, pseudo: str, keys: CodeKeys, *, now: float, ttl_s: int = INVITE_TTL_S,
                    nonce: bytes | None = None) -> dict:
    """Ce que le receveur dépose sur le relais : `{"a": adresse, "box": …, "e": expiration}`."""
    if clean_pseudo(pseudo) != pseudo:
        raise ValueError("pseudo refusé")
    if not 60 <= ttl_s <= INVITE_TTL_S:
        raise ValueError("durée de l'invitation : 1 à 15 min")
    expires = int(now) + ttl_s
    body = cjson({"v": 1, "id": identity.station_id, "ed": b64e(identity.ed_pub), "x": b64e(identity.x_pub),
                  "pseudo": pseudo, "e": expires})
    nonce = nonce or crypto.random_nonce()
    box = nonce + crypto.xchacha_encrypt(keys.key, nonce, body, _aad(keys.address))
    return {"a": keys.address, "box": b64e(box), "e": expires}


def open_invitation(keys: CodeKeys, box_text: object, *, now: float) -> Inviter:
    """Côté émetteur, avec la boîte rendue par le relais pour l'adresse tirée du code tapé."""
    try:
        box = b64d(box_text)
        if len(box) < crypto.NONCE_SIZE + crypto.TAG_SIZE or len(box) > 2048:
            raise Malformed("taille")
    except Malformed as exc:
        raise InviteRefused("malformed") from exc
    try:
        body = crypto.xchacha_decrypt(keys.key, box[:crypto.NONCE_SIZE], box[crypto.NONCE_SIZE:], _aad(keys.address))
    except crypto.DecryptError as exc:
        raise InviteRefused("decrypt") from exc
    try:
        obj = parse_json(body)
        if obj.get("v") != 1 or set(obj) != {"v", "id", "ed", "x", "pseudo", "e"}:
            raise Malformed("invitation")
        ed, x = b64d(obj["ed"], 32), b64d(obj["x"], 32)
        if not station_id_ok(obj["id"]) or obj["id"] != station_id_of(ed):
            raise Malformed("id")
        if clean_pseudo(obj["pseudo"]) != obj["pseudo"]:
            raise Malformed("pseudo")
        e = obj["e"]
        if isinstance(e, bool) or not isinstance(e, int) or not 0 < e < 2**40:
            raise Malformed("e")
    except Malformed as exc:
        raise InviteRefused("malformed") from exc
    if now >= e:
        raise InviteRefused("expired")
    return Inviter(obj["id"], ed, x, obj["pseudo"], e)
