# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Demande d'appairage, empreinte à 6 chiffres, clé de liaison (cahier § 3 et § 17.4, étapes 2 à 4).

Demande d'appairage (de l'émetteur, déposée dans la boîte du receveur) :
`{"a": adresse de l'invitation, "from": id, "to": id, "box": sceau, "s": signature}`
- `box` = sceau X25519 (présence, `crypto.seal`) pour la clé X25519 du receveur LUE DANS L'INVITATION, contenant
  `{"v":1,"id","ed","x","pseudo","t","proof"}` ; `proof` = HMAC-SHA256(clé tirée du code,
  "orx-monlink pair v1\\0" || adresse || receveur || émetteur || ed || x) : prouve la connaissance du code ;
- `s` = signature Ed25519 de l'émetteur sur aad || box (aad = domaine || adresse || "\\0" || receveur || "\\0" || émetteur).

Empreinte : BLAKE2b-64("orx-monlink fp v1\\0" || min(ed_a, ed_b) || max(ed_a, ed_b)) modulo 10^6, `123 456`. Les deux
consoles affichent la même ; c'est sa comparaison DE VIVE VOIX qui écarte un intermédiaire (relais compris).

Clé de liaison : X25519(ma clé, sa clé) puis HKDF-SHA256(sel = ids triés, info "orx-monlink link v1"), la même des deux
côtés ; elle chiffre tous les messages de la liaison (envelope.py).
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..presence import crypto
from ..presence.codec import Malformed, b64d, b64e, cjson, parse_json, station_id_ok
from ..presence.wire import clean_pseudo
from .identity import station_id_of
from .invite import CodeKeys, Inviter

PAIR_DOMAIN = b"orx-monlink pair v1\0"
FP_DOMAIN = b"orx-monlink fp v1\0"
LINK_INFO = b"orx-monlink link v1"
PAIR_MAX_AGE_S = 15 * 60
CONFIRM_TIMEOUT_S = 10 * 60          # empreinte non confirmée : appairage annulé (cahier § 3)


class PairRefused(ValueError):
    """Motifs : malformed, decrypt, signature, unknown_invite, expired, proof, self."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Peer:
    id: str
    ed: bytes
    x: bytes
    pseudo: str


def _proof(key: bytes, address: str, to: str, frm: str, ed: bytes, x: bytes) -> bytes:
    msg = PAIR_DOMAIN + address.encode() + to.encode() + frm.encode() + ed + x
    return hmac.new(key, msg, hashlib.sha256).digest()


def _aad(address: str, to: str, frm: str) -> bytes:
    return PAIR_DOMAIN + address.encode() + b"\0" + to.encode() + b"\0" + frm.encode()


def pair_request(inviter: Inviter, keys: CodeKeys, identity, pseudo: str, *, now: float,
                 eph_seed: bytes | None = None, nonce: bytes | None = None) -> dict:
    """Côté émetteur (station aidée), après lecture de l'invitation."""
    if clean_pseudo(pseudo) != pseudo:
        raise ValueError("pseudo refusé")
    me = identity.station_id
    if me == inviter.id:
        raise PairRefused("self")
    body = cjson({"v": 1, "id": me, "ed": b64e(identity.ed_pub), "x": b64e(identity.x_pub), "pseudo": pseudo,
                  "t": int(now), "proof": b64e(_proof(keys.key, keys.address, inviter.id, me,
                                                         identity.ed_pub, identity.x_pub))})
    aad = _aad(keys.address, inviter.id, me)
    box = crypto.seal(body, inviter.x, aad, eph_seed=eph_seed, nonce=nonce)
    return {"a": keys.address, "from": me, "to": inviter.id, "box": b64e(box), "s": b64e(identity.sign(aad + box))}


@dataclass(frozen=True)
class PendingInvite:
    """Invitation créée par le receveur et pas encore utilisée (gardée en mémoire du module, 15 min)."""
    keys: CodeKeys
    expires: int


def check_pair(req: object, identity, pending: dict[str, PendingInvite], *, now: float) -> Peer:
    """Côté receveur : la demande vient-elle de quelqu'un qui connaît le code d'une invitation en cours ?"""
    try:
        if not isinstance(req, dict) or set(req) != {"a", "from", "to", "box", "s"}:
            raise Malformed("demande")
        for key in ("a", "from", "to"):
            if not station_id_ok(req[key]):
                raise Malformed(key)
        box, sig = b64d(req["box"]), b64d(req["s"], crypto.SIG_SIZE)
        if len(box) > 4096:
            raise Malformed("taille")
    except Malformed as exc:
        raise PairRefused("malformed") from exc
    if req["to"] != identity.station_id:
        raise PairRefused("malformed")
    if req["from"] == identity.station_id:
        raise PairRefused("self")
    inv = pending.get(req["a"])
    if inv is None:
        raise PairRefused("unknown_invite")
    if now >= inv.expires:
        raise PairRefused("expired")
    aad = _aad(req["a"], req["to"], req["from"])
    try:
        obj = parse_json(crypto.unseal(box, identity.x_seed, aad))
    except crypto.DecryptError as exc:
        raise PairRefused("decrypt") from exc
    except Malformed as exc:
        raise PairRefused("malformed") from exc
    try:
        if obj.get("v") != 1 or set(obj) != {"v", "id", "ed", "x", "pseudo", "t", "proof"}:
            raise Malformed("contenu")
        ed, x, proof = b64d(obj["ed"], 32), b64d(obj["x"], 32), b64d(obj["proof"], 32)
        if obj["id"] != req["from"] or station_id_of(ed) != obj["id"]:
            raise Malformed("id")
        if clean_pseudo(obj["pseudo"]) != obj["pseudo"]:
            raise Malformed("pseudo")
        t = obj["t"]
        if isinstance(t, bool) or not isinstance(t, int):
            raise Malformed("t")
    except Malformed as exc:
        raise PairRefused("malformed") from exc
    if not crypto.ed_verify(ed, sig, aad + box):
        raise PairRefused("signature")
    if abs(now - t) > PAIR_MAX_AGE_S:
        raise PairRefused("expired")
    if not hmac.compare_digest(proof, _proof(inv.keys.key, req["a"], req["to"], obj["id"], ed, x)):
        raise PairRefused("proof")
    return Peer(obj["id"], ed, x, obj["pseudo"])


# ------------------------------------------------------------------ empreinte et clé de liaison
def fingerprint(ed_a: bytes, ed_b: bytes) -> str:
    if len(ed_a) != 32 or len(ed_b) != 32:
        raise ValueError("clés Ed25519 de 32 octets attendues")
    lo, hi = sorted((ed_a, ed_b))
    value = int.from_bytes(hashlib.blake2b(FP_DOMAIN + lo + hi, digest_size=8).digest(), "big") % 1_000_000
    text = f"{value:06d}"
    return f"{text[:3]} {text[3:]}"


def link_key(identity, peer_id: str, peer_x: bytes) -> bytes:
    """Clé symétrique de la liaison, la même des deux côtés (indépendante du sens)."""
    if not station_id_ok(peer_id) or peer_id == identity.station_id:
        raise ValueError("identifiant du partenaire invalide")
    try:
        shared = X25519PrivateKey.from_private_bytes(identity.x_seed).exchange(X25519PublicKey.from_public_bytes(peer_x))
    except ValueError as exc:
        raise ValueError("clé X25519 du partenaire refusée") from exc
    if shared == bytes(32):
        raise ValueError("point X25519 de petit ordre")
    salt = "".join(sorted((identity.station_id, peer_id))).encode("ascii")
    return HKDF(hashes.SHA256(), crypto.KEY_SIZE, salt=salt, info=LINK_INFO).derive(shared)
