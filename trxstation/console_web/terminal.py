# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Pseudo-terminal où tourne la console texte, pour la page : même comportement sous Debian (pty de la bibliothèque
standard) et sous Windows (ConPTY par pywinpty) : décision de l'utilisateur, un seul écran à expliquer par téléphone.

Un vrai terminal est nécessaire : sudo demande le mot de passe sur le terminal de contrôle, nano et l'essai du poste
dessinent l'écran. La sortie est rendue au serveur par `on_output(texte)` (UTF-8 décodé au fil de l'eau) ; un fil
de lecture ne programme jamais plus d'un envoi à la fois vers la boucle (piège de l'étape 44).
"""
from __future__ import annotations

import asyncio
import codecs
import os
import sys
import threading
from collections.abc import Callable

IDLE_MARK = "\x1b]777;trx-idle\x07"     # séquence OSC écrite par la console quand elle attend au menu (invisible)


class Terminal:
    """Interface commune : start, write, resize, close ; `on_output` reçoit le texte produit."""

    def __init__(self, cmd: list[str], env: dict[str, str], on_output: Callable[[str], None],
                 on_exit: Callable[[], None], rows: int = 30, cols: int = 110):
        self.cmd, self.env, self.on_output, self.on_exit = cmd, env, on_output, on_exit
        self.rows, self.cols = rows, cols
        self.alive = False

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        raise NotImplementedError

    def write(self, data: str) -> None:
        raise NotImplementedError

    def resize(self, rows: int, cols: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class PosixTerminal(Terminal):
    """Debian, Pi : pty.fork (session et terminal de contrôle à lui : sudo y lit le mot de passe)."""

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        import pty
        self.loop = loop
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pid, fd = pty.fork()
        if pid == 0:                                     # enfant : la console texte
            try:
                os.execvpe(self.cmd[0], self.cmd, self.env)
            finally:
                os._exit(127)
        self.pid, self.fd, self.alive = pid, fd, True
        self.resize(self.rows, self.cols)
        loop.add_reader(fd, self._readable)

    def _readable(self) -> None:
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._ended()
            return
        self.on_output(self.decoder.decode(data))

    def _ended(self) -> None:
        if not self.alive:
            return
        self.alive = False
        try:
            self.loop.remove_reader(self.fd)
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except OSError:
            pass
        self.on_exit()

    def write(self, data: str) -> None:
        if self.alive:
            try:
                os.write(self.fd, data.encode("utf-8"))
            except OSError:
                self._ended()

    def resize(self, rows: int, cols: int) -> None:
        import fcntl
        import struct
        import termios
        self.rows, self.cols = rows, cols
        if self.alive:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self) -> None:
        if self.alive:
            import signal
            try:
                os.kill(self.pid, signal.SIGHUP)
            except OSError:
                pass
            self._ended()


class WindowsTerminal(Terminal):
    """Windows : ConPTY par pywinpty ; lecture dans un fil, un seul envoi en attente vers la boucle à la fois."""

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        from winpty import PtyProcess
        self.loop = loop
        self.proc = PtyProcess.spawn(self.cmd, env=self.env, dimensions=(self.rows, self.cols))
        self.alive = True
        self._pending: list[str] = []
        self._lock = threading.Lock()
        self._scheduled = False
        threading.Thread(target=self._reader, daemon=True, name="console-web-pty").start()

    def _reader(self) -> None:
        while True:
            try:
                data = self.proc.read(65536)
            except EOFError:
                break
            except Exception:                            # fermé pendant la lecture
                break
            if not data:
                if not self.proc.isalive():
                    break
                continue
            with self._lock:
                self._pending.append(data)
                if self._scheduled:
                    continue
                self._scheduled = True
            self.loop.call_soon_threadsafe(self._flush)
        self.loop.call_soon_threadsafe(self._ended)

    def _flush(self) -> None:
        with self._lock:
            text, self._pending, self._scheduled = "".join(self._pending), [], False
        if text:
            self.on_output(text)

    def _ended(self) -> None:
        self._flush()
        if self.alive:
            self.alive = False
            self.on_exit()

    def write(self, data: str) -> None:
        if self.alive:
            try:
                self.proc.write(data)
            except Exception:
                self._ended()

    def resize(self, rows: int, cols: int) -> None:
        self.rows, self.cols = rows, cols
        if self.alive:
            try:
                self.proc.setwinsize(rows, cols)
            except Exception:
                pass

    def close(self) -> None:
        if self.alive:
            try:
                self.proc.terminate(force=True)
            except Exception:
                pass


def make_terminal(*args, **kwargs) -> Terminal:
    return (WindowsTerminal if sys.platform == "win32" else PosixTerminal)(*args, **kwargs)
