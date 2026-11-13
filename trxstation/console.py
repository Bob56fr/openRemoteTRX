# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console : point d'entrée unique de la station pour qui ne connaît pas Linux (commande `trx-console`).

Menus sur deux niveaux, par thème (MENU_THEMES) : 1 Station, 2 Dépannage et essais, 3 Configuration, 4 Accès,
5 Fonctions, 6 Mises à jour ; « 6.3 » tapé directement ouvre un sous-menu ; 0 = langue (fr, en, de, es : trxstation/
i18n/, choix gardé par compte). Les anciens numéros 10 à 24 (un seul niveau, jusqu'à la station 0.125.0) restent
acceptés quelque temps avec le nouveau numéro (OLD_NUMBERS). Les textes des menus et de l'aide « h » viennent des
catalogues de langue ; les textes à l'intérieur des menus sont encore en français (lot L2).
Les actions qui touchent au système passent par `sudo` : le mot de passe de session est demandé au besoin.

    trx-console               menu
    trx-console --diagnostic  diagnostic complet puis sortie (code 1 si une erreur bloquante)
    trx-console --rapport     crée le rapport de dépannage (zip sur le Bureau)
"""
from __future__ import annotations

import argparse
import codecs
import difflib
import json
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
from .i18n import LANGS, NAMES, Translator, load_lang, prefs_path, save_lang
from .paths import default_state_dir
from . import profiles as prof
from .station_id import read_station_id
from .update import apply as upd
from .update.apply import previous_version
from .update.check import Change, UpdateState, clean_text, parse_version, read_state, state_path

TARGET = "trx-remote.target"
IMPORT_NAME = "station.import.toml"
CHECK_UNIT = "trx-update-check.service"
INSTALL_LOG = "/var/log/trx-remote-install.log"
ZIP_PLACES = ("Desktop", "Bureau", "Downloads", "Téléchargements", "")   # où chercher un paquet déposé ("" = dossier personnel)
MAX_DIFF_LINES = 60
GNOME_EXTENSION_UUID = "trx-distant@rf-diy.com"
GNOME_EXTENSION_DIR = Path("/usr/share/gnome-shell/extensions") / GNOME_EXTENSION_UUID
QUIET_AFTER_S = 60.0              # tests : rappel « toujours en cours » après une minute sans rien de nouveau
NOTES_PAGE_LINES = 20             # notes de version : affichées par pages de 20 lignes
UPDATE_MENU = "6.1"
GREEN, YELLOW, RED = "32", "33", "31"   # couleurs ANSI de l'en-tête et du menu 0 (terminal seulement)
# Menus par thème : (numéro du thème, identifiant du titre, [méthodes de Console dans l'ordre des sous-menus]).
# Libellés : « menu.<méthode> » et « theme.<id> » des catalogues trxstation/i18n/console.<langue>.json.
MENU_THEMES = (
    ("1", "station", ("start", "stop", "monitor", "journal", "clear_safe_mode")),
    ("2", "troubleshooting", ("diagnostic", "hwtest", "report", "network", "swr_report", "expert", "qualif")),
    ("3", "configuration", ("assistant", "edit_config", "profiles", "temperature", "indicator")),
    ("4", "access", ("pairing", "visitors")),
    ("5", "features", ("cluster", "breizh", "friends")),
    ("6", "updates", ("update", "rollback", "install_zip")),
)
# Anciens numéros (un seul niveau, jusqu'à la station 0.125.0) -> méthode. 10 à 24 restent acceptés quelque temps
# avec un message ; 1 à 9 ouvrent désormais un thème.
OLD_NUMBERS = {"1": "diagnostic", "2": "assistant", "3": "monitor", "4": "hwtest", "5": "start", "6": "stop",
               "7": "journal", "8": "report", "9": "clear_safe_mode", "10": "update", "11": "rollback",
               "12": "cluster", "13": "install_zip", "14": "edit_config", "15": "expert", "16": "temperature",
               "17": "indicator", "18": "profiles", "19": "pairing", "20": "visitors", "21": "swr_report",
               "22": "breizh", "23": "network", "24": "friends"}
OLD_ACCEPTED = tuple(str(n) for n in range(10, 25))


def menu_number(method: str) -> str:
    """Numéro « thème.sous-menu » d'une méthode de la console (ex. « install_zip » -> « 6.3 »)."""
    for theme, _, methods in MENU_THEMES:
        if method in methods:
            return f"{theme}.{methods.index(method) + 1}"
    raise KeyError(method)
STATUS_FRESH_S = 10               # fichier d'état de la passerelle plus vieux : passerelle arrêtée
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
        if admin and not self.is_root:
            cmd = ["sudo", *cmd]
        try:
            return subprocess.call(cmd)
        except FileNotFoundError:
            print(self.t("runner.not_found", cmd=cmd[0]))
            return 127
        except KeyboardInterrupt:
            print()
            return 130

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
                 lang_file: Path | None = None) -> None:
        self.config, self.runner, self.ask, self.say, self.python = config, runner or Runner(), ask, say, python
        self.color = color if color is not None else (say is print and sys.stdout.isatty())
        self.update_state = update_state or (lambda: read_state(state_path(config_state_dir(self.config))))
        self.previous, self.installed = previous, installed
        self.home = home or Path.home()
        self.editor = editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or shutil.which("nano") or ""
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
        try:
            self.ask("\n" + self.t("loop.pause"))
        except EOFError:
            pass

    def yes(self, question: str, default: bool = True) -> bool:
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
        return any(self.runner.output(["systemctl", "is-active", unit]) == "active" for unit in UNITS)

    def stop_for_exclusive_use(self, why: str) -> bool:
        """Arrête la station si elle tourne (port série et carte son doivent être libres). Vrai si arrêtée ici."""
        if not self.station_running():
            return False
        self.say(self.t("stop_for_exclusive_use.1", why=why))
        self.runner.run(["systemctl", "stop", TARGET], admin=True)
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
                self.runner.run(["systemctl", "start", TARGET], admin=True)
            return
        if self.yes(self.t("assistant.3")):
            self.start()

    def indicator(self) -> None:
        """Extension GNOME installée par install.sh (lecture seule) : l'activer ou la désactiver pour ce compte."""
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

    def cluster(self) -> None:
        if not self.config.exists():
            self.say(self.t("cluster.1"))
            return
        code = self.runner.run(self.module("trxstation.cluster.setup", "--config", str(self.config)), admin=True)
        if code == 0 and self.station_running() and self.yes(self.t("cluster.2")):
            self.start()

    def monitor(self) -> None:
        self.runner.run(self.module("trxstation.monitor.main", "--config", str(self.config)))

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
                      "4": ("--sans-emission",), "5": ()}

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
        stopped = choice != "1" and self.stop_for_exclusive_use(self.t("qualif.why"))
        self.runner.run(self.module("trxstation.qualif.main", "--config", str(self.config), "--output", str(output),
                                    *self.QUALIF_CHOICES[choice]), admin=True)
        if stopped and self.yes(self.t("qualif.5")):
            self.start()

    def start(self) -> None:
        if not self.config.exists():
            self.say(self.t("start.1"))
            return
        code = self.runner.run(["systemctl", "restart", TARGET], admin=True)
        self.say(self.t("start.2") if code == 0
                 else self.t("start.3"))

    def stop(self) -> None:
        code = self.runner.run(["systemctl", "stop", TARGET], admin=True)
        self.say(self.t("stop.1") if code == 0 else self.t("stop.2"))

    def journal(self) -> None:
        self.runner.run(["journalctl", "--no-pager", "-n", "80", "-o", "short", *[f"--unit={u}" for u in UNITS]], admin=True)

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
        self.say(self._apply_result(code, self.t("update.18", version=release.version)))

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
        previous = self.previous()
        if previous is None:
            self.say(self.t("rollback.1"))
            return
        self.say(self.t("rollback.2", installed=self.installed, previous=previous))
        if not self.yes(self.t("rollback.3", previous=previous), False):
            return
        code = self.runner.run(self.module("trxstation.update.apply", "--config", str(self.config), "rollback"),
                               admin=True)
        self.say(self._apply_result(code, self.t("rollback.4", previous=previous)))

    def install_zip(self) -> None:
        """Paquet zip déposé sur la machine : choisi dans une liste, vérifié, installé comme une mise à jour."""
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
        self.say(self._apply_result(code, self.t("install_zip.14", version=version)))

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
            self.say(self.t("edit_config.4", config=self.config))
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

    # ------------------------------------------------------------------ profils de poste (menu 3.3)

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
            code = self.runner.run(["install", "-D", "-m", f"{st.st_mode & 0o777:o}", "-o", str(st.st_uid),
                                    "-g", str(st.st_gid), str(draft), str(target)], admin=True)
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
        code = self.runner.run(["rm", "-f", str(path)], admin=True)
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
        diff = [line for line in difflib.unified_diff(before, after, "avant", "après", n=0, lineterm="")
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
        if self.runner.run(["cp", "-p", str(self.config), str(backup)], admin=True) != 0:
            self.say(self.t("save_config.6"))
            return False
        code = self.runner.run(["install", "-m", f"{st.st_mode & 0o777:o}", "-o", str(st.st_uid), "-g", str(st.st_gid),
                                str(draft), str(self.config)], admin=True)
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
        role = "listener", pseudos, connectés et déconnexion. station.toml passe par le chemin validé du menu 3.2
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
                       "4": self._visitor_delete, "5": self._operator_pseudo}
            if choice == "6":
                self._visitor_kick(cfg)
                continue
            if choice == "7":
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
            answer = self.ask(self.t("ask_int.1", question=question, low=low, high=high, current=current)).strip()
            if not answer:
                return current
            if re.fullmatch(r"\d{1,5}", answer) and low <= int(answer) <= high:
                return int(answer)
            self.say(self.t("ask_int.2", low=low, high=high))

    def _ask_yes(self, question: str, current: bool) -> bool:
        while True:
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

    def _ask_pseudo(self, cfg, current: str = "") -> str | None:
        """Pseudo montré aux autres connectés ; None = abandon."""
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
            elif any(answer.casefold() == c.id.casefold() for c in cfg.clients):
                self.say(self.t("ask_pseudo.6"))
            else:
                return answer

    def _ask_new_password(self, login: str) -> str | None:
        from .passwords import generate_password, password_problem
        while True:
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
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", login) or any(c.id == login for c in cfg.clients):
            self.say(self.t("visitor_create.2"))
            return False
        pseudo = self._ask_pseudo(cfg)
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

    def _operator_pseudo(self, cfg) -> bool:
        account = self._pick_account(cfg, "operator", self.t("verb.name"))
        if account is None:
            return False
        pseudo = self._ask_pseudo(cfg, account.pseudo)
        if pseudo is None or pseudo == account.pseudo:
            return False
        account.pseudo = pseudo
        return True

    def _save_accounts(self, original: bytes, cfg, live: bool = True) -> None:
        """station.toml réécrit depuis `cfg`, validé, puis chemin du menu 3.2 ; `live` : relu sans redémarrer."""
        from . import config as cfgmod
        edited = cfgmod.render_toml(cfg).encode("utf-8")
        if edited == original:
            self.say(self.t("save_accounts.1"))
            return
        work = Path(tempfile.mkdtemp(prefix="trx-config-"))
        try:
            draft = work / "station.toml"
            draft.write_bytes(edited)
            os.chmod(draft, 0o600)                         # contient les empreintes des mots de passe
            try:
                cfgmod.load(draft)
            except cfgmod.ConfigError as exc:
                self.say(self.t("save_accounts.2") + "\n  - ".join(exc.problems))
                return
            self.say(self.t("save_accounts.3"))
            self._save_config(original, edited, draft, live=live)
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
            code = self.runner.run(["install", "-m", "0644", str(request),
                                    str(Path(cfg.supervisor.state_dir) / REOPEN_REQUEST)], admin=True)
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
            code = self.runner.run(["install", "-m", "0644", str(request),
                                    str(Path(cfg.supervisor.state_dir) / KICK_REQUEST)], admin=True)
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
                self.say(self.t("friends.1"))
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
        import secrets
        from .presence.service import CONSOLE_REPLY, CONSOLE_REQUEST
        state_dir = config_state_dir(self.config)
        ident = secrets.token_hex(8)
        body = json.dumps({"id": ident, "action": action, "args": args or {}, "at": time.time()}).encode("utf-8")
        target = state_dir / CONSOLE_REQUEST
        try:
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, target)
        except PermissionError:                   # dossier du compte de la station : par l'administrateur (Linux)
            work = Path(tempfile.mkdtemp(prefix="trx-presence-"))
            try:
                (work / CONSOLE_REQUEST).write_bytes(body)
                if self.runner.run(["install", "-m", "0644", str(work / CONSOLE_REQUEST), str(target)], admin=True) != 0:
                    self.say(self.t("friends_request.1"))
                    return None
            finally:
                shutil.rmtree(work, ignore_errors=True)
        except OSError as exc:
            self.say(self.t("friends_request.2", exc=exc))
            return None
        reply_path = state_dir / "presence" / CONSOLE_REPLY
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                reply = json.loads(reply_path.read_text(encoding="utf-8"))
                if reply.get("id") == ident:
                    return reply
            except (OSError, ValueError):
                pass
            time.sleep(poll_s)
        self.say(self.t("friends_request.3"))
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
            if self.typed_word(self.ask(self.t("friends_leave.type_word", word=self.t("word.delete"))), "word.delete", "SUPPRIMER") and self._friends_do("delete", {"g": g}) is not None:
                self.say(self.t("friends_leave.2"))
            return
        if self.yes(self.t("friends_leave.3"), False) and self._friends_do("leave", {"g": g}) is not None:
            self.say(self.t("friends_leave.4"))

    # ------------------------------------------------------------------ qualité du réseau (menu 2.4)

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
        answer = self.ask(self.t("network_clear.1", word=self.t("word.erase"))).strip()
        if not self.typed_word(answer, "word.erase", "EFFACER", exact=True):
            self.say(self.t("network_clear.2"))
            return
        if self._gateway_status() is not None:          # station en marche : c'est elle qui efface (mémoire comprise)
            work = Path(tempfile.mkdtemp(prefix="trx-net-"))
            try:
                request = work / CLEAR_REQUEST
                request.write_bytes(kick_request("console"))
                code = self.runner.run(["install", "-m", "0644", str(request), str(state_dir / CLEAR_REQUEST)], admin=True)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            self.say(self.t("network_clear.3") if code == 0
                     else self.t("network_clear.4", code=code))
            return
        folder = state_dir / "netprobe"
        if not folder.is_dir():
            self.say(self.t("network_clear.5"))
            return
        code = self.runner.run(["find", str(folder), "-maxdepth", "1", "-type", "f", "!", "-name", "seuils.json",
                                "-delete"], admin=True)
        self.say(self.t("network_clear.6") if code == 0 else self.t("network_clear.7", code=code))

    # ------------------------------------------------------------------ Breizh Audio Box (menu 5.2)

    BREIZH_STATES = {"connecting": "breizh.state.connecting", "ready": "breizh.state.ready", "active": "breizh.state.active",
                     "fallback": "breizh.state.fallback", "refused": "breizh.state.refused"}   # clés du catalogue

    def breizh(self) -> None:
        """Breizh Audio Box (docs/breizh-cahier-des-charges.md) : clé d'appairage (breizh.key, à côté de station.toml,
        créée ici et montrée UNE fois), adresse et port de Breizh et activation ([breizh] de station.toml, chemin validé
        du menu 3.2), essai de la liaison SANS son, état publié par la passerelle, journal. Rien ici ne touche au PTT."""
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
                code = self.runner.run(["install", "-m", f"{mode:o}", "-o", str(st.st_uid), "-g", str(st.st_gid),
                                        str(draft), str(path)], admin=True)
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
        le même chemin que le menu 3.2 : copie, validation, différences, confirmation, sauvegarde."""
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
        return [address_line(n.gateway_bind, n.gateway_port, bool(n.tls_cert), found, self.t),
                rig_vitals_line(status.rig if status is not None else None, self.t)]

    def menu_label(self, key: str, label: str) -> str:
        release = self.offered(self.update_state()) if key in (UPDATE_MENU, UPDATE_MENU.split(".")[0]) else None
        return f"{label}   {self.t('loop.update_tag', version=release.version)}" if release is not None else label

    def resolve(self, choice: str, theme: str | None = None) -> tuple[str, object] | None:
        """Choix tapé -> ("theme", numéro), ("item", (numéro, libellé, méthode)), ("old", même chose) ou None.
        Dans un thème, « 2 » vise son 2e sous-menu ; partout, « 6.3 » vise un sous-menu ; « 13 » (ancien numéro,
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
        """Menu 0 : langue de la console, gardée pour ce compte de l'ordinateur."""
        t = self.t
        self.say("\n" + t("lang.title"))
        self.say(t("lang.current", name=NAMES[t.lang]))
        for n, code in enumerate(LANGS, 1):
            self.say(f"  {n}) {NAMES[code]} ({code})")
        choice = self.ask(t("lang.prompt")).strip().lower()
        if not choice:
            return
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
        for number, title, desc in self.themes():
            self.say(f"  {number}) {self.menu_label(number, title)}" + (f"  ({desc})" if desc else ""))
        self.say("  " + self.t("loop.help_main"))
        self.say("  " + self.t("loop.quit"))

    def show_theme(self, theme: str) -> None:
        title = next(self.t(f"theme.{tid}") for th, tid, _ in MENU_THEMES if th == theme)
        self.say(f"\n--- {theme}) {title} ---")
        for key, label, _ in self.items:
            if key.startswith(theme + "."):
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
            try:
                choice = self.ask(self.t("loop.choice")).strip().lower()
            except EOFError:
                return 0
            if choice in ("q", "quitter", "quit", "beenden", "salir"):
                return 0
            if choice in ("r", "") and theme is not None:
                theme = None
                continue
            if choice == "0" and theme is None:
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-console", description="TRX Console : configuration, tests et dépannage")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--diagnostic", action="store_true", help="diagnostic complet puis sortie")
    ap.add_argument("--rapport", action="store_true", help="crée le rapport de dépannage puis sortie")
    args = ap.parse_args(argv)
    if args.diagnostic:
        checks = run_all(path=args.config)
        print(format_checks(checks, color=sys.stdout.isatty()))
        return exit_code(checks)
    if args.rapport:
        from .report import make_report
        print(f"Rapport créé : {make_report(config_path=args.config)}")
        return 0
    try:
        return Console(args.config).loop()
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
