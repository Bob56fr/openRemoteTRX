# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Faux relais de présence, en mémoire, pour les tests du module (le vrai est en PHP, dépôt openRemoteTRX-relay).

Même contrat (docs/protocole-presence.md) : requêtes signées vérifiées par `wire.verify_request`, enregistrement avec
preuve de travail, listes signées gardées par version (historique borné), clés remises, états rangés sans être lus,
demandes d'adhésion, départs, vue des administrateurs. Plus strict que le vrai sur les listes (il applique les
règles de la station) : la station ne fabrique que des listes valables.

Simulations : `down = True` (relais injoignable), `clock_offset` (heure du relais décalée), `pause`, `history`
(versions gardées), et des crochets `tamper_reply(station, route, reply)` pour jouer un relais MALVEILLANT.

    relay = FakeRelay(clock=lambda: now)
    engine = Engine(store, identity, relay.transport(identity), …)
"""
from __future__ import annotations

import copy
import json
from typing import Callable

from ..presence import roster as ro
from ..presence.codec import Malformed, b64d, parse_json
from ..presence.identity import station_id_of
from ..presence.pow import pow_ok
from ..presence.relay import RelayUnavailable
from ..presence.wire import Counter, RequestRefused, build_request, clean_pseudo, verify_request


class _Refused(Exception):
    def __init__(self, status: int, reason: str, **extra) -> None:
        super().__init__(reason)
        self.status, self.reason, self.extra = status, reason, extra


class FakeRelay:
    def __init__(self, clock: Callable[[], float], *, pow_bits: int = 4, next_in: int = 90, history: int = 50) -> None:
        self.clock = clock
        self.pow_bits, self.next_in, self.history = pow_bits, next_in, history
        self.down = False
        self.pause = 0
        self.clock_offset = 0
        self.tamper_reply: Callable[[str, str, dict], dict] | None = None
        self.stations: dict[str, dict] = {}
        self.groups: dict[str, dict] = {}       # g -> {"rosters": {ver: env}, "ver", "members": {id: {...}}, "pending"}
        self.requests: list[tuple[str, str]] = []

    def now(self) -> int:
        return int(self.clock()) + self.clock_offset

    def transport(self, identity) -> "_Transport":
        return _Transport(self, identity)

    # ------------------------------------------------------------------ entrée
    def handle(self, sid: str, path: str, body: bytes, signature: str) -> tuple[int, dict]:
        now = self.now()
        route = path.removeprefix("/v1/")
        self.requests.append((sid, route))
        try:
            if self.pause:
                raise _Refused(503, "pause", retry_in=self.pause)
            if route == "register":
                obj = parse_json(body)
                ed = b64d(obj.get("ed"), 32)
                if station_id_of(ed) != sid:
                    raise _Refused(400, "malformed")
                verify_request(ed, path, body, signature, now=now, last_n=0)
                return 200, self._register(sid, obj, now)
            station = self.stations.get(sid)
            if station is None:
                raise _Refused(401, "unknown_station")
            obj = verify_request(b64d(station["ed"]), path, body, signature, now=now, last_n=station["last_n"])
            station["last_n"] = obj["n"]
            handler = {"profile": self._profile, "sync": self._sync, "group/create": self._create,
                       "group/join": self._join, "group/roster": self._roster, "group/leave": self._leave,
                       "group/delete": self._delete, "group/reject": self._reject}.get(route)
            if handler is None:
                raise _Refused(404, "unknown_route")
            reply = handler(sid, obj, now)
            return 200, {"ok": True, "now": now, **reply}
        except RequestRefused as exc:
            return 401 if exc.reason != "malformed" else 400, {"error": exc.reason, "now": now}
        except Malformed:
            return 400, {"error": "malformed", "now": now}
        except _Refused as exc:
            return exc.status, {"error": exc.reason, "now": now, **exc.extra}

    # ------------------------------------------------------------------ points d'entrée
    def _register(self, sid: str, obj: dict, now: int) -> dict:
        if clean_pseudo(obj.get("pseudo")) != obj.get("pseudo"):
            raise _Refused(400, "malformed")
        if not pow_ok(sid, obj.get("pow"), self.pow_bits):
            raise _Refused(403, "pow", bits=self.pow_bits)
        if sid in self.stations:
            raise _Refused(409, "exists")
        self.stations[sid] = {"ed": obj["ed"], "x": obj["x"], "pseudo": obj["pseudo"], "version": obj.get("version"),
                              "last_seen": now, "last_sync": 0, "last_n": obj["n"]}
        return {"ok": True, "now": now, "bits": self.pow_bits}

    def _profile(self, sid: str, obj: dict, now: int) -> dict:
        if clean_pseudo(obj.get("pseudo")) != obj.get("pseudo"):
            raise _Refused(400, "malformed")
        self.stations[sid]["pseudo"] = obj["pseudo"]
        return {}

    def _group(self, g) -> dict:
        grp = self.groups.get(g)
        if grp is None:
            raise _Refused(404, "unknown_group")
        return grp

    def _keep(self, grp: dict, env: dict) -> None:
        ver = ro.parse_unchecked(env).version
        grp["rosters"][ver] = copy.deepcopy(env)
        grp["ver"] = ver
        for old in [v for v in grp["rosters"] if v <= ver - self.history]:
            del grp["rosters"][old]

    def _align(self, g: str, grp: dict, roster: ro.Roster, now: int) -> None:
        members = grp["members"]
        for sid in [s for s in members if roster.member(s) is None]:
            del members[sid]
        for m in roster.members:
            if m.id in self.stations and m.id not in members:
                members[m.id] = {"joined": now, "blob": None, "kv": None, "blob_at": 0, "key": None, "key_at": 0,
                                 "left": None}
            grp["pending"].pop(m.id, None)

    def _create(self, sid: str, obj: dict, now: int) -> dict:
        g = obj.get("g")
        if g in self.groups:
            raise _Refused(409, "exists")
        try:
            roster = ro.accept_first(obj.get("roster"), group=g, admin=sid)
        except ro.RosterRefused as exc:
            raise _Refused(403, "not_admin") from exc
        grp = {"rosters": {}, "ver": 0, "members": {}, "pending": {}}
        self.groups[g] = grp
        self._keep(grp, obj["roster"])
        self._align(g, grp, roster, now)
        return {}

    def _join(self, sid: str, obj: dict, now: int) -> dict:
        req = {k: v for k, v in obj.items() if k not in ("t", "n")}
        st = self.stations[sid]
        if req.get("id") != sid or req.get("ed") != st["ed"] or req.get("x") != st["x"]:
            raise _Refused(400, "malformed")
        grp = self._group(req.get("g"))
        if sid in grp["members"]:
            raise _Refused(409, "exists")
        grp["pending"][sid] = (req, now)
        return {}

    def _roster(self, sid: str, obj: dict, now: int) -> dict:
        g = obj.get("g")
        grp = self._group(g)
        current = ro.parse_unchecked(grp["rosters"][grp["ver"]])
        try:
            new = ro.accept_next(current, obj.get("roster"), admin_last_seen=now, now=now)
        except ro.RosterRefused as exc:
            raise _Refused(409 if exc.reason in ("version", "chain") else 403, "stale_roster"
                           if exc.reason in ("version", "chain") else "not_admin") from exc
        if obj["roster"]["by"] != sid:
            raise _Refused(403, "not_admin")
        self._keep(grp, obj["roster"])
        self._align(g, grp, new, now)
        for box in obj.get("keys") or []:
            if box.get("kv") != new.kv or box.get("by") != sid or box.get("for") not in grp["members"]:
                raise _Refused(400, "malformed")
            grp["members"][box["for"]].update(key=copy.deepcopy(box), key_at=now)
        for rid in obj.get("reject") or []:
            grp["pending"].pop(rid, None)
        return {}

    def _reject(self, sid: str, obj: dict, now: int) -> dict:
        grp = self._group(obj.get("g"))
        me = ro.parse_unchecked(grp["rosters"][grp["ver"]]).member(sid)
        if me is None or me.role not in ("a", "c"):
            raise _Refused(403, "not_admin")
        for rid in obj.get("ids") or []:
            grp["pending"].pop(rid, None)
        return {}

    def _leave(self, sid: str, obj: dict, now: int) -> dict:
        grp = self._group(obj.get("g"))
        pending = grp["pending"].pop(sid, None)
        member = grp["members"].get(sid)
        if member is None or member["left"] is not None:
            if pending is None:
                raise _Refused(403, "not_member")
            return {}
        member.update(left=now, blob=None, kv=None)
        return {}

    def _delete(self, sid: str, obj: dict, now: int) -> dict:
        g = obj.get("g")
        grp = self._group(g)
        roster = ro.parse_unchecked(grp["rosters"][grp["ver"]])
        me = roster.member(sid)
        if me is None or me.role != "a":
            raise _Refused(403, "not_admin")
        del self.groups[g]
        return {}

    def _sync(self, sid: str, obj: dict, now: int) -> dict:
        st = self.stations[sid]
        if st["last_sync"] and now - st["last_sync"] < self.next_in // 2:
            raise _Refused(429, "rate", retry_in=self.next_in // 2 - (now - st["last_sync"]))
        known, since = obj.get("known") or {}, obj.get("since") or 0
        refused = []
        for i, s in enumerate(obj.get("states") or []):
            grp = self.groups.get(s.get("g"))
            m = grp["members"].get(sid) if grp else None
            ok = m is not None and m["left"] is None and isinstance(s.get("blob"), str) and len(s["blob"]) == 342
            if ok:
                m.update(blob=s["blob"], kv=s.get("kv"), blob_at=now)
            else:
                refused.append(i)
        st["last_seen"] = st["last_sync"] = now
        groups = []
        for g, grp in sorted(self.groups.items()):
            me = grp["members"].get(sid)
            if me is None or me["left"] is not None:
                continue
            out: dict = {"g": g}
            k = known.get(g, 0) if isinstance(known.get(g, 0), int) else 0
            if k < grp["ver"]:
                out["rosters"] = [copy.deepcopy(grp["rosters"][v]) for v in sorted(grp["rosters"]) if v > k][:50]
            if me["key"] is not None and (me["key_at"] > since or "rosters" in out):
                out["key"] = copy.deepcopy(me["key"])
            members = []
            for mid, m in sorted(grp["members"].items()):
                if mid == sid or m["left"] is not None or mid not in self.stations:
                    continue
                entry = {"id": mid, "pseudo": self.stations[mid]["pseudo"],
                         "age": max(0, now - self.stations[mid]["last_seen"])}
                if m["blob"] is not None and m["blob_at"] > since:
                    entry.update(kv=m["kv"], blob=m["blob"])
                members.append(entry)
            out["members"] = members
            role = ro.parse_unchecked(grp["rosters"][grp["ver"]]).member(sid)
            if role is not None and role.role in ("a", "c"):
                out["pending"] = [copy.deepcopy(r) for r, _ in grp["pending"].values()]
                out["left"] = sorted(mid for mid, m in grp["members"].items() if m["left"] is not None)
                out["admin"] = [{"id": mid, "joined": m["joined"], "version": self.stations.get(mid, {}).get("version")}
                                for mid, m in sorted(grp["members"].items())]
            groups.append(out)
        reply = {"now": now, "next_in": self.next_in, "groups": groups}
        if refused:
            reply["refused_states"] = refused
        return reply


class _Transport:
    """Ce que voit le moteur : `post(route, champs)`, comme HttpRelay (requête signée, puis réponse JSON)."""

    def __init__(self, relay: FakeRelay, identity) -> None:
        self.relay, self.identity = relay, identity
        self.counter = Counter(clock=relay.clock)

    async def post(self, route: str, fields: dict) -> tuple[int, dict]:
        if self.relay.down:
            raise RelayUnavailable("faux relais coupé")
        path = f"/v1/{route}"
        body, headers = build_request(self.identity, path, fields, t=int(self.relay.clock()), n=self.counter.next())
        code, reply = self.relay.handle(headers["X-Orx-Station"], path, body, headers["X-Orx-Signature"])
        reply = json.loads(json.dumps(reply))          # comme une vraie réponse : rien de partagé avec le relais
        if self.relay.tamper_reply is not None:
            reply = self.relay.tamper_reply(self.identity.station_id, route, reply)
        return code, reply

