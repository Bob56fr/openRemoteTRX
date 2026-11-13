# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Cache de rigctld et relecture du PTT (étape 176).

Relevé dans les sources de Hamlib 5.0 (src/rig.c, src/cache.c) : après « T x », rigctld met dans son cache la
valeur COMMANDÉE (la relecture de contrôle de rig_set_ptt est en « #if 0 ») et `get_ptt` renvoie ce cache tant
qu'il a moins de cache_timeout (1000 ms en 5.0, 500 en 4.x). Sans correction, un poste qui accuse « T 0 » mais
reste en émission paraît coupé : la passerelle confirme un faux retour en réception, et le superviseur prend
l'émission qui « revient » une seconde plus tard pour une nouvelle émission de l'opérateur.

Le faux rigctld imite ce cache (`cache_timeout_ms`). Tests de panne : la station coupe le cache (lancement et
connexion), refuse d'émettre s'il reste actif, et ne confirme jamais une coupure sur la foi du cache.
"""
import asyncio

from test_safety import fast_limits, refusal, run, station, until
from test_supervisor_io import ServerThread
from trxstation import config as c
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.cat import RigctldClient
from trxstation.supervisor.rigctl import RigctlProbe
from trxstation.setup_wizard import dummy_config


# --------------------------------------------------------------------------- le danger, sur le faux poste

def test_the_fake_reproduces_the_hamlib_cache_that_hides_a_stuck_transmitter():
    async def scenario(fake):
        fake.cache_timeout_ms, fake.ptt, fake.ignore_unkey = 1000, 1, True     # poste bloqué en émission
        client = RigctldClient("127.0.0.1", fake.port, timeout=1.0)
        await client.connect()
        try:
            await client.write_ptt(False)
            assert await client.get_ptt() is False and fake.ptt == 1             # le cache MENT : le poste émet
            await client.set_cache_timeout(0)
            assert await client.get_cache_timeout() == 0
            assert await client.get_ptt() is True                                # sans cache : l'état réel
        finally:
            await client.close()
    run(scenario)


# --------------------------------------------------------------------------- lancement de rigctld

def test_rigctld_is_always_started_without_cache_and_extra_conf_cannot_change_it():
    args = c.Rig(model=3073, extra_conf=["timeout=500"]).rigctld_args("127.0.0.1", 4532)
    assert args[-2:] == ["-C", "cache_timeout=0"]                               # en dernier : la dernière valeur gagne
    assert "timeout=500" in args
    cfg = dummy_config()
    cfg.rig.extra_conf = ["write_delay=0,cache_timeout=500"]
    problems = c.validate(cfg)
    assert any("cache_timeout interdit" in p for p in problems)


# --------------------------------------------------------------------------- passerelle

def test_the_gateway_turns_the_cache_off_when_it_connects():
    async def scenario(fake):
        fake.cache_timeout_ms = 1000                                             # rigctld lancé sans l'option
        async with station(fake) as (ctrl, link, gate):
            assert fake.cache_timeout_ms == 0 and link.ptt_cache_ok is True
    run(scenario)


def test_a_stuck_transmitter_is_not_taken_for_rx_when_rigctld_had_a_cache():
    """Poste qui accuse « T 0 » mais reste en émission : avec le cache coupé à la connexion, la coupure n'est jamais
    confirmée (défaut verrouillé), comme sans cache."""
    async def scenario(fake):
        fake.cache_timeout_ms = 1000
        async with station(fake, limits=fast_limits(unkey_deadline_s=0.3)) as (ctrl, link, gate):
            beat = asyncio.create_task(_beat(ctrl))
            try:
                await ctrl.toggle("phone")
                await until(lambda: ctrl.snapshot().state == "TX")
                fake.ignore_unkey = True
                cut = asyncio.create_task(ctrl.toggle("phone"))
                await asyncio.sleep(0.6)
                assert fake.ptt == 1 and ctrl.snapshot().state != "RX"          # jamais « RX » sur la foi du cache
                fake.ignore_unkey = False                                       # le poste finit par obéir
                await until(lambda: ctrl.snapshot().state == "RX", 3.0)
                await asyncio.wait_for(cut, 3)
            finally:
                beat.cancel()
    run(scenario)


def test_transmission_is_refused_while_rigctld_keeps_its_cache():
    async def scenario(fake):
        fake.cache_timeout_ms = 1000
        fake.errors["\\set_cache"] = -4                                          # rigctld qui refuse de le couper
        async with station(fake) as (ctrl, link, gate):
            assert link.ptt_cache_ok is False
            assert await refusal(ctrl.toggle("phone")) == "ptt_unreadable"
            assert fake.ptt == 0 and fake.ptt_commands.count(1) == 0
    run(scenario)


def test_unknown_cache_commands_do_not_block_transmission():
    async def scenario(fake):
        fake.errors["\\set_cache"] = fake.errors["\\get_cache"] = -4          # rigctld très ancien ou autre serveur
        async with station(fake) as (ctrl, link, gate):
            assert link.ptt_cache_ok is None
            beat = asyncio.create_task(_beat(ctrl))
            try:
                await ctrl.toggle("phone")
                await until(lambda: ctrl.snapshot().state == "TX")
                await ctrl.toggle("phone")
                await until(lambda: ctrl.snapshot().state == "RX")
            finally:
                beat.cancel()
    run(scenario)


async def _beat(ctrl):
    while True:
        ctrl.heartbeat("phone")
        await asyncio.sleep(0.05)


# --------------------------------------------------------------------------- superviseur

def test_supervisor_force_rx_turns_the_cache_off_and_sees_a_stuck_transmitter():
    srv = ServerThread().start()
    try:
        srv.fake.cache_timeout_ms, srv.fake.ptt, srv.fake.ignore_unkey = 1000, 1, True
        probe = RigctlProbe("127.0.0.1", srv.fake.port)
        assert probe.force_rx() is False and srv.fake.cache_timeout_ms == 0
        srv.fake.ignore_unkey = False
        assert probe.force_rx() is True and srv.fake.ptt == 0
    finally:
        srv.stop()


def test_supervisor_waits_for_the_cache_to_expire_when_it_cannot_turn_it_off():
    srv = ServerThread().start()
    waits = []
    try:
        srv.fake.cache_timeout_ms, srv.fake.ptt, srv.fake.ignore_unkey = 300, 1, True
        srv.fake.errors["\\set_cache"] = -4
        probe = RigctlProbe("127.0.0.1", srv.fake.port, sleep=lambda s: (waits.append(s), __import__("time").sleep(s)))
        assert probe.force_rx() is False                                         # relu APRÈS l'expiration du cache
        assert waits and abs(waits[-1] - 0.4) < 0.01
    finally:
        srv.stop()


def test_fake_default_has_no_cache():
    assert FakeRigctld().cache_timeout_ms == 0
