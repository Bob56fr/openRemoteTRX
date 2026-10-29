# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Split et ΔTX / XIT : la bande d'émission est vérifiée sur la fréquence d'ÉMISSION réelle, relue à l'instant ;
un split ou un XIT illisible fait refuser ; un changement pendant l'émission coupe. Faux rigctld (formats relevés
sur un vrai rigctld, IC-7300MK2, Hamlib 5), aucun matériel."""
import asyncio

from test_safety import beating, fast_limits, refusal, run, state_is, station, until

from trxstation.gateway.cat.capabilities import Capabilities


def test_split_transmit_frequency_out_of_band_is_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.freq, fake.split, fake.split_freq = 14_200_000, 1, 14_500_000      # réception dans la bande, émission hors
            assert await refusal(ctrl.toggle("phone")) == "out_of_band"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_split_transmit_frequency_in_band_is_what_counts():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.set_frequency(14_500_000)                                    # par la station : pas « poste utilisé sur place »
            fake.split, fake.split_freq = 1, 14_200_000                             # écoute hors bande, émission dans la bande
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert state_is(ctrl, "TX") and fake.ptt == 1
            await ctrl.toggle("phone")
            hb.cancel()
    run(scenario)


def test_xit_pushing_the_transmit_frequency_out_of_band_is_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.set_frequency(14_349_500)                                    # par la station : pas « poste utilisé sur place »
            fake.funcs["XIT"], fake.xit = 1, 900                                     # 14 350 400 Hz : au-delà de 14,35 MHz
            assert await refusal(ctrl.toggle("phone")) == "out_of_band"
            fake.xit = -900                                                         # décalé vers le bas : dans la bande
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert fake.ptt == 1
            await ctrl.toggle("phone")
            hb.cancel()
    run(scenario)


def test_unreadable_split_or_xit_refuses():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.errors["s"] = -5                                                   # poste muet sur le split
            assert await refusal(ctrl.toggle("phone")) == "split_unreadable"
            del fake.errors["s"]
            fake.split, fake.errors["i"] = 1, -5                                    # split en service, fréquence d'émission illisible
            assert await refusal(ctrl.toggle("phone")) == "split_unreadable"
            del fake.errors["i"]
            fake.split = 0
            fake.funcs["XIT"], fake.errors["z"] = 1, -5                             # ΔTX en service, décalage illisible
            assert await refusal(ctrl.toggle("phone")) == "xit_unreadable"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_rig_declaring_split_but_answering_unavailable_is_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            link.capabilities = Capabilities(complete=True, can_get_split=True, functions=("NR", "NB"))
            fake.errors["s"] = -11
            assert await refusal(ctrl.toggle("phone")) == "split_unreadable"
            link.capabilities = Capabilities(complete=True, can_get_split=None, functions=("NR", "NB"))
            hb = asyncio.create_task(beating(ctrl, "phone"))                        # poste qui ne connaît pas le split : rien à vérifier
            await ctrl.toggle("phone")
            assert fake.ptt == 1
            await ctrl.toggle("phone")
            hb.cancel()
    run(scenario)


def test_split_switched_on_during_transmission_cuts():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(rig_poll_s=0.1)) as (ctrl, link, gate):
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            fake.split, fake.split_freq = 1, 14_500_000                             # split mis sur le poste pendant l'émission
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "split_changed" and fake.ptt == 0
    run(scenario)


def test_xit_changed_during_transmission_cuts():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(rig_poll_s=0.1)) as (ctrl, link, gate):
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            fake.funcs["XIT"], fake.xit = 1, 5000                                   # ΔTX allumé sur le poste
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "xit_changed" and fake.ptt == 0
    run(scenario)


def test_offset_refused_while_transmitting_and_applied_in_receive():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.set_offset("XIT", 250)
            assert fake.xit == 250 and link.state.offsets["XIT"] == 250
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert await refusal(ctrl.set_offset("XIT", 800)) == "tx_active"
            assert fake.xit == 250
            await ctrl.toggle("phone")
            hb.cancel()
    run(scenario)


def test_link_publishes_split_and_offsets():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.split, fake.split_freq, fake.rit = 1, 14_210_000, 20
            await until(lambda: link.state.split is True and link.state.tx_frequency_hz == 14_210_000
                        and link.state.offsets.get("RIT") == 20)
            fake.split = 0
            await until(lambda: link.state.split is False and link.state.tx_frequency_hz is None)
    run(scenario)


def test_link_publishes_the_active_vfo_and_gives_up_when_the_rig_cannot_say():
    # Yaesu FTDX10 / FTDX101 : VFO lisible (« VFO: VFOA ») ; IC-7300MK2 : RPRT -11 => lecture abandonnée, voyant absent
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await until(lambda: link.state.vfo == "VFOA")
            fake.vfo = "VFOB"
            await until(lambda: link.state.vfo == "VFOB")
            fake.vfo = None
            await until(lambda: link.state.vfo is None)
            asked = fake.count("v")
            await asyncio.sleep(0.3)
            assert fake.count("v") == asked                   # plus jamais redemandé
            assert ctrl.snapshot().state == "RX"              # simple lecture : aucun effet sur le PTT
    run(scenario)
