# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""État réel du squelch lu sur le poste (étape 396, signalement de l'utilisateur du 2026-11-25 : voyant SQL de la page
et de l'application pas représentatif sur l'IC-7300, l'IC-705 et le FTDX10) : `\\get_dcd` seulement si la fiche du
poste le permet, abandonné au premier refus, jamais lu en émission ; affichage seul."""
from __future__ import annotations

import asyncio

from test_cat import make_link, run, until

from trxstation import rigspec


def test_dcd_is_read_and_published_when_the_rig_spec_allows_it():
    async def scenario(fake):
        fake.dcd = False
        link = make_link(fake)
        link.read_dcd = True
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.dcd is False)
        fake.dcd = True                                              # signal qui ouvre le squelch du poste
        await until(lambda: link.state.dcd is True)
        assert link.state.to_dict()["dcd"] is True
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_dcd_is_never_asked_with_an_estimate_only_spec():
    async def scenario(fake):
        fake.dcd = True
        link = make_link(fake)                                       # read_dcd faux par défaut (fiche générique)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.frequency_hz is not None)
        await asyncio.sleep(0.2)
        assert link.state.dcd is None and fake.count_command("\\get_dcd") == 0
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_a_rig_that_refuses_dcd_is_asked_once_then_never_again():
    async def scenario(fake):
        fake.dcd = None                                              # RPRT -11 : le poste ne le dit pas
        link = make_link(fake)
        link.read_dcd = True
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.frequency_hz is not None)
        await asyncio.sleep(0.2)
        assert link.state.dcd is None and fake.count_command("\\get_dcd") == 1
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_dcd_is_not_read_during_a_transmission():
    async def scenario(fake):
        fake.dcd = True
        link = make_link(fake)
        link.read_dcd = True
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.dcd is True)
        fake.ptt = 1                                                 # émission (micro du poste)
        await until(lambda: link.state.ptt is True)
        await until(lambda: link.state.dcd is None)
        asked = fake.count_command("\\get_dcd")
        await asyncio.sleep(0.15)
        assert fake.count_command("\\get_dcd") == asked
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_rig_specs_say_where_the_real_squelch_comes_from():
    assert rigspec.load(1042).squelch.source == "busy" and rigspec.load(3094).squelch.source == "dcd"
    assert rigspec.load(1).squelch.source == "estimate"              # poste inconnu : rien de plus demandé au poste
