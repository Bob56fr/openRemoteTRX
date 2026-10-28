# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Indicateur GNOME (barre du haut) : champs lus = champs publiés par la station, lecture seule, paquet et installation,
menu 17 de TRX Console."""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

from trxstation import console as con_mod
from trxstation.gateway.cat.link import RigState
from trxstation.gateway.safety.ptt import PttSnapshot
from trxstation.status import GatewayStatus

from test_console_tools import make

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "debian" / "gnome-extension"


def test_fields_read_by_the_indicator_are_published_by_the_station():
    status_js = (EXT / "status.js").read_text(encoding="utf-8")
    fields = {
        "ptt": {f.name for f in dataclasses.fields(PttSnapshot)},
        "rig": {f.name for f in dataclasses.fields(RigState)},
        "status": {f.name for f in dataclasses.fields(GatewayStatus)},
    }
    for obj, known in fields.items():
        used = set(re.findall(rf"\b{obj}\.([a-z_]+)\b", status_js))
        assert used and used <= known, (obj, used - known)


def test_extension_is_read_only_and_declares_supported_shells():
    meta = json.loads((EXT / "metadata.json").read_text(encoding="utf-8"))
    assert meta["uuid"] == con_mod.GNOME_EXTENSION_UUID and "48" in meta["shell-version"]
    code = (EXT / "extension.js").read_text(encoding="utf-8") + (EXT / "status.js").read_text(encoding="utf-8")
    for forbidden in ("replace_contents", "set_contents", "rigctl", "4532", "8765", "WebSocket", "Soup", "unlink", "delete("):
        assert forbidden not in code, forbidden                        # aucune écriture, aucune commande, aucun réseau
    for path in ("/run/trx-remote/gateway-status.json", "/var/lib/trx-remote/safe_mode", "/var/lib/trx-remote/station-id"):
        assert path in code


def test_package_ships_and_installer_installs_the_extension():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_debian_zip", ROOT / "scripts" / "build_debian_zip.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    SYSTEM_FILES = builder.SYSTEM_FILES
    shipped = {name for name in SYSTEM_FILES if name.startswith("gnome-extension/")}
    assert shipped == {f"gnome-extension/{p.name}" for p in EXT.iterdir() if p.is_file()}
    install = (ROOT / "debian" / "install.sh").read_text(encoding="utf-8")
    assert "GNOME_EXT_DIR=/usr/share/gnome-shell/extensions/trx-distant@rf-diy.com" in install
    assert install.count('rm -rf "$GNOME_EXT_DIR"') == 2                    # installation (remplacement) et désinstallation


class Gnome:
    def __init__(self, known=True, enabled=False):
        self.known, self.enabled = known, enabled

    def output(self, cmd):
        if cmd[1:] == ["list"]:
            return "ding@rastersoft.com\ntrx-distant@rf-diy.com\n" if self.known else "ding@rastersoft.com\n"
        if cmd[1:] == ["list", "--enabled"]:
            return "trx-distant@rf-diy.com\n" if self.enabled else ""
        return ""


def console_with_gnome(tmp_path, monkeypatch, answers, gnome, installed=True):
    folder = tmp_path / ("ext" if installed else "absent")
    if installed:
        folder.mkdir(exist_ok=True)
    monkeypatch.setattr(con_mod, "GNOME_EXTENSION_DIR", folder)
    monkeypatch.setattr(con_mod.shutil, "which", lambda name: "/usr/bin/gnome-extensions" if name == "gnome-extensions" else None)
    con, fake, out = make(tmp_path, answers=answers)
    fake.output = gnome.output
    return con, fake, out


def test_menu_17_enables_then_disables(tmp_path, monkeypatch):
    con, fake, out = console_with_gnome(tmp_path, monkeypatch, ["OUI"], Gnome())
    con.indicator()
    assert (["/usr/bin/gnome-extensions", "enable", "trx-distant@rf-diy.com"], False) in fake.calls   # sans sudo
    assert any("ne peut rien commander" in line for line in out)
    con, fake, out = console_with_gnome(tmp_path, monkeypatch, ["o"], Gnome(enabled=True))
    con.indicator()
    assert fake.calls[-1][0][1] == "disable"


def test_menu_17_explains_relogin_missing_install_and_other_desktops(tmp_path, monkeypatch):
    con, fake, out = console_with_gnome(tmp_path, monkeypatch, [], Gnome(known=False))
    con.indicator()
    assert "reconnecte-toi" in out[-1] and fake.calls == []
    con, fake, out = console_with_gnome(tmp_path, monkeypatch, [], Gnome(), installed=False)
    con.indicator()
    assert "0.49.0" in out[-1]
    monkeypatch.setattr(con_mod.shutil, "which", lambda name: None)
    con.indicator()
    assert "GNOME" in out[-1]
