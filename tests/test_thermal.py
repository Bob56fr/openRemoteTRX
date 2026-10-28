# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Température du poste : seuils (40 et 50 °C par défaut), hystérésis, coupure de l'émission à distance, alerte."""
import asyncio

import pytest

from test_safety import beating, refusal, run, station, until

from trxstation.config import Config, ConfigError, validate
from trxstation.gateway.safety.thermal import ThermalGuard


def test_levels_and_hysteresis():
    g = ThermalGuard(40, 50)
    assert g.level == "" and not g.observe(None)                 # poste sans TEMP_METER : rien
    assert not g.observe(35) and g.level == ""
    assert g.observe(40) and g.level == "warn"
    assert g.observe(50) and g.hot
    assert not g.observe(45) and g.hot                           # reste coupé tant qu'on n'est pas sous le 1er seuil
    assert not g.observe(None) and g.hot                         # plus de mesure : on ne sort pas de « hot »
    assert g.observe(39.5) and g.level == ""


def test_absurd_readings_are_ignored():
    g = ThermalGuard(40, 50)
    for value in (float("nan"), float("inf"), 400, -100, "abc", True):
        assert not g.observe(value)
    assert g.level == "" and g.temp_c is None
    with pytest.raises(ValueError):
        ThermalGuard(50, 50)


def test_defaults_and_validation():
    cfg = Config()
    assert (cfg.safety.rig_temp_warn_c, cfg.safety.rig_temp_cut_c) == (40, 50)
    cfg.safety.rig_temp_warn_c = 55
    assert any("rig_temp_warn_c" in p for p in validate(cfg))
    cfg.safety.rig_temp_warn_c, cfg.safety.rig_temp_cut_c = 10, 50
    assert any("rig_temp_warn_c" in p for p in validate(cfg))
    cfg.safety.rig_temp_warn_c, cfg.safety.rig_temp_cut_c = 45, 60
    assert not any("rig_temp" in p for p in validate(cfg))


def test_overheat_cuts_remote_tx_and_refuses_until_cooled():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.levels["TEMP_METER"] = 31.0
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            try:
                await ctrl.toggle("phone")
                assert ctrl.snapshot().state == "TX" and fake.ptt == 1
                fake.levels["TEMP_METER"] = 44.0                 # 1er seuil : avertissement, l'émission continue
                await until(lambda: ctrl.snapshot().temp_alert == "warn")
                assert ctrl.snapshot().state == "TX"
                fake.levels["TEMP_METER"] = 52.0                 # 2e seuil : coupure
                await until(lambda: ctrl.snapshot().state == "RX")
                assert fake.ptt == 0 and ctrl.snapshot().last_cut_reason == "rig_overheat"
                assert gate[-1][0] is False                      # micro fermé
                assert await refusal(ctrl.toggle("phone")) == "rig_hot"
                fake.levels["TEMP_METER"] = 45.0                 # entre les seuils : toujours refusé
                await asyncio.sleep(0.6)
                assert await refusal(ctrl.toggle("phone")) == "rig_hot"
                fake.levels["TEMP_METER"] = 38.0                 # sous le 1er seuil : émission de nouveau permise
                await until(lambda: ctrl.snapshot().temp_alert == "")
                await ctrl.toggle("phone")
                assert ctrl.snapshot().state == "TX"
                await ctrl.toggle("phone")
            finally:
                beat.cancel()
    run(scenario)


def test_hot_rig_never_keys_and_lost_reading_keeps_refusing():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.levels["TEMP_METER"] = 60.0
            await until(lambda: ctrl.thermal.hot)
            snap = ctrl.snapshot().to_dict()
            assert snap["temp_alert"] == "hot" and snap["temp_c"] == 60.0
            commands = len(fake.ptt_commands)
            assert await refusal(ctrl.toggle("phone")) == "rig_hot"
            assert len(fake.ptt_commands) == commands and fake.ptt == 0   # aucun ordre d'émission envoyé
            del fake.levels["TEMP_METER"]                        # mesure perdue : prudence, toujours refusé
            await asyncio.sleep(0.5)
            assert await refusal(ctrl.toggle("phone")) == "rig_hot"
    run(scenario)


def test_local_operator_is_not_cut_for_temperature():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.ptt = 1                                         # émission au micro du poste
            await until(lambda: ctrl.local.transmitting)
            commands = len(fake.ptt_commands)
            fake.levels["TEMP_METER"] = 60.0
            await until(lambda: ctrl.thermal.hot)
            await asyncio.sleep(0.2)
            assert fake.ptt == 1 and len(fake.ptt_commands) == commands   # alerte seule (superviseur, page)
            fake.ptt = 0
    run(scenario)
