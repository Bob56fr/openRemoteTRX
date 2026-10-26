"""Section [update] de station.toml : valeurs par défaut, validation, conservation."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation import migrate

ROOT = Path(__file__).resolve().parents[1]


def _base() -> dict:
    return {"rig": {"model": cfgmod.DUMMY_MODEL}}


def test_defaults_check_for_updates_but_ignore_prereleases():
    cfg = cfgmod.from_dict(_base())
    assert cfg.update.enabled is True and cfg.update.allow_prerelease is False


def test_section_is_written_and_read_back():
    cfg = cfgmod.from_dict(_base() | {"update": {"enabled": False, "allow_prerelease": True}})
    text = cfgmod.render_toml(cfg)
    assert "[update]" in text
    again = cfgmod.from_dict(tomllib.loads(text))
    assert (again.update.enabled, again.update.allow_prerelease) == (False, True)


@pytest.mark.parametrize("value", ["false", 0, 1, "oui"])
def test_non_boolean_values_are_refused(value):
    with pytest.raises(cfgmod.ConfigError, match=r"\[update\] allow_prerelease"):
        cfgmod.from_dict(_base() | {"update": {"allow_prerelease": value}})


def test_unknown_key_is_refused():
    with pytest.raises(cfgmod.ConfigError, match=r"\[update\] clé inconnue : interval"):
        cfgmod.from_dict(_base() | {"update": {"interval": 3}})


def test_import_from_another_pc_keeps_the_choice():
    source = cfgmod.from_dict(_base() | {"update": {"enabled": False, "allow_prerelease": True}})
    cfg, _ = migrate.import_config(source, desktop=True)
    assert (cfg.update.enabled, cfg.update.allow_prerelease) == (False, True)


def test_example_file_documents_the_section():
    data = tomllib.loads((ROOT / "config" / "station.example.toml").read_text(encoding="utf-8"))
    assert data["update"] == {"enabled": True, "allow_prerelease": False}
