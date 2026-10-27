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
import difflib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .diagnostics import CONFIG_PATH, UNITS, exit_code, format_checks, run_all
from .paths import default_state_dir
from .update import apply as upd
from .update.apply import previous_version
from .update.check import UpdateState, clean_text, parse_version, read_state, state_path

TARGET = "trx-remote.target"
IMPORT_NAME = "station.import.toml"
CHECK_UNIT = "trx-update-check.service"
INSTALL_LOG = "/var/log/trx-remote-install.log"
ZIP_PLACES = ("Desktop", "Bureau", "Downloads", "Téléchargements", "")   # où chercher un paquet déposé ("" = dossier personnel)
MAX_DIFF_LINES = 60


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
                 home: Path | None = None, editor: str | None = None) -> None:
        self.config, self.runner, self.ask, self.say, self.python = config, runner or Runner(), ask, say, python
        self.update_state = update_state or (lambda: read_state(state_path(config_state_dir(self.config))))
        self.previous, self.installed = previous, installed
        self.home = home or Path.home()
        self.editor = editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or shutil.which("nano") or ""
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
        answer = self.ask(f"{question} ({'O/n' if default else 'o/N'}) : ").strip().lower()
        return default if not answer else answer in ("o", "oui", "y", "yes")

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
        self.say("Essai sur le vrai poste : charge fictive ou antenne accordée, puissance réduite.\n"
                 "Chaque étape d'émission demande une confirmation.")
        stopped = self.stop_for_exclusive_use("l'essai")
        self.runner.run(self.module("trxstation.devtools.hwtest", "--config", str(self.config)), admin=True)
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
        typed = self.ask(f"Pour installer, tape le numéro de version {release.version} (Entrée = non) : ").strip()
        if typed != release.version:
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
            if self.ask("Tape OUI pour accepter un paquet non signé (Entrée = non) : ").strip() != "OUI":
                self.say("Annulé : rien n'a été modifié.")
                return
            extra = ["--sans-signature"]
        typed = self.ask(f"Pour installer, tape le numéro de version {version} (Entrée = non) : ").strip()
        if typed != version:
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
        finally:
            shutil.rmtree(work, ignore_errors=True)

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

    def header(self) -> str:
        if not self.config.exists():
            state = "station PAS ENCORE CONFIGURÉE : commence par le menu 2"
        else:
            state = "station en marche" if self.station_running() else "station arrêtée"
        line = f"\n=== TRX Console === ({state})"
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
