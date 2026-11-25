# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Console (étape 400) : fiche technique du poste au menu 2.5, ligne « Squelch » du tableau de bord 1.3 / trx-monitor
quand l'état est lu sur le poste (et seulement alors)."""
from __future__ import annotations

import re

from test_console import console, write_config
from test_monitor import panel, row, snap, status


def test_menu_2_5_shows_the_technical_sheet_of_the_rig(tmp_path):
    write_config(tmp_path)
    path = tmp_path / "station.toml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^model = 1\b", "model = 1042", text, count=1)
    path.write_text(re.sub(r'(?m)^port = ""', 'port = "/dev/ttyUSB0"', text, count=1), encoding="utf-8")
    con, _, out = console(tmp_path)
    con._show_rig_spec()
    shown = "\n".join(out)
    assert "Yaesu FTDX10" in shown and "d'après le manuel" in shown and "+4 s" in shown
    assert "paliers" in shown and "occupé" in shown and "mémoire par bande" in shown


def test_generic_rig_and_missing_configuration(tmp_path):
    con, _, out = console(tmp_path)
    con._show_rig_spec()                                           # pas de station.toml : rien, jamais d'erreur
    assert out == []
    write_config(tmp_path)
    con, _, out = console(tmp_path)
    con._show_rig_spec()
    assert "poste générique" in "\n".join(out)


def test_dashboard_squelch_row_only_when_read_from_the_rig():
    st = status()
    assert not any(r.label == "Squelch" for r in panel(snap(st), "radio").rows)
    st.rig["dcd"] = True
    assert (row(panel(snap(st), "radio"), "Squelch").text, row(panel(snap(st), "radio"), "Squelch").level) == \
        ("ouvert (signal, lu sur le poste)", "ok")
    st.rig["dcd"] = False
    assert row(panel(snap(st), "radio"), "Squelch").text == "fermé (lu sur le poste)"
