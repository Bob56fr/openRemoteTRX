# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Invitation, demande d'adhésion et clé de groupe remise à un membre (cahier § 6.2 et § 6.4).

Invitation : `<relais>/i#<base64url(JSON)>` (le fragment après `#` n'est jamais envoyé au serveur par un navigateur),
JSON `{"v":1,"r":relais,"g":groupe,"k":clé du groupe,"kv":version de clé,"a":administrateur,"i":jeton,"e":expiration}`.
Elle contient la clé du groupe : qui la lit peut lire les états jusqu'à la prochaine rotation ; le jeton est à usage
unique et expire (7 jours par défaut).

Demande d'adhésion (déposée sur le relais, lue par un administrateur) : identifiant, clés publiques, pseudo, jeton et
`proof` = HMAC-SHA256(clé du groupe, "orx-presence join v1\\0" || groupe || jeton || identifiant || ed || x). Le relais
voit passer le jeton mais, sans la clé du groupe, il ne peut pas fabriquer de preuve pour SES propres clés.

Clé remise : `{"g","kv","for","box","by","s"}` : `box` = clé du groupe scellée pour la clé X25519 du membre (lue dans la
liste SIGNÉE, jamais fournie par le relais seul), signée par un administrateur ou co-administrateur.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from . import crypto
from .codec import (Malformed, b64d, b64e, cjson, group_id_ok, parse_json, station_id_ok, u32)
from .identity import station_id_of
from .roster import Roster
from .wire import clean_pseudo

INVITE_TTL_S = 7 * 86400
JOIN_DOMAIN = b"orx-presence join v1\0"
KEY_DOMAIN = b"orx-presence key v1\0"
TOKEN_SIZE = 16
_RELAY_RE = re.compile(r"https://[a-z0-9.-]{1,100}(?::\d{1,5})?(?:/[A-Za-z0-9._~-]+)*")


class InviteRefused(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Invitation:
    relay: str
    group: str
    key: bytes
    kv: int
    admin: str
    token: bytes
    expires: int

    def to_url(self) -> str:
        return self.relay + "/i#" + b64e(cjson({"v": 1, "r": self.relay, "g": self.group, "k": b64e(self.key),
                                                 "kv": self.kv, "a": self.admin, "i": b64e(self.token),
                                                 "e": self.expires}))


def new_invitation(relay: str, group: str, key: bytes, kv: int, admin: str, *, now: float,
                   ttl_s: int = INVITE_TTL_S, token: bytes | None = None) -> Invitation:
    if not _RELAY_RE.fullmatch(relay):
        raise ValueError("adresse du relais https:// attendue")
    return Invitation(relay, group, key, kv, admin, token or os.urandom(TOKEN_SIZE), int(now) + ttl_s)


def parse_invitation(text: str, *, now: float) -> Invitation:
    """URL complète ou seul le code après `#` (collé, ou lu dans un QR code)."""
    if not isinstance(text, str) or len(text) > 1000:
        raise InviteRefused("malformed")
    code = text.strip().rsplit("#", 1)[-1]
    try:
        obj = parse_json(b64d(code))
        if obj.get("v") != 1 or set(obj) != {"v", "r", "g", "k", "kv", "a", "i", "e"}:
            raise Malformed("invitation")
        if not isinstance(obj["r"], str) or not _RELAY_RE.fullmatch(obj["r"]):
            raise Malformed("r")
        if not group_id_ok(obj["g"]) or not station_id_ok(obj["a"]):
            raise Malformed("g/a")
        for key in ("kv", "e"):
            if isinstance(obj[key], bool) or not isinstance(obj[key], int) or not 0 < obj[key] < 2**40:
                raise Malformed(key)
        inv = Invitation(obj["r"], obj["g"], b64d(obj["k"], crypto.KEY_SIZE), obj["kv"], obj["a"],
                         b64d(obj["i"], TOKEN_SIZE), obj["e"])
    except Malformed as exc:
        raise InviteRefused("malformed") from exc
    if "#" in text and not text.strip().startswith(inv.relay + "/i#"):
        raise InviteRefused("relay_mismatch")        # URL d'un autre site que le relais annoncé dedans
    if now >= inv.expires:
        raise InviteRefused("expired")
    return inv


# ------------------------------------------------------------------ adhésion
def _proof(key: bytes, group: str, token: bytes, station: str, ed: bytes, x: bytes) -> bytes:
    return hmac.new(key, JOIN_DOMAIN + group.encode() + token + station.encode() + ed + x, hashlib.sha256).digest()


def join_request(inv: Invitation, identity, pseudo: str) -> dict:
    if clean_pseudo(pseudo) != pseudo:
        raise ValueError("pseudo refusé")
    return {"g": inv.group, "i": b64e(inv.token), "id": identity.station_id, "ed": b64e(identity.ed_pub),
            "x": b64e(identity.x_pub), "pseudo": pseudo,
            "proof": b64e(_proof(inv.key, inv.group, inv.token, identity.station_id, identity.ed_pub, identity.x_pub))}


@dataclass(frozen=True)
class Joiner:
    id: str
    ed: bytes
    x: bytes
    pseudo: str
    token: bytes


def check_join(req: object, *, group: str, key: bytes, tokens: dict[bytes, int], used: set[bytes],
               now: float) -> Joiner:
    """Ce que fait la station d'un administrateur avant de signer la nouvelle liste.

    `tokens` : jetons créés par cette station (jeton -> expiration) ; `used` : jetons déjà consommés.
    Motifs : malformed, group, token_unknown, token_used, expired, proof.
    """
    try:
        if not isinstance(req, dict) or set(req) != {"g", "i", "id", "ed", "x", "pseudo", "proof"}:
            raise Malformed("demande")
        token, ed, x = b64d(req["i"], TOKEN_SIZE), b64d(req["ed"], 32), b64d(req["x"], 32)
        proof = b64d(req["proof"], 32)
        if req["id"] != station_id_of(ed) or clean_pseudo(req["pseudo"]) != req["pseudo"]:
            raise Malformed("identifiant ou pseudo")
    except Malformed as exc:
        raise InviteRefused("malformed") from exc
    if req["g"] != group:
        raise InviteRefused("group")
    if token in used:
        raise InviteRefused("token_used")
    if token not in tokens:
        raise InviteRefused("token_unknown")
    if now >= tokens[token]:
        raise InviteRefused("expired")
    if not hmac.compare_digest(proof, _proof(key, group, token, req["id"], ed, x)):
        raise InviteRefused("proof")
    return Joiner(req["id"], ed, x, req["pseudo"], token)


# ------------------------------------------------------------------ clé de groupe remise à un membre
def _key_aad(group: str, member: str, kv: int) -> bytes:
    return KEY_DOMAIN + group.encode() + b"\0" + member.encode() + b"\0" + u32(kv)


def key_box(identity, roster: Roster, member: str, key: bytes, *, eph_seed: bytes | None = None,
            nonce: bytes | None = None) -> dict:
    target = roster.member(member)
    if target is None:
        raise ValueError("membre absent de la liste")
    aad = _key_aad(roster.group, member, roster.kv)
    box = crypto.seal(key, target.x, aad, eph_seed=eph_seed, nonce=nonce)
    return {"g": roster.group, "kv": roster.kv, "for": member, "box": b64e(box), "by": identity.station_id,
            "s": b64e(identity.sign(aad + box))}


def open_key_box(env: object, identity, roster: Roster) -> bytes:
    """Clé du groupe pour cette station ; motifs : malformed, group, version, signer, signature, decrypt."""
    try:
        if not isinstance(env, dict) or set(env) != {"g", "kv", "for", "box", "by", "s"}:
            raise Malformed("clé")
        box, sig = b64d(env["box"]), b64d(env["s"], crypto.SIG_SIZE)
    except Malformed as exc:
        raise InviteRefused("malformed") from exc
    if env["g"] != roster.group or env["for"] != identity.station_id:
        raise InviteRefused("group")
    if env["kv"] != roster.kv:
        raise InviteRefused("version")
    signer = roster.member(env["by"]) if isinstance(env["by"], str) else None
    if signer is None or signer.role not in ("a", "c"):
        raise InviteRefused("signer")
    aad = _key_aad(roster.group, identity.station_id, roster.kv)
    if not crypto.ed_verify(signer.ed, sig, aad + box):
        raise InviteRefused("signature")
    try:
        key = crypto.unseal(box, identity.x_seed, aad)
    except crypto.DecryptError as exc:
        raise InviteRefused("decrypt") from exc
    if len(key) != crypto.KEY_SIZE:
        raise InviteRefused("decrypt")
    return key


def new_group_id() -> str:
    return os.urandom(16).hex()
