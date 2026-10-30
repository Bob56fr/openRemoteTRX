# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Surcharge de la station par les visiteurs (gateway/api/overload.py) : coupure après 10 s au-delà d'un seuil,
message précis, réouverture après 5 minutes nettement en dessous, verrou après 3 coupures en une heure, réouverture à
la main seulement au vert ; commandes listener_kick et listeners_reopen réservées aux opérateurs."""
import asyncio

import pytest

from trxstation.config import Access, ClientAuth
from trxstation.gateway.access_watch import REOPEN_REQUEST, AccessWatcher, kick_request
from trxstation.gateway.api.access import AccessControl, AccessRefused
from trxstation.gateway.api.overload import (HOLD_S, MAX_PER_HOUR, REOPEN_S, CpuLoad, Limits, OverloadGuard, Sample,
                                             mem_free_pct)

from test_api import connect, run, station

CALM, HOT = Sample(temp_c=50, cpu_pct=20, lag_ms=5, mem_free_pct=60), Sample(temp_c=87, cpu_pct=20, lag_ms=5, mem_free_pct=60)


class World:
    def __init__(self):
        self.t, self.sample = 0.0, CALM
        self.guard = OverloadGuard(lambda: self.sample, Limits(), clock=lambda: self.t)

    def run(self, seconds, listeners=1):
        cut = False
        for _ in range(int(seconds)):
            cut = self.guard.step(listeners) or cut
            self.t += 1
        return cut


def test_limits_name_the_first_cause_and_need_a_clear_margin_to_go_back():
    limits = Limits()
    assert limits.over(CALM) == ""
    assert limits.over(HOT) == "processeur à 87 °C"
    assert limits.over(Sample(cpu_pct=95)) == "processeur occupé à 95 %"
    assert limits.over(Sample(lag_ms=150)) == "passerelle en retard de 150 ms"
    assert limits.over(Sample(mem_free_pct=7)) == "mémoire libre à 7 %"
    assert limits.over(Sample()) == ""                                      # rien de lisible (Windows) : jamais de coupure
    assert limits.green(CALM) and not limits.green(Sample(temp_c=80))      # sous 85 mais pas sous 75 : pas encore
    assert not limits.green(Sample(cpu_pct=75)) and not limits.green(Sample(lag_ms=60))


def test_ten_seconds_over_cut_the_listeners_with_a_precise_message_then_reopen_after_five_quiet_minutes():
    w = World()
    w.sample = HOT
    assert not w.run(HOLD_S - 1)                                            # un pic bref ne coupe pas
    w.sample = CALM
    w.run(3)
    w.sample = HOT
    assert w.run(HOLD_S + 1) and w.guard.suspended
    assert "processeur à 87 °C" in w.guard.message() and "5 minutes" in w.guard.message()
    status = w.guard.status()
    assert status["locked"] is False and status["reopen_in_s"] == REOPEN_S
    w.sample = Sample(temp_c=80)                                            # redescendu, mais pas assez
    w.run(REOPEN_S + 10)
    assert w.guard.suspended
    w.sample = CALM
    w.run(REOPEN_S - 5)
    w.sample = Sample(temp_c=78)                                            # rechute au-dessus du seuil de retour : on recompte
    w.run(2)
    w.sample = CALM
    w.run(REOPEN_S - 1)
    assert w.guard.suspended
    w.run(2)
    assert not w.guard.suspended and w.guard.status() is None


def test_three_cuts_in_an_hour_lock_until_a_manual_reopen_accepted_only_when_green():
    w = World()
    for _ in range(MAX_PER_HOUR):
        w.sample = HOT
        assert w.run(HOLD_S + 1)
        w.sample = CALM
        w.run(REOPEN_S + 2)
    assert w.guard.suspended and w.guard.status()["locked"] and w.guard.status()["reopen_in_s"] is None
    assert "l'opérateur doit la rouvrir" in w.guard.message()
    w.run(3600)
    assert w.guard.suspended                                                # jamais tout seul
    w.sample = HOT
    w.run(1)
    assert w.guard.reopen().startswith("Refusé") and w.guard.suspended
    w.sample = CALM
    w.run(1)
    assert w.guard.reopen() == "" and not w.guard.suspended


def test_overload_without_listeners_refuses_newcomers_but_does_not_count_toward_the_lock():
    w = World()
    for _ in range(MAX_PER_HOUR + 1):
        w.sample = HOT
        assert not w.run(HOLD_S + 1, listeners=0)                         # personne à déconnecter
        assert w.guard.suspended and not w.guard.status()["locked"]
        w.sample = CALM
        w.run(REOPEN_S + 2, listeners=0)
        assert not w.guard.suspended


def test_listener_reconnected_by_hand_too_early_is_cut_again():
    w = World()
    w.sample = HOT
    w.run(HOLD_S + 1)
    assert w.guard.step(1)                                                 # encore au-delà et un visiteur là : coupé


def test_admission_is_refused_with_the_guard_message():
    access = AccessControl([ClientAuth("phone", password_hash="x"), ClientAuth("club1", password_hash="y", role="listener")],
                           Access(max_listeners=2, listeners_need_operator=False))
    w = World()
    access.guard = w.guard
    w.sample = HOT
    w.run(HOLD_S + 1, listeners=0)
    with pytest.raises(AccessRefused) as exc:
        access.admit("club1")
    assert exc.value.reason == "station_overload" and "87 °C" in exc.value.message and exc.value.status == 403
    access.admit("phone")                                                   # l'opérateur entre toujours
    assert access.presence("operator")["suspended"]["reason"] == "processeur à 87 °C"


def test_real_measures_read_proc_files(tmp_path):
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    cpu = CpuLoad(str(stat))
    assert cpu.read() is None                                               # première lecture : référence
    stat.write_text("cpu  190 0 190 820 0 0 0 0 0 0\n")                    # 180 occupés sur 200
    assert cpu.read() == pytest.approx(90.0)
    assert CpuLoad(str(tmp_path / "rien")).read() is None
    mem = tmp_path / "meminfo"
    mem.write_text("MemTotal:       8000000 kB\nMemFree: 1 kB\nMemAvailable:    800000 kB\n")
    assert mem_free_pct(str(mem)) == pytest.approx(10.0)
    assert mem_free_pct(str(tmp_path / "rien")) is None


class FakeManager:
    def __init__(self):
        self.kicked, self.alerts = [], []
        self.alert = lambda title, text: self.alerts.append(text)

    async def kick(self, client_id, reason, message=""):
        self.kicked.append((client_id, reason, message))


class FakeRegistry:
    def update(self, clients):
        pass


def test_watcher_cuts_every_listener_alerts_and_takes_the_console_reopen_request(tmp_path):
    access = AccessControl([ClientAuth("phone", password_hash="x"), ClientAuth("club1", password_hash="y", role="listener"),
                            ClientAuth("club2", password_hash="z", role="listener")],
                           Access(max_listeners=2, listeners_need_operator=False))
    w = World()
    access.guard = w.guard
    for cid in ("phone", "club1", "club2"):
        access.admit(cid)
        access.opened(cid)
    manager = FakeManager()
    watcher = AccessWatcher(access, FakeRegistry(), manager, None, tmp_path)
    w.sample = HOT
    for _ in range(int(HOLD_S) + 1):
        asyncio.run(watcher.step())
        w.t += 1
    assert {(c, r) for c, r, _ in manager.kicked} == {("club1", "station_overload"), ("club2", "station_overload")}
    assert all("87 °C" in m for _, _, m in manager.kicked) and manager.alerts
    w.sample = CALM
    asyncio.run(watcher.step())
    (tmp_path / REOPEN_REQUEST).write_bytes(kick_request("reopen"))
    asyncio.run(watcher.step())
    assert not w.guard.suspended and not (tmp_path / REOPEN_REQUEST).exists()


def test_operator_commands_kick_and_reopen_and_a_listener_can_use_neither():
    async def scenario(fake):
        async with station(fake) as st:
            kicked = []
            w = World()
            access = AccessControl([ClientAuth("phone", password_hash="x")], Access(max_listeners=2))
            access.guard = w.guard
            phone = await connect(st, "phone", access=access,
                                  kick_listener=lambda account: kicked.append(account) or account == "club1")
            await phone.say(cmd="listener_kick", id=1, account="club1")
            await phone.say(cmd="listener_kick", id=2, account="phone")
            assert phone.result(1)["ok"] and phone.result(2)["reason"] == "unknown_listener" and kicked == ["club1", "phone"]
            w.sample = HOT
            w.run(HOLD_S + 1, listeners=0)
            await phone.say(cmd="listeners_reopen", id=3)
            assert phone.result(3)["reason"] == "still_overloaded" and "87 °C" in phone.result(3)["detail"]
            w.sample = CALM
            w.run(1, listeners=0)
            await phone.say(cmd="listeners_reopen", id=4)
            assert phone.result(4)["ok"] and not w.guard.suspended
            visitor = await connect(st, "club1", role="listener", kick_listener=lambda a: kicked.append(a) or True)
            for ident, message in ((5, {"cmd": "listener_kick", "account": "club2"}), (6, {"cmd": "listeners_reopen"})):
                await visitor.say(id=ident, **message)
                assert visitor.result(ident)["reason"] == "forbidden"
            assert kicked == ["club1", "phone"]
    run(scenario)
