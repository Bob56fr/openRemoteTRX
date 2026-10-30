# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Paquet d'installation Debian : contenu du zip, cohérence install.sh / units / code."""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from trxstation import console, diagnostics, migrate
from trxstation.config import Supervisor

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "debian" / "install.sh"


def _builder():
    spec = importlib.util.spec_from_file_location("build_debian_zip", ROOT / "scripts" / "build_debian_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_text() -> str:
    return INSTALL.read_text(encoding="utf-8").replace("\r\n", "\n")


def _unit(name: str) -> str:
    return (ROOT / "systemd" / name).read_text(encoding="utf-8")


def test_zip_contains_what_install_needs_and_nothing_private(tmp_path):
    builder = _builder()
    target = builder.build(ROOT, tmp_path)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    prefix = f"trx-remote-debian-{version}/"
    assert target.name == f"trx-remote-debian-{version}.zip"
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert all(n.startswith(prefix) for n in names)
        short = {n[len(prefix):] for n in names}
        for needed in ("install.sh", "LISEZMOI.txt", "compiler-hamlib.sh", "app/pyproject.toml", "app/trxstation/__init__.py",
                       "app/trxstation/console.py", "app/trxstation/gateway/api/static/index.html",
                       "app/trxstation/modules/bus.py", "app/trxstation/modules/builtin/demo/manifest.toml",
                       "app/config/station.example.toml", *[f"systeme/{n}" for n in builder.SYSTEM_FILES]):
            assert needed in short, needed
        assert not any("__pycache__" in n or n.endswith((".pyc", ".pem", ".bak", ".wav")) for n in names)
        assert not any(n.endswith("/station.toml") or "/tls/" in n for n in names)
        assert {"app/tests/test_safety.py", "app/debian/install.sh", "app/systemd/trx-gateway.service",
                "app/LICENSE", "LICENSE"} <= short                                # tests lançables sur la station (menu expert)
        assert not any(n.endswith("deploy_debian.ps1") for n in names)           # script personnel de l'auteur
        script = archive.getinfo(prefix + "install.sh")
        assert (script.external_attr >> 16) & 0o111                          # exécutable
        for name in names:
            if name.endswith((".sh", ".service", ".target", ".py", ".toml", ".desktop", ".rules", ".conf")):
                assert b"\r\n" not in archive.read(name), name                # fins de ligne Linux


def test_text_files_are_converted_to_lf_even_from_a_windows_checkout(tmp_path):
    builder = _builder()
    sample = tmp_path / "install.sh"
    sample.write_bytes(b"#!/bin/bash\r\necho ok\r\n")
    assert builder._content(sample) == b"#!/bin/bash\necho ok\n"


def test_install_script_references_only_shipped_system_files():
    text = _install_text()
    referenced = set(re.findall(r'\$HERE/systeme/([\w.\-]+)', text))
    builder = _builder()
    units = re.search(r"^UNITS=\(([^)]*)\)", text, re.M).group(1).split()
    assert referenced - {"$unit"} <= set(builder.SYSTEM_FILES)
    assert set(units) <= set(builder.SYSTEM_FILES)
    timers = {u for u in units if u.endswith(".timer")}              # tâches périodiques, hors état de la station
    assert set(console.UNITS) | {console.TARGET} == set(units) - timers
    assert set(diagnostics.UNITS) <= set(units)


def test_install_script_is_strict_and_does_not_reuse_os_release_names():
    text = _install_text()
    assert "set -Eeuo pipefail" in text
    assert not re.search(r"^\s*(VERSION|NAME|ID)=", text, re.M)     # /etc/os-release est sourcé : collision
    assert "install -d -m 0755 -o root -g \"$SERVICE_USER\" \"$CONF_DIR\"" in text
    assert "chmod 0640" in text and "--desinstaller" in text and "[station]" in text


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason="bash Linux requis")
def test_install_script_syntax():
    assert subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True).returncode == 0


@pytest.mark.parametrize("name,user", [("rigctld.service", "trx"), ("trx-gateway.service", "trx"),
                                       ("trx-supervisor.service", "root")])
def test_units_share_paths_target_and_guards(name, user):
    text = _unit(name)
    assert f"User={user}" in text
    assert "ExecStart=/opt/trx-remote/venv/bin/python -m trxstation." in text
    assert "--config /etc/trx-remote/station.toml" in text
    assert "ConditionPathExists=/etc/trx-remote/station.toml" in text       # rien ne démarre avant l'assistant
    assert "PartOf=trx-remote.target" in text and "WantedBy=trx-remote.target" in text
    assert re.search(r"RestartPreventExitStatus=.*\b2\b", text)              # config invalide : pas de boucle
    assert "StateDirectory" not in text                                     # dossiers partagés : tmpfiles


def test_gateway_unit_stops_with_sigterm_so_ptt_is_released():
    text = _unit("trx-gateway.service")
    assert "KillSignal=SIGTERM" in text and re.search(r"RestartPreventExitStatus=.*\b5\b", text)


def test_supervisor_unit_keeps_its_watchdog():
    text = _unit("trx-supervisor.service")
    assert "Type=notify" in text and "WatchdogSec=" in text and "Restart=always" in text


def test_unit_names_match_supervisor_defaults():
    defaults = Supervisor()
    assert (ROOT / "systemd" / defaults.gateway_unit).is_file() and (ROOT / "systemd" / defaults.rigctld_unit).is_file()


def test_runtime_directories_match_config_and_import_defaults():
    tmpfiles = (ROOT / "debian" / "trx-remote-tmpfiles.conf").read_text(encoding="utf-8")
    assert f"d {Path(migrate.LINUX_STATUS_PATH).parent.as_posix()} 0755 trx trx" in tmpfiles
    assert f"d {migrate.LINUX_STATE_DIR} 0750 trx trx" in tmpfiles
    example = tomllib.loads((ROOT / "config" / "station.example.toml").read_text(encoding="utf-8"))
    assert example["supervisor"]["status_path"] == migrate.LINUX_STATUS_PATH
    assert example["supervisor"]["state_dir"] == migrate.LINUX_STATE_DIR


def test_pyproject_station_extra_and_console_command():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    station = " ".join(project["optional-dependencies"]["station"])
    for module in ("aiortc", "aiohttp", "sounddevice", "textual", "cryptography"):
        assert module in station
    assert project["scripts"]["trx-console"] == "trxstation.console:main"
    launcher = (ROOT / "debian" / "trx-console.desktop").read_text(encoding="utf-8")
    assert "Exec=trx-console" in launcher and "Terminal=true" in launcher


def test_every_linked_command_exists_and_qualification_is_available():
    script = INSTALL.read_text(encoding="utf-8")
    linked = re.search(r"^COMMANDS=\(([^)]*)\)", script, re.M).group(1).split()
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert set(linked) <= set(declared), set(linked) - set(declared)
    assert "trx-qualif" in linked                                   # qualification d'un poste sur le PC Debian


def test_station_installs_pyserial_for_the_hf_spectrum():
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    for name in ("station", "audio"):                              # Debian (station) et Windows (audio)
        assert any(dep.startswith("pyserial") for dep in extras[name]), name

