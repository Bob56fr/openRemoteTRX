# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""[breizh] de station.toml et fichier de la clé d'appairage (docs/breizh-cahier-des-charges.md § 6)."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.breizh import keyfile, protocol


def problems(**breizh) -> list[str]:
    cfg = cfgmod.Config(rig=cfgmod.Rig(model=1), breizh=cfgmod.Breizh(**breizh))
    return [x for x in cfgmod.validate(cfg) if x.startswith("[breizh]")]


def test_defaults_are_valid_and_disabled():
    assert problems() == []
    b = cfgmod.Breizh()
    assert (b.enabled, b.port, b.block_timeout_ms, b.lost_ms, b.fallback_gain_db, b.reactivate_after_s) == (
        False, 47100, 40, 100, -6.0, 60)


@pytest.mark.parametrize("host", ["192.168.1.50", "10.0.0.2", "172.31.255.1", "169.254.3.4", "127.0.0.1",
                                  "fd12:3456::1", "fe80::1", "::1"])
def test_private_addresses_are_accepted(host):
    assert problems(enabled=True, host=host) == []


@pytest.mark.parametrize("host", ["8.8.8.8", "172.32.0.1", "100.64.0.1", "2001:db8::1", "0.0.0.0", "224.0.0.1",
                                  "breizh.local", "pc-breizh", "192.168.1.50:47100"])
def test_public_addresses_and_names_are_refused(host):
    assert any("host" in x for x in problems(enabled=True, host=host))


def test_enabled_needs_a_host():
    assert any("requise" in x for x in problems(enabled=True))
    assert problems(enabled=False, host="") == []


@pytest.mark.parametrize("field,value", [
    ("port", 80), ("port", 70000), ("port", True), ("block_timeout_ms", 10), ("block_timeout_ms", 101),
    ("lost_ms", 40), ("lost_ms", 501), ("fallback_gain_db", 1), ("fallback_gain_db", -21),
    ("reactivate_after_s", 10), ("reactivate_after_s", 4000), ("reactivate_after_s", 60.5), ("enabled", "yes"),
])
def test_bounds(field, value):
    assert problems(**{field: value})


def test_bounds_limits_accepted():
    assert problems(port=1024, block_timeout_ms=15, lost_ms=500, fallback_gain_db=-20, reactivate_after_s=0) == []
    assert problems(port=65535, block_timeout_ms=100, lost_ms=101, fallback_gain_db=0, reactivate_after_s=3600) == []


def test_lost_must_exceed_block_timeout():
    assert any("lost_ms doit être plus grand" in x for x in problems(block_timeout_ms=100, lost_ms=100))


def test_local_breizh_cannot_take_a_port_of_the_station():
    assert any("déjà pris" in x for x in problems(host="127.0.0.1", port=8443))
    assert problems(host="192.168.1.50", port=8443) == []


def test_render_and_reload_keeps_the_section(tmp_path):
    cfg = cfgmod.Config(rig=cfgmod.Rig(model=1),
                        breizh=cfgmod.Breizh(enabled=True, host="192.168.1.50", port=47200, key_file="cle/breizh.key",
                                             block_timeout_ms=30, lost_ms=120, fallback_gain_db=-9.5,
                                             reactivate_after_s=0))
    text = cfgmod.render_toml(cfg)
    again = cfgmod.from_dict(tomllib.loads(text))
    assert again.breizh == cfg.breizh


def test_unknown_key_is_reported():
    _, found = cfgmod.build({"rig": {"model": 1}, "breizh": {"hote": "x"}})
    assert "[breizh] clé inconnue : hote" in found


def test_key_path(tmp_path):
    cfg = cfgmod.Config()
    station = tmp_path / "station.toml"
    assert cfgmod.breizh_key_path(cfg, station) == tmp_path / "breizh.key"
    cfg.breizh.key_file = "autre.key"
    assert cfgmod.breizh_key_path(cfg, station) == tmp_path / "autre.key"
    cfg.breizh.key_file = str(tmp_path / "x" / "abs.key")
    assert cfgmod.breizh_key_path(cfg, station) == tmp_path / "x" / "abs.key"


def test_key_file_round_trip_and_problems(tmp_path):
    cfg = cfgmod.Config(breizh=cfgmod.Breizh(enabled=True, host="192.168.1.50"))
    station = tmp_path / "station.toml"
    assert "absent" in keyfile.key_problem(cfg, station)
    key = protocol.new_key()
    keyfile.write_key(tmp_path / "breizh.key", key)
    assert keyfile.read_key(tmp_path / "breizh.key") == key
    assert keyfile.key_problem(cfg, station) == ""
    assert not list(tmp_path.glob(".breizh-*"))                              # pas de fichier temporaire oublié
    (tmp_path / "breizh.key").write_text("pas une clé\n", encoding="utf-8")
    problem = keyfile.key_problem(cfg, station)
    assert "mal formée" in problem and "pas une clé" not in problem          # jamais le contenu dans un message
    cfg.breizh.enabled = False
    assert keyfile.key_problem(cfg, station) == ""


@pytest.mark.skipif(os.name != "posix", reason="droits POSIX")
def test_key_readable_by_everyone_is_refused(tmp_path):
    path = tmp_path / "breizh.key"
    keyfile.write_key(path, protocol.new_key())
    assert path.stat().st_mode & 0o077 in (0, 0o040)
    path.chmod(0o644)
    with pytest.raises(keyfile.KeyFileError, match="lisible par tous"):
        keyfile.read_key(path)


def test_example_station_toml_is_still_valid():
    example = Path(__file__).resolve().parents[1] / "config" / "station.example.toml"
    cfgmod.load(example)
