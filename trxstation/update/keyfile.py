# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Clé privée de signature des paquets : création, lecture, clé publique (côté auteur, jamais sur la station).

La clé privée est rangée HORS du dépôt, par défaut dans le profil de l'utilisateur :
`~/.trx-remote/update-signing-key.pem` (variable TRX_SIGNING_KEY pour un autre emplacement).
Fichier PEM PKCS#8, chiffré par une phrase de passe si elle est fournie.
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

ENV_VAR = "TRX_SIGNING_KEY"
_PUBKEY_LINE = re.compile(r"^PUBLIC_KEYS: tuple\[str, \.\.\.\] = \(([^)]*)\)", re.MULTILINE)


class KeyFileError(Exception):
    pass


def default_key_path() -> Path:
    value = os.environ.get(ENV_VAR)
    return Path(value) if value else Path.home() / ".trx-remote" / "update-signing-key.pem"


def inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def public_text(private_key) -> str:
    from cryptography.hazmat.primitives import serialization
    raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def create(path: Path, passphrase: bytes | None, *, forbidden_dir: Path | None = None):
    """Crée une clé dans `path` (jamais d'écrasement) et la retourne. Refuse un emplacement dans `forbidden_dir`."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if forbidden_dir is not None and inside(path, forbidden_dir):
        raise KeyFileError(f"{path} est dans le dépôt : la clé privée doit rester hors du dépôt")
    encryption = (serialization.BestAvailableEncryption(passphrase) if passphrase
                  else serialization.NoEncryption())
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError as exc:
        raise KeyFileError(f"{path} existe déjà : clé gardée telle quelle (jamais d'écrasement)") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    return private


def is_encrypted(path: Path) -> bool:
    try:
        return b"ENCRYPTED" in path.read_bytes()[:64]
    except OSError:
        return False


def load(path: Path, passphrase: bytes | None):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise KeyFileError(f"clé privée illisible ({path}) : {exc}") from exc
    try:
        private = serialization.load_pem_private_key(data, password=passphrase or None)
    except (ValueError, TypeError) as exc:
        raise KeyFileError("clé privée illisible : phrase de passe fausse ou fichier abîmé") from exc
    if not isinstance(private, Ed25519PrivateKey):
        raise KeyFileError("ce fichier n'est pas une clé Ed25519")
    return private


def register_public_key(pubkey_file: Path, key: str) -> bool:
    """Ajoute `key` à PUBLIC_KEYS dans pubkey.py. Faux si elle y était déjà."""
    text = pubkey_file.read_text(encoding="utf-8")
    match = _PUBKEY_LINE.search(text)
    if match is None:
        raise KeyFileError(f"ligne PUBLIC_KEYS introuvable dans {pubkey_file}")
    keys = re.findall(r'"([A-Za-z0-9+/=]+)"', match.group(1))
    if key in keys:
        return False
    keys.append(key)
    line = "PUBLIC_KEYS: tuple[str, ...] = (" + "".join(f'\n    "{k}",' for k in keys) + "\n)"
    pubkey_file.write_text(text[:match.start()] + line + text[match.end():], encoding="utf-8", newline="\n")
    return True
