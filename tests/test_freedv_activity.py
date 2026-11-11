# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Activité FreeDV (module freedv_activity) : calculs, lecture de FreeDV Reporter (faux serveur), message publié,
manifeste et réglage [freedv] locator. Jamais de réseau."""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from trxstation import config as cfgmod
from trxstation.freedv import activity as act
from trxstation.freedv import reporter as rep
from trxstation.freedv.activity_service import ActivityService, build_message
from trxstation.modules.registry import selected_manifests

NOW = 1_794_338_400.0


def iso(t: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


# ---------------------------------------------------------------- calculs
def test_locator_and_distance():
    assert act.valid_locator("JN18du") and act.valid_locator("in87") and not act.valid_locator("JN1") and not act.valid_locator("ZZ99")
    assert act.locator_latlon("xx") is None
    assert 40 < act.distance_km("IN87", "JN18") < 600              # Bretagne -> Paris
    assert 8000 < act.distance_km("IN87", "CM97") < 9500           # Bretagne -> Californie
    assert act.distance_km("IN87", "") is None


def test_state_groups_by_frequency_with_a_reception_note():
    st = act.ReporterState()
    st.apply("new_connection", {"sid": "a", "callsign": "w6gok<script>", "grid_square": "CM97", "freq": 14236100, "mode": "RADEV1",
                                "transmitting": True})
    st.apply("new_connection", {"sid": "b", "callsign": "F4ABC", "grid_square": "JN18", "freq": 14235900, "mode": "RADEV1"})
    st.apply("rx_report", {"sid": "b", "callsign": "W6GOK", "snr": 6, "mode": "RADEV1", "last_update": iso(NOW - 10)})
    st.apply("new_connection", {"sid": "c", "callsign": "VK5KVA", "freq": 7177000, "mode": "RADEV1", "last_tx": iso(NOW - 240)})
    st.apply("new_connection", {"sid": "d", "callsign": "OLD", "freq": 3625000, "mode": "RADEV1", "last_tx": iso(NOW - 3600)})
    st.apply("new_connection", {"sid": "e", "callsign": "VHF", "freq": 144_500_000, "transmitting": True, "mode": "RADEV1"})
    out = st.snapshot(NOW, "IN87")
    assert [g["f"] for g in out] == [14236000, 7177000]           # 3,6 MHz trop ancien, 2 m hors HF
    top = out[0]
    assert top["tx"] == [{"c": "W6GOKSCRIPT", "km": act.distance_km("IN87", "CM97"), "on": True, "min": None, "m": "RADEV1"}]
    assert top["rx"][0]["c"] == "F4ABC" and top["rx"][0]["snr"] == 6
    assert top["note"] == 0.8 + 3.0                                # émetteur lointain 2 × 0,4 + voisin < 800 km qui décode
    assert out[1]["tx"][0]["min"] == 4 and out[1]["note"] == 0.4  # distance inconnue
    no_loc = st.snapshot(NOW, "")
    assert no_loc[0]["tx"][0]["km"] is None and all(g["note"] <= 2 for g in no_loc)
    st.apply("remove_connection", {"sid": "a"})
    assert all(t["c"] != "W6GOKSCRIPT" for g in st.snapshot(NOW, "IN87") for t in g["tx"])
    assert "a" not in st.stations


def test_state_rejects_malformed_or_excessive_input():
    st = act.ReporterState()
    for bad in (("new_connection", None), ("new_connection", {"sid": 5}), ("new_connection", {"sid": "x" * 65}),
                ("inconnu", {"sid": "z"}), ("freq_change", {"sid": "f", "freq": "14 MHz"}), ("freq_change", {"sid": "g", "freq": float("nan")})):
        st.apply(*bad)
    assert set(st.stations) <= {"f", "g"} and all(s.get("freq") == 0 for s in st.stations.values())
    st.apply("rx_report", {"sid": "r", "snr": 999, "last_update": "pas une date"})
    assert st.rx["r"][:2] == (None, None)
    for i in range(act.MAX_STATIONS + 50):
        st.apply("new_connection", {"sid": f"s{i}", "freq": 14236000, "transmitting": True, "mode": "RADEV1"})
    assert len(st.stations) == act.MAX_STATIONS
    out = st.snapshot(NOW)
    assert len(out) == 1 and len(out[0]["tx"]) == act.MAX_TX


# ---------------------------------------------------------------- lecture de FreeDV Reporter (faux serveur)
class FakeReporter:
    def __init__(self, polls: list[str]) -> None:
        self.polls, self.posts, self.urls = list(polls), [], []

    def get(self, url, ua):
        self.urls.append(url)
        assert ua.startswith("openRemoteTRX")
        if "sid=" not in url:
            return '0{"sid":"Ab_c-1","upgrades":["websocket"],"pingInterval":25000}'
        if not self.polls:
            raise rep.ReporterError("fin du faux serveur")
        return self.polls.pop(0)

    def post(self, url, body, ua):
        self.posts.append(body)


def test_session_reads_events_answers_pings_and_sends_only_the_observer_role():
    bulk = json.dumps(["bulk_update", [["new_connection", {"sid": "a", "callsign": "W6GOK", "freq": 14236000, "transmitting": True,
                                                            "mode": "RADEV1"}], ["bogus"], "x"]])
    fake = FakeReporter(["40{\"sid\":\"q\"}" + rep.SEP + "42" + bulk, "2", "42[\"freq_change\",{\"sid\":\"a\",\"freq\":7177000}]",
                         "42pas du json", "1"])
    st, lock = act.ReporterState(), threading.Lock()
    client = rep.ReporterClient(st, lock, user_agent="openRemoteTRX/test", get=fake.get, post=fake.post)
    with pytest.raises(rep.ReporterError, match="fermée"):
        client.session(threading.Event())
    assert fake.posts[0] == '40{"role": "view", "protocol_version": 2}' and fake.posts[1:] == ["3"]   # rien d'autre envoyé
    assert all("sid=Ab_c-1" in u for u in fake.urls[1:])
    assert st.stations["a"]["freq"] == 7177000 and client.status == rep.OK


def test_run_reports_the_error_and_retries_without_ever_raising():
    fake = FakeReporter([])
    fake.get = lambda url, ua: "<html>maintenance</html>"
    client = rep.ReporterClient(act.ReporterState(), threading.Lock(), get=fake.get, post=fake.post)
    stop = threading.Event()
    waits = []
    stop.wait = lambda d: (waits.append(d), stop.set())
    client.run(stop)
    assert client.status == rep.ERROR and "injoignable" in client.message and waits == [15.0]
    with pytest.raises(rep.ReporterError):
        rep.parse_open('0{"sid": "a b"}')
    assert rep.events_of("42[]") == [] and rep.events_of('42["x"]') == []


# ---------------------------------------------------------------- message publié
def test_message_is_empty_unless_connected_and_says_whether_the_locator_is_known():
    st, lock = act.ReporterState(), threading.Lock()
    st.apply("new_connection", {"sid": "a", "callsign": "W6GOK", "freq": 14236000, "transmitting": True, "mode": "RADEV1"})
    client = rep.ReporterClient(st, lock)
    m = build_message(client, st, lock, "", NOW)
    assert m["kind"] == "freedv_activity" and m["retain"] == "snapshot" and m["status"] == "connexion" and m["freqs"] == []
    client.status = rep.OK
    m = build_message(client, st, lock, "IN87", NOW)
    assert m["locator"] is True and m["total"] == 1 and m["freqs"][0]["f"] == 14236000 and m["t"] == int(NOW)
    assert "scope" not in m                                     # TOUS les clients, visiteurs compris
    json.dumps(m)


def test_service_publishes_to_the_bus_and_survives_a_refusal():
    sent = []

    class Bus:
        connected = SimpleNamespace(is_set=lambda: True)

        async def client_message(self, **m):
            sent.append(m)
            if len(sent) == 2:
                raise ConnectionError("cœur redémarré")

    st, lock = act.ReporterState(), threading.Lock()
    svc = ActivityService("JN18", Bus(), reporter=rep.ReporterClient(st, lock), clock=lambda: NOW)
    asyncio.run(svc.publish()); asyncio.run(svc.publish()); asyncio.run(svc.publish())
    assert len(sent) == 3 and sent[0]["kind"] == "freedv_activity"
    asyncio.run(ActivityService("", None).publish())             # sans bus : rien, aucune erreur


# ---------------------------------------------------------------- manifeste et configuration
def test_manifest_gives_no_right_on_the_rig():
    selected, problems = selected_manifests(cfgmod.Modules(run=["freedv_activity"]))
    assert problems == [] and len(selected) == 1
    m = selected[0]
    assert m.entry == "trxstation.freedv.activity_service" and not m.rights.commands and not m.rights.events
    assert m.rights.client_messages is True and not m.rights.client_commands


def test_locator_setting():
    assert cfgmod.Freedv().locator == ""
    assert cfgmod._freedv_problems(cfgmod.Freedv(locator="jn18du")) == []
    assert cfgmod._freedv_problems(cfgmod.Freedv(locator="JN1")) == [
        "[freedv] locator : locator Maidenhead de 4 ou 6 caractères attendu (ex. JN18 ou JN18du), ou vide"]
    cfg = cfgmod.Config()
    cfg.freedv = cfgmod.Freedv(locator="IN87")
    import tomllib
    assert tomllib.loads(cfgmod.render_toml(cfg))["freedv"]["locator"] == "IN87"


def test_shared_example_has_exactly_the_fields_published_by_the_station():
    from pathlib import Path
    ex = json.loads((Path(__file__).parent / "protocol" / "messages.json").read_text(encoding="utf-8"))["module_freedv_activity"]
    assert ex["type"] == "module" and ex["module"] == "freedv_activity"
    st, lock = act.ReporterState(), threading.Lock()
    st.apply("new_connection", {"sid": "a", "callsign": "W6GOK", "grid_square": "CM97", "freq": 14236000, "transmitting": True,
                                "mode": "RADEV1"})
    st.apply("rx_report", {"sid": "a", "snr": 5, "mode": "RADEV1", "last_update": iso(NOW)})
    client = rep.ReporterClient(st, lock)
    client.status = rep.OK
    m = build_message(client, st, lock, "IN87", NOW)
    assert set(m) == set(ex["data"])
    assert set(m["freqs"][0]) == set(ex["data"]["freqs"][0])
    assert set(m["freqs"][0]["tx"][0]) == set(ex["data"]["freqs"][0]["tx"][0])
    assert set(m["freqs"][0]["rx"][0]) == set(ex["data"]["freqs"][0]["rx"][0])
