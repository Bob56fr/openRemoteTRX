# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Bus d'événements de la valise de qualification (lot G1, docs/qualification-gui-cahier-des-charges.md).

`run_terrain` ne parle plus au terminal : il pose ses questions et écrit ses lignes sur ce bus. Le terminal n'est
qu'un CLIENT du bus (`KeyboardClient`) ; la page (lot G2) et l'API de pilotage (lot G3) en seront d'autres.

Événements (un par ligne dans `evenements.jsonl`, dossier de la session) : `question`, `reponse`, `refus`,
`ligne` (journal), `etat` (état d'un essai), `mesure`.

Questions TYPÉES : texte libre, oui / non, « c'est fait », MOT DE SÉCURITÉ.

SÉCURITÉ : les mots de sécurité (CHARGE, ANTENNE, EMETTRE) ne sont acceptés que d'un HUMAIN AU CLAVIER
(`HUMAN_SOURCES`). Une réponse d'une autre source (API de pilotage, Claude) est REFUSÉE et la question reste
ouverte : seul un humain peut y répondre (ou la laisser sans suite). Le bus ne juge pas le mot lui-même : l'appelant
le compare comme avant (`typed_emit`, `LOAD_WORD`…) ; un mot faux reste un refus de l'essai.
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

TEXT, YES_NO, DONE, WORD = "texte", "oui_non", "fait", "mot"
KINDS = frozenset({TEXT, YES_NO, DONE, WORD})
SAFETY_WORDS = frozenset({"CHARGE", "ANTENNE", "EMETTRE"})   # mots français ; ceux des langues s'y ajoutent à l'appel

SOURCE_KEYBOARD = "clavier"          # terminal : un humain tape la réponse
SOURCE_PILOT = "pilote"              # API de pilotage (lot G3) : jamais un mot de sécurité
HUMAN_SOURCES = frozenset({SOURCE_KEYBOARD})   # la fenêtre d'intervention de la page s'y ajoutera au lot G2

JOURNAL = "evenements.jsonl"


class RefusedAnswer(PermissionError):
    """Mot de sécurité fourni par une source qui n'est pas un humain au clavier."""


@dataclass
class Question:
    id: int
    kind: str
    prompt: str
    word: str | None = None          # mot demandé (WORD seulement), tel qu'affiché
    answer: str | None = None
    source: str | None = None
    done: threading.Event = field(default_factory=threading.Event, repr=False)


class Bus:
    """Questions, réponses et journal de la valise ; utilisable depuis plusieurs fils (asyncio.to_thread)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._ids = itertools.count(1)
        self._clients: list[Callable[[dict], None]] = []
        self._questions: dict[int, Question] = {}
        self._folder: Path | None = None
        self._pending: list[dict] = []   # événements d'avant le dossier de la session (question de reprise)

    # ------------------------------------------------------------------ clients et journal

    def subscribe(self, client: Callable[[dict], None]) -> None:
        self._clients.append(client)

    def attach(self, folder: Path) -> None:
        """Dossier de la session connu : l'historique y est écrit, y compris ce qui a précédé."""
        folder.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._folder = folder
            pending, self._pending = self._pending, []
            self._write(pending)

    def _write(self, events: list[dict]) -> None:
        if not events or self._folder is None:
            return
        with (self._folder / JOURNAL).open("a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def publish(self, type_: str, **fields) -> dict:
        with self._lock:
            event = {"n": next(self._seq), "t": dt.datetime.now().astimezone().isoformat(timespec="milliseconds"),
                     "type": type_, **fields}
            if self._folder is None:
                self._pending.append(event)
            else:
                self._write([event])
        for client in list(self._clients):
            client(event)                # un client clavier peut répondre ICI (même fil) : voir KeyboardClient
        return event

    # ------------------------------------------------------------------ ce qu'utilise la valise

    def out(self, text: str = "") -> None:
        self.publish("ligne", texte=str(text))

    def state(self, essai: str, etat: str, **fields) -> None:
        self.publish("etat", essai=essai, etat=etat, **fields)

    def measure(self, name: str, value, **fields) -> None:
        self.publish("mesure", nom=name, valeur=value, **fields)

    def question(self, prompt: str, kind: str = TEXT, *, word: str | None = None) -> str:
        """Pose une question et ATTEND la réponse (bloque le fil appelant, comme `input`)."""
        if kind not in KINDS:
            raise ValueError(f"type de question inconnu : {kind}")
        if kind == WORD and not word:
            raise ValueError("une question de mot de sécurité doit dire le mot demandé")
        q = Question(next(self._ids), kind, str(prompt), word)
        with self._lock:
            self._questions[q.id] = q
        try:
            self.publish("question", id=q.id, genre=kind, texte=q.prompt, **({"mot": word} if word else {}))
            q.done.wait()
        finally:
            with self._lock:
                self._questions.pop(q.id, None)
        return q.answer or ""

    def ask(self, prompt: str) -> str:
        """Même signature que `input` : question de texte libre."""
        return self.question(prompt, TEXT)

    def open_questions(self) -> list[Question]:
        with self._lock:
            return list(self._questions.values())

    def answer(self, question_id: int, text: str, *, source: str) -> None:
        """Réponse d'un client. Mot de sécurité d'une source non humaine : RefusedAnswer, question laissée ouverte."""
        with self._lock:
            q = self._questions.get(question_id)
        if q is None or q.done.is_set():
            raise KeyError(f"aucune question ouverte n°{question_id}")
        if q.kind == WORD and source not in HUMAN_SOURCES:
            self.publish("refus", id=q.id, source=source, raison="mot de sécurité réservé à un humain au clavier")
            raise RefusedAnswer(f"le mot {q.word} ne peut être tapé que par un humain au clavier")
        q.answer, q.source = str(text), source
        self.publish("reponse", id=q.id, source=source, texte=q.answer)
        q.done.set()


class KeyboardClient:
    """Le terminal, client du bus : affiche les lignes, répond aux questions par `input` (aucun changement visible)."""

    def __init__(self, bus: Bus, ask: Callable[[str], str] = input, out: Callable[[str], None] = print) -> None:
        self.bus, self._ask, self._out = bus, ask, out
        bus.subscribe(self)

    def __call__(self, event: dict) -> None:
        if event["type"] == "ligne":
            self._out(event["texte"])
        elif event["type"] == "question":
            # Ctrl+C / fin d'entrée : l'exception remonte jusqu'à la valise, comme avec `input`.
            self.bus.answer(event["id"], self._ask(event["texte"]), source=SOURCE_KEYBOARD)


def bus_of(ask) -> Bus | None:
    """Le bus derrière un `ask` (méthode liée d'un Bus), sinon None (outil lancé seul avec `input`)."""
    owner = getattr(ask, "__self__", None)
    return owner if isinstance(owner, Bus) else None


def ask_typed(ask: Callable[[str], str], prompt: str, kind: str = TEXT, *, word: str | None = None) -> str:
    """Question typée si `ask` vient d'un bus ; sinon un simple `ask(prompt)` (trx-hwtest lancé seul, tests)."""
    bus = bus_of(ask)
    if bus is None:
        return ask(prompt)
    return bus.question(prompt, kind, word=word)


def ask_word(ask: Callable[[str], str], prompt: str, word: str) -> str:
    """Mot de sécurité (CHARGE, ANTENNE, EMETTRE ou celui de la langue) : seulement d'un humain au clavier."""
    return ask_typed(ask, prompt, WORD, word=word)
