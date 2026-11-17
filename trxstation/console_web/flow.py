# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Un menu ouvert en formulaires (étape 235) : le processus `worker` et ce que la page en a vu.

Le serveur garde la suite des messages (rejouée à une page qui se reconnecte), sans jamais y mettre un mot de passe :
une réponse à une question de mot de passe y figure masquée. Arrêter le menu tue le worker ET les commandes qu'il a
lancées (groupe de processus sous Debian, arbre de processus sous Windows).
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

MAX_EVENTS = 3000                 # messages gardés pour une page qui se reconnecte
MAX_LINE = 1 << 20                # une ligne du worker (sortie d'une commande découpée par 4 ko : large)


class Flow:
    def __init__(self, key: str, label: str, config: Path, on_event: Callable[[dict], None],
                 python: str = sys.executable) -> None:
        self.key, self.label, self.config, self.on_event, self.python = key, label, config, on_event, python
        self.events: list[dict] = []
        self.proc: asyncio.subprocess.Process | None = None
        self.done = False
        self.asking: dict | None = None             # question en attente de réponse
        self.tasks: list[asyncio.Task] = []

    @property
    def alive(self) -> bool:
        return not self.done

    def summary(self) -> dict:
        return {"key": self.key, "label": self.label, "done": self.done, "events": self.events}

    async def start(self) -> None:
        cmd = [self.python, "-m", "trxstation.console_web.worker", "--config", str(self.config), "--key", self.key]
        env = dict(os.environ, TRX_CONSOLE_WEB="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        extra: dict = {}
        if os.name == "posix":
            extra["start_new_session"] = True          # aucun terminal de contrôle : sudo et getpass n'y lisent rien
        else:
            extra["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, limit=MAX_LINE, **extra)
        self.tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._errors())]

    def record(self, event: dict) -> None:
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        self.on_event(event)

    async def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            while line := await self.proc.stdout.readline():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    continue
                if event["type"] == "form":
                    self.asking = event
                elif event["type"] in ("sudo", "sudo_ok", "sudo_bad"):
                    self.on_event(event)            # traité par le serveur, jamais rejoué
                    continue
                self.record(event)
        except (ValueError, asyncio.LimitOverrunError):
            pass
        await self.proc.wait()
        if not self.done:
            self.done = True
            if not any(e.get("type") == "done" for e in self.events[-3:]):
                self.record({"type": "done", "code": self.proc.returncode})
            self.asking = None

    async def _errors(self) -> None:
        """Erreurs du worker (avertissements Python, plantage) : montrées comme une sortie, jamais perdues."""
        assert self.proc is not None and self.proc.stderr is not None
        while chunk := await self.proc.stderr.read(4096):
            self.record({"type": "out", "data": chunk.decode("utf-8", "replace")})

    def _write(self, message: dict) -> None:
        if self.proc is None or self.proc.stdin is None or self.done:
            return
        try:
            self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        except (ConnectionError, RuntimeError, OSError):
            pass

    def answer(self, value: str, label: str = "") -> bool:
        """Réponse à la question en cours ; faux s'il n'y en a pas (double clic, page en retard)."""
        if self.asking is None:
            return False
        secret = self.asking.get("kind") == "password"
        self.asking = None
        self._write({"type": "answer", "value": value})
        shown = "••••••" if secret and value else (label or value)
        self.record({"type": "answered", "value": shown})
        return True

    def stdin(self, data: str) -> None:
        self._write({"type": "stdin", "data": data})
        self.record({"type": "typed", "data": data})

    def password(self, value: str) -> None:
        self._write({"type": "password", "value": value})

    def stop(self) -> None:
        proc = self.proc
        if proc is None or proc.returncode is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)    # le worker et ses commandes (sudo relaie à la sienne)
            else:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
