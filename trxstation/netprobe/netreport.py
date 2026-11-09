# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""`trx-netreport` : résumé lisible de la qualité du réseau (EF10) et export anonyme pour l'équipe de développement.

    trx-netreport                      24 dernières heures
    trx-netreport --jours 30           30 derniers jours
    trx-netreport --export FICHIER.zip export anonyme (rapport.html + donnees.json)

Lit le journal de la sonde (state_dir/netprobe) sans rien y écrire ; la station peut tourner pendant ce temps.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from .. import __version__
from .. import config as cfgmod
from ..paths import default_config_path
from ..station_id import read_station_id
from .export import build_export, export_name, report_text, store_of


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-netreport", description="Qualité du réseau de la station (sonde réseau)")
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--jours", type=int, default=1, help="période en jours (1 à 90, défaut 1 = 24 h)")
    ap.add_argument("--export", type=Path, default=None, metavar="FICHIER",
                    help="écrit l'export anonyme (zip) ; un dossier = nom automatique dedans")
    args = ap.parse_args(argv)
    if not 1 <= args.jours <= 90:
        print("--jours : entre 1 et 90", file=sys.stderr)
        return 2
    try:
        cfg, _ = cfgmod.load_unchecked(args.config)
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration illisible ({exc}) : dossier d'état par défaut.", file=sys.stderr)
        cfg = cfgmod.Config()
    store = store_of(cfg.supervisor.state_dir, cfg.netprobe)
    if not store.folder.is_dir():
        print(f"Aucune mesure : {store.folder} n'existe pas (sonde réseau arrêtée, ou aucun client connecté depuis "
              "l'installation de la version 0.106.0).")
        return 1
    if args.export is not None:
        target = args.export / export_name() if args.export.is_dir() else args.export
        days = 30 if args.jours == 1 else args.jours                   # sans --jours : les 30 derniers jours
        target.write_bytes(build_export(store, days, version=__version__,
                                        station_id=read_station_id(cfg.supervisor.state_dir) or "",
                                        settings=asdict(cfg.netprobe)))
        print(f"Export anonyme écrit : {target} (à joindre à un message pour l'équipe de développement).")
        return 0
    print(report_text(store.stats(args.jours, "", {})), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
