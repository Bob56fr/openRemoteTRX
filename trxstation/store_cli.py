# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Version Microsoft Store : aiguillage des commandes tapées dans un terminal.

Le Store refuse plus de 8 applications par paquet et toute application cachée du menu Démarrer (erreurs de
validation du 2026-11-21) : UNE seule application « openRemoteTRX » porte TOUS les alias d'exécution (trx-console,
trx-setup, trx-monitor…). Lancé par un alias, `sys.executable` vaut le chemin de l'alias (essai S0) : son nom choisit
la commande ; lancé depuis le menu Démarrer, c'est TRX Console.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import PureWindowsPath

DEFAULT = "trxstation.console"
# Alias (sans .exe) -> module ; même liste que [project.scripts] moins les services (tests/test_store.py le vérifie).
COMMANDS = {
    "trx-console": "trxstation.console",
    "trx-setup": "trxstation.setup_wizard",
    "trx-monitor": "trxstation.monitor.main",
    "trx-hwtest": "trxstation.devtools.hwtest",
    "trx-qualif": "trxstation.qualif.main",
    "trx-journal-android": "trxstation.devtools.androidlog",
    "trx-netreport": "trxstation.netprobe.netreport",
    "trx-sdr": "trxstation.sdr.devices",
}


def module_for(executable: str) -> str:
    return COMMANDS.get(PureWindowsPath(executable).stem.lower(), DEFAULT)


def main() -> None:
    module = module_for(sys.executable)
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
