# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Garde des outils lancés par l'opérateur : jamais de fermeture brutale sans message (étape 201).

Avant : une erreur imprévue (ou une entrée clavier fermée) refermait la fenêtre d'un raccourci Windows ou du lanceur
TRX Console de Debian avant qu'on ait pu lire quoi que ce soit. Désormais `@guarded("trx-hwtest")` sur le `main` :
  - erreur imprévue : message ORT-9312 en clair, trace complète enregistrée dans un fichier (joint au rapport du
    menu 6.3), code de sortie 1 ;
  - Ctrl+C : « Interrompu », code 130 ; entrée clavier fermée : message, code 2 ;
  - si la fenêtre va se refermer toute seule (raccourci Windows, lanceur Debian avec TRX_PAUSE_ON_EXIT=1), on attend
    Entrée après une erreur pour laisser le temps de lire.
Les blocs `finally` des outils (retour en réception, fermeture de l'audio) s'exécutent AVANT la garde : elle ne
change rien à la sécurité d'émission, elle n'arrive qu'après.
"""
from __future__ import annotations

import functools
import os
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from .errors import codes
from .errors.emit import render

CRASH_DIR_NAME = "plantages"
KEEP_FILES = 30                      # plus anciens effacés au-delà
PAUSE_ENV = "TRX_PAUSE_ON_EXIT"      # posé par le lanceur Debian (trx-console.desktop)


def crash_dirs() -> list[Path]:
    """Dossiers essayés dans l'ordre : dossier d'état de la station (joint au rapport), puis dossier temporaire
    (compte sans droit d'écriture sur le dossier d'état, Debian)."""
    dirs: list[Path] = []
    try:
        from .paths import default_state_dir
        dirs.append(default_state_dir() / CRASH_DIR_NAME)
    except Exception:            # garde : rien ici ne doit lever
        pass
    dirs.append(Path(tempfile.gettempdir()) / "trx-remote" / CRASH_DIR_NAME)
    return dirs


def save_crash(tool: str, exc: BaseException, dirs: list[Path] | None = None) -> Path | None:
    """Trace complète dans un fichier ; None si aucun dossier n'est inscriptible."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    text = (f"{tool} : erreur inattendue le {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Python {sys.version.split()[0]} sur {sys.platform}\nCommande : {' '.join(sys.argv)}\n\n"
            + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    for folder in dirs if dirs is not None else crash_dirs():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{tool}-{stamp}-{os.getpid()}.txt"
            path.write_text(text, encoding="utf-8")
            _prune(folder)
            return path
        except OSError:
            continue
    return None


def _prune(folder: Path) -> None:
    try:
        files = sorted(folder.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[KEEP_FILES:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def window_will_close() -> bool:
    """La fenêtre de terminal disparaîtra-t-elle à la sortie ? (raccourci Windows lancé sans PowerShell -NoExit,
    lanceur Debian). Jamais vrai sans clavier (tests, tubes, pythonw)."""
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
    except (OSError, ValueError):
        return False
    if os.environ.get(PAUSE_ENV) == "1":
        return True
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        buf = (ctypes.c_uint32 * 16)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(buf, 16)
    except Exception:
        return False
    own = 2 if "__PYVENV_LAUNCHER__" in os.environ else 1      # python.exe d'un venv = lanceur + interpréteur
    return 0 < count <= own


def pause(say: Callable[[str], None]) -> None:
    say("\nAppuie sur Entrée pour fermer cette fenêtre.")
    try:
        input()
    except (EOFError, KeyboardInterrupt, OSError):
        pass


def _say(text: str) -> None:
    try:
        print(text, file=sys.stderr, flush=True)
    except Exception:
        pass


def guarded(tool: str, *, say: Callable[[str], None] = _say,
            will_close: Callable[[], bool] = window_will_close) -> Callable:
    """Décorateur du `main` d'un outil (voir l'en-tête du module)."""
    def decorate(main: Callable[..., int | None]) -> Callable[..., int | None]:
        @functools.wraps(main)
        def wrapper(*args, **kwargs):
            try:
                code = main(*args, **kwargs)
            except SystemExit as exc:          # argparse, sys.exit : comportement normal
                code = exc.code
            except KeyboardInterrupt:
                say("\nInterrompu (Ctrl+C).")
                code = 130
            except EOFError:
                say(f"\n{tool} attendait une réponse au clavier, mais l'entrée est fermée : arrêt.")
                code = 2
            except Exception as exc:
                path = save_crash(tool, exc)
                summary = f"{type(exc).__name__}: {exc}"[:300]
                _, message = render(codes.ORT_9312, outil=tool, erreur=summary,
                                    fichier=str(path) if path else "(aucun dossier inscriptible)")
                say("\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())
                say(f"\n{codes.ORT_9312} {message}")
                code = 1
            failed = code not in (0, None)
            if failed and will_close():
                pause(say)
            return code
        wrapper.__trx_guarded__ = tool          # vérifié par tests/test_crashguard.py
        return wrapper
    return decorate
