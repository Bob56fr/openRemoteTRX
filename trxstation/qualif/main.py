# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""`trx-qualif` : qualification d'un poste avant son intégration dans TRX Remote (lot Q1, ligne de commande).

  trx-qualif --plan                    cahier de test du modèle de station.toml, sans toucher au poste
  trx-qualif                           qualification complète guidée, rapport dans ./qualifications/
  trx-qualif --catalogue DOSSIER       vérifie toutes les fiches d'un catalogue
  trx-qualif --plan --modele 1042      cahier de test et incohérences de dump_caps d'un modèle, sans station.toml
  trx-qualif --explorer                exploration d'un poste jamais essayé, SANS émission (expert)
  trx-qualif --sans-emission           qualification sans la phase d'émission (verdict « incomplet »)

Le wizard graphique (page web locale) viendra au lot Q2 ; le moteur est le même.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .. import config as cfgmod
from ..asyncio_noise import install_quiet_handler
from ..config import Config
from ..gateway.cat.capabilities import CapabilitiesError, _run_dump_caps
from ..hamlib import rigctld_command
from ..paths import default_config_path
from ..answers import typed
from ..gateway.cat import RigctldClient
from .coherence import analyse_caps, render_findings
from .explore import Exploration
from .explore_report import write_report as write_explore_report
from .plan import build_plan, render_plan
from .profile import HamlibProfile, hamlib_version, parse_profile
from .results import IN_VALIDATION, REFUSE, compute_verdict
from .runner import Qualification
from .sheet import load_catalog
from .trace import TraceProxy

EXIT_OK, EXIT_REFUSED, EXIT_CONFIG, EXIT_HAMLIB, EXIT_INCOMPLETE = 0, 1, 2, 3, 4


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), 0.3):
            return True
    except OSError:
        return False


def load_profile(cfg: Config | None, model: int | None = None, hamlib_dir: str = "") -> tuple[HamlibProfile, str]:
    """Profil Hamlib du modèle configuré, ou de `model` (CapabilitiesError si `rigctl -u` échoue)."""
    model = model if model is not None else cfg.rig.model
    hamlib_dir = cfg.tools.hamlib_dir if cfg is not None else hamlib_dir
    text = _run_dump_caps(model, hamlib_dir)
    profile = parse_profile(text, model)
    if not profile.hamlib_version:
        profile.hamlib_version = hamlib_version(hamlib_dir)
    return profile, text


def render_plan_with_findings(profile: HamlibProfile) -> str:
    return (render_plan(build_plan(profile), profile) + "\n\nIncohérences de dump_caps (aucune commande envoyée au poste) :\n"
            + render_findings(analyse_caps(profile)))


class RigctldUnavailable(Exception):
    pass


@contextlib.asynccontextmanager
async def rigctld_session(cfg: Config, *, spawn: bool, out=print):
    """rigctld propre à l'outil (lancé puis arrêté ici). Un rigctld qui répond déjà est REFUSÉ sauf --no-spawn :
    c'est presque toujours celui de la station, et deux programmes qui pilotent le poste se gênent."""
    host, port = cfg.network.rigctld_host, cfg.network.rigctld_port
    proc = None
    if _port_open(host, port):
        if spawn:
            raise RigctldUnavailable(f"rigctld répond déjà sur {host}:{port} : la station tourne-t-elle ? Arrête-la "
                                     "(TRX Console, menu 1.2), ou ajoute --no-spawn pour utiliser ce rigctld.")
    elif not spawn:
        raise RigctldUnavailable(f"rigctld ne répond pas sur {host}:{port} : lance-le (trx-rigctld) ou retire --no-spawn.")
    else:
        try:
            out("Démarrage de rigctld…")
            proc = subprocess.Popen(rigctld_command(cfg))
        except FileNotFoundError as exc:
            raise RigctldUnavailable(str(exc)) from exc
        for _ in range(50):
            if _port_open(host, port) or proc.poll() is not None:
                break
            await asyncio.sleep(0.1)
        if not _port_open(host, port):
            _stop(proc)
            raise RigctldUnavailable("rigctld n'a pas démarré (modèle, port COM ou débit incorrects ? poste éteint ?).")
    try:
        yield host, port
    finally:
        if proc is not None:
            _stop(proc)


def _stop(proc) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def find_config(cwd: Path | None = None) -> Path:
    """Emplacement standard s'il existe, sinon station.toml du dossier courant (poste de développement)."""
    standard = default_config_path()
    local = (cwd or Path.cwd()) / "station.toml"
    return standard if standard.exists() or not local.exists() else local


def check_catalogue(directory: Path, out=print) -> int:
    catalog = load_catalog(directory)
    count = sum(len(v) for v in catalog.sheets.values())
    out(f"{count} fiche(s) valide(s) dans {directory}")
    for name, problems in catalog.problems.items():
        out(f"  ÉCARTÉE {name} :")
        for p in problems:
            out(f"    - {p}")
    return EXIT_REFUSED if catalog.problems else EXIT_OK


async def run_qualif(cfg: Config, profile: HamlibProfile, dump_text: str, output: Path, *, spawn: bool = True,
                     ask=input, out=print, **kwargs) -> int:
    install_quiet_handler(asyncio.get_running_loop())
    directory = output / f"qualif-{profile.model}-{datetime.now():%Y%m%d-%H%M%S}"
    try:
        async with rigctld_session(cfg, spawn=spawn, out=out) as (host, port):
            proxy = TraceProxy(host, port)
            await proxy.start()
            proxied = copy.deepcopy(cfg)
            proxied.network.rigctld_host, proxied.network.rigctld_port = "127.0.0.1", proxy.port
            directory.mkdir(parents=True, exist_ok=True)
            q = Qualification(proxied, profile=profile, dump_text=dump_text, proxy=proxy, ask=ask, out=out,
                              record_wav=str(directory / "rx.wav"), **kwargs)
            try:
                await q.run()
            finally:
                await proxy.stop()
    except RigctldUnavailable as exc:
        out(str(exc))
        return EXIT_HAMLIB
    if not q.checks:
        if not any(directory.iterdir()):
            directory.rmdir()                          # qualification annulée : pas de dossier vide
        return EXIT_INCOMPLETE
    for line in q.summary():
        out(line)
    q.write_report(directory)
    out(f"\nRapport : {directory}")
    verdict = compute_verdict(q.checks).status
    return EXIT_OK if verdict == IN_VALIDATION else EXIT_REFUSED if verdict == REFUSE else EXIT_INCOMPLETE


EXPLORE_PREFLIGHT = """
Exploration SANS ÉMISSION d'un poste (expert). Aucune commande de PTT n'est envoyée. Le poste va :
  - répondre à la lecture de TOUT ce que Hamlib déclare (fonctions, niveaux, paramètres) ;
  - changer de fréquence (bords de la couverture de réception, puis une fréquence hors couverture) ;
  - changer quelques réglages de réception (liste fermée : CTCSS, APF, PBT, pitch CW…), aussitôt remis.
Le mode n'est jamais changé. Fréquence et réglages sont rétablis à la fin.
Ne touche pas au poste pendant l'essai et N'ÉMETS PAS : une émission détectée arrête tout.
Option --lecture-seule : ni fréquence ni réglage changés, lectures seulement.
"""


async def run_explore(cfg: Config, profile: HamlibProfile, dump_text: str, output: Path, *, spawn: bool = True,
                      ask=input, out=print, writes: bool = True, burst: int = 300, settle_s: float = 1.5) -> int:
    install_quiet_handler(asyncio.get_running_loop())
    out(f"Exploration : {profile.name} (Hamlib {profile.hamlib_version or '?'}, backend {profile.backend_status or '?'})")
    out(EXPLORE_PREFLIGHT)
    if not typed(await asyncio.to_thread(ask, "Tape OUI pour commencer : "), "OUI"):
        out("Exploration annulée.")
        return EXIT_INCOMPLETE
    firmware = (await asyncio.to_thread(ask, "Version du firmware affichée par le poste (Entrée si inconnue) : ")).strip()
    if not (len(firmware) <= 20 and all(c.isalnum() or c in ".-_ " for c in firmware)):
        firmware = ""
    journal: list[str] = []

    def say(text: str) -> None:
        journal.append(text)
        out(text)
    try:
        async with rigctld_session(cfg, spawn=spawn, out=say) as (host, port):
            proxy = TraceProxy(host, port)
            await proxy.start()
            client = RigctldClient("127.0.0.1", proxy.port, timeout=3.0)
            try:
                await client.connect()
                exploration = Exploration(client, profile, out=say, note=proxy.note, writes=writes, burst=burst,
                                          settle_s=settle_s)
                result = await exploration.run()
            finally:
                await client.close()
                await proxy.stop()
    except RigctldUnavailable as exc:
        out(str(exc))
        return EXIT_HAMLIB
    except ConnectionError as exc:                        # liaison impossible : rien n'a été écrit
        out(f"Exploration impossible : {exc}")
        return EXIT_HAMLIB
    say("\n================  CONSTATS DE L'EXPLORATION  ================")
    say(render_findings(result.findings))
    if result.restored is False:
        say("!!! Fréquence ou mode d'origine NON rétablis : vérifie le poste.")
    directory = write_explore_report(output / f"explore-{profile.model}-{datetime.now():%Y%m%d-%H%M%S}", profile, result,
                                     dump_text=dump_text, journal=journal, proxy=proxy, firmware=firmware)
    out(f"\nRapport : {directory}")
    return EXIT_REFUSED if result.stopped else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-qualif", description="Qualification d'un poste pour TRX Remote")
    ap.add_argument("--config", type=Path, default=None,
                    help="station.toml (défaut : emplacement standard, sinon ./station.toml)")
    ap.add_argument("--plan", action="store_true", help="afficher le cahier de test du modèle, sans toucher au poste")
    ap.add_argument("--catalogue", type=Path, metavar="DOSSIER", help="vérifier les fiches d'un catalogue")
    ap.add_argument("--output", type=Path, default=Path("qualifications"), help="dossier des rapports (défaut : ./qualifications)")
    ap.add_argument("--cycles", type=int, default=1000, help="lectures de l'essai d'endurance (défaut : 1000)")
    ap.add_argument("--tot", type=float, default=8.0, help="TOT pendant les essais d'émission, en secondes (défaut : 8)")
    ap.add_argument("--no-spawn", action="store_true", help="ne pas lancer rigctld soi-même")
    ap.add_argument("--modele", type=int, metavar="N", help="avec --plan : modèle Hamlib à analyser, sans station.toml")
    ap.add_argument("--explorer", action="store_true", help="exploration d'un poste jamais essayé, SANS émission (expert)")
    ap.add_argument("--lecture-seule", action="store_true", help="avec --explorer : ni fréquence ni réglage changés")
    ap.add_argument("--sans-emission", action="store_true", help="qualification sans la phase d'émission")
    ap.add_argument("--filtres", action="store_true",
                    help="essayer les largeurs de filtre (peut RÉÉCRIRE les préréglages de filtre du poste, Icom : FIL1/2/3)")
    args = ap.parse_args(argv)
    if args.catalogue is not None:
        return check_catalogue(args.catalogue)
    if args.modele is not None:
        if not args.plan:
            print("--modele ne sert qu'avec --plan (les autres essais prennent le modèle de station.toml).", file=sys.stderr)
            return EXIT_CONFIG
        if not 1 <= args.modele <= 99_999:
            print("--modele : numéro de modèle Hamlib invalide (voir rigctl -l).", file=sys.stderr)
            return EXIT_CONFIG
        try:
            profile, _ = load_profile(None, args.modele)
        except CapabilitiesError as exc:
            print(f"Hamlib : {exc}", file=sys.stderr)
            return EXIT_HAMLIB
        print(render_plan_with_findings(profile))
        return EXIT_OK
    if args.explorer and (args.sans_emission or args.filtres):
        print("--explorer n'émet jamais et ne touche pas aux filtres : --sans-emission et --filtres sont pour la qualification.",
              file=sys.stderr)
        return EXIT_CONFIG
    if args.lecture_seule and not args.explorer:
        print("--lecture-seule ne sert qu'avec --explorer.", file=sys.stderr)
        return EXIT_CONFIG
    config_path = args.config or find_config()
    try:
        cfg = cfgmod.load(config_path)
    except FileNotFoundError:
        print(f"Configuration introuvable : {config_path}\n"
              "  Indique-la avec --config CHEMIN (exemple : --config station.toml), ou crée-la avec trx-setup.",
              file=sys.stderr)
        return EXIT_CONFIG
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return EXIT_CONFIG
    if not 100 <= args.cycles <= 100_000:
        print("--cycles doit être compris entre 100 et 100 000.", file=sys.stderr)
        return EXIT_CONFIG
    if not 2.0 <= args.tot <= 60.0:
        print("--tot doit être compris entre 2 et 60 secondes.", file=sys.stderr)
        return EXIT_CONFIG
    try:
        profile, text = load_profile(cfg)
    except CapabilitiesError as exc:
        print(f"Hamlib : {exc}", file=sys.stderr)
        return EXIT_HAMLIB
    if args.plan:
        print(render_plan_with_findings(profile))
        return EXIT_OK
    try:
        if args.explorer:
            return asyncio.run(run_explore(cfg, profile, text, args.output, spawn=not args.no_spawn,
                                           writes=not args.lecture_seule))
        return asyncio.run(run_qualif(cfg, profile, text, args.output, spawn=not args.no_spawn,
                                      endurance_cycles=args.cycles, tot_s=args.tot, no_tx=args.sans_emission,
                                      filters_test=args.filtres))
    except ValueError as exc:
        print(f"--tot : {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except KeyboardInterrupt:
        print("\nInterrompu : l'émission a été coupée.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
