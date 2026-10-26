"""`trx-qualif` : qualification d'un poste avant son intégration dans TRX Remote (lot Q1, ligne de commande).

  trx-qualif --plan                    cahier de test du modèle de station.toml, sans toucher au poste
  trx-qualif                           qualification complète guidée, rapport dans ./qualifications/
  trx-qualif --catalogue DOSSIER       vérifie toutes les fiches d'un catalogue

Le wizard graphique (page web locale) viendra au lot Q2 ; le moteur est le même.
"""
from __future__ import annotations

import argparse
import asyncio
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


def load_profile(cfg: Config) -> tuple[HamlibProfile, str]:
    """Profil Hamlib du modèle configuré (CapabilitiesError si `rigctl -u` échoue)."""
    text = _run_dump_caps(cfg.rig.model, cfg.tools.hamlib_dir)
    profile = parse_profile(text, cfg.rig.model)
    if not profile.hamlib_version:
        profile.hamlib_version = hamlib_version(cfg.tools.hamlib_dir)
    return profile, text


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
    host, port = cfg.network.rigctld_host, cfg.network.rigctld_port
    proc = None
    if not _port_open(host, port):
        if not spawn:
            out(f"rigctld ne répond pas sur {host}:{port} : lance-le (trx-rigctld) ou retire --no-spawn.")
            return EXIT_HAMLIB
        try:
            out("Démarrage de rigctld…")
            proc = subprocess.Popen(rigctld_command(cfg))
        except FileNotFoundError as exc:
            out(str(exc))
            return EXIT_HAMLIB
        for _ in range(50):
            if _port_open(host, port) or proc.poll() is not None:
                break
            await asyncio.sleep(0.1)
        if not _port_open(host, port):
            out("rigctld n'a pas démarré (modèle, port COM ou débit incorrects ? poste éteint ?).")
            return EXIT_HAMLIB
    proxy = TraceProxy(host, port)
    await proxy.start()
    proxied = copy.deepcopy(cfg)
    proxied.network.rigctld_host, proxied.network.rigctld_port = "127.0.0.1", proxy.port
    directory = output / f"qualif-{profile.model}-{datetime.now():%Y%m%d-%H%M%S}"
    directory.mkdir(parents=True, exist_ok=True)
    q = Qualification(proxied, profile=profile, dump_text=dump_text, proxy=proxy, ask=ask, out=out,
                      record_wav=str(directory / "rx.wav"), **kwargs)
    try:
        await q.run()
    finally:
        await proxy.stop()
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
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
    args = ap.parse_args(argv)
    if args.catalogue is not None:
        return check_catalogue(args.catalogue)
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
        print(render_plan(build_plan(profile), profile))
        return EXIT_OK
    try:
        return asyncio.run(run_qualif(cfg, profile, text, args.output, spawn=not args.no_spawn,
                                      endurance_cycles=args.cycles, tot_s=args.tot))
    except ValueError as exc:
        print(f"--tot : {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except KeyboardInterrupt:
        print("\nInterrompu : l'émission a été coupée.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
