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


# Commandes jamais mises dans le PATH (Windows comme Debian) : services lancés par la tâche planifiée ou systemd.
NOT_ON_PATH = {"trx-gateway", "trx-rigctld", "trx-supervisor"}


def _installer_commands() -> list[str]:
    ps = (WIN / "installer.ps1").read_text(encoding="utf-8")
    return re.findall(r'"(trx-[\w-]+)"', re.search(r"^\$Commands = @\(([^)]*)\)", ps, re.M).group(1))


def test_every_useful_command_is_put_on_the_windows_path():
    import tomllib
    declared = set(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"])
    assert NOT_ON_PATH <= declared
    assert set(_installer_commands()) == declared - NOT_ON_PATH       # une nouvelle commande doit être ajoutée ici
    ps = (WIN / "installer.ps1").read_text(encoding="utf-8")
    assert "Remove-Commands" in ps.split("# ------------------------------------------------------------------ désinstallation", 1)[1].split("exit 0", 1)[0]   # retirée à la désinstallation
    assert '"Machine")' not in ps and "LocalMachine" not in ps        # jamais le PATH du système
    assert ps.index("if ($Essai) {") < ps.index("\nInstall-Commands")  # le mode essai ne touche pas au PATH


@pytest.mark.skipif(sys.platform != "win32", reason="relais .cmd : Windows seulement")
def test_command_relays_and_user_path_round_trip(tmp_path):
    base = tmp_path / "TRX distant"
    scripts = base / "versions" / "9.9.9" / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    import os
    import shutil
    shutil.copy(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe", scripts / "trx-netreport.exe")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(base / "current"), str(scripts.parents[1])], check=True,
                   capture_output=True)
    # Fonctions de l'installateur extraites par l'analyseur PowerShell ; registre remplacé par une variable.
    script = rf"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{WIN / 'installer.ps1'}', [ref]$null, [ref]$null)
foreach ($f in $ast.FindAll({{ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }}, $true)) {{
    if (@('Same-Dir', 'Without-BinDir', 'Install-Commands', 'Remove-Commands') -contains $f.Name) {{ . ([scriptblock]::Create($f.Extent.Text)) }}
}}
$Base = '{base}'
$BinDir = Join-Path $Base 'bin'
$Commands = @('trx-netreport', 'trx-console')
$script:FakePath = '%SystemRoot%\system32;C:\Autre;' + $BinDir + '\'
function Get-UserPath {{ return $script:FakePath }}
function Set-UserPath([string]$Value) {{ $script:FakePath = $Value }}
Install-Commands
Write-Output "APRES=$script:FakePath"
Install-Commands
Write-Output "DEUX=$script:FakePath"
& (Join-Path $BinDir 'trx-netreport.cmd') /c exit 7
Write-Output "CODE=$LASTEXITCODE"
$ErrorActionPreference = 'Continue'
& cmd /c (Join-Path $BinDir 'trx-console.cmd') 2>$null
$ErrorActionPreference = 'Stop'
Write-Output "ABSENT=$LASTEXITCODE"
Remove-Commands
Write-Output "RETIRE=$script:FakePath"
Write-Output "BIN=$(Test-Path -LiteralPath $BinDir)"
"""
    done = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, timeout=120)
    out = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line and line.split("=")[0].isupper())
    assert done.returncode == 0, done.stdout + done.stderr
    bin_dir = str(base / "bin")
    assert out["APRES"] == rf"%SystemRoot%\system32;C:\Autre;{bin_dir}"     # %VAR% gardé, doublon retiré, ajouté à la fin
    assert out["DEUX"] == out["APRES"]                                       # réinstallation : rien en double
    assert out["CODE"] == "7"                                                # arguments et code de sortie transmis
    assert out["ABSENT"] == "9009"                                           # version active sans la commande
    assert out["RETIRE"] == r"%SystemRoot%\system32;C:\Autre"
    assert out["BIN"] == "False"
