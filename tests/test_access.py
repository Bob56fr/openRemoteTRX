# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md, lot 1) : rôles, liste blanche des commandes,
quotas, présence de l'opérateur et attente, pseudos, relecture de station.toml, demande de déconnexion de la console.
Un visiteur ne doit JAMAIS rien faire au poste ni à l'émission."""
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.config import Access, ClientAuth
from trxstation.gateway.access_watch import KICK_REQUEST, AccessWatcher, kick_request
from trxstation.gateway.api.access import (LISTENER_COMMANDS, LISTENER_REFUSED, AccessControl, AccessRefused,
                                           listener_muted)
from trxstation.gateway.api.protocol import COMMANDS, MAX_MESSAGE_BYTES
from trxstation.passwords import hash_password
from trxstation.setup_wizard import dummy_config

from test_api import connect, run, station, until

EXAMPLES = json.loads((Path(__file__).parent / "protocol" / "commands.json").read_text(encoding="utf-8"))["commands"]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def accounts():
    return [ClientAuth("phone", password_hash="h-phone", pseudo="Kriss F4ABC"), ClientAuth("pc", password_hash="h-pc"),
            ClientAuth("club1", password_hash="h-c1", role="listener", pseudo="Radio-club"),
            ClientAuth("club2", password_hash="h-c2", role="listener", pseudo="Radio-club"),
            ClientAuth("club3", password_hash="h-c3", role="listener")]


def control(**settings):
    clock = Clock()
    access = AccessControl(accounts(), Access(**{"max_listeners": 2, **settings}), clock=clock,
                           today=lambda: date(2026, 10, 30))
    return access, clock


def join(access, client_id):
    conn = access.admit(client_id, "192.0.2.1")
    access.opened(client_id)
    return conn


def refused(access, client_id):
    with pytest.raises(AccessRefused) as exc:
        access.admit(client_id)
    return exc.value.reason


# --------------------------------------------------------------------------- liste blanche

def test_every_command_is_classified_for_the_listener_role():
    """Une commande ajoutée au protocole doit être classée : autorisée ou refusée à un visiteur."""
    assert LISTENER_COMMANDS | LISTENER_REFUSED == set(COMMANDS)
    assert not LISTENER_COMMANDS & LISTENER_REFUSED
    assert LISTENER_COMMANDS == {"get_state", "spectrum_watch"}         # rien qui touche au poste ni à la station


def _rig_writes(fake):
    """Ordres d'ÉCRITURE reçus par le faux rigctld (lettres majuscules, ou forme longue \\set_)."""
    return [c for c in fake.commands if c.lstrip("+")[:1].isupper() or "\\set_" in c]


@pytest.mark.parametrize("name", sorted(LISTENER_REFUSED))
def test_a_listener_command_is_refused_and_never_reaches_the_rig(name):
    async def scenario(fake):
        async with station(fake) as st:
            access = AccessControl([ClientAuth("phone", password_hash="x"), ClientAuth("club1", password_hash="y",
                                    role="listener")], Access(max_listeners=2, listeners_need_operator=False))
            st.memories.save(name="M", hz=7_074_000, mode="USB", favorite=False, memory_id=None)
            visitor = await connect(st, "club1", role="listener", access=access)
            writes, memories = len(_rig_writes(fake)), st.memories.list()
            for example in EXAMPLES[name]["valid"]:
                message = dict(example, id=77)
                if "memory_id" in message and message["memory_id"] is not None:
                    message["memory_id"] = memories[0]["id"]
                await visitor.say(**message)
                if name == "heartbeat":
                    assert not visitor.of_type("result")                     # battement : ignoré sans réponse
                else:
                    result = visitor.result(77)
                    assert result["ok"] is False and result["reason"] == "forbidden", message
                visitor.messages.clear()
            await asyncio.sleep(0.1)
            assert len(_rig_writes(fake)) == writes and fake.ptt == 0
            assert st.ctrl.clients == [] and st.ctrl.snapshot().state == "RX"     # jamais enregistré pour l'émission
            assert st.memories.list() == memories
    run(scenario)


def test_a_listener_may_read_the_state_and_watch_the_spectrum_view():
    async def scenario(fake):
        async with station(fake) as st:
            watched = []
            visitor = await connect(st, "club1", role="listener", spectrum_watch=watched.append)
            await visitor.say(cmd="get_state", id=1)
            assert visitor.result(1)["ok"] and visitor.result(1)["state"]["type"] == "state"
            hello = visitor.of_type("hello")[0]
            assert hello["role"] == "listener" and hello["beeps"] is None
    run(scenario)


def test_selcall_is_hidden_from_listeners_but_still_offered_to_operators():
    from types import SimpleNamespace

    async def scenario(fake):
        async with station(fake) as st:
            store = SimpleNamespace(status=SimpleNamespace(to_dict=lambda: {"state": "open", "code": "4721"}),
                                    added=[], add_listener=lambda f: store.added.append(f),
                                    remove_listener=lambda f: None)
            st.pipeline.selcall = SimpleNamespace(store=store)
            phone = await connect(st, "phone")
            visitor = await connect(st, "club1", role="listener")
            assert phone.of_type("hello")[0]["selcall"]["code"] == "4721" and "selcall" in phone.of_type("hello")[0]["features"]
            hello = visitor.of_type("hello")[0]
            assert hello["selcall"] is None and not any(f.startswith("selcall") for f in hello["features"])
            assert len(store.added) == 1                                         # aucun message « selcall » vers le visiteur
            assert "4721" not in json.dumps(visitor.messages)
    run(scenario)


def test_oversized_and_repeated_forbidden_messages_close_the_listener_with_an_alert():
    async def scenario(fake):
        async with station(fake) as st:
            reasons, alerts = [], []
            visitor = await connect(st, "club1", role="listener", disconnect=reasons.append,
                                    alert=lambda title, text: alerts.append(text))
            await visitor.session.on_message(json.dumps({"cmd": "bug_report", "text": "x" * (MAX_MESSAGE_BYTES + 10), "id": 3}))
            assert visitor.result(None)["reason"] == "forbidden"            # trop long : refusé sans analyse
            for i in range(19):
                await visitor.say(cmd="set_frequency", hz=7_100_000, id=10 + i)
            assert reasons == []                                             # 20 refus : encore toléré
            await visitor.say(cmd="toggle", id=99)
            assert reasons == ["too_many_forbidden"] and alerts and "club1" in alerts[0]
            assert fake.ptt == 0
    run(scenario)


def test_a_listener_never_sees_account_identifiers_and_its_loss_changes_nothing_to_the_operator_tx():
    async def scenario(fake):
        async with station(fake) as st:
            access = AccessControl([ClientAuth("phone", password_hash="x", pseudo="Kriss F4ABC"),
                                    ClientAuth("club1", password_hash="y", role="listener")], Access(max_listeners=2))
            access.admit("phone")
            phone = await connect(st, "phone", access=access)
            access.admit("club1")
            visitor = await connect(st, "club1", role="listener", access=access)
            await phone.say(cmd="toggle", id=1)
            assert phone.result(1)["ok"] and fake.ptt == 1
            await until(lambda: any(m["ptt"]["state"] == "TX" for m in visitor.of_type("state")))
            seen = next(m for m in visitor.of_type("state") if m["ptt"]["state"] == "TX")
            assert seen["ptt"]["owner"] == "Kriss F4ABC" and seen["clients"] == []
            assert "connections" not in seen["presence"] and seen["presence"]["listeners"] == 1
            assert '"phone"' not in json.dumps(visitor.messages)                # l'identifiant de l'opérateur ne part jamais
            assert visitor.of_type("hello")[0]["pseudo"] == "Visiteur 2"       # sans pseudo : jamais l'identifiant
            mine = phone.of_type("state")[-1]
            assert mine["ptt"]["owner"] == "phone" and {c["id"] for c in mine["presence"]["connections"]} == {"phone", "club1"}
            await visitor.session.close()                                    # le visiteur part pendant l'émission
            await asyncio.sleep(0.2)
            assert st.ctrl.snapshot().state == "TX" and fake.ptt == 1 and st.ctrl.clients == ["phone"]
            await phone.say(cmd="toggle", id=2)
    run(scenario)


# --------------------------------------------------------------------------- admission et quotas

def test_quotas_are_separate_and_listeners_never_take_an_operator_place():
    access, _ = control(max_operators=1, listeners_need_operator=False)
    join(access, "club1")
    join(access, "club2")
    assert refused(access, "club3") == "listeners_full"
    assert len([c for c in access.connections.values() if c.role == "listener"]) == 2    # personne n'est éjecté
    join(access, "phone")                                                   # visiteurs complets : l'opérateur entre
    assert refused(access, "pc") == "operators_full"
    access.closed("club1")
    join(access, "club3")


def test_listeners_closed_by_default_and_unknown_accounts_refused():
    access, _ = control(max_listeners=0)
    join(access, "phone")
    assert refused(access, "club1") == "listeners_off"
    assert refused(access, "nobody") == "account_changed"


def test_disabled_expired_removed_or_changed_accounts_are_refused_and_disconnected():
    access, _ = control(listeners_need_operator=False)
    clients = accounts()
    clients[2].enabled = False
    clients[3].expires = "2026-10-29"
    access.reload(clients, access.settings)
    assert refused(access, "club1") == "account_disabled"
    assert refused(access, "club2") == "account_expired"
    clients[3].expires = "2026-10-30"                                       # dernier jour : encore valable
    join(access, "club2")
    join(access, "club3")
    join(access, "phone")
    assert access.due() == []
    changed = accounts()
    changed[4].password_hash = "nouvelle"                                    # mot de passe changé
    changed[0].role = "listener"                                             # rôle changé
    changed = [c for c in changed if c.id != "club2"]                        # compte supprimé
    access.reload(changed, access.settings)
    assert dict(access.due()) == {"club3": "account_changed", "phone": "account_changed", "club2": "account_changed"}


def test_listeners_need_an_operator_and_wait_for_him_before_being_disconnected():
    access, clock = control(operator_grace_s=60)
    assert refused(access, "club1") == "operator_absent"
    access.admit("phone")
    assert refused(access, "club1") == "operator_absent"                   # opérateur pas encore ouvert (canal de contrôle)
    access.opened("phone")
    join(access, "club1")
    access.closed("phone")                                                  # opérateur perdu
    clock.t += 30
    assert access.due() == [] and access.grace_remaining() == 30
    assert access.presence("listener")["grace_remaining_s"] == 30
    assert refused(access, "club2") == "operator_absent"                   # nouvel arrivant : refusé pendant l'attente
    access.closed("club1")
    join(access, "club1")                                                   # visiteur déjà là qui se reconnecte : accepté
    join(access, "pc")                                                      # un opérateur revient (autre compte) : rien n'est coupé
    clock.t += 100
    assert access.due() == [] and access.grace_remaining() is None
    access.closed("pc")
    clock.t += 59
    assert access.due() == []
    clock.t += 1
    assert access.due() == [("club1", "operator_absent")]


def test_switch_off_lets_listeners_in_without_operator_and_switching_on_starts_the_wait():
    access, clock = control(listeners_need_operator=False, operator_grace_s=10)
    join(access, "club1")
    assert access.due() == []
    access.reload(accounts(), Access(max_listeners=2, listeners_need_operator=True, operator_grace_s=10))
    assert access.due() == []
    clock.t += 10
    assert access.due() == [("club1", "operator_absent")]


def test_closing_the_listeners_function_disconnects_them():
    access, _ = control(listeners_need_operator=False)
    join(access, "club1")
    access.reload(accounts(), Access(max_listeners=0))
    assert access.due() == [("club1", "listeners_off")]


def test_presence_groups_pseudos_and_shows_identifiers_to_operators_only():
    access, clock = control(listeners_need_operator=False)
    join(access, "phone")
    join(access, "club1")
    clock.t += 5
    join(access, "club2")
    for_listener, for_operator = access.presence("listener"), access.presence("operator")
    assert for_listener["listeners"] == 2 and for_listener["operators"] == 1 and for_listener["max_listeners"] == 2
    assert {(p["pseudo"], p["role"], p["count"]) for p in for_listener["people"]} == {
        ("Kriss F4ABC", "operator", 1), ("Radio-club", "listener", 2)}
    assert "connections" not in for_listener and "club1" not in json.dumps(for_listener)
    assert {c["id"] for c in for_operator["connections"]} == {"phone", "club1", "club2"}
    assert for_operator["connections"][0]["source"] == "192.0.2.1"
    assert access.pseudo("pc") == "Opérateur" and access.public_owner("phone") == "Kriss F4ABC"
    assert access.public_owner(None) is None and access.public_owner("local") == "local"


def test_listener_audio_is_silent_outside_the_bands_unless_allowed():
    cfg = dummy_config()
    muted = lambda freq, **kw: listener_muted(Access(**kw), cfg, freq)    # noqa: E731
    assert not muted(14_200_000) and muted(10_000_000) and muted(None) and muted(0)
    assert not muted(10_000_000, listeners_outside_bands=True)
    cfg.bands = []
    assert muted(14_200_000)                                                # aucune bande : silence permanent


# --------------------------------------------------------------------------- station.toml

def test_account_fields_are_validated_and_roundtrip(tmp_path):
    cfg = dummy_config()
    cfg.clients = [ClientAuth("phone", password_hash=hash_password("Un mot de passe correct 42"), pseudo="Kriss F4ABC"),
                   ClientAuth("club1", password_hash=hash_password("Un mot de passe correct 43"), role="listener",
                              pseudo="Radio-club", enabled=False, expires="2026-12-31")]
    cfg.access = Access(max_listeners=5, operator_grace_s=90, listeners_outside_bands=True)
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert cfgmod.load(path) == cfg
    text = path.read_text(encoding="utf-8")
    assert text.count("role =") == 1                                        # un opérateur n'écrit pas son rôle
    old = text.replace('role = "listener"   # visiteur : réception seule\n', "")
    path.write_text(old.replace('expires = "2026-12-31"', "expires = 2026-12-31"), encoding="utf-8")
    loaded = cfgmod.load(path)                                              # date TOML sans guillemets acceptée
    assert loaded.clients[1].role == "operator" and loaded.clients[1].expires == "2026-12-31"   # rôle absent = opérateur


@pytest.mark.parametrize("change,fragment", [
    (lambda c: setattr(c.clients[0], "role", "listner"), "role « listner » inconnu"),
    (lambda c: setattr(c.clients[0], "role", "admin"), "inconnu"),
    (lambda c: setattr(c.clients[0], "pseudo", "phone"), "l'identifiant d'un compte"),
    (lambda c: setattr(c.clients[0], "pseudo", "PHONE"), "l'identifiant d'un compte"),
    (lambda c: setattr(c.clients[0], "pseudo", "x" * 33), "pseudo invalide"),
    (lambda c: setattr(c.clients[0], "pseudo", "a\nb"), "pseudo invalide"),
    (lambda c: setattr(c.clients[0], "pseudo", " Kriss"), "pseudo invalide"),
    (lambda c: setattr(c.clients[0], "expires", "31/12/2026"), "AAAA-MM-JJ"),
    (lambda c: setattr(c.clients[0], "expires", "2026-02-30"), "pas une date valide"),
    (lambda c: setattr(c.clients[0], "enabled", "non"), "enabled"),
    (lambda c: setattr(c.access, "max_listeners", 21), "max_listeners"),
    (lambda c: setattr(c.access, "max_operators", 0), "max_operators"),
    (lambda c: setattr(c.access, "operator_grace_s", 601), "operator_grace_s"),
    (lambda c: setattr(c.access, "listeners_need_operator", 1), "listeners_need_operator"),
])
def test_account_and_access_mistakes_are_blocking(change, fragment):
    cfg = dummy_config()
    cfg.clients = [ClientAuth("phone", password_hash=hash_password("Un mot de passe correct 42"))]
    change(cfg)
    assert any(fragment in p for p in cfgmod.validate(cfg)), cfgmod.validate(cfg)


def test_unknown_access_key_is_refused():
    with pytest.raises(cfgmod.ConfigError) as exc:
        cfgmod.from_dict({"rig": {"model": 1}, "access": {"max_visitors": 3}})
    assert any("[access] clé inconnue" in p for p in exc.value.problems)


# --------------------------------------------------------------------------- relecture et demande de la console

class FakeManager:
    def __init__(self):
        self.kicked = []

    async def kick(self, client_id, reason):
        self.kicked.append((client_id, reason))


class FakeRegistry:
    def __init__(self):
        self.clients = None

    def update(self, clients):
        self.clients = clients


def _write_config(path, clients, access):
    cfg = dummy_config()
    cfg.clients, cfg.access = clients, access
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")


def test_watcher_reloads_a_valid_station_toml_and_keeps_the_old_accounts_on_error(tmp_path):
    import os
    path = tmp_path / "station.toml"
    good = [ClientAuth("phone", password_hash=hash_password("Un mot de passe correct 42")),
            ClientAuth("club1", password_hash=hash_password("Un mot de passe correct 43"), role="listener")]
    _write_config(path, good, Access(max_listeners=1, listeners_need_operator=False))
    access = AccessControl(good, Access(max_listeners=1, listeners_need_operator=False))
    join(access, "club1")
    registry, manager = FakeRegistry(), FakeManager()
    watcher = AccessWatcher(access, registry, manager, path, tmp_path)
    good[1].enabled = False
    _write_config(path, good, Access(max_listeners=1, listeners_need_operator=False))
    os.utime(path, (1, 1))
    asyncio.run(watcher.step())
    assert registry.clients is not None and manager.kicked == [("club1", "account_disabled")]
    path.write_text(path.read_text(encoding="utf-8").replace('role = "listener"', 'role = "listner"'), encoding="utf-8")
    os.utime(path, (2, 2))
    registry.clients = None
    assert watcher.check_config() is False and registry.clients is None    # invalide : rien de changé
    assert access.accounts["club1"].role == "listener"


def test_console_kick_request_only_disconnects_a_connected_listener_and_expires(tmp_path):
    access, _ = control(listeners_need_operator=False)
    join(access, "phone")
    join(access, "club1")
    manager = FakeManager()
    now = [5000.0]
    watcher = AccessWatcher(access, FakeRegistry(), manager, None, tmp_path, wall=lambda: now[0])
    request = tmp_path / KICK_REQUEST
    request.write_bytes(kick_request("phone", 5000.0))                      # un opérateur : jamais par ce canal
    asyncio.run(watcher.step())
    request.write_bytes(kick_request("club1", 4980.0))                      # trop ancienne
    asyncio.run(watcher.step())
    assert manager.kicked == [] and not request.exists()
    request.write_bytes(b"pas du json")
    asyncio.run(watcher.step())
    request.write_bytes(kick_request("club1", 4995.0))
    asyncio.run(watcher.step())
    assert manager.kicked == [("club1", "kicked")] and not request.exists()


# --------------------------------------------------------------------------- bout en bout (aiortc)

def _aiortc():
    try:
        import aiohttp, aiortc, av  # noqa: F401
        return True
    except ImportError:
        return False


def test_webrtc_listeners_admission_whitelist_silence_and_operator_wait(tmp_path):
    if not _aiortc():
        return
    from trxstation.devtools.fake_client import FakeClient, ToneTrack
    from trxstation.devtools.loopback import LISTENER_PASSWORDS, PASSWORDS, Loopback
    from trxstation.gateway.audio.devices import ToneSource

    async def scenario():
        async with Loopback(source=ToneSource(440.0, -10), access=Access(max_listeners=1, operator_grace_s=1)) as lb:
            watcher = AccessWatcher(lb.access, lb.registry, lb.manager, None, tmp_path, interval_s=0.2)
            stop = asyncio.Event()
            watch = asyncio.ensure_future(watcher.run(stop))
            early = FakeClient(lb.url, "club1", LISTENER_PASSWORDS["club1"])
            with pytest.raises(ConnectionRefusedError):
                await early.connect()
            assert early.refused == "operator_absent"
            await early.close()

            phone = FakeClient(lb.url, "phone", PASSWORDS["phone"])
            await phone.connect()
            visitor = FakeClient(lb.url, "club1", LISTENER_PASSWORDS["club1"], track=ToneTrack(1000.0, -10.0, active=True))
            await visitor.connect()
            assert visitor.hello["role"] == "listener" and visitor.hello["pseudo"] == "Club 1"
            await until(lambda: visitor.rx_frames >= 20 and visitor.rx_loud_times, 10)   # il entend le poste
            second = FakeClient(lb.url, "club2", LISTENER_PASSWORDS["club2"])
            with pytest.raises(ConnectionRefusedError):
                await second.connect()
            assert second.refused == "listeners_full"
            await second.close()

            result = await visitor.command("toggle")
            assert result["reason"] == "forbidden" and lb.fake.ptt == 0 and lb.ctrl.clients == ["phone"]
            assert (await phone.command("toggle"))["ok"] and lb.fake.ptt == 1
            phone.start_heartbeat()
            await asyncio.sleep(0.5)
            assert lb.pipeline.gate.dropped_not_owner == 0                   # le micro du visiteur n'atteint même pas la porte
            assert (await phone.command("toggle"))["ok"] and lb.fake.ptt == 0

            lb.fake.freq = 10_000_000                                        # hors bandes : silence pour le visiteur
            await asyncio.sleep(0.6)
            loud = len(visitor.rx_loud_times)
            await asyncio.sleep(0.6)
            assert len(visitor.rx_loud_times) == loud
            lb.fake.freq = 14_200_000

            await phone.close()                                             # opérateur perdu : attente d'1 s puis « bye »
            await until(lambda: visitor.bye is not None, 10)
            assert visitor.bye["reason"] == "operator_absent"
            await until(lambda: "club1" not in lb.manager.peers, 5)
            await visitor.close()
            stop.set()
            await watch
    asyncio.run(asyncio.wait_for(scenario(), 90))
