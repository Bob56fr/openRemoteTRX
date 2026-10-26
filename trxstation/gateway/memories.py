"""Mémoires de fréquence et de mode, enregistrées sur la STATION et partagées entre tous les clients
(téléphone, voiture, navigateur) : une mémoire créée sur l'un apparaît tout de suite sur les autres.

Ordre d'affichage : les FAVORITES d'abord, puis par fréquence croissante (le mode est indiqué à côté).
Le fichier est un petit JSON écrit de façon atomique ; un fichier illisible n'empêche jamais de démarrer.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import secrets
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MAX_ITEMS = 200
MAX_NAME = 40
MODE_RE = re.compile(r"^[A-Za-z0-9\-]{1,16}$")
ID_RE = re.compile(r"^[a-z0-9]{1,16}$")


class MemoryStoreError(OSError):
    """Écriture du fichier de mémoires impossible (disque plein, droits...)."""


@dataclass(frozen=True)
class Memory:
    id: str
    name: str
    hz: int
    mode: str
    favorite: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def validate_fields(name, hz, mode, favorite) -> tuple[str, int, str, bool]:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME or not name.strip().isprintable():
        raise ValueError(f"nom invalide (1 à {MAX_NAME} caractères imprimables)")
    if isinstance(hz, bool) or not isinstance(hz, int) or not 1 <= hz <= 10_000_000_000:
        raise ValueError("fréquence invalide (entier en Hz)")
    if not isinstance(mode, str) or not MODE_RE.fullmatch(mode):
        raise ValueError("mode invalide")
    if not isinstance(favorite, bool):
        raise ValueError("favori : vrai ou faux attendu")
    return name.strip(), hz, mode, favorite


class MemoryStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._items: dict[str, Memory] = {}
        self._listeners: list[Callable[[list[dict]], None]] = []
        self._load()

    # ------------------------------------------------------------------ lecture

    def list(self) -> list[dict]:
        ordered = sorted(self._items.values(), key=lambda m: (not m.favorite, m.hz, m.name.lower()))
        return [m.to_dict() for m in ordered]

    def get(self, memory_id: str) -> Memory | None:
        return self._items.get(memory_id)

    def add_listener(self, callback: Callable[[list[dict]], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[list[dict]], None]) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(callback)

    # ------------------------------------------------------------------ écriture

    def save(self, *, name, hz, mode, favorite=False, memory_id: str | None = None) -> Memory:
        """Crée une mémoire (identifiant généré) ou met à jour celle dont on donne l'identifiant."""
        name, hz, mode, favorite = validate_fields(name, hz, mode, favorite)
        if memory_id is not None:
            if memory_id not in self._items:
                raise ValueError("mémoire inconnue")
        else:
            if len(self._items) >= MAX_ITEMS:
                raise ValueError(f"{MAX_ITEMS} mémoires au maximum")
            memory_id = secrets.token_hex(4)
            while memory_id in self._items:
                memory_id = secrets.token_hex(4)
        previous = dict(self._items)
        memory = Memory(memory_id, name, hz, mode, favorite)
        self._items[memory_id] = memory
        self._commit(previous)
        return memory

    def delete(self, memory_id: str) -> bool:
        if memory_id not in self._items:
            return False
        previous = dict(self._items)
        del self._items[memory_id]
        self._commit(previous)
        return True

    # ------------------------------------------------------------------ fichier

    def _commit(self, previous: dict[str, Memory]) -> None:
        try:
            self._persist()
        except OSError as exc:
            self._items = previous                                  # rien n'est annoncé qui n'ait été enregistré
            raise MemoryStoreError(f"mémoires non enregistrées : {exc}") from exc
        items = self.list()
        for callback in list(self._listeners):
            try:
                callback(items)
            except Exception:
                log.exception("écouteur de mémoires en erreur")

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "items": self.list()}, ensure_ascii=False, indent=1)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".mem-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for raw in data["items"][:MAX_ITEMS]:
                name, hz, mode, favorite = validate_fields(raw["name"], raw["hz"], raw["mode"], raw.get("favorite", False))
                if isinstance(raw["id"], str) and ID_RE.fullmatch(raw["id"]):
                    self._items[raw["id"]] = Memory(raw["id"], name, hz, mode, favorite)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("fichier de mémoires illisible (%s) : copie conservée, démarrage avec une liste vide", exc)
            self._items.clear()
            with contextlib.suppress(OSError):
                os.replace(self.path, self.path.with_suffix(self.path.suffix + ".corrupt"))
