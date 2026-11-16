# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Identité de la station pour le monitoring inter-stations (cahier § 17.2).

Deux paires de clés comme la présence : Ed25519 (signer) et X25519 (sceller, clé de liaison), mais dans un fichier À PART
(`monlink.key`, à côté de station.toml) et avec un autre domaine pour l'identifiant :
`hex(SHA-256("orx-monlink id v1\\0" || ed_pub)[0:16])`. Décision de l'utilisateur du 2026-11-16 : les partenaires de
monitoring ne doivent pas pouvoir relier la station à son groupe d'amis (présence), ni à `station-id` (collecte).
Le code cryptographique, lui, est celui de la présence (`trxstation/presence/crypto.py`).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..presence import crypto
from ..presence.codec import Malformed, b64d, b64e

ID_DOMAIN = b"orx-monlink id v1\0"
KEY_FILE = "monlink.key"
KEY_FILE_FORMAT = 1


def station_id_of(ed_pub: bytes) -> str:
    if len(ed_pub) != 32:
        raise Malformed("clé publique Ed25519 de 32 octets attendue")
    return hashlib.sha256(ID_DOMAIN + ed_pub).digest()[:16].hex()


@dataclass(frozen=True)
class Identity:
    ed_seed: bytes
    x_seed: bytes

    def __post_init__(self) -> None:
        if len(self.ed_seed) != 32 or len(self.x_seed) != 32:
            raise Malformed("graines de 32 octets attendues")

    @classmethod
    def generate(cls) -> "Identity":
        return cls(os.urandom(32), os.urandom(32))

    @property
    def ed_pub(self) -> bytes:
        return crypto.ed_public(self.ed_seed)

    @property
    def x_pub(self) -> bytes:
        return crypto.x_public(self.x_seed)

    @property
    def station_id(self) -> str:
        return station_id_of(self.ed_pub)

    def sign(self, data: bytes) -> bytes:
        return crypto.ed_sign(self.ed_seed, data)

    def __repr__(self) -> str:                  # jamais les graines dans un journal
        return f"Identity(monlink {self.station_id})"

    # -------------------------------------------------------------- fichier
    def to_text(self) -> str:
        return json.dumps({"format": KEY_FILE_FORMAT, "ed": b64e(self.ed_seed), "x": b64e(self.x_seed)}) + "\n"

    @classmethod
    def from_text(cls, text: str) -> "Identity":
        try:
            obj = json.loads(text)
        except ValueError as exc:
            raise Malformed("fichier de clés illisible") from exc
        if not isinstance(obj, dict) or obj.get("format") != KEY_FILE_FORMAT:
            raise Malformed("format du fichier de clés inconnu")
        return cls(b64d(obj.get("ed"), 32), b64d(obj.get("x"), 32))


def save_key_file(path: Path, identity: Identity) -> None:
    """Écrit le fichier de clés (0600 hors Windows ; sous Windows, les ACL du dossier de configuration)."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(identity.to_text())
    os.replace(tmp, path)


def load_key_file(path: Path) -> Identity:
    return Identity.from_text(path.read_text(encoding="utf-8"))
