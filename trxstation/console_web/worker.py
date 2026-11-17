# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Un menu de TRX Console joué SANS terminal, pour la page (étape 235, lot W3a de la console web).

Processus enfant du serveur de la console web, un par menu ouvert : `python -m trxstation.console_web.worker
--config station.toml --key 4.3`. Il fait tourner le MÊME code que la console texte (aucun menu réécrit) en remplaçant
« dire » et « demander » par des messages JSON, une ligne par message :

  sortie (vers le serveur) : {"type": "say", "id", "text"}, {"type": "form", ...} (question à poser), {"type": "run",
      "cmd"} puis {"type": "out", "data"} et {"type": "end", "code"} (commande lancée par le menu), {"type": "sudo",
      "retry"} (mot de passe d'administration demandé), {"type": "done"} ;
  entrée (depuis le serveur) : {"type": "answer", "value"}, {"type": "stdin", "data"} (ligne pour la commande en
      cours), {"type": "password", "value"}.

La nature d'une question vient de `Console.hint` quand le menu la donne (oui/non, nombre et bornes, mot de passe, mot
de confirmation), sinon des lignes « 1) … » qui la précèdent et des « x = … » de l'invite. La page garde toujours une
réponse libre : une question mal reconnue ne bloque jamais.

sudo : le mot de passe est demandé UNE fois (le serveur le garde pour la session), vérifié par `sudo -k -S true`,
puis passé à chaque commande par `sudo -S -k` (toujours lu, jamais pris dans un cache : il ne peut pas tomber dans
l'entrée de la commande). Il ne passe jamais par la ligne de commande, l'environnement ni un fichier.
"""
from __future__ import annotations

import argparse
import codecs
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

from ..console import CONFIG_PATH, Console, Runner

SUDO_TRIES = 3
CHOICE_LINE = re.compile(r"^\s{1,8}([0-9]{1,2}|[a-zA-Z])\)\s+(\S.*)$")
# « r = retour », « Entrée = non », « - = abandon » dans l'invite (4 langues pour la touche Entrée)
PROMPT_PAIR = re.compile(r"(?:^|[(,;]\s*)(Entrée|Enter|Eingabe|Intro|[a-zA-Z0-9-]{1,3})\s*=\s*([^,;()]+)")
ENTER_WORDS = {"entrée", "enter", "eingabe", "intro"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class Channel:
    """Lignes JSON vers le serveur (sortie standard d'origine) ; un verrou : plusieurs fils écrivent."""

    def __init__(self, stream) -> None:
        self.stream, self.lock, self.next_id = stream, threading.Lock(), 0

    def send(self, message: dict) -> int:
        with self.lock:
            self.next_id += 1
            message.setdefault("id", self.next_id)
            self.stream.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.stream.flush()
            return message["id"]


class Inbox(threading.Thread):
    """Lit les messages du serveur : réponses et mot de passe dans leurs files, lignes pour la commande en cours."""

    def __init__(self, stream, runner: "WebRunner") -> None:
        super().__init__(name="trx-console-inbox", daemon=True)
        self.stream, self.runner = stream, runner
        self.answers: queue.Queue[str | None] = queue.Queue()
        self.passwords: queue.Queue[str | None] = queue.Queue()

    def run(self) -> None:
        for line in self.stream:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            kind, value = msg.get("type"), msg.get("value")
            if kind == "answer" and isinstance(value, str):
                self.answers.put(value[:4096])
            elif kind == "password" and isinstance(value, str):
                self.passwords.put(value[:256])
            elif kind == "stdin" and isinstance(msg.get("data"), str):
                self.runner.feed(msg["data"][:4096])
        self.answers.put(None)                     # serveur parti : la question en cours se termine (EOFError)
        self.passwords.put(None)


class Output(io.TextIOBase):
    """Ce qu'un menu écrit directement (print, sortie des tests) : montré comme la sortie d'une commande."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if text:
            self.channel.send({"type": "out", "data": ANSI.sub("", text)})
        return len(text)


class WebRunner(Runner):
    """Commandes lancées par un menu : sortie envoyée à la page au fil de l'eau, entrée fournie par la page."""

    def __init__(self, channel: Channel) -> None:
        super().__init__()
        self.channel = channel
        self.inbox: Inbox | None = None
        self.password: str | None = None
        self.child: subprocess.Popen | None = None
        self.lock = threading.Lock()
        # sudo : mot de passe lu sur l'entrée (-S), jamais le cache (-k), aucune invite (-p "") ; remplacé dans les tests
        self.sudo = ["sudo", "-S", "-k", "-p", "", "--"]
        self.use_sudo = os.name == "posix" and not self.is_root     # Windows : pas de sudo (comme la console texte)

    def feed(self, data: str) -> None:
        with self.lock:
            child = self.child
        if child is not None and child.stdin is not None:
            try:
                child.stdin.write(data.encode("utf-8"))
                child.stdin.flush()
            except (OSError, ValueError):
                pass

    def sudo_password(self) -> str | None:
        """Mot de passe d'administration vérifié, demandé au serveur (qui le garde pour la session) ; None = refusé."""
        if self.password is not None:
            return self.password
        assert self.inbox is not None
        for retry in range(SUDO_TRIES):
            self.channel.send({"type": "sudo", "retry": retry})
            password = self.inbox.passwords.get()
            if password is None:
                return None
            if password == "":
                return None                       # la page a renoncé
            try:
                ok = subprocess.run([*self.sudo, "true"], input=(password + "\n").encode(),
                                    capture_output=True, timeout=30).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
            if ok:
                self.password = password
                self.channel.send({"type": "sudo_ok"})
                return password
        self.channel.send({"type": "sudo_bad"})
        return None

    def run(self, cmd: list[str], *, admin: bool = False) -> int:
        first = b""
        if admin and self.use_sudo:
            password = self.sudo_password()
            if password is None:
                self.channel.send({"type": "out", "data": self.t("web.sudo_refused") + "\n"})
                return 1
            cmd, first = [*self.sudo, *cmd], (password + "\n").encode()
        self.channel.send({"type": "run", "cmd": Path(cmd[0]).name if cmd else ""})
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "TRX_CONSOLE_FORMS": "1"}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     env=env, creationflags=flags)
        except FileNotFoundError:
            self.channel.send({"type": "out", "data": self.t("runner.not_found", cmd=cmd[0]) + "\n"})
            self.channel.send({"type": "end", "code": 127})
            return 127
        with self.lock:
            self.child = child
        assert child.stdin is not None and child.stdout is not None
        if first:
            try:
                child.stdin.write(first)
                child.stdin.flush()
            except OSError:
                pass
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while chunk := child.stdout.read1(4096):
            text = ANSI.sub("", decoder.decode(chunk))
            if text:
                self.channel.send({"type": "out", "data": text})
        code = child.wait()
        with self.lock:
            self.child = None
        self.channel.send({"type": "end", "code": code})
        return code


def classify(prompt: str, said: list[tuple[int, str]], hint: dict | None) -> dict:
    """Question à poser dans la page : nature, choix, et messages juste avant qui ne sont que la liste des choix (la
    page les remplace par des boutons)."""
    # Invite sur plusieurs lignes (« 1) … 2) … Choix : ») : la dernière est la question, les autres comptent comme un
    # message dit juste avant (numéro 0 : il n'existe pas dans la page, son reste est envoyé dans « intro »).
    parts = prompt.strip("\n").split("\n")
    if len(parts) > 1:
        said = [*said, (0, "\n".join(parts[:-1]))]
        prompt = parts[-1]
    form: dict = {"type": "form", "prompt": prompt.strip(), "choices": [], "hide": [], "rewrite": []}
    if hint:
        form.update(hint)
    pairs = []
    for key, label in PROMPT_PAIR.findall(prompt):
        value = "" if key.lower() in ENTER_WORDS else key
        pairs.append([value, label.strip().rstrip(".:) ")])
    # Liste « 1) … » des derniers messages (bloc continu à la fin) ; un message qui finit par la liste est réécrit
    # sans elle (la page remplace les lignes de choix par des boutons).
    choices: list[list[str]] = []
    hide: list[int] = []
    rewrite: list[list] = []
    for ident, text in reversed(said):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            continue
        found = [CHOICE_LINE.match(ln) for ln in lines]
        if all(found):
            choices[:0] = [[m.group(1), m.group(2).strip()] for m in found if m]
            hide.append(ident)
            continue
        tail = []
        for m in reversed(found):
            if not m:
                break
            tail.insert(0, [m.group(1), m.group(2).strip()])
        if tail:
            choices[:0] = tail
            rewrite.append([ident, "\n".join(lines[: len(lines) - len(tail)])])
        break
    if "kind" not in form:
        form["kind"] = "choice" if choices else "text"
    if form["kind"] == "choice":
        form["choices"], form["hide"], form["rewrite"] = choices, hide, rewrite
    intro = next((text for ident, text in form["rewrite"] if ident == 0), None)
    if intro is None and len(parts) > 1 and 0 not in form["hide"]:
        intro = "\n".join(parts[:-1])
    if intro is not None:
        form["intro"] = intro.strip("\n")
    form["hide"] = [i for i in form["hide"] if i]
    form["rewrite"] = [r for r in form["rewrite"] if r[0]]
    known = {c[0] for c in form["choices"]}
    if form["kind"] in ("int", "yesno", "password", "word", "pause"):    # Entrée : déjà un bouton de la page
        pairs = [p for p in pairs if p[0]]
    form["extra"] = [p for p in pairs if p[0] not in known]
    return form


def find_item(con: Console, key: str):
    if key == "0":
        return con.language
    for number, _label, fn in con.items:
        if number == key:
            return fn
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-console-worker")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--key", required=True)
    args = ap.parse_args(argv)
    from ..i18n import load_lang, load_level, prefs_path

    proto = io.TextIOWrapper(os.fdopen(os.dup(sys.stdout.fileno()), "wb"), encoding="utf-8", line_buffering=True)
    channel = Channel(proto)
    sys.stdout = Output(channel)                      # un print d'un menu ne casse jamais le protocole
    runner = WebRunner(channel)
    inbox = Inbox(io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8"), runner)
    runner.inbox = inbox
    said: list[tuple[int, str]] = []
    con: Console

    def say(text: str) -> None:
        text = ANSI.sub("", str(text))
        said.append((channel.send({"type": "say", "text": text}), text))
        del said[:-40]

    def ask(prompt: str) -> str:
        hint, con.hint = con.hint, None
        form = classify(ANSI.sub("", prompt), said, hint)
        said.clear()
        channel.send(form)
        answer = inbox.answers.get()
        if answer is None:
            raise EOFError
        return answer

    con = Console(args.config, runner=runner, ask=ask, say=say, lang=load_lang(prefs_path()),
                  level=load_level(prefs_path(), args.config.exists()))
    fn = find_item(con, args.key)
    inbox.start()
    if fn is None:
        channel.send({"type": "done", "code": 2})
        return 2
    code = 0
    try:
        fn()
    except EOFError:
        code = 1
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:                          # un défaut d'un menu : dit dans la page, jamais un silence
        import traceback
        channel.send({"type": "out", "data": "".join(traceback.format_exception(exc))})
        code = 1
    channel.send({"type": "done", "code": code})
    return code


if __name__ == "__main__":
    # Fin immédiate : le fil qui lit l'entrée y reste bloqué ; une sortie normale attendrait son verrou (plantage de
    # l'interpréteur à l'arrêt). Tout a déjà été écrit (lignes vidées une à une).
    os._exit(main())
