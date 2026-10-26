"""Versions installées côte à côte (/opt/trx-remote/releases) : version active, précédente, retour arrière.

Les essais de releases.sh exigent bash et de vrais liens symboliques : Linux seulement. Les tests de
structure d'install.sh tournent partout.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASES_SH = ROOT / "debian" / "releases.sh"
INSTALL = (ROOT / "debian" / "install.sh").read_text(encoding="utf-8").replace("\r\n", "\n")

linux_only = pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                                reason="bash et liens symboliques Linux requis")


def _sh(app: Path, script: str) -> subprocess.CompletedProcess:
    code = f'set -Eeuo pipefail\nAPP_DIR="{app}"\n. "{RELEASES_SH.as_posix()}"\n{script}'
    return subprocess.run(["bash", "-c", code], capture_output=True, text=True)


def _release(app: Path, version: str, *, venv: bool = True) -> None:
    base = app / "releases" / version
    (base / "app").mkdir(parents=True)
    if venv:
        python = base / "venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)


def _state(app: Path) -> tuple[str | None, str | None, list[str]]:
    link = lambda name: os.readlink(app / name) if (app / name).is_symlink() else None   # noqa: E731
    return link("current"), link("previous"), sorted(p.name for p in (app / "releases").iterdir())


@linux_only
def test_first_install_then_updates_keep_exactly_one_previous(tmp_path):
    app = tmp_path / "opt"
    _release(app, "0.23.0")
    assert _sh(app, "activate_release 0.23.0").returncode == 0
    assert _state(app) == ("releases/0.23.0", None, ["0.23.0"])
    assert os.readlink(app / "venv") == "current/venv" and (app / "venv" / "bin" / "python").exists()
    _release(app, "0.24.0")
    assert _sh(app, "activate_release 0.24.0").returncode == 0
    assert _state(app) == ("releases/0.24.0", "releases/0.23.0", ["0.23.0", "0.24.0"])
    _release(app, "0.25.0")
    assert _sh(app, "activate_release 0.25.0").returncode == 0
    assert _state(app) == ("releases/0.25.0", "releases/0.24.0", ["0.24.0", "0.25.0"])   # 0.23.0 retirée


@linux_only
def test_going_back_swaps_active_and_previous(tmp_path):
    app = tmp_path / "opt"
    for version in ("0.23.0", "0.24.0"):
        _release(app, version)
        assert _sh(app, f"activate_release {version}").returncode == 0
    assert _sh(app, "activate_release 0.23.0").returncode == 0
    assert _state(app) == ("releases/0.23.0", "releases/0.24.0", ["0.23.0", "0.24.0"])
    assert _sh(app, "release_of \"$CURRENT_LINK\"").stdout.strip() == "0.23.0"


@linux_only
def test_reactivating_the_active_version_keeps_the_previous(tmp_path):
    app = tmp_path / "opt"
    for version in ("0.23.0", "0.24.0", "0.24.0"):
        if not (app / "releases" / version).exists():
            _release(app, version)
        assert _sh(app, f"activate_release {version}").returncode == 0
    assert _state(app) == ("releases/0.24.0", "releases/0.23.0", ["0.23.0", "0.24.0"])


@linux_only
def test_release_without_python_is_never_activated(tmp_path):
    app = tmp_path / "opt"
    _release(app, "0.23.0")
    _sh(app, "activate_release 0.23.0")
    _release(app, "0.24.0", venv=False)
    assert _sh(app, "activate_release 0.24.0").returncode != 0
    assert _state(app) == ("releases/0.23.0", None, ["0.23.0", "0.24.0"])


@linux_only
@pytest.mark.parametrize("version", ["../x", "", "0.23.0/..", "-rf", "a b"])
def test_dangerous_version_names_are_refused(tmp_path, version):
    app = tmp_path / "opt"
    _release(app, "0.23.0")
    _sh(app, "activate_release 0.23.0")
    assert _sh(app, f'activate_release "{version}"').returncode != 0
    assert _state(app)[0] == "releases/0.23.0"


@linux_only
def test_legacy_layout_is_replaced_by_links(tmp_path):
    app = tmp_path / "opt"
    (app / "venv" / "bin").mkdir(parents=True)
    (app / "app").mkdir()
    assert _sh(app, "legacy_layout").returncode == 0
    _release(app, "0.23.0")
    assert _sh(app, "activate_release 0.23.0").returncode == 0
    assert (app / "venv").is_symlink() and not (app / "app").exists()
    assert _sh(app, "legacy_layout").returncode != 0


@linux_only
def test_prune_without_active_version_deletes_nothing(tmp_path):
    app = tmp_path / "opt"
    _release(app, "0.23.0")
    _release(app, "0.24.0")
    assert _sh(app, "prune_releases").returncode == 0
    assert _state(app)[2] == ["0.23.0", "0.24.0"]


# ------------------------------------------------------------------ structure d'install.sh (toutes plateformes)

def test_install_script_uses_the_release_layout():
    assert '. "$HERE/releases.sh"' in INSTALL
    assert 'rm -rf "$SRC_DIR"' not in INSTALL                          # l'ancienne version n'est plus effacée
    assert 'RELEASE=$RELEASES/$TRX_VERSION' in INSTALL
    assert 'activate_release "$TRX_VERSION"' in INSTALL
    assert 'valid_version "$TRX_VERSION"' in INSTALL
    # Seuls les fichiers du paquet sont copiés : jamais une station.toml posée à côté d'install.sh.
    assert 'cp -r "$HERE/app" "$HERE/systeme" "$RELEASE/"' in INSTALL
    assert not re.search(r'cp -r "\$HERE"/?\s', INSTALL) and 'cp -r "$HERE/"' not in INSTALL


def test_failed_update_leaves_the_active_version_and_restarts_it():
    assert "trap on_exit EXIT" in INSTALL
    body = INSTALL.split("on_exit() {", 1)[1].split("\n}\n", 1)[0]
    assert 'rm -rf "${RELEASES:?}/$TRX_VERSION"' in body and "BUILDING" in body
    assert "systemctl start trx-remote.target" in body and "config_loads" in body
    # L'activation (bascule des liens) vient APRÈS la vérification des modules Python.
    assert INSTALL.index("modules Python incomplets") < INSTALL.rindex('activate_release "$TRX_VERSION" ||')


def test_rollback_option_reuses_installed_version_without_network():
    body = INSTALL.split("reactivate() {", 1)[1].split("\n}\n", 1)[0]
    assert '[[ $HERE == "$RELEASES/$TRX_VERSION" ]]' in body
    for forbidden in ("apt-get", "pip install", "getent hosts"):
        assert forbidden not in body
    assert "station.toml.avant-$left" in body and "install_services" in body
    assert "--reactiver) MODE=reactivate" in INSTALL
    assert INSTALL.index("reactivate; exit 0") < INSTALL.index('step "1/8 Vérifications"')


def test_config_backup_is_protected_like_station_toml():
    body = INSTALL.split("backup_config_for() {", 1)[1].split("\n}\n", 1)[0]
    assert 'chown root:"$SERVICE_USER"' in body and "chmod 0640" in body


def test_units_still_use_the_stable_venv_path():
    for unit in ("rigctld.service", "trx-gateway.service", "trx-supervisor.service", "trx-update-check.service"):
        assert "ExecStart=/opt/trx-remote/venv/bin/python -m" in (ROOT / "systemd" / unit).read_text(encoding="utf-8")
    assert "VENV=$APP_DIR/venv" in RELEASES_SH.read_text(encoding="utf-8")


def test_zip_ships_releases_script(tmp_path):
    spec = importlib.util.spec_from_file_location("build_debian_zip", ROOT / "scripts" / "build_debian_zip.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    target = builder.build(ROOT, tmp_path)
    with zipfile.ZipFile(target) as archive:
        info = archive.getinfo(f"{target.stem}/releases.sh")
        assert b"\r\n" not in archive.read(info)
