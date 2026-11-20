# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Version Microsoft Store : lanceur de la station et dossier des données.

Cahier `docs/store-microsoft-cahier-des-charges.md` § 3.2, § 3.3, § 5. La tâche de démarrage d'un MSIX IGNORE les
paramètres du manifeste (essai S0) : l'application « Supervisor » est `python\\trx-station.exe` (copie de pythonw.exe)
SANS paramètre ; un `.pth` du paquet appelle `maybe_boot()` à chaque démarrage de Python : seul trx-station.exe lancé
sans argument démarre la station, tout autre lancement (passerelle, modules, outils) continue normalement.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from . import paths

log = logging.getLogger("trxstation.store_boot")

LAUNCHER = "trx-station.exe"
ZIP_TASK = "TRX distant"                 # tâche planifiée de la version zip (windows/installer.ps1, $TaskName)
EXIT_ZIP_INSTALLED = 6
CREATE_NO_WINDOW = 0x08000000


def data_dir() -> Path:
    return paths.default_config_path().parent


def zip_installed(run=subprocess.run) -> bool:
    """Vrai si la version zip est installée sur ce PC (sa tâche planifiée existe) : deux stations = deux rigctld."""
    if sys.platform != "win32":
        return False
    try:
        rc = run(["schtasks", "/Query", "/TN", ZIP_TASK], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW).returncode
    except OSError:
        return False
    return rc == 0


def prepare_data_dir(root: Path | None = None, *, run=subprocess.run) -> Path:
    """Crée `C:\\ProgramData\\trx-remote` (et `logs`) SOUS LE COMPTE de l'opérateur, puis réserve le dossier à ce
    compte, aux administrateurs et au système, comme l'installateur du zip (station.toml contient les empreintes des
    mots de passe). Un dossier déjà là (zip, installation précédente) n'est pas touché."""
    root = root or data_dir()
    created = not root.exists()
    (root / "logs").mkdir(parents=True, exist_ok=True)
    if created and sys.platform == "win32":
        me = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
        try:
            run(["icacls", str(root), "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
                 "*S-1-5-18:(OI)(CI)F", f"{me}:(OI)(CI)M", "/T", "/C", "/Q"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW)
        except OSError:
            pass                                 # droits hérités de ProgramData : lisibles des autres comptes du PC
    return root


def boot(*, supervisor_main=None, zip_check=zip_installed, setup_logs: bool = True) -> int:
    """Démarre la station (superviseur) avec la configuration par défaut ; refus si la version zip est installée."""
    from .errors import codes
    from .errors.emit import emit_event
    from .logsetup import LOG_DIR_ENV, setup_logging
    root = prepare_data_dir()
    if zip_check():
        if setup_logs:
            os.environ[LOG_DIR_ENV] = str(root / "logs")
            setup_logging("superviseur")
        emit_event(codes.ORT_8029, logger=log)
        return EXIT_ZIP_INSTALLED
    config = root / "station.toml"
    if not config.exists():
        return 0                                 # station pas encore configurée : TRX Console s'en charge
    if supervisor_main is None:
        from .supervisor.main import main as supervisor_main
    return supervisor_main(["--config", str(config), "--log-dir", str(root / "logs")])


def maybe_boot() -> None:
    """Appelé par le `.pth` du paquet à CHAQUE démarrage de Python : n'agit que pour trx-station.exe sans argument."""
    if os.path.basename(sys.executable).lower() != LAUNCHER or sys.argv not in ([], [""]):
        return
    sys.argv = ["trx-station"]
    try:
        code = boot()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:                     # noqa: BLE001 - aucune fenêtre : seule trace possible, le journal
        from .errors import codes
        from .errors.emit import emit_event
        code = 1
        emit_event(codes.ORT_9312, logger=log, trace=True, outil="trx-station", erreur=repr(exc),
                   fichier=str(data_dir() / "logs"))
    os._exit(code)
