# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Journaux des processus de la station : à l'écran (terminal, systemd) et, si TRX_REMOTE_LOG_DIR est défini, dans des
fichiers tournants `<dossier>/<nom>.log` (1 Mo x 5).

Sous Windows, la station tourne sans fenêtre (tâche planifiée, pythonw) : sans fichier, ses journaux seraient perdus.
Le superviseur reçoit `--log-dir` et le transmet à ses processus (passerelle, rigctld) par cette variable.

Journal STRUCTURÉ (lot M1 du monitoring, étape 174) : `add_json_journal` ajoute un fichier JSON Lines tournant
`<dossier d'état>/journal-<nom>.jsonl` (1 Mo x 3), un objet par ligne : avertissements et plus graves, et tout
événement du catalogue d'erreurs (champ `event` d'`emit_event` / `Notifier.alert` : code, gravité, contexte). Lu plus
tard par le monitor inter-stations ; jamais bloquant (dossier non inscriptible = pas de journal JSON).
"""
from __future__ import annotations

import datetime as dt
import json
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


class JsonFormatter(logging.Formatter):
    """Une ligne JSON par enregistrement ; les valeurs non sérialisables deviennent du texte."""

    def __init__(self, process: str) -> None:
        super().__init__()
        self.process = process

    def format(self, record: logging.LogRecord) -> str:
        line: dict = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(timespec="milliseconds")
                    .replace("+00:00", "Z"),
            "processus": self.process, "niveau": record.levelname, "source": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, dict):
            for key in ("code", "gravite", "titre", "contexte", "module", "connu"):
                if key in event:
                    line[key] = event[key]
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False, default=str)


class _JournalFilter(logging.Filter):
    """Avertissements et plus graves, ou événement du catalogue (même d'information)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or isinstance(getattr(record, "event", None), dict)


def add_json_journal(name: str, folder: str | Path) -> Path | None:
    """Ajoute le journal JSON du processus `name` dans `folder` (dossier d'état) ; renvoie son chemin ou None."""
    try:
        path = Path(folder) / f"journal-{name}.jsonl"
        root = logging.getLogger()
        for h in root.handlers:                      # appel répété (essais) : pas de second fichier
            if isinstance(h, logging.handlers.RotatingFileHandler) and Path(h.baseFilename) == path.resolve():
                return path
        if not Path(folder).is_dir():
            return None                              # jamais de dossier d'état créé ici (droits du compte trx)
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(JsonFormatter(name))
        handler.addFilter(_JournalFilter())
        handler.setLevel(logging.INFO)
        root.addHandler(handler)
        return path
    except (OSError, ValueError):
        return None                                  # jamais bloquant : la station marche sans journal JSON
