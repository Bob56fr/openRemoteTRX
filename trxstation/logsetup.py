# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Journaux des processus de la station : à l'écran (terminal, systemd) et, si TRX_REMOTE_LOG_DIR est défini, dans des
fichiers tournants `<dossier>/<nom>.log` (1 Mo x 5).

Sous Windows, la station tourne sans fenêtre (tâche planifiée, pythonw) : sans fichier, ses journaux seraient perdus.
Le superviseur reçoit `--log-dir` et le transmet à ses processus (passerelle, rigctld) par cette variable.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOG_DIR_ENV = "TRX_REMOTE_LOG_DIR"
SCREEN_FORMAT = "%(levelname)s %(name)s: %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def log_dir() -> Path | None:
    value = os.environ.get(LOG_DIR_ENV, "").strip()
    return Path(value) if value else None


def setup_logging(name: str, level: int = logging.INFO) -> Path | None:
    """Configure la journalisation du processus `name` ; renvoie le fichier utilisé (ou None)."""
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:                       # pythonw : pas de sortie d'erreur
        screen = logging.StreamHandler()
        screen.setFormatter(logging.Formatter(SCREEN_FORMAT))
        handlers.append(screen)
    path = None
    folder = log_dir()
    if folder is not None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{name}.log"
            file = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
            file.setFormatter(logging.Formatter(FILE_FORMAT))
            handlers.append(file)
        except OSError:
            path = None                              # jamais bloquant : la station marche sans fichier de journal
    logging.basicConfig(level=level, handlers=handlers or [logging.NullHandler()], force=True)
    return path
