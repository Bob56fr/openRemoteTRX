# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Monitoring inter-stations, lot R3a : module « monlink » contre le faux relais (devtools/fake_monlink_relay.py).

Deux stations : HELPER (celle qui aide, receveur) et AIDED (l'opérateur en difficulté, émetteur). Le VRAI relais est
essayé à part (dépôt du relais, tests/e2e_monlink.py, en local et en ligne)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.devtools.fake_monlink_relay import FakeMonRelay
from trxstation.modules.registry import selected_manifests
from trxstation.monlink import engine as eng_mod, profiles as pr
from trxstation.monlink.engine import ActionRefused, Engine
from trxstation.monlink.identity import Identity
from trxstation.monlink.service import CONSOLE_REPLY, CONSOLE_REQUEST, MonlinkService
from trxstation.monlink.store import Store
from trxstation.status import GatewayStatus, write_status

NOW = 1_794_900_000


class Clock:
    def __init__(self) -> None:
        self.t = float(NOW)

    def __call__(self) -> float:
        return self.t


class FakeMonitor:
    def summary(self) -> dict:
        return {"cpu": 12, "mem": 40, "disk": 55, "temp": None}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    relay = FakeMonRelay(clock=clock)
    made: list[str] = []

    def make(name: str, pseudo: str) -> Engine:
        made.append(name)
        folder = tmp_path / f"{name}-{len(made)}"
        folder.mkdir()
        ident = Identity.generate()
        store = Store(folder / "monlink")
        store.data["pseudo"] = pseudo
        eng = Engine(store, ident, relay.transport(ident), status_path=folder / "gateway-status.json",
                     state_dir=folder, clock=clock, monitor=FakeMonitor(),
                     known_words={"minix-bzh": "<host>"})
        eng.folder = folder
        return eng

    return clock, relay, make


def gateway(eng: Engine, clock: Clock, *, freq: int = 7_074_000, mode: str = "PKTUSB") -> None:
    write_status(eng.status_path, GatewayStatus(pid=1, seq=1, written_at=clock(), ptt={"state": "rx"},
                                                rig={"connected": True, "frequency_hz": freq, "mode": mode},
                                                clients=["kriss-pc"]))


def journal(eng: Engine, *events: dict) -> None:
    with (eng.folder / "journal-passerelle.jsonl").open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps({"ts": "2026-11-20T10:00:00.000Z", "processus": "passerelle", "niveau": "WARNING",
                                 "message": "…", **e}) + "\n")


def cycle(clock: Clock, *engines: Engine, step: float = 61.0) -> None:
    """Un cycle de chaque station ; la passerelle (fausse) réécrit son état comme toutes les secondes."""
    from trxstation.status import read_status

    async def go():
        clock.t += step
        for e in engines:
            gw = read_status(e.status_path)
            if gw is not None:
                gw.written_at = clock()
                write_status(e.status_path, gw)
        for e in engines:
            await e.cycle()
    run(go())


def paired(world) -> tuple[Engine, Engine, Clock, FakeMonRelay]:
    """HELPER invite, AIDED rejoint, empreintes comparées, AIDED choisit « diagnostic »."""
    clock, relay, make = world
    helper, aided = make("helper", "Dev 56"), make("aided", "F4XYZ")
    gateway(aided, clock)
    journal(aided, {"code": "ORT-1001", "gravite": "avertissement"})          # avant : jamais envoyé (historique)
    code = run(helper.invite())["code"]
    joined = run(aided.join(code.lower()))
    cycle(clock, helper, aided)
    link_h = helper.store.links[aided.me]
    assert link_h["state"] == "confirm" and link_h["fingerprint"] == joined["fingerprint"]
    run(helper.confirm(aided.me))
    run(aided.confirm(helper.me, "diagnostic"))
    return helper, aided, clock, relay


# ------------------------------------------------------------------ appairage
def test_pairing_shows_the_same_fingerprint_and_nothing_leaves_before_the_profile(world):
    clock, relay, make = world
    helper, aided = make("helper", "Dev 56"), make("aided", "F4XYZ")
    gateway(aided, clock)
    code = run(helper.invite())
    assert len(code["code"]) == 11 and code["expires"] == int(clock()) + 900
    joined = run(aided.join(code["code"]))
    assert joined["pseudo"] == "Dev 56"
    cycle(clock, helper, aided)
    view = helper.view()["links"][0]
    assert view["fingerprint"] == joined["fingerprint"] and view["state"] == "confirm"
    assert aided.view()["links"][0]["fingerprint"] == joined["fingerprint"]
    assert not [c for c in relay.calls if c[1] == "put"]                   # rien n'est parti
    with pytest.raises(ActionRefused, match="profil|profile"):
        run(aided.confirm(helper.me, None))
    with pytest.raises(ActionRefused) as err:
        run(aided.confirm(helper.me, {"period_s": 5}))
    assert err.value.reason == "profile"
    cycle(clock, helper, aided)
    assert not [c for c in relay.calls if c[1] == "put"]
    with pytest.raises(ActionRefused) as err:
        run(helper.request_assist(aided.me))
    assert err.value.reason == "not_confirmed"


def test_code_is_single_use_and_bad_codes_are_refused(world):
    clock, relay, make = world
    helper, aided, other = make("helper", "Dev 56"), make("aided", "F4XYZ"), make("other", "Intrus")
    code = run(helper.invite())["code"]
    run(aided.join(code))
    with pytest.raises(ActionRefused) as err:
        run(other.join(code))
    assert err.value.reason == "unknown_invite"
    with pytest.raises(ActionRefused) as err:
        run(other.join("trop-court"))
    assert err.value.reason == "code"
    with pytest.raises(ActionRefused) as err:
        run(helper.join(run(helper.invite())["code"]))
    assert err.value.reason == "unknown_invite"                            # sa propre invitation
    nameless = make("nameless", "x")
    nameless.store.data["pseudo"] = ""
    with pytest.raises(ActionRefused) as err:
        run(nameless.invite())
    assert err.value.reason == "no_pseudo"
    clock.t += 901
    code2 = run(helper.invite())["code"]
    clock.t += 901
    with pytest.raises(ActionRefused):
        run(other.join(code2))                                             # expirée


# ------------------------------------------------------------------ envoi et réception
def test_heartbeat_state_and_events_are_sent_masked_and_kept_by_the_helper(world, caplog):
    helper, aided, clock, relay = paired(world)
    journal(aided, {"code": "ORT-2104", "gravite": "erreur",
                    "contexte": {"password": "hunter2", "port": "/dev/serial/by-id/usb-Icom_IC-7300_13003336-if00",
                                 "host": "minix-bzh", "url": "https://ntfy.sh/sujet-perso"}},
            {"code": "ORT-4019", "gravite": "info"})                       # info : pas dans « diagnostic »
    aided.journal.read()                                                   # 1er passage : positions posées
    journal(aided, {"code": "ORT-2104", "gravite": "erreur",
                    "contexte": {"password": "hunter2", "port": "/dev/serial/by-id/usb-Icom_IC-7300_13003336-if00",
                                 "host": "minix-bzh", "url": "https://ntfy.sh/sujet-perso"}},
            {"code": "ORT-4019", "gravite": "info"})
    cycle(clock, aided, helper)
    link = helper.store.links[aided.me]
    assert link["profile"]["events_min"] == "avertissement" and link["paused"] is False
    assert link["last_hb"]["gateway"] == "ok" and link["last_hb"]["safe"] is None
    assert link["last_st"]["system"]["cpu"] == 12
    rig = link["last_st"]["rig"]
    assert rig["cat"] is True and rig["clients"] == 1
    assert "freq" not in rig and "mode" not in rig                         # masqués par défaut
    events = helper.received(aided.me)
    assert [e["content"]["code"] for e in events] == ["ORT-2104"]
    text = json.dumps(events)
    for secret in ("hunter2", "13003336", "minix-bzh", "sujet-perso"):
        assert secret not in text, secret
    assert "ORT-1001" not in text                                          # écrit avant l'appairage : jamais envoyé
    for msg in relay.msgs:
        assert "ORT-2104" not in json.dumps(msg["msg"])                    # le relais ne lit rien


def test_frequency_only_when_the_aided_operator_allows_it(world):
    helper, aided, clock, relay = paired(world)
    run(aided.set_profile(helper.me, {"freq_mode": True}))
    cycle(clock, aided, helper)
    rig = helper.store.links[aided.me]["last_st"]["rig"]
    assert (rig["freq"], rig["mode"]) == (7_074_000, "PKTUSB")
    assert helper.store.links[aided.me]["profile"]["freq_mode"] is True


def test_rhythm_of_the_profile(world):
    helper, aided, clock, relay = paired(world)
    cycle(clock, aided)
    puts = lambda: sum(1 for c in relay.calls if c == (aided.me, "put"))   # noqa: E731
    before = puts()
    cycle(clock, aided, step=60)                                          # 300 s pas encore écoulées
    assert puts() == before
    cycle(clock, aided, step=300)
    assert puts() == before + 2                                           # hb + st


def test_assistance_requested_accepted_faster_and_expiring(world):
    helper, aided, clock, relay = paired(world)
    with pytest.raises(ActionRefused) as err:
        run(helper.request_assist(aided.me, 60))
    assert err.value.reason == "duration"
    run(helper.request_assist(aided.me, 3600))
    with pytest.raises(ActionRefused) as err:
        run(aided.request_assist(helper.me))                              # la station aidée ne demande rien
    assert err.value.reason == "role"
    cycle(clock, aided)
    request = aided.view()["links"][0]["request"]
    assert request["assist"] == 3600
    run(aided.answer(helper.me, True))
    assert 3500 < aided.view()["links"][0]["assist_left_s"] <= 3600
    journal(aided, {"code": "ORT-4019", "gravite": "info"})
    assert run(aided.cycle()) == eng_mod.FAST_CYCLE_S
    cycle(clock, helper, step=1)
    assert helper.store.links[aided.me]["answer"]["accepted"] is True
    assert "ORT-4019" in json.dumps(helper.received(aided.me))            # info passe pendant l'assistance
    clock.t += 3601
    eff = pr.effective(pr.Profile.from_dict(aided.store.links[helper.me]["profile"]),
                       aided.store.links[helper.me]["assist_until"], clock())
    assert not eff.assistance
    with pytest.raises(ActionRefused) as err:
        run(aided.answer(helper.me, True))
    assert err.value.reason == "no_request"
    for _ in range(2):
        run(helper.request_assist(aided.me, 3600))
    with pytest.raises(ActionRefused) as err:
        run(helper.request_assist(aided.me, 3600))
    assert err.value.reason == "too_many"                                 # 3 par jour


def test_pause_stops_everything_and_shows_paused(world):
    helper, aided, clock, relay = paired(world)
    cycle(clock, aided, helper)
    run(aided.pause(helper.me, True))
    cycle(clock, helper, step=1)
    assert helper.view()["links"][0]["paused"] is True
    puts = sum(1 for c in relay.calls if c == (aided.me, "put"))
    cycle(clock, aided, step=1000)
    assert sum(1 for c in relay.calls if c == (aided.me, "put")) == puts
    run(aided.pause(helper.me, False))
    cycle(clock, aided, helper, step=1000)
    assert helper.view()["links"][0]["paused"] is False


def test_end_by_either_side_is_immediate(world, caplog):
    helper, aided, clock, relay = paired(world)
    cycle(clock, aided, helper)
    caplog.set_level(logging.INFO)
    run(aided.end(helper.me))
    assert aided.view()["links"] == []
    cycle(clock, helper, step=eng_mod.CHECK_LINK_S + 1)
    assert helper.view()["links"] == []                                  # constatée au relais
    assert "ORT-7002" in caplog.text

    helper, aided, clock, relay = paired(world)
    cycle(clock, aided, helper)
    run(helper.end(aided.me, purge=True))
    assert helper.store.recent(aided.me) == []
    cycle(clock, aided, step=400)                                        # son prochain envoi : not_linked
    assert aided.view()["links"] == []


# ------------------------------------------------------------------ pannes et refus
def test_relay_down_is_reported_once_and_recovers(world, caplog):
    helper, aided, clock, relay = paired(world)
    caplog.set_level(logging.INFO)
    relay.down = True
    cycle(clock, aided, helper)
    cycle(clock, aided, helper)
    assert caplog.text.count("ORT-7040") == 2                             # une fois par station, pas à chaque cycle
    assert aided.problem == "relay"
    journal(aided, {"code": "ORT-2104", "gravite": "erreur"})
    cycle(clock, aided)
    relay.down = False
    cycle(clock, aided, helper)
    assert aided.problem == ""
    assert "ORT-2104" in json.dumps(helper.received(aided.me))            # gardé dans la file, envoyé ensuite


def test_tampered_or_replayed_messages_are_refused(world, caplog):
    helper, aided, clock, relay = paired(world)
    caplog.set_level(logging.INFO)
    cycle(clock, aided)
    pending = [m for m in relay.msgs if m["owner"] == helper.me]
    copy = json.loads(json.dumps(pending[0]["msg"]))
    relay.msgs.append({**pending[0], "id": relay.next_id, "msg": copy})   # rejeu
    relay.next_id += 1
    bad = json.loads(json.dumps(pending[-1]["msg"]))
    bad["b"] = bad["b"][:-4] + ("AAAA" if not bad["b"].endswith("AAAA") else "BBBB")
    relay.msgs.append({**pending[-1], "id": relay.next_id, "msg": bad})   # altéré
    relay.next_id += 1
    cycle(clock, helper, step=1)
    assert caplog.text.count("ORT-7031") == 2
    assert helper.store.links[aided.me]["state"] == "active"


# ------------------------------------------------------------------ module, configuration, manifeste
def test_configuration_section_and_separate_keys(tmp_path):
    cfg, problems = cfgmod.build({"rig": {"model": 1}, "supervisor": {"state_dir": str(tmp_path)}})
    assert cfg.monitor_link.enabled is False and cfg.monitor_link.relay_url == cfgmod.PRESENCE_DEFAULT_RELAY
    assert cfgmod.monlink_key_path(cfg, tmp_path / "station.toml") == tmp_path / "monlink" / "monlink.key"
    assert cfgmod.monlink_key_path(cfg, tmp_path / "x.toml") != cfgmod.presence_key_path(cfg, tmp_path / "x.toml")
    _, problems = cfgmod.build({"rig": {"model": 1}, "monitor_link": {"enabled": True, "relay_url": "http://evil"}})
    assert any("relay_url" in p for p in problems) and any("[modules] run" in p for p in problems)
    text = cfgmod.dumps(cfg) if hasattr(cfgmod, "dumps") else ""
    if text:
        assert "[monitor_link]" in text


def test_manifest_gives_no_right_on_the_rig():
    """Aucun droit sur le poste ni vers les pages ; seul droit (lot R5) : recevoir la commande « monitoring » d'un
    OPÉRATEUR de la page, relayée par le cœur."""
    manifests, problems = selected_manifests(cfgmod.Modules(run=["monlink"]))
    assert not problems
    m = manifests[0]
    assert m.name == "monlink" and m.entry == "trxstation.monlink.service"
    rights = m.rights
    assert list(rights.events) == [] and list(rights.commands) == []
    assert rights.client_messages is False and rights.client_commands is True


def test_service_disabled_then_console_request(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    cfg, _ = cfgmod.build({"rig": {"model": 1}, "supervisor": {"state_dir": str(state),
                                                              "status_path": str(state / "gw.json")}})
    service = MonlinkService(cfg, tmp_path / "station.toml", clock=Clock(), monitor=FakeMonitor())

    async def disabled():
        task = asyncio.ensure_future(service.run())
        await asyncio.sleep(0.05)
        task.cancel()
    run(disabled())
    assert json.loads((state / "monlink" / "status.json").read_text(encoding="utf-8"))["enabled"] is False

    relay = FakeMonRelay(clock=service.clock)
    service = MonlinkService(cfg, tmp_path / "station.toml", relay_factory=relay.transport, clock=service.clock,
                             monitor=FakeMonitor())
    service.setup()
    assert (state / "monlink" / "monlink.key").exists()

    def ask(action: str, args: dict) -> dict:
        (state / CONSOLE_REQUEST).write_text(json.dumps({"id": "r1", "action": action, "args": args,
                                                         "at": service.clock()}), encoding="utf-8")
        run(service.check_console())
        assert not (state / CONSOLE_REQUEST).exists()
        return json.loads((state / "monlink" / CONSOLE_REPLY).read_text(encoding="utf-8"))

    assert ask("pseudo", {"pseudo": "F4XYZ"})["ok"] is True
    reply = ask("invite", {})
    assert reply["ok"] and len(reply["result"]["code"]) == 11
    assert ask("shell", {})["error"] == "unknown_action"
    assert ask("view", {"x": 1})["error"] == "malformed"
    assert ask("confirm", {"peer": "0" * 32})["error"] == "unknown_link"
    status = json.loads((state / "monlink" / "status.json").read_text(encoding="utf-8"))
    assert status["pseudo"] == "F4XYZ" and status["invites"] == 1
    assert "key" not in json.dumps(status)                                # jamais de clé dans le résumé lisible


def test_new_relay_that_forgot_the_station_means_a_new_registration_without_alert(world, caplog):
    """Relais déménagé ou remis à zéro (migration vers le VPS, étape 342) : la station ne reste pas « inscrite » à tort."""
    clock, relay, make = world
    eng = make("aided", "F4XYZ")
    gateway(eng, clock)
    cycle(clock, eng)
    assert eng.store.data["registered"] is True and eng.me in relay.stations
    caplog.set_level(logging.INFO)
    relay.stations.clear()                                                 # base neuve
    cycle(clock, eng)
    assert eng.store.data["registered"] is False and eng.problem == "unknown_station"
    assert "ORT-7040" not in caplog.text                                   # pas d'alerte pour ça
    cycle(clock, eng)
    assert eng.store.data["registered"] is True and eng.me in relay.stations and eng.problem == ""


def test_operator_action_on_a_relay_that_forgot_the_station_registers_and_replays_once(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    cfg, _ = cfgmod.build({"rig": {"model": 1}, "supervisor": {"state_dir": str(state),
                                                              "status_path": str(state / "gw.json")}})
    clock = Clock()
    relay = FakeMonRelay(clock=clock)
    service = MonlinkService(cfg, tmp_path / "station.toml", relay_factory=relay.transport, clock=clock,
                             monitor=FakeMonitor())
    service.setup()
    run(service.act("pseudo", {"pseudo": "F4XYZ"}))
    assert run(service.act("invite", {}))["code"]
    relay.stations.clear()                                                 # le relais ne la connaît plus
    assert run(service.act("invite", {}))["code"]                          # inscrite de nouveau, action rejouée
    assert service.engine.store.data["registered"] is True and service.engine.me in relay.stations
    assert [r for _, r in relay.calls].count("register") >= 2


def test_monlink_package_never_touches_the_ptt_nor_the_cat():
    """Rappel du lot R1, étendu aux nouveaux fichiers (service, moteur, collecte)."""
    import ast
    forbidden = ("safety", "cat", "rigctl", "ptt", "gateway", "subprocess")
    root = Path(__file__).resolve().parents[1] / "trxstation" / "monlink"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Attribute) and node.attr in ("command", "client_message"):
                raise AssertionError(f"{path.name} : .{node.attr} interdit au monitoring")
            for name in names:
                assert not any(part in forbidden for part in name.split(".")), f"{path.name} importe {name}"
