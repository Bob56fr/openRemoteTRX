# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fichier d'empreintes des modules Python de la station : requirements.lock (pip --require-hashes).

    python scripts/build_lock.py            # régénère requirements.lock (uv, réseau)
    python scripts/build_lock.py --check    # vérifie seulement qu'il correspond à pyproject.toml (sans réseau)

Résolution UNIVERSELLE par uv (Linux amd64, Raspberry Pi arm64, Windows amd64 ; Python 3.11 et plus) : versions exactes
et empreintes SHA-256 de tous les fichiers publiés de chaque version. install.sh et installer.ps1 installent avec
`pip install --require-hashes -r requirements.lock`, puis l'application seule (`--no-deps --no-build-isolation`) ;
setuptools et wheel (construction de l'application) sont dans le fichier, vérifiés eux aussi.
Limite connue (documentée, décision de l'utilisateur du 2026-11-09) : un module SANS fichier précompilé pour la
plateforme est compilé, et les outils de compilation que pip télécharge alors ne sont pas vérifiés par empreinte.
À relancer après tout changement des dépendances de pyproject.toml (les tests et les fabrications le rappellent).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock"
EXTRAS = ("station", "tray")
BUILD_TOOLS = ("setuptools>=68", "wheel")
PYTHON_MIN = "3.11"
HEADER = "# requirements-sha256: "


def inputs_digest(root: Path = ROOT) -> str:
    """Empreinte de ce qui détermine le fichier : extras installés, outils de construction, Python minimal."""
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    payload = {"extras": {name: sorted(extras[name]) for name in EXTRAS},
               "build": sorted(data["build-system"]["requires"]) + sorted(BUILD_TOOLS),
               "python": data["project"]["requires-python"]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def lock_digest(lock: Path = LOCK) -> str | None:
    try:
        first = lock.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    return first[len(HEADER):].strip() if first.startswith(HEADER) else None


def is_fresh(root: Path = ROOT) -> bool:
    return lock_digest(root / "requirements.lock") == inputs_digest(root)


def build(root: Path = ROOT) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        tools = Path(tmp) / "build-tools.in"
        tools.write_text("\n".join(BUILD_TOOLS) + "\n", encoding="utf-8")
        out = Path(tmp) / "requirements.lock"
        cmd = [sys.executable, "-m", "uv", "pip", "compile", str(root / "pyproject.toml"), str(tools),
               *[f"--extra={e}" for e in EXTRAS], "--universal", "--generate-hashes", "--python-version", PYTHON_MIN,
               "--no-header", "--no-annotate", "--quiet", "-o", str(out)]
        subprocess.run(cmd, check=True, cwd=root)
        body = out.read_text(encoding="utf-8").replace("\r\n", "\n")
    text = (f"{HEADER}{inputs_digest(root)}\n"
            "# Modules Python de la station, versions exactes et empreintes SHA-256 (pip --require-hashes).\n"
            "# Fabriqué par : python scripts/build_lock.py (uv, résolution universelle). Ne pas modifier à la main.\n"
            + body)
    target = root / "requirements.lock"
    target.write_bytes(text.encode("utf-8"))           # LF partout : le fichier part aussi sous Linux
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="vérifie seulement que requirements.lock est à jour")
    args = ap.parse_args(argv)
    if args.check:
        if is_fresh():
            print("requirements.lock à jour.")
            return 0
        print("requirements.lock absent ou périmé : python scripts/build_lock.py", file=sys.stderr)
        return 1
    try:
        path = build()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Fabrication impossible ({exc}) : uv installé (python -m pip install uv) et accès à PyPI ?", file=sys.stderr)
        return 1
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith((" ", "#")))
    print(f"Écrit : {path} ({count} modules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
