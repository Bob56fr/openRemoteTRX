# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Changements par poste (étape 407) : fichier livré valide, filtrage par modèle et par marque, menu 7.4."""
from __future__ import annotations

import json

import pytest

from trxstation import __version__, changes
from trxstation.changes import ChangesError, for_model, load, parse, version_key


def test_the_shipped_file_is_valid_and_its_newest_entry_is_the_current_version():
    known = load()
    assert known and known[0].version == __version__, "ajouter l'entrée de la version courante dans changes.toml"
    assert all(version_key(c.version) <= version_key(__version__) for c in known)
    dates = [c.date for c in known]
    assert dates == sorted(dates, reverse=True)


def entry(**over):
    e = {"date": "2026-11-28", "version": "1.2.3", "type": "correctif", "postes": ["*"],
         "fr": "a", "en": "b", "de": "c", "es": "d"}
    e.update(over)
    return e


def test_filtering_by_model_brand_and_common_changes():
    known = parse({"change": [entry(postes=["3094"], fr="mk2"), entry(postes=["icom"], fr="icom"),
                              entry(postes=["yaesu"], fr="yaesu"), entry(fr="tous")]})
    assert [c.text("fr") for c in for_model(known, 3094)] == ["mk2", "icom", "tous"]
    assert [c.text("fr") for c in for_model(known, 3085, common=False)] == ["icom"]
    assert [c.text("fr") for c in for_model(known, 1042, common=False)] == ["yaesu"]
    assert for_model(known, 2014, common=False) == []
    assert len(for_model(parse({"change": [entry()] * 80}), 3094)) == changes.LIMIT


@pytest.mark.parametrize("bad", [{"type": "autre"}, {"postes": []}, {"postes": ["IC-7300"]}, {"date": "28/11"},
                                 {"version": "1.2"}, {"es": ""}, {"de": "x" * 400}])
def test_a_bad_entry_refuses_the_whole_file(bad):
    with pytest.raises(ChangesError):
        parse({"change": [entry(), entry(**bad)]})


def test_menu_shows_the_table_for_the_rig_of_the_station(tmp_path):
    from test_console import console
    from trxstation import config as cfgmod
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.rig.model = 1042
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    con, _, out = console(tmp_path, answers=["", "n"])
    con.changes()
    text = "\n".join(out)
    assert "1042" in text and "★" in text and "0.285.0" in text and "Console Web" not in text


def test_the_published_copy_is_up_to_date():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("build_changes_doc", root / "scripts" / "build_changes_doc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.OUTPUT.read_bytes() == mod.render(), "relancer python scripts/build_changes_doc.py"
    assert changes.parse_public(mod.render()) == load()


def test_update_check_keeps_the_downloaded_list_and_refuses_a_bad_one(tmp_path):
    from trxstation.update.check import CheckError, fetch_changes
    good = json.dumps(changes.to_public(parse({"change": [entry(version="9.9.9", postes=["icom"], fr="futur")]})))
    assert fetch_changes(tmp_path, lambda url: good.encode()) is True
    assert [c.version for c in changes.load_cached(tmp_path)] == ["9.9.9"]
    assert fetch_changes(tmp_path, lambda url: b'{"schema": 1, "change": [{"date": "x"}]}') is False
    def offline(url):
        raise CheckError("injoignable")
    assert fetch_changes(tmp_path, offline) is False
    assert [c.version for c in changes.load_cached(tmp_path)] == ["9.9.9"]       # ancienne copie gardée
    (tmp_path / "update" / "changes.json").write_text("abîmé", encoding="utf-8")
    assert changes.load_cached(tmp_path) == []


def test_menus_show_the_coming_changes_of_the_downloaded_list(tmp_path):
    from test_console import console
    from trxstation import config as cfgmod
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.rig.model = 3094
    cfg.supervisor.state_dir = str(tmp_path / "state")
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    cache = changes.cache_path(cfg.supervisor.state_dir)
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps(changes.to_public(parse({"change": [
        entry(version="99.0.0", date="2099-01-01", postes=["3094"], fr="nouveau filtre"),
        entry(version="99.0.0", date="2099-01-01", postes=["1042"], fr="autre poste")]}))), encoding="utf-8")
    con, _, out = console(tmp_path, answers=["", "o"])
    con.changes()
    text = "\n".join(out)
    assert "[à venir] nouveau filtre" in text and "autre poste" not in text
    out.clear()
    con._update_rig_changes("99.0.0")
    text = "\n".join(out)
    assert "Ce que cette mise à jour change pour ton poste (1)" in text and "nouveau filtre" in text
    assert "7.4" in text
