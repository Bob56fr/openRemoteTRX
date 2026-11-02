# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mesure de TOS, calculs purs (docs/tos-cahier-des-charges.md § 5) : exemples partagés avec la page et l'application."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from trxstation.config import DEFAULT_BANDS_R1
from trxstation.swr import plan as p

SHARED = json.loads((Path(__file__).parent / "protocol" / "swr_plans.json").read_text(encoding="utf-8"))


def test_shared_band_table_and_steps_are_the_station_ones():
    assert SHARED["bands"] == [asdict(b) for b in p.BANDS]
    assert SHARED["nice_steps_hz"] == list(p.NICE_STEPS_HZ)
    assert SHARED["grid"] == list(p.GRID)
    amateur = {b.name: (b.low_hz, b.high_hz) for b in p.BANDS if b.kind == "amateur"}
    for band in DEFAULT_BANDS_R1:                                       # mêmes limites que la table proposée par trx-setup
        assert amateur[band.name] == (round(band.low_mhz * 1e6), round(band.high_mhz * 1e6))


@pytest.mark.parametrize("case", SHARED["plans"], ids=lambda c: f"{c['low_hz']}-{c['high_hz']}-{c['points']}")
def test_plans(case):
    if "error" in case:
        with pytest.raises(p.PlanError) as err:
            p.plan(case["low_hz"], case["high_hz"], case["points"], case["max_points"])
        assert err.value.code == case["error"]
    else:
        got = p.plan(case["low_hz"], case["high_hz"], case["points"], case["max_points"])
        assert {k: got[k] for k in ("step_hz", "freqs", "amateur_only")} == case["expect"]


def test_center_band_scale_and_levels():
    for c in SHARED["center"]:
        assert p.range_from_center(c["center_hz"], c["width_hz"]) == (c["low_hz"], c["high_hz"])
    for c in SHARED["band_at"]:
        b = p.band_at(c["hz"])
        assert (b.name if b else None, b.kind if b else None) == (c["name"], c["kind"])
    for c in SHARED["scale"]:
        assert p.scale_y(c["swr"]) == pytest.approx(c["y"])
    for c in SHARED["levels"]:
        assert p.level(c["swr"]) == c["level"]
    with pytest.raises(p.PlanError):
        p.range_from_center(7_100_000, 0)
