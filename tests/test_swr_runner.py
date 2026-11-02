# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Moteur de la mesure de TOS (docs/tos-cahier-des-charges.md § 6 et § 7) : tests de PANNE avec le faux rigctld.

Chaque point est une prise d'émission normale du client ; toute coupure qui n'est pas la sienne arrête la mesure
(jamais de point suivant), le poste est toujours remis en état (relu) et la réservation libérée."""
from __future__ import annotations

import asyncio

from test_safety import beating, fast_limits, refusal, run, station, until

from trxstation.gateway.safety import Refused
from trxstation.setup_wizard import dummy_config
from trxstation.swr.runner import SwrRunner
from trxstation.swr.store import SwrStore


def config(**swr):
    cfg = dummy_config()
    cfg.rig.max_power_w = 100
    cfg.swr.point_tx_max_s = 0.5
    for key, value in swr.items():
        setattr(cfg.swr, key, value)
    return cfg


def prepare(fake):
    fake.freq, fake.mode, fake.passband = 14_074_000, "PKTUSB", 3000
    fake.levels.update({"RFPOWER": 1.0, "SWR": 1.3, "RFPOWER_METER": 0.15})
    fake.funcs["TUNER"] = 1


async def wait_done(runner, timeout=20):
    await until(lambda: not runner.busy, timeout)


def test_sweep_measures_each_point_then_restores_the_rig(tmp_path):
    async def scenario(fake):
        prepare(fake)
        cfg = config()
        async with station(fake, cfg=cfg, limits=fast_limits(tot_s=10.0)) as (ctrl, link, gate):
            store = SwrStore(tmp_path / "swr.json")
            runner, messages = SwrRunner(ctrl, cfg, store), []
            hb = asyncio.create_task(beating(ctrl, "phone"))
            plan = await runner.start("phone", 14_000_000, 14_100_000, 3, 15, messages.append)
            assert [p["hz"] for p in plan["points"]] == [14_000_000, 14_050_000, 14_100_000]
            assert plan["fm_mode"] == "FM" and plan["power_w"] == 15.0 and plan["calibration_needed"]
            assert await refusal(ctrl.toggle("car")) == "swr_busy"                      # un autre client ne prend pas la main
            await wait_done(runner)
            hb.cancel()
            final = messages[-1]
            assert final["state"] == "done" and final["result"]["reason"] == "done"
            assert [p["status"] for p in final["points"]] == ["measured"] * 3
            assert all(p["swr"] == 1.3 and p["power_w"] == 15.0 for p in final["points"])
            assert final["result"]["differences"] == []
            assert (fake.freq, fake.mode, fake.passband) == (14_074_000, "PKTUSB", 3000)   # poste remis en état
            assert fake.levels["RFPOWER"] == 1.0 and fake.funcs["TUNER"] == 1 and fake.ptt == 0
            assert ctrl.reserved_by is None and ctrl.snapshot().state == "RX"
            assert not any(opened for opened, _ in gate)                               # porte audio JAMAIS ouverte
            assert store.settle_s(cfg.rig.model) is not None and store.last()["best"]["swr"] == 1.3
            assert {m["state"] for m in messages} >= {"preparing", "calibrating", "measuring", "restoring", "done"}
    run(scenario)


def test_stop_from_another_client_stops_the_sweep_and_restores(tmp_path):
    async def scenario(fake):
        prepare(fake)
        cfg = config()
        async with station(fake, cfg=cfg, limits=fast_limits(tot_s=10.0)) as (ctrl, link, gate):
            store = SwrStore(tmp_path / "swr.json")
            store.save_settle(cfg.rig.model, 0.4)
            runner, messages = SwrRunner(ctrl, cfg, store), []
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await runner.start("phone", 14_000_000, 14_350_000, 8, 15, messages.append)
            await until(lambda: any(m["state"] == "measuring" for m in messages), 10)
            await ctrl.force_rx("stop", by="car")                                      # STOP de la voiture
            await wait_done(runner)
            hb.cancel()
            final = messages[-1]
            assert final["state"] == "cut" and final["result"]["detail"] == "stop", final["result"]
            assert final["result"]["differences"] == [], final["result"]["differences"]
            measured = [p for p in final["points"] if p["status"] == "measured"]
            assert 1 <= len(measured) < 8                                              # aucun point après la coupure
            assert fake.ptt == 0 and (fake.freq, fake.mode) == (14_074_000, "PKTUSB") and fake.funcs["TUNER"] == 1
            assert ctrl.reserved_by is None
            presses = len(fake.ptt_commands)
            await asyncio.sleep(1.0)
            assert len(fake.ptt_commands) == presses                                   # jamais de reprise
    run(scenario)


def test_lost_heartbeat_cuts_and_the_sweep_never_continues(tmp_path):
    async def scenario(fake):
        prepare(fake)
        cfg = config()
        async with station(fake, cfg=cfg, limits=fast_limits(tot_s=10.0, heartbeat_timeout_s=0.3)) as (ctrl, link, gate):
            store = SwrStore(tmp_path / "swr.json")
            store.save_settle(cfg.rig.model, 1.0)                                      # point plus long que le battement
            runner, messages = SwrRunner(ctrl, cfg, store), []
            await runner.start("phone", 14_000_000, 14_100_000, 3, 15, messages.append)   # aucun battement du client
            await wait_done(runner)
            final = messages[-1]
            assert final["state"] == "cut" and final["result"]["detail"] == "heartbeat"
            assert all(p["status"] == "pending" for p in final["points"])
            assert fake.ptt == 0 and (fake.freq, fake.mode) == (14_074_000, "PKTUSB")
    run(scenario)


def test_owner_lost_between_points_aborts(tmp_path):
    async def scenario(fake):
        prepare(fake)
        cfg = config()
        async with station(fake, cfg=cfg, limits=fast_limits(tot_s=10.0, rekey_cooldown_s=0.5)) as (ctrl, link, gate):
            store = SwrStore(tmp_path / "swr.json")
            store.save_settle(cfg.rig.model, 0.3)
            runner, messages = SwrRunner(ctrl, cfg, store), []
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await runner.start("phone", 14_000_000, 14_350_000, 8, 15, messages.append)
            await until(lambda: any(m["state"] == "measuring" for m in messages), 10)
            await ctrl.disconnect_client("phone")                                      # perdu (en RX ou en émission)
            await wait_done(runner)
            hb.cancel()
            assert messages[-1]["state"] in ("cut", "failed") and fake.ptt == 0
            assert messages[-1]["result"]["reason"] in ("cut", "unknown_client")
            assert fake.mode == "PKTUSB" and ctrl.reserved_by is None
    run(scenario)


def test_bands_out_of_band_points_and_refusals(tmp_path):
    async def scenario(fake):
        prepare(fake)
        cfg = config()
        async with station(fake, cfg=cfg) as (ctrl, link, gate):
            runner = SwrRunner(ctrl, cfg, SwrStore(tmp_path / "swr.json"))
            plan = runner.make_plan(14_300_000, 14_400_000, 3)                          # 20 m s'arrête à 14,35 MHz
            assert [p["status"] for p in plan["points"]] == ["pending", "pending", "out_of_band"]      # 14,35 MHz compris
            assert plan["power_pct"] == 15 and runner.make_plan(14_000_000, 14_100_000, 3, 80)["power_pct"] == 50   # plafond
            assert await refusal(runner.start("phone", 9_000_000, 9_100_000, 3, 15, lambda m: None)) == "swr_out_of_band"
            cfg.safety.enforce_bands = False                                           # montage sans émission sur l'air
            assert [p["status"] for p in runner.make_plan(9_000_000, 9_100_000, 3)["points"]] == ["pending"] * 3
            cfg.rig.tx_modes = ["PKTUSB"]
            assert await refusal(runner.start("phone", 14_000_000, 14_100_000, 3, 15, lambda m: None)) == "swr_no_fm_mode"
            cfg.rig.tx_modes = ["PKTUSB", "FM-D"]
            assert runner.fm_mode() == "FM-D"                                          # IC-7300 : FM-D permis par tx_modes
            assert ctrl.reserved_by is None and 1 not in fake.ptt_commands               # rien n'a été émis
    run(scenario)


def test_reservation_only_blocks_other_clients(tmp_path):
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            ctrl.reserve("phone")
            assert await refusal(ctrl.toggle("car")) == "swr_busy"
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.key_without_audio("phone")
            assert ctrl.snapshot().state == "TX" and fake.ptt == 1 and gate == []        # porte audio restée fermée
            await ctrl.force_rx("stop", by="car")                                      # STOP toujours permis
            hb.cancel()
            assert fake.ptt == 0
            ctrl.release_reservation("phone")
            assert ctrl.reserved_by is None
    run(scenario)


def test_exact_power_is_for_the_station_only_and_never_during_tx():
    async def scenario(fake):
        import pytest
        async with station(fake) as (ctrl, link, gate):
            await ctrl.set_power_exact(0.15)
            assert fake.levels["RFPOWER"] == 0.15
            with pytest.raises(ValueError):
                await ctrl.set_power_exact(1.5)
            with pytest.raises(ValueError):
                await link.set_level("RFPOWER", 0.15)                                   # les clients : paliers seulement
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("phone")
            assert await refusal(ctrl.set_power_exact(0.5)) == "tx_active"               # jamais pendant l'émission
            await ctrl.toggle("phone")
            hb.cancel()
            assert fake.levels["RFPOWER"] == 0.15
    run(scenario)


def test_protocol_operator_starts_others_are_refused_and_a_listener_cannot(tmp_path):
    from test_api import connect, run as api_run, station as api_station
    from trxstation.gateway.api.access import AccessControl
    from trxstation.config import Access, ClientAuth

    async def scenario(fake):
        prepare(fake)
        async with api_station(fake) as st:
            cfg = st.ctrl.config
            cfg.rig.max_power_w, cfg.swr.point_tx_max_s = 100, 0.5
            store = SwrStore(tmp_path / "swr.json")
            store.save_settle(cfg.rig.model, 0.3)
            swr = SwrRunner(st.ctrl, cfg, store)
            access = AccessControl([ClientAuth("phone", password_hash="x"), ClientAuth("car", password_hash="y"),
                                    ClientAuth("club1", password_hash="z", role="listener")], Access(max_listeners=2))
            access.switch.open = True                                                     # écoute des visiteurs ouverte
            access.admit("phone")
            phone = await connect(st, "phone", access=access, swr=swr)
            access.admit("car")
            car = await connect(st, "car", access=access, swr=swr)
            access.admit("club1")                                                         # visiteur : opérateur présent
            visitor = await connect(st, "club1", role="listener", access=access, swr=swr)
            assert "swr" in phone.of_type("hello")[0]["features"] and "swr" not in visitor.of_type("hello")[0]["features"]
            await phone.say(cmd="swr_plan", id=1, low_hz=14_000_000, high_hz=14_100_000, points=3, power_pct=15)
            assert phone.result(1)["plan"]["step_hz"] == 50_000 and phone.result(1)["choices"]["power_pct"] == 15
            hb = asyncio.create_task(beating(st.ctrl, "phone"))
            await phone.say(cmd="swr_start", id=2, low_hz=14_000_000, high_hz=14_100_000, points=3, power_pct=15)
            assert phone.result(2)["ok"]
            await car.say(cmd="set_frequency", id=3, hz=7_100_000)
            assert car.result(3)["reason"] == "swr_busy"                                 # personne ne touche au poste
            await visitor.say(cmd="swr_start", id=4, low_hz=14_000_000, high_hz=14_100_000, points=3, power_pct=15)
            assert visitor.result(4)["reason"] == "forbidden"                             # un visiteur ne lance rien
            await until(lambda: not swr.busy, 20)
            hb.cancel()
            states = [m["state"] for m in phone.of_type("swr")]
            assert states[0] == "preparing" and states[-1] == "done" and not car.of_type("swr")
            await phone.say(cmd="swr_last", id=5)
            assert phone.result(5)["last"]["best"]["swr"] == 1.3
            assert fake.mode == "PKTUSB" and fake.freq == 14_074_000
    api_run(scenario)

