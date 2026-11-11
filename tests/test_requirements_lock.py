# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Empreintes des modules Python (requirements.lock, pip --require-hashes) : fichier à jour, complet, utilisé par les
deux installateurs, présent dans les deux paquets."""
from __future__ import annotations

import importlib.util
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock"
spec = importlib.util.spec_from_file_location("build_lock", ROOT / "scripts" / "build_lock.py")
build_lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_lock)

pytestmark = pytest.mark.skipif(not (ROOT / "scripts" / "build_lock.py").is_file(), reason="dépôt seulement")


def _pinned() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line[:1].isalpha() and "==" in line:
            name, rest = line.split("==", 1)
            out.setdefault(name.lower().replace("_", "-"), []).append(rest.split()[0].rstrip(";"))
    return out


def test_lock_matches_pyproject():
    assert build_lock.is_fresh(), "requirements.lock périmé : python scripts/build_lock.py"


def test_every_requirement_is_pinned_and_hashed():
    text = LOCK.read_text(encoding="utf-8")
    assert b"\r" not in LOCK.read_bytes()                                       # LF : le fichier part aussi sous Linux
    pinned = _pinned()
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    for req in extras["station"] + extras["tray"] + ["setuptools", "wheel"]:
        name = req.split(";")[0].split(">")[0].split("=")[0].split("[")[0].strip().lower()
        assert name in pinned, name
    blocks = [b for b in text.splitlines() if b[:1].isalpha()]
    assert blocks and all(b.endswith("\\") for b in blocks)                   # chaque module suivi de ses empreintes
    assert text.count("--hash=sha256:") >= len(blocks)
    for name in ("pystray", "pillow"):                                        # indicateur : Windows seulement
        line = next(b for b in blocks if b.lower().startswith(name + "=="))
        assert "sys_platform == 'win32'" in line


def test_both_installers_use_the_hashes_then_the_app_without_dependencies():
    sh = (ROOT / "debian" / "install.sh").read_text(encoding="utf-8")
    ps = (ROOT / "windows" / "installer.ps1").read_text(encoding="utf-8-sig")
    for text in (sh, ps):
        assert "--require-hashes -r" in text and "--no-deps --no-build-isolation" in text
        assert "--upgrade pip" not in text                                    # pip lui-même n'est plus téléchargé
        assert "app[station" not in text and "[station,tray]" not in text      # plus aucune résolution libre


def test_packages_carry_the_lock(tmp_path):
    for script, prefix in (("build_windows_zip.py", "trx-remote-windows-"),):
        spec = importlib.util.spec_from_file_location(script[:-3], ROOT / "scripts" / script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert ("app/requirements.lock", LOCK) in mod.manifest()
    spec = importlib.util.spec_from_file_location("build_debian_zip", ROOT / "scripts" / "build_debian_zip.py")
    deb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deb)
    assert ("app/requirements.lock", LOCK) in deb.manifest()


def test_a_stale_lock_is_refused(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text(encoding="utf-8").replace(
        '"numpy>=1.24"]', '"numpy>=1.25"]'), encoding="utf-8")
    (tmp_path / "requirements.lock").write_bytes(LOCK.read_bytes())
    assert not build_lock.is_fresh(tmp_path)


def test_installers_tell_a_hash_mismatch_ort_9311_from_other_failures_ort_9308():
    """Empreinte différente = ORT-9311 (critique, ne jamais contourner) ; autre échec de pip = ORT-9308. La phrase
    cherchée dans le compte-rendu de pip (`--log`) est celle de pip lui-même."""
    import os

    import pip
    marker = "DO NOT MATCH THE HASHES"
    source = Path(os.path.dirname(pip.__file__)) / "_internal" / "exceptions.py"
    assert marker in " ".join(source.read_text(encoding="utf-8").replace('"\n', "").split()), "message de pip changé"
    sh = (ROOT / "debian" / "install.sh").read_text(encoding="utf-8")
    ps = (ROOT / "windows" / "installer.ps1").read_text(encoding="utf-8-sig")
    for text in (sh, ps):
        assert "--log" in text and marker in text
        assert text.index("ORT-9311") < text.index("ORT-9308")       # l'empreinte est examinée d'abord
        assert "erreurs/ORT-9311/" in text and "erreurs/ORT-9308/" in text
