# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Liste des membres d'un groupe, signée par un administrateur (cahier § 5.2 et § 6).

Enveloppe transmise par le relais (qui ne peut pas la modifier) : `{"p": base64url(contenu), "by": signataire,
"s": base64url(signature Ed25519 de "orx-presence roster v1\\0" || contenu)}`.
Contenu (JSON compact) : `v` = 1, `g` groupe, `ver` version (1, 2, …), `prev` SHA-256 hexadécimal du contenu de la
version précédente ("" pour la 1re), `t` heure, `kv` version de la clé du groupe, `m` membres triés par identifiant
(`id`, `ed`, `x` clés publiques en base64url, `r` rôle a / c / m, `j` heure d'adhésion).

Règles vérifiées par CHAQUE station (jamais par le relais seul) :
- un identifiant est l'empreinte de sa clé Ed25519 ; les clés d'un membre ne changent jamais ;
- version + 1, chaînage `prev`, même groupe ; signataire administrateur (a) ou co-administrateur (c) de la version
  PRÉCÉDENTE ; la 1re version est signée par l'administrateur nommé dans l'invitation ;
- un départ ou une exclusion impose une nouvelle clé (`kv` + 1) ; `kv` ne recule jamais ;
- un co-administrateur ne touche pas aux administrateurs, sauf reprise après 90 jours sans administrateur actif : il
  devient alors administrateur ;
- au moins un administrateur, 50 membres au plus.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from . import crypto
from .codec import Malformed, b64d, b64e, cjson, group_id_ok, parse_json, station_id_ok
from .identity import station_id_of

ROSTER_DOMAIN = b"orx-presence roster v1\0"
ROLES = ("a", "c", "m")
MAX_MEMBERS = 50
TAKEOVER_S = 90 * 86400
_HASH_RE = re.compile(r"[0-9a-f]{64}")


class RosterRefused(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Member:
    id: str
    ed: bytes
    x: bytes
    role: str
    joined: int

    def as_json(self) -> dict:
        return {"id": self.id, "ed": b64e(self.ed), "x": b64e(self.x), "r": self.role, "j": self.joined}


@dataclass(frozen=True)
class Roster:
    group: str
    version: int
    prev: str
    t: int
    kv: int
    members: tuple[Member, ...]

    def __post_init__(self) -> None:          # une seule forme : membres triés par identifiant
        object.__setattr__(self, "members", tuple(sorted(self.members, key=lambda m: m.id)))

    def payload(self) -> bytes:
        return cjson({"v": 1, "g": self.group, "ver": self.version, "prev": self.prev, "t": self.t, "kv": self.kv,
                      "m": [m.as_json() for m in self.members]})

    def digest(self) -> str:
        return hashlib.sha256(self.payload()).hexdigest()

    def member(self, station: str) -> Member | None:
        return next((m for m in self.members if m.id == station), None)

    def admins(self) -> set[str]:
        return {m.id for m in self.members if m.role == "a"}

    def next(self, *, t: int, members: list[Member], kv: int | None = None) -> "Roster":
        return Roster(self.group, self.version + 1, self.digest(), t, self.kv if kv is None else kv, tuple(members))


def new_member(ed: bytes, x: bytes, role: str, joined: int) -> Member:
    return Member(station_id_of(ed), ed, x, role, joined)


def sign(roster: Roster, identity) -> dict:
    body = roster.payload()
    return {"p": b64e(body), "by": identity.station_id, "s": b64e(identity.sign(ROSTER_DOMAIN + body))}


def _parse(env: object) -> tuple[Roster, str, bytes, bytes]:
    if not isinstance(env, dict) or set(env) != {"p", "by", "s"} or not station_id_ok(env.get("by")):
        raise RosterRefused("malformed")
    try:
        body = b64d(env["p"])
        sig = b64d(env["s"], crypto.SIG_SIZE)
        obj = parse_json(body)
        roster = _roster(obj)
    except Malformed as exc:
        raise RosterRefused("malformed") from exc
    if roster.payload() != body:              # forme unique : pas deux écritures d'une même liste
        raise RosterRefused("malformed")
    return roster, env["by"], body, sig


def _roster(obj: dict) -> Roster:
    if obj.get("v") != 1 or set(obj) != {"v", "g", "ver", "prev", "t", "kv", "m"} or not group_id_ok(obj["g"]):
        raise Malformed("liste")
    for key in ("ver", "t", "kv"):
        if isinstance(obj[key], bool) or not isinstance(obj[key], int) or not 0 < obj[key] < 2**40:
            raise Malformed(key)
    if not isinstance(obj["prev"], str) or (obj["prev"] and not _HASH_RE.fullmatch(obj["prev"])):
        raise Malformed("prev")
    if not isinstance(obj["m"], list) or not 0 < len(obj["m"]) <= MAX_MEMBERS:
        raise Malformed("m")
    members = []
    for m in obj["m"]:
        if not isinstance(m, dict) or set(m) != {"id", "ed", "x", "r", "j"} or m["r"] not in ROLES:
            raise Malformed("membre")
        ed, x = b64d(m["ed"], 32), b64d(m["x"], 32)
        if m["id"] != station_id_of(ed):
            raise Malformed("identifiant différent de l'empreinte de la clé")
        if isinstance(m["j"], bool) or not isinstance(m["j"], int) or not 0 < m["j"] < 2**40:
            raise Malformed("j")
        members.append(Member(m["id"], ed, x, m["r"], m["j"]))
    if len({m.id for m in members}) != len(members):
        raise Malformed("membre en double")
    return Roster(obj["g"], obj["ver"], obj["prev"], obj["t"], obj["kv"], tuple(members))


def accept_first(env: object, *, group: str, admin: str) -> Roster:
    """1re liste d'un groupe rejoint : signée par l'administrateur de l'invitation, qui y est administrateur."""
    roster, by, body, sig = _parse(env)
    if roster.group != group:
        raise RosterRefused("group")
    if by != admin:
        raise RosterRefused("signer")
    signer = roster.member(by)
    if signer is None or signer.role not in ("a", "c"):
        raise RosterRefused("signer")
    if not crypto.ed_verify(signer.ed, sig, ROSTER_DOMAIN + body):
        raise RosterRefused("signature")
    if not roster.admins():
        raise RosterRefused("no_admin")
    return roster


def accept_next(old: Roster, env: object, *, admin_last_seen: float, now: float) -> Roster:
    """Version suivante d'une liste connue ; `admin_last_seen` : dernière fois qu'un administrateur s'est manifesté."""
    new, by, body, sig = _parse(env)
    if new.version != old.version + 1:
        raise RosterRefused("version")
    if new.prev != old.digest():
        raise RosterRefused("chain")
    return _transition(old, new, by, body, sig, admin_last_seen=admin_last_seen, now=now)


def accept_jump(old: Roster, env: object, *, admin_last_seen: float, now: float) -> Roster:
    """Version PLUS LOINTAINE que la suivante (station éteinte au-delà de l'historique du relais) : sans chaînage,
    elle doit être signée par un administrateur ou co-administrateur de la liste CONNUE, avec la clé connue ; mêmes
    règles pour le reste (clés figées, clé qui ne recule pas, droits d'un co-administrateur)."""
    new, by, body, sig = _parse(env)
    if new.version <= old.version + 1:
        raise RosterRefused("version")
    return _transition(old, new, by, body, sig, admin_last_seen=admin_last_seen, now=now, jumped=True)


def _transition(old: Roster, new: Roster, by: str, body: bytes, sig: bytes, *, admin_last_seen: float, now: float,
                jumped: bool = False) -> Roster:
    if new.group != old.group:
        raise RosterRefused("group")
    signer = old.member(by)
    if signer is None or signer.role not in ("a", "c"):
        raise RosterRefused("signer")
    if not crypto.ed_verify(signer.ed, sig, ROSTER_DOMAIN + body):
        raise RosterRefused("signature")
    for m in new.members:
        before = old.member(m.id)
        if before is not None and (before.ed != m.ed or before.x != m.x or before.joined != m.joined):
            raise RosterRefused("key_changed")
    removed = {m.id for m in old.members} - {m.id for m in new.members}
    if new.kv < old.kv or (removed and new.kv == old.kv):
        raise RosterRefused("rotation_missing")
    if not new.admins():
        raise RosterRefused("no_admin")
    if signer.role == "c":
        same = new.admins() == old.admins()
        takeover = now - admin_last_seen >= TAKEOVER_S and new.admins() == {by}
        if not (same or takeover):
            raise RosterRefused("admin_rights")
    return new


def follow(current: Roster | None, envelopes: list, *, group: str, invite_admin: str | None,
           admin_last_seen: float, now: float) -> tuple[Roster | None, list[str]]:
    """Applique dans l'ordre les versions reçues du relais ; (liste retenue, motifs des versions refusées).

    Sans liste connue (adhésion), la 1re version acceptée est la première signée par l'administrateur de
    l'invitation ; ensuite chaque version doit suivre (chaînage) ou, après un trou, sauter (accept_jump).
    """
    refused: list[str] = []
    for env in envelopes:
        try:
            if current is None:
                if invite_admin is None:
                    raise RosterRefused("signer")
                current = accept_first(env, group=group, admin=invite_admin)
                continue
            version = _parse(env)[0].version
            if version <= current.version:
                continue
            if version == current.version + 1:
                current = accept_next(current, env, admin_last_seen=admin_last_seen, now=now)
            else:
                current = accept_jump(current, env, admin_last_seen=admin_last_seen, now=now)
        except RosterRefused as exc:
            refused.append(exc.reason)
    return current, refused


def parse_unchecked(env: object) -> Roster:
    """Liste relue depuis le fichier de la station (déjà vérifiée quand elle a été reçue)."""
    return _parse(env)[0]
