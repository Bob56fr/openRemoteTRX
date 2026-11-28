# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Décalage relais (DUP+ / DUP-, étape 401) : un poste VHF / UHF (IC-705, IC-7100…) en DUP+ émet sur la fréquence de
réception PLUS l'écart ; la bande se vérifie sur celle-là, un décalage illisible fait refuser, un changement pendant
l'émission coupe. Et « T 0 » refusé par RPRT -20 (rigctld qui se croit le poste éteint) : l'alimentation est relue puis
« T 0 » renvoyé, par la passerelle comme par le superviseur. Faux rigctld (formats relevés sur un vrai rigctld 4.7.2,
poste factice, 2026-11-26), aucun matériel."""
import asyncio

from test_safety import beating, fast_limits, refusal, run, state_is, station, until

from trxstation.gateway.cat.capabilities import Capabilities, parse_dump_caps
from trxstation.supervisor.rigctl import RigctlProbe


def test_repeater_shift_pushing_the_transmit_frequency_out_of_band_is_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.freq, fake.rptr_shift, fake.rptr_offs = 14_200_000, "+", 500_000  # réception dans la bande, émission hors
            assert await refusal(ctrl.toggle("phone")) == "out_of_band"
            assert 1 not in fake.ptt_commands
            fake.rptr_shift = "-"                                                   # même écart vers le bas : 13,7 MHz
            assert await refusal(ctrl.toggle("phone")) == "out_of_band"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_simplex_or_small_shift_inside_the_band_transmits():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.freq, fake.rptr_shift, fake.rptr_offs = 14_200_000, "None", 600_000
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert state_is(ctrl, "TX") and fake.ptt == 1
            await ctrl.toggle("phone")
            fake.rptr_shift, fake.rptr_offs = "+", 100_000                          # 14,3 MHz : toujours dans la bande
            await ctrl.toggle("phone")
            assert state_is(ctrl, "TX") and fake.ptt == 1
            await ctrl.toggle("phone")
            hb.cancel()
    run(scenario)


def test_unreadable_repeater_shift_refuses():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.rptr_shift, fake.rptr_offs = "+", 0                                # en service, écart relu à 0 (Yaesu)
            assert await refusal(ctrl.toggle("phone")) == "rptr_unreadable"
            fake.rptr_offs, fake.errors["o"] = 600_000, -5                          # écart illisible
            assert await refusal(ctrl.toggle("phone")) == "rptr_unreadable"
            del fake.errors["o"]
            fake.rptr_shift = "?"                                                   # réponse inattendue
            assert await refusal(ctrl.toggle("phone")) == "rptr_unreadable"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_rig_declaring_the_repeater_shift_but_refusing_it_is_refused_and_one_without_it_transmits():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            link.capabilities = Capabilities(complete=True, can_get_rptr_shift=True, functions=("NR", "NB"))
            fake.errors["r"] = -11
            assert await refusal(ctrl.toggle("phone")) == "rptr_unreadable"
            assert 1 not in fake.ptt_commands
            link.capabilities = Capabilities(complete=True, can_get_rptr_shift=False, functions=("NR", "NB"))
            hb = asyncio.create_task(beating(ctrl, "phone"))                        # IC-7300 : pas de décalage relais
            seen = len(fake.commands)
            await ctrl.toggle("phone")
            assert fake.ptt == 1 and not any(c.lstrip("+").split()[:1] == ["r"] for c in fake.commands[seen:])
            await ctrl.toggle("phone")
            hb.cancel()
    run(scenario)


def test_repeater_shift_switched_on_during_transmission_cuts():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(rig_poll_s=0.1)) as (ctrl, link, gate):
            fake.rptr_shift, fake.rptr_offs = "None", 600_000
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert state_is(ctrl, "TX")
            fake.rptr_shift = "+"                                                   # DUP+ mis sur le poste pendant l'émission
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "rptr_changed" and fake.ptt == 0
    run(scenario)


def test_dump_caps_repeater_lines_are_read():
    text = ("Caps dump for model: 3085\nModel name:\tIC-705\nCan get Split VFO:\tY\n"
            "Can set Repeater Duplex:\tY\nCan get Repeater Duplex:\tY\nCan set Repeater Offset:\tY\n"
            "Can get Repeater Offset:\tN\n")
    caps = parse_dump_caps(text)
    assert caps.can_get_rptr_shift is True and caps.can_get_rptr_offs is False
    assert parse_dump_caps("Caps dump for model: 1\n").can_get_rptr_shift is None


def test_unkey_refused_because_rigctld_believes_the_rig_off_is_sent_again():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert state_is(ctrl, "TX") and fake.ptt == 1
            fake.believes_off = True                       # rigctld se croit le poste éteint : « T 0 » = RPRT -20
            await ctrl.toggle("phone")
            hb.cancel()
            assert state_is(ctrl, "RX") and fake.ptt == 0
            assert any(c.lstrip("+") == "\\get_powerstat" for c in fake.commands) and not fake.believes_off
    run(scenario)


def test_supervisor_unkey_refused_by_rpr_minus_20_reads_the_power_then_unkeys():
    async def scenario(fake):
        fake.ptt, fake.believes_off = 1, True
        probe = RigctlProbe("127.0.0.1", fake.port, timeout=1.0)
        assert await asyncio.to_thread(probe.force_rx) is True
        assert fake.ptt == 0 and not fake.believes_off
    run(scenario)
