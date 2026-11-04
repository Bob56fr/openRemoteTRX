# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Faux Breizh et fausse station (breizh_probe) l'un contre l'autre, en UDP local : modes de panne du § 9."""
from __future__ import annotations

import asyncio

import pytest

from trxstation.breizh import protocol as p
from trxstation.devtools import breizh_probe as probe_mod
from trxstation.devtools import fake_breizh

KEY = bytes(range(32))


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


async def pair(key=KEY, probe_key=None, **options):
    fake_transport, fake = await fake_breizh.serve(key, "127.0.0.1", 0, **options)
    port = fake_transport.get_extra_info("sockname")[1]
    probe_transport, probe = await probe_mod.open_probe(probe_key or key, "127.0.0.1", port)
    return fake_transport, fake, probe_transport, probe


async def scenario(seconds=0.4, connect_timeout=2.0, probe_key=None, **options):
    ft, fake, pt, probe = await pair(probe_key=probe_key, **options)
    try:
        await probe.connect(connect_timeout, retry=0.3)
        pings = await probe.ping(3, 0.02, 0.1)
        report = await probe.tone(seconds, wait=0.3)
        probe.bye()
        await asyncio.sleep(0.05)
        return fake, probe, pings, report
    finally:
        pt.close()
        ft.close()


def test_echo_returns_every_block_unchanged():
    fake, probe, pings, report = run(scenario())
    assert all(r is not None for r in pings)
    assert report["sent"] == 40 and report["returned"] == 40 and report["lost"] == 0
    assert report["gain_db"] == 0.0 and report["rejected"] == {}
    assert fake.session is None                                     # BYE reçu


def test_gain_is_applied():
    _, _, _, report = run(scenario(mode="gain", gain_db=-6.0))
    assert report["returned"] == report["sent"]
    assert report["gain_db"] == pytest.approx(-6.0, abs=0.1)


def test_freeze_loses_blocks():
    _, _, _, report = run(scenario(seconds=0.6, mode="freeze", freeze_after_s=0.15))
    assert report["lost"] > 0 and report["returned"] < report["sent"]


def test_drop_loses_one_block_in_n():
    _, _, _, report = run(scenario(mode="drop", drop_every=4))
    assert report["lost"] == report["sent"] // 4


def test_slow_blocks_are_late():
    # 120 ms : les minuteries d'asyncio sous Windows ont ~16 ms de résolution (un délai de 60 ms y sortait parfois à 35)
    _, _, _, report = run(scenario(mode="slow", delay_ms=120))
    assert report["late"] == report["returned"] > 0


def test_forged_returns_are_never_accepted():
    _, _, pings, report = run(scenario(mode="forge"))
    assert report["returned"] == 0 and report["lost"] == report["sent"]
    assert all(r is None for r in pings)
    assert report["rejected"]["tag"] >= report["sent"]


def test_replayed_returns_are_refused():
    _, _, _, report = run(scenario(mode="replay"))
    assert report["returned"] == report["sent"]                     # chaque bloc accepté UNE fois
    assert report["rejected"]["replay"] > 0


def test_spontaneous_returns_are_refused():
    _, _, _, report = run(scenario(mode="spontaneous"))
    assert report["returned"] == report["sent"]
    assert report["rejected"]["unsolicited"] == report["sent"]


@pytest.mark.parametrize("mode,reason", [("cat_on", "cat_on"), ("proto2", "proto"), ("mode_off", "error")])
def test_refused_links(mode, reason):
    with pytest.raises(probe_mod.ProbeError) as err:
        run(scenario(mode=mode))
    assert err.value.reason == reason


def test_wrong_key_gets_no_answer_at_all():
    async def go():
        ft, fake, pt, probe = await pair(probe_key=bytes(32))
        try:
            with pytest.raises(probe_mod.ProbeError) as err:
                await probe.connect(0.6, retry=0.2)
            assert err.value.reason == "timeout"
            assert fake.stats["rejected"] >= 2 and fake.stats["hello"] == 0
        finally:
            pt.close()
            ft.close()
    run(go())


def test_fake_only_serves_its_station():
    async def go():
        ft, fake, pt, probe = await pair(station="10.9.9.9")
        try:
            with pytest.raises(probe_mod.ProbeError):
                await probe.connect(0.5, retry=0.2)
            assert fake.stats["foreign"] >= 2
        finally:
            pt.close()
            ft.close()
    run(go())


def test_probe_ignores_packets_from_another_address():
    async def go():
        ft, fake, pt, probe = await pair()
        try:
            await probe.connect(2.0, retry=0.3)
            other = await fake_breizh.serve(KEY, "127.0.0.1", 0)
            data = p.encode(p.Packet(p.Type.PONG, probe.session, 99, 1), probe.session_key)
            other[0].sendto(data, ("127.0.0.1", pt.get_extra_info("sockname")[1]))
            await asyncio.sleep(0.1)
            assert probe.rejected["foreign"] == 1
            other[0].close()
        finally:
            pt.close()
            ft.close()
    run(go())
