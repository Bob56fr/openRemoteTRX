# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""État d'une station dans un groupe : signé par la station, chiffré avec la clé du groupe, 256 octets FIXES.

Bloc envoyé au relais (base64url) : nonce (24) || chiffré (216) || étiquette (16).
Clair de 216 octets : longueur L (2 octets, gros-boutiste) || contenu JSON (L ≤ 150) || signature (64) || zéros.
Signature Ed25519 et données associées du chiffrement liées au groupe, à la station et à la version de la clé :
`"orx-presence state v1\\0" || groupe || "\\0" || station || "\\0" || u32(version de clé)` (signature : suivi du
contenu). Un état ne peut donc être ni déplacé d'un groupe à l'autre, ni attribué à une autre station.

Contenu (`v` = 1) : `n` compteur, `t` heure, `st` statut (Q R S A, ou H = invisible, sans autre champ), `sd` début du
statut (absent si l'opérateur cache sa durée d'absence), `lt` dernière émission, `su` fin de la plage « Au shack »,
`lv` niveau (`f` fréquence et mode avec `f` et `m`, `o` On Air, `x` texte avec `x`).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from . import crypto
from .codec import Malformed, b64d, b64e, cjson, parse_json, u32
from .status import Status
from .wire import clean_text, freq_ok, mode_ok

STATE_DOMAIN = b"orx-presence state v1\0"
BLOB_SIZE = 256
PLAIN_SIZE = BLOB_SIZE - crypto.NONCE_SIZE - crypto.TAG_SIZE      # 216
MAX_CONTENT = PLAIN_SIZE - 2 - crypto.SIG_SIZE                     # 150
MAX_TIME = 2**40
LEVELS = ("f", "o", "x")
CODES = ("Q", "R", "S", "A", "H")
MAX_SKEW_S = 600          # un état daté de plus de 10 min dans le futur est refusé


class StateRefused(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Share:
    """Ce que l'opérateur partage dans un groupe."""
    level: str = "o"
    text: str | None = None
    invisible: bool = False
    hide_absence: bool = False

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError("niveau f, o ou x")
        if self.level == "x" and clean_text(self.text) != self.text:
            raise ValueError("texte libre refusé")


def header(group: str, station: str, key_version: int) -> bytes:
    return STATE_DOMAIN + group.encode("ascii") + b"\0" + station.encode("ascii") + b"\0" + u32(key_version)


def content(status: Status, share: Share, *, n: int, t: float, freq: int | None, mode: str | None) -> dict:
    if share.invisible:
        return {"v": 1, "n": n, "t": int(t), "st": "H"}
    out: dict = {"v": 1, "n": n, "t": int(t), "st": status.code, "lv": share.level}
    if not (status.code == "A" and share.hide_absence):
        out["sd"] = int(status.since)
    if status.last_tx is not None:
        out["lt"] = int(status.last_tx)
    if status.shack_until is not None:
        out["su"] = int(status.shack_until)
    if share.level == "f":
        if freq_ok(freq) and mode_ok(mode):
            out["f"], out["m"] = freq, mode
        else:
            out["lv"] = "o"           # poste muet ou mode inconnu : rien de faux à suivre
    elif share.level == "x":
        out["x"] = share.text
    return out


def seal_state(identity, group: str, key: bytes, key_version: int, obj: dict, *, nonce: bytes | None = None) -> str:
    body = cjson(obj)
    if len(body) > MAX_CONTENT:
        raise ValueError(f"état trop long ({len(body)} > {MAX_CONTENT})")
    head = header(group, identity.station_id, key_version)
    plain = struct.pack(">H", len(body)) + body + identity.sign(head + body)
    plain += bytes(PLAIN_SIZE - len(plain))
    nonce = nonce or crypto.random_nonce()
    return b64e(nonce + crypto.xchacha_encrypt(key, nonce, plain, head))


def open_state(blob: str, *, group: str, station: str, ed_pub: bytes, key: bytes, key_version: int,
               last_n: int = 0, now: float) -> dict:
    """État d'un membre, vérifié ; `StateRefused(motif)` sinon : size, decrypt, signature, malformed, replay, future."""
    try:
        raw = b64d(blob, BLOB_SIZE)
    except Malformed as exc:
        raise StateRefused("size") from exc
    head = header(group, station, key_version)
    try:
        plain = crypto.xchacha_decrypt(key, raw[:crypto.NONCE_SIZE], raw[crypto.NONCE_SIZE:], head)
    except crypto.DecryptError as exc:
        raise StateRefused("decrypt") from exc
    (size,) = struct.unpack(">H", plain[:2])
    if size > MAX_CONTENT or any(plain[2 + size + crypto.SIG_SIZE:]):
        raise StateRefused("malformed")
    body, sig = plain[2:2 + size], plain[2 + size:2 + size + crypto.SIG_SIZE]
    if not crypto.ed_verify(ed_pub, sig, head + body):
        raise StateRefused("signature")
    try:
        obj = _validate(parse_json(body))
    except Malformed as exc:
        raise StateRefused("malformed") from exc
    if obj["n"] <= last_n:
        raise StateRefused("replay")
    if obj["t"] > now + MAX_SKEW_S:
        raise StateRefused("future")
    return obj


def _validate(obj: dict) -> dict:
    """Garde seulement les champs connus, chacun vérifié ; tout écart = Malformed."""
    if obj.get("v") != 1:
        raise Malformed("version")
    n = obj.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or not 0 < n < 2**53:
        raise Malformed("n")
    out: dict = {"n": n, "t": _time(obj, "t")}
    st = obj.get("st")
    if st not in CODES:
        raise Malformed("st")
    out["st"] = st
    if st == "H":
        if set(obj) - {"v", "n", "t", "st"}:
            raise Malformed("champs en trop")
        return out
    lv = obj.get("lv")
    if lv not in LEVELS:
        raise Malformed("lv")
    out["lv"] = lv
    for key in ("sd", "lt", "su"):
        if key in obj:
            out[key] = _time(obj, key)
    if lv == "f":
        if not freq_ok(obj.get("f")) or not mode_ok(obj.get("m")):
            raise Malformed("f/m")
        out["f"], out["m"] = obj["f"], obj["m"]
    elif lv == "x":
        if clean_text(obj.get("x")) != obj.get("x"):
            raise Malformed("x")
        out["x"] = obj["x"]
    allowed = {"v", "n", "t", "st", "lv", "sd", "lt", "su"} | {"f": {"f", "m"}, "o": set(), "x": {"x"}}[lv]
    if set(obj) - allowed:
        raise Malformed("champs en trop")
    return out


def _time(obj: dict, key: str) -> int:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < MAX_TIME:
        raise Malformed(key)
    return value
