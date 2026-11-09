# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Indicateur près de l'horloge (Windows) : icône colorée, infobulle, menu des lignes de `summarize`.

LECTURE SEULE : il lit les fichiers publiés par la station (état de la passerelle, mode sûr, Cluster DX, identifiant) et
ne commande jamais rien (pas de STOP TX : il est dans le tableau de bord). Processus à part, lancé à l'ouverture de
session (dossier Démarrage) : s'il s'arrête, la station n'en sait rien. Une seule instance par session (mutex nommé).
pystray et Pillow (paquet facultatif [tray]) ne sont importés qu'au lancement de l'icône : la logique reste testable.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .. import __version__
from .. import config as cfgmod
from ..paths import default_config_path
from .status import WINDOWS_HINTS, summarize

log = logging.getLogger(__name__)

POLL_S = 1.0
TOOLTIP_MAX = 127                        # limite de Windows (NOTIFYICONDATAW.szTip, 128 avec le zéro final)
COLORS = {"off": "#8a8a8a", "ok": "#2e9d4a", "tx": "#d32f2f", "warn": "#f0a020", "stale": "#c9a400", "safe": "#8e44ad"}
LEVEL_WORDS = {"off": "arrêtée", "ok": "en marche", "tx": "ÉMISSION", "warn": "à surveiller", "stale": "ne répond plus",
               "safe": "MODE SÛR"}
MUTEX_NAME = "Local\\TRX-distant-indicateur"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def collect(status_path: str | Path, state_dir: str | Path, now: float | None = None) -> dict:
    """Entrée de `summarize`, à partir des fichiers de la station (jamais d'exception)."""
    state = Path(state_dir)
    return {"status": _read_json(Path(status_path)), "nowS": time.time() if now is None else now,
            "safeMode": _read_text(state / "safe_mode"), "cluster": _read_json(state / "cluster" / "status.json"),
            "stationId": _read_text(state / "station-id"), "version": __version__}


def tooltip(view: dict) -> str:
    """Infobulle : « TRX distant : 7.195 LSB-D » ; en émission « TRX distant : TX 1:05 ». 127 caractères au plus."""
    level = view.get("level", "off")
    label = view.get("label") or ""
    tip = f"TRX distant : {label}" if label and label not in ("TRX", "TRX arrêtée") else f"TRX distant : {LEVEL_WORDS.get(level, level)}"
    if level == "warn":
        worst = next((ln for ln in view.get("lines", []) if ln.get("level") in ("bad", "warn")), None)
        if worst:
            tip += f"\n{worst['key']} : {worst['text']}"
    return tip[:TOOLTIP_MAX]


def menu_lines(view: dict) -> list[str]:
    """Lignes du menu (non cliquables) : « Clé : texte », marquées « ! » quand elles sont à surveiller."""
    return [("! " if ln.get("level") in ("warn", "bad") else "") + f"{ln['key']} : {ln['text']}" for ln in view.get("lines", [])]


def icon_image(level: str, size: int = 64):
    """Pastille de la couleur du niveau, cerclée de sombre (lisible sur barre claire ou sombre)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = size // 10
    draw.ellipse((pad, pad, size - pad, size - pad), fill=COLORS.get(level, COLORS["off"]), outline="#1e1e1e",
                 width=max(2, size // 16))
    if level == "tx":                                       # émission : un point blanc au centre, visible même en daltonisme
        r = size // 6
        draw.ellipse((size // 2 - r, size // 2 - r, size // 2 + r, size // 2 + r), fill="#ffffff")
    return img


def _single_instance() -> object | None:
    """Mutex nommé de la session : None si un indicateur tourne déjà."""
    if sys.platform != "win32":
        return object()
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle or kernel32.GetLastError() == 183:         # ERROR_ALREADY_EXISTS
        return None
    return handle


class Tray:
    def __init__(self, cfg, config_path: Path):
        self.cfg, self.config_path = cfg, config_path
        self.view: dict = summarize(None, WINDOWS_HINTS)
        self.icon = None
        self._stop = threading.Event()

    def refresh(self) -> bool:
        """Relit les fichiers ; vrai si l'affichage a changé."""
        view = summarize(collect(self.cfg.supervisor.status_path, self.cfg.supervisor.state_dir), WINDOWS_HINTS)
        changed = view != self.view
        self.view = view
        return changed

    # ---- actions (aucune ne commande la station)

    def open_page(self, *_):
        webbrowser.open(f"https://localhost:{self.cfg.network.gateway_port}")

    def open_dashboard(self, *_):
        python = Path(sys.executable).with_name("python.exe")          # pythonw n'a pas de console
        subprocess.Popen([str(python), "-m", "trxstation.monitor.main", "--config", str(self.config_path)],
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))

    def open_logs(self, *_):
        logs = self.config_path.parent / "logs"
        if hasattr(os, "startfile"):
            os.startfile(str(logs if logs.is_dir() else self.config_path.parent))

    def quit(self, *_):
        self._stop.set()
        if self.icon is not None:
            self.icon.stop()

    # ---- pystray

    def _menu(self):
        import pystray
        items = [pystray.MenuItem(line, None, enabled=False) for line in menu_lines(self.view)]
        return items + [pystray.Menu.SEPARATOR,
                        pystray.MenuItem("Ouvrir la page web de la station", self.open_page, default=True),
                        pystray.MenuItem("Ouvrir le tableau de bord", self.open_dashboard),
                        pystray.MenuItem("Journaux de la station", self.open_logs),
                        pystray.MenuItem("Quitter l'indicateur", self.quit)]

    def _loop(self, icon) -> None:
        icon.visible = True
        while not self._stop.is_set():
            try:
                if self.refresh():
                    icon.icon = icon_image(self.view["level"])
                    icon.title = tooltip(self.view)
                    icon.update_menu()
            except Exception:                                  # l'indicateur ne s'arrête jamais sur une lecture ratée
                log.exception("indicateur : mise à jour impossible")
            self._stop.wait(POLL_S)

    def run(self) -> None:
        import pystray
        self.refresh()
        self.icon = pystray.Icon("trx-distant", icon_image(self.view["level"]), tooltip(self.view),
                                 menu=pystray.Menu(lambda: self._menu()))
        self.icon.run(setup=self._loop)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m trxstation.tray",
                                     description="Indicateur de la station près de l'horloge (Windows, lecture seule).")
    parser.add_argument("--config", default=str(default_config_path()), help="station.toml")
    args = parser.parse_args(argv)
    config_path = Path(args.config)
    try:
        cfg, _problems = cfgmod.load_unchecked(config_path)    # même une configuration à corriger : on affiche quand même
    except Exception as exc:
        print(f"Configuration illisible ({exc}) : indicateur avec les chemins par défaut.", file=sys.stderr)
        cfg = cfgmod.Config()
    if _single_instance() is None:
        return 0                                               # déjà affiché dans cette session
    try:
        import pystray  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        print("Indicateur indisponible : modules pystray et Pillow absents (relance installer.cmd).", file=sys.stderr)
        return 2
    Tray(cfg, config_path).run()
    return 0
