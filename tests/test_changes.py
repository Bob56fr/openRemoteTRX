# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Changements par poste (étape 407) : fichier livré valide, filtrage par modèle et par marque, menu 7.4."""
from __future__ import annotations

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
    con, _, out = console(tmp_path, answers=["n"])
    con.changes()
    text = "\n".join(out)
    assert "1042" in text and "★" in text and "0.285.0" in text and "Console Web" not in text
