# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Secrets de la diffusion : `diffusion.key` (JSON, 0600), jamais dans station.toml, jamais affichés en entier.

Champs : `source_password` et `meta_key` (64 caractères hexadécimaux), donnés par l'administrateur du serveur ;
`listener_user` et `listener_password` : identifiants des auditeurs du montage privé, choisis par l'opérateur
(« En générer un ») et renvoyés au serveur à chaque lancement privé.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from . import protocol as p

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class KeyFileError(ValueError):
    pass


@dataclass(frozen=True)
class Secrets:
    source_password: str
    meta_key: str
    listener_user: str = "auditeur"
    listener_password: str = ""

    def __repr__(self) -> str:                       # jamais un secret dans un journal ou une trace
        return (f"Secrets(source={p.masked(self.source_password)}, meta_key=…, user={self.listener_user}, "
                f"password={p.masked(self.listener_password)})")

    @property
    def meta_key_bytes(self) -> bytes:
        return bytes.fromhex(self.meta_key)


def check(s: Secrets) -> Secrets:
    if not isinstance(s.source_password, str) or not s.source_password or any(c in s.source_password for c in "\r\n:"):
        raise KeyFileError("source_password vide ou invalide")
    if not isinstance(s.meta_key, str) or not _HEX64.match(s.meta_key):
        raise KeyFileError("meta_key : 64 caractères hexadécimaux attendus")
    if not isinstance(s.listener_user, str) or not p.LISTENER_USER.match(s.listener_user):
        raise KeyFileError("listener_user invalide")
    if s.listener_password and not p.LISTENER_PASSWORD.match(s.listener_password):
        raise KeyFileError("listener_password : 8 à 64 lettres ou chiffres")
    return s


def read(path: Path) -> Secrets:
    try:
        st = path.stat()
    except FileNotFoundError:
        raise KeyFileError(f"{path.name} absent") from None
    if os.name == "posix" and st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise KeyFileError(f"{path.name} lisible par d'autres comptes (droits attendus : 0600)")
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        s = Secrets(**{k: d[k] for k in ("source_password", "meta_key") },
                    listener_user=d.get("listener_user", "auditeur"),
                    listener_password=d.get("listener_password", ""))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise KeyFileError(f"{path.name} illisible ({exc.__class__.__name__})") from None
    return check(s)


def save(path: Path, s: Secrets) -> None:
    check(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (json.dumps(asdict(s), indent=1) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)
