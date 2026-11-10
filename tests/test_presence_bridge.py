# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Présence de groupe, lot 3b : bus (call / reply), pont, session (`friends`), service, console, trx-monitor."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation import config as cfgmod
from trxstation.devtools.fake_presence_relay import FakeRelay
from trxstation.gateway.api.protocol import ProtocolError, parse_command
from trxstation.gateway.api.session import ControlSession
from trxstation.modules.bus import BusServer, CommandRefused
from trxstation.modules.client import CallRefused, ModuleClient
from trxstation.modules.gateway_bridge import ModuleBridge
from trxstation.modules.manifest import parse_manifest
from trxstation.monitor.model import presence_row
from trxstation.presence import actions
from trxstation.presence.engine import ActionRefused
from trxstation.presence.service import CONSOLE_REPLY, CONSOLE_REQUEST, PresenceService

SECRETS = {"presence": "secret-presence", "cluster": "secret-cluster"}


def manifest(name: str, *, client_commands: bool):
    return parse_manifest({"module": {"name": name, "version": "0.1.0", "api": "1.0", "entry": "a.b"},
                           "rights": {"events": ["operator_activity"], "client_messages": True,
                                      "client_commands": client_commands}})


async def until(pred, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condition jamais atteinte")
        await asyncio.sleep(0.01)


# ------------------------------------------------------------------ bus : appel du cœur vers UN module
def test_call_reaches_one_module_and_returns_its_result_or_refusal():
    async def scenario():
        bus = BusServer({"presence": manifest("presence", client_commands=True),
                         "cluster": manifest("cluster", client_commands=False)}, SECRETS, state_provider=dict)
        await bus.start()
        seen = []

        async def on_call(data):
            seen.append(data)
            if data["action"] == "refuse":
                raise CallRefused("not_admin", "réservé")
            if data["action"] == "boom":
                raise RuntimeError("panne")
            if data["action"] == "slow":
                await asyncio.sleep(1.0)
            return {"echo": data["action"]}

        client = ModuleClient("presence", SECRETS["presence"], port=bus.port, heartbeat_s=0.05)
        client.on_call = on_call
        task = asyncio.ensure_future(client.run_session())
        other = ModuleClient("cluster", SECRETS["cluster"], port=bus.port, heartbeat_s=0.05)
        other_task = asyncio.ensure_future(other.run_session())
        await until(lambda: {"presence", "cluster"} <= set(bus.sessions))
        assert await bus.call("presence", {"action": "view"}) == {"echo": "view"}
        with pytest.raises(CommandRefused) as err:
            await bus.call("presence", {"action": "refuse"})
        assert (err.value.code, str(err.value)) == ("not_admin", "réservé")
        with pytest.raises(CommandRefused) as err:
            await bus.call("presence", {"action": "boom"})
        assert err.value.code == "internal"
        with pytest.raises(CommandRefused) as err:
            await bus.call("cluster", {"action": "view"})
        assert err.value.code == "forbidden"                       # pas de droit client_commands
        with pytest.raises(CommandRefused) as err:
            await bus.call("absent", {})
        assert err.value.code == "module_absent"
        with pytest.raises(CommandRefused) as err:
            await bus.call("presence", {"action": "slow"}, timeout_s=0.2)
        assert err.value.code == "timeout"
        pending = asyncio.ensure_future(bus.call("presence", {"action": "slow"}))
        await asyncio.sleep(0.1)
        client.stop()                                               # module perdu pendant l'appel
        with pytest.raises(CommandRefused) as err:
            await pending
        assert err.value.code == "module_absent"
        assert [d["action"] for d in seen][:3] == ["view", "refuse", "boom"]
        for t in (task, other_task):
            t.cancel()
        other.stop()
        await bus.stop()
    asyncio.run(scenario())


# ------------------------------------------------------------------ pont : visiteurs, activité
def _bridge():
    cfg = cfgmod.Config()
    return ModuleBridge(cfg, SimpleNamespace(), SimpleNamespace())


def test_operator_scope_never_reaches_a_visitor_even_on_replay():
    bridge = _bridge()
    op, visitor, unknown = [], [], []
    sessions = [SimpleNamespace(listener=False, send=op.append, hf_view=True),
                SimpleNamespace(listener=True, send=visitor.append, hf_view=True),
                SimpleNamespace(send=unknown.append, hf_view=True)]
    bridge.clients = lambda: sessions
    bridge.to_clients("presence", {"kind": "friends_changed", "scope": "operators", "retain": "snapshot"})
    bridge.to_clients("cluster", {"kind": "spots"})
    assert [m["data"]["kind"] for m in op] == ["friends_changed", "spots"]
    assert [m["data"]["kind"] for m in visitor] == ["spots"] and [m["data"]["kind"] for m in unknown] == ["spots"]
    late = []
    bridge.on_hf_view(SimpleNamespace(listener=True, send=late.append), True)
    assert late == []


def test_operator_activity_is_published_at_most_every_30_s():
    bridge = _bridge()
    published = []
    bridge.bus = SimpleNamespace(publish=lambda name, data: published.append(name))
    for t in (100.0, 110.0, 129.9, 130.0, 131.0):
        bridge.operator_activity(now=t)
    assert published == ["operator_activity", "operator_activity"]


# ------------------------------------------------------------------ session de la passerelle
def _session(sent, *, role="operator", friends=None, activity=None):
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), heartbeat=lambda cid: None,
                           config=SimpleNamespace(rig=SimpleNamespace(), safety=SimpleNamespace(allow_replay=False)))
    s = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append, role=role)
    s.friends_call = friends
    s.on_operator_activity = activity
    return s


def test_friends_command_is_relayed_for_an_operator_only():
    calls, sent, activity = [], [], []

    async def friends(data):
        calls.append(data)
        if data["action"] == "exclude":
            raise CommandRefused("not_admin", "réservé aux administrateurs")
        return {"groups": []}

    s = _session(sent, friends=friends, activity=lambda: activity.append(1))
    assert "friends" in s.features()
    asyncio.run(s.on_message(json.dumps({"cmd": "friends", "id": 1, "action": "view"})))
    assert sent[-1] == {"type": "result", "id": 1, "ok": True, "action": "view", "data": {"groups": []}}
    assert calls[-1] == {"action": "view", "args": {}, "client": "phone"} and activity == []
    asyncio.run(s.on_message(json.dumps({"cmd": "friends", "id": 2, "action": "exclude",
                                         "args": {"g": "0" * 32, "member": "1" * 32}})))
    assert sent[-1]["ok"] is False and sent[-1]["reason"] == "not_admin" and activity == [1]
    bare = _session(sent)
    assert "friends" not in bare.features()
    asyncio.run(bare.on_message(json.dumps({"cmd": "friends", "id": 3, "action": "view"})))
    assert sent[-1]["reason"] == "friends_unavailable"
    visitor_sent = []
    visitor = _session(visitor_sent, role="listener", friends=friends)
    assert "friends" not in visitor.features()
    before = len(calls)
    asyncio.run(visitor.on_message(json.dumps({"cmd": "friends", "id": 4, "action": "view"})))
    assert len(calls) == before                                    # jamais relayée pour un visiteur
    assert visitor_sent and visitor_sent[-1].get("ok") is not True


def test_operator_activity_ignores_passive_commands():
    sent, activity = [], []
    s = _session(sent, activity=lambda: activity.append(1))
    for cmd in ({"cmd": "heartbeat"}, {"cmd": "get_state", "id": 1}):
        try:
            asyncio.run(s.on_message(json.dumps(cmd)))
        except Exception:
            pass
    assert activity == []
    try:
        asyncio.run(s.on_message(json.dumps({"cmd": "local_release", "id": 2})))
    except Exception:
        pass
    assert activity == [1]


def test_friends_command_shape():
    assert parse_command('{"cmd":"friends","action":"invite","args":{"g":"x"}}').params == {"action": "invite",
                                                                                             "args": {"g": "x"}}
    for bad in ('{"cmd":"friends","action":"qsy"}', '{"cmd":"friends","action":"view","args":[1]}',
                '{"cmd":"friends","action":"view","hz":1}'):
        with pytest.raises(ProtocolError):
            parse_command(bad)


# ------------------------------------------------------------------ service : actions, avis, console
class Clock:
    def __init__(self) -> None:
        self.t = 1_794_000_000.0

    def __call__(self) -> float:
        return self.t


def _service(tmp_path, clock=None):
    clock = clock or Clock()
    relay = FakeRelay(clock)
    cfg = cfgmod.Config()
    cfg.supervisor.state_dir = str(tmp_path / "state")
    cfg.presence.enabled = True
    svc = PresenceService(cfg, tmp_path / "station.toml", relay_factory=relay.transport, clock=clock)
    eng = svc.setup()
    eng.store.data["pseudo"] = "F4ABC"
    return svc, eng, clock


def test_actions_validate_their_arguments_and_qsy_back_is_given_once(tmp_path):
    svc, eng, clock = _service(tmp_path)
    asyncio.run(svc.step())
    for action, args in (("share", {"g": "pas-un-id", "level": "f"}), ("invite", {"g": "0" * 32, "days": 90}),
                         ("exclude", {"g": "0" * 32, "member": "x"}), ("texts", {"texts": "Mobile"}),
                         ("shack_for", {"minutes": 0}), ("role", {"g": "0" * 32, "member": "1" * 32, "role": "z"}),
                         ("nouvelle", {})):
        with pytest.raises(ActionRefused):
            asyncio.run(actions.handle(eng, action, args))
    g = asyncio.run(svc.act("create", {"name": "Amis"}))["g"]
    assert asyncio.run(svc.act("invite", {"g": g}))["url"].startswith("https://api.rf-diy.com/i#")
    eng.set_rig(7_074_000, "PKTUSB")
    assert asyncio.run(svc.act("qsy_mark", {})) == {"back": {"freq": 7_074_000, "mode": "PKTUSB"}}
    eng.on_rig(14_205_000, "USB")                               # le client a fait son QSY
    assert asyncio.run(svc.act("qsy_mark", {}))["back"]["freq"] == 7_074_000   # point de départ gardé
    assert asyncio.run(svc.act("qsy_back", {}))["back"]["freq"] == 7_074_000
    assert asyncio.run(svc.act("qsy_back", {})) == {"back": None}
    status = json.loads((tmp_path / "state" / "presence" / "status.json").read_text(encoding="utf-8"))
    assert [x["name"] for x in status["groups"]] == ["Amis"]
    assert asyncio.run(svc.on_call({"action": "view", "args": {}}))["groups"][0]["g"] == g
    with pytest.raises(CallRefused) as err:
        asyncio.run(svc.on_call({"action": "share", "args": {"g": g, "level": "z"}}))
    assert err.value.code == "share"


def test_view_is_truncated_under_the_data_channel_limit(tmp_path):
    svc, eng, clock = _service(tmp_path)
    eng.store.groups["0" * 32] = {"name": "Gros", "role": "m", "status": "member", "share": {}, "members": {
        f"{i:032x}": {"pseudo": f"P{i}", "age": 10, "seen_at": int(clock.t),
                      "state": {"st": "R", "lv": "x", "x": "Test antenne", "sd": 1, "lt": 1}, "state_at": int(clock.t)}
        for i in range(600)}}
    out = actions.view(eng)
    assert out["truncated"] and len(json.dumps(out)) < 64 * 1024 and out["groups"][0]["count"] == 600


def test_friends_changed_goes_to_operators_only_when_the_view_changes(tmp_path):
    svc, eng, clock = _service(tmp_path)
    sent = []

    class Bus:
        connected = SimpleNamespace(is_set=lambda: True)

        async def client_message(self, **message):
            sent.append(message)

    svc.bus = Bus()
    asyncio.run(svc.notify_if_changed())
    asyncio.run(svc.notify_if_changed())
    asyncio.run(svc.step())
    asyncio.run(svc.notify_if_changed())                          # comme la boucle après chaque cycle
    asyncio.run(svc.act("create", {"name": "Amis"}))
    assert sent and all(m == {"kind": "friends_changed", "scope": "operators"} for m in sent)
    assert len(sent) == 3                                         # départ, enregistrement, groupe créé


def test_console_mailbox_request_reply_and_cleanup(tmp_path):
    svc, eng, clock = _service(tmp_path)
    state = tmp_path / "state"
    req = state / CONSOLE_REQUEST
    req.write_text(json.dumps({"id": "abc", "action": "pseudo", "args": {"pseudo": "F5XYZ"}, "at": clock.t}),
                   encoding="utf-8")
    asyncio.run(svc.check_console())
    reply = json.loads((state / "presence" / CONSOLE_REPLY).read_text(encoding="utf-8"))
    assert reply == {"id": "abc", "ok": True, "result": {"pseudo": "F5XYZ"}} and not req.exists()
    req.write_text(json.dumps({"id": "old", "action": "view", "at": clock.t - 600}), encoding="utf-8")
    asyncio.run(svc.check_console())
    assert json.loads((state / "presence" / CONSOLE_REPLY).read_text(encoding="utf-8"))["id"] == "abc"
    req.write_text(json.dumps({"id": "bad", "action": "share", "args": {"g": "x"}, "at": clock.t}), encoding="utf-8")
    asyncio.run(svc.check_console())
    reply = json.loads((state / "presence" / CONSOLE_REPLY).read_text(encoding="utf-8"))
    assert reply["id"] == "bad" and reply["ok"] is False and reply["error"] == "args"
    req.write_text("{pas du json", encoding="utf-8")
    asyncio.run(svc.check_console())
    assert not req.exists()
    clock.t += 61
    asyncio.run(svc.check_console())
    assert not (state / "presence" / CONSOLE_REPLY).exists()      # invitation éventuelle : pas plus d'une minute


def test_console_menu_talks_to_the_module_through_the_mailbox(tmp_path):
    from trxstation.console import Console
    clock = Clock()
    svc, eng, _ = _service(tmp_path, clock)
    asyncio.run(svc.step())
    cfg_path = tmp_path / "station.toml"
    cfg = cfgmod.Config()
    cfg.supervisor.state_dir = str(tmp_path / "state")
    cfg_path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    stop = threading.Event()

    def module():
        while not stop.is_set():
            clock.t = time.time()
            asyncio.run(svc.check_console())
            time.sleep(0.05)

    worker = threading.Thread(target=module, daemon=True)
    worker.start()
    try:
        console = Console.__new__(Console)
        console.config = cfg_path
        console.runner = SimpleNamespace(run=lambda *a, **k: 1)
        said = []
        console.say = said.append
        reply = console.friends_request("create", {"name": "Radio-club"}, timeout_s=5, poll_s=0.05)
        assert reply["ok"] and reply["result"]["g"] in eng.store.groups
        reply = console.friends_request("view", timeout_s=5, poll_s=0.05)
        assert reply["result"]["groups"][0]["name"] == "Radio-club"
        text = console.friends_summary(json.loads((tmp_path / "state" / "presence" / "status.json")
                                              .read_text(encoding="utf-8")))
        assert "pseudo F4ABC" in text and "Radio-club : administrateur" in text
    finally:
        stop.set()
        worker.join(2)


def test_monitor_presence_row():
    assert presence_row(None) is None and presence_row({"enabled": False}) is None
    assert presence_row({"enabled": True, "registered": False}).text == "pas encore enregistrée auprès du relais"
    row = presence_row({"enabled": True, "registered": True, "groups": [
        {"status": "member", "members": 3}, {"status": "pending", "members": 0}, {"status": "member", "members": 1}]})
    assert (row.text, row.level) == ("2 groupe(s), 4 ami(s)", "ok")
    assert presence_row({"enabled": True, "registered": True, "problem": "clock"}).level == "warn"


def test_presence_manifest_now_receives_operator_commands_but_still_no_rig_command():
    from trxstation.modules.manifest import load_manifest
    m = load_manifest(Path(__file__).resolve().parents[1] / "trxstation" / "modules" / "builtin" / "presence" / "manifest.toml")
    assert m.rights.client_commands and m.rights.client_messages and m.rights.commands == frozenset()
    assert "operator_activity" in m.rights.events


# ------------------------------------------------------------------ intégration : pont réel, bus réel, service réel
def test_gateway_bridge_relays_friends_to_the_real_presence_service(tmp_path):
    from trxstation.modules.keys import key_path, load_or_create_key, module_secrets

    async def scenario():
        clock = Clock()
        cfg = cfgmod.Config()
        cfg.supervisor.state_dir = str(tmp_path / "state")
        cfg.modules.run = ["presence"]
        cfg.presence.enabled = True
        rig = SimpleNamespace(frequency_hz=14_074_000, mode="PKTUSB", connected=True, levels={})
        ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), add_listener=lambda f: None)
        link = SimpleNamespace(state=rig, add_listener=lambda f: None)
        operator, visitor = [], []
        bridge = ModuleBridge(cfg, ctrl, link, port=0, clients=lambda: [
            SimpleNamespace(listener=False, send=operator.append), SimpleNamespace(listener=True, send=visitor.append)])
        assert bridge.has_client_commands("presence") and not bridge.has_client_commands("cluster")
        assert await bridge.start()
        secret = module_secrets(load_or_create_key(key_path(cfg.supervisor.state_dir)), ["presence"])["presence"]
        client = ModuleClient("presence", secret, port=bridge.bus.port, heartbeat_s=0.05)
        relay = FakeRelay(clock)
        svc = PresenceService(cfg, tmp_path / "station.toml", bus_client=client, relay_factory=relay.transport,
                              clock=clock)
        eng = svc.setup()
        eng.store.data["pseudo"] = "F4ABC"
        task = asyncio.ensure_future(client.run_session())
        await until(lambda: "presence" in bridge.bus.sessions)
        await until(lambda: eng.freq == 14_074_000)                # état relu à la connexion (on_connect)
        await svc.step()
        view = await bridge.call("presence", {"action": "view", "args": {}, "client": "phone"})
        assert view["registered"] and view["pseudo"] == "F4ABC"
        with pytest.raises(CommandRefused) as err:
            await bridge.call("presence", {"action": "share", "args": {"g": "x"}, "client": "phone"})
        assert err.value.code == "args"
        await bridge.call("presence", {"action": "create", "args": {"name": "Amis"}, "client": "phone"})
        await until(lambda: any(m["data"].get("kind") == "friends_changed" for m in operator))
        assert visitor == []
        before = eng.tracker.last_activity
        bridge.operator_activity()
        await until(lambda: eng.tracker.last_activity != before)
        client.stop()
        task.cancel()
        await bridge.stop()
    asyncio.run(scenario())


def test_view_relayed_to_a_page_says_which_shared_frequencies_this_station_may_transmit_on():
    from trxstation.config import Band
    sent = []
    cfg = cfgmod.Config()
    cfg.bands = [Band(name="20m", low_mhz=14.0, high_mhz=14.35)]
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), heartbeat=lambda cid: None, config=cfg)

    async def friends(data):
        return {"groups": [{"g": "0" * 32, "members": [{"id": "1" * 32, "f": 14_205_000}, {"id": "2" * 32, "f": 27_555_000},
                                                       {"id": "3" * 32, "code": "O"}]}]}

    s = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append)
    s.friends_call = friends
    asyncio.run(s.on_message(json.dumps({"cmd": "friends", "id": 1, "action": "view"})))
    members = sent[-1]["data"]["groups"][0]["members"]
    assert [m.get("tx_ok") for m in members] == [True, False, None]
    cfg.safety.enforce_bands = False                                # la station ne juge pas les bandes : rien d'ajouté
    asyncio.run(s.on_message(json.dumps({"cmd": "friends", "id": 2, "action": "view"})))
    assert all("tx_ok" not in m for m in sent[-1]["data"]["groups"][0]["members"])
