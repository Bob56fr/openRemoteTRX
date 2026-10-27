# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lance rigctld avec les réglages de station.toml (utilisé par l'unit systemd rigctld.service)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import config as cfgmod
from .hamlib import rigctld_command
from .paths import default_config_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-rigctld")
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--print", action="store_true", help="affiche la commande sans l'exécuter")
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    if args.print:
        print(" ".join(cfg.rig.rigctld_args(cfg.network.rigctld_host, cfg.network.rigctld_port)
                       + cfgmod.spectrum_rigctld_conf(cfg)))
        return 0
    try:
        command = rigctld_command(cfg)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 3
    if os.name == "nt":                # Windows : execv ne remplace pas le processus, on attend rigctld
        return subprocess.call(command)
    os.execv(command[0], command)      # remplace ce processus : systemd suit directement rigctld


if __name__ == "__main__":
    raise SystemExit(main())
