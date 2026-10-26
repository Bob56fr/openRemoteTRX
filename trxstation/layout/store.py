"""Stockage des profils sur la STATION (à côté des mémoires), un profil actif par identifiant de connexion.

  * Un profil n'est enregistré qu'après validation complète ; la version précédente est conservée
    (`<id>.prev.json`) pour revenir en arrière.
  * Sans profil enregistré, ou si le fichier est illisible ou n'est plus valide, la station sert le
    PROFIL D'USINE : un utilisateur n'est jamais bloqué. Un fichier invalide est mis de côté (`.corrupt`).
  * Écriture atomique : un arrêt brutal ne laisse jamais un profil à moitié écrit.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from .factory import factory_profile
from .validate import Report, validate_profile

log = logging.getLogger(__name__)

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")        # même règle que [[clients]] id dans station.toml


class LayoutInvalid(ValueError):
    def __init__(self, report: Report):
        self.report = report
        super().__init__("; ".join(report.errors[:3]) or "profil invalide")


class LayoutStorageError(OSError):
    """Écriture du profil impossible (disque plein, droits...)."""


class LayoutStore:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory else None
        self._memory: dict[str, dict] = {}                   # sans dossier (tests) : en mémoire seulement

    def _path(self, client_id: str, suffix: str = ".json") -> Path:
        if not isinstance(client_id, str) or not CLIENT_ID_RE.fullmatch(client_id):
            raise ValueError("identifiant de client invalide")
        assert self.directory is not None
        return self.directory / f"{client_id}{suffix}"

    # ------------------------------------------------------------------ lecture
    def get(self, client_id: str) -> tuple[dict, str]:
        """(profil, origine) : origine « user » (profil enregistré) ou « factory » (profil d'usine)."""
        if self.directory is None:
            stored = self._memory.get(client_id)
            return (json.loads(json.dumps(stored)), "user") if stored else (factory_profile(), "factory")
        path = self._path(client_id)
        if not path.exists():
            return factory_profile(), "factory"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            report = validate_profile(data)
            if not report.ok:
                raise ValueError(report.errors[0])
            return data, "user"
        except (OSError, ValueError) as exc:
            log.warning("profil de « %s » illisible ou invalide (%s) : copie conservée, profil d'usine servi", client_id, exc)
            with contextlib.suppress(OSError):
                os.replace(path, path.with_suffix(".corrupt"))
            return factory_profile(), "factory"

    # ------------------------------------------------------------------ écriture
    def save(self, client_id: str, profile, capabilities=None) -> Report:
        """Valide puis enregistre. Lève LayoutInvalid (rien n'est écrit) ou LayoutStorageError."""
        report = validate_profile(profile, capabilities)
        if not report.ok:
            raise LayoutInvalid(report)
        if self.directory is None:
            self._memory[client_id] = json.loads(json.dumps(profile))
            return report
        path = self._path(client_id)
        payload = json.dumps(profile, ensure_ascii=False, indent=1)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                os.replace(path, self._path(client_id, ".prev.json"))     # retour arrière possible
            self._write(path, payload)
        except OSError as exc:
            raise LayoutStorageError(f"profil non enregistré : {exc}") from exc
        return report

    def reset(self, client_id: str) -> None:
        """Retour au profil d'usine (le profil actuel devient la version précédente)."""
        if self.directory is None:
            self._memory.pop(client_id, None)
            return
        path = self._path(client_id)
        try:
            if path.exists():
                os.replace(path, self._path(client_id, ".prev.json"))
        except OSError as exc:
            raise LayoutStorageError(f"retour au profil d'usine impossible : {exc}") from exc

    def restore_previous(self, client_id: str) -> bool:
        """Remet la version précédente (échange avec l'actuelle). Faux s'il n'y en a pas."""
        if self.directory is None:
            return False
        path, prev = self._path(client_id), self._path(client_id, ".prev.json")
        if not prev.exists():
            return False
        try:
            data = json.loads(prev.read_text(encoding="utf-8"))
            if not validate_profile(data).ok:
                return False
            current = path.read_text(encoding="utf-8") if path.exists() else None
            self._write(path, json.dumps(data, ensure_ascii=False, indent=1))
            if current is None:
                prev.unlink()
            else:
                self._write(prev, current)
        except (OSError, ValueError) as exc:
            raise LayoutStorageError(f"retour à la version précédente impossible : {exc}") from exc
        return True

    @staticmethod
    def _write(path: Path, payload: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".layout-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
