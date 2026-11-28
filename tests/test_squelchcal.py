# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Étalonnage du squelch (étape 411) : validation, priorité station / modèle, interpolation, export, station.toml."""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace

import pytest

from trxstation import config as cfgmod
from trxstation import rigspec, squelchcal

POINTS = [0.12, 0.16, 0.20, 0.25, 0.29, 0.33, 0.38, 0.42, 0.47, 0.54]


def test_problem_refuses_wrong_count_range_and_order():
    assert squelchcal.problem(POINTS) is None
    assert squelchcal.problem(POINTS[:9]) is not None
    assert squelchcal.problem([*POINTS[:9], 1.2]) is not None
    assert squelchcal.problem([*POINTS[:8], 0.42, 0.42]) is not None       # pas strictement croissant
    assert squelchcal.problem([True] * 10) is not None


def test_to_db_interpolates_like_the_clients():
    assert squelchcal.to_db(0, POINTS) is None
    assert squelchcal.to_db(0.12, POINTS) == pytest.approx(-48)              # S1
    assert squelchcal.to_db(0.47, POINTS) == pytest.approx(0)                # S9
    assert squelchcal.to_db(0.54, POINTS) == pytest.approx(10)               # S9+10
    assert squelchcal.to_db(0.06, POINTS) == pytest.approx(-51)              # entre S0 (SQL 0) et S1
    assert squelchcal.to_db(0.18, POINTS) == pytest.approx(-39)              # milieu de S2-S3
    assert squelchcal.to_db(1.0, POINTS) == pytest.approx(60)                # plafond S9+60


def _cfg(model=3094, points=None, cal_model=3094):
    from types import SimpleNamespace
    return SimpleNamespace(rig=SimpleNamespace(model=model),
                           squelch_cal=cfgmod.SquelchCal(model=cal_model, points=list(points or [])))


def test_effective_prefers_the_station_then_the_model():
    spec_with = replace(rigspec.RigSpec(), squelch=replace(rigspec.Squelch(), calibration=tuple(p + 0.01 for p in POINTS)))
    own = squelchcal.effective(_cfg(points=POINTS), spec_with)
    assert own["source"] == "station" and own["points"] == POINTS and own["levels_db"][-1] == 10
    other_rig = squelchcal.effective(_cfg(points=POINTS, cal_model=1042), spec_with)
    assert other_rig["source"] == "model"
    assert squelchcal.effective(_cfg(), rigspec.RigSpec()) is None


def test_rigspec_accepts_a_model_table_and_refuses_a_bad_one():
    base = "format = 1\nmodel = 1\nname = \"essai\"\n[squelch]\nsource = \"estimate\"\n"
    spec = rigspec.parse(base + "calibration = [" + ", ".join(map(str, POINTS)) + "]\n")
    assert list(spec.squelch.calibration) == POINTS
    with pytest.raises(rigspec.RigSpecError):
        rigspec.parse(base + "calibration = [0.5, 0.4]\n")


def test_station_toml_round_trip_and_validation(tmp_path):
    example = cfgmod.load_unchecked(_example())[0]
    example.squelch_cal = cfgmod.SquelchCal(model=example.rig.model, points=POINTS)
    text = cfgmod.render_toml(example)
    path = tmp_path / "station.toml"
    path.write_text(text, encoding="utf-8")
    again = cfgmod.load(path)
    assert again.squelch_cal.points == POINTS and again.squelch_cal.model == example.rig.model
    path.write_text(text.replace("points = [0.1200", "points = [0.9000"), encoding="utf-8")
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(path)


def test_export_has_no_serial_number_nor_address():
    raw = squelchcal.export_zip(3094, "IC-7300MK2", POINTS, "4.7.2", now=0)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        data = json.loads(z.read("squelch-calibration.json"))
        assert set(z.namelist()) == {"squelch-calibration.json", "rigspec-extrait.toml"}
        assert "calibration = [0.1200" in z.read("rigspec-extrait.toml").decode()
    assert data["model"] == 3094 and data["points"] == POINTS and data["labels"][-1] == "9+10"


def _example():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "config" / "station.example.toml"
