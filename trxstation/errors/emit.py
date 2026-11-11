# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Émission d'un événement du catalogue d'erreurs : `emit_event(codes.ORT_2104, commande="f", delai_ms=2000)`.

Chaque événement porte le code, la gravité et un dictionnaire de contexte (valeurs mesurées, module, port…) ;
il est journalisé au niveau qui correspond à sa gravité, avec l'événement complet dans `record.event`
(pour les journaux JSON et le monitor inter-stations), puis remis aux abonnés (`add_sink`).

Règles de sécurité : `emit_event` ne lève JAMAIS d'exception (la passerelle ne doit pas quitter sur une erreur
de journalisation) ; un code inconnu, une variable manquante ou un abonné en panne sont tolérés. Le catalogue est
lu dans `catalog.json` (fabriqué par scripts/build_errors.py), avec la stdlib seulement.
"""
from __future__ import annotations

import json
import logging
import string
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

CATALOG_JSON = Path(__file__).with_name("catalog.json")
LEVELS = {"info": logging.INFO, "avertissement": logging.WARNING, "erreur": logging.ERROR, "critique": logging.CRITICAL}
LANGS = ("fr", "en")
UNKNOWN_TITLE = {"fr": "Code d'erreur absent du catalogue", "en": "Error code missing from the catalogue"}

log = logging.getLogger("trxstation.errors")
_lock = threading.Lock()
_catalog: dict[str, dict] | None = None
_sinks: list[Callable[["ErrorEvent"], None]] = []


@dataclass(frozen=True)
class ErrorEvent:
    """Un événement émis : ce qui part vers le journal, ntfy, le monitor."""
    code: str
    gravite: str
    titre: str
    message: str
    contexte: dict[str, Any] = field(default_factory=dict)
    module: str = "ORT"
    horodatage: float = 0.0
    connu: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "gravite": self.gravite, "titre": self.titre, "message": self.message,
                "contexte": dict(self.contexte), "module": self.module, "horodatage": self.horodatage,
                "connu": self.connu}


class _Keep(dict):
    """Variable absente du contexte : laissée telle quelle ({nom}) plutôt qu'une exception."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format(template: str, contexte: dict[str, Any]) -> str:
    try:
        return string.Formatter().vformat(template, (), _Keep(contexte))
    except (ValueError, IndexError, AttributeError, KeyError, TypeError):
        return template                                # gabarit ou valeur inattendus : le texte brut suffit


def catalog() -> dict[str, dict]:
    """Catalogue chargé une fois (dictionnaire vide si catalog.json manque : la station continue)."""
    global _catalog
    with _lock:
        if _catalog is None:
            try:
                data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
                _catalog = dict(data["codes"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.error("catalogue d'erreurs illisible (%s) : événements sans texte", exc)
                _catalog = {}
        return _catalog


def entry(code: str) -> dict | None:
    return catalog().get(code)


def by_machine(name: str) -> str | None:
    """Premier code en service dont `codes_machine` contient `name` (raison de coupure, type de problème…)."""
    for code, e in catalog().items():
        if not e.get("deprecated") and name in (e.get("codes_machine") or ()):
            return code
    return None


def render(code: str, lang: str = "fr", **contexte: Any) -> tuple[str, str]:
    """(titre, message) du code dans la langue demandée, variables remplacées ; code inconnu = texte générique."""
    e = entry(code)
    lang = lang if lang in LANGS else "fr"
    if e is None:
        return UNKNOWN_TITLE[lang], f"{code} {contexte}" if contexte else code
    texts = e if lang == "fr" else e.get("en", e)
    return texts["titre"], _format(texts["message"], contexte)


def add_sink(sink: Callable[[ErrorEvent], None]) -> None:
    """Abonne `sink` à tous les événements (monitor, ntfy…). Appelé dans le fil de l'émetteur : doit être rapide."""
    with _lock:
        _sinks.append(sink)


def remove_sink(sink: Callable[[ErrorEvent], None]) -> None:
    with _lock:
        if sink in _sinks:
            _sinks.remove(sink)


def emit_event(code: str, *, logger: logging.Logger | None = None, prefixe: str = "ORT",
               **contexte: Any) -> ErrorEvent:
    """Journalise et diffuse l'événement `code` ; renvoie l'événement. Ne lève jamais d'exception.

    `prefixe` : préfixe du module qui émet (registre modules.yaml), publié dans le champ `module` de l'événement ;
    ne pas confondre avec la variable `{module}` des messages ORT-65xx, passée dans le contexte.
    """
    try:
        e = entry(code)
        titre, message = render(code, **contexte)
        gravite = e["gravite"] if e else "erreur"
        event = ErrorEvent(code=code, gravite=gravite, titre=titre, message=message, contexte=dict(contexte),
                           module=prefixe, horodatage=time.time(), connu=e is not None)
    except Exception:                                  # filet ultime : jamais d'exception vers l'appelant
        event = ErrorEvent(code=str(code), gravite="erreur", titre=UNKNOWN_TITLE["fr"], message=str(code),
                           horodatage=time.time(), connu=False)
    publish(event, logger=logger)
    return event


def publish(event: ErrorEvent, *, logger: logging.Logger | None = None, prefix: str = "") -> None:
    """Journalise un événement déjà construit (au niveau de sa gravité) et le remet aux abonnés. Ne lève jamais.
    `prefix` : mot placé en tête de la ligne du journal (« ALERTE » pour une alerte ntfy)."""
    try:
        head = f"{prefix} " if prefix else ""
        (logger or log).log(LEVELS.get(event.gravite, logging.ERROR), "%s%s %s", head, event.code, event.message,
                            extra={"event": event.as_dict()})
    except Exception:
        pass
    with _lock:
        sinks = list(_sinks)
    for sink in sinks:
        try:
            sink(event)
        except Exception:                              # un abonné en panne n'arrête ni les autres ni l'appelant
            try:
                log.warning("abonné des événements en erreur : %r", sink, exc_info=True)
            except Exception:
                pass


def _reset_for_tests() -> None:
    global _catalog
    with _lock:
        _catalog = None
        _sinks.clear()
