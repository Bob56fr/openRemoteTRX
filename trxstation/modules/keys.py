# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Clé des modules et secret de chaque module.

Une seule clé maîtresse (`<state_dir>/modules.key`, 32 octets aléatoires) est
créée par la PASSERELLE, qui tourne sous le compte de la station : le fichier
lui appartient et n'est lisible que par elle (droits 600 sous Linux). Le
superviseur (root sous Debian) la lit pour transmettre à chaque module son
secret ; il ne la crée jamais.

Le secret d'un module est dérivé de la clé : HMAC-SHA256(clé, "module:<nom>").
Aucun fichier de secrets à tenir à jour, et un module ajouté plus tard a son
secret sans rien régénérer.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

KEY_FILE = "modules.key"
KEY_BYTES = 32


def key_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / KEY_FILE


def read_key(path: Path) -> bytes | None:
    """Clé existante, ou None si absente ou illisible (le superviseur attend)."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    return raw if len(raw) == KEY_BYTES else None


def load_or_create_key(path: Path) -> bytes:
    """Côté passerelle : lit la clé, ou la crée sans jamais écraser une clé existante."""
    path = Path(path)
    existing = read_key(path)
    if existing is not None:
        return existing
    if path.exists():
        raise OSError(f"{path} : clé des modules invalide (taille inattendue). "
                      "Supprimer le fichier pour en générer une nouvelle.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, secrets.token_bytes(KEY_BYTES))
    finally:
        os.close(fd)
    try:
        if os.name == "nt":
            os.rename(tmp, path)          # refuse d'écraser une clé déjà là
        else:
            os.link(tmp, path)            # idem, de façon atomique
    except FileExistsError:
        pass                              # une autre instance l'a créée juste avant
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    key = read_key(path)
    if key is None:
        raise OSError(f"{path} : clé des modules illisible après création")
    return key


def module_secret(key: bytes, name: str) -> str:
    return hmac.new(key, f"module:{name}".encode("utf-8"), hashlib.sha256).hexdigest()


def module_secrets(key: bytes, names) -> dict[str, str]:
    return {name: module_secret(key, name) for name in names}
