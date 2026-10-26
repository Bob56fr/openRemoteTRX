"""Droits des fichiers sensibles de la station (configuration, clé TLS) sous Linux.

Les services tournent sous le compte système `trx` ; la configuration est écrite par root (sudo trx-setup).
Règle : propriétaire root, groupe `trx`, lecture pour le groupe seulement (0640). Ainsi la passerelle lit
station.toml et la clé TLS, sans pouvoir les modifier, et les autres comptes n'y ont pas accès.
Hors Linux, ou sans groupe `trx` (poste de développement), on reste en 0600 pour le propriétaire.
"""
from __future__ import annotations

import os
from pathlib import Path

SERVICE_GROUP = "trx"


def _group_id(name: str) -> int | None:
    try:
        import grp
        return grp.getgrnam(name).gr_gid
    except (ImportError, KeyError):
        return None


def protect(path: str | Path, previous: os.stat_result | None = None, *, group: str = SERVICE_GROUP) -> None:
    """Applique les droits de la station à `path`.

    `previous` : état du fichier AVANT sa réécriture ; ses droits et son propriétaire sont alors conservés
    (l'installateur a pu les régler), mais jamais plus larges que 0640.
    """
    if os.name != "posix":
        return
    path = Path(path)
    if previous is not None:
        os.chmod(path, previous.st_mode & 0o640)
        if os.geteuid() == 0:
            os.chown(path, previous.st_uid, previous.st_gid)
        return
    gid = _group_id(group)
    if gid is not None and os.geteuid() == 0:
        os.chown(path, 0, gid)
        os.chmod(path, 0o640)
    else:
        os.chmod(path, 0o600)
