# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Poste à deux récepteurs (Yaesu FTDX101, étape 397) : le côté qui émet (touche TX du MAIN ou du SUB, commande FT) est
lu sur le poste avant chaque émission, car Hamlib ne lit que le split (ST). La bande est vérifiée aussi sur la fréquence
de CE côté ; une réponse illisible fait refuser ; un changement de côté ou de sa fréquence pendant l'émission coupe.
Faux rigctld, aucun matériel."""
import asyncio

import pytest

from test_safety import beating, fast_limits, refusal, run, state_is, station, until

from trxstation import rigspec
from trxstation.gateway.cat.client import RigctldClient


def ftdx101(ctrl, fake, *, side="0", main=14_200_000, sub=14_250_000):
    ctrl.spec = rigspec.load(1040)                                   # fiche du FTDX101D : lectures FT, FA, FB
    fake.ascii = {"FT;": f"FT{side};", "FA;": f"FA{main:09d};", "FB;": f"FB{sub:09d};"}


def test_transmit_on_the_sub_band_out_of_band_is_refused_even_without_split():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.freq, fake.split = 14_200_000, 0                     # Hamlib : pas de split, MAIN dans la bande
            ftdx101(ctrl, fake, side="1", sub=14_500_000)              # touche TX du SUB, SUB hors bande
            assert await refusal(ctrl.toggle("phone")) == "out_of_band"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_transmit_on_the_main_band_in_band_is_allowed_and_sub_out_of_band_does_not_matter():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            ftdx101(ctrl, fake, side="0", main=14_200_000, sub=7_500_000)
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert state_is(ctrl, "TX") and fake.ptt == 1
            await ctrl.toggle("phone")
            hb.cancel()
    run(scenario)


@pytest.mark.parametrize("answers", [
    {"FT;": "FT2;", "FA;": "FA014200000;", "FB;": "FB014250000;"},          # côté inconnu
    {"FT;": "??", "FA;": "FA014200000;", "FB;": "FB014250000;"},            # réponse illisible
    {"FA;": "FA014200000;", "FB;": "FB014250000;"},                         # FT refusé (RPRT -5)
    {"FT;": "FT0;", "FA;": "FA00000000;", "FB;": "FB014250000;"},           # fréquence illisible
    {"FT;": "FT1;", "FA;": "FA014200000;"},                                 # fréquence du SUB refusée
])
def test_unreadable_transmit_side_refuses(answers):
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            ctrl.spec = rigspec.load(1040)
            fake.ascii = answers
            assert await refusal(ctrl.toggle("phone")) == "tx_side_unreadable"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_switching_the_transmit_side_during_transmission_cuts():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(rig_poll_s=0.1)) as (ctrl, link, gate):
            ftdx101(ctrl, fake, side="0")
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert state_is(ctrl, "TX")
            fake.ascii["FT;"] = "FT1;"                                # touche TX du SUB pendant l'émission
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "tx_side_changed" and fake.ptt == 0
    run(scenario)


def test_tuning_the_transmitting_band_during_transmission_cuts():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(rig_poll_s=0.1)) as (ctrl, link, gate):
            ftdx101(ctrl, fake, side="1", sub=14_250_000)
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            fake.ascii["FB;"] = "FB014260000;"                        # bouton du SUB tourné pendant l'émission
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "tx_side_changed" and fake.ptt == 0
    run(scenario)


def test_rigs_without_a_transmit_side_never_send_raw_reads():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            hb = asyncio.create_task(beating(ctrl, "phone"))         # fiche générique (poste factice) : rien de plus
            await ctrl.toggle("phone")
            assert fake.ptt == 1 and fake.count_command("w FT;") == 0
            await ctrl.toggle("phone")
            hb.cancel()
    run(scenario)


def test_raw_reads_are_a_closed_list_of_reads():
    assert rigspec.read_queries() == {"FT;", "FA;", "FB;", "BY;"}   # BY : squelch des Yaesu (étape 402)
    client = RigctldClient("127.0.0.1", 1)
    for bad in ("FT1;", "FA014200000;", "TX1;", "EX030116;", "FT", "ft;"):
        with pytest.raises(ValueError):
            asyncio.run(client.read_ascii(bad))
    with pytest.raises(rigspec.RigSpecError, match="lecture"):
        rigspec.parse("format = 1\nmodel = 5\nname = 'x'\nreceivers = 2\n[transmit]\nside_query = 'FT1;'\n"
                      "side_reply = 'FT(.);'\nmain_value = '0'\nsub_value = '1'\nmain_freq_query = 'FA;'\n"
                      "sub_freq_query = 'FB;'\nfreq_reply = 'F.(.*);'")
