# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Messages d'une liaison établie, anti-rejeu, instantané en fragments (cahier § 4, § 17.5, § 17.6).

Enveloppe déposée sur le relais : `{"f": émetteur, "to": destinataire, "k": type, "q": séquence, "b": boîte}`.
- `b` = nonce (24) || XChaCha20-Poly1305(clé de liaison, zlib(JSON compact du contenu)), données associées
  "orx-monlink msg v1\\0" || f || "\\0" || to || "\\0" || k || "\\0" || q (8 octets, gros-boutiste).
- `q` : séquence PAR SENS de la liaison, 1 à 2^53 - 1, croissante ; le receveur tient une fenêtre de 2 048 (rejeu).
- Le relais voit f, to, k, q et la taille ; jamais le contenu.

Types et sens (le relais refuse un type hors de son sens) :
- de la station surveillée (émetteur) : `cf` confirmation et profil, `hb` battement, `st` état, `ev` événements,
  `lg` journaux, `sn` fragment d'instantané, `an` réponse à une demande, `end` fin de liaison ;
- de la station qui aide (receveur) : `rq` demande (assistance, instantané), `end`.
La demande d'appairage (`pair`) n'utilise pas cette enveloppe (pairing.py).
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass, field

from ..presence import crypto
from ..presence.codec import Malformed, b64d, b64e, cjson, parse_json, station_id_ok

MSG_DOMAIN = b"orx-monlink msg v1\0"
FROM_EMITTER = frozenset({"cf", "hb", "st", "ev", "lg", "sn", "an", "end"})
FROM_RECEIVER = frozenset({"rq", "end"})
KINDS = FROM_EMITTER | FROM_RECEIVER
MAX_SEQ = 2**53 - 1
MAX_ENVELOPE = 64 * 1024              # octets du JSON de l'enveloppe (limite du relais pour /v1/mon/put)
MAX_PLAIN = 1024 * 1024               # contenu décompressé : refus au-delà (bombe zlib)
WINDOW = 2048
SNAP_CHUNK = 32 * 1024                # octets bruts par fragment d'instantané (enveloppe < 64 ko)
SNAP_MAX = 2 * 1024 * 1024            # instantané compressé : 2 Mo au plus (64 fragments)


class MessageRefused(ValueError):
    """Motifs : malformed, kind, direction, decrypt, too_large, replay."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _aad(frm: str, to: str, kind: str, seq: int) -> bytes:
    return MSG_DOMAIN + frm.encode() + b"\0" + to.encode() + b"\0" + kind.encode() + b"\0" + struct.pack(">Q", seq)


def seal_message(key: bytes, frm: str, to: str, kind: str, seq: int, content: dict, *,
                 nonce: bytes | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"type de message inconnu : {kind}")
    if isinstance(seq, bool) or not isinstance(seq, int) or not 0 < seq <= MAX_SEQ:
        raise ValueError("séquence hors bornes")
    plain = cjson(content)
    if len(plain) > MAX_PLAIN:
        raise ValueError("contenu trop grand")
    nonce = nonce or crypto.random_nonce()
    box = nonce + crypto.xchacha_encrypt(key, nonce, zlib.compress(plain, 6), _aad(frm, to, kind, seq))
    env = {"f": frm, "to": to, "k": kind, "q": seq, "b": b64e(box)}
    if len(cjson(env)) > MAX_ENVELOPE:
        raise ValueError("message trop grand pour le relais (64 ko)")
    return env


def _inflate(data: bytes) -> bytes:
    d = zlib.decompressobj()
    try:
        out = d.decompress(data, MAX_PLAIN + 1)
    except zlib.error as exc:
        raise MessageRefused("malformed") from exc
    if len(out) > MAX_PLAIN or d.unconsumed_tail:
        raise MessageRefused("too_large")
    if not d.eof:
        raise MessageRefused("malformed")
    return out


def open_message(key: bytes, env: object, *, me: str, peer: str, peer_is_emitter: bool) -> tuple[str, int, dict]:
    """(type, séquence, contenu) d'un message reçu du partenaire ; ne gère PAS le rejeu (ReplayWindow)."""
    try:
        if not isinstance(env, dict) or set(env) != {"f", "to", "k", "q", "b"}:
            raise Malformed("enveloppe")
        if not station_id_ok(env["f"]) or not station_id_ok(env["to"]):
            raise Malformed("ids")
        seq = env["q"]
        if isinstance(seq, bool) or not isinstance(seq, int) or not 0 < seq <= MAX_SEQ:
            raise Malformed("q")
        box = b64d(env["b"])
    except Malformed as exc:
        raise MessageRefused("malformed") from exc
    if env["f"] != peer or env["to"] != me:
        raise MessageRefused("malformed")
    kind = env["k"]
    if kind not in KINDS:
        raise MessageRefused("kind")
    if kind not in (FROM_EMITTER if peer_is_emitter else FROM_RECEIVER):
        raise MessageRefused("direction")
    if len(box) < crypto.NONCE_SIZE + crypto.TAG_SIZE:
        raise MessageRefused("malformed")
    try:
        packed = crypto.xchacha_decrypt(key, box[:crypto.NONCE_SIZE], box[crypto.NONCE_SIZE:],
                                        _aad(env["f"], env["to"], kind, seq))
    except crypto.DecryptError as exc:
        raise MessageRefused("decrypt") from exc
    try:
        content = parse_json(_inflate(packed))
    except Malformed as exc:
        raise MessageRefused("malformed") from exc
    return kind, seq, content


# ------------------------------------------------------------------ anti-rejeu
@dataclass
class ReplayWindow:
    """Fenêtre glissante de 2 048 séquences (comme IPsec / WireGuard) : en retard accepté une fois, trop vieux refusé."""
    top: int = 0
    bits: int = 0                     # bit i = séquence (top - i) déjà vue
    size: int = WINDOW

    def check(self, seq: int) -> bool:
        """Sans rien marquer : la séquence serait-elle acceptée ?"""
        if seq > self.top:
            return True
        offset = self.top - seq
        return offset < self.size and not (self.bits >> offset) & 1 and seq > 0

    def accept(self, seq: int) -> None:
        """À appeler APRÈS un déchiffrement réussi (un faux message ne doit pas faire glisser la fenêtre)."""
        if not self.check(seq):
            raise MessageRefused("replay")
        if seq > self.top:
            shift = seq - self.top
            self.bits = ((self.bits << shift) | 1) & ((1 << self.size) - 1) if shift < self.size else 1
            self.top = seq
        else:
            self.bits |= 1 << (self.top - seq)

    def to_dict(self) -> dict:
        return {"top": self.top, "bits": format(self.bits, "x")}

    @classmethod
    def from_dict(cls, obj: object) -> "ReplayWindow":
        if not isinstance(obj, dict):
            return cls()
        try:
            top, bits = int(obj.get("top", 0)), int(str(obj.get("bits", "0")), 16)
        except (TypeError, ValueError):
            return cls()                  # état illisible : fenêtre neuve (la séquence de l'émetteur, elle, a grandi)
        if not 0 <= top <= MAX_SEQ or bits < 0 or bits >> WINDOW:
            return cls()
        return cls(top, bits)


# ------------------------------------------------------------------ instantané en fragments
def split_snapshot(data: bytes, snap_id: str) -> list[dict]:
    """Contenus `sn` : `{"id", "i", "n", "h", "d"}` (h = SHA-256 du tout, d = morceau en base64url)."""
    if not data or len(data) > SNAP_MAX:
        raise ValueError("instantané vide ou plus grand que 2 Mo")
    digest = hashlib.sha256(data).hexdigest()
    parts = [data[i:i + SNAP_CHUNK] for i in range(0, len(data), SNAP_CHUNK)]
    return [{"id": snap_id, "i": i, "n": len(parts), "h": digest, "d": b64e(p)} for i, p in enumerate(parts)]


@dataclass
class Reassembler:
    """Remonte un instantané, fragments dans n'importe quel ordre ; None tant qu'il en manque."""
    parts: dict[int, bytes] = field(default_factory=dict)
    n: int = 0
    digest: str = ""
    snap_id: str = ""

    def add(self, frag: object) -> bytes | None:
        try:
            if not isinstance(frag, dict) or set(frag) != {"id", "i", "n", "h", "d"}:
                raise Malformed("fragment")
            n, i = frag["n"], frag["i"]
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (n, i)):
                raise Malformed("i/n")
            if not 0 < n <= SNAP_MAX // SNAP_CHUNK or not 0 <= i < n:
                raise Malformed("i/n")
            if not isinstance(frag["h"], str) or len(frag["h"]) != 64 or not isinstance(frag["id"], str):
                raise Malformed("h/id")
            data = b64d(frag["d"])
            if not 0 < len(data) <= SNAP_CHUNK:
                raise Malformed("d")
        except Malformed as exc:
            raise MessageRefused("malformed") from exc
        if self.n == 0:
            self.n, self.digest, self.snap_id = n, frag["h"], frag["id"]
        elif (n, frag["h"], frag["id"]) != (self.n, self.digest, self.snap_id):
            raise MessageRefused("malformed")
        self.parts[i] = data
        if len(self.parts) < self.n:
            return None
        whole = b"".join(self.parts[k] for k in range(self.n))
        if hashlib.sha256(whole).hexdigest() != self.digest:
            raise MessageRefused("decrypt")       # contenu incohérent : on jette tout
        return whole
