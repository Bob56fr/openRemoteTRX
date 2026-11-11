# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique le paquet Windows : dist/trx-remote-windows-X.Y.Z.zip.

Contenu (dossier racine trx-remote-windows-X.Y.Z/) : installer.cmd (double-clic), installer.ps1, notice-windows.html,
LISEZMOI.txt, LICENSE, VERSION, et app/ (pyproject.toml, LICENSE, trxstation/) installé par pip dans un environnement
Python propre à chaque version. Pas de Hamlib (à installer à part, licence et mises à jour propres) ni de Python.
freedv/ : décodeurs FreeDV RADE V1 (freedv-ka9q.exe, radae_rx.exe, DLL, licences) compilés depuis Debian par
`bash debian/compiler-freedv.sh --windows DOSSIER` (sources épinglées) ; chaque fichier est vérifié contre le
SHA256SUMS du dossier. Sans ce dossier, le paquet est fait SANS décodeurs (avertissement) : le mode FreeDV de la
station répond alors « décodeur introuvable ».

installer.ps1 est écrit en UTF-8 AVEC BOM : sans lui, PowerShell 5.1 le lit en ANSI et abîme les accents.
Usage : python scripts/build_windows_zip.py [--freedv DOSSIER]   (défaut : dist/freedv-windows s'il existe)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows"
BOM = b"\xef\xbb\xbf"
TOP_FILES = ("installer.cmd", "installer.ps1", "notice-windows.html", "LISEZMOI.txt")
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache",
                  "marque", "play-store"}                          # images de présentation (site, Play Store) : inutiles sur une station
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
FREEDV_REQUIRED = ("freedv-ka9q.exe", "radae_rx.exe", "librade.dll", "VERSION", "SHA256SUMS")


def version(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def manifest(root: Path = ROOT) -> list[tuple[str, Path]]:
    """[(nom dans le zip, sans le dossier racine), fichier source]."""
    files = [(name, root / "windows" / name) for name in TOP_FILES]
    files += [("LICENSE", root / "LICENSE"), ("app/LICENSE", root / "LICENSE"), ("app/pyproject.toml", root / "pyproject.toml"),
              ("app/requirements.lock", root / "requirements.lock")]          # empreintes des modules (pip --require-hashes)
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_lock", root / "scripts" / "build_lock.py")
    lock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lock)
    if not lock.is_fresh(root):
        raise FileNotFoundError("requirements.lock absent ou périmé : python scripts/build_lock.py")
    for path in sorted((root / "trxstation").rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not EXCLUDED_PARTS.intersection(rel.parts) and path.suffix not in EXCLUDED_SUFFIXES:
            files.append((f"app/{rel.as_posix()}", path))
    missing = [str(src.relative_to(root)) for _, src in files if not src.is_file()]
    if missing:
        raise FileNotFoundError("fichiers manquants : " + ", ".join(missing))
    return files


def freedv_files(folder: Path) -> list[tuple[str, Path]]:
    """[(nom dans le zip, fichier)] des décodeurs FreeDV ; chaque fichier doit figurer dans SHA256SUMS avec la bonne
    empreinte, et rien d'autre ne doit traîner dans le dossier (sinon ValueError : paquet refusé)."""
    missing = [n for n in FREEDV_REQUIRED if not (folder / n).is_file()]
    if missing:
        raise ValueError(f"décodeurs FreeDV incomplets dans {folder} : {', '.join(missing)}")
    sums: dict[str, str] = {}
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, _, name = line.partition("  ")
            if len(digest) != 64 or not name or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"ligne illisible dans SHA256SUMS : {line!r}")
            sums[name] = digest.lower()
    present = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()} - {"SHA256SUMS"}
    if present != set(sums):
        raise ValueError("SHA256SUMS ne correspond pas au dossier des décodeurs FreeDV : "
                         + ", ".join(sorted(present ^ set(sums))))
    files = []
    for name in sorted(sums):
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != sums[name]:
            raise ValueError(f"empreinte SHA-256 incorrecte : {name} (décodeurs FreeDV)")
        files.append((f"freedv/{name}", folder / name))
    files.append(("freedv/SHA256SUMS", folder / "SHA256SUMS"))
    return files


def content(name: str, source: Path) -> bytes:
    data = source.read_bytes()
    if name.endswith(".ps1") and not data.startswith(BOM):
        data = BOM + data
    if name.endswith((".cmd", ".txt")) and not name.startswith("freedv/"):
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")     # Bloc-notes et cmd.exe : fins de ligne Windows
    return data


def build(out_dir: Path | None = None, root: Path = ROOT, freedv: Path | None = None) -> Path:
    """freedv : dossier des décodeurs FreeDV (None = paquet sans décodeurs)."""
    v = version(root)
    extra = freedv_files(freedv) if freedv is not None else []
    top = f"trx-remote-windows-{v}"
    out_dir = out_dir or root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{top}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, source in manifest(root) + extra:
            archive.writestr(f"{top}/{name}", content(name, source))
        archive.writestr(f"{top}/VERSION", v + "\r\n")
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fabrique dist/trx-remote-windows-X.Y.Z.zip")
    ap.add_argument("--freedv", type=Path, help="décodeurs FreeDV (bash debian/compiler-freedv.sh --windows DOSSIER)")
    args = ap.parse_args(argv)
    folder = args.freedv
    if folder is None and (ROOT / "dist" / "freedv-windows").is_dir():
        folder = ROOT / "dist" / "freedv-windows"
    try:
        target = build(freedv=folder)
    except ValueError as e:
        print(f"Paquet refusé : {e}", file=sys.stderr)
        return 1
    print(f"Paquet Windows créé : {target}")
    if folder is None:
        print("ATTENTION : paquet SANS décodeurs FreeDV (bash debian/compiler-freedv.sh --windows dist/freedv-windows "
              "sur Debian, puis copier le dossier ici)", file=sys.stderr)
    else:
        print(f"Décodeurs FreeDV : {folder} ({(folder / 'VERSION').read_text(encoding='utf-8').splitlines()[0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
