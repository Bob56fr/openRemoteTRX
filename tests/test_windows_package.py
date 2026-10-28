# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Paquet Windows (scripts/build_windows_zip.py, windows/) : contenu, encodages, règles de sécurité de l'installateur,
notice cohérente avec les raccourcis créés."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "windows"
spec = importlib.util.spec_from_file_location("build_windows_zip", ROOT / "scripts" / "build_windows_zip.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

pytestmark = pytest.mark.skipif(not WIN.is_dir(), reason="dépôt seulement (absent du paquet Debian)")


def test_zip_contents_and_encodings(tmp_path):
    target = builder.build(tmp_path)
    version = builder.version()
    top = f"trx-remote-windows-{version}/"
    with zipfile.ZipFile(target) as z:
        names = set(z.namelist())
        for name in ("installer.cmd", "installer.ps1", "notice-windows.html", "LISEZMOI.txt", "LICENSE", "VERSION",
                     "app/pyproject.toml", "app/LICENSE", "app/trxstation/__init__.py",
                     "app/trxstation/gateway/api/static/index.html"):
            assert top + name in names, name
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
        assert not any("/tests/" in n or "deploy_debian" in n for n in names)
        assert z.read(top + "installer.ps1").startswith(b"\xef\xbb\xbf")             # PowerShell 5.1 : accents
        assert b"\r\n" in z.read(top + "installer.cmd") and b"\n" not in z.read(top + "installer.cmd").replace(b"\r\n", b"")
        assert z.read(top + "VERSION").decode().strip() == version


def test_installer_respects_the_safety_and_privacy_rules():
    ps = (WIN / "installer.ps1").read_text(encoding="utf-8")
    profiles = re.findall(r"-Profile\s+(\w+)", ps)
    assert profiles and set(profiles) == {"Private"}                                # jamais Public ni Any
    assert "--stop" in ps and "Stop-Station" in ps                                  # arrêt propre (retour RX) avant de remplacer
    assert "pythonw.exe" in ps and "--log-dir" in ps                                # station sans fenêtre, journaux en fichiers
    assert "/inheritance:r" in ps                                                   # configuration réservée au compte
    assert "-RunLevel Limited" in ps                                                # la station ne tourne pas en administrateur
    assert "WindowsApps" in ps                                                      # jamais l'alias Python du Microsoft Store
    assert "[station]" in ps
    for forbidden in ("Invoke-Expression", "iex ", "DownloadString", "Set-ExecutionPolicy"):
        assert forbidden not in ps, forbidden


def test_notice_describes_every_shortcut_created():
    ps = (WIN / "installer.ps1").read_text(encoding="utf-8")
    notice = (WIN / "notice-windows.html").read_text(encoding="utf-8")
    shortcuts = re.findall(r'New-Shortcut "([^"]+)"', ps)
    assert len(shortcuts) == 9
    for name in shortcuts:
        assert name in notice, name
    assert notice.startswith("<!doctype html>\n<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->")
    assert not re.search(r"<(script|link|img|iframe)\b", notice, re.I)               # notice autonome


@pytest.mark.skipif(sys.platform != "win32", reason="analyse PowerShell : Windows seulement")
def test_installer_script_parses_in_windows_powershell():
    command = ("$e = $null; [System.Management.Automation.Language.Parser]::ParseFile("
               f"'{WIN / 'installer.ps1'}', [ref]$null, [ref]$e) | Out-Null; $e.Count")
    done = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60)
    assert done.stdout.strip() == "0", done.stdout + done.stderr
