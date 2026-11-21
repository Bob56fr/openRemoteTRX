# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fichiers du module « monlink », dans `state_dir/monlink/` (écrits par le module seul).

- `monlink.json` (0600 : clés publiques des partenaires, clés des invitations en cours) : pseudo, enregistrement,
  invitations, liaisons (rôle, état, profil, séquences, fenêtre anti-rejeu, positions des journaux lus) ;
- `status.json` (0644) : résumé SANS clé, lu par openRemoteTRX Console et trx-monitor ;
- `received.db` (SQLite, côté station qui AIDE) : battements, états et événements reçus de chaque partenaire,
  gardés 30 jours (cahier § 8), effacés à la fin d'une liaison si l'opérateur le demande.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..presence.store import read_json, write_json

STATE_FILE = "monlink.json"
STATUS_FILE = "status.json"
DB_FILE = "received.db"
FORMAT = 1
KEEP_DAYS = 30


def default_data() -> dict:
    return {"format": FORMAT, "registered": False, "pseudo": "", "invites": {}, "links": {}, "inbox_after": 0,
            "journal": {}}


class Store:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        data = read_json(self.folder / STATE_FILE)
        if data is None or data.get("format") != FORMAT:
            data = default_data()
        base = default_data()
        base.update(data)
        self.data = base
        self._db: sqlite3.Connection | None = None

    @property
    def links(self) -> dict[str, dict]:
        return self.data["links"]

    def save(self) -> None:
        write_json(self.folder / STATE_FILE, self.data, private=True)

    def write_status(self, status: dict) -> None:
        try:
            write_json(self.folder / STATUS_FILE, status, private=False)
        except OSError:
            pass                                  # l'état reste en mémoire ; réécrit au cycle suivant

    # ------------------------------------------------------------ réception (station qui aide)
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self.folder.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.folder / DB_FILE)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("CREATE TABLE IF NOT EXISTS received (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                             "peer TEXT NOT NULL, kind TEXT NOT NULL, at REAL NOT NULL, content TEXT NOT NULL)")
            self._db.execute("CREATE INDEX IF NOT EXISTS received_peer ON received (peer, id)")
        return self._db

    def keep(self, peer: str, kind: str, content: dict, at: float) -> None:
        db = self.db()
        db.execute("INSERT INTO received (peer, kind, at, content) VALUES (?, ?, ?, ?)",
                   (peer, kind, at, json.dumps(content, ensure_ascii=False)))
        db.commit()

    def recent(self, peer: str, kinds: tuple[str, ...] = ("ev",), limit: int = 50) -> list[dict]:
        rows = self.db().execute(
            f"SELECT kind, at, content FROM received WHERE peer = ? AND kind IN ({','.join('?' * len(kinds))}) "
            "ORDER BY id DESC LIMIT ?", (peer, *kinds, limit)).fetchall()
        return [{"kind": k, "at": at, "content": json.loads(c)} for k, at, c in rows]

    def purge(self, now: float | None = None, peer: str | None = None) -> None:
        db = self.db()
        if peer is not None:
            db.execute("DELETE FROM received WHERE peer = ?", (peer,))
        db.execute("DELETE FROM received WHERE at < ?", ((now or time.time()) - KEEP_DAYS * 86400,))
        db.commit()

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
