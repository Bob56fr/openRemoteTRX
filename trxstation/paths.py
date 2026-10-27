# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Emplacements par défaut selon le système (configuration, état, dossier d'exécution).

Linux / Raspberry Pi : /etc, /run, /var/lib. Windows : %PROGRAMDATA%\\trx-remote.
La variable d'environnement TRX_REMOTE_HOME place tout sous un seul dossier (développement,
installation sans droits administrateur).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def _override() -> Path | None:
    value = os.environ.get("TRX_REMOTE_HOME")
    return Path(value) if value else None


def _windows_root() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "trx-remote"


def default_config_path() -> Path:
    if (home := _override()) is not None:
        return home / "station.toml"
    return _windows_root() / "station.toml" if is_windows() else Path("/etc/trx-remote/station.toml")


def default_status_path() -> Path:
    if (home := _override()) is not None:
        return home / "run" / "gateway-status.json"
    return (_windows_root() / "run" / "gateway-status.json" if is_windows()
            else Path("/run/trx-remote/gateway-status.json"))


def default_state_dir() -> Path:
    if (home := _override()) is not None:
        return home / "state"
    return _windows_root() / "state" if is_windows() else Path("/var/lib/trx-remote")
