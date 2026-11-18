# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Alerte de TOS élevé pendant une émission (2026-11-19) : message à celui qui émet, une fois par émission, JAMAIS de
coupure ; seuil `[safety] swr_alert` (0 = arrêt)."""
from __future__ import annotations

import asyncio

import pytest

from test_api import connect, run, station, until

from trxstation import config as cfgmod
from trxstation.errors import codes


def _swr(client):
    return [m for m in client.messages if m.get("type") == "rig_notice" and m["event"] == "swr_high"]


def _transmit(swr, limit=2.0, hold_s=1.6):
    seen = {}

    async def scenario(fake):
        fake.levels["SWR"] = swr
        async with station(fake) as st:
            st.ctrl.config.safety.swr_alert = limit
            phone = await connect(st, "phone")
            other = await connect(st, "tablet")
            await phone.say(cmd="toggle", id=1)
            assert phone.result(1)["ok"]
            end = asyncio.get_running_loop().time() + hold_s
            while asyncio.get_running_loop().time() < end:
                await phone.say(cmd="heartbeat")
                await asyncio.sleep(0.1)
            seen["state"] = st.ctrl.snapshot().state
            seen["phone"], seen["other"] = _swr(phone), _swr(other)
            await phone.say(cmd="toggle", id=2)
    run(scenario)
    return seen


def test_a_high_swr_while_transmitting_alerts_the_owner_once_and_never_cuts():
    seen = _transmit(2.7)
    assert seen["state"] == "TX"                                         # aucune coupure
    assert len(seen["phone"]) == 1 and seen["phone"][0]["ort"] == codes.ORT_5039
    assert "2.7" in seen["phone"][0]["detail"] and seen["phone"][0]["swr"] == 2.7
    assert seen["other"] == []                                           # seulement celui qui émet


def test_an_swr_below_the_threshold_or_a_disabled_alert_says_nothing():
    assert _transmit(1.5)["phone"] == []
    assert _transmit(2.7, limit=0)["phone"] == []


@pytest.mark.parametrize("value,ok", [(2.0, True), (0, True), (1.0, False), (11, False), (True, False)])
def test_swr_alert_threshold_is_validated(value, ok):
    cfg = cfgmod.Config()
    cfg.safety.swr_alert = value
    problems = [p for p in cfgmod.validate(cfg) if "swr_alert" in p]
    assert (problems == []) is ok, problems
