# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Identifiant unique de la station (GUID), pour les échanges futurs avec rf-diy.com (rapports, autres services).

`<state_dir>/station-id` : un UUID version 4 (122 bits tirés de `os.urandom`, le générateur du système), créé
une seule fois par la PASSERELLE au premier démarrage, jamais écrasé, lisible par tous (0644 : TRX Console et le
rapport de dépannage le lisent). Il survit aux mises à jour et aux retours arrière (dossier d'état hors des versions).

Doublons : avec 2^122 valeurs possibles, il faudrait environ 2,7 milliards de milliards de stations pour avoir
une chance sur deux d'en voir deux identiques. Les seuls vrais risques sont humains : copier le dossier d'état
d'une station à l'autre (clonage d'une carte SD de Pi), ou un générateur aléatoire cassé ; d'où l'UUID 4
tiré de `os.urandom` (et non l'UUID 1, qui dépend de l'horloge et de l'adresse MAC), et la possibilité de
supprimer le fichier pour en obtenir un nouveau.

Il n'est envoyé nulle part par la station : il n'accompagne que ce que l'utilisateur choisit de transmettre.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

ID_FILE = "station-id"


def id_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / ID_FILE


def read_station_id(state_dir: str | Path) -> str | None:
    """Identifiant existant (forme canonique), ou None si absent, illisible ou invalide."""
    try:
        text = id_path(state_dir).read_text(encoding="ascii").strip()
        value = uuid.UUID(text)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return str(value) if value.version == 4 and str(value) == text.lower() else None


def ensure_station_id(state_dir: str | Path) -> str:
    """Côté passerelle : lit l'identifiant, ou le crée sans jamais écraser un fichier existant."""
    existing = read_station_id(state_dir)
    if existing is not None:
        return existing
    path = id_path(state_dir)
    if path.exists():
        raise OSError(f"{path} : identifiant de station invalide. Supprimer le fichier pour en générer un nouveau.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    try:
        os.write(fd, (str(uuid.uuid4()) + "\n").encode("ascii"))
    finally:
        os.close(fd)
    try:
        os.chmod(tmp, 0o644)                  # umask du service : lisible par le compte de bureau
        if os.name == "nt":
            os.rename(tmp, path)              # refuse d'écraser un identifiant déjà là
        else:
            os.link(tmp, path)                # idem, de façon atomique
    except FileExistsError:
        pass                                  # une autre instance l'a créé juste avant
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    value = read_station_id(state_dir)
    if value is None:
        raise OSError(f"{path} : identifiant de station illisible après création")
    return value
