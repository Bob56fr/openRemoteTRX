# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console : point d'entrée unique de la station pour qui ne connaît pas Linux (commande `trx-console`).

Menus sur deux niveaux, par thème (MENU_THEMES, rangés par intention depuis la station 0.166.0) : 1 Station, 2 Poste
et matériel, 3 Sécurité d'émission et alertes, 4 Accès et comptes, 5 Fonctions, 6 Dépannage et assistance, 7 Mises
à jour, 8 Expert et préférences ; « 7.3 » tapé directement ouvre un sous-menu ; 0 = langue (fr, en, de, es : trxstation/
i18n/, choix gardé par compte). Les anciens numéros 10 à 24 (un seul niveau, jusqu'à la station 0.125.0) restent
acceptés quelque temps avec le nouveau numéro (OLD_NUMBERS). Les textes des menus et de l'aide « h » viennent des
catalogues de langue ; les textes à l'intérieur des menus sont encore en français (lot L2).
Les actions qui touchent au système passent par `sudo` : le mot de passe de session est demandé au besoin.

    trx-console               menu
    trx-console --diagnostic  diagnostic complet puis sortie (code 1 si une erreur bloquante)
    trx-console --rapport     crée le rapport de dépannage (zip sur le Bureau)
"""
from __future__ import annotations

from .crashguard import guarded

import argparse
import codecs
import difflib
import json
import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .diagnostics import CONFIG_PATH, UNITS, exit_code, format_checks, run_all
from .answers import typed, yes_no
from .i18n import ENV_LANG, LANGS, NAMES, Translator, load_lang, prefs_path, save_lang
from .i18n import LEVELS, load_level, save_level
from .paths import default_state_dir
from . import profiles as prof
from .station_id import read_station_id
from .update import apply as upd
from .update.apply import previous_version
from .update.check import Change, UpdateState, clean_text, parse_version, read_state, state_path

TARGET = "trx-remote.target"
IS_WINDOWS = sys.platform == "win32"
WINDOWS_TASK = "TRX distant"        # tâche planifiée posée par windows/installer.ps1 ($TaskName)
JOURNAL_LINES = 80
IMPORT_NAME = "station.import.toml"
CHECK_UNIT = "trx-update-check.service"
INSTALL_LOG = "/var/log/trx-remote-install.log"
ZIP_PLACES = ("Desktop", "Bureau", "Downloads", "Téléchargements", "")   # où chercher un paquet déposé ("" = dossier personnel)
MAX_DIFF_LINES = 60
GNOME_EXTENSION_UUID = "trx-distant@rf-diy.com"
GNOME_EXTENSION_DIR = Path("/usr/share/gnome-shell/extensions") / GNOME_EXTENSION_UUID
QUIET_AFTER_S = 60.0              # tests : rappel « toujours en cours » après une minute sans rien de nouveau
NOTES_PAGE_LINES = 20             # notes de version : affichées par pages de 20 lignes
GREEN, YELLOW, RED = "32", "33", "31"   # couleurs ANSI de l'en-tête et du menu 0 (terminal seulement)
# Menus par thème : (numéro du thème, identifiant du titre, [méthodes de Console dans l'ordre des sous-menus]).
# Libellés : « menu.<méthode> » et « theme.<id> » des catalogues trxstation/i18n/console.<langue>.json.
# Arborescence par INTENTION de l'opérateur (station 0.166.0, étape 219 ; carte des réglages du 2026-11-16). Un
# nouveau menu s'ajoute EN FIN de son thème : les numéros existants ne bougent plus.
MENU_THEMES = (
    ("1", "station", ("start", "stop", "monitor", "clear_safe_mode")),
    ("2", "hardware", ("assistant", "hwtest", "profiles", "sdr", "rig", "sound", "hf_spectrum", "remote_power",
                               "rx_gain")),
    ("3", "safety", ("temperature", "bands", "transmit", "local_operator", "alerts")),
    ("4", "access", ("pairing", "visitors", "operators", "certificate", "access_network", "remote_console")),
    ("5", "features", ("cluster", "breizh", "friends", "swr_report", "features_switch", "diffusion")),
    ("6", "troubleshooting", ("diagnostic", "journal", "report", "network", "monitoring")),
    ("7", "updates", ("update", "rollback", "install_zip")),
    ("8", "expert", ("edit_config", "expert", "qualif", "indicator")),
)
# Numéros d'avant la station 0.166.0 (deux niveaux, 0.126.0 à 0.165.0) -> méthode : rappelés dans l'en-tête
# jusqu'à RENUMBER_NOTICE_UNTIL, jamais acceptés à la saisie (« 6.3 » désigne désormais le rapport de dépannage).
RENUMBERED_IN = "0.166.0"
RENUMBER_NOTICE_UNTIL = (0, 180, 0)
# Anciens numéros (un seul niveau, jusqu'à la station 0.125.0) -> méthode. 10 à 24 restent acceptés quelque temps
# avec un message ; 1 à 9 ouvrent désormais un thème.
RX_TARGET_DBFS = -20       # menu 2.9 : niveau reçu visé (voix ou bruit de bande sur antenne)
RX_FLOOR_DBFS = -85        # en dessous : pas de son mesurable (station arrêtée, poste muet), aucune proposition
RX_GAIN_LOW, RX_GAIN_HIGH = -40, 20     # bornes de [audio] rx_gain_db (config.validate)
OLD_NUMBERS = {"1": "diagnostic", "2": "assistant", "3": "monitor", "4": "hwtest", "5": "start", "6": "stop",
               "7": "journal", "8": "report", "9": "clear_safe_mode", "10": "update", "11": "rollback",
               "12": "cluster", "13": "install_zip", "14": "edit_config", "15": "expert", "16": "temperature",
               "17": "indicator", "18": "profiles", "19": "pairing", "20": "visitors", "21": "swr_report",
               "22": "breizh", "23": "network", "24": "friends"}
OLD_ACCEPTED = tuple(str(n) for n in range(10, 25))


# Niveau de chaque menu (étape 234) : Basic = mettre en service, utiliser, demander de l'aide ; Expert = réglages fins et
# outils de développement ; tout le reste = Normal. « 0 » (langue et niveau) est toujours montré.
BASIC_MENUS = frozenset({"start", "stop", "monitor", "clear_safe_mode", "assistant", "hwtest", "pairing", "operators",
                         "diagnostic", "report", "update"})
EXPERT_MENUS = frozenset({"temperature", "edit_config", "expert", "qualif"})


def menu_level(method: str) -> str:
    return "basic" if method in BASIC_MENUS else "expert" if method in EXPERT_MENUS else "normal"


def menu_number(method: str) -> str:
    """Numéro « thème.sous-menu » d'une méthode de la console (ex. « install_zip » -> « 7.3 »)."""
    for theme, _, methods in MENU_THEMES:
        if method in methods:
            return f"{theme}.{methods.index(method) + 1}"
    raise KeyError(method)


UPDATE_MENU = menu_number("update")
# Console web (étape 229) : la console texte tourne dans le terminal intégré de la page ; elle écrit cette séquence
# OSC (invisible) quand elle attend au menu, seul moment où la page peut taper un numéro de menu à sa place.
WEB_MODE = os.environ.get("TRX_CONSOLE_WEB") == "1"
WEB_IDLE_MARK = "\x1b]777;trx-idle\x07"
TOT_ABS_MAX_S = 600               # menu 3.4 : TOT absolu du superviseur, au plus 10 minutes depuis la console
# Menu 5.5 « Fonctions en service » : (clé du libellé, section de station.toml portant `enabled` ou None,
# module de [modules] run ou None, menu de ses réglages ou None). Activer = enabled ET module lancé.
FEATURES = (
    ("features.cluster", "cluster", "cluster", "cluster"),
    ("features.freedv", "freedv", None, None),
    ("features.freedv_activity", None, "freedv_activity", None),
    ("features.selcall", "selcall", None, None),
    ("features.presence", "presence", "presence", "friends"),
    ("features.monlink", "monitor_link", "monlink", "monitoring"),
    ("features.diffusion", "diffusion", "diffusion", "diffusion"),
    ("features.sdr", "sdr", "sdr", "sdr"),
    ("features.breizh", "breizh", None, "breizh"),
    ("features.netprobe", "netprobe", None, "network"),
    ("features.swr", "swr", None, "swr_report"),
)


def feature_on(cfg, section: str | None, module: str | None) -> bool:
    on = getattr(getattr(cfg, section), "enabled") is True if section else True
    return on and (module in cfg.modules.run if module else True)


def set_feature(cfg, section: str | None, module: str | None, on: bool) -> None:
    if section:
        getattr(cfg, section).enabled = on
    if module:
        run = [m for m in cfg.modules.run if m != module]
        cfg.modules.run = [*run, module] if on else run


NEW_CONSOLE = "<nouvelle-console>"        # marque de new_terminal_command : Windows, nouvelle fenêtre de console


def new_terminal_command(cmd: list[str], *, title: str = "trx-monitor", environ: dict | None = None,
                         windows: bool | None = None, which: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    """Commande qui lance `cmd` dans un NOUVEL onglet ou une nouvelle fenêtre de terminal, sinon None (rester ici).
    tmux / screen d'abord (marche aussi en SSH) ; Windows : onglet de Windows Terminal, sinon nouvelle console ;
    bureau Linux (jamais en SSH : la fenêtre s'ouvrirait sur l'écran de la station) : onglet de GNOME Terminal, sinon
    x-terminal-emulator."""
    env = os.environ if environ is None else environ
    windows = IS_WINDOWS if windows is None else windows
    if env.get("TMUX") and which("tmux"):
        import shlex
        return ["tmux", "new-window", "-n", title, shlex.join(cmd)]
    if env.get("STY") and which("screen"):
        return ["screen", "-X", "screen", "-t", title, *cmd]
    if windows:
        if env.get("WT_SESSION") and which("wt"):
            return ["wt", "-w", "0", "new-tab", "--title", title, *cmd]
        return [NEW_CONSOLE, *cmd]                     # Runner.spawn : nouvelle fenêtre de console
    if env.get("SSH_CONNECTION") or not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return None
    if which("gnome-terminal"):
        return ["gnome-terminal", "--tab", "--title", title, "--", *cmd]
    if which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", *cmd]
    return None


def windows_tray_startup() -> Path:
    """Raccourci du dossier Démarrage de la session (même nom que $TrayStartup de windows/installer.ps1)."""
    return (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            / "TRX distant - indicateur.lnk")


def windows_pythonw() -> str:
    """pythonw.exe du même environnement (aucune fenêtre) ; à défaut, l'interpréteur courant."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate if candidate.exists() else Path(sys.executable))


def console_url(host: str, port: int) -> str:
    """Adresse de TRX Console sur le réseau (étape 233)."""
    return "https://" + (f"[{host}]" if ":" in host else host) + f":{port}/"


def mask_notify_url(url: str) -> str:
    """Adresse ntfy montrée sans son secret : https://ntfy.sh/abc… (qui connaît le sujet lit les alertes)."""
    if not url:
        return ""
    scheme, _, rest = url.partition("://")
    host, _, topic = rest.partition("/")
    return f"{scheme}://{host}/" + (topic[:3] + "…" if topic else "")


_NOTIFY_LINE = re.compile(r'^([+-]?\s*notify_url\s*=\s*")([^"]*)(".*)$')


def hide_secret_line(line: str) -> str:
    """Ligne de différences de station.toml : l'adresse ntfy (sujet secret) n'est jamais montrée en entier."""
    m = _NOTIFY_LINE.match(line)
    return f"{m.group(1)}{mask_notify_url(m.group(2))}{m.group(3)}" if m else line
STATUS_FRESH_S = 10              # fichier d'état de la passerelle plus vieux : passerelle arrêtée
HANG_DUMP_S = 600                 # tests : un test bloqué 10 minutes affiche sa pile (faulthandler de pytest)


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes} min {secs:02d} s" if minutes else f"{secs} s"


def find_packages(home: Path) -> list[tuple[str, Path]]:
    """Paquets « trx-remote-debian-X.Y.Z.zip » déposés par l'utilisateur, du plus récent au plus ancien."""
    found: dict[Path, tuple[str, Path]] = {}
    for place in ZIP_PLACES:
        folder = home / place if place else home
        try:
            candidates = list(folder.glob("trx-remote-debian-*.zip"))
        except OSError:
            continue
        for path in candidates:
            version = upd.local_package_version(path)
            if version and path.is_file():
                found.setdefault(path.resolve(), (version, path))
    return sorted(found.values(), key=lambda item: (parse_version(item[0]) or (), str(item[1])), reverse=True)


def set_safety_values(text: str, values: dict[str, int]) -> str:
    """Remplace (ou ajoute) des clés de la section [safety] de station.toml, sans toucher au reste ni aux commentaires."""
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if text.endswith("\r\n") else "\n"
    start = next((i for i, line in enumerate(lines) if line.strip() == "[safety]"), None)
    if start is None:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        lines += [newline, "[safety]" + newline]
        start = len(lines) - 1
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    for key, value in values.items():
        pattern = re.compile(rf"^(\s*{key}\s*=\s*)[^#\r\n]*?(\s*(#.*)?)(\r?\n)?$")
        for i in range(start + 1, end):
            match = pattern.match(lines[i])
            if match:
                lines[i] = f"{match.group(1)}{value}{match.group(2) or ''}{match.group(4) or ''}"
                break
        else:
            lines.insert(start + 1, f"{key} = {value}{newline}")
            end += 1
    return "".join(lines)


def address_line(bind: str, port: int, tls: bool, addresses: list[str], t: Translator | None = None) -> str:
    """En-tête de la console : adresse(s) où joindre la station (page web, application)."""
    t = t or Translator()
    scheme = "https" if tls else "http"
    if bind in ("", "127.0.0.1", "localhost", "::1"):
        return "  " + t("head.address_local", url=f"{scheme}://127.0.0.1:{port}")
    hosts = addresses if bind in ("0.0.0.0", "::") else [bind]
    if not hosts:
        return "  " + t("head.address_unknown", port=port)
    return "  " + t("head.address", urls=", ".join(f"{scheme}://{host}:{port}" for host in hosts))


def console_line(enabled: bool, bind: str, port: int, tls: bool, addresses: list[str],
                 t: Translator | None = None) -> str:
    """En-tête de la console : adresse(s) de TRX Console sur le réseau ([remote_console], menu 4.6)."""
    t = t or Translator()
    menu = menu_number("remote_console")
    if not enabled or not tls or bind in ("", "127.0.0.1", "localhost", "::1"):
        return "  " + t("head.console_off", menu=menu)
    hosts = addresses if bind in ("0.0.0.0", "::") else [bind]
    if not hosts:
        return "  " + t("head.console_unknown", port=port)
    return "  " + t("head.console", urls=", ".join(console_url(host, port).rstrip("/") for host in hosts))


def rig_vitals_line(rig: dict | None, t: Translator | None = None) -> str:
    """En-tête de la console : tension d'alimentation et température du poste, telles que la passerelle les publie
    (aucune connexion de plus à rigctld). `rig` None = passerelle arrêtée. « — » = valeur non fournie par le poste
    (l'IC-7300MK2 ne donne pas sa température à Hamlib)."""
    t = t or Translator()
    if rig is None:
        return "  " + t("head.rig_unavailable")
    if not rig.get("connected"):
        return "  " + t("head.rig_no_cat")
    levels = rig.get("levels") if isinstance(rig.get("levels"), dict) else {}

    def number(key: str) -> float | None:
        value = levels.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    vd, temp = number("VD_METER"), number("TEMP_METER")
    volts = f"{vd:.1f} V".replace(".", t("num.decimal")) if vd is not None else "—"
    degrees = f"{round(temp)} °C" if temp is not None else "—"
    return "  " + t("head.rig", volts=volts, degrees=degrees)


def config_state_dir(config: Path) -> Path:
    """Dossier d'état de la station (repli : emplacement par défaut si la configuration est illisible)."""
    from . import config as cfgmod
    try:
        cfg, _ = cfgmod.load_unchecked(config)
        return Path(cfg.supervisor.state_dir)
    except (cfgmod.ConfigError, OSError):
        return default_state_dir()


class Runner:
    """Exécute les commandes dans le terminal de l'utilisateur ; remplacé par un faux dans les tests."""
    t = Translator()                     # remplacé par la console (langue choisie)

    def __init__(self) -> None:
        self.is_root = hasattr(os, "geteuid") and os.geteuid() == 0

    def run(self, cmd: list[str], *, admin: bool = False) -> int:
        lang = f"{ENV_LANG}={self.t.lang}"                 # outils dans la langue de la console (lot L3, étape 240)
        if admin and os.name == "posix" and not self.is_root:     # Windows : pas de sudo (désactivé ou autre fenêtre)
            cmd = ["sudo", "env", lang, *cmd]                      # sudo vide l'environnement : `env` le redonne
        try:
            return subprocess.call(cmd, env={**os.environ, ENV_LANG: self.t.lang})
        except FileNotFoundError:
            print(self.t("runner.not_found", cmd=cmd[0]))
            return 127
        except KeyboardInterrupt:
            print()
            return 130

    def spawn(self, cmd: list[str]) -> bool:
        """Lance un programme qui continue seul (indicateur près de l'horloge) ; vrai s'il a démarré."""
        if cmd and cmd[0] == NEW_CONSOLE:              # programme interactif dans sa propre fenêtre (Windows)
            try:
                subprocess.Popen(cmd[1:], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0), close_fds=True)
                return True
            except OSError:
                return False
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen(cmd, creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
            return True
        except OSError:
            return False

    def run_logged(self, cmd: list[str], log_path: Path, *, cwd: Path | None = None,
                   quiet_after_s: float = QUIET_AFTER_S) -> int:
        """Affiche la sortie AU CARACTÈRE PRÈS (les points de pytest, pas ligne par ligne) ET l'enregistre aussitôt dans
        `log_path`. Sans rien de nouveau pendant `quiet_after_s`, rappelle que l'exécution continue (petit PC : un test
        lent ne doit pas passer pour un plantage)."""
        started = time.monotonic()
        last = [started]
        lock = threading.Lock()
        done = threading.Event()

        def heartbeat() -> None:
            while not done.wait(1.0):
                now = time.monotonic()
                with lock:
                    if now - last[0] >= quiet_after_s:
                        last[0] = now
                        sys.stdout.write("\n" + self.t("runner.still_running", duration=format_duration(now - started)) + "\n")
                        sys.stdout.flush()
        try:
            with open(log_path, "wb") as log, subprocess.Popen(
                    cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}) as proc:
                assert proc.stdout is not None
                decoder = codecs.getincrementaldecoder("utf-8")("replace")
                beat = threading.Thread(target=heartbeat, name="trx-console-patience", daemon=True)
                beat.start()
                try:
                    while chunk := proc.stdout.read1(4096):
                        log.write(chunk)
                        log.flush()                      # le fichier sur le Bureau suit lui aussi
                        with lock:
                            last[0] = time.monotonic()
                            sys.stdout.write(decoder.decode(chunk))
                            sys.stdout.flush()
                    return proc.wait()
                finally:
                    done.set()
        except FileNotFoundError:
            print(self.t("runner.not_found", cmd=cmd[0]))
            return 127
        except KeyboardInterrupt:
            print()
            return 130

    def output(self, cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""


class Console:
    t = Translator()          # français par défaut ; remplacé dans __init__ par la langue choisie

    def __init__(self, config: Path = CONFIG_PATH, runner: Runner | None = None,
                 ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
                 python: str = sys.executable, update_state: Callable[[], UpdateState | None] | None = None,
                 previous: Callable[[], str | None] = previous_version, installed: str = __version__,
                 home: Path | None = None, editor: str | None = None, app_dir: Path = upd.APP_DIR,
                 desktop: Callable[[], Path] | None = None, color: bool | None = None,
                 addresses: Callable[[], list[str]] | None = None, lang: str | None = None,
                 lang_file: Path | None = None, level: str | None = None) -> None:
        self.config, self.runner, self.ask, self.say, self.python = config, runner or Runner(), ask, say, python
        self.color = color if color is not None else (say is print and sys.stdout.isatty())
        self.update_state = update_state or (lambda: read_state(state_path(config_state_dir(self.config))))
        self.previous, self.installed = previous, installed
        self.home = home or Path.home()
        self.editor = (editor or os.environ.get("VISUAL") or os.environ.get("EDITOR")
                       or ("notepad.exe" if IS_WINDOWS else shutil.which("nano")) or "")
        self.app_dir = app_dir
        self.desktop = desktop
        self.addresses = addresses
        # Langue : choisie par le menu 0 (fichier par compte), sinon celle du système, sinon le français. Les tests
        # passent `lang` (défaut "fr" quand `ask` n'est pas la saisie du terminal : sorties stables).
        self.lang_file = lang_file or prefs_path(home)
        if lang is None:
            lang = load_lang(self.lang_file) if ask is input else "fr"
        self.t = Translator(lang)
        self._share_language()
        # Niveau (étape 234) : choisi au menu 0 ; les tests (ask factice) voient tous les menus.
        if level is None:
            level = load_level(self.lang_file, self.config.exists()) if ask is input else "expert"
        self.level = level if level in LEVELS else "normal"
        # Nature de la PROCHAINE question (étape 235) : lue par la console web en formulaires, ignorée au terminal.
        self.hint: dict | None = None

    def visible(self, method: str) -> bool:
        """Menu montré au niveau choisi ? « Sortir du mode sûr » n'encombre le niveau Basic que si la station y est."""
        if method == "clear_safe_mode" and self.level == "basic":
            return self.in_safe_mode()
        return LEVELS.index(menu_level(method)) <= LEVELS.index(self.level)

    def in_safe_mode(self) -> bool:
        try:
            return (config_state_dir(self.config) / "safe_mode").exists()
        except Exception:                               # en-tête et menus : jamais d'exception pour un affichage
            return False

    def visible_themes(self) -> set[str]:
        return {theme for theme, _, methods in MENU_THEMES if any(self.visible(m) for m in methods)}

    def _share_language(self) -> None:
        try:
            self.runner.t = self.t                 # messages du lanceur de commandes dans la même langue
        except AttributeError:
            pass

    @property
    def items(self) -> list[tuple[str, str, Callable[[], None]]]:
        """[(numéro « thème.n », libellé dans la langue choisie, méthode)] dans l'ordre des thèmes."""
        return [(f"{theme}.{n}", self.t(f"menu.{name}"), getattr(self, name))
                for theme, _, methods in MENU_THEMES for n, name in enumerate(methods, 1)]

    def themes(self) -> list[tuple[str, str, str]]:
        """[(numéro, titre, contenu en quelques mots)] du menu principal."""
        return [(theme, self.t(f"theme.{tid}"), self.t(f"theme.{tid}.desc")) for theme, tid, _ in MENU_THEMES]

    # ------------------------------------------------------------------ outils

    def module(self, name: str, *args: str) -> list[str]:
        return [self.python, "-m", name, *args]

    def pause(self) -> None:
        self.hint = {"kind": "pause"}
        try:
            self.ask("\n" + self.t("loop.pause"))
        except EOFError:
            pass

    def yes(self, question: str, default: bool = True) -> bool:
        self.hint = {"kind": "yesno", "default": default}
        answer = self.ask(f"{question} ({self.t('yes.default_yes') if default else self.t('yes.default_no')}) : ").strip()
        return default if not answer else yes_no(answer) is True

    def typed_word(self, answer: str, key: str, french: str, exact: bool = False) -> bool:
        """Mot de confirmation tapé : celui de la langue choisie OU le mot français (toujours accepté).
        `exact` : casse et accents comptent (comme avant pour EFFACER)."""
        words = {self.t(key), french}
        if exact:
            return (answer or "").strip() in words
        return any(typed(answer, w) for w in words)

    def station_running(self) -> bool:
        if IS_WINDOWS:                                   # pas de systemd : verrou d'instance du superviseur
            from .procutil import station_running
            return station_running(self._lock_port())
        return any(self.runner.output(["systemctl", "is-active", unit]) == "active" for unit in UNITS)

    def _lock_port(self) -> int:
        from . import config as cfgmod
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
            return cfg.supervisor.instance_lock_port
        except (OSError, cfgmod.ConfigError):
            return cfgmod.Supervisor().instance_lock_port

    def _start_station(self, verb: str = "restart") -> int:
        """Debian : systemd. Windows : tâche planifiée de l'installation (pas de sudo ni de systemctl)."""
        if IS_WINDOWS:
            return self.runner.run(["schtasks", "/Run", "/TN", WINDOWS_TASK])
        return self.runner.run(["systemctl", verb, TARGET], admin=True)

    def _stop_station(self) -> int:
        """Debian : systemd. Windows : demande d'arrêt au superviseur (passerelle d'abord : retour en réception)."""
        if IS_WINDOWS:
            return self.runner.run(self.module("trxstation.supervisor.main", "--config", str(self.config), "--stop"))
        return self.runner.run(["systemctl", "stop", TARGET], admin=True)

    # ------------------------------------------------------------------ écritures avec droits d'administration

    def _install_file(self, src: Path, dst: Path, *, mode: str = "0644", like: Path | None = None,
                      parents: bool = False) -> int:
        """Copie `src` vers `dst` avec les droits d'administration ; `like` : même propriétaire que ce fichier.
        Debian : `install` par sudo. Windows : copie directe (le compte de l'installation a les droits). 0 = réussi."""
        if IS_WINDOWS:
            try:
                if parents:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                return 0
            except OSError:
                return 1
        cmd = ["install", *(["-D"] if parents else []), "-m", mode]
        if like is not None:
            st = like.stat()
            cmd += ["-o", str(st.st_uid), "-g", str(st.st_gid)]
        return self.runner.run([*cmd, str(src), str(dst)], admin=True)

    def _remove_file(self, path: Path) -> int:
        if IS_WINDOWS:
            try:
                path.unlink(missing_ok=True)
                return 0
            except OSError:
                return 1
        return self.runner.run(["rm", "-f", str(path)], admin=True)

    def _make_dir(self, path: Path) -> int:
        if IS_WINDOWS:
            try:
                path.mkdir(parents=True, exist_ok=True)
                return 0
            except OSError:
                return 1
        return self.runner.run(["mkdir", "-p", str(path)], admin=True)

    def _windows_updates(self) -> bool:
        """Windows : pas de mise à jour par la console (on lance installer.cmd du nouveau zip). Vrai si dit."""
        if IS_WINDOWS:
            self.say(self.t("updates.windows"))
        return IS_WINDOWS

    def stop_for_exclusive_use(self, why: str) -> bool:
        """Arrête la station si elle tourne (port série et carte son doivent être libres). Vrai si arrêtée ici."""
        if not self.station_running():
            return False
        self.say(self.t("stop_for_exclusive_use.1", why=why))
        self._stop_station()
        return True

    # ------------------------------------------------------------------ actions

    def diagnostic(self) -> None:
        self.say(self.t("diagnostic.1"))
        self.say(format_checks(run_all(path=self.config), color=sys.stdout.isatty()))
        extras = self._diagnostic_modes()
        if extras:
            self.say(extras)

    def _diagnostic_modes(self) -> str:
        """Breizh Audio Box et visiteurs en trois lignes (lecture seule, aucun secret : ni clé ni mot de passe)."""
        from datetime import date

        from . import config as cfgmod
        if not self.config.exists():
            return ""
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
        except (OSError, cfgmod.ConfigError):
            return ""                                   # déjà signalé par le diagnostic
        b, a = cfg.breizh, cfg.access
        breizh = self.t("diagnostic_modes.1") if b.enabled else self.t("diagnostic_modes.2")
        if b.enabled:
            status = self._gateway_status()
            live = status.breizh if status is not None and isinstance(getattr(status, "breizh", None), dict) else {}
            state = self.label(self.BREIZH_STATES, live.get("state"), live.get("state")) if live else self.t("diagnostic_modes.3")
            breizh += self.t("diagnostic_modes.4", v=b.host or self.t("diagnostic_modes.5"), port=b.port, state=state)
        today = date.today()
        accounts = []
        for c in (c for c in cfg.clients if c.role == "listener"):
            label = self._account_label(c)
            accounts.append(label + (self.t("diagnostic_modes.6") if c.expired(today) else ""))
        return "\n".join([
            self.t("diagnostic_modes.7"),
            self.t("diagnostic_modes.8", breizh=breizh),
            self.t("diagnostic_modes.9") + (self.t("diagnostic_modes.10", max_listeners=a.max_listeners) if a.max_listeners
                                       else self.t("diagnostic_modes.11")),
            self.t("diagnostic_modes.12") + (", ".join(accounts) or self.t("diagnostic_modes.13")),
        ])

    def assistant(self) -> None:
        stopped = self.stop_for_exclusive_use(self.t("assistant.why"))
        cmd = self.module("trxstation.setup_wizard", "--output", str(self.config))
        imported = self.config.parent / IMPORT_NAME
        if not self.config.exists() and imported.exists():
            self.say(self.t("assistant.1", imported=imported))
            cmd += ["--base", str(imported)]
        code = self.runner.run(cmd, admin=True)
        if code != 0:
            self.say(self.t("assistant.2"))
            if stopped and self.config.exists():
                self._start_station("start")
            return
        if self.yes(self.t("assistant.3")):
            self.start()

    # ------------------------------------------------------------------ parties de l'assistant (étape 220)

    def rig(self) -> None:
        self._setup_part("poste", exclusive=True)

    def sound(self) -> None:
        self._setup_part("son", exclusive=True)

    def hf_spectrum(self) -> None:
        self._setup_part("spectre", exclusive=True)

    def bands(self) -> None:
        self._setup_part("bandes")

    def transmit(self) -> None:
        self._setup_part("emission")

    def access_network(self) -> None:
        self._setup_part("reseau")

    def _setup_part(self, part: str, exclusive: bool = False) -> None:
        """Une partie de l'assistant (`trx-setup --partie`), avec les droits d'administration : mêmes questions,
        même sauvegarde de l'ancienne configuration que l'assistant complet (menu 2.1). `exclusive` : le poste ou la
        carte son doivent être libres (station arrêtée le temps des questions)."""
        if not self.config.exists():
            full = menu_number("assistant")
            self.say(self.t("setup_part.1", menu=full))
            return
        was_running = self.station_running()
        stopped = self.stop_for_exclusive_use(self.t("setup_part.why")) if exclusive else False
        before = self.config.read_bytes()
        code = self.runner.run(self.module("trxstation.setup_wizard", "--output", str(self.config), "--partie", part),
                               admin=True)
        changed = self.config.exists() and self.config.read_bytes() != before
        if code != 0 or not changed:
            self.say(self.t("setup_part.2"))
            if stopped:
                self._start_station("start")
            return
        if was_running:
            if self.yes(self.t("setup_part.3"), True):
                self.start()
        elif self.yes(self.t("assistant.3")):
            self.start()

    # ------------------------------------------------------------------ écrans dédiés (étape 221)

    def _load_for_edit(self):
        """(contenu d'origine, configuration) pour un écran de réglage ; None si la station n'est pas configurée."""
        from . import config as cfgmod
        if not self.config.exists():
            full = menu_number("assistant")
            self.say(self.t("setup_part.1", menu=full))
            return None
        try:
            return self.config.read_bytes(), cfgmod.load_unchecked(self.config)[0]
        except (OSError, cfgmod.ConfigError) as exc:
            self.say(self.t("visitors.2", config=self.config, exc=exc))
            return None

    def local_operator(self) -> None:
        """Opérateur sur place (règles d'émission, décisions du 2026-10-27 et du 2026-11-16) : station partagée ou non,
        TOT absolu du superviseur, durée tolérée d'une émission locale quand la présence est prouvée. Le superviseur
        ne peut que COUPER : ces réglages ne déclenchent jamais d'émission."""
        from .config import LOCAL_TX_CEILING_S
        loaded = self._load_for_edit()
        if loaded is None:
            return
        original, cfg = loaded
        v = cfg.supervisor
        self.say(self.t("local_operator.1"))
        self.say(self.t("local_operator.state", shared=self.t("ask_yes.2") if v.allow_local_tx else self.t("ask_yes.3"),
                        abs=v.tot_abs_s, present=v.local_tx_max_s))
        v.allow_local_tx = self._ask_yes(self.t("local_operator.2"), v.allow_local_tx)
        v.tot_abs_s = self._ask_int(self.t("local_operator.3"), v.tot_abs_s, cfg.safety.tot_ceiling_s + 1, TOT_ABS_MAX_S)
        if v.allow_local_tx:
            v.local_tx_max_s = self._ask_int(self.t("local_operator.4"), v.local_tx_max_s, 1, LOCAL_TX_CEILING_S)
        self._save_accounts(original, cfg, live=False)

    def remote_power(self) -> None:
        """Allumage et extinction du poste à distance (docs/alimentation-poste-cahier-des-charges.md § 8.3) :
        interrupteur HORS SERVICE par défaut ; mise en service refusée si Hamlib ne déclare pas la fonction ou si
        l'essai (éteindre, ports relus, rallumer : trxstation/power_trial.py, station arrêtée) échoue ; identité USB
        des ports relevée. La console n'allume ni n'éteint jamais le poste elle-même hors de cet essai."""
        from . import usbports
        loaded = self._load_for_edit()
        if loaded is None:
            return
        original, cfg = loaded
        pw, rig = cfg.power, cfg.rig
        on_off = lambda value: self.t("ask_yes.2") if value else self.t("ask_yes.3")   # noqa: E731
        self.say(self.t("remote_power.1"))
        self.say(self.t("remote_power.state", on=on_off(pw.enabled), idle=on_off(pw.idle_off), hours=pw.idle_off_hours,
                        notify=on_off(pw.notify), ident=rig.port_usb or self.t("remote_power.no_ident")))
        enable = self._ask_yes(self.t("remote_power.2"), pw.enabled)
        stopped = False
        if enable and (not pw.enabled or not rig.port_usb):
            declared = self._power_declared(rig.model, cfg.tools.hamlib_dir)
            if declared is not True:
                self.say(self.t("remote_power.unsupported") if declared is False else self.t("remote_power.caps_unknown"))
                enable = False
            else:
                self.say(self.t("remote_power.warning"))
                if self.yes(self.t("remote_power.trial_ask")):
                    stopped = self.stop_for_exclusive_use(self.t("remote_power.why"))
                    code = self.runner.run(self.module("trxstation.power_trial", "--config", str(self.config)), admin=True)
                    if code != 0:
                        self.say(self.t("remote_power.trial_failed"))
                        enable = False
                if enable:
                    for name, port in (("port_usb", rig.port), ("ptt_port_usb", rig.ptt_port)):
                        if name == "ptt_port_usb" and (rig.ptt_type not in ("RTS", "DTR") or not port
                                                       or port.strip().lower() == rig.port.strip().lower()):
                            setattr(rig, name, "")
                            continue
                        ident = usbports.identity(port) if port else None
                        setattr(rig, name, str(ident) if ident is not None else "")
                        self.say(self.t("remote_power.ident", port=port or "-",
                                        ident=str(ident) if ident is not None else self.t("remote_power.no_ident")))
        if enable:
            pw.idle_off = self._ask_yes(self.t("remote_power.3"), pw.idle_off)
            if pw.idle_off:
                pw.idle_off_hours = self._ask_int(self.t("remote_power.4"), pw.idle_off_hours, 1, 168)
            pw.notify = self._ask_yes(self.t("remote_power.5"), pw.notify)
            if pw.notify and not cfg.supervisor.notify_url:
                alerts_menu = menu_number("alerts")
                self.say(self.t("remote_power.no_ntfy", menu=alerts_menu))
        pw.enabled = enable
        saved = self._save_accounts(original, cfg, live=False)
        if stopped and not saved and self.yes(self.t("hwtest.6")):
            self.start()

    def rx_gain(self) -> None:
        """Gain audio de réception (étape 295) : `[audio] rx_gain_db` (son du poste vers TOUS les terminaux, visiteurs
        et diffusion compris) et limiteur du son reçu `rx_limiter` (crête à -1 dBFS, en service par défaut). Niveau
        reçu en ce moment lu dans le fichier d'état de la passerelle, valeur proposée pour viser RX_TARGET_DBFS."""
        loaded = self._load_for_edit()
        if loaded is None:
            return
        original, cfg = loaded
        a = cfg.audio
        on_off = lambda value: self.t("ask_yes.2") if value else self.t("ask_yes.3")   # noqa: E731
        self.say(self.t("rx_gain.1"))
        self.say(self.t("rx_gain.state", gain=f"{a.rx_gain_db:+g}", limiter=on_off(a.rx_limiter)))
        status = self._gateway_status()
        audio = status.audio if status is not None else {}
        level, used = audio.get("rx_db"), audio.get("rx_gain_db", a.rx_gain_db)
        if (isinstance(level, (int, float)) and not isinstance(level, bool) and level > RX_FLOOR_DBFS
                and isinstance(used, (int, float)) and not isinstance(used, bool)):
            suggest = max(RX_GAIN_LOW, min(RX_GAIN_HIGH, round(RX_TARGET_DBFS - (level - used))))
            self.say(self.t("rx_gain.level", level=round(level), target=RX_TARGET_DBFS, suggest=f"{suggest:+d}"))
            limited, frames = audio.get("rx_limited"), audio.get("rx_frames")
            if isinstance(limited, int) and isinstance(frames, int) and frames > 0 and limited > 0:
                self.say(self.t("rx_gain.limited", pct=max(1, round(100 * limited / frames))))
        else:
            self.say(self.t("rx_gain.no_level"))
        current = round(a.rx_gain_db)
        gain = self._ask_int(self.t("rx_gain.2"), current, RX_GAIN_LOW, RX_GAIN_HIGH)
        if gain != current:
            a.rx_gain_db = float(gain)
        a.rx_limiter = self._ask_yes(self.t("rx_gain.3"), a.rx_limiter)
        if not a.rx_limiter:
            self.say(self.t("rx_gain.warning"))
        self._save_accounts(original, cfg, live=False)

    def _power_declared(self, model: int, hamlib_dir: str) -> bool | None:
        """« set / get Power Stat » déclarés par Hamlib pour ce modèle ? None = rigctl illisible (Hamlib absent)."""
        from .gateway.cat.capabilities import CapabilitiesError, _run_dump_caps, parse_dump_caps
        try:
            caps = parse_dump_caps(_run_dump_caps(model, hamlib_dir), model)
        except (CapabilitiesError, OSError):
            return None
        return bool(caps.can_set_power and caps.can_get_power)

    def remote_console(self) -> None:
        """TRX Console sur le réseau (étape 233) : marche / arrêt, comptes opérateurs ADMINISTRATEURS, compte Linux du
        service (Debian). La console tourne sous ce compte, jamais root : sudo reste demandé dans le terminal."""
        from .config import SSH_USER_RE
        loaded = self._load_for_edit()
        if loaded is None:
            return
        original, cfg = loaded
        v, net = cfg.remote_console, cfg.network
        old_account = v.account
        operators = [c for c in cfg.clients if c.role == "operator" and c.password_hash]
        self.say(self.t("remote_console.1"))
        self.say(self.t("remote_console.state", on=self.t("ask_yes.2") if v.enabled else self.t("ask_yes.3"),
                        port=v.port, admins=", ".join(c.id for c in operators if c.admin) or "—"))
        v.enabled = self._ask_yes(self.t("remote_console.2"), v.enabled)
        if v.enabled:
            if not operators:
                accounts_menu = menu_number("operators")
                self.say(self.t("remote_console.no_operator", menu=accounts_menu))
                return
            while True:
                for n, c in enumerate(operators, 1):
                    self.say(f"  {n}) {c.id}" + (f"  [{self.t('remote_console.admin_mark')}]" if c.admin else ""))
                answer = self.ask(self.t("remote_console.admins")).strip()
                if not answer:
                    chosen = {c.id for c in operators if c.admin}
                else:
                    picks = answer.replace(",", " ").split()
                    if not all(x.isdigit() and 1 <= int(x) <= len(operators) for x in picks):
                        self.say(self.t("remote_console.admins_bad"))
                        continue
                    chosen = {operators[int(x) - 1].id for x in picks}
                if chosen:
                    break
                self.say(self.t("remote_console.admins_none"))
            for c in cfg.clients:
                c.admin = c.id in chosen
            if not IS_WINDOWS:
                current = v.account or os.environ.get("SUDO_USER") or getpass.getuser()
                while True:
                    answer = self.ask(self.t("remote_console.account", current=current)).strip() or current
                    if SSH_USER_RE.fullmatch(answer) and answer != "root":
                        v.account = answer
                        break
                    self.say(self.t("remote_console.account_bad", user=answer))
            cert_menu, network_menu = menu_number("certificate"), menu_number("access_network")
            if not (net.tls_cert and net.tls_key):
                self.say(self.t("remote_console.no_tls", menu=cert_menu))
            if net.gateway_bind in ("127.0.0.1", "::1", "localhost"):
                self.say(self.t("remote_console.local_only", menu=network_menu))
        if not self._save_accounts(original, cfg, live=not IS_WINDOWS):
            return
        if not IS_WINDOWS:
            self._remote_console_service(v.enabled, v.account, old_account)
        if v.enabled:
            from .setup_wizard import local_addresses
            urls = "  ".join(console_url(h, v.port) for h in local_addresses() or ["<station>"])
            self.say(self.t("remote_console.done", urls=urls))

    def _remote_console_service(self, on: bool, account: str, old_account: str) -> None:
        """Debian / Pi : service systemd `trx-console-web@<compte>` (sous ce compte, groupe trx pour lire la
        configuration et le certificat). Sous Windows, c'est le superviseur qui lance la console (mode géré)."""
        def systemctl(*args: str) -> int:
            # Dans le terminal de TRX Console sur le réseau, arrêter ou relancer son service tuerait ce menu même :
            # l'ordre part 5 s plus tard, par systemd (la page se reconnecte).
            later = ["systemd-run", "--quiet", "--on-active=5"] if os.environ.get("TRX_CONSOLE_WEB") else []
            return self.runner.run([*later, "systemctl", *args], admin=True)

        if old_account and (old_account != account or not on):
            systemctl("disable", "--now", f"trx-console-web@{old_account}")
        if not on:
            self.say(self.t("remote_console.stopped"))
            return
        try:
            import grp
            members = grp.getgrnam("trx").gr_mem
        except (ImportError, KeyError):
            members = None
        if members is not None and account not in members:
            self.runner.run(["usermod", "-aG", "trx", account], admin=True)
        self.runner.run(["systemctl", "enable", f"trx-console-web@{account}"], admin=True)
        if systemctl("restart", f"trx-console-web@{account}") != 0:
            self.say(self.t("remote_console.service_failed", account=account))

    def alerts(self) -> None:
        """Alertes sur le téléphone (ntfy) : adresse, langue, message « Station en service », envoi d'un essai.
        L'adresse est un secret (qui la connaît lit les alertes) : jamais affichée en entier."""
        while True:
            loaded = self._load_for_edit()
            if loaded is None:
                return
            original, cfg = loaded
            v = cfg.supervisor
            self.say(self.t("alerts.state", url=mask_notify_url(v.notify_url) or self.t("alerts.none"),
                            lang=v.notify_lang, alive=v.alive_every_h))
            choice = self.ask(self.t("alerts.menu")).strip()
            if not choice:
                return
            if choice == "4":
                self._alert_test(v.notify_url, v.notify_lang)
                continue
            if choice == "1":
                answer = self.ask(self.t("alerts.url")).strip()
                if not answer:
                    continue
                if answer == "-":
                    v.notify_url = ""
                elif answer.startswith(("https://", "http://")) and " " not in answer and len(answer) <= 300:
                    v.notify_url = answer
                else:
                    self.say(self.t("alerts.url_bad"))
                    continue
            elif choice == "2":
                answer = self.ask(self.t("alerts.lang", lang=v.notify_lang)).strip().lower()
                if answer not in ("", "fr", "en"):
                    self.say(self.t("alerts.lang_bad"))
                    continue
                v.notify_lang = answer or v.notify_lang
            elif choice == "3":
                answer = self.ask(self.t("alerts.alive", alive=v.alive_every_h)).strip().replace(",", ".")
                try:
                    hours = float(answer) if answer else v.alive_every_h
                except ValueError:
                    hours = -1.0
                if hours != 0 and not 0.25 <= hours <= 168:
                    self.say(self.t("alerts.alive_bad"))
                    continue
                v.alive_every_h = hours
            else:
                self.say(self.t("visitors.4"))
                continue
            self._save_accounts(original, cfg, live=False)

    def _alert_test(self, url: str, lang: str) -> None:
        """Envoie le code ORT-8025 à l'adresse donnée, tout de suite, et dit si l'envoi a échoué."""
        from .errors import codes
        from .supervisor import notify
        if not url:
            self.say(self.t("alerts.none_to_test"))
            return
        failures: list[str] = []

        def post(target: str, title: str, message: str, priority: str = "") -> None:
            try:
                notify._default_post(target, title, message, priority)
            except Exception as exc:                       # réseau, adresse, délai : le dire à l'opérateur
                failures.append(str(exc)[:200])
                raise

        sender = notify.Notifier(url, post=post, threaded=False, min_interval_s=0, lang=lang)
        sender.alert(codes.ORT_8025, heure=time.strftime("%H:%M"))
        self.say(self.t("alerts.test_failed", exc=failures[0]) if failures else self.t("alerts.test_sent"))

    def features_switch(self) -> None:
        """Interrupteur « En service » de chaque fonction : son réglage enabled ET sa place dans [modules] run. Une
        fonction qui demande d'autres réglages est refusée par la validation, avec le menu où les faire."""
        while True:
            loaded = self._load_for_edit()
            if loaded is None:
                return
            original, cfg = loaded
            self.say(self.t("features.title"))
            for n, (key, section, module, menu) in enumerate(FEATURES, 1):
                state = self.t("features.on") if feature_on(cfg, section, module) else self.t("features.off")
                where = self.t("features.where", menu=menu_number(menu)) if menu else ""
                label = self.t(key)
                self.say(f"  {n:>2}) [{state}] {label}{where}")
            answer = self.ask(self.t("features.ask")).strip()
            if not answer:
                return
            if not answer.isdigit() or not 1 <= int(answer) <= len(FEATURES):
                self.say(self.t("visitors.4"))
                continue
            _, section, module, _ = FEATURES[int(answer) - 1]
            set_feature(cfg, section, module, not feature_on(cfg, section, module))
            self._save_accounts(original, cfg, live=False)

    def indicator(self) -> None:
        """Debian : extension GNOME installée par install.sh (lecture seule), activée ou désactivée pour ce compte.
        Windows : indicateur près de l'horloge (trxstation.tray), lancé maintenant ou à chaque ouverture de session."""
        if IS_WINDOWS:
            self._indicator_windows()
            return
        tool = shutil.which("gnome-extensions")
        if tool is None:
            self.say(self.t("indicator.1"))
            return
        if not GNOME_EXTENSION_DIR.is_dir():
            self.say(self.t("indicator.2", gnome_extension_dir=GNOME_EXTENSION_DIR))
            return
        known = GNOME_EXTENSION_UUID in self.runner.output([tool, "list"]).split()
        if not known:
            self.say(self.t("indicator.3"))
            return
        enabled = GNOME_EXTENSION_UUID in self.runner.output([tool, "list", "--enabled"]).split()   # sans dépendre de la langue
        self.say(self.t("indicator.4", v=self.t("indicator.5") if enabled else self.t("indicator.6")))
        if enabled:
            if self.yes(self.t("indicator.7"), False):
                code = self.runner.run([tool, "disable", GNOME_EXTENSION_UUID])
                self.say(self.t("indicator.8") if code == 0 else self.t("indicator.9", code=code))
        elif self.yes(self.t("indicator.10"), True):
            code = self.runner.run([tool, "enable", GNOME_EXTENSION_UUID])
            self.say(self.t("indicator.11") if code == 0 else
                     self.t("indicator.12", code=code))

    def _indicator_windows(self) -> None:
        startup = windows_tray_startup()
        command = [windows_pythonw(), "-m", "trxstation.tray"]
        on = startup.exists()
        self.say(self.t("indicator.win.state", v=self.t("ask_yes.2") if on else self.t("ask_yes.3")))
        choice = self.ask(self.t("indicator.win.menu")).strip()
        if choice == "1":
            self.say(self.t("indicator.win.started") if self.runner.spawn(command) else self.t("indicator.win.failed"))
        elif choice == "2" and on:
            try:
                startup.unlink()
                self.say(self.t("indicator.win.off"))
            except OSError as exc:
                self.say(self.t("indicator.win.failed_link", exc=exc))
        elif choice == "2":
            quote = lambda s: "'" + str(s).replace("'", "''") + "'"      # chaîne PowerShell entre apostrophes
            script = (f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut({quote(startup)}); "
                      f"$l.TargetPath = {quote(command[0])}; $l.Arguments = '-m trxstation.tray'; "
                      f"$l.WorkingDirectory = {quote(self.config.parent)}; $l.Save()")
            code = self.runner.run(["powershell.exe", "-NoProfile", "-Command", script])
            self.say(self.t("indicator.win.on") if code == 0 else self.t("indicator.win.failed_link", exc=code))

    def cluster(self) -> None:
        if not self.config.exists():
            self.say(self.t("cluster.1"))
            return
        code = self.runner.run(self.module("trxstation.cluster.setup", "--config", str(self.config)), admin=True)
        if code == 0 and self.station_running() and self.yes(self.t("cluster.2")):
            self.start()

    def monitor(self) -> None:
        """Tableau de bord : dans un NOUVEL onglet ou une nouvelle fenêtre quand c'est possible (TRX Console reste ici),
        sinon dans ce terminal comme avant (SSH sans tmux)."""
        cmd = self.module("trxstation.monitor.main", "--config", str(self.config))
        opener = new_terminal_command(cmd, title="trx-monitor")
        if opener is not None and self.runner.spawn(opener):
            self.say(self.t("monitor.new_window"))
            return
        if os.environ.get("SSH_CONNECTION") and not os.environ.get("TMUX"):
            self.say(self.t("monitor.tmux_tip"))
        self.runner.run(cmd)

    def hwtest(self) -> None:
        if not self.config.exists():
            self.say(self.t("hwtest.1"))
            return
        from .audio_devices import desktop_audio_advice
        self.say(self.t("hwtest.2") + desktop_audio_advice() + "\n")
        self.say(self.t("hwtest.3"))
        choice = self.ask(self.t("hwtest.4")).strip()
        if choice not in ("1", "2"):
            self.say(self.t("hwtest.5"))
            return
        stopped = self.stop_for_exclusive_use(self.t("hwtest.why"))
        extra = ["--reception-seule"] if choice == "1" else []
        self.runner.run(self.module("trxstation.devtools.hwtest", "--config", str(self.config), *extra), admin=True)
        if stopped and self.yes(self.t("hwtest.6")):
            self.start()

    QUALIF_CHOICES = {"1": ("--plan",), "2": ("--explorer",), "3": ("--explorer", "--lecture-seule"),
                      "4": ("--sans-emission",), "5": (), "6": ("--terrain",)}
    QUALIF_OWN_STATION = {"1", "6"}      # 1 : sans poste ; 6 : la valise arrête et démarre la station elle-même

    def qualif(self) -> None:
        """trx-qualif pour un expert : cahier, exploration SANS émission, qualification avec ou sans émission.
        Seul le choix 5 peut émettre, et chaque émission y exige EMETTRE (PttController, comme trx-hwtest)."""
        if not self.config.exists():
            self.say(self.t("qualif.1"))
            return
        output = config_state_dir(self.config) / "qualifications"
        self.say(self.t("qualif.2", path=output))
        choice = self.ask(self.t("qualif.3")).strip()
        if choice not in self.QUALIF_CHOICES:
            self.say(self.t("qualif.4"))
            return
        stopped = choice not in self.QUALIF_OWN_STATION and self.stop_for_exclusive_use(self.t("qualif.why"))
        self.runner.run(self.module("trxstation.qualif.main", "--config", str(self.config), "--output", str(output),
                                    *self.QUALIF_CHOICES[choice]), admin=True)
        if stopped and self.yes(self.t("qualif.5")):
            self.start()

    def start(self) -> None:
        if not self.config.exists():
            self.say(self.t("start.1"))
            return
        code = self._start_station()
        self.say(self.t("start.2") if code == 0
                 else self.t("start.3"))

    def stop(self) -> None:
        code = self._stop_station()
        self.say(self.t("stop.1") if code == 0 else self.t("stop.2"))

    def journal(self) -> None:
        if IS_WINDOWS:
            self._journal_windows()
            return
        self.runner.run(["journalctl", "--no-pager", "-n", "80", "-o", "short", *[f"--unit={u}" for u in UNITS]], admin=True)

    def _journal_windows(self) -> None:
        """Windows : pas de journalctl ; dernières lignes des journaux du dossier `logs` (posé par l'installation, à
        côté de station.toml)."""
        folder = self.config.parent / "logs"
        files = sorted(folder.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []
        if not files:
            self.say(self.t("journal.windows_none", folder=folder))
            return
        for path in files[:3]:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-JOURNAL_LINES:]
            except OSError as exc:
                self.say(self.t("journal.windows_unreadable", path=path, exc=exc))
                continue
            self.say(self.t("journal.windows_file", path=path, n=len(lines)))
            self.say("\n".join(lines))

    def report(self) -> None:
        from .report import make_report
        try:
            path = make_report(config_path=self.config)
        except OSError as exc:
            self.say(self.t("report.1", exc=exc))
            return
        self.say(self.t("report.2", path=path))

    def clear_safe_mode(self) -> None:
        self.say(self.t("clear_safe_mode.1"))
        if not self.yes(self.t("clear_safe_mode.2"), False):
            return
        code = self.runner.run(self.module("trxstation.supervisor.main", "--config", str(self.config),
                                           "--clear-safe-mode"), admin=True)
        if code == 0:
            self.start()

    def update(self) -> None:
        if self._windows_updates():
            return
        state = self.update_state()
        if state is None:
            self.say(self.t("update.1"))
            if self.config.exists() and self.yes(self.t("update.2"), False):
                state = self.search_now()
            if state is None:
                return
        if not state.ok:
            self.say(self.t("update.3", clean_text=clean_text(state.error, 300, single_line=True)))
        release = self.offered(state)
        if release is None:
            checked = time.strftime("%d/%m/%Y %H:%M", time.localtime(state.checked_at)) if state.checked_at else "inconnue"
            self.say(self.t("update.4", installed=self.installed, checked=checked))
            if not (self.config.exists() and self.yes(self.t("update.5"), False)):
                return
            state = self.search_now()
            release = self.offered(state)
            if release is None:
                self.say(self.t("update.6") if state is not None and state.ok else self.t("update.7")
                         + clean_text(state.error if state is not None else self.t("update.8"), 300, single_line=True))
                return
        changes = self.changes_of(state, release)
        published = clean_text(release.published_at, 40, single_line=True)[:10]
        self.say(self.banner([self.t("update.9", version=release.version, v=self.t("update.10") if release.prerelease else '', installed=self.installed),
                              clean_text(release.name, 120, single_line=True) + (f" ({published})" if published else "")]))
        if len(changes) > 1:
            self.say(self.t("update.11", len=len(changes))
                     + ", ".join(c.version for c in reversed(changes)) + self.t("update.12"))
        if self.yes(self.t("update.13"), True):
            self.show_changes(changes)
            self.say(self.t("update.14", clean_text=clean_text(release.page_url, 200, single_line=True)))
        self.say(self.t("update.15", installed=self.installed))
        entered = self.ask(self.t("update.16", version=release.version)).strip()
        if entered != release.version:
            self.say(self.t("update.17", update_menu=UPDATE_MENU))
            return
        code = self.runner.run(self.module("trxstation.update.apply", "--config", str(self.config), "install",
                                           "--version", release.version), admin=True)
        done = self.t(self.reopen_key("update.18"), version=release.version)       # page : jamais « Quitte (q) »
        self.say(self._apply_result(code, done))

    def search_now(self) -> UpdateState | None:
        """Recherche immédiate par le service de la station (compte trx, jamais root) ; rien n'est installé."""
        self.say(self.t("search_now.1"))
        self.runner.run(["systemctl", "start", CHECK_UNIT], admin=True)
        return self.update_state()

    def changes_of(self, state: UpdateState, release) -> list[Change]:
        """Journal des changements, la plus récente d'abord ; à défaut, les seules notes de la version proposée."""
        low, high = parse_version(self.installed) or (), parse_version(release.version) or ()
        changes = [c for c in state.changes if low < (parse_version(c.version) or ()) <= high]
        if not any(c.version == release.version for c in changes):
            changes.insert(0, Change(release.version, release.name, release.published_at, release.notes))
        return changes

    def show_changes(self, changes: list[Change]) -> None:
        """Notes de chaque version, par pages (Entrée = suite, q = arrêter là)."""
        lines: list[str] = []
        for change in changes:
            published = clean_text(change.published_at, 40, single_line=True)[:10]
            lines += ["", self.t("show_changes.1", version=change.version, v=self.t("show_changes.2") + published if published else '', clean_text=clean_text(change.name, 120, single_line=True))]
            lines += (clean_text(change.notes, 4000) or self.t("show_changes.3")).split("\n")
        for start in range(0, len(lines), NOTES_PAGE_LINES):
            self.say("\n".join(lines[start:start + NOTES_PAGE_LINES]))
            if start + NOTES_PAGE_LINES < len(lines):
                if self.ask(self.t("show_changes.4")).strip().lower() in ("q", "quitter"):
                    return

    def banner(self, lines: list[str]) -> str:
        """Cadre bien visible (texte noir sur fond jaune dans un vrai terminal)."""
        width = max(len(line) for line in lines)
        body = ["*" * (width + 4)] + [f"* {line.ljust(width)} *" for line in lines] + ["*" * (width + 4)]
        if self.color:
            body = [f"\033[1;30;43m{line}\033[0m" for line in body]
        return "\n" + "\n".join("  " + line for line in body)

    def rollback(self) -> None:
        if self._windows_updates():
            return
        previous = self.previous()
        if previous is None:
            self.say(self.t("rollback.1"))
            return
        self.say(self.t("rollback.2", installed=self.installed, previous=previous))
        if not self.yes(self.t("rollback.3", previous=previous), False):
            return
        code = self.runner.run(self.module("trxstation.update.apply", "--config", str(self.config), "rollback"),
                               admin=True)
        done = self.t(self.reopen_key("rollback.4"), previous=previous)       # page : jamais « Quitte (q) »
        self.say(self._apply_result(code, done))

    def install_zip(self) -> None:
        """Paquet zip déposé sur la machine : choisi dans une liste, vérifié, installé comme une mise à jour."""
        if self._windows_updates():
            return
        packages = find_packages(self.home)
        if not packages:
            self.say(self.t("install_zip.1", home=self.home))
            return
        self.say(self.t("install_zip.2", installed=self.installed))
        for number, (version, path) in enumerate(packages, 1):
            signed = path.with_name(path.name + ".sig").is_file()
            self.say(f"  {number}) {version:<10} {self.t('install_zip.3') if signed else self.t('install_zip.4')}   {path}")
        choice = self.ask(self.t("install_zip.5")).strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(packages):
            self.say(self.t("install_zip.6"))
            return
        version, path = packages[int(choice) - 1]
        signed = path.with_name(path.name + ".sig").is_file()
        newer, current = parse_version(version) or (), parse_version(self.installed) or ()
        if newer < current:
            self.say(self.t("install_zip.7", version=version, installed=self.installed))
        elif newer == current:
            self.say(self.t("install_zip.8", version=version))
        self.say(self.t("install_zip.9", installed=self.installed))
        extra: list[str] = []
        if not signed:
            self.say(self.t("install_zip.10"))
            self.hint = {"kind": "word", "word": self.t("word.yes")}
            if not self.typed_word(self.ask(self.t("install_zip.type_word", word=self.t("word.yes"))), "word.yes", "OUI"):
                self.say(self.t("install_zip.11"))
                return
            extra = ["--sans-signature"]
        entered = self.ask(self.t("install_zip.12", version=version)).strip()
        if entered != version:
            self.say(self.t("install_zip.13"))
            return
        code = self.runner.run(self.module("trxstation.update.apply", "--config", str(self.config), "local",
                                           "--zip", str(path), *extra), admin=True)
        done = self.t(self.reopen_key("install_zip.14"), version=version)       # page : jamais « Quitte (q) »
        self.say(self._apply_result(code, done))

    def edit_config(self) -> None:
        """station.toml modifiée sur une COPIE (nano), validée, différences montrées, puis enregistrée par sudo
        avec ses droits d'origine ; l'ancienne version est gardée à côté. Une configuration invalide n'est jamais écrite."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say(self.t("edit_config.1"))
            return
        try:
            original = self.config.read_bytes()
        except OSError as exc:
            self.say(self.t("edit_config.2", config=self.config, exc=exc))
            return
        if not self.editor:
            self.say(self.t("edit_config.3"))
            return
        work = Path(tempfile.mkdtemp(prefix="trx-config-"))
        draft = work / "station.toml"
        try:
            draft.write_bytes(original)
            os.chmod(draft, 0o600)                         # contient les empreintes des mots de passe
            intro = self.t(self.page_key("edit_config.4"), config=self.config)   # page : pas de mode d'emploi de nano
            self.say(intro)
            while True:
                self.runner.run([self.editor, str(draft)])
                edited = draft.read_bytes()
                if edited == original:
                    self.say(self.t("edit_config.5"))
                    return
                try:
                    cfgmod.load(draft)
                    break
                except cfgmod.ConfigError as exc:
                    self.say(self.t("edit_config.6") + "\n  - ".join(exc.problems))
                    if not self.yes(self.t("edit_config.7"), True):
                        self.say(self.t("edit_config.8"))
                        return
            self._save_config(original, edited, draft)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ------------------------------------------------------------------ profils de poste (menu 2.3)

    def pairing(self) -> None:
        """Adresse, comptes et empreinte du certificat à vérifier dans l'application Android. Lecture seule ;
        aucun mot de passe affiché (la station ne les connaît pas en clair)."""
        from . import config as cfgmod
        from .setup_wizard import show_pairing
        if not self.config.exists():
            self.say(self.t("pairing.1"))
            return
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
            show_pairing(cfg, ask=self.ask, say=self.say)
        except PermissionError:                            # certificat réservé à la station : relu avec les droits d'administration
            self.runner.run(self.module("trxstation.setup_wizard", "--output", str(self.config), "--empreinte"), admin=True)
        except (OSError, ValueError, cfgmod.ConfigError) as exc:
            self.say(self.t("pairing.2", exc=exc))

    def sdr(self) -> None:
        """Module SDR (docs/sdr-cahier-des-charges.md) : recherche des SDR sur TOUS les ports USB et hubs (lecture
        seule : aucun SDR ouvert), choix du SDR de la station par son NUMÉRO DE SÉRIE, largeur, antenne, plafonds,
        mise en service. Ne pilote jamais le SDR : seul station.toml change (redémarrage proposé)."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say(self.t("sdr.1"))
            return
        while True:
            try:
                original = self.config.read_bytes()
                cfg, _ = cfgmod.load_unchecked(self.config)
            except (OSError, cfgmod.ConfigError) as exc:
                self.say(self.t("pairing.2", exc=exc))
                return
            sd = cfg.sdr
            state = self.t("sdr.on") if sd.enabled and "sdr" in cfg.modules.run else self.t("sdr.off")
            mhz = sd.sample_rate_hz // 1_000_000
            self.say(self.t("sdr.2", state=state, serial=sd.serial or "—", driver=sd.driver, mhz=mhz, ant=sd.antenna,
                            cpu=sd.max_cpu_pct, mem=sd.max_mem_mb))
            choice = self.ask(self.t("sdr.3")).strip()
            if not choice:
                return
            if choice == "1":
                self.runner.run(self.module("trxstation.sdr.devices", "--serial", sd.serial), admin=True)
                continue
            if choice == "7":
                self._sdr_rename(cfg, original)
                continue
            changed = {"2": self._sdr_choose, "3": self._sdr_rate, "4": self._sdr_antenna, "5": self._sdr_limits,
                       "6": self._sdr_toggle}.get(choice)
            if changed is None:
                self.say(self.t("operators.4"))
                continue
            if changed(cfg):
                self._save_accounts(original, cfg, live=False)       # redémarrage proposé : le module relit tout

    def _sdr_rename(self, cfg, original: bytes) -> None:
        """Nouveau numéro de série d'une clé RTL-SDR (numéros d'usine en double) : rtl_eeprom ne désigne une clé que par
        sa POSITION, donc UNE SEULE clé RTL-SDR branchée ; jamais une clé prise par un autre programme ; station
        arrêtée si c'est la sienne ; mémoire de la clé sauvegardée avant l'écriture ; rtl_eeprom demande aussi sa
        confirmation. La station suit le nouveau numéro si c'était sa clé."""
        found = self._sdr_found(cfg.sdr.serial)
        keys = [d for d in found if d.get("kind") == "rtlsdr"]
        if len(keys) != 1:
            self.say(self.t("sdr.14", n=len(keys)))
            return
        key = keys[0]
        if key.get("state") in ("pris", "noyau"):
            self.say(self.t("sdr.8"))
            return
        new = self.ask(self.t("sdr.15", old=key.get("serial") or "—")).strip()
        if not re.fullmatch(r"[A-Za-z0-9]{4,8}", new):
            if new:
                self.say(self.t("sdr.16"))
            return
        if any(d.get("serial") == new for d in found):
            self.say(self.t("sdr.17", serial=new))
            return
        if not self.yes(self.t("sdr.18", old=key.get("serial") or "—", new=new), False):
            return
        mine = bool(key.get("serial")) and key.get("serial") == cfg.sdr.serial
        stopped = mine and self.stop_for_exclusive_use(self.t("sdr.why"))
        state_dir = Path(cfg.supervisor.state_dir) / "sdr"
        backup = state_dir / f"eeprom-{key.get('serial') or 'sans-numero'}-{time.strftime('%Y%m%d-%H%M%S')}.bin"
        self._make_dir(state_dir)
        # rtl_eeprom rend le code 1 MÊME quand il réussit (relevé sur minix-bzh, étape 200) : on vérifie le RÉSULTAT,
        # jamais le code de sortie : sauvegarde = fichier non vide ; écriture = nouveau numéro relu dans la clé
        self.runner.run(["rtl_eeprom", "-d", "0", "-r", str(backup)], admin=True)
        if self.runner.run(["test", "-s", str(backup)], admin=True) != 0:
            self.say(self.t("sdr.19"))
        elif (self.runner.run(["rtl_eeprom", "-d", "0", "-s", new], admin=True) is None
              or not self._rtl_serial_is(new)):
            self.say(self.t("sdr.19"))
        else:
            self.say(self.t("sdr.20", backup=backup))
            if mine:
                cfg.sdr.serial = new
                self._save_accounts(original, cfg, live=False)
        if stopped and self.yes(self.t("sdr.21"), True):
            self.start()

    def _rtl_serial_is(self, serial: str) -> bool:
        """Numéro relu dans la mémoire de la clé (rtl_eeprom sans option n'écrit rien) ; droits d'administration au
        besoin (le mot de passe vient d'être donné pour l'écriture)."""
        cmd = ["sh", "-c", "rtl_eeprom -d 0 2>&1"]                  # l'outil écrit tout sur la sortie d'erreur
        if not getattr(self.runner, "is_root", False):
            cmd = ["sudo", "-n", *cmd]
        out = self.runner.output(cmd)
        return re.search(r"^Serial number:\s*" + re.escape(serial) + r"\s*$", out, re.M) is not None

    def _sdr_found(self, serial: str) -> list[dict]:
        out = self.runner.output(self.module("trxstation.sdr.devices", "--json", "--serial", serial))
        try:
            return list(json.loads(out.splitlines()[-1]).get("devices", [])) if out else []
        except (ValueError, IndexError, AttributeError):
            return []

    def _sdr_choose(self, cfg) -> bool:
        found = self._sdr_found(cfg.sdr.serial)
        if not found:
            self.say(self.t("sdr.4"))
            return False
        for i, d in enumerate(found, 1):
            self.say(f"  {i}) {d.get('model', '?')}  {d.get('serial') or '—'}  [{d.get('state', '?')}]  {d.get('location') or ''}")
        answer = self.ask(self.t("sdr.5")).strip()
        if not answer.isdigit() or not 1 <= int(answer) <= len(found):
            return False
        d = found[int(answer) - 1]
        if not d.get("serial") or d.get("duplicate"):
            self.say(self.t("sdr.7"))
            return False
        if d.get("state") in ("pris", "noyau") and d.get("serial") != cfg.sdr.serial:
            self.say(self.t("sdr.8"))
            return False
        from .config import sdr_rates
        driver = "rtlsdr" if d.get("kind") == "rtlsdr" else "sdrplay"
        cfg.sdr.serial, cfg.sdr.driver = d["serial"], driver
        if cfg.sdr.sample_rate_hz not in sdr_rates(driver):            # largeur adaptée au type de SDR
            cfg.sdr.sample_rate_hz = 2_048_000 if driver == "rtlsdr" else 2_000_000
        return True

    def _sdr_rate(self, cfg) -> bool:
        from .config import sdr_rates
        rates = sdr_rates(cfg.sdr.driver)
        shown = [f"{r / 1e6:g}" for r in rates]
        answer = self.ask(self.t("sdr.9", choices=", ".join(shown))).strip().replace(",", ".")
        if answer not in shown:
            return False
        cfg.sdr.sample_rate_hz = rates[shown.index(answer)]
        return True

    def _sdr_antenna(self, cfg) -> bool:
        if cfg.sdr.driver == "rtlsdr":
            self.say(self.t("sdr.6"))
            return False
        answer = self.ask(self.t("sdr.10")).strip().upper()
        if answer not in ("A", "B"):
            return False
        cfg.sdr.antenna = answer
        return True

    def _sdr_limits(self, cfg) -> bool:
        cpu = self.ask(self.t("sdr.11", v=cfg.sdr.max_cpu_pct)).strip()
        mem = self.ask(self.t("sdr.12", v=cfg.sdr.max_mem_mb)).strip()
        if cpu.isdigit():
            cfg.sdr.max_cpu_pct = int(cpu)
        if mem.isdigit():
            cfg.sdr.max_mem_mb = int(mem)
        return cpu.isdigit() or mem.isdigit()            # bornes vérifiées à l'enregistrement (configuration validée)

    def _sdr_toggle(self, cfg) -> bool:
        if cfg.sdr.enabled and "sdr" in cfg.modules.run:
            cfg.sdr.enabled = False
            cfg.modules.run = [m for m in cfg.modules.run if m != "sdr"]
            return True
        if not cfg.sdr.serial:
            self.say(self.t("sdr.13"))
            return False
        cfg.sdr.enabled = True
        if "sdr" not in cfg.modules.run:
            cfg.modules.run = [*cfg.modules.run, "sdr"]
        return True

    def certificate(self) -> None:
        """Certificat HTTPS de la station : état, et passage à l'AUTORITÉ DE LA STATION (étape 195) : une fois installée
        sur un appareil, plus d'avertissement du navigateur et le mot de passe peut être retenu. Refaire le certificat
        change l'empreinte épinglée par l'application Android (nouvel appairage, menu 4.1)."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say(self.t("certificate.1"))
            return
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
        except (OSError, cfgmod.ConfigError) as exc:
            self.say(self.t("pairing.2", exc=exc))
            return
        n = cfg.network
        if not n.tls_cert:
            self.say(self.t("certificate.2"))
            return
        info = self._certificate_info(n.tls_cert)
        if info is None:
            self.say(self.t("certificate.3"))
        else:
            kind = self.t("certificate.kind_ca") if info["authority"] else self.t("certificate.kind_self")
            self.say(self.t("certificate.4", kind=kind, hosts=", ".join(info["hosts"]) or "?", until=info["until"]))
            if info["authority"] and info["hosts"]:
                url = f"https://{info['hosts'][0]}:{n.gateway_port}/station-ca.crt"
                self.say(self.t("certificate.5", url=url))
        choice = self.ask(self.t("certificate.6")).strip()
        if choice not in ("1", "2"):
            return
        extra = self.ask(self.t("certificate.7")).split() if choice == "2" else []
        if not self.yes(self.t("certificate.8"), False):
            return
        code = self.runner.run(self.module("trxstation.setup_wizard", "--output", str(self.config),
                                           "--autorite-station", *extra), admin=True)
        if code != 0:
            self.say(self.t("certificate.9"))
            return
        pairing_menu = menu_number("pairing")
        self.say(self.t("certificate.10", menu=pairing_menu))
        if self.yes(self.t("certificate.11"), True):
            self.start()

    @staticmethod
    def _certificate_info(path: str) -> dict | None:
        """Noms, échéance et origine (autorité de la station ou non) du certificat ; None s'il est illisible."""
        try:
            from cryptography import x509

            from .gateway.api.tls import CA_CERT
            cert = x509.load_pem_x509_certificate(Path(path).read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            hosts = [str(i) for i in san.get_values_for_type(x509.IPAddress)] + list(san.get_values_for_type(x509.DNSName))
            ca_file = Path(path).parent / CA_CERT
            authority = ca_file.is_file() and x509.load_pem_x509_certificate(ca_file.read_bytes()).subject == cert.issuer
        except Exception:                                  # illisible (droits), module absent, format inattendu
            return None
        return {"hosts": hosts, "until": cert.not_valid_after_utc.date().isoformat(), "authority": bool(authority)}

    def profiles(self) -> None:
        if not self.config.exists():
            self.say(self.t("profiles.1"))
            return
        self._list_profiles()
        self.say(self.t("profiles.2"))
        choice = self.ask(self.t("profiles.3")).strip().lower()
        action = {"1": self._save_profile, "2": self._load_profile, "3": self._delete_profile}.get(choice)
        if action is not None:
            action()

    def _list_profiles(self) -> list[tuple[Path, prof.Profile | None, str]]:
        from . import config as cfgmod
        found = prof.list_profiles(self.config)
        self.say(self.t("list_profiles.1"))
        if not found:
            self.say(self.t("list_profiles.2"))
            return found
        try:
            current, _ = cfgmod.load_unchecked(self.config)
        except (OSError, cfgmod.ConfigError):
            current = None
        self.say(self.t("list_profiles.3"))
        for number, (path, profile, problem) in enumerate(found, 1):
            if profile is None:
                self.say(self.t("list_profiles.4", number=number, name=path.name, problem=problem))
                continue
            if profile.format > prof.PROFILE_FORMAT:
                state = self.t("list_profiles.5")
            elif profile.format < prof.PROFILE_FORMAT:
                state = self.t("list_profiles.6")
            else:
                state = ""
            rig = profile.sections.get("rig")
            model = rig.get("model", "?") if isinstance(rig, dict) else "?"
            here = self.t("list_profiles.7") if current is not None and prof.same_rig(current, profile) else ""
            self.say(self.t("list_profiles.8", number=number, name=profile.name, model=model, saved_at=profile.saved_at, version=profile.version, v=' ; ' + state if state else '', here=here))
        return found

    def _choose_profile(self, found, verb: str):
        if not found:
            return None
        choice = self.ask(self.t("choose_profile.1", verb=verb)).strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(found):
            self.say(self.t("choose_profile.2"))
            return None
        return found[int(choice) - 1]

    def _save_profile(self) -> None:
        from . import config as cfgmod
        try:
            cfg = cfgmod.load(self.config)
        except (OSError, cfgmod.ConfigError) as exc:
            self.say(self.t("save_profile.1", exc=exc))
            return
        name = self.ask(self.t("save_profile.2")).strip()
        if not name:
            self.say(self.t("save_profile.3"))
            return
        if not prof.valid_name(name):
            self.say(self.t("save_profile.4"))
            return
        target = prof.folder_for(self.config) / prof.file_name(name)
        if target.exists() and not self.yes(self.t("save_profile.5", name=target.name), False):
            self.say(self.t("save_profile.6"))
            return
        text = prof.render(name, cfg, self.installed, time.strftime("%Y-%m-%d %H:%M"))
        work = Path(tempfile.mkdtemp(prefix="trx-profil-"))
        try:
            draft = work / target.name
            draft.write_text(text, encoding="utf-8")
            st = self.config.stat()
            code = self._install_file(draft, target, mode=f"{st.st_mode & 0o777:o}", like=self.config, parents=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.say(self.t("save_profile.7", name=name, target=target) if code == 0 else
                 self.t("save_profile.8", code=code))

    def _load_profile(self) -> None:
        picked = self._choose_profile(self._list_profiles(), self.t("verb.load"))
        if picked is None:
            return
        path, profile, problem = picked
        if profile is None:
            self.say(self.t("load_profile.1", problem=problem))
            return
        if self.transmitting():
            self.say(self.t("load_profile.2"))
            return
        try:
            original = self.config.read_bytes()
            _, text = prof.apply(original.decode("utf-8"), profile)
        except prof.ProfileError as exc:
            self.say(self.t("load_profile.3", exc=exc))
            return
        except OSError as exc:
            self.say(self.t("load_profile.4", config=self.config, exc=exc))
            return
        if profile.format < prof.PROFILE_FORMAT:
            self.say(self.t("load_profile.5", format=profile.format, profile_format=prof.PROFILE_FORMAT))
        rig = profile.sections.get("rig")
        port = str(rig.get("port", "")) if isinstance(rig, dict) else ""
        if port and not Path(port).exists():
            self.say(self.t("load_profile.6", port=port))
        edited = text.encode("utf-8")
        if edited == original:
            self.say(self.t("load_profile.7"))
            return
        work = Path(tempfile.mkdtemp(prefix="trx-config-"))
        try:
            draft = work / "station.toml"
            draft.write_bytes(edited)
            os.chmod(draft, 0o600)                         # contient les empreintes des mots de passe
            self.say(self.t("load_profile.8", name=profile.name))
            self._save_config(original, edited, draft)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _delete_profile(self) -> None:
        picked = self._choose_profile(self._list_profiles(), self.t("verb.delete"))
        if picked is None:
            return
        path, profile, _ = picked
        if not self.yes(self.t("delete_profile.1", v=profile.name if profile else path.name), False):
            self.say(self.t("delete_profile.2"))
            return
        code = self._remove_file(path)
        self.say(self.t("delete_profile.3") if code == 0 else self.t("delete_profile.4", code=code))

    def transmitting(self) -> bool:
        """Émission en cours d'après l'état publié par la passerelle ; en cas de doute (état illisible), oui."""
        from . import config as cfgmod
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
            status_path = Path(cfg.supervisor.status_path)
            if not status_path.exists() or time.time() - status_path.stat().st_mtime > 10:
                return False                               # passerelle arrêtée : pas d'émission de la station
            status = json.loads(status_path.read_text(encoding="utf-8"))
            state, rig_keyed = status.get("ptt", {}).get("state", "RX"), status.get("rig", {}).get("ptt")
        except (OSError, ValueError, AttributeError, cfgmod.ConfigError):
            return True
        return state != "RX" or rig_keyed is True                 # émission de la station ou au micro du poste

    def _save_config(self, original: bytes, edited: bytes, draft: Path, live: bool = False) -> bool:
        """Différences montrées, confirmation, sauvegarde de l'ancienne version, enregistrement par sudo avec les
        droits d'origine. `draft` est déjà validé. `live` : la passerelle relit d'elle-même ce qui change (comptes,
        [access]) : pas de redémarrage proposé. Vrai si enregistré."""
        before = original.decode("utf-8", "replace").splitlines()
        after = edited.decode("utf-8", "replace").splitlines()
        diff = [hide_secret_line(line) for line in difflib.unified_diff(before, after, "avant", "après", n=0, lineterm="")
                if not line.startswith(("---", "+++", "@@"))]
        self.say(self.t("save_config.1") + "\n".join("  " + line for line in diff[:MAX_DIFF_LINES])
                 + (self.t("save_config.2", v=len(diff) - MAX_DIFF_LINES) if len(diff) > MAX_DIFF_LINES else ""))
        if not self.yes(self.t("save_config.3"), False):
            self.say(self.t("save_config.4"))
            return False
        if self.config.read_bytes() != original:
            self.say(self.t("save_config.5"))
            return False
        st = self.config.stat()
        backup = self.config.with_name(f"{self.config.name}.avant-modification-{time.strftime('%Y%m%d-%H%M%S')}")
        if IS_WINDOWS:                     # ni sudo ni cp / install : le compte de l'installation a les droits (ACL)
            try:
                shutil.copy2(self.config, backup)
            except OSError:
                self.say(self.t("save_config.6"))
                return False
            try:
                self.config.write_bytes(draft.read_bytes())       # en place : le fichier garde ses droits
            except OSError as exc:
                self.say(self.t("save_config.7", code=exc))
                return False
        else:
            if self.runner.run(["cp", "-p", str(self.config), str(backup)], admin=True) != 0:
                self.say(self.t("save_config.6"))
                return False
            code = self.runner.run(["install", "-m", f"{st.st_mode & 0o777:o}", "-o", str(st.st_uid), "-g",
                                    str(st.st_gid), str(draft), str(self.config)], admin=True)
            if code != 0:
                self.say(self.t("save_config.7", code=code))
                return False
        self.say(self.t("save_config.8", backup=backup))
        if live:
            self.say(self.t("save_config.9"))
        elif self.station_running():
            if self.yes(self.t("save_config.10")):
                self.start()
        else:
            self.say(self.t("save_config.11"))
        return True

    # ------------------------------------------------------------------ visiteurs (menu 4.2)

    def swr_report(self) -> None:
        """Dernière mesure de TOS (state_dir/swr.json) : lecture seule. La console ne lance JAMAIS de mesure (un outil ne
        peut que couper) : la mesure se lance depuis la page ou l'application."""
        from .swr.plan import level
        from .swr.store import SwrStore
        last = SwrStore(config_state_dir(self.config) / "swr.json").last()
        if not last or not last.get("points"):
            self.say(self.t("swr_report.1"))
            return
        when = time.strftime("%d/%m/%Y %H:%M", time.localtime(last.get("at") or 0))
        power = f"{last['power_w']} W" if last.get("power_w") else f"{last.get('power_pct')} %"
        out = [self.t("swr_report.2", when=when, power=power, get=last.get('fm_mode')),
               self.t("swr_report.3", v=last['low_hz'] / 1e6, v2=last['high_hz'] / 1e6, v3=last['step_hz'] // 1000), ""]
        marks = {"good": "", "fair": self.t("swr_report.fair"), "bad": self.t("swr_report.4")}
        for p in last["points"]:
            swr = p.get("swr")
            if swr is None:
                text = {"out_of_band": self.t("swr_report.5"), "unread": self.t("swr_report.6")}.get(p.get("status"), p.get("status") or "—")
                out.append(f"  {p['hz'] / 1e6:9.3f} MHz   {text}")
            else:
                bar = "#" * max(1, min(40, round((min(swr, 5.0) - 1) * 10)))
                out.append(f"  {p['hz'] / 1e6:9.3f} MHz   {swr:4.2f}  {bar}{marks[level(swr)]}"
                           + (self.t("swr_report.7") if p.get("status") == "reduced" else ""))
        best = last.get("best")
        if best:
            out.append(self.t("swr_report.8", swr=best['swr'], v=best['hz'] / 1e6))
        if last.get("reason") and last["reason"] != "done":
            out.append(self.t("swr_report.9", v=last.get('detail') or last['reason']))
        for diff in last.get("differences") or []:
            out.append(self.t("swr_report.10", diff=diff))
        self.say("\n".join(out))

    def visitors(self) -> None:
        """Visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md) : réglages [access], comptes
        role = "listener", pseudos, connectés et déconnexion. station.toml passe par le chemin validé du menu 8.1
        (réécrit dans sa forme standard) ; la passerelle le relit sans redémarrer."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say(self.t("visitors.1"))
            return
        while True:
            try:
                original = self.config.read_bytes()
                cfg, _ = cfgmod.load_unchecked(self.config)
            except (OSError, cfgmod.ConfigError) as exc:
                self.say(self.t("visitors.2", config=self.config, exc=exc))
                return
            self.say(self._visitors_summary(cfg))
            choice = self.ask(self.t("visitors.3")).strip()
            if not choice:
                return
            actions = {"1": self._visitor_settings, "2": self._visitor_create, "3": self._visitor_edit,
                       "4": self._visitor_delete}            # pseudo d'un opérateur : menu 4.3 (comptes opérateurs)
            if choice == "5":
                self._visitor_kick(cfg)
                continue
            if choice == "6":
                self._visitor_reopen(cfg)
                continue
            action = actions.get(choice)
            if action is None:
                self.say(self.t("visitors.4"))
                continue
            if action(cfg):
                self._save_accounts(original, cfg)

    def _visitors_summary(self, cfg) -> str:
        a = cfg.access
        listeners = [c for c in cfg.clients if c.role == "listener"]
        lines = [self.t("visitors_summary.1"),
                 self.t("visitors_summary.2", v=self.t("visitors_summary.3") + str(a.max_listeners) + self.t("visitors_summary.4") if a.max_listeners else self.t("visitors_summary.5")),
                 self.t("visitors_summary.6") + (self.t("visitors_summary.7", operator_grace_s=a.operator_grace_s)
                                                if a.listeners_need_operator else self.t("visitors_summary.8")),
                 self.t("visitors_summary.9") + (self.t("visitors_summary.10") if a.listeners_outside_bands else self.t("visitors_summary.11")),
                 self.t("visitors_summary.12") + (", ".join(self._account_label(c) for c in listeners) or self.t("visitors_summary.13"))]
        presence = self._presence()
        if isinstance(presence.get("open"), bool):        # commutateur de l'opérateur (page, application)
            lines.append(self.t("visitors_summary.14") + (self.t("visitors_summary.15") if presence["open"] else
                                                       self.t("visitors_summary.16")))
        suspended = presence.get("suspended")
        if isinstance(suspended, dict):
            lines.append(self.t("visitors_summary.17") + str(suspended.get("message", ""))[:300])
        connected = [c for c in self._connected() if c.get("role") == "listener"]
        lines.append(self.t("visitors_summary.18") + (", ".join(
            self.t("visitors_summary.19", get=c.get('pseudo', '?'), get2=c.get('id', '?'), get3=c.get('source', '?'), v=int(c.get('since_s', 0)) // 60)
            for c in connected) or self.t("visitors_summary.20")))
        return "\n".join(lines)

    def _account_label(self, c) -> str:
        notes = [n for n in (self.t("account_label.1") if not c.enabled else "", self.t("account_label.until", expires=c.expires) if c.expires else "") if n]
        return f"{c.id} « {c.pseudo or self.t('account_label.2')} »" + (f" ({', '.join(notes)})" if notes else "")

    def _connected(self) -> list[dict]:
        """Connexions publiées par la passerelle (fichier d'état) ; [] si elle est arrêtée."""
        items = self._presence().get("connections", [])
        return [c for c in items if isinstance(c, dict)] if isinstance(items, list) else []

    def _presence(self) -> dict:
        """`presence` du fichier d'état de la passerelle ; {} si elle est arrêtée."""
        status = self._gateway_status()
        return status.presence if status is not None else {}

    def _gateway_status(self):
        """Fichier d'état de la passerelle (`status.GatewayStatus`) ; None si elle est arrêtée ou l'état illisible."""
        from . import config as cfgmod
        from .status import read_status
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
            path = Path(cfg.supervisor.status_path)
            if not path.exists() or time.time() - path.stat().st_mtime > STATUS_FRESH_S:
                return None
            return read_status(path)
        except (OSError, cfgmod.ConfigError):
            return None

    def _ask_int(self, question: str, current: int, low: int, high: int) -> int:
        while True:
            self.hint = {"kind": "int", "low": low, "high": high, "current": current}
            answer = self.ask(self.t("ask_int.1", question=question, low=low, high=high, current=current)).strip()
            if not answer:
                return current
            if re.fullmatch(r"-?\d{1,5}", answer) and low <= int(answer) <= high:     # négatif : gains en dB
                return int(answer)
            self.say(self.t("ask_int.2", low=low, high=high))

    def _ask_yes(self, question: str, current: bool) -> bool:
        while True:
            self.hint = {"kind": "yesno", "default": current}
            answer = self.ask(self.t("ask_yes.1", question=question, v=self.t("ask_yes.2") if current else self.t("ask_yes.3"))).strip()
            if not answer:
                return current
            value = yes_no(answer)
            if value is not None:
                return value
            self.say(self.t("ask_yes.4"))

    def _visitor_settings(self, cfg) -> bool:
        a = cfg.access
        before = (a.max_listeners, a.listeners_need_operator, a.operator_grace_s, a.listeners_outside_bands,
                  a.listener_spectrum_fps)
        a.max_listeners = self._ask_int(self.t("visitor_settings.1"), a.max_listeners, 0, 20)
        a.listeners_need_operator = self._ask_yes(self.t("visitor_settings.2"),
                                                  a.listeners_need_operator)
        if a.listeners_need_operator:
            a.operator_grace_s = self._ask_int(self.t("visitor_settings.3"), a.operator_grace_s, 0, 600)
        a.listeners_outside_bands = self._ask_yes(self.t("visitor_settings.4"), a.listeners_outside_bands)
        a.listener_spectrum_fps = self._ask_int(self.t("visitor_settings.5"),
                                                a.listener_spectrum_fps, 1, 20)
        return before != (a.max_listeners, a.listeners_need_operator, a.operator_grace_s, a.listeners_outside_bands,
                          a.listener_spectrum_fps)

    def _ask_pseudo(self, cfg, current: str = "", login: str = "") -> str | None:
        """Pseudo montré aux autres connectés ; None = abandon. `login` : identifiant du compte en création (pas
        encore dans la configuration), refusé comme pseudo dès la question."""
        from .config import PSEUDO_MAX
        while True:
            answer = self.ask(self.t("ask_pseudo.1", pseudo_max=PSEUDO_MAX)
                              + (self.t("ask_pseudo.2", current=current) if current else self.t("ask_pseudo.3")) + self.t("ask_pseudo.4")).strip()
            if answer == "-":
                return None
            if not answer:
                return current
            if len(answer) > PSEUDO_MAX or any(ord(ch) < 32 for ch in answer):
                self.say(self.t("ask_pseudo.5", pseudo_max=PSEUDO_MAX))
            elif any(answer.casefold() == c.id.casefold() for c in cfg.clients) or answer.casefold() == login.casefold():
                self.say(self.t("ask_pseudo.6"))
            else:
                return answer

    def _ask_new_password(self, login: str) -> str | None:
        from .passwords import generate_password, password_problem
        while True:
            self.hint = {"kind": "password", "generate": True, "abandon": "-"}
            answer = self.ask(self.t("ask_new_password.1")).strip()
            if answer == "-":
                return None
            if not answer:
                answer = generate_password()
                self.say(self.t("ask_new_password.2", answer=answer))
                return answer
            problem = password_problem(answer, login)
            if problem is None:
                return answer
            self.say(self.t("ask_new_password.3", problem=problem))

    def _ask_expiry(self, current: str) -> str | None:
        from datetime import date
        while True:
            answer = self.ask(self.t("ask_expiry.1") + (current or self.t("ask_expiry.never")) + self.t("ask_expiry.2")).strip()
            if answer == "-":
                return None
            if not answer:
                return current
            if answer == "0":
                return ""
            try:
                date.fromisoformat(answer)
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", answer):
                    return answer
            except ValueError:
                pass
            self.say(self.t("ask_expiry.3"))

    def _pick_account(self, cfg, role: str, verb: str):
        accounts = [c for c in cfg.clients if c.role == role]
        if not accounts:
            self.say(self.t("pick_account.1") + (self.t("pick_account.visitor") if role == "listener" else self.t("pick_account.2")))
            return None
        for i, c in enumerate(accounts, 1):
            self.say(f"  {i}) {self._account_label(c)}")
        answer = self.ask(self.t("pick_account.3", verb=verb)).strip()
        if answer.isdigit() and 1 <= int(answer) <= len(accounts):
            return accounts[int(answer) - 1]
        return None

    def _visitor_create(self, cfg) -> bool:
        from .config import ClientAuth
        from .passwords import hash_password
        login = self.ask(self.t("visitor_create.1")).strip()
        if not login:
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", login) or any(c.id.casefold() == login.casefold() for c in cfg.clients):
            self.say(self.t("visitor_create.2"))
            return False
        pseudo = self._ask_pseudo(cfg, login=login)
        expires = None if pseudo is None else self._ask_expiry("")
        password = None if expires is None else self._ask_new_password(login)
        if password is None:
            return False
        if pseudo and pseudo.casefold() == login.casefold():
            self.say(self.t("visitor_create.3"))
            return False
        cfg.clients.append(ClientAuth(id=login, password_hash=hash_password(password), role="listener", pseudo=pseudo,
                                      expires=expires))
        if not cfg.access.max_listeners:
            self.say(self.t("visitor_create.4"))
        return True

    def _visitor_edit(self, cfg) -> bool:
        from .passwords import hash_password
        account = self._pick_account(cfg, "listener", self.t("verb.edit"))
        if account is None:
            return False
        pseudo = self._ask_pseudo(cfg, account.pseudo)
        if pseudo is None:
            return False
        enabled = self._ask_yes(self.t("visitor_edit.1"), account.enabled)
        expires = self._ask_expiry(account.expires)
        if expires is None:
            return False
        changed = (pseudo, enabled, expires) != (account.pseudo, account.enabled, account.expires)
        account.pseudo, account.enabled, account.expires = pseudo, enabled, expires
        if self.yes(self.t("visitor_edit.2"), False):
            password = self._ask_new_password(account.id)
            if password is None:
                return False
            account.password_hash, account.token, changed = hash_password(password), "", True
        return changed

    def _visitor_delete(self, cfg) -> bool:
        account = self._pick_account(cfg, "listener", self.t("verb.delete"))
        if account is None or not self.yes(self.t("visitor_delete.1", id=account.id), False):
            return False
        cfg.clients.remove(account)
        return True

    # ------------------------------------------------------------------ comptes opérateurs (menu 4.3)

    def operators(self) -> None:
        """Comptes opérateurs, UN PAR APPAREIL (PC, téléphone, tablette) : un même compte ouvert sur un second appareil
        ferme la connexion du premier (et coupe son émission). Ajout, mot de passe, activation, pseudo, suppression ;
        jamais sans un opérateur actif. Même chemin validé que le menu 4.2 : la passerelle relit sans redémarrer et
        ferme aussitôt la connexion d'un compte désactivé, supprimé ou dont le mot de passe a changé."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say(self.t("operators.1"))
            return
        while True:
            try:
                original = self.config.read_bytes()
                cfg, _ = cfgmod.load_unchecked(self.config)
            except (OSError, cfgmod.ConfigError) as exc:
                self.say(self.t("operators.2", config=self.config, exc=exc))
                return
            self.say(self._operators_summary(cfg))
            choice = self.ask(self.t("operators.3")).strip()
            if not choice:
                return
            if choice == "6":
                self.pairing()
                continue
            action = {"1": self._operator_create, "2": self._operator_password, "3": self._operator_toggle,
                      "4": self._operator_pseudo, "5": self._operator_delete}.get(choice)
            if action is None:
                self.say(self.t("operators.4"))
                continue
            login = action(cfg)
            if not login:
                continue
            saved = self._save_accounts(original, cfg)
            if saved and choice == "1" and self.yes(self.t("operators.5", id=login), True):
                self._pair_account(login)

    def _operators_summary(self, cfg) -> str:
        operators = [c for c in cfg.clients if c.role == "operator"]
        connected = {c.get("id") for c in self._connected() if c.get("role") != "listener"}
        lines = [self.t("operators_summary.1"), self.t("operators_summary.2")]
        for c in operators:
            lines.append("  - " + self._account_label(c) + (self.t("operators_summary.3") if c.id in connected else ""))
        if not operators:
            lines.append(self.t("operators_summary.4"))
        return "\n".join(lines)

    def _active_operators(self, cfg) -> list:
        from datetime import date
        today = date.today()
        return [c for c in cfg.clients if c.role == "operator" and c.enabled is True and not c.expired(today)]

    def _warn_if_connected(self, login: str) -> None:
        if any(c.get("id") == login for c in self._connected()):
            self.say(self.t("operators.connected", id=login))

    def _operator_create(self, cfg) -> str:
        from .config import ClientAuth
        from .passwords import hash_password
        self.say(self.t("operator_create.1"))
        login = self.ask(self.t("operator_create.2")).strip()
        if not login:
            return ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", login) or any(c.id.casefold() == login.casefold() for c in cfg.clients):
            self.say(self.t("operator_create.3"))
            return ""
        if any(c.pseudo and c.pseudo.casefold() == login.casefold() for c in cfg.clients):
            self.say(self.t("operator_create.4"))
            return ""
        pseudo = self._ask_pseudo(cfg, login=login)
        password = None if pseudo is None else self._ask_new_password(login)
        if password is None:
            return ""
        if pseudo and pseudo.casefold() == login.casefold():
            self.say(self.t("visitor_create.3"))
            return ""
        cfg.clients.append(ClientAuth(id=login, password_hash=hash_password(password), pseudo=pseudo))
        return login

    def _operator_password(self, cfg) -> str:
        from .passwords import hash_password
        account = self._pick_account(cfg, "operator", self.t("verb.edit"))
        if account is None:
            return ""
        password = self._ask_new_password(account.id)
        if password is None:
            return ""
        self._warn_if_connected(account.id)
        account.password_hash, account.token = hash_password(password), ""
        return account.id

    def _operator_toggle(self, cfg) -> str:
        account = self._pick_account(cfg, "operator", self.t("verb.toggle"))
        if account is None:
            return ""
        if account.enabled is True:
            if [c.id for c in self._active_operators(cfg)] == [account.id]:
                self.say(self.t("operators.last"))
                return ""
            if not self.yes(self.t("operator_toggle.1", id=account.id), False):
                return ""
            self._warn_if_connected(account.id)
            account.enabled = False
        else:
            account.enabled = True
        return account.id

    def _operator_pseudo(self, cfg) -> str:
        account = self._pick_account(cfg, "operator", self.t("verb.name"))
        if account is None:
            return ""
        pseudo = self._ask_pseudo(cfg, account.pseudo)
        if pseudo is None or pseudo == account.pseudo:
            return ""
        account.pseudo = pseudo
        return account.id

    def _operator_delete(self, cfg) -> str:
        account = self._pick_account(cfg, "operator", self.t("verb.delete"))
        if account is None:
            return ""
        if [c.id for c in self._active_operators(cfg)] == [account.id] or \
                sum(c.role == "operator" for c in cfg.clients) == 1:
            self.say(self.t("operators.last"))
            return ""
        if not self.yes(self.t("operator_delete.1", id=account.id), False):
            return ""
        self._warn_if_connected(account.id)
        cfg.clients.remove(account)
        return account.id

    def _pair_account(self, login: str) -> None:
        """QR code d'appairage du compte qui vient d'être créé (sans mot de passe)."""
        from . import config as cfgmod
        from .setup_wizard import show_pairing
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
            show_pairing(cfg, ask=self.ask, say=self.say, user=login)
        except PermissionError:                            # certificat réservé à la station : relu avec les droits d'administration
            self.runner.run(self.module("trxstation.setup_wizard", "--output", str(self.config), "--empreinte",
                                        "--compte", login), admin=True)
        except (OSError, ValueError, cfgmod.ConfigError) as exc:
            self.say(self.t("pairing.2", exc=exc))

    def _save_accounts(self, original: bytes, cfg, live: bool = True) -> bool:
        """station.toml réécrit depuis `cfg`, validé, puis chemin du menu 8.1 ; `live` : relu sans redémarrer.
        Vrai si enregistré."""
        from . import config as cfgmod
        edited = cfgmod.render_toml(cfg).encode("utf-8")
        if edited == original:
            self.say(self.t("save_accounts.1"))
            return False
        work = Path(tempfile.mkdtemp(prefix="trx-config-"))
        try:
            draft = work / "station.toml"
            draft.write_bytes(edited)
            os.chmod(draft, 0o600)                         # contient les empreintes des mots de passe
            try:
                cfgmod.load(draft)
            except cfgmod.ConfigError as exc:
                self.say(self.t("save_accounts.2") + "\n  - ".join(exc.problems))
                return False
            self.say(self.t("save_accounts.3"))
            return self._save_config(original, edited, draft, live=live)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _visitor_reopen(self, cfg) -> None:
        """Demande à la station de rouvrir l'écoute (elle refuse tant qu'elle n'est pas nettement revenue à la normale)."""
        from .gateway.access_watch import REOPEN_REQUEST, kick_request
        if not isinstance(self._presence().get("suspended"), dict):
            self.say(self.t("visitor_reopen.1"))
            return
        work = Path(tempfile.mkdtemp(prefix="trx-reopen-"))
        try:
            request = work / REOPEN_REQUEST
            request.write_bytes(kick_request("reopen"))
            code = self._install_file(request, Path(cfg.supervisor.state_dir) / REOPEN_REQUEST)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.say(self.t("visitor_reopen.2") if code == 0 else self.t("visitor_reopen.3", code=code))

    def _visitor_kick(self, cfg) -> None:
        from .gateway.access_watch import KICK_REQUEST, kick_request
        connected = [c for c in self._connected() if c.get("role") == "listener"]
        if not connected:
            self.say(self.t("visitor_kick.1"))
            return
        for i, c in enumerate(connected, 1):
            self.say(f"  {i}) {c.get('pseudo', '?')} ({c.get('id', '?')}, {c.get('source', '?')})")
        answer = self.ask(self.t("visitor_kick.2")).strip()
        if not (answer.isdigit() and 1 <= int(answer) <= len(connected)):
            return
        target = str(connected[int(answer) - 1].get("id", ""))
        if not self.yes(self.t("visitor_kick.3", target=target), False):
            return
        work = Path(tempfile.mkdtemp(prefix="trx-kick-"))
        try:
            request = work / KICK_REQUEST
            request.write_bytes(kick_request(target))
            code = self._install_file(request, Path(cfg.supervisor.state_dir) / KICK_REQUEST)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.say(self.t("visitor_kick.4") if code == 0 else self.t("visitor_kick.5", code=code))

    # ------------------------------------------------------------------ présence de groupe (menu 5.3)

    # Libellés : clés du catalogue de langue (traduites au moment de l'affichage par `label`)
    FRIEND_LEVELS = {"1": ("f", "friends.level.f"), "2": ("o", "friends.level.o"), "3": ("x", "friends.level.x")}
    FRIEND_ROLES = {"a": "friends.role.a", "c": "friends.role.c", "m": "friends.role.m"}
    FRIEND_STATUS = {"member": "friends.status.member", "pending": "friends.status.pending",
                     "removed": "friends.status.removed"}
    FRIEND_CODES = {"Q": "friends.code.Q", "R": "friends.code.R", "S": "friends.code.S", "A": "friends.code.A",
                    "O": "friends.code.O"}

    def label(self, table: dict, code, default):
        """Libellé traduit d'un code (FRIEND_ROLES, BREIZH_STATES...) ; `default` si le code est inconnu."""
        return self.t(table[code]) if code in table else default

    def friends(self) -> None:
        """Présence de groupe (docs/presence-cahier-des-charges.md) : le module « presence » fait le travail ; la
        console lui dépose une demande (state_dir/presence-request.json) et lit sa réponse. Rien ici ne touche au
        poste : un QSY vers un ami se fait depuis la page ou l'application."""
        from .presence.store import STATUS_FILE
        state_dir = config_state_dir(self.config)
        while True:
            try:
                status = json.loads((state_dir / "presence" / STATUS_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                status = None
            if not status or not status.get("enabled"):
                switch_menu, start_menu = menu_number("features_switch"), menu_number("start")
                self.say(self.t("friends.1", menu=switch_menu, start=start_menu))
                return
            self.say("\n" + self.friends_summary(status))
            choice = self.ask(self.t("friends.2")).strip()
            if not choice:
                return
            {"1": self._friends_pseudo, "2": self._friends_view, "3": self._friends_create,
             "4": self._friends_invite, "5": self._friends_join, "6": self._friends_share,
             "7": self._friends_leave}.get(choice, lambda: self.say(self.t("loop.unknown")))()

    def friends_summary(self, status: dict) -> str:
        lines = [self.t("friends_summary.1", v=status.get('pseudo') or self.t("friends_summary.2"), v2=self.t("friends_summary.3") if status.get('registered') else self.t("friends_summary.4"))]
        problem = status.get("problem")
        if problem:
            lines.append(self.t("friends_summary.5", problem=problem))
        for grp in status.get("groups") or []:
            lines.append(self.t("friends_summary.6", get=grp.get('name'), get2=self.label(self.FRIEND_ROLES, grp.get('role'), '?'), get3=self.label(self.FRIEND_STATUS, grp.get('status'), grp.get('status')), get4=grp.get('members', 0)))
        if not status.get("groups"):
            lines.append(self.t("friends_summary.7"))
        return "\n".join(lines)

    def friends_request(self, action: str, args: dict | None = None, *, timeout_s: float = 45.0,
                        poll_s: float = 0.5) -> dict | None:
        """Dépose la demande pour le module et attend sa réponse ; None si rien dans le délai (module arrêté)."""
        from .presence.service import CONSOLE_REPLY, CONSOLE_REQUEST
        return self.module_request(CONSOLE_REQUEST, Path("presence") / CONSOLE_REPLY, action, args,
                                   timeout_s=timeout_s, poll_s=poll_s, silent=self.t("friends_request.3"))

    def module_request(self, request_name: str, reply_rel: Path, action: str, args: dict | None, *,
                       timeout_s: float, poll_s: float, silent: str) -> dict | None:
        """Demande déposée pour un module (présence, monitoring) dans le dossier d'état, réponse attendue dans
        `reply_rel` (relatif au dossier d'état) ; None et `silent` affiché si rien dans le délai (module arrêté)."""
        import secrets
        state_dir = config_state_dir(self.config)
        ident = secrets.token_hex(8)
        body = json.dumps({"id": ident, "action": action, "args": args or {}, "at": time.time()}).encode("utf-8")
        target = state_dir / request_name
        try:
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, target)
        except PermissionError:                   # dossier du compte de la station : par l'administrateur (Linux)
            work = Path(tempfile.mkdtemp(prefix="trx-module-"))
            try:
                (work / request_name).write_bytes(body)
                if self._install_file(work / request_name, target) != 0:
                    self.say(self.t("friends_request.1"))
                    return None
            finally:
                shutil.rmtree(work, ignore_errors=True)
        except OSError as exc:
            self.say(self.t("friends_request.2", exc=exc))
            return None
        reply_path = state_dir / reply_rel
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                reply = json.loads(reply_path.read_text(encoding="utf-8"))
                if reply.get("id") == ident:
                    return reply
            except (OSError, ValueError):
                pass
            time.sleep(poll_s)
        self.say(silent)
        return None

    def _friends_do(self, action: str, args: dict | None = None) -> dict | None:
        self.say(self.t("friends_do.1"))
        reply = self.friends_request(action, args)
        if reply is None:
            return None
        if not reply.get("ok"):
            self.say(self.t("friends_do.2", v=reply.get('message') or reply.get('error')))
            return None
        return reply.get("result") or {}

    def _friends_pick(self, *, admin: bool = False) -> str | None:
        view = self._friends_do("view")
        groups = [g for g in (view or {}).get("groups", []) if not admin or g.get("role") in ("a", "c")]
        if not groups:
            self.say(self.t("friends_pick.1") + (self.t("friends_pick.2") if admin else "."))
            return None
        for i, g in enumerate(groups, 1):
            self.say(f"  {i}) {g['name']} ({self.label(self.FRIEND_ROLES, g['role'], '?')})")
        answer = self.ask(self.t("friends_pick.3")).strip()
        if answer.isdigit() and 1 <= int(answer) <= len(groups):
            return groups[int(answer) - 1]["g"]
        return None

    def _friends_pseudo(self) -> None:
        pseudo = self.ask(self.t("friends_pseudo.1")).strip()
        if pseudo and self._friends_do("pseudo", {"pseudo": pseudo}) is not None:
            self.say(self.t("friends_pseudo.2", pseudo=pseudo))

    def _friends_view(self) -> None:
        view = self._friends_do("view")
        for g in (view or {}).get("groups", []):
            self.say(f"\n{g['name']} ({self.label(self.FRIEND_ROLES, g['role'], '?')}, "
                     f"{self.label(self.FRIEND_STATUS, g['status'], g['status'])})")
            for m in g.get("members", []):
                detail = ""
                if m.get("lv") == "f" and "f" in m:
                    detail = f" {m['f'] / 1e6:.3f} MHz {m.get('m', '')}"
                elif m.get("lv") == "x" and m.get("x"):
                    detail = f" « {m['x']} »"
                self.say(f"  [{m['code']}] {m['pseudo']} : {self.label(self.FRIEND_CODES, m['code'], '?')}{detail}")
            if not g.get("members"):
                self.say(self.t("friends_view.1"))

    def _friends_create(self) -> None:
        name = self.ask(self.t("friends_create.1")).strip()
        if name and self._friends_do("create", {"name": name}) is not None:
            self.say(self.t("friends_create.2", name=name))

    def _friends_invite(self) -> None:
        from .setup_wizard import qr_lines
        g = self._friends_pick(admin=True)
        if g is None:
            return
        result = self._friends_do("invite", {"g": g, "days": 7})
        if not result:
            return
        url = result["url"]
        self.say(self.t("friends_invite.1") + url + "\n")
        lines = qr_lines(url)
        if lines:
            self.say("\n".join(lines))
        self.say(self.t("friends_invite.2"))

    def _friends_join(self) -> None:
        url = self.ask(self.t("friends_join.1")).strip()
        if not url:
            return
        name = self.ask(self.t("friends_join.2")).strip()
        if self._friends_do("join", {"url": url, "name": name}) is not None:
            self.say(self.t("friends_join.3"))

    def _friends_share(self) -> None:
        g = self._friends_pick()
        if g is None:
            return
        for key, (_, label) in self.FRIEND_LEVELS.items():
            self.say(f"  {key}) {self.t(label)}")
        level = self.FRIEND_LEVELS.get(self.ask(self.t("friends_share.what")).strip())
        if level is None:
            return
        args = {"g": g, "level": level[0]}
        if level[0] == "x":
            args["text"] = self.ask(self.t("friends_share.1")).strip()
        args["invisible"] = self.yes(self.t("friends_share.2"), False)
        if self._friends_do("share", args) is not None:
            self.say(self.t("friends_share.3"))

    def _friends_leave(self) -> None:
        g = self._friends_pick()
        if g is None:
            return
        view = self._friends_do("view", {"g": g}) or {}
        role = (view.get("groups") or [{}])[0].get("role")
        if role == "a" and self.yes(self.t("friends_leave.1"), False):
            self.hint = {"kind": "word", "word": self.t("word.delete")}
            if self.typed_word(self.ask(self.t("friends_leave.type_word", word=self.t("word.delete"))), "word.delete", "SUPPRIMER") and self._friends_do("delete", {"g": g}) is not None:
                self.say(self.t("friends_leave.2"))
            return
        if self.yes(self.t("friends_leave.3"), False) and self._friends_do("leave", {"g": g}) is not None:
            self.say(self.t("friends_leave.4"))

    # ------------------------------------------------------------------ monitoring inter-stations (menu 6.5)

    MON_ROLES = {"receiver": "monitoring.role.receiver", "emitter": "monitoring.role.emitter"}
    MON_STATES = {"confirm": "monitoring.state.confirm", "active": "monitoring.state.active",
                  "paused": "monitoring.state.paused"}
    MON_HOURS = {"1": 1, "2": 2, "3": 4, "4": 24}

    # ---- diffusion en direct (docs/diffusion-cahier-des-charges.md § 12.3, lot D3) : menu 5.6
    def diffusion(self) -> None:
        """Diffusion en direct : état, lancer / arrêter, identifiants des auditeurs, réglages du serveur et secrets.
        Lancer et arrêter passent par le module « diffusion » (demande déposée, comme la page) ; le module n'a AUCUN
        droit sur le poste et la console ne peut déclencher aucune émission. Le mot de passe source n'est JAMAIS
        déposé dans une demande (fichier lisible) : la console l'écrit elle-même dans diffusion.key (0600)."""
        state_dir = config_state_dir(self.config)
        while True:
            try:
                status = json.loads((state_dir / "diffusion" / "status.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                status = None
            self.say("\n" + self.diffusion_summary(status))
            choice = self.ask(self.t("diffusion.menu")).strip()
            if not choice:
                return
            {"1": self._dif_start, "2": self._dif_stop, "3": self._dif_reveal, "4": self._dif_generate,
             "5": self._dif_settings, "6": self._dif_secrets}.get(choice, lambda: self.say(self.t("loop.unknown")))()

    def diffusion_summary(self, status: dict | None) -> str:
        if not status:
            return self.t("diffusion.no_module", menu=menu_number("features_switch"), start=menu_number("start"))
        if not status.get("enabled"):
            return self.t("diffusion.off", menu=menu_number("features_switch"))
        lines = []
        if status.get("problem"):
            lines.append(self.t("diffusion.problem", v=status["problem"]))
        if status.get("active"):
            remaining = status.get("remaining_s")
            left = self.t("diffusion.unlimited") if remaining is None else f"{int(remaining) // 60} min"
            n = status.get("listeners")
            lines.append(self.t("diffusion.live", access=self.t(f"diffusion.access.{status.get('access', 'prive')}"),
                                operator=status.get("operator") or "?", left=left,
                                listeners="?" if n is None else n,
                                voice=self.t("ask_yes.2") if status.get("voice") else self.t("ask_yes.3")))
        else:
            last = status.get("last_stop") or {}
            cause = last.get("cause")
            causes = ("operator", "duration", "overload", "gateway_restart", "auth", "disabled", "station_stop")
            text = self.t(f"diffusion.cause.{cause}") if cause in causes else ""
            lines.append(self.t("diffusion.idle") + (self.t("diffusion.last", cause=text) if text else ""))
        lines.append(self.t("diffusion.bands_on") if status.get("outside_bands") else self.t("diffusion.bands_off"))
        if status.get("active") and status.get("silence") in ("hors_bandes", "emission", "pas_de_son", "poste_eteint"):
            lines.append(self.t("diffusion.silence", v=self.t(f"diffusion.silence.{status['silence']}")))
        if status.get("listen_page"):
            lines.append(self.t("diffusion.page", url=status["listen_page"]))
        return "\n".join(lines)

    def _dif_do(self, action: str, args: dict | None = None, *, quiet: bool = False) -> dict | None:
        """Demande au module ; refus dit en clair (sauf `quiet`) ; None si le module ne répond pas."""
        from .diffusion.service import CONSOLE_REPLY, CONSOLE_REQUEST
        reply = self.module_request(CONSOLE_REQUEST, Path("diffusion") / CONSOLE_REPLY, action, args, timeout_s=20.0,
                                    poll_s=0.5, silent="" if quiet else self.t("diffusion.noreply",
                                                                              menu=menu_number("journal")))
        if reply is not None and not reply.get("ok") and not quiet and reply.get("error") != "confirm_required":
            self.say(self.t("diffusion.refused", v=reply.get("message") or reply.get("error")))
        return reply

    def _dif_start(self) -> None:
        """Canal (privé par défaut), durée (1 h par défaut, 0 = sans limite), voix émise (non par défaut), pseudo."""
        self.say(self.t("diffusion.access_list"))
        access = "public" if self.ask(self.t("diffusion.ask_access")).strip() == "2" else "prive"
        hours = self._ask_int(self.t("diffusion.ask_hours"), 1, 0, 24)
        voice = self._ask_yes(self.t("diffusion.ask_voice"), False)
        pseudo = self.ask(self.t("diffusion.ask_pseudo")).strip()[:32]
        from .diffusion.protocol import DEFAULT_META_CHOICE      # tout, comme le POC (décision du 2026-11-18)
        args = {"access": access, "hours": None if hours == 0 else hours, "voice": voice,
                "meta": list(DEFAULT_META_CHOICE)}
        if pseudo:
            args["pseudo"] = pseudo
        reply = self._dif_do("start", args)
        if reply is not None and reply.get("error") == "confirm_required":
            self.say(self.t("diffusion.warning"))
            if not self.yes(self.t("diffusion.confirm"), False):
                self.say(self.t("diffusion.not_started"))
                return
            reply = self._dif_do("start", {**args, "confirm": True})
        if reply is not None and reply.get("ok"):
            page = (reply.get("result") or {}).get("listen_page") or ""
            self.say(self.t("diffusion.started", url=page))

    def _dif_stop(self) -> None:
        if self.yes(self.t("diffusion.ask_stop"), False):
            reply = self._dif_do("stop")
            if reply is not None and reply.get("ok"):
                self.say(self.t("diffusion.stopped"))

    def _dif_show_listener(self, data: dict) -> None:
        self.say(self.t("diffusion.listener", user=data.get("listener_user") or "?",
                        password=data.get("listener_password") or self.t("diffusion.no_password")))

    def _dif_reveal(self) -> None:
        reply = self._dif_do("reveal")
        if reply is not None and reply.get("ok"):
            self._dif_show_listener(reply.get("result") or {})

    def _dif_generate(self) -> None:
        if not self.yes(self.t("diffusion.ask_generate"), False):
            return
        reply = self._dif_do("listener", {"generate": True})
        if reply is not None and reply.get("ok"):
            self.say(self.t("diffusion.new_password"))
            self._dif_show_listener(reply.get("result") or {})

    def _dif_settings(self) -> None:
        """[diffusion] de station.toml : serveur, nom de la station, codec, hors bandes, port des sources."""
        from .diffusion.protocol import CODECS, STATION_NAME
        while True:
            loaded = self._load_for_edit()
            if loaded is None:
                return
            original, cfg = loaded
            d = cfg.diffusion
            self.say(self.t("diffusion.settings_state", server=d.server or "—", station=d.station or "—",
                            codec=d.codec, port=d.source_port,
                            bands=self.t("ask_yes.2") if d.outside_bands else self.t("ask_yes.3")))
            choice = self.ask(self.t("diffusion.settings_menu")).strip()
            if not choice:
                return
            if choice == "1":
                answer = self.ask(self.t("diffusion.ask_server")).strip().lower()
                if not answer:
                    continue
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", answer):
                    self.say(self.t("diffusion.bad_value"))
                    continue
                d.server = answer
            elif choice == "2":
                answer = self.ask(self.t("diffusion.ask_station")).strip().lower()
                if not answer:
                    continue
                if not STATION_NAME.fullmatch(answer):
                    self.say(self.t("diffusion.bad_value"))
                    continue
                d.station = answer
            elif choice == "3":
                answer = self.ask(self.t("diffusion.ask_codec", codec=d.codec)).strip().lower()
                if answer and answer not in CODECS:
                    self.say(self.t("diffusion.bad_value"))
                    continue
                d.codec = answer or d.codec
            elif choice == "4":
                self.say(self.t("diffusion.bands_explain"))
                d.outside_bands = self._ask_yes(self.t("diffusion.ask_bands"), d.outside_bands)
            elif choice == "5":
                d.source_port = self._ask_int(self.t("diffusion.ask_port"), d.source_port, 1, 65535)
            else:
                self.say(self.t("visitors.4"))
                continue
            self._save_accounts(original, cfg, live=False)

    def _dif_secrets(self) -> None:
        """Mot de passe source et clé des métadonnées, donnés par l'administrateur du serveur : écrits dans
        diffusion.key (0600, au compte du service), jamais affichés, jamais déposés dans une demande au module.
        Les identifiants des auditeurs sont gardés (relus auprès du module s'il tourne)."""
        from .config import diffusion_key_path
        from .diffusion import keyfile
        loaded = self._load_for_edit()
        if loaded is None:
            return
        _, cfg = loaded
        self.say(self.t("diffusion.secrets_explain"))
        self.hint = {"kind": "password"}
        source = self.ask(self.t("diffusion.ask_source")).strip()
        if not source:
            self.say(self.t("diffusion.secrets_unchanged"))
            return
        self.hint = {"kind": "password"}
        meta_key = self.ask(self.t("diffusion.ask_meta_key")).strip().lower()
        current = self._dif_do("reveal", quiet=True)
        data = (current or {}).get("result") or {} if (current or {}).get("ok") else {}
        try:
            secrets_ = keyfile.check(keyfile.Secrets(source, meta_key, data.get("listener_user") or "auditeur",
                                                     data.get("listener_password") or ""))
        except keyfile.KeyFileError as exc:
            self.say(self.t("diffusion.secrets_bad", v=str(exc)))
            return
        path = diffusion_key_path(cfg, self.config)
        if os.name == "posix":
            work = Path(tempfile.mkdtemp(prefix="trx-diffusion-"))
            try:
                draft = work / "diffusion.key"
                keyfile.save(draft, secrets_)                          # 0600 dès la création
                owner = path.parent if path.parent.exists() else config_state_dir(self.config)
                code = self._install_file(draft, path, mode="600", like=owner, parents=True)
            finally:
                shutil.rmtree(work, ignore_errors=True)
        else:
            try:
                keyfile.save(path, secrets_)
                code = 0
            except OSError:
                code = 1
        if code != 0:
            self.say(self.t("diffusion.secrets_failed", code=code))
            return
        self.say(self.t("diffusion.secrets_saved", file=path.name))
        if not data.get("listener_password"):
            self.say(self.t("diffusion.secrets_listener_note"))

    def monitoring(self) -> None:
        """Monitoring inter-stations (docs/cdc-monitoring.md § 17) : AIDER un opérateur en difficulté, ou ÊTRE AIDÉ.
        Le module « monlink » fait le travail ; la console lui dépose une demande (state_dir/monlink-request.json) et
        lit sa réponse. Aucune commande vers une station n'existe : la station qui aide ne peut que lire et demander."""
        state_dir = config_state_dir(self.config)
        while True:
            try:
                status = json.loads((state_dir / "monlink" / "status.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                status = None
            if not status or not status.get("enabled"):
                switch_menu, start_menu = menu_number("features_switch"), menu_number("start")
                self.say(self.t("monitoring.off", menu=switch_menu, start=start_menu))
                return
            self.say("\n" + self.monitoring_summary(status))
            choice = self.ask(self.t("monitoring.menu")).strip()
            if not choice:
                return
            {"1": self._mon_pseudo, "2": self._mon_view, "3": self._mon_invite, "4": self._mon_join,
             "5": self._mon_confirm, "6": self._mon_request, "7": self._mon_answer, "8": self._mon_manage,
             "9": self._mon_end, "10": self._mon_report}.get(choice, lambda: self.say(self.t("loop.unknown")))()

    def monitoring_summary(self, status: dict) -> str:
        reg = self.t("monitoring.summary.registered" if status.get("registered") else "monitoring.summary.not_registered")
        lines = [self.t("monitoring.summary.head", pseudo=status.get("pseudo") or self.t("monitoring.summary.no_pseudo"),
                        reg=reg)]
        if status.get("problem"):
            lines.append(self.t("monitoring.summary.problem", problem=status["problem"]))
        for link in status.get("links") or []:
            lines.append(self.t("monitoring.summary.link", pseudo=link.get("pseudo") or "?",
                                role=self.label(self.MON_ROLES, link.get("role"), "?"),
                                state=self.label(self.MON_STATES, link.get("state"), "?"),
                                extra=self._mon_extra(link)))
        if not status.get("links"):
            lines.append(self.t("monitoring.summary.none"))
        return "\n".join(lines)

    def _mon_extra(self, link: dict) -> str:
        extra = ""
        if link.get("state") != "confirm":
            age = link.get("last_rx_age")
            extra += (self.t("monitoring.extra.never") if age is None
                      else self.t("monitoring.extra.age", minutes=max(0, int(age) // 60)))
        if link.get("request"):
            extra += self.t("monitoring.extra.request")
        if link.get("assist_left_s"):
            extra += self.t("monitoring.extra.assist", minutes=max(1, int(link["assist_left_s"]) // 60))
        if link.get("paused"):
            extra += self.t("monitoring.extra.paused")
        if link.get("silent"):
            extra += self.t("monitoring.extra.silent")
        if link.get("report_due"):
            extra += self.t("monitoring.extra.report_due")
        if link.get("reports"):
            extra += self.t("monitoring.extra.reports", n=link["reports"])
        return extra

    def _mon_do(self, action: str, args: dict | None = None) -> dict | list | None:
        from .monlink.service import CONSOLE_REPLY, CONSOLE_REQUEST
        self.say(self.t("monitoring.do.sent"))
        journal_menu = menu_number("journal")
        reply = self.module_request(CONSOLE_REQUEST, Path("monlink") / CONSOLE_REPLY, action, args, timeout_s=60.0,
                                    poll_s=0.5, silent=self.t("monitoring.do.noreply", menu=journal_menu))
        if reply is None:
            return None
        if not reply.get("ok"):
            self.say(self.t("monitoring.do.refused", v=reply.get("message") or reply.get("error")))
            return None
        result = reply.get("result")
        return {} if result is None else result

    def _mon_pick(self, keep) -> dict | None:
        """Une liaison parmi celles que `keep(liaison)` retient ; choisie d'office s'il n'y en a qu'une."""
        view = self._mon_do("view")
        links = [l for l in (view or {}).get("links", []) if keep(l)]
        if not links:
            self.say(self.t("monitoring.pick.none"))
            return None
        if len(links) == 1:
            return links[0]
        for i, l in enumerate(links, 1):
            self.say(f"  {i}) {l.get('pseudo') or '?'} ({self.label(self.MON_ROLES, l.get('role'), '?')}, "
                     f"{self.label(self.MON_STATES, l.get('state'), '?')})")
        answer = self.ask(self.t("monitoring.pick.ask")).strip()
        if answer.isdigit() and 1 <= int(answer) <= len(links):
            return links[int(answer) - 1]
        return None

    def _mon_pseudo(self) -> None:
        pseudo = self.ask(self.t("monitoring.pseudo.ask")).strip()
        if pseudo and self._mon_do("pseudo", {"pseudo": pseudo}) is not None:
            self.say(self.t("monitoring.pseudo.done", pseudo=pseudo))

    def _mon_view(self) -> None:
        view = self._mon_do("view")
        for l in (view or {}).get("links", []):
            self.say(self.t("monitoring.view.head", pseudo=l.get("pseudo") or "?",
                            role=self.label(self.MON_ROLES, l.get("role"), "?"),
                            state=self.label(self.MON_STATES, l.get("state"), "?")) + self._mon_extra(l))
            if l.get("role") == "emitter":
                p = l.get("profile") or {}
                if p:
                    self.say(self.t("monitoring.view.profile", min=p.get("events_min", "?"),
                                    period=int(p.get("period_s", 0)) // 60,
                                    fm=self.t("monitoring.fm.on") if p.get("freq_mode") else self.t("monitoring.fm.off")))
                continue
            hb, st = l.get("last_hb") or {}, l.get("last_st") or {}
            if not hb and not st:
                self.say(self.t("monitoring.view.nothing"))
            if hb:
                self.say(self.t("monitoring.view.hb", v=hb.get("v", "?"), gateway=hb.get("gateway", "?"),
                                safe=hb.get("safe") or self.t("monitoring.safe.none")))
            sysinfo, rig = st.get("system") or {}, st.get("rig") or {}
            if sysinfo:
                self.say(self.t("monitoring.view.system", cpu=sysinfo.get("cpu", "--"), mem=sysinfo.get("mem", "--"),
                                disk=sysinfo.get("disk", "--"),
                                temp="--" if sysinfo.get("temp") is None else f"{sysinfo['temp']} °C"))
            if rig:
                freq = ""
                if rig.get("freq"):
                    freq = f", {rig['freq'] / 1e6:.3f} MHz {rig.get('mode') or ''}".rstrip()
                self.say(self.t("monitoring.view.rig", cat="OK" if rig.get("cat") else (rig.get("cat_error") or "?"),
                                tx=rig.get("tx") or "?", clients=rig.get("clients", 0), freq=freq))
            events = self._mon_do("received", {"peer": l["peer"], "limit": 10})
            if events:
                self.say(self.t("monitoring.view.events"))
                for e in events:
                    c = e.get("content") or {}
                    self.say(self.t("monitoring.view.event", ts=str(c.get("ts", ""))[:16].replace("T", " "),
                                    code=c.get("code", "?"), gravite=c.get("gravite", "?"),
                                    titre=c.get("titre") or c.get("message") or ""))
            elif events is not None:
                self.say(self.t("monitoring.view.no_events"))

    def _mon_invite(self) -> None:
        result = self._mon_do("invite")
        if result:
            here = menu_number("monitoring")
            self.say(self.t("monitoring.invite.done", code=result["code"], menu=here))

    def _mon_profile(self) -> dict | None:
        """Ce que la station AIDÉE envoie : « essentiel » ou « diagnostic » (défaut), fréquence et mode à part."""
        self.say(self.t("monitoring.profile.menu"))
        answer = self.ask(self.t("monitoring.profile.ask")).strip() or "2"
        if answer not in ("1", "2"):
            return None
        profile = {"rig": answer == "2", "events_min": "erreur" if answer == "1" else "avertissement"}
        profile["freq_mode"] = self.yes(self.t("monitoring.profile.fm"), False)
        return profile

    def _mon_fingerprint_ok(self, link: dict) -> bool:
        """Les 6 chiffres comparés de vive voix ; différents = liaison refusée et effacée (intermédiaire possible)."""
        self.say(self.t("monitoring.fp.show", fp=link.get("fingerprint", "?")))
        if self.yes(self.t("monitoring.fp.same"), False):
            return True
        self._mon_do("end", {"peer": link["peer"]})
        self.say(self.t("monitoring.fp.differ"))
        return False

    def _mon_join(self) -> None:
        here = menu_number("monitoring")
        self.say(self.t("monitoring.join.intro", menu=here))
        code = self.ask(self.t("monitoring.join.ask")).strip()
        if not code:
            return
        result = self._mon_do("join", {"code": code})
        if not result:
            return
        self.say(self.t("monitoring.join.done", pseudo=result.get("pseudo") or "?"))
        self._mon_finish({"peer": result["peer"], "pseudo": result.get("pseudo"), "role": "emitter",
                          "fingerprint": result.get("fingerprint")})

    def _mon_confirm(self) -> None:
        link = self._mon_pick(lambda l: l.get("state") == "confirm")
        if link is not None:
            self._mon_finish(link)

    def _mon_finish(self, link: dict) -> None:
        if not self._mon_fingerprint_ok(link):
            return
        args: dict = {"peer": link["peer"]}
        if link.get("role") == "emitter":
            profile = self._mon_profile()
            if profile is None:
                return
            args["profile"] = profile
        if self._mon_do("confirm", args) is not None:
            self.say(self.t("monitoring.confirm.done", pseudo=link.get("pseudo") or "?"))

    def _mon_request(self) -> None:
        link = self._mon_pick(lambda l: l.get("role") == "receiver" and l.get("state") == "active")
        if link is None:
            return
        self.say(self.t("monitoring.request.kind"))
        kind = self.ask(self.t("monitoring.request.kind_ask")).strip() or "1"
        here = menu_number("monitoring")
        if kind == "2":
            if self._mon_do("request_report", {"peer": link["peer"]}) is not None:
                self.say(self.t("monitoring.request.done", menu=here))
            return
        if kind != "1":
            return
        self.say(self.t("monitoring.request.menu"))
        hours = self.MON_HOURS.get(self.ask(self.t("monitoring.request.ask")).strip() or "2")
        if hours and self._mon_do("request_assist", {"peer": link["peer"], "duration_s": hours * 3600}) is not None:
            self.say(self.t("monitoring.request.done", menu=here))

    def _mon_answer(self) -> None:
        link = self._mon_pick(lambda l: l.get("role") == "emitter" and l.get("request"))
        if link is None:
            return
        if link["request"].get("snapshot"):
            self.say(self.t("monitoring.answer.report_show", pseudo=link.get("pseudo") or "?"))
            accept = self.yes(self.t("monitoring.answer.ask"), False)
            if self._mon_do("answer", {"peer": link["peer"], "accept": accept}) is not None:
                self.say(self.t("monitoring.report.queued") if accept else self.t("monitoring.answer.no"))
            return
        hours = round(int(link["request"].get("assist", 0)) / 3600, 1)
        self.say(self.t("monitoring.answer.show", pseudo=link.get("pseudo") or "?", hours=hours))
        accept = self.yes(self.t("monitoring.answer.ask"), False)
        if self._mon_do("answer", {"peer": link["peer"], "accept": accept}) is not None:
            self.say(self.t("monitoring.answer.yes", hours=hours) if accept else self.t("monitoring.answer.no"))

    def _mon_report(self) -> None:
        """Station AIDÉE : envoyer son rapport de dépannage. Station qui AIDE : copier le dernier reçu sur SON Bureau."""
        link = self._mon_pick(lambda l: l.get("state") in ("active", "paused"))
        if link is None:
            return
        if link.get("role") == "emitter":
            if self._mon_do("send_report", {"peer": link["peer"]}) is not None:
                self.say(self.t("monitoring.report.queued"))
            return
        result = self._mon_do("last_report", {"peer": link["peer"]})
        if not result:
            return
        from .report import desktop_dir
        try:
            target = desktop_dir() / Path(result["path"]).name
            shutil.copyfile(result["path"], target)
        except OSError as exc:
            self.say(self.t("monitoring.report.copy_failed", exc=exc, path=result["path"]))
            return
        self.say(self.t("monitoring.report.copied", path=target))

    def _mon_manage(self) -> None:
        link = self._mon_pick(lambda l: l.get("role") == "emitter" and l.get("state") in ("active", "paused"))
        if link is None:
            return
        self.say(self.t("monitoring.manage.menu"))
        choice = self.ask(self.t("monitoring.manage.ask")).strip()
        if choice == "1":
            profile = self._mon_profile()
            done = profile is not None and self._mon_do("profile", {"peer": link["peer"], "profile": profile}) is not None
        elif choice in ("2", "3"):
            done = self._mon_do("pause", {"peer": link["peer"], "paused": choice == "2"}) is not None
        else:
            return
        if done:
            self.say(self.t("monitoring.manage.done"))

    def _mon_end(self) -> None:
        link = self._mon_pick(lambda l: True)
        if link is None or not self.yes(self.t("monitoring.end.ask", pseudo=link.get("pseudo") or "?"), False):
            return
        purge = link.get("role") == "receiver" and self.yes(self.t("monitoring.end.purge"), True)
        if self._mon_do("end", {"peer": link["peer"], "purge": purge}) is not None:
            self.say(self.t("monitoring.end.done"))

    # ------------------------------------------------------------------ qualité du réseau (menu 6.4)

    def network(self) -> None:
        """Sonde de qualité réseau (docs/netprobe-cahier-des-charges.md § 12.3) : liaisons en ce moment (fichier d'état),
        synthèses 24 h et 30 jours, export anonyme sur le Bureau, « Tout effacer ». Lecture seule sauf l'effacement ;
        rien ici ne touche à l'émission. Les seuils de l'indicateur se règlent dans la page ou l'application."""
        from .monitor.model import Snapshot, _reseau_panel, render_plain
        from .netprobe.export import report_text, store_of
        state_dir = config_state_dir(self.config)
        while True:
            st = self._gateway_status()
            if st is None:
                self.say(self.t("network.1"))
            else:
                panel = _reseau_panel(Snapshot(status=st, gateway_fresh=True, stale_s=0.0, safe_mode=None), detail=True)
                self.say("\n" + render_plain([panel]).rstrip())
            choice = self.ask(self.t("network.2")).strip()
            if not choice:
                return
            store = store_of(state_dir)
            if choice in ("1", "2"):
                if not store.folder.is_dir():
                    self.say(self.t("network.3"))
                    continue
                self.say("\n" + report_text(store.stats(1 if choice == "1" else 30, "", {})))
            elif choice == "3":
                self._network_export(store, state_dir)
            elif choice == "4":
                self._network_clear(state_dir)
            else:
                self.say(self.t("network.4"))

    def _network_export(self, store, state_dir: Path) -> None:
        from dataclasses import asdict

        from . import __version__
        from . import config as cfgmod
        from .netprobe.export import build_export, export_name
        from .report import desktop_dir
        from .station_id import read_station_id
        if not store.folder.is_dir():
            self.say(self.t("network_export.1"))
            return
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
            settings = asdict(cfg.netprobe)
        except (cfgmod.ConfigError, OSError):
            settings = {}
        folder = self.desktop() if self.desktop else desktop_dir()
        target = folder / export_name()
        try:
            target.write_bytes(build_export(store, 30, version=__version__, station_id=read_station_id(state_dir) or "",
                                            settings=settings))
        except OSError as exc:
            self.say(self.t("network_export.2", exc=exc))
            return
        self.say(self.t("network_export.3", target=target))

    def _network_clear(self, state_dir: Path) -> None:
        from .gateway.access_watch import kick_request
        from .netprobe.probe import CLEAR_REQUEST
        self.hint = {"kind": "word", "word": self.t("word.erase")}
        answer = self.ask(self.t("network_clear.1", word=self.t("word.erase"))).strip()
        if not self.typed_word(answer, "word.erase", "EFFACER", exact=True):
            self.say(self.t("network_clear.2"))
            return
        if self._gateway_status() is not None:          # station en marche : c'est elle qui efface (mémoire comprise)
            work = Path(tempfile.mkdtemp(prefix="trx-net-"))
            try:
                request = work / CLEAR_REQUEST
                request.write_bytes(kick_request("console"))
                code = self._install_file(request, state_dir / CLEAR_REQUEST)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            self.say(self.t("network_clear.3") if code == 0
                     else self.t("network_clear.4", code=code))
            return
        folder = state_dir / "netprobe"
        if not folder.is_dir():
            self.say(self.t("network_clear.5"))
            return
        if IS_WINDOWS:
            try:
                for item in folder.iterdir():
                    if item.is_file() and item.name != "seuils.json":
                        item.unlink()
                code = 0
            except OSError:
                code = 1
        else:
            code = self.runner.run(["find", str(folder), "-maxdepth", "1", "-type", "f", "!", "-name", "seuils.json",
                                    "-delete"], admin=True)
        self.say(self.t("network_clear.6") if code == 0 else self.t("network_clear.7", code=code))

    # ------------------------------------------------------------------ Breizh Audio Box (menu 5.2)

    BREIZH_STATES = {"connecting": "breizh.state.connecting", "ready": "breizh.state.ready", "active": "breizh.state.active",
                     "fallback": "breizh.state.fallback", "refused": "breizh.state.refused"}   # clés du catalogue

    def breizh(self) -> None:
        """Breizh Audio Box (docs/breizh-cahier-des-charges.md) : clé d'appairage (breizh.key, à côté de station.toml,
        créée ici et montrée UNE fois), adresse et port de Breizh et activation ([breizh] de station.toml, chemin validé
        du menu 8.1), essai de la liaison SANS son, état publié par la passerelle, journal. Rien ici ne touche au PTT."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say(self.t("breizh.1"))
            return
        while True:
            try:
                original = self.config.read_bytes()
                cfg, _ = cfgmod.load_unchecked(self.config)
            except (OSError, cfgmod.ConfigError) as exc:
                self.say(self.t("breizh.2", config=self.config, exc=exc))
                return
            self.say(self._breizh_summary(cfg))
            choice = self.ask(self.t("breizh.3")).strip()
            if not choice:
                return
            if choice == "1":
                self._breizh_new_key(cfg)
            elif choice == "2":
                if self._breizh_settings(cfg):
                    self._save_accounts(original, cfg, live=False)
            elif choice == "3":
                self._breizh_probe(cfg)
            elif choice == "4":
                self._breizh_journal(cfg, 20)
            else:
                self.say(self.t("breizh.4"))

    def _breizh_key_state(self, cfg) -> str:
        """« présente », ou le problème (absente, illisible, droits trop larges). Jamais la clé elle-même."""
        from .breizh.keyfile import KeyFileError, read_key
        from .config import breizh_key_path
        path = breizh_key_path(cfg, self.config)
        if not path.exists():
            return self.t("breizh_key_state.1")
        try:
            read_key(path)
        except KeyFileError as exc:
            if " illisible (" in str(exc):                     # droits root:trx : le compte de bureau ne la lit pas
                return self.t("breizh_key_state.2", path=path)
            return self.t("breizh_key_state.3", exc=exc)
        return self.t("breizh_key_state.4", path=path)

    def _breizh_summary(self, cfg) -> str:
        b = cfg.breizh
        lines = [self.t("breizh_summary.1"),
                 self.t("breizh_summary.2"),
                 self.t("breizh_summary.3", v=self.t("breizh_summary.4") if b.enabled else self.t("breizh_summary.5")),
                 self.t("breizh_summary.6", v=b.host or self.t("breizh_summary.7"), port=b.port),
                 self.t("breizh_summary.8", breizh_key_state=self._breizh_key_state(cfg))]
        status = self._gateway_status()
        live = status.breizh if status is not None and isinstance(getattr(status, "breizh", None), dict) else {}
        if live:
            details = [self.t("breizh_summary.route", route=live.get('route')) + (self.t("breizh_summary.9") if live.get("bypass") else "")]
            if live.get("peer"):
                details.append(str(live["peer"])[:64])
            if live.get("rtt_ms") is not None:
                details.append(self.t("breizh_summary.10", rtt_ms=live['rtt_ms']))
            lines.append(self.t("breizh_summary.11", get=self.label(self.BREIZH_STATES, live.get('state'), live.get('state')))
                         + " · ".join(details))
        elif b.enabled:
            lines.append(self.t("breizh_summary.12"))
        for entry in self._breizh_entries(cfg)[-3:]:
            lines.append(self.t("breizh_summary.13", entry=entry))
        return "\n".join(lines)

    def _breizh_entries(self, cfg) -> list[str]:
        from .breizh.store import BreizhStore
        try:
            store = BreizhStore(cfg.supervisor.state_dir)
        except OSError:
            return []
        return [(e.get("t", "").replace("T", " ").replace("Z", " UTC") + " : " if e.get("t") else "") + str(e.get("detail", ""))
                for e in store.last(50)]

    def _breizh_journal(self, cfg, count: int) -> None:
        entries = self._breizh_entries(cfg)[-count:]
        self.say("\n".join([self.t("breizh_journal.1")]
                           + ["  " + e for e in entries]) if entries else self.t("breizh_journal.2"))

    def _breizh_new_key(self, cfg) -> None:
        """Nouvelle clé de 32 octets, écrite avec les droits de station.toml (jamais lisible par tous) et montrée UNE fois."""
        from .breizh.protocol import key_to_text, new_key
        from .config import breizh_key_path
        path = breizh_key_path(cfg, self.config)
        if path.exists() and not self.yes(self.t("breizh_new_key.1"), False):
            return
        key = new_key()
        work = Path(tempfile.mkdtemp(prefix="trx-breizh-"))
        try:
            draft = work / "breizh.key"
            draft.write_text(key_to_text(key) + "\n", encoding="utf-8")
            if os.name == "posix":
                os.chmod(draft, 0o600)
                st = self.config.stat()
                mode = (st.st_mode & 0o660) or 0o600                     # jamais lisible par les autres comptes
                code = self._install_file(draft, path, mode=f"{mode:o}", like=self.config)
            else:
                from .breizh.keyfile import write_key
                try:
                    write_key(path, key)
                    code = 0
                except OSError as exc:
                    self.say(self.t("breizh_new_key.2", exc=exc))
                    code = 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if code != 0:
            self.say(self.t("breizh_new_key.3", code=code))
            return
        try:
            if self.addresses is None:
                from .setup_wizard import local_addresses
                self.addresses = local_addresses
            found = self.addresses()
        except Exception:                                   # adresse introuvable : texte générique
            found = []
        self.say(self.t("breizh_new_key.4", key_to_text=key_to_text(key), v=', '.join(found) or self.t("breizh_new_key.5"), port=cfg.breizh.port, port2=cfg.breizh.port))
        if cfg.breizh.enabled and self.station_running() and self.yes(self.t("breizh_new_key.6")):
            self.start()

    def _breizh_settings(self, cfg) -> bool:
        """Adresse IP PRIVÉE de Breizh, port, activation. Vrai si quelque chose a changé."""
        from .config import breizh_host_allowed
        b = cfg.breizh
        before = (b.enabled, b.host, b.port)
        while True:
            answer = self.ask(self.t("breizh_settings.1", v=b.host or self.t("breizh_settings.2"))).strip()
            if not answer or breizh_host_allowed(answer):
                b.host = answer or b.host
                break
            self.say(self.t("breizh_settings.3"))
        b.port = self._ask_int(self.t("breizh_settings.4"), b.port, 1024, 65535)
        b.enabled = self._ask_yes(self.t("breizh_settings.5"), b.enabled)
        if b.enabled and not b.host:
            self.say(self.t("breizh_settings.6"))
            b.enabled = False
        if b.enabled and self._breizh_key_state(cfg).startswith("ABSENTE"):
            self.say(self.t("breizh_settings.7"))
        return (b.enabled, b.host, b.port) != before

    def _breizh_probe(self, cfg) -> None:
        """Essai par la fausse station (HELLO puis 5 PING, aucun son), lancé en administrateur pour lire la clé."""
        from .config import breizh_key_path
        b = cfg.breizh
        if not b.host:
            self.say(self.t("breizh_probe.1"))
            return
        path = breizh_key_path(cfg, self.config)
        if not path.exists():
            self.say(self.t("breizh_probe.2"))
            return
        status = self._gateway_status()
        live = status.breizh if status is not None and isinstance(getattr(status, "breizh", None), dict) else {}
        if live.get("state") in ("ready", "active", "fallback") and live.get("peer"):
            self.say(self.t("breizh_probe.3", get=live.get('peer'), get2=live.get('rtt_ms')))
            return
        self.runner.run(self.module("trxstation.devtools.breizh_probe", "--host", b.host, "--port", str(b.port),
                                    "--key-file", str(path), "--sans-son"), admin=os.name == "posix")

    def temperature(self) -> None:
        """Seuils de température du poste ([safety] rig_temp_warn_c, rig_temp_cut_c), écrits dans station.toml par
        le même chemin que le menu 8.1 : copie, validation, différences, confirmation, sauvegarde."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say(self.t("temperature.1"))
            return
        try:
            original = self.config.read_bytes()
            cfg, _ = cfgmod.load_unchecked(self.config)
        except (OSError, cfgmod.ConfigError) as exc:
            self.say(self.t("temperature.2", config=self.config, exc=exc))
            return
        s = cfg.safety
        self.say(self.t("temperature.3", rig_temp_warn_c=s.rig_temp_warn_c, rig_temp_cut_c=s.rig_temp_cut_c))
        warn = self._ask_degrees(self.t("temperature.4"), s.rig_temp_warn_c)
        cut = self._ask_degrees(self.t("temperature.5"), s.rig_temp_cut_c)
        if (warn, cut) == (s.rig_temp_warn_c, s.rig_temp_cut_c):
            self.say(self.t("temperature.6"))
            return
        edited = set_safety_values(original.decode("utf-8"), {"rig_temp_warn_c": warn, "rig_temp_cut_c": cut}).encode("utf-8")
        work = Path(tempfile.mkdtemp(prefix="trx-config-"))
        draft = work / "station.toml"
        try:
            draft.write_bytes(edited)
            os.chmod(draft, 0o600)                         # contient les empreintes des mots de passe
            try:
                cfgmod.load(draft)
            except cfgmod.ConfigError as exc:
                self.say(self.t("temperature.7") + "\n  - ".join(exc.problems))
                return
            self._save_config(original, edited, draft)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _ask_degrees(self, question: str, current: int) -> int:
        while True:
            answer = self.ask(self.t("ask_degrees.1", question=question, current=current)).strip()
            if not answer:
                return current
            if re.fullmatch(r"\d{1,3}", answer):
                return int(answer)
            self.say(self.t("ask_degrees.2"))

    def expert(self) -> None:
        self.say(self.t("expert.1"))
        if self.ask(self.t("expert.2")).strip() == "1":
            self.run_tests()

    def run_tests(self) -> None:
        """Toute la suite de tests de la version installée, sur cette machine. Résultat enregistré sur le Bureau."""
        tests = self.app_dir / "current" / "app" / "tests"
        if not tests.is_dir():
            self.say(self.t("run_tests.1", tests=tests))
            return
        if self.runner.output([self.python, "-c", "import pytest; print('ok')"]) != "ok":
            self.say(self.t("run_tests.2"))
            if not self.yes(self.t("run_tests.3"), False):
                return
            self.runner.run([self.python, "-m", "pip", "install", "--quiet", "pytest"], admin=True)
            if self.runner.output([self.python, "-c", "import pytest; print('ok')"]) != "ok":
                self.say(self.t("run_tests.4"))
                return
        self.say(self.t("run_tests.5"))
        if not self.yes(self.t("run_tests.6"), True):
            return
        stopped = self.stop_for_exclusive_use(self.t("run_tests.7"))
        from .report import desktop_dir
        folder = self.desktop() if self.desktop else desktop_dir()
        log = folder / f"trx-remote-tests-{time.strftime('%Y%m%d-%H%M')}.txt"
        work = Path(tempfile.mkdtemp(prefix="trx-tests-"))
        try:
            cmd = [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", f"faulthandler_timeout={HANG_DUMP_S}",
                   "--basetemp", str(work / "tmp"), str(tests)]
            runner = getattr(self.runner, "run_logged", None)
            code = runner(cmd, log, cwd=work) if runner else self.runner.run(cmd)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.say(self.t("run_tests.8") if code == 0 else
                 self.t("run_tests.9", code=code, log=log))
        if code == 0:
            self.say(self.t("run_tests.10", log=log))
        if stopped and self.yes(self.t("run_tests.11")):
            self.start()

    def offered(self, state: UpdateState | None):
        """Version annoncée seulement si elle est plus récente que celle qui tourne (latest.json peut dater)."""
        release = state.release if state is not None else None
        if release is None or (parse_version(release.version) or ()) <= (parse_version(self.installed) or ()):
            return None
        return release

    @staticmethod
    def page_key(key: str) -> str:
        """Variante `<clé>.page` d'un message quand le menu tourne dans la page (console web en formulaires)."""
        return f"{key}.page" if os.environ.get("TRX_CONSOLE_PAGE") else key

    def reopen_key(self, key: str) -> str:
        """Message « Quitte TRX Console (q) et rouvre-la » : dans la page (menus en formulaires), la clé
        `<clé>.page` (console sur le réseau relancée seule, actualiser la page) ou `<clé>.local` (relancer
        trx-console --web)."""
        page = os.environ.get("TRX_CONSOLE_PAGE")
        return f"{key}.{'page' if page == 'network' else 'local'}" if page else key

    def _apply_result(self, code: int, success: str) -> str:
        if code == upd.EXIT_OK:
            return success
        if code == upd.EXIT_TX:
            return self.t("apply_result.1")
        if code == upd.EXIT_REFUSED:
            return self.t("apply_result.2")
        return self.t("apply_result.3", code=code, install_log=INSTALL_LOG)

    # ------------------------------------------------------------------ boucle

    def station_id(self) -> str | None:
        return read_station_id(config_state_dir(self.config))

    def header(self) -> str:
        t = self.t
        if not self.config.exists():
            state = self.paint(t("head.not_configured", menu=menu_number("assistant")), YELLOW)
        elif self.station_running():
            state = self.paint(t("head.running"), GREEN)
        else:
            state = self.paint(t("head.stopped"), RED)
        line = f"\n=== {t('app.title', version=self.installed)} ===\n  {state}"
        if self.config.exists():
            line += "".join("\n" + extra for extra in self.station_lines())
        line += "\n  " + t("head.station_id", id=self.station_id() or t("head.station_id_later"))
        release = self.offered(self.update_state())
        if release is not None:
            line += self.banner([t("head.new_version", version=release.version, installed=self.installed),
                                 t("head.new_version_menu", menu=UPDATE_MENU)])
        line += "\n  " + t("head.level", level=t(f"level.{self.level}"))
        if (parse_version(self.installed) or (0,)) < RENUMBER_NOTICE_UNTIL:
            line += "\n  " + self.paint(t("head.renumbered", version=RENUMBERED_IN, update=UPDATE_MENU,
                                          zip=menu_number("install_zip"), diag=menu_number("diagnostic")), YELLOW)
        return line

    def station_lines(self) -> list[str]:
        """Adresse de la station, puis alimentation et température du poste (fichier d'état de la passerelle).
        Jamais d'exception : l'en-tête s'affiche avant chaque menu."""
        from . import config as cfgmod
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
        except (cfgmod.ConfigError, OSError):
            return []
        n = cfg.network
        try:
            if self.addresses is None:
                from .setup_wizard import local_addresses
                self.addresses = local_addresses
            found = self.addresses()
        except Exception:                               # en-tête : une adresse introuvable ne bloque pas la console
            found = []
        status = self._gateway_status()
        rc = cfg.remote_console
        return [address_line(n.gateway_bind, n.gateway_port, bool(n.tls_cert), found, self.t),
                console_line(rc.enabled is True, n.gateway_bind, rc.port, bool(n.tls_cert), found, self.t),
                rig_vitals_line(status.rig if status is not None else None, self.t)]

    def menu_label(self, key: str, label: str) -> str:
        release = self.offered(self.update_state()) if key in (UPDATE_MENU, UPDATE_MENU.split(".")[0]) else None
        return f"{label}   {self.t('loop.update_tag', version=release.version)}" if release is not None else label

    def resolve(self, choice: str, theme: str | None = None) -> tuple[str, object] | None:
        """Choix tapé -> ("theme", numéro), ("item", (numéro, libellé, méthode)), ("old", même chose) ou None.
        Dans un thème, « 2 » vise son 2e sous-menu ; partout, « 7.3 » vise un sous-menu ; « 13 » (ancien numéro,
        menu principal seulement) est accepté avec un message."""
        items = {key: (key, label, fn) for key, label, fn in self.items}
        if theme is not None and choice.isdigit() and f"{theme}.{choice}" in items:
            return "item", items[f"{theme}.{choice}"]
        if choice in items:
            return "item", items[choice]
        if theme is None and choice in {t for t, _, _ in MENU_THEMES}:
            return "theme", choice
        if theme is None and choice in OLD_ACCEPTED:
            return "old", items[menu_number(OLD_NUMBERS[choice])]
        return None

    def language(self) -> None:
        """Menu 0 : langue de la console, puis niveau d'affichage (Basic, Normal, Expert), gardés pour ce compte de
        l'ordinateur. Entrée garde chaque choix."""
        t = self.t
        self.say("\n" + t("lang.title"))
        self.say(t("lang.current", name=NAMES[t.lang]))
        for n, code in enumerate(LANGS, 1):
            self.say(f"  {n}) {NAMES[code]} ({code})")
        choice = self.ask(t("lang.prompt")).strip().lower()
        if choice:
            code = LANGS[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(LANGS) else choice
            if code not in LANGS:
                self.say(t("loop.unknown"))
                return
            self.t = Translator(code)
            self._share_language()
            saved = save_lang(self.lang_file, code)
            self.say(self.t("lang.saved", name=NAMES[code]) if saved else self.t("lang.not_saved", path=self.lang_file))
            if code != "fr":
                self.say(self.t("lang.partial"))
        self.choose_level()

    def choose_level(self) -> None:
        t = self.t
        self.say("\n" + t("level.title", level=t(f"level.{self.level}")))
        for n, level in enumerate(LEVELS, 1):
            self.say(f"  {n}) {t(f'level.{level}')} : {t(f'level.{level}.desc')}")
        choice = self.ask(t("level.prompt")).strip()
        if not choice:
            return
        if not (choice.isdigit() and 1 <= int(choice) <= len(LEVELS)):
            self.say(t("loop.unknown"))
            return
        self.level = LEVELS[int(choice) - 1]
        saved = save_level(self.lang_file, self.level)
        self.say(t("level.saved", level=t(f"level.{self.level}")) if saved else t("lang.not_saved", path=self.lang_file))

    def help_menu(self, key: str = "", theme: str | None = None) -> None:
        """Touche « h » : à quoi sert un menu, quand s'en servir, ce qu'il modifie. Mêmes textes que le mode d'emploi
        en ligne (docs/console/contenu*.toml), livrés avec la station dans console_help.json, dans la langue choisie."""
        t = self.t
        if not key:
            key = self.ask(t("help.ask")).strip()
            if not key:
                return
        found = self.resolve(key, theme)
        if found is None:
            self.say(t("help.none", key=key))
            return
        kind, value = found
        if kind == "theme":
            title = next(self.t(f"theme.{tid}") for th, tid, _ in MENU_THEMES if th == value)
            self.say(t("help.theme", key=value, title=title))
            return
        number, label, fn = value
        texts = load_help(t.lang).get(fn.__name__)
        if not texts:
            self.say(t("help.unavailable", key=number, url=DOC_URL))
            return
        title = t("help.title", key=number, label=label)
        out = ["", title, "=" * min(76, len(title))]
        for head, field in (("help.role", "role"), ("help.when", "quand"), ("help.changes", "modifie")):
            if texts.get(field):
                out += ["", t(head).upper(), texts[field]]
        out += ["", t("help.admin", value=t("help.admin_yes") if texts.get("admin") else t("help.admin_no"))]
        if texts.get("expert"):
            out += ["", t("help.more").upper(), texts["expert"]]
        self.say("\n".join(out))

    def paint(self, text: str, color: str) -> str:
        """Texte en couleur dans un vrai terminal (gras) ; tel quel sinon (tests, fichier, pythonw)."""
        return f"[1;{color}m{text}[0m" if self.color else text

    def show_main(self) -> None:
        self.say(self.header())
        self.say("  " + self.paint(f"0) {self.t('menu.language')}", YELLOW))     # en tête : retrouvable dans toute langue
        shown = self.visible_themes()
        for number, title, desc in self.themes():
            if number not in shown:
                continue
            self.say(f"  {number}) {self.menu_label(number, title)}" + (f"  ({desc})" if desc else ""))
        self.say("  " + self.t("loop.help_main"))
        self.say("  " + self.t("loop.quit"))

    def show_theme(self, theme: str) -> None:
        title = next(self.t(f"theme.{tid}") for th, tid, _ in MENU_THEMES if th == theme)
        self.say(f"\n--- {theme}) {title} ---")
        everything = theme not in self.visible_themes()      # thème caché, tapé quand même : tous ses menus
        for key, label, fn in self.items:
            if key.startswith(theme + ".") and (everything or self.visible(fn.__name__)):
                self.say(f"  {key.split('.')[1]}) {self.menu_label(key, label)}")
        self.say("  " + self.t("loop.help_theme", example=f"{theme}.1"))
        self.say("  " + self.t("loop.back"))
        self.say("  " + self.t("loop.quit"))

    def run_item(self, item: tuple[str, str, Callable[[], None]]) -> bool:
        """Lance un sous-menu ; False si le terminal est fermé (quitter)."""
        try:
            item[2]()
        except KeyboardInterrupt:
            self.say("\n" + self.t("loop.interrupted"))
        except EOFError:                             # terminal fermé pendant une question : on quitte proprement
            return False
        self.pause()
        return True

    def loop(self) -> int:
        if not self.config.exists():
            self.say(self.header())
            if self.yes(self.t("loop.first_use")):
                self.assistant()
                self.pause()
        theme: str | None = None
        while True:
            if theme is None:
                self.show_main()
            else:
                self.show_theme(theme)
            if WEB_MODE:                                   # console web : la page sait qu'elle peut ouvrir un menu
                sys.stdout.write(WEB_IDLE_MARK)
                sys.stdout.flush()
            try:
                choice = self.ask(self.t("loop.choice")).strip().lower()
            except EOFError:
                return 0
            if choice in ("q", "quitter", "quit", "beenden", "salir"):
                return 0
            if choice in ("r", "") and theme is not None:
                theme = None
                continue
            if choice == "0":                            # langue, depuis le menu principal ou un thème
                try:
                    self.language()
                except EOFError:
                    return 0
                continue
            asked = re.fullmatch(r"(?:h|aide|help|hilfe|ayuda|\?)\s*([\d.]*)", choice)
            if asked:
                try:
                    self.help_menu(asked.group(1), theme)
                except EOFError:
                    return 0
                self.pause()
                continue
            found = self.resolve(choice, theme)
            if found is None:
                self.say(self.t("loop.unknown"))
                continue
            kind, value = found
            if kind == "theme":
                theme = value
                continue
            if kind == "old":
                self.say(self.t("loop.moved", old=choice, new=value[0], label=value[1]))
            elif not self.visible(value[2].__name__):          # caché à ce niveau : ouvert quand même, signalé
                self.say(self.t("level.hidden_menu", key=value[0], level=self.t(f"level.{menu_level(value[2].__name__)}")))
            if not self.run_item(value):
                return 0


DOC_URL = "https://bob56fr.github.io/openRemoteTRX/console/"


def load_help(lang: str = "fr") -> dict[str, dict]:
    """Textes de l'aide (touche h) par nom de méthode du menu, dans la langue demandée (sinon en français) ; {} si le
    fichier manque ou est illisible."""
    try:
        from importlib.resources import files
        data = json.loads(files("trxstation").joinpath("console_help.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, ModuleNotFoundError):
        return {}
    langs = data.get("langs", {}) if isinstance(data, dict) else {}
    menus = (langs.get(lang) or {}).get("menus") or (langs.get("fr") or {}).get("menus") or {}
    return menus if isinstance(menus, dict) else {}


@guarded("trx-console")
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-console", description="TRX Console : configuration, tests et dépannage")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--diagnostic", action="store_true", help="diagnostic complet puis sortie")
    ap.add_argument("--rapport", action="store_true", help="crée le rapport de dépannage puis sortie")
    ap.add_argument("--texte", action="store_true",
                    help="console texte (menus numérotés au clavier) au lieu de l'écran plein avec pictogrammes")
    ap.add_argument("--web", action="store_true",
                    help="console dans le navigateur (127.0.0.1 seulement, adresse à usage unique ; autre PC : tunnel SSH)")
    ap.add_argument("--port", type=int, default=8765, help="avec --web : port local (8765 par défaut)")
    ap.add_argument("--reseau", action="store_true",
                    help="TRX Console sur le réseau (service : HTTPS, comptes administrateurs, [remote_console])")
    args = ap.parse_args(argv)
    if args.web:
        from .console_web.server import run
        return run(args.config, args.port)
    if args.reseau:
        from .console_web.server import run_network
        return run_network(args.config)
    if args.diagnostic:
        checks = run_all(path=args.config)
        print(format_checks(checks, color=sys.stdout.isatty()))
        return exit_code(checks)
    if args.rapport:
        from .report import make_report
        print(f"Rapport créé : {make_report(config_path=args.config)}")
        return 0
    try:
        console = Console(args.config)
        if not args.texte and sys.stdin.isatty() and sys.stdout.isatty():
            try:
                from .console_tui import run_tui
            except ImportError:                          # Textual absent : console texte
                pass
            else:
                return run_tui(console)
        return console.loop()
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
