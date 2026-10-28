# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""État des flux du Cluster DX pour les pages : compteurs par source et verdict selon la vitesse du flux."""
from __future__ import annotations

from types import SimpleNamespace

from trxstation.cluster.engine import SOURCE_WINDOW_S, Engine
from trxstation.cluster.feed import CONNECTED, DISABLED, FAILED, RECONNECTING
from trxstation.cluster.service import QUIET_AFTER_S, page_summary


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def engine(clock):
    cache = SimpleNamespace(add=lambda *a, **k: None, counters={"received": 0, "filtered": 0, "duplicates": 0,
                                                                 "expired": 0, "evicted": 0})
    return Engine(cache, clock=clock)


def src(name, kind):
    return SimpleNamespace(name=name, kind=kind, spot_kind="cb" if kind == "web" else "cluster", enabled=True)


DX = "DX de F4XYZ:     14025.0  K1ABC        CW 22 dB                       1234Z"


def test_each_source_is_counted_on_its_own_over_ten_minutes():
    clock = Clock()
    eng = engine(clock)
    rbn, cl = src("RBN", "rbn"), src("on0dxk", "telnet")
    for _ in range(30):
        eng.handle_line(rbn, DX)
    eng.handle_line(cl, DX)
    clock.t += 5
    assert eng.source_stats("RBN") == {"received": 30, "last_10min": 30, "last_spot_age_s": 5.0}
    assert eng.source_stats("on0dxk")["last_10min"] == 1
    assert eng.source_stats("inconnu") == {"received": 0, "last_10min": 0, "last_spot_age_s": None}
    clock.t += SOURCE_WINDOW_S
    assert eng.source_stats("RBN")["last_10min"] == 0 and eng.source_stats("RBN")["received"] == 30


def test_web_spots_keep_their_real_age():
    clock = Clock()
    eng = engine(clock)
    web = src("clusterdx", "web")
    eng.handle_web(web, [SimpleNamespace(age_s=120.0, raw=None), SimpleNamespace(age_s=40.0, raw=None)], 0)
    assert eng.source_stats("clusterdx")["last_spot_age_s"] == 40.0


def feed_of(*rows):
    sources = [src(name, kind) for name, kind, _ in rows]
    states = {name: SimpleNamespace(state=state, retry_in_s=30.0 if state == RECONNECTING else None,
                                    last_code="callsign_refused" if state == FAILED else "") for name, _, state in rows}
    return SimpleNamespace(sources=sources, states=states)


def test_verdict_depends_on_the_usual_speed_of_each_feed():
    clock = Clock()
    eng = engine(clock)
    feed = feed_of(("RBN", "rbn", CONNECTED), ("on0dxk", "telnet", CONNECTED), ("db0sue", "telnet", DISABLED),
                   ("clusterdx", "web", CONNECTED))
    eng.handle_line(feed.sources[0], DX)
    eng.handle_line(feed.sources[1], DX)
    eng.handle_web(feed.sources[3], [SimpleNamespace(age_s=10.0, raw=None)], 0)
    clock.t += QUIET_AFTER_S["rbn"] + 1                    # 5 min sans spot : RBN calme, le cluster pas encore
    by = {s["name"]: s for s in page_summary(feed, eng)["sources"]}
    assert by["RBN"]["verdict"] == "calme" and by["on0dxk"]["verdict"] == "ok" and by["clusterdx"]["verdict"] == "ok"
    assert by["db0sue"]["verdict"] == "reserve"           # cluster de secours : pas une panne
    clock.t += QUIET_AFTER_S["telnet"]
    by = {s["name"]: s for s in page_summary(feed, eng)["sources"]}
    assert by["on0dxk"]["verdict"] == "calme" and by["clusterdx"]["verdict"] == "ok"   # page CB : 2 h de patience


def test_failed_and_waiting_sources_and_no_feed():
    eng = engine(Clock())
    feed = feed_of(("RBN", "rbn", FAILED), ("on0dxk", "telnet", RECONNECTING))
    summary = page_summary(feed, eng)
    by = {s["name"]: s for s in summary["sources"]}
    assert by["RBN"]["verdict"] == "echec" and by["RBN"]["code"] == "callsign_refused"
    assert by["on0dxk"]["verdict"] == "attente" and by["on0dxk"]["retry_in_s"] == 30.0
    assert summary["kind"] == "cluster_status" and summary["health"] == "red"
    assert page_summary(None, None) == {"kind": "cluster_status", "health": "off", "sources": [], "bands": {}}


def test_active_spots_are_counted_per_band_for_the_band_buttons():
    eng = engine(Clock())
    eng.cache.spots = lambda: [SimpleNamespace(band="20m"), SimpleNamespace(band="20m"), SimpleNamespace(band="40m"),
                               SimpleNamespace(band=None)]
    assert page_summary(feed_of(("RBN", "rbn", CONNECTED)), eng)["bands"] == {"20m": 2, "40m": 1}


def test_service_sends_the_status_on_change_then_every_third_write(tmp_path):
    import asyncio

    from trxstation.cluster.service import ClusterService
    from trxstation.setup_wizard import dummy_config

    sent = []

    class Bus:
        on_event = on_connect = on_gap = None

        async def client_message(self, **message):
            sent.append(message)

    async def scenario():
        cfg = dummy_config()
        cfg.supervisor.state_dir = str(tmp_path)
        service = ClusterService(cfg, tmp_path / "station.toml", bus_client=Bus())
        for _ in range(6):                                    # 6 écritures de status.json (5 s chacune en vrai)
            service._status()
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)
    asyncio.run(scenario())
    statuses = [m for m in sent if m.get("kind") == "cluster_status"]
    assert len(statuses) == 3                                 # 1re écriture (pastille nouvelle), puis 3e et 6e
    assert any(m.get("kind") == "module_state" for m in sent)  # le texte de la pastille, une seule fois
