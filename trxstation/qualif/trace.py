# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Relais TCP entre l'application et rigctld : enregistre toutes les trames et sait simuler une coupure.

Placé devant rigctld pendant la qualification, il fournit :
  - la trace CAT horodatée (preuve brute pour le rapport, et future matière du rejeu en non-régression) ;
  - l'exercice « perte de la liaison CAT pendant l'émission » : `interrupt()` ferme les connexions et
    refuse les nouvelles pendant quelques secondes, puis laisse l'application se reconnecter.

Il n'écoute QUE sur 127.0.0.1 (rigctld n'a aucune authentification).
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

MAX_RECORDS = 500_000          # environ 30 Mo de texte au pire : une qualification en produit bien moins


class TraceProxy:
    def __init__(self, target_host: str, target_port: int):
        self.target_host, self.target_port = target_host, target_port
        self.port = 0
        self.records: list[tuple[float, str, str]] = []     # (secondes depuis le début, sens, texte)
        self.truncated = False
        self._t0 = time.monotonic()
        self._server: asyncio.AbstractServer | None = None
        self._refuse_until = 0.0
        self._writers: set[asyncio.StreamWriter] = set()
        self._tasks: set[asyncio.Task] = set()

    def _log(self, direction: str, raw: bytes) -> None:
        if len(self.records) >= MAX_RECORDS:
            self.truncated = True
            return
        self.records.append((time.monotonic() - self._t0, direction, raw.decode(errors="replace").rstrip("\r\n")))

    def note(self, text: str) -> None:
        """Repère dans la trace (début d'un test, coupure simulée…)."""
        self._log("#", text.encode())

    async def start(self, port: int = 0) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        self._drop()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _drop(self) -> None:
        for writer in list(self._writers):
            writer.close()
        self._writers.clear()

    async def interrupt(self, seconds: float) -> None:
        """Coupe la liaison : connexions fermées, nouvelles refusées pendant `seconds`, puis rétablie."""
        self.note(f"COUPURE SIMULÉE {seconds:g} s")
        self._refuse_until = time.monotonic() + seconds
        self._drop()
        await asyncio.sleep(seconds)
        self.note("LIAISON RÉTABLIE")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if time.monotonic() < self._refuse_until:
            writer.close()
            return
        try:
            up_reader, up_writer = await asyncio.open_connection(self.target_host, self.target_port)
        except OSError as exc:
            self.note(f"rigctld injoignable : {exc!r}")
            writer.close()
            return
        self._writers.update((writer, up_writer))
        pumps = [asyncio.create_task(self._pump(reader, up_writer, ">")),
                 asyncio.create_task(self._pump(up_reader, writer, "<"))]
        self._tasks.update(pumps)
        try:
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in pumps:
                task.cancel()
                self._tasks.discard(task)
            for w in (writer, up_writer):
                self._writers.discard(w)
                w.close()

    async def _pump(self, src: asyncio.StreamReader, dst: asyncio.StreamWriter, direction: str) -> None:
        try:
            while True:
                raw = await src.readline()
                if not raw:
                    return
                self._log(direction, raw)
                dst.write(raw)
                await dst.drain()
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            return

    def render(self) -> str:
        lines = ["# Trace CAT : t (s) | sens (> vers rigctld, < réponse, # repère) | texte"]
        lines += [f"{t:12.6f} {d} {text}" for t, d, text in self.records]
        if self.truncated:
            lines.append(f"# TRACE TRONQUÉE à {MAX_RECORDS} lignes")
        return "\n".join(lines) + "\n"

    def write(self, path: Path) -> None:
        Path(path).write_text(self.render(), encoding="utf-8")
