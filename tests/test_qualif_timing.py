# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Délais du poste mesurés par la valise (étape 400) : retards de relecture, mémoire par bande, squelch réel, largeurs
par paliers, puis brouillon de la fiche technique. Faux rigctld, aucune émission."""
from __future__ import annotations

import tomllib

from test_safety import run, station

from trxstation import rigspec
from trxstation.qualif import timing


def test_measure_reads_back_delays_band_memory_dcd_and_restores_the_rig():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.freq, fake.mode, fake.dcd = 14_200_000, "USB", False
            found = await timing.measure(ctrl, link.client, spec=rigspec.load(1), modes=["USB", "LSB", "CW"])
            assert len(found.freq_delays_s) == timing.REPEATS and len(found.mode_delays_s) == 3
            assert all(0 <= d < 2 for d in found.freq_delays_s + found.mode_delays_s), found.to_dict()
            assert found.band_changes_mode is False and found.dcd is True and not found.problems
            assert fake.freq == 14_200_000 and fake.mode == "USB"                  # poste remis
            assert found.proposed_read_delay_s() in (0.0, 0.5, 1.0)
            assert 1 not in fake.ptt_commands                                      # jamais d'émission
    run(scenario)


def test_unreadable_dcd_and_missing_mode_are_reported_not_fatal():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.dcd = None
            found = await timing.measure(ctrl, link.client, spec=rigspec.load(1), modes=["USB"])
            assert found.dcd is False and found.mode_delays_s == [] and found.freq_delays_s
    run(scenario)


def test_proposed_margin_and_draft_sheet():
    t = timing.Timing(freq_delays_s=[0.4, 1.2, 0.5], mode_delays_s=[0.3], band_changes_mode=True, tuner_on=False, dcd=True,
                      widths=[(1800, 1800), (2400, 2400)])
    assert t.worst_s == 1.2 and t.proposed_read_delay_s() == 2.5                   # 2 × 1,2 = 2,4 -> 2,5
    assert timing.Timing(freq_delays_s=[0.1]).proposed_read_delay_s() == 0.0
    text = timing.render_draft(rigspec.load(1040), 1040, "Yaesu FTDX101D", t)
    spec = rigspec.parse(text, "brouillon")                                        # le brouillon est une fiche VALIDE
    assert spec.verified and spec.timing.read_delay_s == 2.5 and spec.timing.linked_changes
    assert spec.transmit.side_query == "FT;" and spec.squelch.source == "busy"
    assert "1800 -> 1800" in text
    unknown = timing.render_draft(rigspec.load(3094), 3094, "Icom IC-7300MK2", timing.Timing(dcd=False))
    sheet = tomllib.loads(unknown)
    assert sheet["verified"] is False and sheet["squelch"]["source"] == "estimate" and sheet["filters"]["presets"] == 3


def test_band_center_is_always_another_band():
    for f in (3_650_000, 7_050_000, 14_200_000, 21_300_000, 28_400_000, 50_100_000):
        assert abs(timing._band_center(f) - f) > 2_000_000
