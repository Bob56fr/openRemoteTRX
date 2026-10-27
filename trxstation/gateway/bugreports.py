# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Rapports de problème envoyés par la page (« Signaler un problème » > « Envoyer à la station »).

Le texte est assemblé par la page et MONTRÉ à l'utilisateur avant l'envoi : il décide de ce qui part. La station le
range dans `<state_dir>/reports/page-AAAAMMJJ-HHMMSS-<compte>.txt` ; TRX Console le joint au rapport de dépannage
(menu 8). Rien ne part sur Internet depuis la passerelle.

Garde-fous : clients authentifiés seulement (la session donne le compte, jamais le message) ; texte borné
(MAX_TEXT_CHARS), caractères de contrôle retirés (sauf saut de ligne et tabulation) ; un envoi par compte toutes les
MIN_INTERVAL_S ; les KEEP plus récents gardés (les plus anciens supprimés) ; écriture atomique, fichiers 0644.
"""
from __future__ import annotations

import datetime
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

MAX_TEXT_CHARS = 30_000
MIN_INTERVAL_S = 30.0
KEEP = 20
PREFIX = "page-"
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]")
_ACCOUNT = re.compile(r"[^A-Za-z0-9_-]")


class ReportRefused(Exception):
    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        super().__init__(f"{reason}: {detail}" if detail else reason)


def clean(text: str) -> str:
    return _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))[:MAX_TEXT_CHARS]


class ReportStore:
    def __init__(self, folder: Path, *, version: str = "", clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime.datetime] = datetime.datetime.now):
        self.folder, self.version, self.clock, self.now = Path(folder), version, clock, now
        self._last: dict[str, float] = {}

    def save(self, client_id: str, text: str) -> str:
        """Range le rapport ; renvoie son nom de fichier. ReportRefused si refusé."""
        if not isinstance(text, str) or not text.strip():
            raise ReportRefused("report_empty")
        moment = self.clock()
        last = self._last.get(client_id)
        if last is not None and moment - last < MIN_INTERVAL_S:
            raise ReportRefused("report_too_soon", f"{MIN_INTERVAL_S - (moment - last):.0f} s")
        stamp = self.now()
        account = _ACCOUNT.sub("_", client_id)[:32] or "inconnu"
        name = f"{PREFIX}{stamp.strftime('%Y%m%d-%H%M%S')}-{account}.txt"
        header = (f"# Rapport de problème envoyé par la page\n# compte : {account}\n"
                  f"# reçu par la station le {stamp.strftime('%Y-%m-%d %H:%M:%S')} (version {self.version or '?'})\n\n")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".rapport-", dir=self.folder)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(header + clean(text) + "\n")
            os.chmod(tmp, 0o644)
            os.replace(tmp, self.folder / name)
        except OSError as exc:
            raise ReportRefused("report_storage_error", str(exc)) from exc
        self._last[client_id] = moment
        self._prune()
        return name

    def list(self) -> list[Path]:
        try:
            return sorted(p for p in self.folder.glob(f"{PREFIX}*.txt") if p.is_file())
        except OSError:
            return []

    def _prune(self) -> None:
        for old in self.list()[:-KEEP]:
            try:
                old.unlink()
            except OSError:
                pass
