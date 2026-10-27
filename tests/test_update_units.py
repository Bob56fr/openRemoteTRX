# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Timer systemd de recherche de mise à jour : compte trx, jamais root, intégré au zip et à install.sh."""
from __future__ import annotations

import importlib.util
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "systemd" / "trx-update-check.service").read_text(encoding="utf-8")
TIMER = (ROOT / "systemd" / "trx-update-check.timer").read_text(encoding="utf-8")
INSTALL = (ROOT / "debian" / "install.sh").read_text(encoding="utf-8").replace("\r\n", "\n")


def _builder():
    spec = importlib.util.spec_from_file_location("build_debian_zip", ROOT / "scripts" / "build_debian_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_service_runs_unprivileged_and_only_reads():
    assert "User=trx" in SERVICE and "User=root" not in SERVICE
    assert "Type=oneshot" in SERVICE and "NoNewPrivileges=true" in SERVICE
    assert "ProtectSystem=strict" in SERVICE and "ReadWritePaths=/var/lib/trx-remote" in SERVICE
    assert "ExecStart=/opt/trx-remote/venv/bin/python -m trxstation.update.check " \
           "--config /etc/trx-remote/station.toml" in SERVICE
    assert "ConditionPathExists=/etc/trx-remote/station.toml" in SERVICE
    assert "[Install]" not in SERVICE                      # jamais lancé autrement que par le timer
    assert importlib.util.find_spec("trxstation.update.check") is not None


def test_timer_runs_at_start_then_every_day_with_the_station():
    assert "Unit=trx-update-check.service" in TIMER
    assert re.search(r"^OnActiveSec=\S+", TIMER, re.M) and "OnUnitActiveSec=24h" in TIMER
    assert "WantedBy=trx-remote.target" in TIMER and "PartOf=trx-remote.target" in TIMER


def test_install_script_installs_enables_and_removes_the_timer():
    units = re.search(r"^UNITS=\((.*)\)", INSTALL, re.M).group(1).split()
    helpers = re.search(r"^HELPER_UNITS=\((.*?)\)", INSTALL, re.M).group(1).split()
    assert "trx-update-check.timer" in units and helpers == ["trx-update-check.service"]
    assert 'for unit in "${UNITS[@]}" "${HELPER_UNITS[@]}"; do install' in INSTALL
    assert 'for unit in "${HELPER_UNITS[@]}"; do rm -f' in INSTALL
    for unit in units + helpers:
        assert (ROOT / "systemd" / unit).is_file()


def test_zip_ships_both_units_with_linux_line_endings(tmp_path):
    builder = _builder()
    target = builder.build(ROOT, tmp_path)
    with zipfile.ZipFile(target) as archive:
        prefix = target.stem + "/systeme/"
        for name in ("trx-update-check.service", "trx-update-check.timer"):
            assert b"\r\n" not in archive.read(prefix + name)
