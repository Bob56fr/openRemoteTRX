"""TRX Console : point d'entrée unique de la station pour qui ne connaît pas Linux (commande `trx-console`).

Un menu numéroté regroupe le diagnostic, l'assistant de configuration, le tableau de bord, l'essai du poste,
le démarrage et l'arrêt des services, le journal, le rapport de dépannage et la sortie du mode sûr.
Les actions qui touchent au système passent par `sudo` : le mot de passe de session est demandé au besoin.

    trx-console               menu
    trx-console --diagnostic  diagnostic complet puis sortie (code 1 si une erreur bloquante)
    trx-console --rapport     crée le rapport de dépannage (zip sur le Bureau)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .diagnostics import CONFIG_PATH, UNITS, exit_code, format_checks, run_all

TARGET = "trx-remote.target"
IMPORT_NAME = "station.import.toml"


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
                 python: str = sys.executable) -> None:
        self.config, self.runner, self.ask, self.say, self.python = config, runner or Runner(), ask, say, python
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

    # ------------------------------------------------------------------ boucle

    def header(self) -> str:
        if not self.config.exists():
            state = "station PAS ENCORE CONFIGURÉE : commence par le menu 2"
        else:
            state = "station en marche" if self.station_running() else "station arrêtée"
        return f"\n=== TRX Console === ({state})"

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
