# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Logique du module de présence : enregistrement, requête périodique, groupes, invitations, rotation des clés.

Aucun accès au poste : le moteur reçoit la fréquence, le mode et l'émission (événements du bus) et ne renvoie que
des vues. Le relais est un objet `post(route, champs) -> (code, réponse)` (HttpRelay, ou le faux relais des tests).
Tout ce qui vient du relais est revérifié ici (liste signée, clés remises signées, états signés) : le relais n'est
jamais cru sur parole.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime

from . import crypto, invite, roster as ro, state as st, stats as stt_stats
from .codec import Malformed, b64d, b64e, station_id_ok
from .pow import pow_solve
from .relay import RelayUnavailable
from .status import OFFLINE_AFTER_S, ShackRule, StatusTracker, display_code, sort_key
from .wire import Counter, clean_pseudo, clean_text

log = logging.getLogger("trx.presence")

DEFAULT_NEXT_IN = 90
MIN_NEXT_IN, MAX_NEXT_IN = 30, 3600
MAX_POW_BITS = 28
MAX_CREATED = 5
MAX_GROUPS = 20
MAX_TEXTS = 8
OLD_KEYS_KEPT = 2
GROUP_NAME_MAX = 24
_NAME_BAD = re.compile(r"[\x00-\x1f\x7f<>]")


class ActionRefused(ValueError):
    """Action de l'opérateur refusée ; `reason` : motif court (affiché par la page, l'application, la console)."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


def clean_group_name(name: object) -> str | None:
    if not isinstance(name, str):
        return None
    name = " ".join(name.split())
    return name if 1 <= len(name) <= GROUP_NAME_MAX and not _NAME_BAD.search(name) else None


def _new_record(name: str, *, role: str, status: str, key: bytes, kv: int, roster_env: dict | None,
                invite_admin: str, now: float) -> dict:
    return {"name": name, "role": role, "status": status, "key": b64e(key), "kv": kv, "old_keys": {},
            "roster": roster_env, "invite_admin": invite_admin, "joined": int(now), "admin_last_seen": int(now),
            "share": {"level": "o", "text": None, "invisible": False, "hide_absence": False},
            "tokens": {}, "used": [], "members": {}}


class Engine:
    def __init__(self, store, identity, relay, *, relay_url: str, version: str, clock=time.time, tz=None,
                 solver=None) -> None:
        self.store, self.identity, self.relay = store, identity, relay
        self.relay_url = relay_url.rstrip("/")
        self.version = version
        self.clock = clock
        self.tz = tz or datetime.now().astimezone().tzinfo
        self.solver = solver or (lambda sid, bits: asyncio.to_thread(pow_solve, sid, bits))
        self.tracker = StatusTracker(started=clock(), tz=self.tz)
        self._load_shack()
        self.freq: int | None = None
        self.mode: str | None = None
        self.next_in = DEFAULT_NEXT_IN
        self.since = 0
        self.problem: str | None = None
        self.last_sync: float | None = None
        self.failures = 0
        self._retry_in: int | None = None
        self.counter = Counter()
        self.me = identity.station_id

    # ------------------------------------------------------------------ événements de la station
    def set_rig(self, freq: object, mode: object) -> None:
        """État relu (connexion au bus) : pas une activité."""
        self.freq = freq if isinstance(freq, int) else None
        self.mode = mode if isinstance(mode, str) else None

    def on_rig(self, freq: object, mode: object) -> None:
        before = (self.freq, self.mode)
        known = before != (None, None)
        self.set_rig(freq, mode)
        if known and (self.freq, self.mode) != before:
            self.tracker.activity(self.clock())

    def on_ptt(self, active: object) -> None:
        self.tracker.tx(bool(active), self.clock())

    def on_activity(self) -> None:
        """Commande d'un client opérateur, client opérateur connecté (jamais un visiteur)."""
        self.tracker.activity(self.clock())

    # ------------------------------------------------------------------ profil
    @property
    def pseudo(self) -> str:
        return self.store.data.get("pseudo") or ""

    async def set_pseudo(self, pseudo: str) -> None:
        clean = clean_pseudo(pseudo)
        if clean is None:
            raise ActionRefused("pseudo", "pseudo refusé (1 à 16 caractères : lettres sans accent, chiffres, "
                                          "espace, . / _ -)")
        self.store.data["pseudo"] = clean
        self.store.save()
        if self.store.data.get("registered"):
            await self._post_ok("profile", {"pseudo": clean, "version": self.version})

    def set_texts(self, texts: list) -> None:
        clean = [clean_text(x) for x in texts][:MAX_TEXTS]
        if any(c is None for c in clean):
            raise ActionRefused("text", "texte refusé (16 caractères : lettres sans accent, chiffres, espace, . / -)")
        self.store.data["texts"] = clean
        self.store.save()

    def set_shack_rules(self, rules: list[dict], suspended_until: float | None = None) -> None:
        try:
            parsed = [ShackRule(frozenset(r["days"]), r["start"], r["end"]) for r in rules]
        except (KeyError, TypeError, ValueError) as exc:
            raise ActionRefused("shack", f"plage « Au shack » refusée : {exc}") from exc
        self.store.data["shack"]["rules"] = [{"days": sorted(r.days), "start": r.start, "end": r.end} for r in parsed]
        self.store.data["shack"]["suspended_until"] = suspended_until
        self.store.save()
        self._load_shack()

    def shack_for(self, seconds: float) -> None:
        if not 60 <= seconds <= 24 * 3600:
            raise ActionRefused("shack", "durée de 1 min à 24 h")
        now = self.clock()
        self.store.data["shack"]["once"] = [now, now + seconds]
        self.store.save()
        self._load_shack()

    def shack_cancel(self) -> None:
        self.store.data["shack"]["once"] = None
        self.store.save()
        self._load_shack()

    def _load_shack(self) -> None:
        shack = self.store.data.get("shack") or {}
        rules = []
        for r in shack.get("rules") or []:
            try:
                rules.append(ShackRule(frozenset(r["days"]), r["start"], r["end"]))
            except (KeyError, TypeError, ValueError):
                log.warning("plage « Au shack » illisible ignorée : %r", r)
        self.tracker.rules = rules
        self.tracker.suspended_until = shack.get("suspended_until")
        once = shack.get("once")
        self.tracker.once = tuple(once) if isinstance(once, list) and len(once) == 2 else None

    # ------------------------------------------------------------------ groupes : actions de l'opérateur
    def _group(self, g: str) -> dict:
        rec = self.store.groups.get(g)
        if rec is None:
            raise ActionRefused("unknown_group", "groupe inconnu")
        return rec

    def _roster(self, rec: dict) -> ro.Roster | None:
        return ro.parse_unchecked(rec["roster"]) if rec.get("roster") else None

    def _need_registered(self) -> None:
        if not self.store.data.get("registered"):
            raise ActionRefused("not_registered", "station pas encore enregistrée auprès du relais")

    async def create_group(self, name: str) -> str:
        self._need_registered()
        clean = clean_group_name(name)
        if clean is None:
            raise ActionRefused("name", f"nom de groupe refusé (1 à {GROUP_NAME_MAX} caractères)")
        created = sum(1 for r in self.store.groups.values() if r.get("invite_admin") == self.me)
        if created >= MAX_CREATED or len(self.store.groups) >= MAX_GROUPS:
            raise ActionRefused("quota", "trop de groupes pour cette station")
        now = self.clock()
        g, key = invite.new_group_id(), crypto.random_key()
        first = ro.Roster(g, 1, "", int(now), 1, (ro.new_member(self.identity.ed_pub, self.identity.x_pub, "a", int(now)),))
        env = ro.sign(first, self.identity)
        await self._post_ok("group/create", {"g": g, "roster": env})
        self.store.groups[g] = _new_record(clean, role="a", status="member", key=key, kv=1, roster_env=env,
                                           invite_admin=self.me, now=now)
        self.store.save()
        log.info("groupe %s créé (%s)", g, clean)
        return g

    def invitation(self, g: str, ttl_s: int = invite.INVITE_TTL_S) -> str:
        rec = self._group(g)
        roster = self._roster(rec)
        me = roster.member(self.me) if roster else None
        if me is None or me.role not in ("a", "c") or rec["status"] != "member":
            raise ActionRefused("not_admin", "seul un administrateur du groupe peut inviter")
        now = self.clock()
        inv = invite.new_invitation(self.relay_url, g, b64d(rec["key"]), rec["kv"], self.me, now=now, ttl_s=ttl_s)
        tokens = {t: v for t, v in rec["tokens"].items() if v["exp"] > now}
        tokens[b64e(inv.token)] = {"exp": inv.expires, "key": rec["key"]}
        rec["tokens"] = tokens
        self.store.save()
        return inv.to_url()

    async def join(self, url: str, name: str = "") -> str:
        self._need_registered()
        try:
            inv = invite.parse_invitation(url, now=self.clock())
        except invite.InviteRefused as exc:
            raise ActionRefused(f"invitation_{exc.reason}", "invitation refusée : " + exc.reason) from exc
        if inv.relay.rstrip("/") != self.relay_url:
            raise ActionRefused("other_relay", f"invitation pour un autre relais ({inv.relay})")
        if inv.group in self.store.groups:
            raise ActionRefused("already", "déjà dans ce groupe (ou demande en attente)")
        if len(self.store.groups) >= MAX_GROUPS:
            raise ActionRefused("quota", "trop de groupes pour cette station")
        clean = clean_group_name(name) or f"Groupe {inv.group[:6]}"
        await self._post_ok("group/join", invite.join_request(inv, self.identity, self.pseudo))
        self.store.groups[inv.group] = _new_record(clean, role="m", status="pending", key=inv.key, kv=inv.kv,
                                                   roster_env=None, invite_admin=inv.admin, now=self.clock())
        self.store.save()
        log.info("demande d'adhésion envoyée pour le groupe %s", inv.group)
        return inv.group

    async def leave(self, g: str) -> None:
        self._group(g)
        try:
            await self._post_ok("group/leave", {"g": g})
        except ActionRefused as exc:
            if exc.reason not in ("not_member", "unknown_group"):
                raise
        self._forget(g)

    async def delete_group(self, g: str) -> None:
        rec = self._group(g)
        roster = self._roster(rec)
        me = roster.member(self.me) if roster else None
        if me is None or me.role != "a":
            raise ActionRefused("not_admin", "seul un administrateur peut supprimer le groupe")
        await self._post_ok("group/delete", {"g": g})
        self._forget(g)

    async def exclude(self, g: str, member: str) -> None:
        rec = self._group(g)
        roster = self._roster(rec)
        me = roster.member(self.me) if roster else None
        target = roster.member(member) if roster else None
        if me is None or me.role not in ("a", "c"):
            raise ActionRefused("not_admin", "seul un administrateur peut exclure")
        if target is None or member == self.me:
            raise ActionRefused("unknown_member", "membre absent du groupe")
        if target.role == "a" and me.role != "a":
            raise ActionRefused("not_admin", "un co-administrateur ne peut pas exclure un administrateur")
        await self._publish(g, rec, roster, remove={member}, add=[], reject=[])

    async def set_role(self, g: str, member: str, role: str) -> None:
        """Nommer ou retirer un co-administrateur, ou transférer le rôle d'administrateur (administrateur seul)."""
        rec = self._group(g)
        roster = self._roster(rec)
        me = roster.member(self.me) if roster else None
        target = roster.member(member) if roster else None
        if me is None or me.role != "a":
            raise ActionRefused("not_admin", "réservé à un administrateur")
        if target is None or role not in ro.ROLES:
            raise ActionRefused("unknown_member", "membre ou rôle inconnu")
        changed = [ro.Member(m.id, m.ed, m.x, role if m.id == member else m.role, m.joined) for m in roster.members]
        await self._publish(g, rec, roster, remove=set(), add=[], reject=[], members=changed)

    def set_share(self, g: str, *, level: str, text: str | None = None, invisible: bool = False,
                  hide_absence: bool = False) -> None:
        rec = self._group(g)
        try:
            share = st.Share(level, text if level == "x" else None, bool(invisible), bool(hide_absence))
        except ValueError as exc:
            raise ActionRefused("share", str(exc)) from exc
        rec["share"] = {"level": share.level, "text": share.text, "invisible": share.invisible,
                        "hide_absence": share.hide_absence}
        self.store.save()

    def rename(self, g: str, name: str) -> None:
        rec = self._group(g)
        clean = clean_group_name(name)
        if clean is None:
            raise ActionRefused("name", f"nom de groupe refusé (1 à {GROUP_NAME_MAX} caractères)")
        rec["name"] = clean
        self.store.save()

    def _forget(self, g: str) -> None:
        self.store.groups.pop(g, None)
        self.store.stats.pop(g, None)
        self.store.save()

    # ------------------------------------------------------------------ relais
    async def _post(self, route: str, fields: dict) -> tuple[int, dict]:
        try:
            return await self.relay.post(route, fields)
        except RelayUnavailable as exc:
            raise ActionRefused("relay_unreachable", f"relais injoignable : {exc}") from exc

    async def _post_ok(self, route: str, fields: dict) -> dict:
        code, reply = await self._post(route, fields)
        if code != 200:
            raise ActionRefused(str(reply.get("error") or f"http_{code}"), str(reply.get("message") or ""))
        return reply

    async def _register(self) -> bool:
        fields = {"ed": b64e(self.identity.ed_pub), "x": b64e(self.identity.x_pub), "pseudo": self.pseudo,
                  "version": self.version}
        code, reply = await self.relay.post("register", fields)
        if code == 403 and reply.get("error") == "pow":
            bits = reply.get("bits")
            if isinstance(bits, bool) or not isinstance(bits, int) or not 0 <= bits <= MAX_POW_BITS:
                self.problem = "pow_bits"
                return False
            log.info("enregistrement : preuve de travail (%d bits)…", bits)
            nonce = await self.solver(self.me, bits)
            code, reply = await self.relay.post("register", fields | {"pow": nonce})
        if code == 200 or (code == 409 and reply.get("error") == "exists"):
            self.store.data["registered"] = True
            self.store.save()
            log.info("station enregistrée auprès du relais (%s)", self.me)
            return True
        self.problem = f"register_{reply.get('error') or code}"
        log.warning("enregistrement refusé : %s %s", code, reply.get("message", ""))
        return False

    # ------------------------------------------------------------------ requête périodique
    async def cycle(self) -> float:
        """Une requête périodique ; renvoie le délai avant la suivante (secondes)."""
        now = self.clock()
        if not self.pseudo:
            self.problem = "pseudo_missing"
            return 60.0
        try:
            if not self.store.data.get("registered") and not await self._register():
                return self._backoff()
            reply = await self._sync(now)
        except RelayUnavailable as exc:
            self.problem = "relay_unreachable"
            log.warning("relais injoignable : %s", exc)
            return self._backoff()
        if reply is None:
            retry, self._retry_in = self._retry_in, None
            return float(retry) if retry else self._backoff()
        self.failures = 0
        self.problem = None
        self.last_sync = now
        await self._admin_pass(reply, now)
        stt_stats.prune(self.store.stats, now, self.tz,
                        {g for g, r in self.store.groups.items() if r.get("role") in ("a", "c")})
        self.store.save()
        return float(self.next_in)

    def _backoff(self) -> float:
        self.failures += 1
        return float(min(MAX_NEXT_IN, 60 * 2 ** min(self.failures - 1, 4)))

    def _states(self, now: float) -> list[dict]:
        status = self.tracker.status(now)
        out = []
        for g, rec in sorted(self.store.groups.items()):
            if rec["status"] != "member" or not rec.get("key"):
                continue
            share = st.Share(**rec["share"])
            content = st.content(status, share, n=self.counter.next(), t=now, freq=self.freq, mode=self.mode)
            out.append({"g": g, "kv": rec["kv"],
                        "blob": st.seal_state(self.identity, g, b64d(rec["key"]), rec["kv"], content)})
        return out

    async def _sync(self, now: float) -> dict | None:
        known = {}
        for g, rec in self.store.groups.items():
            roster = self._roster(rec)
            if roster is not None:
                known[g] = roster.version
        code, reply = await self.relay.post("sync", {"states": self._states(now), "known": known, "since": self.since})
        if code != 200:
            reason = reply.get("error")
            retry = reply.get("retry_in")
            if reason == "unknown_station":
                self.store.data["registered"] = False
            self.problem = {"clock": "clock", "pause": "relay_paused", "rate": "relay_busy"}.get(
                reason, f"relay_error_{reason or code}")
            log.warning("requête périodique refusée : %s %s", code, reply.get("message", ""))
            if isinstance(retry, int) and not isinstance(retry, bool):
                self._retry_in = max(MIN_NEXT_IN, min(MAX_NEXT_IN, retry))
            return None
        nxt = reply.get("next_in")
        if isinstance(nxt, int) and not isinstance(nxt, bool):
            self.next_in = max(MIN_NEXT_IN, min(MAX_NEXT_IN, nxt))
        when = reply.get("now")
        if isinstance(when, int) and not isinstance(when, bool):
            self.since = when
        seen = set()
        for entry in reply.get("groups") or []:
            g = entry.get("g") if isinstance(entry, dict) else None
            rec = self.store.groups.get(g) if isinstance(g, str) else None
            if rec is None:
                continue
            seen.add(g)
            try:
                self._apply(g, rec, entry, now)
            except (Malformed, KeyError, TypeError, ValueError) as exc:     # réponse du relais incohérente : ignorée
                log.warning("groupe %s : réponse du relais ignorée (%s)", g, exc)
        for g, rec in self.store.groups.items():
            if g not in seen and rec["status"] == "member":
                rec["status"] = "removed"
                log.info("groupe %s : la station n'en fait plus partie (exclue ou groupe supprimé)", g)
        return reply

    def _apply(self, g: str, rec: dict, entry: dict, now: float) -> None:
        current = self._roster(rec)
        envs = entry.get("rosters") or []
        if envs:
            by_version = {}
            for env in envs:
                try:
                    by_version[ro.parse_unchecked(env).version] = env
                except ro.RosterRefused:
                    pass
            new, refused = ro.follow(current, envs, group=g, invite_admin=rec.get("invite_admin"),
                                     admin_last_seen=rec.get("admin_last_seen", now), now=now)
            for reason in refused:
                log.warning("groupe %s : version de la liste refusée (%s)", g, reason)
            if new is not None and (current is None or new.version != current.version):
                rec["roster"] = by_version[new.version]
                current = new
        roster = current
        if roster is None:
            return                                      # adhésion pas encore validée
        me = roster.member(self.me)
        if me is None:
            if rec["status"] == "member":
                rec["status"] = "removed"
            return
        rec["role"] = me.role
        box = entry.get("key")
        if box:
            try:
                key = invite.open_key_box(box, self.identity, roster)
                if box["kv"] != rec["kv"]:
                    rec["old_keys"][str(rec["kv"])] = rec["key"]
                    rec["old_keys"] = dict(sorted(rec["old_keys"].items(), key=lambda kv: int(kv[0]))[-OLD_KEYS_KEPT:])
                rec["key"], rec["kv"] = b64e(key), box["kv"]
            except invite.InviteRefused as exc:
                log.warning("groupe %s : clé remise refusée (%s)", g, exc.reason)
        if rec["status"] != "member" and rec["kv"] == roster.kv:
            rec["status"] = "member"
            log.info("groupe %s : adhésion validée", g)
        if me.role == "a":
            rec["admin_last_seen"] = int(now)
        cache = rec["members"]
        for m in entry.get("members") or []:
            mid = m.get("id")
            rm = roster.member(mid) if station_id_ok(mid) else None
            if rm is None:
                continue
            c = cache.setdefault(mid, {})
            age = m.get("age") if isinstance(m.get("age"), int) else OFFLINE_AFTER_S + 1
            pseudo = m.get("pseudo")
            c["pseudo"] = pseudo if clean_pseudo(pseudo) == pseudo else "?"
            c["age"], c["seen_at"] = age, int(now)
            if rm.role == "a" and age <= OFFLINE_AFTER_S:
                rec["admin_last_seen"] = max(rec.get("admin_last_seen", 0), int(now - age))
            if "blob" in m:
                self._read_state(g, rec, c, m, rm, now)
            if me.role in ("a", "c"):
                code = display_code(c.get("state", {}).get("st"), age)
                stt_stats.record(self.store.stats, g, mid, code, now - c.get("stat_at", now), now, self.tz)
                c["stat_at"] = int(now)
        for mid in [i for i in cache if roster.member(i) is None]:
            del cache[mid]

    def _read_state(self, g: str, rec: dict, c: dict, m: dict, rm: ro.Member, now: float) -> None:
        kv = m.get("kv")
        key = rec["key"] if kv == rec["kv"] else rec["old_keys"].get(str(kv))
        if key is None or not isinstance(kv, int):
            c["refused"] = c.get("refused", 0) + 1
            return
        try:
            state = st.open_state(m["blob"], group=g, station=rm.id, ed_pub=rm.ed, key=b64d(key), key_version=kv,
                                  last_n=c.get("n", 0), now=now)
        except st.StateRefused as exc:
            if exc.reason != "replay":
                c["refused"] = c.get("refused", 0) + 1
                log.info("groupe %s : état de %s refusé (%s)", g, rm.id, exc.reason)
            return
        c["state"], c["n"], c["state_at"] = state, state["n"], int(now)

    # ------------------------------------------------------------------ administration
    async def _admin_pass(self, reply: dict, now: float) -> None:
        for entry in reply.get("groups") or []:
            g = entry.get("g") if isinstance(entry, dict) else None
            rec = self.store.groups.get(g) if isinstance(g, str) else None
            roster = self._roster(rec) if rec else None
            me = roster.member(self.me) if roster else None
            if me is None or me.role not in ("a", "c") or rec["status"] != "member":
                continue
            accept, reject, used = [], [], []
            for req in entry.get("pending") or []:
                rid = req.get("id") if isinstance(req, dict) else None
                try:
                    token = b64e(b64d(req.get("i"), invite.TOKEN_SIZE))
                    issued = rec["tokens"].get(token)
                    if issued is None:
                        raise invite.InviteRefused("token_unknown")
                    joiner = invite.check_join(req, group=g, key=b64d(issued["key"]),
                                               tokens={b64d(token): issued["exp"]},
                                               used={b64d(t) for t in rec["used"]}, now=now)
                except (invite.InviteRefused, Malformed, AttributeError) as exc:
                    reason = getattr(exc, "reason", "malformed")
                    if reason == "token_unknown" and me.role == "c":
                        continue                       # jeton d'un autre administrateur : c'est à lui de juger
                    if station_id_ok(rid):
                        reject.append(rid)
                    log.info("groupe %s : demande d'adhésion de %s refusée (%s)", g, rid, reason)
                    continue
                if roster.member(joiner.id) is None and all(a.id != joiner.id for a in accept):
                    accept.append(ro.new_member(joiner.ed, joiner.x, "m", int(now)))
                    used.append(token)
            remove = {i for i in entry.get("left") or []
                      if station_id_ok(i) and i != self.me and roster.member(i) is not None
                      and (me.role == "a" or roster.member(i).role != "a")}
            if reject and not (accept or remove):
                try:
                    await self._post_ok("group/reject", {"g": g, "ids": reject})
                except ActionRefused as exc:
                    log.warning("groupe %s : refus non transmis (%s)", g, exc.reason)
            if accept or remove:
                try:
                    await self._publish(g, rec, roster, remove=remove, add=accept, reject=reject)
                    rec["used"] = (rec["used"] + used)[-200:]
                    for t in used:
                        rec["tokens"].pop(t, None)
                except ActionRefused as exc:
                    log.warning("groupe %s : nouvelle liste refusée par le relais (%s), réessai au prochain cycle",
                                g, exc.reason)

    async def _publish(self, g: str, rec: dict, roster: ro.Roster, *, remove: set[str], add: list[ro.Member],
                       reject: list[str], members: list[ro.Member] | None = None) -> None:
        now = int(self.clock())
        kept = members if members is not None else [m for m in roster.members if m.id not in remove]
        rotate = bool(remove)
        kv = roster.kv + 1 if rotate else roster.kv
        key = crypto.random_key() if rotate else b64d(rec["key"])
        new = roster.next(t=now, members=[*kept, *add], kv=kv)
        env = ro.sign(new, self.identity)
        targets = [m for m in new.members if m.id != self.me] if rotate else add
        boxes = [invite.key_box(self.identity, new, m.id, key) for m in targets]
        await self._post_ok("group/roster", {"g": g, "roster": env, "keys": boxes, "reject": reject})
        if rotate:
            rec["old_keys"][str(rec["kv"])] = rec["key"]
            rec["old_keys"] = dict(sorted(rec["old_keys"].items(), key=lambda kv_: int(kv_[0]))[-OLD_KEYS_KEPT:])
            rec["key"], rec["kv"] = b64e(key), kv
        rec["roster"] = env
        self.store.save()
        log.info("groupe %s : liste v%d publiée (+%d, -%d%s)", g, new.version, len(add), len(remove),
                 ", nouvelle clé" if rotate else "")

    # ------------------------------------------------------------------ vues
    def view(self) -> dict:
        """Vue des groupes pour les clients et la console (états déjà déchiffrés, jamais de clé)."""
        now = self.clock()
        groups = []
        for g, rec in sorted(self.store.groups.items(), key=lambda kv: kv[1]["name"].casefold()):
            members = []
            for mid, c in rec["members"].items():
                state = c.get("state") or {}
                age = c.get("age", OFFLINE_AFTER_S + 1) + max(0, now - c.get("seen_at", now))
                code = display_code(state.get("st"), age)
                item = {"id": mid, "pseudo": c.get("pseudo", "?"), "code": code, "age": int(age)}
                if code != "O":
                    for key in ("sd", "lt", "su", "lv", "f", "m", "x"):
                        if key in state:
                            item[key] = state[key]
                    item["updated"] = int(now - c.get("state_at", now))
                members.append(item)
            members.sort(key=lambda m: sort_key(m["code"], m["pseudo"]))
            groups.append({"g": g, "name": rec["name"], "role": rec["role"], "status": rec["status"],
                           "share": dict(rec["share"]), "members": members})
        return {"station": self.me, "pseudo": self.pseudo, "registered": bool(self.store.data.get("registered")),
                "problem": self.problem, "last_sync": int(self.last_sync) if self.last_sync else None,
                "texts": list(self.store.data.get("texts") or []), "groups": groups}

    def admin_stats(self, g: str) -> dict:
        rec = self._group(g)
        if rec.get("role") not in ("a", "c"):
            raise ActionRefused("not_admin", "réservé aux administrateurs du groupe")
        return stt_stats.summary(self.store.stats, g, self.clock(), self.tz)

    def status_summary(self) -> dict:
        """Pour TRX Console et trx-monitor : jamais de clé, ni de fréquence d'un ami."""
        return {"station": self.me, "pseudo": self.pseudo, "registered": bool(self.store.data.get("registered")),
                "problem": self.problem, "last_sync": int(self.last_sync) if self.last_sync else None,
                "next_in": self.next_in,
                "groups": [{"g": g, "name": r["name"], "role": r["role"], "status": r["status"],
                            "members": len(r["members"])} for g, r in sorted(self.store.groups.items())]}
