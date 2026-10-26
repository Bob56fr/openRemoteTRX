"""Localisation des outils Hamlib (rigctl, rigctld) : réglage, variable d'environnement, PATH,
puis dossiers d'installation habituels sous Windows."""
from __future__ import annotations

import glob
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from .config import Config, spectrum_rigctld_conf

WINDOWS_PATTERNS = (r"C:\Program Files\hamlib*", r"C:\Program Files (x86)\hamlib*", r"C:\hamlib*",
                    r"C:\Hamlib*")


def find_tool(name: str, hamlib_dir: str = "", *, env: Mapping[str, str] | None = None,
              which: Callable[[str], str | None] = shutil.which,
              globber: Callable[[str], list[str]] = glob.glob, platform: str | None = None) -> str | None:
    plat = platform or sys.platform
    env = os.environ if env is None else env
    exe = name + (".exe" if plat == "win32" else "")
    directories = [d for d in (hamlib_dir, env.get("TRX_HAMLIB_DIR", "")) if d]
    for directory in directories:
        for candidate in (Path(directory) / "bin" / exe, Path(directory) / exe):
            if candidate.is_file():
                return str(candidate)
    if found := which(name):
        return found
    if plat == "win32":
        for pattern in WINDOWS_PATTERNS:
            for directory in sorted(globber(pattern), reverse=True):   # version la plus récente d'abord
                candidate = Path(directory) / "bin" / exe
                if candidate.is_file():
                    return str(candidate)
    return None


def rigctld_command(cfg: Config, **find_kwargs) -> list[str]:
    """Commande complète de rigctld avec son chemin résolu (FileNotFoundError si Hamlib est absent)."""
    args = cfg.rig.rigctld_args(cfg.network.rigctld_host, cfg.network.rigctld_port) + spectrum_rigctld_conf(cfg)
    exe = find_tool("rigctld", cfg.tools.hamlib_dir, **find_kwargs)
    if exe is None:
        raise FileNotFoundError("rigctld introuvable : installe Hamlib ou renseigne [tools] hamlib_dir "
                                "dans station.toml")
    return [exe, *args[1:]]
