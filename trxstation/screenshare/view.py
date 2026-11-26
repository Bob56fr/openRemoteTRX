# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Côté aidant : l'écran de la console d'un ami, en lecture seule, dans le terminal (Linux et Windows).

Les octets reçus sont écrits tels quels dans le terminal de l'aidant : la fenêtre doit être au moins aussi grande que
celle de l'ami (prévenu par le titre de la fenêtre). Rien n'est envoyé à l'ami : les touches ne servent qu'à
quitter (Ctrl+]) ou à redemander un écran complet (Ctrl+R).

`Viewer` (lecture des images) ne touche pas au terminal : il est essayé seul, avec un faux relais.
"""
from __future__ import annotations

import os
import shutil
import sys
import time

from . import calc
from .relay import RelayRefused, RelayUnavailable

QUIT_KEYS = ("\x1d", "\x03")       # Ctrl+], Ctrl+C
REFRESH_KEY = "\x12"               # Ctrl+R
POLL_S = 0.7
RETRY_S = 3.0
RESTORE = (b"\x1b[0m\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l\x1b[?2004l\x1b[?25h\x1b[?1049l"
           b"\x1b]0;\x07")


class Viewer:
    """Lit les images de la session. `ended` : None tant que le partage vit, sinon `closed` ou `expired`."""

    def __init__(self, relay, keys: calc.ScreenKeys) -> None:
        self.relay, self.keys = relay, keys
        self.after = 0
        self.last_seq: int | None = None
        self.synced = False                      # un écran complet a été appliqué depuis le dernier trou
        self.ended: str | None = None
        self.cols = self.rows = 0
        self.last_put = 0
        self.bad = 0                             # images illisibles (code faux ou relais qui triche)
        self.polled = False

    def poll(self, *, refresh: bool = False) -> list[bytes]:
        """Octets à écrire dans le terminal, dans l'ordre. Demande un écran complet tant qu'il n'est pas à jour."""
        out: list[bytes] = []
        while True:
            # Pas de demande au tout premier relevé : un écran complet récent est peut-être déjà chez le relais.
            reply = self.relay.call("get", {"a": self.keys.address, "after": self.after,
                                            "refresh": bool(refresh or (not self.synced and self.polled))})
            self.polled = True
            if reply.get("ended"):
                self.ended = str(reply.get("reason") or "closed")
                return out
            self.last_put = int(reply.get("last_put") or 0)
            for item in reply.get("frames") or []:
                if not isinstance(item, dict) or not isinstance(item.get("id"), int) or not isinstance(item.get("s"), int):
                    continue
                self.after = max(self.after, item["id"])
                try:
                    frame = calc.open_frame(self.keys, item["s"], item.get("d"))
                except calc.FrameRefused:
                    self.bad += 1
                    self.synced = False
                    continue
                gap = self.last_seq is not None and item["s"] != self.last_seq + 1
                self.last_seq = item["s"]
                self.cols, self.rows = frame.cols, frame.rows
                if frame.kind == calc.KIND_KEYFRAME:
                    self.synced = True
                    out.append(frame.data)
                elif gap:
                    self.synced = False              # images perdues : attendre le prochain écran complet
                elif self.synced and frame.data:
                    out.append(frame.data)
            if not reply.get("more"):
                return out
            refresh = False


# ==================================================================== terminal
class _Keys:
    """Lecture des touches sans écho ni attente (Linux : mode cbreak ; Windows : msvcrt)."""

    def __enter__(self) -> "_Keys":
        self.saved = None
        if os.name == "nt":
            import msvcrt
            self.msvcrt = msvcrt
        elif sys.stdin.isatty():
            import termios
            import tty
            self.saved = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
        return self

    def read(self) -> str:
        if os.name == "nt":
            keys = ""
            while self.msvcrt.kbhit():
                keys += self.msvcrt.getwch()
            return keys
        import select
        if not sys.stdin.isatty():
            return ""
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        return os.read(sys.stdin.fileno(), 1024).decode("utf-8", "replace") if ready else ""

    def __exit__(self, *_exc) -> None:
        if self.saved is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSAFLUSH, self.saved)


def _windows_vt() -> tuple | None:
    """Séquences VT et UTF-8 dans la console Windows ; ce qu'il faut remettre à la fin."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        kernel.GetConsoleMode(handle, ctypes.byref(mode))
        kernel.SetConsoleMode(handle, mode.value | 0x0004)     # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        cp = kernel.GetConsoleOutputCP()
        kernel.SetConsoleOutputCP(65001)
        return handle, mode.value, cp
    except (AttributeError, OSError):
        return None


def _windows_restore(saved: tuple | None) -> None:
    if saved is None:
        return
    import ctypes
    kernel = ctypes.windll.kernel32
    handle, mode, cp = saved
    kernel.SetConsoleMode(handle, mode)
    kernel.SetConsoleOutputCP(cp)


def run_view(code: str, *, t, relay_url: str, version: str = "", relay=None, out=None) -> int:
    """Montre l'écran partagé jusqu'à ce que l'ami arrête ou que l'aidant quitte. 0 si l'écran a été vu."""
    out = out or sys.stdout.buffer

    def write(data: bytes) -> None:
        out.write(data)
        out.flush()

    def say(text: str) -> None:
        write((text + "\n").encode("utf-8", "replace"))

    try:
        keys = calc.derive(code)
    except calc.InviteRefused:
        say(t("screen_view.bad_code"))
        return 1
    from .relay import ScreenRelay
    from .share import relay_host
    relay = relay or ScreenRelay(relay_url, version=version)
    viewer = Viewer(relay, keys)
    try:
        try:
            first = viewer.poll()
        except RelayRefused as exc:
            say(t("screen_view.unknown" if exc.reason == "unknown_session" else "screen_view.refused",
                  reason=exc.reason))
            return 1
        except RelayUnavailable as exc:
            say(t("screen_view.relay_down", relay=relay_host(relay_url), detail=str(exc)))
            return 1
        if viewer.ended:
            say(t("screen_view.ended." + ("expired" if viewer.ended == "expired" else "closed")))
            return 1
        vt = _windows_vt()
        seen = False
        try:
            with _Keys() as keys_in:
                write(b"\x1b[H\x1b[2J")
                say(t("screen_view.waiting"))
                pending = first
                next_poll = time.monotonic() + POLL_S
                title = None
                while True:
                    for data in pending:
                        write(data)
                        seen = True
                    pending = []
                    if viewer.ended:
                        break
                    term = shutil.get_terminal_size((80, 24))
                    small = viewer.cols and (term.columns < viewer.cols or term.lines < viewer.rows)
                    wanted = (t("screen_view.title_small", cols=viewer.cols, rows=viewer.rows) if small
                              else t("screen_view.title"))
                    if wanted != title:
                        write(b"\x1b]0;" + wanted.encode("utf-8", "replace") + b"\x07")
                        title = wanted
                    refresh = False
                    keys = keys_in.read()
                    if any(k in keys for k in QUIT_KEYS):
                        break
                    if REFRESH_KEY in keys:
                        refresh = True
                    if not refresh and time.monotonic() < next_poll:
                        time.sleep(0.1)
                        continue
                    try:
                        pending = viewer.poll(refresh=refresh)
                        next_poll = time.monotonic() + POLL_S
                    except RelayUnavailable:
                        write(b"\x1b]0;" + t("screen_view.title_down").encode("utf-8", "replace") + b"\x07")
                        title = None
                        next_poll = time.monotonic() + RETRY_S
                    except RelayRefused as exc:
                        viewer.ended = "closed" if exc.reason == "unknown_session" else exc.reason
        except KeyboardInterrupt:
            pass
        finally:
            write(RESTORE)
            _windows_restore(vt)
        say("")
        if viewer.ended:
            say(t("screen_view.ended." + ("expired" if viewer.ended == "expired" else "closed")))
        else:
            say(t("screen_view.quit"))
        if viewer.bad:
            say(t("screen_view.bad_frames", n=viewer.bad))
        return 0 if seen else 1
    finally:
        relay.close()
