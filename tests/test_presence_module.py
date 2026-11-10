# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Présence de groupe, lot 3a : module de la station contre le faux relais (devtools/fake_presence_relay.py)."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.devtools.fake_presence_relay import FakeRelay
from trxstation.presence import roster as ro
from trxstation.presence.codec import b64e
from trxstation.presence.engine import ActionRefused, Engine
from trxstation.presence.identity import Identity
from trxstation.presence.service import PresenceService
from trxstation.presence.store import Store

NOW = 1_794_000_000
TZ = timezone(timedelta(hours=1))
RELAY = "https://api.rf-diy.com"


class Clock:
    def __init__(self) -> None:
        self.t = float(NOW)

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    relay = FakeRelay(clock)
    made = {}

    def make(name: str, pseudo: str | None = None) -> Engine:
        ident = Identity.generate()
        store = Store(tmp_path / name)
        store.data["pseudo"] = pseudo or name.upper()
        eng = Engine(store, ident, relay.transport(ident), relay_url=RELAY, version="0.117.0", clock=clock, tz=TZ)
        made[name] = eng
        return eng

    return clock, relay, make


def run(coro):
    return asyncio.run(coro)


def rounds(clock: Clock, engines, n: int = 1, step: float = 60.0) -> None:
    async def go():
        for _ in range(n):
            clock.t += step
            for e in engines:
                await e.cycle()
    run(go())


def member_view(eng: Engine, g: str, other: Engine) -> dict:
    group = next(x for x in eng.view()["groups"] if x["g"] == g)
    return next(m for m in group["members"] if m["id"] == other.me)


def group_of(world, admin_name="a", names=("b", "c")):
    clock, relay, make = world
    a = make(admin_name)
    others = [make(n) for n in names]
    rounds(clock, [a, *others])                          # enregistrement (preuve de travail)
    g = run(a.create_group("Amis du radio-club"))
    for o in others:
        run(o.join(a.invitation(g), "Amis"))
    rounds(clock, [a, *others], 2)
    return a, others, g


# ------------------------------------------------------------------ enregistrement, groupe, états
def test_registration_with_proof_of_work_then_nothing_without_pseudo(world):
    clock, relay, make = world
    a = make("a")
    assert run(a.cycle()) == 90 and a.store.data["registered"] and a.problem is None
    assert relay.stations[a.me]["pseudo"] == "A"
    lone = make("z")
    lone.store.data["pseudo"] = ""
    before = len(relay.requests)
    assert run(lone.cycle()) == 60 and lone.problem == "pseudo_missing" and len(relay.requests) == before
    lone.store.data["registered"] = True                 # fichier perdu côté relais : réenregistrement
    relay.stations.pop(lone.me, None)
    lone.store.data["pseudo"] = "Z"
    run(lone.cycle())
    assert lone.problem == "relay_error_unknown_station" and not lone.store.data["registered"]
    clock.t += 60
    run(lone.cycle())
    assert lone.store.data["registered"] and lone.problem is None


def test_full_group_life_status_frequency_and_qso(world):
    clock, relay, make = world
    a, (b, c), g = group_of(world)
    assert [b.store.groups[g]["status"], c.store.groups[g]["status"]] == ["member", "member"]
    assert b.store.groups[g]["role"] == "m" and a.store.groups[g]["role"] == "a"
    b.set_share(g, level="f")
    b.set_rig(14_074_000, "PKTUSB")
    b.on_rig(14_205_000, "USB")                          # changement = activité => En RX
    c.on_ptt(True)                                       # émission => En QSO
    rounds(clock, [b, c, a])
    vb, vc = member_view(a, g, b), member_view(a, g, c)
    assert (vb["code"], vb["f"], vb["m"], vb["lv"]) == ("R", 14_205_000, "USB", "f")
    assert vc["code"] == "Q" and vc["lv"] == "o" and "f" not in vc
    assert member_view(b, g, a)["code"] == "A"           # l'administrateur ne fait rien : absent
    c.on_ptt(False)
    rounds(clock, [c, a], 11)                            # 10 min après la dernière émission : plus en QSO
    assert member_view(a, g, c)["code"] == "A"
    view = json.dumps(a.view())
    assert a.store.groups[g]["key"] not in view and "key" not in a.status_summary()["groups"][0]
    assert "14205000" not in json.dumps(a.status_summary())


def test_exclusion_rotates_the_key_and_the_excluded_station_reads_nothing_more(world):
    clock, relay, make = world
    a, (b, c), g = group_of(world)
    old_key = a.store.groups[g]["key"]
    run(a.exclude(g, c.me))
    assert a.store.groups[g]["kv"] == 2 and a.store.groups[g]["key"] != old_key
    b.on_activity()
    rounds(clock, [b, c, a], 2)
    assert b.store.groups[g]["kv"] == 2 and b.store.groups[g]["key"] == a.store.groups[g]["key"]
    assert c.store.groups[g]["status"] == "removed" and c.store.groups[g]["kv"] == 1
    assert member_view(a, g, b)["code"] == "R"
    assert c.me not in a.store.groups[g]["members"]
    with pytest.raises(ActionRefused):
        run(b.exclude(g, a.me))                          # un simple membre n'exclut personne


def test_leaving_member_triggers_a_rotation_by_the_admin(world):
    clock, relay, make = world
    a, (b, c), g = group_of(world)
    run(c.leave(g))
    assert g not in c.store.groups
    rounds(clock, [a, b], 2)
    assert a.store.groups[g]["kv"] == 2 == b.store.groups[g]["kv"]
    assert ro.parse_unchecked(a.store.groups[g]["roster"]).member(c.me) is None


def test_co_admin_and_delete(world):
    clock, relay, make = world
    a, (b, c), g = group_of(world)
    run(a.set_role(g, b.me, "c"))
    rounds(clock, [b, a])
    assert b.store.groups[g]["role"] == "c"
    url = b.invitation(g)                                 # un co-administrateur invite
    d = make("d")
    rounds(clock, [d])
    run(d.join(url))
    rounds(clock, [b, a, d], 2)
    assert d.store.groups[g]["status"] == "member"
    with pytest.raises(ActionRefused) as err:
        run(b.exclude(g, a.me))
    assert err.value.reason == "not_admin"
    with pytest.raises(ActionRefused):
        run(b.delete_group(g))
    run(a.delete_group(g))
    rounds(clock, [b, c])
    assert b.store.groups[g]["status"] == "removed" and g not in a.store.groups


# ------------------------------------------------------------------ invitations
def test_invitation_is_single_use_and_expires(world):
    clock, relay, make = world
    a, (b,), g = group_of(world, names=("b",))
    url = a.invitation(g)
    c, d = make("c"), make("d")
    rounds(clock, [c, d])
    run(c.join(url))
    rounds(clock, [a])
    run(d.join(url))                                      # même jeton : refusé par l'administrateur
    rounds(clock, [a, c, d], 2)
    assert c.store.groups[g]["status"] == "member" and d.store.groups[g]["status"] == "pending"
    assert d.me not in relay.groups[g]["pending"]         # rejetée
    short = a.invitation(g, ttl_s=60)
    clock.t += 120
    e = make("e")
    rounds(clock, [e])
    with pytest.raises(ActionRefused) as err:
        run(e.join(short))
    assert err.value.reason == "invitation_expired"
    with pytest.raises(ActionRefused) as err:
        run(c.join(a.invitation(g)))
    assert err.value.reason == "already"
    other = a.invitation(g).replace(RELAY, "https://autre.example")
    with pytest.raises(ActionRefused):
        run(e.join(other))


# ------------------------------------------------------------------ relais malveillant
def _attacker_roster(eng: Engine, g: str, attacker: Identity) -> dict:
    cur = ro.parse_unchecked(eng.store.groups[g]["roster"])
    forged = cur.next(t=NOW, members=[*cur.members, ro.new_member(attacker.ed_pub, attacker.x_pub, "a", NOW)])
    return ro.sign(forged, attacker)


def test_a_malicious_relay_cannot_add_its_key_nor_hand_a_fake_group_key(world):
    clock, relay, make = world
    a, (b,), g = group_of(world, names=("b",))
    attacker = Identity.generate()
    version = ro.parse_unchecked(b.store.groups[g]["roster"]).version
    key = b.store.groups[g]["key"]

    def tamper(station, route, reply):
        if station == b.me and route == "sync":
            for grp in reply.get("groups", []):
                grp["rosters"] = [_attacker_roster(b, g, attacker)]
                from trxstation.presence import invite
                fake = ro.parse_unchecked(grp["rosters"][0])
                grp["key"] = invite.key_box(attacker, fake, b.me, bytes(32))
        return reply

    relay.tamper_reply = tamper
    rounds(clock, [b])
    assert ro.parse_unchecked(b.store.groups[g]["roster"]).version == version
    assert b.store.groups[g]["key"] == key


def test_a_state_moved_to_another_member_is_refused(world):
    clock, relay, make = world
    a, (b, c), g = group_of(world)
    b.set_share(g, level="f")
    b.set_rig(7_074_000, "PKTUSB")
    rounds(clock, [b, c])

    def tamper(station, route, reply):
        if station == a.me and route == "sync":
            for grp in reply["groups"]:
                blobs = {m["id"]: m for m in grp["members"]}
                if "blob" in blobs.get(b.me, {}):
                    blobs[c.me].update(blob=blobs[b.me]["blob"], kv=blobs[b.me]["kv"])   # état de b attribué à c
        return reply

    relay.tamper_reply = tamper
    rounds(clock, [a])
    assert a.store.groups[g]["members"][c.me].get("refused", 0) >= 1
    assert a.store.groups[g]["members"][c.me].get("state", {}).get("f") != 7_074_000


def test_a_station_offline_beyond_the_relay_history_follows_by_a_jump(world):
    clock, relay, make = world
    relay.history = 1
    a, (b,), g = group_of(world, names=("b",))
    extra = [make(n) for n in ("c", "d")]
    rounds(clock, extra)
    for e in extra:                                        # deux nouvelles versions pendant que b dort
        run(e.join(a.invitation(g)))
        rounds(clock, [a, e], 2)
    rounds(clock, [b])
    roster = ro.parse_unchecked(b.store.groups[g]["roster"])
    assert {e.me for e in extra} <= {m.id for m in roster.members}


# ------------------------------------------------------------------ pannes du relais
def test_relay_down_clock_and_pause(world):
    clock, relay, make = world
    a = make("a")
    rounds(clock, [a])
    relay.down = True
    assert run(a.cycle()) == 60 and a.problem == "relay_unreachable"
    assert run(a.cycle()) == 120
    relay.down = False
    clock.t += 60
    assert run(a.cycle()) == 90 and a.problem is None
    relay.clock_offset = 1000
    clock.t += 60
    run(a.cycle())
    assert a.problem == "clock"
    relay.clock_offset = 0
    relay.pause = 300
    clock.t += 60
    assert run(a.cycle()) == 300 and a.problem == "relay_paused"
    relay.pause = 0
    with pytest.raises(ActionRefused) as err:
        relay.down = True
        run(a.create_group("X"))
    assert err.value.reason == "relay_unreachable"


# ------------------------------------------------------------------ partage, persistance, statistiques
def test_invisible_and_hidden_absence(world):
    clock, relay, make = world
    a, (b, c), g = group_of(world)
    b.set_share(g, level="f", invisible=True)
    c.set_share(g, level="x", text="Test antenne", hide_absence=True)
    b.set_rig(14_074_000, "PKTUSB")
    rounds(clock, [b, c, a])
    vb, vc = member_view(a, g, b), member_view(a, g, c)
    assert vb["code"] == "O" and "f" not in vb
    assert vc["code"] == "A" and vc["x"] == "Test antenne" and "sd" not in vc
    with pytest.raises(ActionRefused):
        c.set_share(g, level="x", text="café")


def test_restart_keeps_groups_keys_and_counters(world, tmp_path):
    clock, relay, make = world
    a, (b,), g = group_of(world, names=("b",))
    again = Engine(Store(tmp_path / "b"), b.identity, relay.transport(b.identity), relay_url=RELAY,
                   version="0.117.0", clock=clock, tz=TZ)
    assert again.store.groups[g]["key"] == b.store.groups[g]["key"]
    again.set_share(g, level="f")
    again.set_rig(3_615_000, "LSB")
    rounds(clock, [again, a])
    assert member_view(a, g, b)["f"] == 3_615_000


def test_admin_statistics_are_daily_aggregates(world):
    clock, relay, make = world
    a, (b,), g = group_of(world, names=("b",))
    for _ in range(4):
        b.on_activity()
        rounds(clock, [b, a])
    summary = a.admin_stats(g)[b.me]
    assert summary["active_days_month"] == 1 and summary["weeks"][0]["rx_min"] >= 2
    assert set(a.store.stats[g][b.me]) == {"2026-11-12"} or len(a.store.stats[g][b.me]) == 1
    with pytest.raises(ActionRefused):
        b.admin_stats(g)


def test_profile_texts_shack_and_names(world):
    clock, relay, make = world
    a = make("a")
    rounds(clock, [a])
    run(a.set_pseudo("F4ABC/P"))
    assert relay.stations[a.me]["pseudo"] == "F4ABC/P"
    with pytest.raises(ActionRefused):
        run(a.set_pseudo("Élodie"))
    a.set_texts(["Mobile", "Test antenne"])
    with pytest.raises(ActionRefused):
        a.set_texts(["<b>"])
    a.shack_for(7200)
    assert a.tracker.status(clock.t + 10).code == "S"
    a.shack_cancel()
    a.set_shack_rules([{"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59"}])
    assert a.tracker.status(clock.t).code == "S"
    with pytest.raises(ActionRefused):
        a.set_shack_rules([{"days": [9], "start": "12:00", "end": "13:00"}])
    with pytest.raises(ActionRefused):
        run(a.create_group("<script>"))


# ------------------------------------------------------------------ service et configuration
def test_service_creates_its_keys_writes_a_status_and_reads_the_bus(tmp_path):
    clock = Clock()
    relay = FakeRelay(clock)
    cfg = cfgmod.Config()
    cfg.supervisor.state_dir = str(tmp_path / "state")
    cfg.presence.enabled = True
    service = PresenceService(cfg, tmp_path / "station.toml", relay_factory=relay.transport, clock=clock)
    engine = service.setup()
    key = tmp_path / "state" / "presence" / "presence.key"
    assert key.exists()
    if os.name == "posix":
        assert key.stat().st_mode & 0o077 == 0
    engine.store.data["pseudo"] = "F4ABC"
    assert run(service.step()) == 90
    status = json.loads((tmp_path / "state" / "presence" / "status.json").read_text(encoding="utf-8"))
    assert status["enabled"] and status["registered"] and status["station"] == engine.me
    service.on_event("freq_mode", {"freq": 7_100_000, "mode": "LSB"})
    service.on_event("freq_mode", {"freq": 7_110_000, "mode": "LSB"})
    service.on_event("ptt", {"active": True})
    assert engine.tracker.status(clock.t).code == "Q" and engine.freq == 7_110_000

    async def broken():
        raise RuntimeError("panne inattendue")
    engine.cycle = broken
    assert run(service.step()) == 120 and engine.problem == "internal"
    again = PresenceService(cfg, tmp_path / "station.toml", relay_factory=relay.transport, clock=clock).setup()
    assert again.me == engine.me                          # mêmes clés au redémarrage


def test_presence_section_of_station_toml():
    cfg = cfgmod.Config()
    assert cfgmod._presence_problems(cfg.presence) == []
    text = cfgmod.render_toml(cfg)
    assert "[presence]" in text and 'relay_url = "https://rf-diy.com/orx-relay/public"' in text
    for bad in ("http://api.rf-diy.com", "ftp://x", "https://", 12):
        cfg.presence.relay_url = bad
        assert cfgmod._presence_problems(cfg.presence)
    cfg.presence.relay_url = "http://127.0.0.1:8099"
    assert cfgmod._presence_problems(cfg.presence) == []
    cfg.presence.key_file = "cles/presence.key"
    assert cfgmod.presence_key_path(cfg, Path("/etc/trx-remote/station.toml")) == Path("/etc/trx-remote/cles/presence.key")


def test_manifest_gives_no_right_on_the_rig():
    from trxstation.modules.manifest import load_manifest
    m = load_manifest(Path(__file__).resolve().parents[1] / "trxstation" / "modules" / "builtin" / "presence" / "manifest.toml")
    assert m.rights.commands == frozenset() and not m.rights.verify_tokens
    assert m.rights.events == {"freq_mode", "ptt", "operator_activity"}


def test_b64e_is_still_exported():
    assert b64e(b"\x00") == "AA"
