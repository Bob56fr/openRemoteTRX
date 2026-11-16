# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Faux relais du monitoring, en mémoire, pour les tests du module « monlink » (aucun réseau).

Même comportement que `src/MonApi.php` du dépôt du relais (docs/protocole-monlink.md § 4 à § 6) : signatures
vérifiées, invitation à usage unique, appairage seulement par la station qui a lu l'invitation, types par sens,
autorisations, fin de liaison immédiate, quotas. Le VRAI relais est essayé à part (`tests/e2e_monlink.py` du dépôt
du relais, en local et en ligne).

    relay = FakeMonRelay(clock=lambda: now)
    client = relay.transport(identity)          # même interface que monlink.relay.HttpRelay : await call(route, champs)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from ..monlink import envelope, wire
from ..monlink.identity import station_id_of
from ..monlink.relay import RelayRefused, RelayUnavailable, check
from ..presence import pow as pw
from ..presence.codec import Malformed, b64d
from ..presence.wire import Counter, RequestRefused

INVITE_TTL = 900
MAX_INVITES, MAX_LINKS = 3, 20
DAY_BYTES, DAY_BYTES_ASSIST, BOX_BYTES, GET_BYTES = 2 << 20, 10 << 20, 5 << 20, 512 << 10
FROM_EMITTER, FROM_RECEIVER = envelope.FROM_EMITTER, envelope.FROM_RECEIVER


class _Refuse(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


@dataclass
class FakeMonRelay:
    clock: object = time.time
    pow_bits: int = 4
    down: bool = False                        # vrai : relais injoignable (RelayUnavailable)
    stations: dict = field(default_factory=dict)       # id -> {"ed": bytes, "last_n": int}
    invites: dict = field(default_factory=dict)        # a -> {"owner", "box", "e", "taken_by", "taken_at", "paired"}
    links: dict = field(default_factory=dict)          # (receiver, emitter) -> {"day", "bytes", "assist_day"}
    allow: set = field(default_factory=set)            # (owner, peer)
    msgs: list = field(default_factory=list)           # {"id", "owner", "from", "k", "msg", "size", "at"}
    next_id: int = 1
    calls: list = field(default_factory=list)          # (station, route) : ce qu'ont demandé les stations

    def transport(self, identity) -> "_Client":
        return _Client(self, identity)

    # ------------------------------------------------------------ requête signée
    def handle(self, path: str, body: bytes, headers: dict) -> tuple[int, dict]:
        now = int(self.clock())
        try:
            route = path.rsplit("/v1/mon/", 1)[-1]
            sid = headers["X-Orx-Station"]
            self.calls.append((sid, route))
            obj = json.loads(body)
            if route == "register":
                ed = b64d(obj.get("ed"), 32)
                if station_id_of(ed) != sid:
                    raise _Refuse(400, "malformed")
                wire.verify_request(ed, path, body, headers["X-Orx-Signature"], now=now, last_n=0)
                if not isinstance(obj.get("pow"), int) or not pw.pow_ok(sid, obj["pow"], self.pow_bits):
                    return 403, {"error": "pow", "bits": self.pow_bits, "now": now}
                if sid in self.stations:
                    raise _Refuse(409, "exists")
                self.stations[sid] = {"ed": ed, "last_n": obj["n"]}
                return 200, {"ok": True, "now": now}
            st = self.stations.get(sid)
            if st is None:
                raise _Refuse(401, "unknown_station")
            wire.verify_request(st["ed"], path, body, headers["X-Orx-Signature"], now=now, last_n=st["last_n"])
            st["last_n"] = obj["n"]
            out = getattr(self, "_" + route.replace("/", "_"))(sid, obj, now)
            return 200, {**out, "ok": True, "now": now}
        except _Refuse as exc:
            return exc.status, {"error": exc.reason, "now": now}
        except RequestRefused as exc:
            return (404 if exc.reason == "unknown_route" else 401), {"error": exc.reason, "now": now}
        except (Malformed, KeyError, TypeError, ValueError, AttributeError):
            return 400, {"error": "malformed", "now": now}

    # ------------------------------------------------------------ routes
    def _link(self, a: str, b: str) -> tuple[str, str] | None:
        """Clé (receveur, émetteur) de la liaison entre a et b, dans un sens ou dans l'autre."""
        if (a, b) in self.links:
            return (a, b)
        if (b, a) in self.links:
            return (b, a)
        return None

    def _invite_put(self, sid, obj, now):
        a, e = obj["a"], obj["e"]
        if not isinstance(e, int) or not now < e <= now + INVITE_TTL or len(b64d(obj["box"])) > 2048:
            raise _Refuse(400, "malformed")
        if sum(1 for i in self.invites.values() if i["owner"] == sid and i["e"] > now and i["box"]) >= MAX_INVITES:
            raise _Refuse(403, "quota")
        if a in self.invites:
            raise _Refuse(409, "exists")
        self.invites[a] = {"owner": sid, "box": obj["box"], "e": e, "taken_by": None, "taken_at": 0, "paired": False}
        return {}

    def _invite_take(self, sid, obj, now):
        inv = self.invites.get(obj["a"])
        if inv is None or not inv["box"] or inv["e"] <= now or inv["owner"] == sid:
            raise _Refuse(404, "unknown_invite")
        box, inv["box"], inv["taken_by"], inv["taken_at"] = inv["box"], None, sid, now
        return {"box": box, "e": inv["e"]}

    def _pair(self, sid, obj, now):
        req = obj["req"]
        if not isinstance(req, dict) or set(req) != {"a", "from", "to", "box", "s"} or req["from"] != sid:
            raise _Refuse(400, "malformed")
        inv = self.invites.get(req["a"])
        if inv is None or inv["taken_by"] != sid or inv["taken_at"] < now - INVITE_TTL or inv["paired"] \
                or inv["owner"] != req["to"]:
            raise _Refuse(404, "unknown_invite")
        count = lambda s: sum(1 for k in self.links if s in k)        # noqa: E731
        if self._link(sid, req["to"]) is None and (count(sid) >= MAX_LINKS or count(req["to"]) >= MAX_LINKS):
            raise _Refuse(403, "quota")
        inv["paired"] = True
        self.links.setdefault((req["to"], sid), {"day": 0, "bytes": 0, "assist_day": 0})
        self._store(req["to"], sid, "pair", req, now)
        return {}

    def _allow(self, sid, obj, now):
        if self._link(sid, obj["peer"]) is None:
            raise _Refuse(403, "not_linked")
        self.allow.add((sid, obj["peer"]))
        return {}

    def _revoke(self, sid, obj, now):
        peer = obj["peer"]
        self.allow -= {(sid, peer), (peer, sid)}
        self.links.pop((sid, peer), None)
        self.links.pop((peer, sid), None)
        self.msgs = [m for m in self.msgs if {m["owner"], m["from"]} != {sid, peer}]
        return {}

    def _put(self, sid, obj, now):
        msg, assist = obj["msg"], obj.get("assist", False)
        if not isinstance(msg, dict) or set(msg) != {"f", "to", "k", "q", "b"} or msg["f"] != sid \
                or not isinstance(assist, bool):
            raise _Refuse(400, "malformed")
        size = len(json.dumps(msg, separators=(",", ":")))
        if size > envelope.MAX_ENVELOPE:
            raise _Refuse(400, "too_large")
        key = self._link(sid, msg["to"])
        if key is None:
            raise _Refuse(403, "not_linked")
        emitter = key[1] == sid
        if msg["k"] not in (FROM_EMITTER if emitter else FROM_RECEIVER):
            raise _Refuse(403, "direction")
        if (msg["to"], sid) not in self.allow:
            raise _Refuse(403, "not_allowed")
        link, day = self.links[key], now // 86400
        used = link["bytes"] if link["day"] == day else 0
        assist_day = day if assist and emitter else link["assist_day"]
        if used + size > (DAY_BYTES_ASSIST if assist_day == day else DAY_BYTES):
            raise _Refuse(403, "quota")
        if sum(m["size"] for m in self.msgs if m["owner"] == msg["to"]) + size > BOX_BYTES:
            raise _Refuse(403, "quota")
        link.update(day=day, bytes=used + size, assist_day=assist_day)
        self._store(msg["to"], sid, msg["k"], msg, now, size)
        return {}

    def _get(self, sid, obj, now):
        after, out, total, more = obj["after"], [], 0, False
        for m in (m for m in self.msgs if m["owner"] == sid and m["id"] > after):
            if out and (total + m["size"] > GET_BYTES or len(out) >= 200):
                more = True
                break
            total += m["size"]
            out.append({"id": m["id"], "from": m["from"], "k": m["k"], "msg": json.loads(json.dumps(m["msg"]))})
        return {"msgs": out, "more": more}

    def _ack(self, sid, obj, now):
        self.msgs = [m for m in self.msgs if not (m["owner"] == sid and m["id"] <= obj["upto"])]
        return {}

    def _store(self, owner, frm, k, msg, now, size=None):
        self.msgs.append({"id": self.next_id, "owner": owner, "from": frm, "k": k, "msg": msg, "at": now,
                          "size": size or len(json.dumps(msg))})
        self.next_id += 1


class _Client:
    def __init__(self, relay: FakeMonRelay, identity) -> None:
        self.relay, self.identity, self.counter = relay, identity, Counter(clock=lambda: relay.clock())

    async def call(self, route: str, fields: dict) -> dict:
        if self.relay.down:
            raise RelayUnavailable("relais d'essai coupé")
        path, body, headers = wire.build_request(self.identity, route, fields, t=int(self.relay.clock()),
                                                 n=self.counter.next(), prefix="/orx-relay/public")
        return check(*self.relay.handle(path, body, headers))

    async def close(self) -> None:
        pass


__all__ = ["FakeMonRelay", "RelayRefused", "RelayUnavailable"]
