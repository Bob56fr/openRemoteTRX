# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sonde de qualité réseau dans la passerelle (docs/netprobe-cahier-des-charges.md) : battements, coupures, diagnostic,
profil VPN partagé, journal et statistiques, session ; et surtout : la sonde ne touche JAMAIS à l'émission."""
import asyncio
import json

import pytest

from trxstation import config as cfgmod
from trxstation.config import Netprobe
from trxstation.netprobe.probe import NetProbeHub
from trxstation.netprobe.report import ReportInvalid, clean_report
from trxstation.netprobe.store import NetStore
from trxstation.netprobe.vpn import private_address

from test_api import connect, run, station, until

WALL0 = 1_762_700_000_000


class Clock:
    def __init__(self):
        self.mono, self.wall = 0, WALL0

    def advance(self, ms):
        self.mono += ms
        self.wall += ms


def make_hub(tmp_path, clock, **cfg):
    alerts = []
    hub = NetProbeHub(Netprobe(**cfg), tmp_path, alert=lambda t, m: alerts.append((t, m)),
                      mono_ms=lambda: clock.mono, wall_ms=lambda: clock.wall)
    return hub, alerts


class Peer:
    """Un client qui répond (ou non) aux net_ping de la station."""

    def __init__(self, hub, clock, client_id="phone", device="a" * 32, agent="android 0.53.0", source="192.168.27.2",
                 role="operator"):
        self.messages, self.clock, self.hub, self.answer, self.delay = [], clock, hub, True, 40
        self.probe = hub.open(client_id, role, device, agent, source, self.messages.append)

    def run(self, seconds, step=250):
        for _ in range(int(seconds * 1000 / step)):
            self.clock.advance(step)
            self.hub.tick()
            for m in list(self.messages):
                if m.get("type") == "net_ping" and self.answer and not m.get("_done"):
                    m["_done"] = True
                    self.probe.on_pong({"seq": m["seq"], "t": m["t"], "tr": 0})

    def of_type(self, kind):
        return [m for m in self.messages if m.get("type") == kind]


def report(clock, **fields):
    base = {"t": clock.wall, "net_type": "4g", "health_ok": 0, "health_fail": 0}
    base.update(fields)
    return clean_report(base)


def test_beats_level_and_state_net(tmp_path):
    clock = Clock()
    hub, _ = make_hub(tmp_path, clock)
    peer = Peer(hub, clock)
    peer.run(5)
    assert peer.probe.state()["level"] == "gray"                   # moins de 10 s de mesures
    peer.run(10)
    net = peer.probe.state()
    assert net["level"] == "green" and net["loss_pct"] == 0.0 and net["outage"] is False
    assert len(peer.of_type("net_ping")) == 15                     # un battement par seconde
    assert net["thresholds"] == {"rtt_warn": 250, "rtt_alert": 600, "loss_warn": 2.0, "loss_alert": 10.0}
    assert net["vpn"] == []


def test_client_ping_gets_an_immediate_pong(tmp_path):
    clock = Clock()
    hub, _ = make_hub(tmp_path, clock)
    peer = Peer(hub, clock)
    clock.advance(1234)
    peer.probe.on_ping({"seq": 9, "t": 77, "w": WALL0})
    assert peer.of_type("net_pong")[-1] == {"type": "net_pong", "seq": 9, "t": 77, "tr": 1234}


def test_forged_or_duplicate_echo_is_ignored(tmp_path):
    clock = Clock()
    hub, _ = make_hub(tmp_path, clock)
    peer = Peer(hub, clock)
    peer.answer = False
    peer.run(2)
    ping = peer.of_type("net_ping")[0]
    peer.probe.on_pong({"seq": ping["seq"], "t": ping["t"] + 1, "tr": 0})      # mauvaise heure d'envoi
    peer.probe.on_pong({"seq": 999, "t": 0, "tr": 0})                         # numéro jamais envoyé
    assert peer.probe.stats(10_000)["received"] == 0


def test_outage_detected_diagnosed_journalised_and_alerted(tmp_path):
    clock = Clock()
    hub, alerts = make_hub(tmp_path, clock, alert_outage_s=5)
    peer = Peer(hub, clock)
    peer.run(12)
    peer.answer = False
    peer.run(4)
    assert peer.probe.state()["outage"] is True and peer.probe.state()["level"] == "red"
    peer.run(8)
    hub.add_reports(peer.probe, [report(clock, health_fail=3)])               # /health aussi perdu : réseau ou tunnel
    peer.answer = True
    peer.run(1)
    assert peer.probe.state()["outage"] is False
    assert peer.probe.state()["level"] == "red"                                # 12 battements perdus sur 60 s : 20 %
    peer.run(16)                                                               # le diagnostic attend 15 s
    events = peer.of_type("net_event")
    assert [e["event"] for e in events] == ["outage"]
    outage = events[0]["outage"]
    assert outage["diagnosis"] == "mobile_or_tunnel" and outage["kind"] == "in_session"
    assert 10_000 <= outage["duration_ms"] <= 14_000 and outage["agent"] == "android 0.53.0"
    stored = hub.store.outages()
    assert len(stored) == 1 and stored[0]["diagnosis"] == "mobile_or_tunnel"
    assert len(alerts) == 1 and "mobile" in alerts[0][1]
    assert peer.probe.state()["last_outage"]["diagnosis"] == "mobile_or_tunnel"
    peer.run(50)                                                               # pertes sorties de la fenêtre de 60 s
    assert peer.probe.state()["level"] == "orange"                             # coupure close depuis moins de 2 min
    peer.run(60)
    assert peer.probe.state()["level"] == "green"


def test_webrtc_diagnosis_when_health_still_answers(tmp_path):
    clock = Clock()
    hub, _ = make_hub(tmp_path, clock)
    peer = Peer(hub, clock)
    peer.run(12)
    peer.answer = False
    peer.run(6)
    hub.add_reports(peer.probe, [report(clock, health_ok=1)])
    peer.answer = True
    peer.run(17)
    assert peer.of_type("net_event")[0]["outage"]["diagnosis"] == "webrtc"


def test_outage_without_client_data_is_unknown_and_short_outage_is_not_alerted(tmp_path):
    clock = Clock()
    hub, alerts = make_hub(tmp_path, clock)                                     # alerte à partir de 10 s
    peer = Peer(hub, clock)
    peer.run(12)
    peer.answer = False
    peer.run(5)
    peer.answer = True
    peer.run(17)
    assert peer.of_type("net_event")[0]["outage"]["diagnosis"] == "unknown"
    assert alerts == []


def test_reconnection_of_the_same_device_closes_a_disconnect_outage(tmp_path):
    clock = Clock()
    hub, _ = make_hub(tmp_path, clock)
    peer = Peer(hub, clock)
    peer.run(12)
    hub.close(peer.probe)
    clock.advance(20_000)
    again = Peer(hub, clock)
    hub.add_reports(again.probe, [report(clock, cell_changed=True)])
    again.run(16)
    outage = hub.store.outages()[0]
    assert outage["kind"] == "disconnect" and outage["diagnosis"] == "phone_radio"
    assert 20_000 <= outage["duration_ms"] <= 21_000


def test_listener_is_measured_but_never_journalised(tmp_path):
    clock = Clock()
    hub, _ = make_hub(tmp_path, clock)
    visitor = Peer(hub, clock, client_id="club1", role="listener")
    visitor.run(12)
    visitor.answer = False
    visitor.run(6)
    visitor.answer = True
    visitor.run(17)
    assert visitor.probe.state()["level"] in ("orange", "red") and "vpn" not in visitor.probe.state()
    assert hub.store.outages() == [] and not list(tmp_path.glob("netprobe/*.jsonl"))
    assert visitor.of_type("net_event") == []


def test_regular_outages_point_to_a_shared_vpn_profile(tmp_path):
    """Incident du 2026-11-09 : coupures de ~4 s toutes les ~28 s, signal correct."""
    clock = Clock()
    hub, alerts = make_hub(tmp_path, clock, alert_outage_s=0)
    peer = Peer(hub, clock)
    peer.run(12)
    for _ in range(6):
        peer.answer = False
        peer.run(5)
        hub.add_reports(peer.probe, [report(clock, health_fail=1, rsrp_dbm=-90, sinr_db=15)])
        peer.answer = True
        peer.run(23)
    peer.run(16)
    diagnoses = [e["outage"]["diagnosis"] for e in peer.of_type("net_event") if e["event"] == "outage"]
    assert diagnoses[0] == "mobile_or_tunnel" and diagnoses[-1] == "vpn_shared"
    warnings = [e["warning"] for e in peer.of_type("net_event") if e["event"] == "vpn_shared"]
    assert warnings and warnings[0]["kind"] == "pattern" and 25_000 < warnings[0]["period_ms"] < 31_000
    assert len([a for a in alerts if "VPN" in a[0]]) == 1                       # une alerte par 24 h


def test_shared_vpn_profile_same_time_and_alternate(tmp_path):
    clock = Clock()
    hub, alerts = make_hub(tmp_path, clock)
    pc = Peer(hub, clock, client_id="bob", device="b" * 32, agent="page Windows")
    phone = Peer(hub, clock, client_id="phone", device="a" * 32, agent="android 0.53.0")     # même adresse, même moment
    warning = phone.of_type("net_event")[0]["warning"]
    assert warning["kind"] == "same_time" and warning["address"] == "192.168.27.2"
    assert set(warning["agents"]) == {"page Windows", "android 0.53.0"}
    assert pc.of_type("net_event")                                               # tous les opérateurs sont prévenus
    assert len(alerts) == 1
    hub.vpn.ignore("192.168.27.2")
    assert phone.probe.state()["vpn"] == []
    # D2 : une autre adresse, un appareil part, un autre arrive 2 min après
    first = Peer(hub, clock, client_id="bob", device="c" * 32, agent="page Linux", source="10.8.0.5")
    hub.close(first.probe)
    clock.advance(120_000)
    second = Peer(hub, clock, client_id="phone", device="d" * 32, agent="android", source="10.8.0.5")
    assert second.probe.state()["vpn"][0]["kind"] == "alternate"
    # même appareil qui revient : rien ; adresses publique et locale : jamais
    clock.advance(1_000)
    hub.close(second.probe)
    Peer(hub, clock, client_id="phone", device="d" * 32, agent="android", source="10.8.0.5")
    hub.vpn.warnings.clear()
    Peer(hub, clock, client_id="x", device="e" * 32, source="203.0.113.9")
    Peer(hub, clock, client_id="y", device="f" * 32, source="203.0.113.9")
    Peer(hub, clock, client_id="z", device="1" * 32, source="127.0.0.1")
    Peer(hub, clock, client_id="w", device="2" * 32, source="127.0.0.1")
    assert hub.vpn.active() == []


def test_private_addresses():
    assert private_address("192.168.27.2") and private_address("10.8.0.1") and private_address("100.64.1.2")
    assert private_address("::ffff:192.168.1.5") and private_address("fd00::1")
    assert not private_address("127.0.0.1") and not private_address("8.8.8.8") and not private_address("nom")


def test_loss_alert_once_until_the_link_recovers(tmp_path):
    clock = Clock()
    hub, alerts = make_hub(tmp_path, clock, alert_outage_s=0, alert_cooldown_s=30)
    peer = Peer(hub, clock)
    original = peer.probe.on_pong
    count = {"n": 0}

    def lossy(params):                                                          # un écho sur quatre perdu : 25 %
        count["n"] += 1
        if count["n"] % 4:
            original(params)
    peer.probe.on_pong = lossy
    peer.run(70)
    assert len([a for a in alerts if "degradee" in a[0]]) == 1


def test_hours_stats_thresholds_and_clear(tmp_path):
    clock = Clock()
    hub, _ = make_hub(tmp_path, clock)
    peer = Peer(hub, clock)
    hub.add_reports(peer.probe, [report(clock, net_type="wifi")])
    peer.probe.on_report(report(clock, net_type="wifi", degraded=True))
    peer.run(65)
    stats = hub.stats(30, "")
    assert stats["summary"]["connected_s"] >= 60 and stats["summary"]["outages"] == 0
    assert stats["devices"][0]["agent"] == "android 0.53.0"
    wifi = stats["thresholds"]["wifi"]
    assert sum(n for n, _ in wifi["rtt_hist"]) >= 6 and sum(d for _, d in wifi["rtt_hist"]) == 1
    assert wifi["proposed"] == {"rtt": None, "loss": None} and wifi["chosen"] is False   # moins de 7 jours
    hub.set_thresholds({"net_type": "wifi", "rtt_warn": 300, "rtt_alert": 700, "loss_warn": 3, "loss_alert": 12})
    assert peer.probe.state()["thresholds"]["rtt_warn"] == 300
    assert hub.stats(30, "")["thresholds"]["wifi"]["chosen"] is True
    assert len(json.dumps(hub.stats(30, ""))) < 60_000                          # tient dans un message du canal
    hub.clear("bob")
    assert hub.stats(30, "")["summary"]["connected_s"] == 0
    assert peer.probe.state()["thresholds"]["rtt_warn"] == 300                   # « Tout effacer » garde les seuils
    hub.set_thresholds({"net_type": "wifi", "reset": True})
    assert peer.probe.state()["thresholds"]["rtt_warn"] == 250


def test_store_prunes_old_files_and_lines(tmp_path):
    now = {"ms": WALL0}
    store = NetStore(tmp_path, log_days=7, stats_days=30, wall_ms=lambda: now["ms"])
    day = 86_400_000
    store.log({"ts": WALL0 - 10 * day, "kind": "mesure"})
    store.log({"ts": WALL0, "kind": "mesure"})
    store.add_outage({"start_ms": WALL0 - 40 * day, "end_ms": WALL0 - 40 * day + 5000, "duration_ms": 5000})
    store.add_outage({"start_ms": WALL0 - day, "end_ms": WALL0 - day + 5000, "duration_ms": 5000})
    store.prune()
    assert len(list(tmp_path.glob("????-??-??.jsonl"))) == 2                     # J-10 effacé ; J-1 (coupure) et J gardés
    assert len(store.outages()) == 1


def test_bad_reports_are_refused():
    for bad in ({"t": 5}, {"t": WALL0, "rsrp_dbm": 3}, {"t": WALL0, "net_type": "6g"}, {"t": WALL0, "degraded": "oui"},
                {"t": WALL0, "health_ok": 1000}, {"t": WALL0, "ice": "boom"}, "texte"):
        with pytest.raises(ReportInvalid):
            clean_report(bad)
    assert clean_report({"t": WALL0, "futur": 1})["rsrp_dbm"] is None          # champ inconnu ignoré, absents à null


def test_config_defaults_validation_and_supervisor_untouched(tmp_path):
    cfg = cfgmod.Config()
    assert cfg.netprobe.enabled and cfg.netprobe.rtt_warn_ms == 250 and cfg.netprobe.internet_target == "1.1.1.1"
    d = {"netprobe": {"rtt_warn_ms": 700, "rtt_alert_ms": 600, "lan_target": "box", "heartbeat_interval_s": 0.1}}
    _, problems = cfgmod.build(d)
    assert any("rtt_warn_ms doit être plus petit" in p for p in problems) or any("lan_target" in p for p in problems)
    assert any("heartbeat_interval_s" in p for p in problems) and any("lan_target" in p for p in problems)
    cfg.supervisor.notify_url = "https://ntfy.sh/sujet-essai"
    text = cfgmod.render_toml(cfg)
    path = tmp_path / "station.toml"
    path.write_text(text, encoding="utf-8")
    again, problems = cfgmod.load_unchecked(path)
    assert again.supervisor.notify_url == "https://ntfy.sh/sujet-essai" and again.netprobe == cfg.netprobe
    old = text[:text.index("[netprobe]")] + (text[text.index("[netprobe]"):] + "\n\n").split("\n\n", 1)[1]
    path.write_text(old, encoding="utf-8")                                       # station.toml d'avant : défauts
    assert cfgmod.load_unchecked(path)[0].netprobe == Netprobe()


# ---------------------------------------------------------------------- dans une vraie session

def test_session_announces_netprobe_and_answers_without_touching_the_ptt(tmp_path):
    async def scenario(fake):
        async with station(fake) as st:
            hub = NetProbeHub(Netprobe(), tmp_path)
            phone = await connect(st, "phone", netprobe=hub, device="a" * 32, agent="page Windows", source="192.168.1.20")
            assert "netprobe" in phone.of_type("hello")[0]["features"]
            hub.tick()
            ping = phone.of_type("net_ping")[0]
            await phone.say(cmd="net_pong", seq=ping["seq"], t=ping["t"], tr=5)
            await phone.say(cmd="net_ping", seq=1, t=10)
            assert phone.of_type("net_pong")[0]["seq"] == 1
            await until(lambda: phone.of_type("state") and "net" in phone.of_type("state")[-1])
            assert phone.of_type("state")[-1]["net"]["level"] == "gray"
            await phone.say(cmd="net_report", report={"t": WALL0 + 10**9, "net_type": "wifi"})
            await phone.say(cmd="net_stats", id=1, days=7)
            assert phone.result(1)["ok"] and phone.result(1)["stats"]["days"] == 7
            await phone.say(cmd="net_thresholds", id=2, net_type="wifi", rtt_warn=300, rtt_alert=700, loss_warn=2, loss_alert=9)
            assert phone.result(2)["thresholds"]["wifi"]["loss_alert"] == 9
            await phone.say(cmd="net_clear", id=3)
            assert phone.result(3)["ok"]
            # non-régression de la sécurité : un flot de messages de la sonde, valides ou non, ne change rien à l'émission
            before = st.ctrl.snapshot()
            for i in range(25):
                await phone.say(cmd="net_ping", seq=i, t="x")
                await phone.say(cmd="net_pong", seq=i, t=i, tr=i)
            assert st.ctrl.snapshot().state == before.state == "RX" and st.ctrl.snapshot().owner is None
            assert not [m for m in phone.of_type("result") if m.get("id") is None]   # aucune réponse aux battements
    run(scenario)


def test_session_without_netprobe_and_listener_whitelist(tmp_path):
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            assert "netprobe" not in phone.of_type("hello")[0]["features"]
            await phone.say(cmd="net_ping", seq=1, t=1)                       # ignoré sans réponse
            await phone.say(cmd="net_stats", id=4)
            assert phone.result(4)["reason"] == "netprobe_unavailable"
            assert "net" not in phone.of_type("state")[-1]
    run(scenario)


def test_hub_runs_until_stopped(tmp_path):
    async def main():
        hub = NetProbeHub(Netprobe(), tmp_path)
        sent = []
        hub.open("phone", "operator", "", "", "", sent.append)
        stop = asyncio.Event()
        task = asyncio.create_task(hub.run(stop, every_s=0.01))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, 2)
        assert any(m["type"] == "net_ping" for m in sent)
    asyncio.run(main())
