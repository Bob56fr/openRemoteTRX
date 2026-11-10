# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fichiers du module de présence, dans `state_dir/presence/` (écrits par le module seul).

- `presence.json` (droits 0600 : il contient les CLÉS DES GROUPES) : profil (pseudo, textes prédéfinis, plages
  « Au shack »), enregistrement auprès du relais, groupes (rôle, liste signée, clés, partage, jetons d'invitation,
  derniers états reçus des membres) ;
- `stats.json` : statistiques agrégées par jour pour les groupes dont la station est administratrice (§ 11 du cahier),
  6 mois au plus ;
- `status.json` (0644) : résumé SANS clé ni état reçu, lu par TRX Console et trx-monitor.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ..status import replace_atomic

log = logging.getLogger("trx.presence")

STATE_FILE = "presence.json"
STATS_FILE = "stats.json"
STATUS_FILE = "status.json"
FORMAT = 1


def default_data() -> dict:
    return {"format": FORMAT, "registered": False, "pseudo": "", "texts": [],
            "shack": {"rules": [], "suspended_until": None, "once": None}, "groups": {}}


def write_json(path: Path, obj: dict, *, private: bool) -> None:
    """Écriture atomique ; `private` : droits 0600 dès la création (clés), sinon 0644."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    replace_atomic(tmp, path)
    if not private:
        try:
            os.chmod(path, 0o644)
        except OSError:
            pass


def read_json(path: Path) -> dict | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.error("%s illisible (%s) : mis de côté, repart de zéro", path, exc)
        try:
            os.replace(path, path.with_name(path.name + ".illisible"))
        except OSError:
            pass
        return None
    return obj if isinstance(obj, dict) else None


class Store:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        data = read_json(self.folder / STATE_FILE)
        if data is None or data.get("format") != FORMAT:
            data = default_data()
        base = default_data()
        base.update(data)
        self.data = base
        self.stats = read_json(self.folder / STATS_FILE) or {}

    @property
    def groups(self) -> dict[str, dict]:
        return self.data["groups"]

    def save(self) -> None:
        write_json(self.folder / STATE_FILE, self.data, private=True)
        write_json(self.folder / STATS_FILE, self.stats, private=True)

    def write_status(self, status: dict) -> None:
        try:
            write_json(self.folder / STATUS_FILE, status, private=False)
        except OSError as exc:
            log.warning("état %s non écrit : %s", self.folder / STATUS_FILE, exc)
