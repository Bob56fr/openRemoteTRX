# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fichier de la clé d'appairage avec Breizh (breizh.key, à côté de station.toml, JAMAIS dedans).

Une ligne : la clé en base64url (43 caractères), celle que l'on recopie dans l'onglet « OpenRemoteTRX » de Breizh.
Droits : ceux de la configuration (root:trx 0640 sous Linux, ACL du dossier sous Windows) ; un fichier lisible par
tous les comptes est REFUSÉ. Jamais la clé dans un message, un journal ou un rapport.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .. import fsperm
from ..config import Config, breizh_key_path
from .protocol import key_from_text, key_to_text


class KeyFileError(ValueError):
    pass


def read_key(path: str | Path) -> bytes:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
        mode = path.stat().st_mode
    except FileNotFoundError:
        raise KeyFileError(f"{path} absent : crée la clé d'appairage (TRX Console)") from None
    except OSError as exc:
        raise KeyFileError(f"{path} illisible ({exc.strerror or type(exc).__name__})") from None
    if os.name == "posix" and mode & 0o007:
        raise KeyFileError(f"{path} est lisible par tous les comptes : droits 0640 ou 0600 attendus")
    try:
        return key_from_text(text)
    except ValueError:
        raise KeyFileError(f"{path} : clé d'appairage mal formée (43 caractères attendus)") from None


def write_key(path: str | Path, key: bytes) -> None:
    """Écrit la clé (remplacement atomique) avec les droits de la configuration."""
    path = Path(path)
    previous = path.stat() if path.exists() else None
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".breizh-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key_to_text(key) + "\n")
        fsperm.protect(tmp, previous)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def key_problem(cfg: Config, config_path: str | Path) -> str:
    """Problème BLOQUANT de la clé quand Breizh est activé (texte vide si tout va bien ou si Breizh est désactivé)."""
    if cfg.breizh.enabled is not True:
        return ""
    try:
        read_key(breizh_key_path(cfg, config_path))
    except KeyFileError as exc:
        return f"[breizh] {exc}"
    return ""
