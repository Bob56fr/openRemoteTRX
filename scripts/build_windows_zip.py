# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique le paquet Windows : dist/trx-remote-windows-X.Y.Z.zip.

Contenu (dossier racine trx-remote-windows-X.Y.Z/) : installer.cmd (double-clic), installer.ps1, notice-windows.html,
LISEZMOI.txt, LICENSE, VERSION, et app/ (pyproject.toml, LICENSE, trxstation/) installé par pip dans un environnement
Python propre à chaque version. Pas de Hamlib (à installer à part, licence et mises à jour propres) ni de Python.

installer.ps1 est écrit en UTF-8 AVEC BOM : sans lui, PowerShell 5.1 le lit en ANSI et abîme les accents.
Usage : python scripts/build_windows_zip.py
"""
from __future__ import annotations

import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows"
BOM = b"\xef\xbb\xbf"
TOP_FILES = ("installer.cmd", "installer.ps1", "notice-windows.html", "LISEZMOI.txt")
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def version(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def manifest(root: Path = ROOT) -> list[tuple[str, Path]]:
    """[(nom dans le zip, sans le dossier racine), fichier source]."""
    files = [(name, root / "windows" / name) for name in TOP_FILES]
    files += [("LICENSE", root / "LICENSE"), ("app/LICENSE", root / "LICENSE"), ("app/pyproject.toml", root / "pyproject.toml")]
    for path in sorted((root / "trxstation").rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not EXCLUDED_PARTS.intersection(rel.parts) and path.suffix not in EXCLUDED_SUFFIXES:
            files.append((f"app/{rel.as_posix()}", path))
    missing = [str(src.relative_to(root)) for _, src in files if not src.is_file()]
    if missing:
        raise FileNotFoundError("fichiers manquants : " + ", ".join(missing))
    return files


def content(name: str, source: Path) -> bytes:
    data = source.read_bytes()
    if name.endswith(".ps1") and not data.startswith(BOM):
        data = BOM + data
    if name.endswith((".cmd", ".txt")):
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")     # Bloc-notes et cmd.exe : fins de ligne Windows
    return data


def build(out_dir: Path | None = None, root: Path = ROOT) -> Path:
    v = version(root)
    top = f"trx-remote-windows-{v}"
    out_dir = out_dir or root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{top}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, source in manifest(root):
            archive.writestr(f"{top}/{name}", content(name, source))
        archive.writestr(f"{top}/VERSION", v + "\r\n")
    return target


def main() -> int:
    target = build()
    print(f"Paquet Windows créé : {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
