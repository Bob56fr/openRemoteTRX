# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglages de l'opérateur pour Breizh (state_dir/breizh.json) et journal de la liaison (state_dir/breizh-log.jsonl).

Pas dans station.toml : la passerelle ne doit pas pouvoir y écrire (docs/breizh-cahier-des-charges.md § 6.2).
- return_gain_db : volume retour, de −20 à +6 dB par pas de 0,5 ;
- bypass : « Direct » choisi par l'opérateur (Breizh ignoré à la prochaine émission).
Le journal garde les 200 derniers événements ; chaque événement part aussi vers les écouteurs (clients opérateurs).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

RETURN_GAIN_MIN, RETURN_GAIN_MAX = -20.0, 6.0
JOURNAL_SIZE = 200
EVENTS = ("connected", "lost", "fallback", "back", "reactivated", "refused", "bad_packets", "bypass", "unbypass")


@dataclass
class BreizhSettings:
    return_gain_db: float = 0.0
    bypass: bool = False


def check_return_gain(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise ValueError("return_gain_db : nombre attendu")
    value = float(value)
    if not RETURN_GAIN_MIN <= value <= RETURN_GAIN_MAX or round(value * 2) != value * 2:
        raise ValueError(f"return_gain_db : de {RETURN_GAIN_MIN:g} à +{RETURN_GAIN_MAX:g} dB par pas de 0,5")
    return value


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class BreizhStore:
    def __init__(self, state_dir: str | Path, clock: Callable[[], float] = time.time) -> None:
        self.settings_path = Path(state_dir) / "breizh.json"
        self.journal_path = Path(state_dir) / "breizh-log.jsonl"
        self.clock = clock
        self.settings = self._load_settings()
        self.journal: deque[dict] = deque(self._load_journal(), maxlen=JOURNAL_SIZE)
        self._listeners: list[Callable[[dict], None]] = []

    # -- réglages
    def _load_settings(self) -> BreizhSettings:
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            settings = BreizhSettings(check_return_gain(data.get("return_gain_db", 0.0)), data.get("bypass") is True)
        except FileNotFoundError:
            return BreizhSettings()
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("%s illisible (%s) : réglages par défaut", self.settings_path, exc)
            return BreizhSettings()
        return settings

    def update(self, *, return_gain_db: float | None = None, bypass: bool | None = None) -> BreizhSettings:
        """OSError si le fichier ne peut pas être écrit (le réglage n'est alors pas changé)."""
        new = BreizhSettings(self.settings.return_gain_db if return_gain_db is None else check_return_gain(return_gain_db),
                             self.settings.bypass if bypass is None else bypass)
        _write_atomic(self.settings_path, json.dumps(asdict(new)) + "\n")
        self.settings = new
        return new

    # -- journal
    def _load_journal(self) -> list[dict]:
        try:
            lines = self.journal_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries = []
        for line in lines[-JOURNAL_SIZE:]:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("event") in EVENTS:
                entries.append(entry)
        return entries

    def add_listener(self, callback: Callable[[dict], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[dict], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def event(self, event: str, detail: str) -> dict:
        """Journal + écouteurs. Jamais d'exception : un disque plein ne doit pas gêner l'émission."""
        entry = {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock())), "event": event, "detail": detail}
        self.journal.append(entry)
        log.log(logging.WARNING if event in ("lost", "fallback", "refused") else logging.INFO, "Breizh : %s", detail)
        try:
            _write_atomic(self.journal_path, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.journal))
        except OSError as exc:
            log.error("journal de Breizh non écrit : %s", exc)
        for callback in list(self._listeners):
            try:
                callback(entry)
            except Exception:
                log.exception("événement Breizh non transmis")
        return entry

    def last(self, count: int = 50) -> list[dict]:
        return list(self.journal)[-count:]
