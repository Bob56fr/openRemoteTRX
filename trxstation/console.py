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
from .station_id import read_station_id
from .update import apply as upd
from .update.apply import previous_version
from .update.check import UpdateState, clean_text, parse_version, read_state, state_path

TARGET = "trx-remote.target"
IMPORT_NAME = "station.import.toml"
CHECK_UNIT = "trx-update-check.service"
INSTALL_LOG = "/var/log/trx-remote-install.log"
ZIP_PLACES = ("Desktop", "Bureau", "Downloads", "Téléchargements", "")   # où chercher un paquet déposé ("" = dossier personnel)
MAX_DIFF_LINES = 60
GNOME_EXTENSION_UUID = "trx-distant@rf-diy.com"
GNOME_EXTENSION_DIR = Path("/usr/share/gnome-shell/extensions") / GNOME_EXTENSION_UUID
QUIET_AFTER_S = 60.0              # tests : rappel « toujours en cours » après une minute sans rien de nouveau
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
                 desktop: Callable[[], Path] | None = None) -> None:
        self.config, self.runner, self.ask, self.say, self.python = config, runner or Runner(), ask, say, python
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
                self.runner.run(["systemctl", "start", CHECK_UNIT], admin=True)
                state = self.update_state()
            if state is None:
                return
        if not state.ok:
            self.say(f"Dernière recherche impossible : {clean_text(state.error, 300, single_line=True)}")
        release = self.offered(state)
        if release is None:
            self.say(f"TRX distant est à jour (version {self.installed}).")
            return
        published = clean_text(release.published_at, 40, single_line=True)
        self.say(f"\nNouvelle version : {release.version}{' (PRÉ-VERSION)' if release.prerelease else ''}"
                 f" ; installée : {self.installed}\n{clean_text(release.name, 120, single_line=True)}"
                 f"{' (' + published + ')' if published else ''}")
        self.say("\nNotes de version :\n" + (clean_text(release.notes, 4000) or "(aucune)"))
        self.say("\nPendant l'installation (quelques minutes, Internet nécessaire), la station est arrêtée.\n"
                 "Elle est refusée tant que le poste émet. Le paquet est vérifié (signature) avant toute installation ;\n"
                 f"la version {self.installed}, station.toml et les certificats sont conservés.")
        entered = self.ask(f"Pour installer, tape le numéro de version {release.version} (Entrée = non) : ").strip()
        if entered != release.version:
            self.say("Mise à jour annulée : rien n'a été modifié.")
            return
        code = self.runner.run(self.module("trxstation.update.apply", "--config", str(self.config), "install",
                                           "--version", release.version), admin=True)
        self.say(self._apply_result(code, f"Version {release.version} installée. Quitte TRX Console (q) et "
                                          "rouvre-la pour utiliser la nouvelle version."))

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

    def _save_config(self, original: bytes, edited: bytes, draft: Path) -> None:
        """Différences montrées, confirmation, sauvegarde de l'ancienne version, enregistrement par sudo avec les
        droits d'origine. `draft` est déjà validé."""
        before = original.decode("utf-8", "replace").splitlines()
        after = edited.decode("utf-8", "replace").splitlines()
        diff = [line for line in difflib.unified_diff(before, after, "avant", "après", n=0, lineterm="")
                if not line.startswith(("---", "+++", "@@"))]
        self.say("Changements :\n" + "\n".join("  " + line for line in diff[:MAX_DIFF_LINES])
                 + (f"\n  ... ({len(diff) - MAX_DIFF_LINES} lignes de plus)" if len(diff) > MAX_DIFF_LINES else ""))
        if not self.yes("Enregistrer ces changements", False):
            self.say("Abandon : station.toml n'a pas été changé.")
            return
        if self.config.read_bytes() != original:
            self.say("station.toml a été modifié par ailleurs pendant ce temps : abandon, recommence.")
            return
        st = self.config.stat()
        backup = self.config.with_name(f"{self.config.name}.avant-modification-{time.strftime('%Y%m%d-%H%M%S')}")
        if self.runner.run(["cp", "-p", str(self.config), str(backup)], admin=True) != 0:
            self.say("Copie de sauvegarde impossible : station.toml n'a pas été changé.")
            return
        code = self.runner.run(["install", "-m", f"{st.st_mode & 0o777:o}", "-o", str(st.st_uid), "-g", str(st.st_gid),
                                str(draft), str(self.config)], admin=True)
        if code != 0:
            self.say(f"Enregistrement impossible (code {code}) : station.toml n'a pas été changé.")
            return
        self.say(f"Enregistré. Ancienne version gardée : {backup}")
        if self.station_running():
            if self.yes("Redémarrer la station pour appliquer"):
                self.start()
        else:
            self.say("Les changements s'appliqueront au prochain démarrage de la station (menu 5).")

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
            line += f"\n  ** Nouvelle version {release.version} disponible : menu 10 **"
        return line

    def loop(self) -> int:
        if not self.config.exists():
            self.say(self.header())
            if self.yes("Première utilisation : lancer l'assistant de configuration"):
                self.assistant()
                self.pause()
        while True:
            self.say(self.header())
            for key, label, _ in self.items:
                self.say(f"  {key}) {label}")
            self.say("  q) Quitter")
            try:
                choice = self.ask("Choix : ").strip().lower()
            except EOFError:
                return 0
            if choice in ("q", "quitter"):
                return 0
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
