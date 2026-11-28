# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Côté opérateur aidé : la console relancée dans un pseudo-terminal, son écran envoyé au relais (Linux seulement).

L'opérateur voit et tape comme d'habitude ; ce qui s'affiche est AUSSI envoyé, chiffré, environ 3 fois par seconde.
L'aidant ne peut RIEN envoyer : aucune touche ne remonte (lecture seule). Ctrl+] arrête le partage (la console
continue) ; la fin de la console, ou 2 h (le relais refuse ensuite), arrête tout.

`Uploader` (fil d'envoi) ne touche pas au terminal : il est essayé seul, avec un faux relais.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from . import calc
from .relay import RelayRefused, RelayUnavailable

STOP_KEY = b"\x1d"                 # Ctrl+]
INTERVAL_S = 0.3
HEARTBEAT_S = 2.0                  # image vide : l'opérateur apprend qu'on le regarde, l'aidant que le partage vit
RETRY_S = 3.0
MAX_PENDING = 256 * 1024           # au-delà (relais injoignable), on renverra l'écran complet
ENV_SHARED = "TRX_SCREEN_SHARED"   # posée pour la console partagée : ligne d'en-tête, pas de partage imbriqué


def relay_host(relay_url: str) -> str:
    return urlsplit(relay_url).netloc or relay_url


class Uploader:
    """Envoie la bande de l'écran. États : `ok`, `interrupted` (relais injoignable, nouvel essai), `stopped`
    (`stop_reason` : you, ended, forbidden, unknown_session, quota, error)."""

    def __init__(self, relay, keys: calc.ScreenKeys, *, clock: Callable[[], float] = time.monotonic,
                 interval: float = INTERVAL_S, heartbeat: float = HEARTBEAT_S) -> None:
        self.relay, self.keys, self.clock = relay, keys, clock
        self.interval, self.heartbeat = interval, heartbeat
        self.tape = calc.Tape()
        self.pending = bytearray()
        self.cols, self.rows = 80, 24
        self.seq = 0
        self.need_key = True
        self.sharing = True
        self.state = "ok"
        self.stop_reason: str | None = None
        self.watching = False
        self.nudge = threading.Event()               # l'aidant demande un écran complet : faire redessiner la console
        self.last_put = float("-inf")
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- entrées (fil du terminal)
    def feed(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self.tape.feed(data)
            if not self.need_key:
                self.pending += data
                if len(self.pending) > MAX_PENDING:
                    self.pending.clear()
                    self.need_key = True

    def resize(self, cols: int, rows: int) -> None:
        with self._lock:
            self.cols, self.rows = cols, rows

    # ---------------------------------------------------------------- un tour d'envoi
    def _chunks(self) -> list[tuple[int, bytes]]:
        with self._lock:
            if self.need_key:
                data, first = self.tape.keyframe(), calc.KIND_KEYFRAME
                self.need_key = False
                self.pending.clear()
            elif self.pending:
                data, first = bytes(self.pending), calc.KIND_OUTPUT
                self.pending.clear()
            elif self.clock() - self.last_put >= self.heartbeat:
                return [(calc.KIND_OUTPUT, b"")]
            else:
                return []
        parts = [data[i:i + calc.MAX_DATA] for i in range(0, len(data), calc.MAX_DATA)] or [b""]
        return [(first if i == 0 else calc.KIND_OUTPUT, part) for i, part in enumerate(parts)]

    def step(self) -> None:
        if not self.sharing:
            return
        for kind, data in self._chunks():
            self.seq += 1
            box = calc.seal_frame(self.keys, self.seq, kind, self.cols, self.rows, data)
            try:
                reply = self.relay.call("put", {"a": self.keys.address, "w": self.keys.write_token, "s": self.seq,
                                                "d": box})
            except RelayUnavailable:
                self.state = "interrupted"
                with self._lock:
                    self.need_key = True                 # ce qui n'est pas passé sera dans l'écran complet suivant
                return
            except RelayRefused as exc:
                if exc.reason == "sequence":             # réponse perdue alors que l'image était passée
                    last = exc.reply.get("last")
                    if isinstance(last, int) and last >= self.seq:
                        self.seq = last
                    with self._lock:
                        self.need_key = True
                    return
                self._stopped(exc.reason if exc.reason in ("ended", "forbidden", "unknown_session", "quota")
                              else "error")
                return
            self.state = "ok"
            self.last_put = self.clock()
            self.watching = bool(reply.get("watching"))
            if reply.get("refresh"):
                with self._lock:
                    self.need_key = True
                self.nudge.set()

    def _stopped(self, reason: str) -> None:
        self.sharing = False
        self.state = "stopped"
        self.stop_reason = reason
        self.watching = False

    # ---------------------------------------------------------------- fil
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="screen-upload", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self.sharing:
            try:
                self.step()
            except Exception:                            # jamais d'arrêt de la console pour une erreur d'envoi
                self._stopped("error")
                break
            self._wake.wait(RETRY_S if self.state == "interrupted" else self.interval)
            self._wake.clear()

    def stop(self, reason: str = "you", *, close: bool = True) -> None:
        was = self.sharing
        if was:
            self._stopped(reason)
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(10)
        if close and (was or reason == "you"):
            try:
                self.relay.call("close", {"a": self.keys.address, "w": self.keys.write_token})
            except (RelayRefused, RelayUnavailable):
                pass                                     # le relais efface la session après 2 h de toute façon


# ==================================================================== terminal (Linux)
def _write_all(fd: int, data: bytes) -> None:
    while data:
        try:
            n = os.write(fd, data)
        except InterruptedError:
            continue
        data = data[n:]


def _title(fd: int, text: str) -> None:
    """Titre de la fenêtre du terminal : l'état du partage s'y lit sans abîmer l'écran de la console."""
    _write_all(fd, b"\x1b]0;" + text.replace("\x07", "").encode("utf-8", "replace") + b"\x07")


def open_session(relay, t, relay_url: str, out: Callable[[str], None]):
    """Code tiré au hasard, session ouverte sur le relais. (code, clés) ou None (message déjà écrit)."""
    code = calc.new_code()
    keys = calc.derive(code)
    try:
        relay.call("open", {"a": keys.address, "h": keys.write_hash})
    except RelayUnavailable as exc:
        out(t("screen_share.relay_down", relay=relay_host(relay_url), detail=str(exc)))
        return None
    except RelayRefused as exc:
        out(t("screen_share.refused", relay=relay_host(relay_url), reason=exc.reason))
        return None
    return code, keys


def run_share(child_argv: list[str], *, t, relay_url: str, version: str = "", stdin: int = 0, stdout: int = 1,
              ask_start: bool = True, relay=None) -> int:
    """Partage complet (Linux) : ouvre la session, montre le code, lance `child_argv` dans un pseudo-terminal et
    recopie son écran. Code de sortie de la console partagée (1 si le partage n'a pas pu commencer)."""
    import fcntl
    import pty
    import select
    import signal
    import struct
    import termios
    import tty

    def say(text: str, raw: bool = False) -> None:
        """Terminal normal : le pilote ajoute « \\r » ; terminal brut (pendant le partage) : à ajouter soi-même."""
        text = text.replace("\r\n", "\n") + "\n"
        _write_all(stdout, (text.replace("\n", "\r\n") if raw else text).encode("utf-8", "replace"))

    if os.environ.get(ENV_SHARED):
        say(t("screen_share.already"))
        return 1
    from .relay import ScreenRelay
    relay = relay or ScreenRelay(relay_url, version=version)
    try:
        opened = open_session(relay, t, relay_url, say)
        if opened is None:
            return 1
        code, keys = opened
        say(t("screen_share.started", code=calc.display_code(code), relay=relay_host(relay_url)))
        if ask_start:
            say(t("screen_share.press_enter"))
            try:
                line = sys.stdin.readline() if stdin == 0 else os.read(stdin, 1024).decode("utf-8", "replace")
            except KeyboardInterrupt:
                line = "0"
            if line.strip() in ("0", "q", "Q"):
                Uploader(relay, keys).stop("you")
                say(t("screen_share.cancelled"))
                return 1

        def size() -> tuple[int, int]:
            try:
                rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(stdin, termios.TIOCGWINSZ, b"\0" * 8))
                if rows and cols:
                    return cols, rows
            except OSError:
                pass
            return 80, 24

        def set_size(fd: int, cols: int, rows: int) -> None:
            try:
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            except OSError:
                pass

        env = dict(os.environ, **{ENV_SHARED: "1"})
        pid, master = pty.fork()
        if pid == 0:                                         # enfant : la console partagée
            try:
                os.execvpe(child_argv[0], child_argv, env)
            finally:
                os._exit(127)
        cols, rows = size()
        set_size(master, cols, rows)
        uploader = Uploader(relay, keys)
        uploader.resize(cols, rows)
        uploader.start()
        winch = threading.Event()
        old_handler = signal.signal(signal.SIGWINCH, lambda *_: winch.set())
        saved = termios.tcgetattr(stdin) if os.isatty(stdin) else None
        if saved is not None:
            tty.setraw(stdin)
        shown = None
        reading_stdin = True
        try:
            while True:
                state = (uploader.state, uploader.watching, uploader.stop_reason)
                if state != shown:
                    if uploader.state == "stopped" and (shown is None or shown[0] != "stopped"):
                        say("\n" + t(f"screen_share.stopped.{uploader.stop_reason or 'error'}"), raw=saved is not None)
                        uploader.nudge.set()
                    _title(stdout, t("screen_share.title." + ("stopped" if uploader.state == "stopped" else
                                                              "interrupted" if uploader.state == "interrupted" else
                                                              "watching" if uploader.watching else "waiting"),
                                     code=calc.display_code(code)))
                    shown = state
                if winch.is_set():
                    winch.clear()
                    cols, rows = size()
                    set_size(master, cols, rows)
                    uploader.resize(cols, rows)
                if uploader.nudge.is_set():                  # faire redessiner l'écran plein (Textual)
                    uploader.nudge.clear()
                    set_size(master, cols, max(1, rows - 1))
                    time.sleep(0.05)
                    set_size(master, cols, rows)
                watch = [master] + ([stdin] if reading_stdin else [])
                try:
                    ready, _, _ = select.select(watch, [], [], 0.25)
                except InterruptedError:
                    continue
                if master in ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:                          # EIO : la console partagée est terminée
                        break
                    if not data:
                        break
                    _write_all(stdout, data)
                    if uploader.sharing:
                        uploader.feed(data)
                if stdin in ready:
                    data = os.read(stdin, 4096)
                    if not data:
                        reading_stdin = False
                        continue
                    if STOP_KEY in data:
                        data = data.replace(STOP_KEY, b"")
                        if uploader.sharing:
                            uploader.stop("you")
                    if data:
                        _write_all(master, data)
        finally:
            if saved is not None:
                termios.tcsetattr(stdin, termios.TCSAFLUSH, saved)
            signal.signal(signal.SIGWINCH, old_handler)
            _title(stdout, "")
            uploader.stop("you")
            try:
                os.close(master)
            except OSError:
                pass
            try:
                _, status = os.waitpid(pid, 0)
                exit_code = os.waitstatus_to_exitcode(status)
            except ChildProcessError:
                exit_code = 0
        say(t("screen_share.ended"))
        return exit_code if exit_code >= 0 else 1
    finally:
        relay.close()
