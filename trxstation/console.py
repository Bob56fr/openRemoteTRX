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
# Menus par thème : (numéro du thème, identifiant du titre, [méthodes de Console dans l'ordre des sous-menus]).
# Libellés : « menu.<méthode> » et « theme.<id> » des catalogues trxstation/i18n/console.<langue>.json.
MENU_THEMES = (
    ("1", "station", ("start", "stop", "monitor", "journal", "clear_safe_mode")),
    ("2", "troubleshooting", ("diagnostic", "hwtest", "report", "network", "swr_report", "expert")),
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

    def __init__(self) -> None:
        self.is_root = hasattr(os, "geteuid") and os.geteuid() == 0

    def run(self, cmd: list[str], *, admin: bool = False) -> int:
        if admin and not self.is_root:
            cmd = ["sudo", *cmd]
        try:
            return subprocess.call(cmd)
        except FileNotFoundError:
            print(f"Commande introuvable : {cmd[0]}")
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
                        sys.stdout.write(f"\n  ... toujours en cours ({format_duration(now - started)} écoulées) : "
                                         "test long ou petit PC, patience.\n")
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
            print(f"Commande introuvable : {cmd[0]}")
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

    def station_running(self) -> bool:
        return any(self.runner.output(["systemctl", "is-active", unit]) == "active" for unit in UNITS)

    def stop_for_exclusive_use(self, why: str) -> bool:
        """Arrête la station si elle tourne (port série et carte son doivent être libres). Vrai si arrêtée ici."""
        if not self.station_running():
            return False
        self.say(f"La station est en marche : elle va être arrêtée pendant {why}.")
        self.runner.run(["systemctl", "stop", TARGET], admin=True)
        return True

    # ------------------------------------------------------------------ actions

    def diagnostic(self) -> None:
        self.say("Diagnostic en cours (lecture seule, aucune émission)...")
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
        breizh = "activé" if b.enabled else "désactivé"
        if b.enabled:
            status = self._gateway_status()
            live = status.breizh if status is not None and isinstance(getattr(status, "breizh", None), dict) else {}
            state = self.BREIZH_STATES.get(live.get("state"), live.get("state")) if live else "passerelle arrêtée"
            breizh += f" ({b.host or 'adresse à régler'} port {b.port}) · liaison : {state}"
        today = date.today()
        accounts = []
        for c in (c for c in cfg.clients if c.role == "listener"):
            label = self._account_label(c)
            accounts.append(label + (" EXPIRÉ" if c.expired(today) else ""))
        return "\n".join([
            "\nModes de la station :",
            f"  Breizh Audio Box : {breizh}",
            "  Visiteurs        : " + (f"écoute OUVERTE, {a.max_listeners} au plus" if a.max_listeners
                                       else "écoute FERMÉE (max_listeners = 0)"),
            "  Comptes visiteurs: " + (", ".join(accounts) or "aucun"),
        ])

    def assistant(self) -> None:
        stopped = self.stop_for_exclusive_use("l'assistant")
        cmd = self.module("trxstation.setup_wizard", "--output", str(self.config))
        imported = self.config.parent / IMPORT_NAME
        if not self.config.exists() and imported.exists():
            self.say(f"Reprise de la configuration importée de l'ancien PC ({imported}).")
            cmd += ["--base", str(imported)]
        code = self.runner.run(cmd, admin=True)
        if code != 0:
            self.say("L'assistant n'est pas allé au bout : rien n'a été modifié.")
            if stopped and self.config.exists():
                self.runner.run(["systemctl", "start", TARGET], admin=True)
            return
        if self.yes("Démarrer la station maintenant"):
            self.start()

    def indicator(self) -> None:
        """Extension GNOME installée par install.sh (lecture seule) : l'activer ou la désactiver pour ce compte."""
        tool = shutil.which("gnome-extensions")
        if tool is None:
            self.say("Bureau sans GNOME (ou outil gnome-extensions absent) : l'indicateur n'existe que pour GNOME pour l'instant.")
            return
        if not GNOME_EXTENSION_DIR.is_dir():
            self.say(f"Indicateur absent ({GNOME_EXTENSION_DIR}) : installe la version 0.49.0 ou plus récente (menu 6.3).")
            return
        known = GNOME_EXTENSION_UUID in self.runner.output([tool, "list"]).split()
        if not known:
            self.say("L'indicateur est installé mais GNOME ne le connaît pas encore : déconnecte-toi puis reconnecte-toi,\n"
                     "puis reviens dans ce menu.")
            return
        enabled = GNOME_EXTENSION_UUID in self.runner.output([tool, "list", "--enabled"]).split()   # sans dépendre de la langue
        self.say("L'indicateur affiche en haut de l'écran, à gauche du son : un voyant (vert réception, rouge émission,\n"
                 "orange alerte, gris station arrêtée, violet mode sûr), la fréquence ou le compte à rebours d'émission,\n"
                 "et au clic l'état complet (clients, poste, spectre, Cluster DX, température, mise à jour...).\n"
                 "Il ne fait que LIRE l'état de la station : il ne peut rien commander.\n"
                 f"État : {'ACTIVÉ' if enabled else 'désactivé'}.")
        if enabled:
            if self.yes("Désactiver l'indicateur", False):
                code = self.runner.run([tool, "disable", GNOME_EXTENSION_UUID])
                self.say("Indicateur désactivé." if code == 0 else f"Échec de la désactivation (code {code}).")
        elif self.yes("Activer l'indicateur", True):
            code = self.runner.run([tool, "enable", GNOME_EXTENSION_UUID])
            self.say("Indicateur activé : il apparaît en haut à droite." if code == 0 else
                     f"Échec de l'activation (code {code}) : déconnecte-toi puis reconnecte-toi et réessaie.")

    def cluster(self) -> None:
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 3.1).")
            return
        code = self.runner.run(self.module("trxstation.cluster.setup", "--config", str(self.config)), admin=True)
        if code == 0 and self.station_running() and self.yes("Redémarrer la station pour appliquer"):
            self.start()

    def monitor(self) -> None:
        self.runner.run(self.module("trxstation.monitor.main", "--config", str(self.config)))

    def hwtest(self) -> None:
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 3.1).")
            return
        from .audio_devices import desktop_audio_advice
        self.say("Avant l'essai, vérifie le son de l'ordinateur :\n" + desktop_audio_advice() + "\n")
        self.say("Essai sur le vrai poste :\n"
                 "  1) en réception seule (aucune émission) : CAT, audio reçu, accord, largeurs de filtre, écran du spectre\n"
                 "  2) complet : la même chose, puis l'émission (charge fictive, puissance réduite, confirmation à chaque étape)")
        choice = self.ask("Choix (1, 2 ; Entrée = annuler) : ").strip()
        if choice not in ("1", "2"):
            self.say("Annulé.")
            return
        stopped = self.stop_for_exclusive_use("l'essai")
        extra = ["--reception-seule"] if choice == "1" else []
        self.runner.run(self.module("trxstation.devtools.hwtest", "--config", str(self.config), *extra), admin=True)
        if stopped and self.yes("Redémarrer la station"):
            self.start()

    def start(self) -> None:
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 3.1).")
            return
        code = self.runner.run(["systemctl", "restart", TARGET], admin=True)
        self.say("Station démarrée. Diagnostic conseillé dans quelques secondes (menu 2.1)." if code == 0
                 else "Le démarrage a échoué : voir le journal (menu 1.4).")

    def stop(self) -> None:
        code = self.runner.run(["systemctl", "stop", TARGET], admin=True)
        self.say("Station arrêtée (le poste reste en réception)." if code == 0 else "Arrêt impossible : voir le journal (menu 1.4).")

    def journal(self) -> None:
        self.runner.run(["journalctl", "--no-pager", "-n", "80", "-o", "short", *[f"--unit={u}" for u in UNITS]], admin=True)

    def report(self) -> None:
        from .report import make_report
        try:
            path = make_report(config_path=self.config)
        except OSError as exc:
            self.say(f"Rapport impossible : {exc}")
            return
        self.say(f"Rapport créé : {path}\nIl ne contient aucun mot de passe : joins-le à ta demande d'aide.")

    def clear_safe_mode(self) -> None:
        self.say("Le mode sûr a été déclenché par le superviseur après des pannes répétées.\n"
                 "Vérifie d'abord la cause (menu 2.1 et menu 1.4).")
        if not self.yes("La cause est réglée, sortir du mode sûr", False):
            return
        code = self.runner.run(self.module("trxstation.supervisor.main", "--config", str(self.config),
                                           "--clear-safe-mode"), admin=True)
        if code == 0:
            self.start()

    def update(self) -> None:
        state = self.update_state()
        if state is None:
            self.say("Pas encore de recherche de mise à jour (elle a lieu 2 minutes après le démarrage de la station).")
            if self.config.exists() and self.yes("Chercher maintenant", False):
                state = self.search_now()
            if state is None:
                return
        if not state.ok:
            self.say(f"Dernière recherche impossible : {clean_text(state.error, 300, single_line=True)}")
        release = self.offered(state)
        if release is None:
            checked = time.strftime("%d/%m/%Y %H:%M", time.localtime(state.checked_at)) if state.checked_at else "inconnue"
            self.say(f"TRX distant est à jour (version {self.installed}). Dernière recherche : {checked}.")
            if not (self.config.exists() and self.yes("Chercher à nouveau maintenant sur GitHub", False)):
                return
            state = self.search_now()
            release = self.offered(state)
            if release is None:
                self.say("Toujours à jour." if state is not None and state.ok else "Recherche impossible : "
                         + clean_text(state.error if state is not None else "aucun résultat", 300, single_line=True))
                return
        changes = self.changes_of(state, release)
        published = clean_text(release.published_at, 40, single_line=True)[:10]
        self.say(self.banner([f"NOUVELLE VERSION {release.version}{' (PRÉ-VERSION)' if release.prerelease else ''}"
                              f" ; installée : {self.installed}",
                              clean_text(release.name, 120, single_line=True) + (f" ({published})" if published else "")]))
        if len(changes) > 1:
            self.say(f"{len(changes)} versions publiées depuis la tienne : "
                     + ", ".join(c.version for c in reversed(changes)) + " (toutes comprises dans la mise à jour).")
        if self.yes("Voir la nature des changements avant de décider", True):
            self.show_changes(changes)
            self.say(f"\nNotes complètes sur GitHub : {clean_text(release.page_url, 200, single_line=True)}")
        self.say("\nPendant l'installation (quelques minutes, Internet nécessaire), la station est arrêtée.\n"
                 "Elle est refusée tant que le poste émet. Le paquet est vérifié (signature) avant toute installation ;\n"
                 f"la version {self.installed}, station.toml et les certificats sont conservés (retour possible : menu 6.2).")
        entered = self.ask(f"Pour installer, tape le numéro de version {release.version} (Entrée = non) : ").strip()
        if entered != release.version:
            self.say(f"Mise à jour annulée : rien n'a été modifié. Elle reste proposée par le menu {UPDATE_MENU}.")
            return
        code = self.runner.run(self.module("trxstation.update.apply", "--config", str(self.config), "install",
                                           "--version", release.version), admin=True)
        self.say(self._apply_result(code, f"Version {release.version} installée. Quitte TRX Console (q) et "
                                          "rouvre-la pour utiliser la nouvelle version."))

    def search_now(self) -> UpdateState | None:
        """Recherche immédiate par le service de la station (compte trx, jamais root) ; rien n'est installé."""
        self.say("Recherche sur GitHub...")
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
            lines += ["", f"--- Version {change.version}{' du ' + published if published else ''} : "
                          f"{clean_text(change.name, 120, single_line=True)} ---"]
            lines += (clean_text(change.notes, 4000) or "(aucune note)").split("\n")
        for start in range(0, len(lines), NOTES_PAGE_LINES):
            self.say("\n".join(lines[start:start + NOTES_PAGE_LINES]))
            if start + NOTES_PAGE_LINES < len(lines):
                if self.ask("-- Entrée : suite des notes ; q : arrêter là -- ").strip().lower() in ("q", "quitter"):
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
            self.say("Aucune version précédente gardée : elle apparaît après une première mise à jour.")
            return
        self.say(f"Version active : {self.installed}. Version précédente gardée : {previous}.\n"
                 "Le retour se fait sans Internet ; la station est arrêtée pendant l'opération.")
        if not self.yes(f"Revenir à la version {previous}", False):
            return
        code = self.runner.run(self.module("trxstation.update.apply", "--config", str(self.config), "rollback"),
                               admin=True)
        self.say(self._apply_result(code, f"Retour à la version {previous} fait. Quitte TRX Console (q) et "
                                          "rouvre-la. La version plus récente restera proposée par le menu 6.1."))

    def install_zip(self) -> None:
        """Paquet zip déposé sur la machine : choisi dans une liste, vérifié, installé comme une mise à jour."""
        packages = find_packages(self.home)
        if not packages:
            self.say("Aucun paquet « trx-remote-debian-X.Y.Z.zip » sur le Bureau, dans Téléchargements ni dans le\n"
                     f"dossier personnel ({self.home}). Copie-le à l'un de ces endroits puis recommence.")
            return
        self.say(f"Version installée : {self.installed}\nPaquets trouvés :")
        for number, (version, path) in enumerate(packages, 1):
            signed = path.with_name(path.name + ".sig").is_file()
            self.say(f"  {number}) {version:<10} {'signé' if signed else 'NON signé'}   {path}")
        choice = self.ask("Numéro du paquet à installer (Entrée = annuler) : ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(packages):
            self.say("Annulé : rien n'a été modifié.")
            return
        version, path = packages[int(choice) - 1]
        signed = path.with_name(path.name + ".sig").is_file()
        newer, current = parse_version(version) or (), parse_version(self.installed) or ()
        if newer < current:
            self.say(f"ATTENTION : {version} est plus ANCIENNE que la version installée ({self.installed}).\n"
                     "Pour revenir simplement à la version précédente, le menu 6.2 suffit.")
        elif newer == current:
            self.say(f"La version {version} est déjà installée : elle sera réinstallée.")
        self.say("\nPendant l'installation (quelques minutes, Internet nécessaire pour les modules Python), la station\n"
                 "est arrêtée. Elle est refusée tant que le poste émet ; le contenu du paquet est contrôlé avant\n"
                 f"toute installation ; la version {self.installed}, station.toml et les certificats sont conservés.")
        extra: list[str] = []
        if not signed:
            self.say("\nCe paquet n'est PAS SIGNÉ : rien ne garantit qu'il vient de l'équipe TRX distant. Installe-le\n"
                     "seulement si tu l'as toi-même copié depuis une source sûre (ton PC, ta clé USB).")
            if not typed(self.ask("Tape OUI pour accepter un paquet non signé (Entrée = non) : "), "OUI"):
                self.say("Annulé : rien n'a été modifié.")
                return
            extra = ["--sans-signature"]
        entered = self.ask(f"Pour installer, tape le numéro de version {version} (Entrée = non) : ").strip()
        if entered != version:
            self.say("Annulé : rien n'a été modifié.")
            return
        code = self.runner.run(self.module("trxstation.update.apply", "--config", str(self.config), "local",
                                           "--zip", str(path), *extra), admin=True)
        self.say(self._apply_result(code, f"Version {version} installée. Quitte TRX Console (q) et "
                                          "rouvre-la pour utiliser la nouvelle version."))

    def edit_config(self) -> None:
        """station.toml modifiée sur une COPIE (nano), validée, différences montrées, puis enregistrée par sudo
        avec ses droits d'origine ; l'ancienne version est gardée à côté. Une configuration invalide n'est jamais écrite."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 3.1).")
            return
        try:
            original = self.config.read_bytes()
        except OSError as exc:
            self.say(f"Lecture de {self.config} impossible ({exc}).\nSi tu viens d'être ajouté au groupe « trx », "
                     "ferme ta session puis rouvre-la.")
            return
        if not self.editor:
            self.say("Aucun éditeur de texte trouvé : installe nano (sudo apt install nano).")
            return
        work = Path(tempfile.mkdtemp(prefix="trx-config-"))
        draft = work / "station.toml"
        try:
            draft.write_bytes(original)
            os.chmod(draft, 0o600)                         # contient les empreintes des mots de passe
            self.say(f"Modification de {self.config} (sur une copie : rien n'est changé avant ta confirmation).\n"
                     "Dans nano : Ctrl+O puis Entrée pour enregistrer, Ctrl+X pour quitter.")
            while True:
                self.runner.run([self.editor, str(draft)])
                edited = draft.read_bytes()
                if edited == original:
                    self.say("Aucune modification : station.toml n'a pas été changé.")
                    return
                try:
                    cfgmod.load(draft)
                    break
                except cfgmod.ConfigError as exc:
                    self.say("Configuration REFUSÉE (la station ne démarrerait pas) :\n  - " + "\n  - ".join(exc.problems))
                    if not self.yes("Reprendre la modification", True):
                        self.say("Abandon : station.toml n'a pas été changé.")
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
            self.say("Configure d'abord la station (menu 3.1).")
            return
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
            show_pairing(cfg, ask=self.ask, say=self.say)
        except PermissionError:                            # certificat réservé à la station : relu avec les droits d'administration
            self.runner.run(self.module("trxstation.setup_wizard", "--output", str(self.config), "--empreinte"), admin=True)
        except (OSError, ValueError, cfgmod.ConfigError) as exc:
            self.say(f"Lecture impossible ({exc}).")

    def profiles(self) -> None:
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 3.1).")
            return
        self._list_profiles()
        self.say("\n  1) Enregistrer la configuration actuelle du poste sous un profil\n"
                 "  2) Charger un profil (changer de poste)\n"
                 "  3) Supprimer un profil\n"
                 "  q) Retour")
        choice = self.ask("Choix : ").strip().lower()
        action = {"1": self._save_profile, "2": self._load_profile, "3": self._delete_profile}.get(choice)
        if action is not None:
            action()

    def _list_profiles(self) -> list[tuple[Path, prof.Profile | None, str]]:
        from . import config as cfgmod
        found = prof.list_profiles(self.config)
        self.say("Un profil garde ce qui dépend du POSTE : modèle, ports, PTT, cartes son, spectre. Les comptes, le réseau,\n"
                 "les bandes autorisées et les sécurités appartiennent à la station : un profil n'y touche jamais.")
        if not found:
            self.say("\nAucun profil enregistré.")
            return found
        try:
            current, _ = cfgmod.load_unchecked(self.config)
        except (OSError, cfgmod.ConfigError):
            current = None
        self.say("\nProfils enregistrés :")
        for number, (path, profile, problem) in enumerate(found, 1):
            if profile is None:
                self.say(f"  {number}) {path.name:<28} INUTILISABLE : {problem}")
                continue
            if profile.format > prof.PROFILE_FORMAT:
                state = "version plus récente : mettre TRX distant à jour"
            elif profile.format < prof.PROFILE_FORMAT:
                state = "ancien format : converti au chargement"
            else:
                state = ""
            rig = profile.sections.get("rig")
            model = rig.get("model", "?") if isinstance(rig, dict) else "?"
            here = "  <- poste en service" if current is not None and prof.same_rig(current, profile) else ""
            self.say(f"  {number}) {profile.name:<28} modèle Hamlib {model}, enregistré le {profile.saved_at} "
                     f"(version {profile.version}){' ; ' + state if state else ''}{here}")
        return found

    def _choose_profile(self, found, verb: str):
        if not found:
            return None
        choice = self.ask(f"Numéro du profil à {verb} (Entrée = annuler) : ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(found):
            self.say("Annulé.")
            return None
        return found[int(choice) - 1]

    def _save_profile(self) -> None:
        from . import config as cfgmod
        try:
            cfg = cfgmod.load(self.config)
        except (OSError, cfgmod.ConfigError) as exc:
            self.say(f"Configuration actuelle invalide ou illisible : corrige-la d'abord (menu 3.2). ({exc})")
            return
        name = self.ask("Nom du profil (ex. IC-7300 maison ; Entrée = annuler) : ").strip()
        if not name:
            self.say("Annulé.")
            return
        if not prof.valid_name(name):
            self.say("Nom refusé : 40 caractères au plus, lettres, chiffres, espaces et - _ . + seulement.")
            return
        target = prof.folder_for(self.config) / prof.file_name(name)
        if target.exists() and not self.yes(f"Le profil {target.name} existe déjà : le remplacer", False):
            self.say("Annulé : rien n'a été modifié.")
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
        self.say(f"Profil « {name} » enregistré : {target}" if code == 0 else
                 f"Enregistrement impossible (code {code}) : rien n'a été modifié.")

    def _load_profile(self) -> None:
        picked = self._choose_profile(self._list_profiles(), "charger")
        if picked is None:
            return
        path, profile, problem = picked
        if profile is None:
            self.say(f"Profil inutilisable : {problem}")
            return
        if self.transmitting():
            self.say("Refusé : le poste émet (ou son état est illisible). Charge le profil une fois revenu en réception.")
            return
        try:
            original = self.config.read_bytes()
            _, text = prof.apply(original.decode("utf-8"), profile)
        except prof.ProfileError as exc:
            self.say(f"Chargement impossible : {exc}")
            return
        except OSError as exc:
            self.say(f"Lecture de {self.config} impossible ({exc}).")
            return
        if profile.format < prof.PROFILE_FORMAT:
            self.say(f"Profil d'un ancien format ({profile.format}) converti au format {prof.PROFILE_FORMAT}. Vérifie les "
                     "changements ci-dessous ; réenregistre-le ensuite (choix 1) pour ne plus avoir à le convertir.")
        rig = profile.sections.get("rig")
        port = str(rig.get("port", "")) if isinstance(rig, dict) else ""
        if port and not Path(port).exists():
            self.say(f"Attention : le port du poste {port} est absent pour l'instant (poste éteint ou pas encore branché ?).")
        edited = text.encode("utf-8")
        if edited == original:
            self.say("Ce profil est déjà celui du poste en service : rien à changer.")
            return
        work = Path(tempfile.mkdtemp(prefix="trx-config-"))
        try:
            draft = work / "station.toml"
            draft.write_bytes(edited)
            os.chmod(draft, 0o600)                         # contient les empreintes des mots de passe
            self.say(f"Chargement du profil « {profile.name} » : seules les sections [rig], [audio] et [spectrum] changent "
                     "(station.toml est réécrit dans sa forme standard).")
            self._save_config(original, edited, draft)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _delete_profile(self) -> None:
        picked = self._choose_profile(self._list_profiles(), "supprimer")
        if picked is None:
            return
        path, profile, _ = picked
        if not self.yes(f"Supprimer définitivement le profil {profile.name if profile else path.name}", False):
            self.say("Annulé.")
            return
        code = self.runner.run(["rm", "-f", str(path)], admin=True)
        self.say("Profil supprimé." if code == 0 else f"Suppression impossible (code {code}).")

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
        self.say("Changements :\n" + "\n".join("  " + line for line in diff[:MAX_DIFF_LINES])
                 + (f"\n  ... ({len(diff) - MAX_DIFF_LINES} lignes de plus)" if len(diff) > MAX_DIFF_LINES else ""))
        if not self.yes("Enregistrer ces changements", False):
            self.say("Abandon : station.toml n'a pas été changé.")
            return False
        if self.config.read_bytes() != original:
            self.say("station.toml a été modifié par ailleurs pendant ce temps : abandon, recommence.")
            return False
        st = self.config.stat()
        backup = self.config.with_name(f"{self.config.name}.avant-modification-{time.strftime('%Y%m%d-%H%M%S')}")
        if self.runner.run(["cp", "-p", str(self.config), str(backup)], admin=True) != 0:
            self.say("Copie de sauvegarde impossible : station.toml n'a pas été changé.")
            return False
        code = self.runner.run(["install", "-m", f"{st.st_mode & 0o777:o}", "-o", str(st.st_uid), "-g", str(st.st_gid),
                                str(draft), str(self.config)], admin=True)
        if code != 0:
            self.say(f"Enregistrement impossible (code {code}) : station.toml n'a pas été changé.")
            return False
        self.say(f"Enregistré. Ancienne version gardée : {backup}")
        if live:
            self.say("La station prend ces changements en compte d'elle-même en quelques secondes (sans redémarrer) ; "
                     "un compte désactivé ou supprimé est déconnecté aussitôt.")
        elif self.station_running():
            if self.yes("Redémarrer la station pour appliquer"):
                self.start()
        else:
            self.say("Les changements s'appliqueront au prochain démarrage de la station (menu 1.1).")
        return True

    # ------------------------------------------------------------------ visiteurs (menu 4.2)

    def swr_report(self) -> None:
        """Dernière mesure de TOS (state_dir/swr.json) : lecture seule. La console ne lance JAMAIS de mesure (un outil ne
        peut que couper) : la mesure se lance depuis la page ou l'application."""
        from .swr.plan import level
        from .swr.store import SwrStore
        last = SwrStore(config_state_dir(self.config) / "swr.json").last()
        if not last or not last.get("points"):
            self.say("Aucune mesure de TOS rangée sur cette station. Elle se lance depuis la page ou l'application "
                     "(rubrique « Mesure de TOS »), jamais depuis la console.")
            return
        when = time.strftime("%d/%m/%Y %H:%M", time.localtime(last.get("at") or 0))
        power = f"{last['power_w']} W" if last.get("power_w") else f"{last.get('power_pct')} %"
        out = [f"\nDernière mesure de TOS : {when}, {power} en {last.get('fm_mode')}",
               f"  de {last['low_hz'] / 1e6:.3f} à {last['high_hz'] / 1e6:.3f} MHz, pas de {last['step_hz'] // 1000} kHz", ""]
        marks = {"good": "", "fair": "  (moyen)", "bad": "  ÉLEVÉ"}
        for p in last["points"]:
            swr = p.get("swr")
            if swr is None:
                text = {"out_of_band": "hors bande", "unread": "non lu"}.get(p.get("status"), p.get("status") or "—")
                out.append(f"  {p['hz'] / 1e6:9.3f} MHz   {text}")
            else:
                bar = "#" * max(1, min(40, round((min(swr, 5.0) - 1) * 10)))
                out.append(f"  {p['hz'] / 1e6:9.3f} MHz   {swr:4.2f}  {bar}{marks[level(swr)]}"
                           + ("  (puissance réduite par le poste)" if p.get("status") == "reduced" else ""))
        best = last.get("best")
        if best:
            out.append(f"\n  Meilleur TOS : {best['swr']:.2f} à {best['hz'] / 1e6:.3f} MHz")
        if last.get("reason") and last["reason"] != "done":
            out.append(f"  Mesure interrompue : {last.get('detail') or last['reason']}")
        for diff in last.get("differences") or []:
            out.append(f"  À CORRIGER À LA MAIN : {diff}")
        self.say("\n".join(out))

    def visitors(self) -> None:
        """Visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md) : réglages [access], comptes
        role = "listener", pseudos, connectés et déconnexion. station.toml passe par le chemin validé du menu 3.2
        (réécrit dans sa forme standard) ; la passerelle le relit sans redémarrer."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 3.1).")
            return
        while True:
            try:
                original = self.config.read_bytes()
                cfg, _ = cfgmod.load_unchecked(self.config)
            except (OSError, cfgmod.ConfigError) as exc:
                self.say(f"Lecture de {self.config} impossible ({exc}).")
                return
            self.say(self._visitors_summary(cfg))
            choice = self.ask("\n  1) Réglages (nombre maximal, opérateur requis, attente, hors bandes)\n"
                              "  2) Créer un compte visiteur\n"
                              "  3) Modifier un compte visiteur (pseudo, mot de passe, activé, expiration)\n"
                              "  4) Supprimer un compte visiteur\n"
                              "  5) Pseudo d'un compte opérateur (montré aux visiteurs)\n"
                              "  6) Déconnecter un visiteur connecté\n"
                              "  7) Rouvrir l'écoute suspendue par une surcharge de la station\n"
                              "Choix (Entrée = retour) : ").strip()
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
                self.say("Choix inconnu.")
                continue
            if action(cfg):
                self._save_accounts(original, cfg)

    def _visitors_summary(self, cfg) -> str:
        a = cfg.access
        listeners = [c for c in cfg.clients if c.role == "listener"]
        lines = ["\nVisiteurs en réception seule : ils écoutent et voient l'écran, sans AUCUNE commande vers le poste.",
                 f"  Écoute des visiteurs : {'ouverte, ' + str(a.max_listeners) + ' au plus' if a.max_listeners else 'FERMÉE (0)'}",
                 "  Opérateur requis     : " + (f"oui (visiteurs déconnectés {a.operator_grace_s} s après sa perte)"
                                                if a.listeners_need_operator else "non (écoute possible sans opérateur)"),
                 "  Hors bandes          : " + ("écoute permise" if a.listeners_outside_bands else "silence pour les visiteurs"),
                 "  Comptes visiteurs    : " + (", ".join(self._account_label(c) for c in listeners) or "aucun")]
        presence = self._presence()
        if isinstance(presence.get("open"), bool):        # commutateur de l'opérateur (page, application)
            lines.append("  Commutateur opérateur: " + ("ÉCOUTE OUVERTE" if presence["open"] else
                                                       "écoute fermée (l'opérateur l'ouvre depuis la page ou l'application)"))
        suspended = presence.get("suspended")
        if isinstance(suspended, dict):
            lines.append("  ÉCOUTE SUSPENDUE     : " + str(suspended.get("message", ""))[:300])
        connected = [c for c in self._connected() if c.get("role") == "listener"]
        lines.append("  Connectés maintenant : " + (", ".join(
            f"{c.get('pseudo', '?')} ({c.get('id', '?')}, {c.get('source', '?')}, {int(c.get('since_s', 0)) // 60} min)"
            for c in connected) or "aucun visiteur"))
        return "\n".join(lines)

    @staticmethod
    def _account_label(c) -> str:
        notes = [n for n in ("désactivé" if not c.enabled else "", f"jusqu'au {c.expires}" if c.expires else "") if n]
        return f"{c.id} « {c.pseudo or 'sans pseudo'} »" + (f" ({', '.join(notes)})" if notes else "")

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
            answer = self.ask(f"{question} ({low} à {high}, Entrée = {current}) : ").strip()
            if not answer:
                return current
            if re.fullmatch(r"\d{1,5}", answer) and low <= int(answer) <= high:
                return int(answer)
            self.say(f"Un nombre entier de {low} à {high}.")

    def _ask_yes(self, question: str, current: bool) -> bool:
        while True:
            answer = self.ask(f"{question} (o/n, Entrée = {'oui' if current else 'non'}) : ").strip()
            if not answer:
                return current
            value = yes_no(answer)
            if value is not None:
                return value
            self.say("Réponds par oui ou non.")

    def _visitor_settings(self, cfg) -> bool:
        a = cfg.access
        before = (a.max_listeners, a.listeners_need_operator, a.operator_grace_s, a.listeners_outside_bands,
                  a.listener_spectrum_fps)
        a.max_listeners = self._ask_int("Visiteurs connectés en même temps au plus (0 = écoute fermée)", a.max_listeners, 0, 20)
        a.listeners_need_operator = self._ask_yes("Visiteurs admis SEULEMENT si un opérateur est connecté",
                                                  a.listeners_need_operator)
        if a.listeners_need_operator:
            a.operator_grace_s = self._ask_int("Attente après la perte de l'opérateur avant de déconnecter les visiteurs, "
                                               "en secondes", a.operator_grace_s, 0, 600)
        a.listeners_outside_bands = self._ask_yes("Laisser les visiteurs écouter HORS des bandes de la station "
                                                  "(sous ta responsabilité)", a.listeners_outside_bands)
        a.listener_spectrum_fps = self._ask_int("Spectre HF des visiteurs : images par seconde au plus",
                                                a.listener_spectrum_fps, 1, 20)
        return before != (a.max_listeners, a.listeners_need_operator, a.operator_grace_s, a.listeners_outside_bands,
                          a.listener_spectrum_fps)

    def _ask_pseudo(self, cfg, current: str = "") -> str | None:
        """Pseudo montré aux autres connectés ; None = abandon."""
        from .config import PSEUDO_MAX
        while True:
            answer = self.ask(f"Pseudo montré aux autres connectés ({PSEUDO_MAX} caractères au plus"
                              + (f", Entrée = {current}" if current else ", Entrée = aucun") + ", - = abandon) : ").strip()
            if answer == "-":
                return None
            if not answer:
                return current
            if len(answer) > PSEUDO_MAX or any(ord(ch) < 32 for ch in answer):
                self.say(f"{PSEUDO_MAX} caractères au plus, sans caractère spécial.")
            elif any(answer.casefold() == c.id.casefold() for c in cfg.clients):
                self.say("C'est l'identifiant d'un compte : il serait montré aux autres connectés. Choisis un autre pseudo.")
            else:
                return answer

    def _ask_new_password(self, login: str) -> str | None:
        from .passwords import generate_password, password_problem
        while True:
            answer = self.ask("Mot de passe (Entrée = en générer un fort, - = abandon) : ").strip()
            if answer == "-":
                return None
            if not answer:
                answer = generate_password()
                self.say(f"Mot de passe : {answer}\nTransmets-le au visiteur maintenant : la station ne le garde pas en clair.")
                return answer
            problem = password_problem(answer, login)
            if problem is None:
                return answer
            self.say(f"Refusé : {problem}.")

    def _ask_expiry(self, current: str) -> str | None:
        from datetime import date
        while True:
            answer = self.ask("Date de fin AAAA-MM-JJ (Entrée = " + (current or "jamais") + ", 0 = jamais, - = abandon) : ").strip()
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
            self.say("Une date comme 2026-12-31.")

    def _pick_account(self, cfg, role: str, verb: str):
        accounts = [c for c in cfg.clients if c.role == role]
        if not accounts:
            self.say("Aucun compte " + ("visiteur." if role == "listener" else "opérateur."))
            return None
        for i, c in enumerate(accounts, 1):
            self.say(f"  {i}) {self._account_label(c)}")
        answer = self.ask(f"Numéro du compte à {verb} (Entrée = annuler) : ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(accounts):
            return accounts[int(answer) - 1]
        return None

    def _visitor_create(self, cfg) -> bool:
        from .config import ClientAuth
        from .passwords import hash_password
        login = self.ask("Identifiant de connexion du visiteur (lettres, chiffres, _ et -, Entrée = annuler) : ").strip()
        if not login:
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", login) or any(c.id == login for c in cfg.clients):
            self.say("Identifiant invalide ou déjà utilisé.")
            return False
        pseudo = self._ask_pseudo(cfg)
        expires = None if pseudo is None else self._ask_expiry("")
        password = None if expires is None else self._ask_new_password(login)
        if password is None:
            return False
        if pseudo and pseudo.casefold() == login.casefold():
            self.say("Le pseudo ne peut pas être l'identifiant : il serait montré aux autres connectés.")
            return False
        cfg.clients.append(ClientAuth(id=login, password_hash=hash_password(password), role="listener", pseudo=pseudo,
                                      expires=expires))
        if not cfg.access.max_listeners:
            self.say("Attention : l'écoute des visiteurs est FERMÉE (nombre maximal 0) : ouvre-la par le choix 1.")
        return True

    def _visitor_edit(self, cfg) -> bool:
        from .passwords import hash_password
        account = self._pick_account(cfg, "listener", "modifier")
        if account is None:
            return False
        pseudo = self._ask_pseudo(cfg, account.pseudo)
        if pseudo is None:
            return False
        enabled = self._ask_yes("Compte activé", account.enabled)
        expires = self._ask_expiry(account.expires)
        if expires is None:
            return False
        changed = (pseudo, enabled, expires) != (account.pseudo, account.enabled, account.expires)
        account.pseudo, account.enabled, account.expires = pseudo, enabled, expires
        if self.yes("Lui donner un nouveau mot de passe", False):
            password = self._ask_new_password(account.id)
            if password is None:
                return False
            account.password_hash, account.token, changed = hash_password(password), "", True
        return changed

    def _visitor_delete(self, cfg) -> bool:
        account = self._pick_account(cfg, "listener", "supprimer")
        if account is None or not self.yes(f"Supprimer le compte {account.id}", False):
            return False
        cfg.clients.remove(account)
        return True

    def _operator_pseudo(self, cfg) -> bool:
        account = self._pick_account(cfg, "operator", "nommer")
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
            self.say("Aucune modification : station.toml n'a pas été changé.")
            return
        work = Path(tempfile.mkdtemp(prefix="trx-config-"))
        try:
            draft = work / "station.toml"
            draft.write_bytes(edited)
            os.chmod(draft, 0o600)                         # contient les empreintes des mots de passe
            try:
                cfgmod.load(draft)
            except cfgmod.ConfigError as exc:
                self.say("Changement REFUSÉ :\n  - " + "\n  - ".join(exc.problems))
                return
            self.say("(station.toml est réécrit dans sa forme standard.)")
            self._save_config(original, edited, draft, live=live)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _visitor_reopen(self, cfg) -> None:
        """Demande à la station de rouvrir l'écoute (elle refuse tant qu'elle n'est pas nettement revenue à la normale)."""
        from .gateway.access_watch import REOPEN_REQUEST, kick_request
        if not isinstance(self._presence().get("suspended"), dict):
            self.say("L'écoute des visiteurs n'est pas suspendue.")
            return
        work = Path(tempfile.mkdtemp(prefix="trx-reopen-"))
        try:
            request = work / REOPEN_REQUEST
            request.write_bytes(kick_request("reopen"))
            code = self.runner.run(["install", "-m", "0644", str(request),
                                    str(Path(cfg.supervisor.state_dir) / REOPEN_REQUEST)], admin=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.say("Demande envoyée : la station rouvre l'écoute si elle est revenue nettement sous les seuils "
                 "(sinon elle refuse : voir le journal, menu 1.4)." if code == 0 else f"Demande impossible (code {code}).")

    def _visitor_kick(self, cfg) -> None:
        from .gateway.access_watch import KICK_REQUEST, kick_request
        connected = [c for c in self._connected() if c.get("role") == "listener"]
        if not connected:
            self.say("Aucun visiteur connecté (ou station arrêtée).")
            return
        for i, c in enumerate(connected, 1):
            self.say(f"  {i}) {c.get('pseudo', '?')} ({c.get('id', '?')}, {c.get('source', '?')})")
        answer = self.ask("Numéro du visiteur à déconnecter (Entrée = annuler) : ").strip()
        if not (answer.isdigit() and 1 <= int(answer) <= len(connected)):
            return
        target = str(connected[int(answer) - 1].get("id", ""))
        if not self.yes(f"Déconnecter {target} maintenant", False):
            return
        work = Path(tempfile.mkdtemp(prefix="trx-kick-"))
        try:
            request = work / KICK_REQUEST
            request.write_bytes(kick_request(target))
            code = self.runner.run(["install", "-m", "0644", str(request),
                                    str(Path(cfg.supervisor.state_dir) / KICK_REQUEST)], admin=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.say("Demande envoyée : le visiteur est déconnecté dans la seconde (il peut se reconnecter ; pour l'en "
                 "empêcher, désactive son compte, choix 3)." if code == 0 else f"Demande impossible (code {code}).")

    # ------------------------------------------------------------------ présence de groupe (menu 5.3)

    FRIEND_LEVELS = {"1": ("f", "fréquence et mode"), "2": ("o", "« On Air » seulement"), "3": ("x", "un texte")}
    FRIEND_ROLES = {"a": "administrateur", "c": "co-administrateur", "m": "membre"}
    FRIEND_STATUS = {"member": "membre", "pending": "adhésion en attente", "removed": "exclu ou groupe supprimé"}
    FRIEND_CODES = {"Q": "En QSO", "R": "En RX", "S": "Au shack", "A": "Absent", "O": "Hors ligne"}

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
                self.say("\nPrésence de groupe désactivée, ou module « presence » jamais démarré.\n"
                         "Pour l'activer (menu 3.2) : dans [presence], enabled = true ; dans [modules], ajouter\n"
                         "\"presence\" à run (ex. run = [\"cluster\", \"presence\"]) ; puis redémarrer la station (menu 1.1).")
                return
            self.say("\n" + self.friends_summary(status))
            choice = self.ask("\n  1) Choisir le pseudo\n"
                              "  2) Groupes et membres\n"
                              "  3) Créer un groupe\n"
                              "  4) Inviter quelqu'un (lien et QR code)\n"
                              "  5) Rejoindre un groupe (coller une invitation)\n"
                              "  6) Ce que je partage dans un groupe\n"
                              "  7) Quitter ou supprimer un groupe\n"
                              "Choix (Entrée = retour) : ").strip()
            if not choice:
                return
            {"1": self._friends_pseudo, "2": self._friends_view, "3": self._friends_create,
             "4": self._friends_invite, "5": self._friends_join, "6": self._friends_share,
             "7": self._friends_leave}.get(choice, lambda: self.say("Choix inconnu."))()

    def friends_summary(self, status: dict) -> str:
        lines = [f"Présence de groupe : pseudo {status.get('pseudo') or '(aucun : choix 1)'}, "
                 f"{'enregistrée auprès du relais' if status.get('registered') else 'PAS ENCORE enregistrée'}"]
        problem = status.get("problem")
        if problem:
            lines.append(f"  Problème : {problem}")
        for grp in status.get("groups") or []:
            lines.append(f"  - {grp.get('name')} : {self.FRIEND_ROLES.get(grp.get('role'), '?')}, "
                         f"{self.FRIEND_STATUS.get(grp.get('status'), grp.get('status'))}, {grp.get('members', 0)} ami(s)")
        if not status.get("groups"):
            lines.append("  Aucun groupe : en créer un (choix 3) ou en rejoindre un (choix 5).")
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
                    self.say("Demande impossible à déposer.")
                    return None
            finally:
                shutil.rmtree(work, ignore_errors=True)
        except OSError as exc:
            self.say(f"Demande impossible à déposer : {exc}")
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
        self.say("Pas de réponse du module « presence » (station arrêtée ? voir le journal, menu 1.4).")
        return None

    def _friends_do(self, action: str, args: dict | None = None) -> dict | None:
        self.say("Demande envoyée au module…")
        reply = self.friends_request(action, args)
        if reply is None:
            return None
        if not reply.get("ok"):
            self.say(f"Refusé : {reply.get('message') or reply.get('error')}")
            return None
        return reply.get("result") or {}

    def _friends_pick(self, *, admin: bool = False) -> str | None:
        view = self._friends_do("view")
        groups = [g for g in (view or {}).get("groups", []) if not admin or g.get("role") in ("a", "c")]
        if not groups:
            self.say("Aucun groupe" + (" que tu administres." if admin else "."))
            return None
        for i, g in enumerate(groups, 1):
            self.say(f"  {i}) {g['name']} ({self.FRIEND_ROLES.get(g['role'], '?')})")
        answer = self.ask("Numéro du groupe (Entrée = annuler) : ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(groups):
            return groups[int(answer) - 1]["g"]
        return None

    def _friends_pseudo(self) -> None:
        pseudo = self.ask("Pseudo (indicatif ou surnom, 16 caractères : lettres sans accent, chiffres, espace, . / _ -) : ").strip()
        if pseudo and self._friends_do("pseudo", {"pseudo": pseudo}) is not None:
            self.say(f"Pseudo enregistré : {pseudo}")

    def _friends_view(self) -> None:
        view = self._friends_do("view")
        for g in (view or {}).get("groups", []):
            self.say(f"\n{g['name']} ({self.FRIEND_ROLES.get(g['role'], '?')}, "
                     f"{self.FRIEND_STATUS.get(g['status'], g['status'])})")
            for m in g.get("members", []):
                detail = ""
                if m.get("lv") == "f" and "f" in m:
                    detail = f" {m['f'] / 1e6:.3f} MHz {m.get('m', '')}"
                elif m.get("lv") == "x" and m.get("x"):
                    detail = f" « {m['x']} »"
                self.say(f"  [{m['code']}] {m['pseudo']} : {self.FRIEND_CODES.get(m['code'], '?')}{detail}")
            if not g.get("members"):
                self.say("  (personne d'autre pour l'instant)")

    def _friends_create(self) -> None:
        name = self.ask("Nom du groupe (24 caractères) : ").strip()
        if name and self._friends_do("create", {"name": name}) is not None:
            self.say(f"Groupe « {name} » créé : tu en es l'administrateur. Invite tes amis (choix 4).")

    def _friends_invite(self) -> None:
        from .setup_wizard import qr_lines
        g = self._friends_pick(admin=True)
        if g is None:
            return
        result = self._friends_do("invite", {"g": g, "days": 7})
        if not result:
            return
        url = result["url"]
        self.say("\nInvitation valable 7 jours, pour UNE seule station. À transmettre seulement à la personne invitée\n"
                 "(elle contient la clé du groupe) :\n\n" + url + "\n")
        lines = qr_lines(url)
        if lines:
            self.say("\n".join(lines))
        self.say("Son adhésion sera validée automatiquement par ta station à sa prochaine requête.")

    def _friends_join(self) -> None:
        url = self.ask("Coller l'invitation (lien complet) : ").strip()
        if not url:
            return
        name = self.ask("Nom de ce groupe chez toi (Entrée = automatique) : ").strip()
        if self._friends_do("join", {"url": url, "name": name}) is not None:
            self.say("Demande d'adhésion envoyée : elle est validée dès que la station de l'administrateur la voit.")

    def _friends_share(self) -> None:
        g = self._friends_pick()
        if g is None:
            return
        for key, (_, label) in self.FRIEND_LEVELS.items():
            self.say(f"  {key}) {label}")
        level = self.FRIEND_LEVELS.get(self.ask("Que partager avec ce groupe : ").strip())
        if level is None:
            return
        args = {"g": g, "level": level[0]}
        if level[0] == "x":
            args["text"] = self.ask("Texte (16 caractères : lettres sans accent, chiffres, espace, . / -) : ").strip()
        args["invisible"] = self.yes("Être invisible dans ce groupe pour l'instant", False)
        if self._friends_do("share", args) is not None:
            self.say("Partage enregistré : pris à la prochaine requête (moins de 2 minutes).")

    def _friends_leave(self) -> None:
        g = self._friends_pick()
        if g is None:
            return
        view = self._friends_do("view", {"g": g}) or {}
        role = (view.get("groups") or [{}])[0].get("role")
        if role == "a" and self.yes("Tu es administrateur : SUPPRIMER le groupe pour tout le monde", False):
            if typed(self.ask("Taper SUPPRIMER pour confirmer : "), "SUPPRIMER") and self._friends_do("delete", {"g": g}) is not None:
                self.say("Groupe supprimé.")
            return
        if self.yes("Quitter ce groupe", False) and self._friends_do("leave", {"g": g}) is not None:
            self.say("Groupe quitté.")

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
                self.say("\nStation arrêtée : pas de liaison en cours à montrer.")
            else:
                panel = _reseau_panel(Snapshot(status=st, gateway_fresh=True, stale_s=0.0, safe_mode=None), detail=True)
                self.say("\n" + render_plain([panel]).rstrip())
            choice = self.ask("\n  1) Synthèse des 24 dernières heures\n"
                              "  2) Synthèse des 30 derniers jours\n"
                              "  3) Export anonyme sur le Bureau (pour l'équipe de développement)\n"
                              "  4) Tout effacer (historique réseau ; les seuils choisis sont gardés)\n"
                              "Choix (Entrée = retour) : ").strip()
            if not choice:
                return
            store = store_of(state_dir)
            if choice in ("1", "2"):
                if not store.folder.is_dir():
                    self.say("Aucune mesure encore : la sonde enregistre dès qu'un téléphone ou une page est connecté.")
                    continue
                self.say("\n" + report_text(store.stats(1 if choice == "1" else 30, "", {})))
            elif choice == "3":
                self._network_export(store, state_dir)
            elif choice == "4":
                self._network_clear(state_dir)
            else:
                self.say("Choix inconnu.")

    def _network_export(self, store, state_dir: Path) -> None:
        from dataclasses import asdict

        from . import __version__
        from . import config as cfgmod
        from .netprobe.export import build_export, export_name
        from .report import desktop_dir
        from .station_id import read_station_id
        if not store.folder.is_dir():
            self.say("Aucune mesure à exporter.")
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
            self.say(f"Export impossible : {exc}")
            return
        self.say(f"Export anonyme créé : {target}\nSans compte, adresse IP ni position : joins-le à ton message pour "
                 "l'équipe de développement.")

    def _network_clear(self, state_dir: Path) -> None:
        from .gateway.access_watch import kick_request
        from .netprobe.probe import CLEAR_REQUEST
        answer = self.ask("Effacer tout l'historique réseau (coupures, statistiques, appareils vus) ? "
                          "Tape EFFACER pour confirmer : ").strip()
        if answer != "EFFACER":
            self.say("Rien n'a été effacé.")
            return
        if self._gateway_status() is not None:          # station en marche : c'est elle qui efface (mémoire comprise)
            work = Path(tempfile.mkdtemp(prefix="trx-net-"))
            try:
                request = work / CLEAR_REQUEST
                request.write_bytes(kick_request("console"))
                code = self.runner.run(["install", "-m", "0644", str(request), str(state_dir / CLEAR_REQUEST)], admin=True)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            self.say("Demande envoyée : l'historique est effacé dans la seconde." if code == 0
                     else f"Demande impossible (code {code}).")
            return
        folder = state_dir / "netprobe"
        if not folder.is_dir():
            self.say("Aucun historique à effacer.")
            return
        code = self.runner.run(["find", str(folder), "-maxdepth", "1", "-type", "f", "!", "-name", "seuils.json",
                                "-delete"], admin=True)
        self.say("Historique réseau effacé (seuils choisis gardés)." if code == 0 else f"Effacement impossible (code {code}).")

    # ------------------------------------------------------------------ Breizh Audio Box (menu 5.2)

    BREIZH_STATES = {"connecting": "recherche de Breizh…", "ready": "prêt : prochaines émissions par Breizh",
                     "active": "ÉMISSION par Breizh", "fallback": "REPLI : Breizh ne répond plus, émissions en direct",
                     "refused": "liaison refusée par Breizh (voir le journal)"}

    def breizh(self) -> None:
        """Breizh Audio Box (docs/breizh-cahier-des-charges.md) : clé d'appairage (breizh.key, à côté de station.toml,
        créée ici et montrée UNE fois), adresse et port de Breizh et activation ([breizh] de station.toml, chemin validé
        du menu 3.2), essai de la liaison SANS son, état publié par la passerelle, journal. Rien ici ne touche au PTT."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 3.1).")
            return
        while True:
            try:
                original = self.config.read_bytes()
                cfg, _ = cfgmod.load_unchecked(self.config)
            except (OSError, cfgmod.ConfigError) as exc:
                self.say(f"Lecture de {self.config} impossible ({exc}).")
                return
            self.say(self._breizh_summary(cfg))
            choice = self.ask("\n  1) Créer ou remplacer la clé d'appairage (à recopier dans Breizh)\n"
                              "  2) Adresse et port de Breizh, activer ou désactiver\n"
                              "  3) Essai de la liaison (sans son)\n"
                              "  4) Journal de la liaison\n"
                              "Choix (Entrée = retour) : ").strip()
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
                self.say("Choix inconnu.")

    def _breizh_key_state(self, cfg) -> str:
        """« présente », ou le problème (absente, illisible, droits trop larges). Jamais la clé elle-même."""
        from .breizh.keyfile import KeyFileError, read_key
        from .config import breizh_key_path
        path = breizh_key_path(cfg, self.config)
        if not path.exists():
            return "ABSENTE (choix 1)"
        try:
            read_key(path)
        except KeyFileError as exc:
            if " illisible (" in str(exc):                     # droits root:trx : le compte de bureau ne la lit pas
                return f"présente ({path} ; lue par la station, pas par ce compte)"
            return f"PROBLÈME : {exc}"
        return f"présente ({path})"

    def _breizh_summary(self, cfg) -> str:
        b = cfg.breizh
        lines = ["\nBreizh Audio Box : la voix de l'opérateur passe par Breizh (autre PC du réseau local) avant le poste ;",
                 "la station garde le PTT, le TOT et son limiteur, et repasse en direct si Breizh ne répond plus.",
                 f"  En service            : {'oui' if b.enabled else 'non'}",
                 f"  PC de Breizh          : {b.host or '(adresse à régler, choix 2)'} port UDP {b.port}",
                 f"  Clé d'appairage       : {self._breizh_key_state(cfg)}"]
        status = self._gateway_status()
        live = status.breizh if status is not None and isinstance(getattr(status, "breizh", None), dict) else {}
        if live:
            details = [f"route {live.get('route')}" + (" (« Direct » choisi)" if live.get("bypass") else "")]
            if live.get("peer"):
                details.append(str(live["peer"])[:64])
            if live.get("rtt_ms") is not None:
                details.append(f"aller-retour {live['rtt_ms']} ms")
            lines.append(f"  Liaison maintenant    : {self.BREIZH_STATES.get(live.get('state'), live.get('state'))} · "
                         + " · ".join(details))
        elif b.enabled:
            lines.append("  Liaison maintenant    : passerelle arrêtée, ou clé illisible au démarrage (voir le journal, menu 1.4)")
        for entry in self._breizh_entries(cfg)[-3:]:
            lines.append(f"  Journal               : {entry}")
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
        self.say("\n".join(["\nJournal de la liaison avec Breizh (le plus récent en bas) :"]
                           + ["  " + e for e in entries]) if entries else "Journal vide : la passerelle n'a encore rien noté.")

    def _breizh_new_key(self, cfg) -> None:
        """Nouvelle clé de 32 octets, écrite avec les droits de station.toml (jamais lisible par tous) et montrée UNE fois."""
        from .breizh.protocol import key_to_text, new_key
        from .config import breizh_key_path
        path = breizh_key_path(cfg, self.config)
        if path.exists() and not self.yes("Une clé existe déjà : la remplacer oblige à recopier la nouvelle dans Breizh. "
                                          "Remplacer", False):
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
                    self.say(f"Écriture impossible ({exc}) : relance TRX Console en administrateur.")
                    code = 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if code != 0:
            self.say(f"Clé NON enregistrée (code {code}).")
            return
        try:
            if self.addresses is None:
                from .setup_wizard import local_addresses
                self.addresses = local_addresses
            found = self.addresses()
        except Exception:                                   # adresse introuvable : texte générique
            found = []
        self.say("\nClé d'appairage enregistrée. À recopier MAINTENANT dans l'onglet « OpenRemoteTRX » des réglages de Breizh"
                 " (elle n'est plus jamais affichée ; perdue : en créer une nouvelle) :\n\n"
                 f"    {key_to_text(key)}\n\n"
                 f"Dans Breizh : adresse de cette station = {', '.join(found) or 'son adresse IP sur le réseau local'}, "
                 f"port UDP = {cfg.breizh.port}, puis activer le mode OpenRemoteTRX (cela coupe le CAT de Breizh).\n"
                 f"Sur le PC de Breizh, le pare-feu doit laisser entrer l'UDP {cfg.breizh.port} depuis cette station.")
        if cfg.breizh.enabled and self.station_running() and self.yes("Redémarrer la station pour qu'elle prenne la nouvelle clé"):
            self.start()

    def _breizh_settings(self, cfg) -> bool:
        """Adresse IP PRIVÉE de Breizh, port, activation. Vrai si quelque chose a changé."""
        from .config import breizh_host_allowed
        b = cfg.breizh
        before = (b.enabled, b.host, b.port)
        while True:
            answer = self.ask(f"Adresse IP du PC de Breizh (127.0.0.1 = ce PC ; Entrée = {b.host or 'aucune'}) : ").strip()
            if not answer or breizh_host_allowed(answer):
                b.host = answer or b.host
                break
            self.say("Adresse IP PRIVÉE attendue (192.168.x.y, 10.x.y.z, 172.16 à 31.x.y, 127.0.0.1…) : ni nom ni adresse "
                     "publique, le son du micro circule en clair.")
        b.port = self._ask_int("Port UDP de Breizh", b.port, 1024, 65535)
        b.enabled = self._ask_yes("Faire passer la voix par Breizh", b.enabled)
        if b.enabled and not b.host:
            self.say("Sans adresse, Breizh ne peut pas être activé.")
            b.enabled = False
        if b.enabled and self._breizh_key_state(cfg).startswith("ABSENTE"):
            self.say("Attention : pas encore de clé d'appairage (choix 1) : la station démarrera SANS Breizh.")
        return (b.enabled, b.host, b.port) != before

    def _breizh_probe(self, cfg) -> None:
        """Essai par la fausse station (HELLO puis 5 PING, aucun son), lancé en administrateur pour lire la clé."""
        from .config import breizh_key_path
        b = cfg.breizh
        if not b.host:
            self.say("Règle d'abord l'adresse de Breizh (choix 2).")
            return
        path = breizh_key_path(cfg, self.config)
        if not path.exists():
            self.say("Crée d'abord la clé d'appairage (choix 1).")
            return
        status = self._gateway_status()
        live = status.breizh if status is not None and isinstance(getattr(status, "breizh", None), dict) else {}
        if live.get("state") in ("ready", "active", "fallback") and live.get("peer"):
            self.say(f"La liaison de la station avec Breizh est EN SERVICE ({live.get('peer')}, aller-retour "
                     f"{live.get('rtt_ms')} ms) : essai inutile. Breizh ne sert qu'une station à la fois et répondrait "
                     "« occupé » à l'essai. L'essai sert quand la station est arrêtée ou que Breizh n'y est pas activé.")
            return
        self.runner.run(self.module("trxstation.devtools.breizh_probe", "--host", b.host, "--port", str(b.port),
                                    "--key-file", str(path), "--sans-son"), admin=os.name == "posix")

    def temperature(self) -> None:
        """Seuils de température du poste ([safety] rig_temp_warn_c, rig_temp_cut_c), écrits dans station.toml par
        le même chemin que le menu 3.2 : copie, validation, différences, confirmation, sauvegarde."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 3.1).")
            return
        try:
            original = self.config.read_bytes()
            cfg, _ = cfgmod.load_unchecked(self.config)
        except (OSError, cfgmod.ConfigError) as exc:
            self.say(f"Lecture de {self.config} impossible ({exc}).")
            return
        s = cfg.safety
        self.say("Température du poste (lue par Hamlib, TEMP_METER) :\n"
                 f"  1er seuil (avertissement : page et notification)            : {s.rig_temp_warn_c} °C\n"
                 f"  2e seuil (émission à distance coupée, reprise sous le 1er)  : {s.rig_temp_cut_c} °C\n"
                 "Sans effet si le poste ne donne pas sa température (cas de l'IC-7300MK2 sous Hamlib).")
        warn = self._ask_degrees("Nouveau 1er seuil", s.rig_temp_warn_c)
        cut = self._ask_degrees("Nouveau 2e seuil", s.rig_temp_cut_c)
        if (warn, cut) == (s.rig_temp_warn_c, s.rig_temp_cut_c):
            self.say("Aucune modification : station.toml n'a pas été changé.")
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
                self.say("Seuils REFUSÉS :\n  - " + "\n  - ".join(exc.problems))
                return
            self._save_config(original, edited, draft)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _ask_degrees(self, question: str, current: int) -> int:
        while True:
            answer = self.ask(f"{question} en °C (Entrée = {current}) : ").strip()
            if not answer:
                return current
            if re.fullmatch(r"\d{1,3}", answer):
                return int(answer)
            self.say("Un nombre entier de degrés, par exemple 45.")

    def expert(self) -> None:
        self.say("\nMenu expert :\n"
                 "  1) Tests automatiques du logiciel (pytest, 7 à 10 minutes sur un PC récent, 30 minutes ou plus sur un\n"
                 "     petit PC ; poste SIMULÉ : aucune émission)\n"
                 "  q) Retour")
        if self.ask("Choix : ").strip() == "1":
            self.run_tests()

    def run_tests(self) -> None:
        """Toute la suite de tests de la version installée, sur cette machine. Résultat enregistré sur le Bureau."""
        tests = self.app_dir / "current" / "app" / "tests"
        if not tests.is_dir():
            self.say(f"Tests absents de la version installée ({tests}) : ils sont fournis à partir de la version 0.42.0.")
            return
        if self.runner.output([self.python, "-c", "import pytest; print('ok')"]) != "ok":
            self.say("L'outil de test (pytest) n'est pas installé. Son installation demande Internet et le mot de passe\n"
                     "(il est ajouté à la version installée ; une mise à jour le retire, il suffira de le réinstaller).")
            if not self.yes("Installer pytest maintenant", False):
                return
            self.runner.run([self.python, "-m", "pip", "install", "--quiet", "pytest"], admin=True)
            if self.runner.output([self.python, "-c", "import pytest; print('ok')"]) != "ok":
                self.say("Installation de pytest impossible (Internet ?) : tests non lancés.")
                return
        self.say("Les tests utilisent un poste SIMULÉ (aucune commande au vrai poste, aucune émission). La station est\n"
                 "arrêtée pendant les tests pour libérer ses ports réseau, puis relancée si tu le souhaites.")
        if not self.yes("Lancer les tests", True):
            return
        stopped = self.stop_for_exclusive_use("les tests")
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
        self.say("\nTous les tests passent." if code == 0 else
                 f"\nDes tests échouent (code {code}). Transmets ce fichier pour analyse : {log}")
        if code == 0:
            self.say(f"Résultat enregistré : {log}")
        if stopped and self.yes("Redémarrer la station"):
            self.start()

    def offered(self, state: UpdateState | None):
        """Version annoncée seulement si elle est plus récente que celle qui tourne (latest.json peut dater)."""
        release = state.release if state is not None else None
        if release is None or (parse_version(release.version) or ()) <= (parse_version(self.installed) or ()):
            return None
        return release

    @staticmethod
    def _apply_result(code: int, success: str) -> str:
        if code == upd.EXIT_OK:
            return success
        if code == upd.EXIT_TX:
            return "Refusé : le poste émet, ou son état n'a pas pu être vérifié. Rien n'a été modifié."
        if code == upd.EXIT_REFUSED:
            return "Refusé : paquet non vérifié ou indisponible. Rien n'a été installé."
        return f"Échec (code {code}) : la version active est inchangée. Détails : {INSTALL_LOG}"

    # ------------------------------------------------------------------ boucle

    def station_id(self) -> str | None:
        return read_station_id(config_state_dir(self.config))

    def header(self) -> str:
        t = self.t
        if not self.config.exists():
            state = t("head.not_configured", menu=menu_number("assistant"))
        else:
            state = t("head.running") if self.station_running() else t("head.stopped")
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

    def show_main(self) -> None:
        self.say(self.header())
        for number, title, desc in self.themes():
            self.say(f"  {number}) {self.menu_label(number, title)}" + (f"  ({desc})" if desc else ""))
        self.say(f"  0) {self.t('menu.language')}")
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
