# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mesure de TOS, outils de la station (étape 5 du cahier des charges) : TRX Console en lecture seule, trx-monitor,
fichier d'état de la passerelle."""
from __future__ import annotations

import asyncio
import time

from test_console_tools import make, write_config
from test_safety import beating, fast_limits, run, station, until

from trxstation import console
from trxstation.monitor.model import Snapshot, build_panels, render_plain
from trxstation.setup_wizard import dummy_config
from trxstation.status import GatewayStatus, read_status, write_status
from trxstation.swr.runner import SwrRunner
from trxstation.swr.store import SwrStore

LAST = {"low_hz": 14_000_000, "high_hz": 14_100_000, "step_hz": 50_000, "fm_mode": "FM-D", "power_pct": 15, "power_w": 15.0,
        "points": [{"hz": 14_000_000, "status": "measured", "swr": 1.3, "power_w": 15.0},
                   {"hz": 14_050_000, "status": "reduced", "swr": 2.4, "power_w": 5.0},
                   {"hz": 14_100_000, "status": "out_of_band", "swr": None, "power_w": None}],
        "best": {"hz": 14_000_000, "status": "measured", "swr": 1.3, "power_w": 15.0}, "reason": "done", "detail": "",
        "differences": ["coupleur : non remis en service, à rallumer à la main"], "at": time.time()}


def test_console_shows_the_last_measure_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "config_state_dir", lambda _: tmp_path / "state")
    write_config(tmp_path)
    con, fake, out = make(tmp_path)
    con.swr_report()
    assert "Aucune mesure" in out[-1] and "jamais depuis la console" in out[-1]
    SwrStore(tmp_path / "state" / "swr.json").save_last(LAST)
    con.swr_report()
    text = out[-1]
    assert "15.0 W en FM-D" in text and "14.000 à 14.100 MHz, pas de 50 kHz" in text
    assert "1.30" in text and "2.40" in text and "ÉLEVÉ" in text and "puissance réduite" in text and "hors bande" in text
    assert "Meilleur TOS : 1.30 à 14.000 MHz" in text and "À CORRIGER À LA MAIN : coupleur" in text
    assert fake.admin_commands() == []                                                    # lecture seule
    assert any(key == "21" and fn.__name__ == "swr_report" for key, _, fn in con.items)


def test_monitor_shows_a_measure_in_progress(tmp_path):
    status = GatewayStatus(pid=1, seq=1, written_at=time.time(), ptt={"state": "RX"}, rig={"connected": True},
                           swr={"running": True, "owner": "phone", "state": "measuring", "done": 3, "total": 8})
    path = tmp_path / "status.json"
    write_status(path, status)
    again = read_status(path)
    assert again.swr["done"] == 3                                                         # champ relu
    text = render_plain(build_panels(Snapshot(again, True, 0.1, None)))
    assert "Mesure de TOS" in text and "mesure 3/8 (phone)" in text and "STOP TX" in text
    quiet = GatewayStatus(pid=1, seq=2, written_at=time.time(), ptt={"state": "RX"}, rig={"connected": True})
    assert "Mesure de TOS" not in render_plain(build_panels(Snapshot(quiet, True, 0.1, None)))


def test_runner_publishes_its_progress_for_the_status_file(tmp_path):
    async def scenario(fake):
        fake.levels.update({"SWR": 1.2, "RFPOWER_METER": 0.15})
        cfg = dummy_config()
        cfg.rig.max_power_w, cfg.swr.point_tx_max_s = 100, 0.5
        async with station(fake, cfg=cfg, limits=fast_limits(tot_s=10.0)) as (ctrl, link, gate):
            store = SwrStore(tmp_path / "swr.json")
            store.save_settle(cfg.rig.model, 0.3)
            runner = SwrRunner(ctrl, cfg, store)
            assert runner.status() == {"running": False}
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await runner.start("phone", 14_000_000, 14_100_000, 3, 15, lambda m: None)
            seen = []
            await until(lambda: (seen.append(runner.status()) or not runner.busy), 20)
            hb.cancel()
            running = [s for s in seen if s.get("running")]
            assert running and running[0]["owner"] == "phone" and running[-1]["total"] == 3
            assert runner.status() == {"running": False}
    run(scenario)
