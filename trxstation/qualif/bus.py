# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Bus d'événements de la valise de qualification (lots G1 et G2a, docs/qualification-gui-cahier-des-charges.md).

`run_terrain` ne parle plus au terminal : il pose ses questions et écrit ses lignes sur ce bus. Le terminal n'est
qu'un CLIENT du bus (`KeyboardClient`, ou `DisplayClient` quand la page répond) ; la page de la valise
(`qualif/page/`, lot G2) en est un autre, l'API de pilotage (lot G3) en sera un troisième.

Événements (un par ligne dans `evenements.jsonl`, dossier de la session) : `question`, `reponse`, `refus`, `annule`,
`ligne` (journal), `statut` (bandeau de la page), `etat` (état d'un essai), `mesure`, `stop`.

Questions TYPÉES : texte libre, oui / non, « c'est fait », choix dans une liste, secret (mot de passe : jamais écrit
dans le journal), MOT DE SÉCURITÉ.

SÉCURITÉ : les mots de sécurité (CHARGE, ANTENNE, EMETTRE) ne sont acceptés que d'un HUMAIN AU CLAVIER
(`HUMAN_SOURCES` : le terminal, ou la fenêtre d'intervention de la page). Une réponse d'une autre source (route
ordinaire de la page, API de pilotage, Claude) est REFUSÉE et la question reste ouverte : seul un humain peut y
répondre (ou la laisser sans suite). Le bus ne juge pas le mot lui-même : l'appelant le compare comme avant
(`typed_emit`, `LOAD_WORD`…) ; un mot faux, ou vide (« Passer cet essai »), reste un refus de l'essai.

STOP (page) : `request_stop` interrompt le fil principal comme un Ctrl+C (les essais coupent leur émission dans leurs
`finally`, comme aujourd'hui) ; les questions encore ouvertes dans d'autres fils sont ensuite libérées par
`QuestionStopped` ; la valise reconnaît son STOP (`consume_stop`) et revient au menu.
"""
from __future__ import annotations

import _thread
import datetime as dt
import itertools
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

TEXT, YES_NO, DONE, CHOICE, SECRET, WORD = "texte", "oui_non", "fait", "choix", "secret", "mot"
KINDS = frozenset({TEXT, YES_NO, DONE, CHOICE, SECRET, WORD})
SAFETY_WORDS = frozenset({"CHARGE", "ANTENNE", "EMETTRE"})   # mots français ; ceux des langues s'y ajoutent à l'appel

SOURCE_KEYBOARD = "clavier"          # terminal : un humain tape la réponse
SOURCE_WINDOW = "fenetre"            # fenêtre d'intervention de la page : mot tapé au clavier (collage refusé)
SOURCE_PAGE = "page"                 # boutons et champs ordinaires de la page : jamais un mot de sécurité
SOURCE_PILOT = "pilote"              # API de pilotage (lot G3) : jamais un mot de sécurité
HUMAN_SOURCES = frozenset({SOURCE_KEYBOARD, SOURCE_WINDOW})

JOURNAL = "evenements.jsonl"
WAIT_SLICE_S = 0.25                  # attente d'une réponse par tranches : Ctrl+C et STOP passent sous Windows
RELEASE_AFTER_S = 0.5                # STOP : délai avant de libérer les questions des autres fils


class RefusedAnswer(PermissionError):
    """Mot de sécurité fourni par une source qui n'est pas un humain au clavier."""


class QuestionStopped(RuntimeError):
    """Question abandonnée par un STOP de la page (l'essai qui l'attendait est interrompu)."""


@dataclass
class Question:
    id: int
    kind: str
    prompt: str
    word: str | None = None          # mot demandé (WORD seulement), tel qu'affiché
    answer: str | None = None
    source: str | None = None
    stopped: bool = False
    done: threading.Event = field(default_factory=threading.Event, repr=False)


class Bus:
    """Questions, réponses et journal de la valise ; utilisable depuis plusieurs fils (asyncio.to_thread)."""

    def __init__(self, *, interrupt: Callable[[], None] = _thread.interrupt_main) -> None:
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._ids = itertools.count(1)
        self._clients: list[Callable[[dict], None]] = []
        self._questions: dict[int, Question] = {}
        self._folder: Path | None = None
        self._pending: list[dict] = []   # événements d'avant le dossier de la session (question de reprise)
        self._interrupt = interrupt
        self._stop_requested = False

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

    @property
    def folder(self) -> Path | None:
        return self._folder

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

    def status(self, **fields) -> None:
        self.publish("statut", **fields)

    def state(self, essai: str, etat: str, **fields) -> None:
        self.publish("etat", essai=essai, etat=etat, **fields)

    def measure(self, name: str, value, **fields) -> None:
        self.publish("mesure", nom=name, valeur=value, **fields)

    def question(self, prompt: str, kind: str = TEXT, *, word: str | None = None, family: str | None = None,
                 context: str | None = None, choices: list[dict] | None = None, role: str | None = None) -> str:
        """Pose une question et ATTEND la réponse (bloque le fil appelant, comme `input`).

        `family` (WORD) : CHARGE, ANTENNE ou EMETTRE (le mot affiché peut être celui d'une langue) ; `context` : ce
        qu'il faut faire, montré dans la fenêtre d'intervention ; `choices` (CHOICE) : [{"cle", "texte"?, "fait"?,
        "info"?}], la réponse est une clé (le terminal peut toujours taper autre chose, comme avant)."""
        if kind not in KINDS:
            raise ValueError(f"type de question inconnu : {kind}")
        if kind == WORD and not word:
            raise ValueError("une question de mot de sécurité doit dire le mot demandé")
        q = Question(next(self._ids), kind, str(prompt), word)
        with self._lock:
            if self._stop_requested:
                raise QuestionStopped("STOP demandé")
            self._questions[q.id] = q
        extra: dict = {}
        if word:
            extra.update(mot=word, famille=family or (word if word in SAFETY_WORDS else "EMETTRE"))
        if context:
            extra["contexte"] = str(context)
        if choices is not None:
            extra["choix"] = choices
        if role:
            extra["role"] = role                    # « menu » : le menu principal de la valise (tuiles de la page)
        try:
            self.publish("question", id=q.id, genre=kind, texte=q.prompt, **extra)
            while not q.done.wait(WAIT_SLICE_S):
                pass
        finally:
            with self._lock:
                self._questions.pop(q.id, None)
            if not q.done.is_set():                  # Ctrl+C ou STOP pendant l'attente : les clients l'oublient
                q.done.set()
                self.publish("annule", id=q.id)
        if q.stopped:
            raise QuestionStopped("STOP demandé")
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
        shown = "***" if q.kind == SECRET else q.answer       # un mot de passe n'entre jamais dans le journal
        self.publish("reponse", id=q.id, source=source, texte=shown)
        q.done.set()

    # ------------------------------------------------------------------ STOP de la page

    def request_stop(self, *, release_after: float = RELEASE_AFTER_S) -> None:
        """Arrête l'enchaînement : le fil principal reçoit un KeyboardInterrupt (comme Ctrl+C), puis les questions
        encore ouvertes dans les autres fils sont libérées (QuestionStopped). Ne coupe RIEN au poste : l'appelant a
        déjà envoyé « T 0 » (`stop_tx`)."""
        with self._lock:
            self._stop_requested = True
            waiting = list(self._questions.values())
        self.publish("stop")
        self._interrupt()

        def release() -> None:
            for q in waiting:
                if not q.done.is_set():
                    q.stopped = True
                    self.publish("annule", id=q.id)
                    q.done.set()
        timer = threading.Timer(release_after, release)
        timer.daemon = True
        timer.start()

    def consume_stop(self) -> bool:
        """Vrai (une fois) si le KeyboardInterrupt reçu vient du STOP de la page, et non d'un Ctrl+C."""
        with self._lock:
            requested, self._stop_requested = self._stop_requested, False
        return requested


class KeyboardClient:
    """Le terminal, client du bus : affiche les lignes, répond aux questions par `input` (aucun changement visible)."""

    def __init__(self, bus: Bus, ask: Callable[[str], str] = input, out: Callable[[str], None] = print,
                 secret: Callable[[str], str] | None = None) -> None:
        self.bus, self._ask, self._out, self._secret = bus, ask, out, secret
        bus.subscribe(self)

    def __call__(self, event: dict) -> None:
        if event["type"] == "ligne":
            self._out(event["texte"])
        elif event["type"] == "question":
            # Ctrl+C / fin d'entrée : l'exception remonte jusqu'à la valise, comme avec `input`.
            ask = self._ask
            if event["genre"] == SECRET:
                ask = self._secret or _terminal_secret
            self.bus.answer(event["id"], ask(event["texte"]), source=SOURCE_KEYBOARD)


def _terminal_secret(prompt: str) -> str:
    """Mot de passe au terminal : champ masqué de la console web (menu 8.3 dans la page), sinon getpass."""
    from .. import formhint
    if formhint.enabled():
        formhint.emit("password", prompt.strip(), prompt)
        return input(prompt)
    import getpass
    return getpass.getpass(prompt)


class DisplayClient:
    """Le terminal quand la PAGE répond : il affiche le journal et les questions, il ne répond à rien."""

    def __init__(self, bus: Bus, out: Callable[[str], None] = print, mark: str = "[page] ") -> None:
        self._out, self._mark = out, mark
        bus.subscribe(self)

    def __call__(self, event: dict) -> None:
        if event["type"] == "ligne":
            self._out(event["texte"])
        elif event["type"] == "question":
            self._out(self._mark + event["texte"].strip())


def bus_of(ask) -> Bus | None:
    """Le bus derrière un `ask` (méthode liée d'un Bus), sinon None (outil lancé seul avec `input`)."""
    owner = getattr(ask, "__self__", None)
    return owner if isinstance(owner, Bus) else None


def ask_typed(ask: Callable[[str], str], prompt: str, kind: str = TEXT, **fields) -> str:
    """Question typée si `ask` vient d'un bus ; sinon un simple `ask(prompt)` (trx-hwtest lancé seul, tests)."""
    bus = bus_of(ask)
    if bus is None:
        return ask(prompt)
    return bus.question(prompt, kind, **fields)


def ask_word(ask: Callable[[str], str], prompt: str, word: str, *, family: str | None = None,
             context: str | None = None) -> str:
    """Mot de sécurité (CHARGE, ANTENNE, EMETTRE ou celui de la langue) : seulement d'un humain au clavier."""
    return ask_typed(ask, prompt, WORD, word=word, family=family, context=context)
