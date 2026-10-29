# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console : point d'entrée unique de la station pour qui ne connaît pas Linux (commande `trx-console`).

Un menu numéroté regroupe le diagnostic, l'assistant de configuration, le tableau de bord, l'essai du poste,
le démarrage et l'arrêt des services, le journal, le rapport de dépannage, la sortie du mode sûr,
la mise à jour (paquet signé, après confirmation), le retour à la version précédente, le Cluster DX,
l'installation d'un paquet zip déposé sur la machine (Bureau, Téléchargements) et la modification de station.toml
(copie éditée avec nano, VALIDÉE avant d'être enregistrée, ancienne version gardée).
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
UPDATE_MENU = "10"
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
                 desktop: Callable[[], Path] | None = None, color: bool | None = None) -> None:
        self.config, self.runner, self.ask, self.say, self.python = config, runner or Runner(), ask, say, python
        self.color = color if color is not None else (say is print and sys.stdout.isatty())
        self.update_state = update_state or (lambda: read_state(state_path(config_state_dir(self.config))))
        self.previous, self.installed = previous, installed
        self.home = home or Path.home()
        self.editor = editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or shutil.which("nano") or ""
        self.app_dir = app_dir
        self.desktop = desktop
        self.items: list[tuple[str, str, Callable[[], None]]] = [
            ("1", "Diagnostic complet", self.diagnostic),
            ("2", "Assistant de configuration", self.assistant),
            ("3", "Tableau de bord (fréquence, émission, services)", self.monitor),
            ("4", "Essai du poste (CAT, audio, PTT)", self.hwtest),
            ("5", "Démarrer ou redémarrer la station", self.start),
            ("6", "Arrêter la station", self.stop),
            ("7", "Journal de la station", self.journal),
            ("8", "Rapport de dépannage (zip sur le Bureau)", self.report),
            ("9", "Sortir du mode sûr", self.clear_safe_mode),
            ("10", "Mise à jour de TRX distant", self.update),
            ("11", "Revenir à la version précédente", self.rollback),
            ("12", "Cluster DX (spots suivis, sources, test)", self.cluster),
            ("13", "Installer une version depuis un fichier zip (Bureau, Téléchargements)", self.install_zip),
            ("14", "Modifier la configuration (station.toml)", self.edit_config),
            ("15", "Menu expert (tests automatiques du logiciel)", self.expert),
            ("16", "Seuils de température du poste (avertissement, coupure)", self.temperature),
            ("17", "Indicateur dans la barre du haut (GNOME : état de la station en permanence)", self.indicator),
            ("18", "Profils de poste (plusieurs TRX : enregistrer, charger, supprimer)", self.profiles),
            ("19", "Appairer un téléphone (application Android : adresse, empreinte, QR code)", self.pairing),
            ("20", "Visiteurs en réception seule (comptes, nombre maximal, connectés)", self.visitors),
        ]

    # ------------------------------------------------------------------ outils

    def module(self, name: str, *args: str) -> list[str]:
        return [self.python, "-m", name, *args]

    def pause(self) -> None:
        try:
            self.ask("\nEntrée pour revenir au menu... ")
        except EOFError:
            pass

    def yes(self, question: str, default: bool = True) -> bool:
        answer = self.ask(f"{question} ({'O/n' if default else 'o/N'}) : ").strip()
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
            self.say(f"Indicateur absent ({GNOME_EXTENSION_DIR}) : installe la version 0.49.0 ou plus récente (menu 13).")
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
            self.say("Configure d'abord la station (menu 2).")
            return
        code = self.runner.run(self.module("trxstation.cluster.setup", "--config", str(self.config)), admin=True)
        if code == 0 and self.station_running() and self.yes("Redémarrer la station pour appliquer"):
            self.start()

    def monitor(self) -> None:
        self.runner.run(self.module("trxstation.monitor.main", "--config", str(self.config)))

    def hwtest(self) -> None:
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 2).")
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
            self.say("Configure d'abord la station (menu 2).")
            return
        code = self.runner.run(["systemctl", "restart", TARGET], admin=True)
        self.say("Station démarrée. Diagnostic conseillé dans quelques secondes (menu 1)." if code == 0
                 else "Le démarrage a échoué : voir le journal (menu 7).")

    def stop(self) -> None:
        code = self.runner.run(["systemctl", "stop", TARGET], admin=True)
        self.say("Station arrêtée (le poste reste en réception)." if code == 0 else "Arrêt impossible : voir le journal (menu 7).")

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
                 "Vérifie d'abord la cause (menu 1 et menu 7).")
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
                 f"la version {self.installed}, station.toml et les certificats sont conservés (retour possible : menu 11).")
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
                                          "rouvre-la. La version plus récente restera proposée par le menu 10."))

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
                     "Pour revenir simplement à la version précédente, le menu 11 suffit.")
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
            self.say("Configure d'abord la station (menu 2).")
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

    # ------------------------------------------------------------------ profils de poste (menu 18)

    def pairing(self) -> None:
        """Adresse, comptes et empreinte du certificat à vérifier dans l'application Android. Lecture seule ;
        aucun mot de passe affiché (la station ne les connaît pas en clair)."""
        from . import config as cfgmod
        from .setup_wizard import show_pairing
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 2).")
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
            self.say("Configure d'abord la station (menu 2).")
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
            self.say(f"Configuration actuelle invalide ou illisible : corrige-la d'abord (menu 14). ({exc})")
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
            self.say("Les changements s'appliqueront au prochain démarrage de la station (menu 5).")
        return True

    # ------------------------------------------------------------------ visiteurs (menu 20)

    def visitors(self) -> None:
        """Visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md) : réglages [access], comptes
        role = "listener", pseudos, connectés et déconnexion. station.toml passe par le chemin validé du menu 14
        (réécrit dans sa forme standard) ; la passerelle le relit sans redémarrer."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 2).")
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
                              "Choix (Entrée = retour) : ").strip()
            if not choice:
                return
            actions = {"1": self._visitor_settings, "2": self._visitor_create, "3": self._visitor_edit,
                       "4": self._visitor_delete, "5": self._operator_pseudo}
            if choice == "6":
                self._visitor_kick(cfg)
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
        from . import config as cfgmod
        from .status import read_status
        try:
            cfg, _ = cfgmod.load_unchecked(self.config)
            path = Path(cfg.supervisor.status_path)
            if not path.exists() or time.time() - path.stat().st_mtime > 10:
                return []
            status = read_status(path)
        except (OSError, cfgmod.ConfigError):
            return []
        items = status.presence.get("connections", []) if status is not None else []
        return [c for c in items if isinstance(c, dict)]

    def _ask_int(self, question: str, current: int, low: int, high: int) -> int:
        while True:
            answer = self.ask(f"{question} ({low} à {high}, Entrée = {current}) : ").strip()
            if not answer:
                return current
            if re.fullmatch(r"\d{1,4}", answer) and low <= int(answer) <= high:
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

    def _save_accounts(self, original: bytes, cfg) -> None:
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
            self._save_config(original, edited, draft, live=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)

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

    def temperature(self) -> None:
        """Seuils de température du poste ([safety] rig_temp_warn_c, rig_temp_cut_c), écrits dans station.toml par
        le même chemin que le menu 14 : copie, validation, différences, confirmation, sauvegarde."""
        from . import config as cfgmod
        if not self.config.exists():
            self.say("Configure d'abord la station (menu 2).")
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
        if not self.config.exists():
            state = "station PAS ENCORE CONFIGURÉE : commence par le menu 2"
        else:
            state = "station en marche" if self.station_running() else "station arrêtée"
        line = (f"\n=== TRX Console  -  TRX distant version {self.installed} ===\n  {state}"
                f"\n  Identifiant de la station : {self.station_id() or 'créé au premier démarrage de la station'}")
        release = self.offered(self.update_state())
        if release is not None:
            line += self.banner([f"NOUVELLE VERSION {release.version} DISPONIBLE (installée : {self.installed})",
                                 f"Menu {UPDATE_MENU} : voir les changements, puis installer si tu le souhaites"])
        return line

    def menu_label(self, key: str, label: str) -> str:
        release = self.offered(self.update_state()) if key == UPDATE_MENU else None
        return f"{label}   <== NOUVELLE VERSION {release.version}" if release is not None else label

    def help_menu(self, key: str = "") -> None:
        """Touche « h » : à quoi sert un menu, quand s'en servir, ce qu'il modifie. Mêmes textes que le mode d'emploi
        en ligne (docs/console/contenu.toml), livrés avec la station dans console_help.json."""
        if not key:
            key = self.ask("Aide sur quel menu ? Numéro (Entrée = annuler) : ").strip()
            if not key:
                return
        item = next(((k, label, fn) for k, label, fn in self.items if k == key), None)
        if item is None:
            self.say(f"Pas de menu {key} : choisir un numéro de 1 à {len(self.items)}.")
            return
        number, label, fn = item
        texts = load_help().get(fn.__name__)
        if not texts:
            self.say(f"Aide indisponible pour le menu {number} : voir le mode d'emploi en ligne, {DOC_URL}")
            return
        out = [f"\nMenu {number} : {label}", "=" * min(76, len(label) + 10)]
        for title, field in (("À quoi il sert", "role"), ("Quand l'utiliser", "quand"), ("Ce qu'il modifie", "modifie")):
            if texts.get(field):
                out += ["", title.upper(), texts[field]]
        out += ["", "Droits d'administration (sudo) : " + ("oui, le mot de passe de session sera demandé" if texts.get("admin") else "non")]
        if texts.get("expert"):
            out += ["", "POUR ALLER PLUS LOIN", texts["expert"]]
        self.say("\n".join(out))

    def loop(self) -> int:
        if not self.config.exists():
            self.say(self.header())
            if self.yes("Première utilisation : lancer l'assistant de configuration"):
                self.assistant()
                self.pause()
        while True:
            self.say(self.header())
            for key, label, _ in self.items:
                self.say(f"  {key}) {self.menu_label(key, label)}")
            self.say("  h) Aide sur un menu (ex. « h 19 »)")
            self.say("  q) Quitter")
            try:
                choice = self.ask("Choix : ").strip().lower()
            except EOFError:
                return 0
            if choice in ("q", "quitter"):
                return 0
            asked = re.fullmatch(r"(?:h|aide|\?)\s*(\d*)", choice)
            if asked:
                try:
                    self.help_menu(asked.group(1))
                except EOFError:
                    return 0
                self.pause()
                continue
            action = next((fn for key, _, fn in self.items if key == choice), None)
            if action is None:
                self.say("Choix inconnu.")
                continue
            try:
                action()
            except KeyboardInterrupt:
                self.say("\nInterrompu.")
            except EOFError:                             # terminal fermé pendant une question : on quitte proprement
                return 0
            self.pause()


DOC_URL = "https://bob56fr.github.io/openRemoteTRX/console/"


def load_help() -> dict[str, dict]:
    """Textes de l'aide (touche h) par nom de méthode du menu ; {} si le fichier manque ou est illisible."""
    try:
        from importlib.resources import files
        data = json.loads(files("trxstation").joinpath("console_help.json").read_text(encoding="utf-8"))
        return data.get("menus", {}) if isinstance(data, dict) else {}
    except (OSError, ValueError, ModuleNotFoundError):
        return {}


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
