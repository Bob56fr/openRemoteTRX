# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""python -m trxstation.dashboard [--config station.toml] [--demo]

  (sans option) : sert le tableau de bord d'après [dashboard] (service trx-dashboard) ;
  --demo        : fausse station, pour essayer la page sans station (127.0.0.1 seulement).
Pas de commande trx-dashboard dans le PATH : sans clé d'accès, il n'y a rien à afficher à l'opérateur ; les adresses sont
dans l'en-tête d'openRemoteTRX Console.
Codes de sortie : 0 = arrêt normal ou [dashboard] enabled = false ; 2 = configuration refusée (relancer n'y changerait rien).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .. import config as station_config
from ..paths import default_config_path
from . import __version__
from .app import Dashboard
from .settings import Settings, SettingsError, check, from_station


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.dashboard",
                                 description="Tableau de bord des signes vitaux de la station (lecture seule).")
    ap.add_argument("--config", type=Path, default=None, help="station.toml (défaut : celui de la station)")
    ap.add_argument("--demo", action="store_true", help="fausse station, pour essayer la page")
    ap.add_argument("--port", type=int, help="remplace [dashboard] port (essais)")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s : %(message)s")

    if args.demo:
        settings = Settings(port=args.port or 8450)
    else:
        path = args.config or default_config_path()
        try:
            cfg = station_config.load(path)
        except station_config.ConfigError as exc:
            print(f"station.toml refusée : {exc}", file=sys.stderr)
            return 2
        if cfg.dashboard.enabled is not True:
            print("tableau de bord hors service ([dashboard] enabled = false)")
            return 0
        settings = from_station(cfg, Path(path))
        if args.port:
            settings.port = args.port
    try:
        check(settings)
    except SettingsError as exc:
        print(f"tableau de bord : {exc}", file=sys.stderr)
        return 2
    try:
        asyncio.run(Dashboard(settings, demo_mode=args.demo).run())
    except KeyboardInterrupt:
        pass
    except OSError as exc:                       # port déjà pris, certificat illisible…
        print(f"tableau de bord : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
