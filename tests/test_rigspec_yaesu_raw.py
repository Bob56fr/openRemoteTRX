# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Yaesu FTDX10 / FTDX101 (étape 402, lecture du code de Hamlib 5.0.0~git, `docs/hamlib-5-analyse.md`) : Hamlib n'a pas
get_dcd pour ces postes, le squelch se lit par la lecture brute « BY; » de la fiche ; et une largeur 0 envoyée avec un
mode y devient 2400 Hz et réécrit le filtre de toit : leur fiche envoie -1 (largeur inchangée). Faux rigctld."""
from __future__ import annotations

import asyncio

import pytest

from test_cat import make_link, run, until

from trxstation import rigspec
from trxstation.rigspec import RigSpecError


def _raw_squelch(link, model=1042):
    sq = rigspec.load(model).squelch
    link.read_dcd, link.dcd_raw = True, (sq.query, sq.reply, sq.open_value)


def test_ftdx10_squelch_is_read_by_the_raw_busy_query():
    async def scenario(fake):
        fake.ascii = {"BY;": "BY00;"}                                 # manuel : « BY P1 P2; », P1 = 1 squelch ouvert
        link = make_link(fake)
        _raw_squelch(link)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.dcd is False)
        fake.ascii["BY;"] = "BY10;"
        await until(lambda: link.state.dcd is True)
        assert fake.count_command("\\get_dcd") == 0
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_unexpected_busy_reply_gives_up_the_squelch_reading():
    async def scenario(fake):
        fake.ascii = {"BY;": "?;"}
        link = make_link(fake)
        _raw_squelch(link)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.frequency_hz is not None)
        await asyncio.sleep(0.3)
        assert link.state.dcd is None and fake.count_command("w BY;") == 1
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_ftdx101_reads_the_main_receiver_of_busy():
    sq = rigspec.load(1040).squelch
    import re
    assert re.fullmatch(sq.reply, "BY01;").group(1) == "0"            # SUB occupé seulement : squelch du MAIN fermé
    assert "BY;" in rigspec.read_queries()


@pytest.mark.parametrize("squelch, problem", [
    ("source = 'busy'", "exigés"),
    ("source = 'busy'\nquery = 'BY0;'\nreply = 'BY(.)'\nopen_value = '1'", "lecture"),
    ("source = 'busy'\nquery = 'BY;'\nreply = 'BY..;'\nopen_value = '1'", "un seul groupe"),
    ("source = 'dcd'\nquery = 'BY;'", "seulement pour source = busy"),
])
def test_bad_raw_squelch_fields_are_refused(squelch, problem):
    with pytest.raises(RigSpecError, match=problem):
        rigspec.parse(f"format = 1\nmodel = 5\nname = 'x'\n[squelch]\n{squelch}\n")


def test_mode_width_is_zero_or_minus_one():
    with pytest.raises(RigSpecError, match="mode_width"):
        rigspec.parse("format = 1\nmodel = 5\nname = 'x'\n[filters]\nmode_width = 2400\n")
    assert rigspec.load(1042).filters.mode_width == -1 and rigspec.load(3094).filters.mode_width == 0


def test_mode_without_a_chosen_width_sends_the_width_of_the_rig_spec():
    async def scenario(fake):
        link = make_link(fake)
        await link.client.connect()
        fake.passband = 1800
        link.client.mode_width = -1                                   # FTDX10 : largeur inchangée
        await link.client.set_mode("LSB")
        assert fake.commands[-1].endswith("M LSB -1") and fake.mode == "LSB" and fake.passband == 1800
        link.client.mode_width = 0                                    # Icom : largeur normale, comme avant
        await link.client.set_mode("USB")
        assert fake.commands[-1].endswith("M USB 0")
        await link.client.set_mode("USB", 2400)                       # largeur choisie : envoyée telle quelle
        assert fake.commands[-1].endswith("M USB 2400")
        await link.client.close()
    run(scenario)
