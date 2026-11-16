# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Moteur du monitoring inter-stations, mode R (cahier § 17, docs/protocole-monlink.md).

Une même station peut AIDER (rôle « receiver » : elle invite, relève, garde, demande) et ÊTRE AIDÉE (rôle « emitter » :
elle rejoint avec un code, choisit son profil, envoie ; elle seule accepte une demande). Rien ne part avant que son
opérateur ait confirmé l'empreinte ET choisi un profil ; tout passe par `redact.Redactor` avant chiffrement.

Aucune commande vers la station aidée n'existe : une « demande » (`rq`) n'est qu'une question posée à son opérateur.
Le moteur ne touche jamais au poste (il lit des fichiers d'état) ; il ne lève jamais d'exception vers la boucle du
module pour une panne du relais (RelayUnavailable -> problème « relay », nouvel essai au cycle suivant).
"""
from __future__ import annotations

import asyncio
import collections
import getpass
import hashlib
import logging
import os
import re
import socket
import time
from pathlib import Path

from ..errors import codes
from ..errors.emit import emit_event
from ..logsetup import ASSIST_FLAG
from ..presence import pow as pw
from ..presence.codec import b64d, b64e
from ..presence.wire import clean_pseudo
from . import collect, envelope as env, invite as inv, pairing, profiles as pr, snapshot
from .redact import Redactor
from .relay import RelayRefused, RelayUnavailable

log = logging.getLogger("trx.monlink")

CYCLE_S = 60.0
FAST_CYCLE_S = 15.0                    # assistance en cours ou empreinte à confirmer
CHECK_LINK_S = 600.0                   # la station qui aide vérifie que la liaison existe encore (fin par l'autre)
REQUEST_TTL_S = 24 * 3600
EVENTS_PER_MESSAGE = 50
PENDING_EVENTS_MAX = 500
ROLES = ("receiver", "emitter")
SILENCE_MIN_S = 600                    # station suivie muette : alerte après 3 rythmes, et jamais avant 10 min
ALERT_REPEAT_S = 30 * 60               # même alerte, même station : une fois par demi-heure au plus (cahier § 9)
ALERTS_PER_HOUR = 20                   # plafond global des alertes du monitoring
REPORTS_KEPT = 5                       # rapports reçus gardés par liaison


class ActionRefused(Exception):
    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


def _label(link: dict, peer: str) -> str:
    """Nom d'un partenaire dans les journaux et alertes : pseudo et début d'identifiant (jamais d'adresse)."""
    return f"{link.get('pseudo') or '?'} ({peer[:8]})"


class Engine:
    def __init__(self, store, identity, relay, *, status_path: str | Path, state_dir: str | Path,
                 clock=time.time, monitor=None, known_words: dict[str, str] | None = None, notifier=None,
                 make_report=None) -> None:
        self.store, self.identity, self.relay = store, identity, relay
        self.me = identity.station_id
        self.status_path, self.state_dir = Path(status_path), Path(state_dir)
        self.clock = clock
        self.monitor = monitor
        self.notifier = notifier                  # supervisor.notify.Notifier (ntfy de la station) ; None = journal seul
        self.make_report = make_report            # () -> octets du zip du menu 2.3 ; None = pas de rapport
        self.started = clock()
        self.problem = ""
        self.journal = collect.JournalTail(self.state_dir, store.data.get("journal"))
        self._keys: dict[str, bytes] = {}
        self._known = known_words if known_words is not None else default_known_words()
        self._quota_day: dict[str, int] = {}
        self._snaps: dict[tuple[str, str], env.Reassembler] = {}
        self._alerted: dict[str, float] = {}
        self._alert_times: collections.deque[float] = collections.deque()

    # ------------------------------------------------------------ lignes INFO pendant l'assistance
    def _assist_flag(self, now: float) -> None:
        """Échéance de la plus longue assistance accordée par l'opérateur de CETTE station (station aidée), lue par le
        filtre des journaux JSON de la passerelle et du superviseur (`logsetup.ASSIST_FLAG`) : ils gardent alors aussi
        les lignes INFO, envoyées à la station qui aide. Plus d'assistance = fichier effacé (filtre ordinaire)."""
        flag = self.state_dir / ASSIST_FLAG
        until = max((float(l.get("assist_until") or 0) for l in self.store.links.values()
                     if l["role"] == "emitter" and l["state"] == "active"), default=0.0)
        try:
            if until > now:
                text = f"{until:.0f}\n"
                if not flag.exists() or flag.read_text(encoding="ascii") != text:
                    flag.parent.mkdir(parents=True, exist_ok=True)
                    flag.write_text(text, encoding="ascii")
                    os.chmod(flag, 0o644)            # lu par le superviseur et la passerelle
            elif flag.exists():
                flag.unlink()
        except OSError as exc:
            log.info("échéance d'assistance non écrite (%s) : journaux sans lignes INFO", exc)

    # ------------------------------------------------------------ alertes (station qui aide)
    def _alert(self, code: str, key: str, **contexte) -> None:
        """Alerte du catalogue par le ntfy de la station ; une fois par demi-heure par (code, station), 20 par heure."""
        now = self.clock()
        if now - self._alerted.get(f"{code}:{key}", -1e12) < ALERT_REPEAT_S:
            return
        while self._alert_times and now - self._alert_times[0] > 3600:
            self._alert_times.popleft()
        if len(self._alert_times) >= ALERTS_PER_HOUR:
            log.info("plafond des alertes du monitoring atteint : %s non envoyée", code)
            return
        self._alerted[f"{code}:{key}"] = now
        self._alert_times.append(now)
        if self.notifier is not None:
            self.notifier.alert(code, key=key, **contexte)
        else:
            emit_event(code, logger=log, **contexte)

    # ------------------------------------------------------------ outils
    def _link(self, peer: object, role: str | None = None, *, active: bool = False) -> dict:
        link = self.store.links.get(peer) if isinstance(peer, str) else None
        if link is None:
            raise ActionRefused("unknown_link", "liaison inconnue")
        if role is not None and link["role"] != role:
            raise ActionRefused("role", "action impossible dans ce rôle")
        if active and link["state"] not in ("active", "paused"):
            raise ActionRefused("not_confirmed", "empreinte pas encore confirmée")
        return link

    def _key(self, peer: str) -> bytes:
        if peer not in self._keys:
            self._keys[peer] = pairing.link_key(self.identity, peer, b64d(self.store.links[peer]["x"], 32))
        return self._keys[peer]

    def _redactor(self, peer: str) -> Redactor:
        salt = hashlib.sha256(self._key(peer) + b"orx-monlink redact v1").digest()[:16]
        return Redactor(salt, known=self._known)

    def _drop(self, peer: str, *, by: str, purge: bool = False) -> None:
        link = self.store.links.pop(peer, None)
        self._keys.pop(peer, None)
        if link is not None:
            emit_event(codes.ORT_7002, logger=log, station=_label(link, peer), par=by)
        if purge:
            self.store.purge(self.clock(), peer)
        self.store.save()
        self._assist_flag(self.clock())          # fin de liaison = fin des lignes INFO tout de suite

    async def _send(self, peer: str, kind: str, content: dict, *, assist: bool = False) -> None:
        """Un message chiffré vers le partenaire ; la séquence avance AVANT l'envoi (jamais deux contenus sous le même
        numéro). Liaison disparue chez le relais = fin de liaison décidée par l'autre côté."""
        link = self.store.links[peer]
        link["seq_out"] = int(link.get("seq_out", 0)) + 1
        self.store.save()
        msg = env.seal_message(self._key(peer), self.me, peer, kind, link["seq_out"], content)
        try:
            await self.relay.call("put", {"msg": msg, **({"assist": True} if assist else {})})
        except RelayRefused as exc:
            if exc.reason in ("not_linked",):
                self._drop(peer, by="partenaire")
            raise

    # ------------------------------------------------------------ enregistrement
    async def ensure_registered(self) -> None:
        if self.store.data["registered"]:
            return
        fields = {"ed": b64e(self.identity.ed_pub), "x": b64e(self.identity.x_pub)}
        try:
            await self.relay.call("register", fields)
        except RelayRefused as exc:
            if exc.reason == "exists":
                pass
            elif exc.reason == "pow":
                bits = int(exc.reply.get("bits", 20))
                nonce = await asyncio.to_thread(pw.pow_solve, self.me, bits)
                try:
                    await self.relay.call("register", fields | {"pow": nonce})
                except RelayRefused as again:
                    if again.reason != "exists":
                        raise
            else:
                raise
        self.store.data["registered"] = True
        self.store.save()
        log.info("station enregistrée auprès du relais du monitoring (%s)", self.me)

    # ------------------------------------------------------------ actions de l'opérateur (TRX Console)
    def set_pseudo(self, pseudo: object) -> dict:
        pseudo = clean_pseudo(pseudo)
        if pseudo is None:
            raise ActionRefused("pseudo", "pseudo refusé : 1 à 16 lettres sans accent, chiffres, espace . / _ -")
        self.store.data["pseudo"] = pseudo
        self.store.save()
        return {"pseudo": pseudo}

    def _pseudo(self) -> str:
        if not self.store.data["pseudo"]:
            raise ActionRefused("no_pseudo", "choisir d'abord un pseudo")
        return self.store.data["pseudo"]

    async def invite(self) -> dict:
        """Station qui AIDE : un code de 10 caractères, valable 15 min, à dicter à l'opérateur aidé."""
        pseudo = self._pseudo()
        await self.ensure_registered()
        code = inv.new_code()
        keys = await asyncio.to_thread(inv.derive, code)
        deposit = inv.seal_invitation(self.identity, pseudo, keys, now=self.clock())
        await self.relay.call("invite/put", deposit)
        self.store.data["invites"][keys.address] = {"key": keys.key.hex(), "e": deposit["e"]}
        self.store.save()
        return {"code": inv.display_code(code), "expires": deposit["e"]}

    async def join(self, code: object) -> dict:
        """Station AIDÉE : code tapé -> demande d'appairage ; l'empreinte s'affiche, rien ne part encore."""
        pseudo = self._pseudo()
        try:
            keys = await asyncio.to_thread(inv.derive, inv.normalize_code(code))
        except inv.InviteRefused as exc:
            raise ActionRefused("code", "code mal formé (10 caractères)") from exc
        await self.ensure_registered()
        try:
            got = await self.relay.call("invite/take", {"a": keys.address})
        except RelayRefused as exc:
            if exc.reason == "unknown_invite":
                raise ActionRefused("unknown_invite", "code inconnu, déjà utilisé ou expiré") from exc
            raise
        try:
            inviter = inv.open_invitation(keys, got.get("box"), now=self.clock())
        except inv.InviteRefused as exc:
            raise ActionRefused("invite_" + exc.reason, "invitation illisible") from exc
        if inviter.id == self.me:
            raise ActionRefused("self", "sa propre invitation")
        req = pairing.pair_request(inviter, keys, self.identity, pseudo, now=self.clock())
        await self.relay.call("pair", {"req": req})
        fp = pairing.fingerprint(self.identity.ed_pub, inviter.ed)
        self.store.links[inviter.id] = self._new_link("emitter", inviter.ed, inviter.x, inviter.pseudo, fp)
        self.store.save()
        return {"peer": inviter.id, "pseudo": inviter.pseudo, "fingerprint": fp}

    def _new_link(self, role: str, ed: bytes, x: bytes, pseudo: str, fp: str) -> dict:
        return {"role": role, "ed": b64e(ed), "x": b64e(x), "pseudo": pseudo, "state": "confirm", "fingerprint": fp,
                "created": int(self.clock()), "seq_out": 0, "window": {}, "profile": None, "last_rx": None}

    async def confirm(self, peer: object, profile: object = None) -> dict:
        """Empreinte confirmée de vive voix. Station aidée : profil OBLIGATOIRE (rien ne part sans lui)."""
        link = self._link(peer)
        if link["state"] != "confirm":
            raise ActionRefused("already", "liaison déjà confirmée")
        if link["role"] == "emitter":
            chosen = self._profile(profile)
            await self.relay.call("allow", {"peer": peer})
            link.update(state="active", profile=chosen.to_dict())
            self.store.save()
            await self._send_cf(peer)
        else:
            await self.relay.call("allow", {"peer": peer})
            link.update(state="active", checked=int(self.clock()))
            self.store.save()
        emit_event(codes.ORT_7001, logger=log, station=_label(link, peer))
        return {"peer": peer, "state": "active"}

    @staticmethod
    def _profile(profile: object) -> pr.Profile:
        if isinstance(profile, str) and profile in pr.PRESETS:
            return pr.PRESETS[profile]
        try:
            return pr.Profile.from_dict(profile)
        except pr.ProfileRefused as exc:
            raise ActionRefused("profile", str(exc)) from exc

    async def set_profile(self, peer: object, profile: object) -> dict:
        link = self._link(peer, "emitter", active=True)
        chosen = self._profile(profile)
        link["profile"] = chosen.to_dict()
        self.store.save()
        await self._send_cf(peer)
        return {"profile": chosen.to_dict()}

    async def pause(self, peer: object, paused: bool) -> dict:
        """Station aidée : envoi suspendu, battement compris ; l'autre côté voit « en pause » (pas d'alerte d'absence)."""
        link = self._link(peer, "emitter", active=True)
        link["state"] = "paused" if paused else "active"
        self.store.save()
        await self._send_cf(peer)
        return {"state": link["state"]}

    async def _send_cf(self, peer: str) -> bool:
        """Profil et pause annoncés à la station qui aide. Si elle n'a pas encore confirmé l'empreinte de son côté
        (le relais répond `not_allowed` : ordre ordinaire au téléphone), l'annonce attend et part au cycle suivant ;
        rien d'autre ne part avant elle."""
        link = self.store.links[peer]
        link["cf_pending"] = True
        self.store.save()
        try:
            await self._send(peer, "cf", {"profile": link["profile"], "paused": link["state"] == "paused"})
        except RelayRefused as exc:
            if exc.reason == "not_allowed":
                return False
            raise
        link["cf_pending"] = False
        self.store.save()
        return True

    async def end(self, peer: object, *, purge: bool = False) -> dict:
        """Fin de liaison immédiate, sans l'accord de l'autre (cahier § 11) ; l'autre côté la constate au relais."""
        self._link(peer)
        try:
            await self.relay.call("revoke", {"peer": peer})
        except RelayRefused:
            pass                                   # déjà finie chez le relais : on finit ici aussi
        self._drop(peer, by="cette station", purge=purge)
        return {"ended": peer}

    async def request_assist(self, peer: object, duration_s: object = pr.ASSIST_DEFAULT_S) -> dict:
        """Station qui AIDE : demande le mode assistance ; l'opérateur aidé accepte ou refuse (3 demandes par jour)."""
        link = self._link(peer, "receiver", active=True)
        try:
            pr.assist_until(0, duration_s if isinstance(duration_s, int) else -1)   # bornes : 15 min à 24 h
        except pr.ProfileRefused as exc:
            raise ActionRefused("duration", str(exc)) from exc
        await self._request(link, peer, {"assist": duration_s})
        return {"requested": duration_s}

    async def request_report(self, peer: object) -> dict:
        """Station qui AIDE : demande le rapport de dépannage (menu 2.3, masqué) ; l'opérateur aidé accepte ou refuse."""
        link = self._link(peer, "receiver", active=True)
        await self._request(link, peer, {"snapshot": True})
        return {"requested": "snapshot"}

    async def _request(self, link: dict, peer: str, content: dict) -> None:
        now = self.clock()
        recent = [t for t in link.get("requests", []) if now - t < 86400]
        if len(recent) >= pr.ASSIST_REQUESTS_PER_DAY:
            raise ActionRefused("too_many", "3 demandes par jour au plus")
        await self._send(peer, "rq", content)
        link["requests"] = recent + [int(now)]
        self.store.save()

    async def answer(self, peer: object, accept: bool) -> dict:
        """Station AIDÉE : réponse de SON opérateur à la demande en attente (assistance ou rapport)."""
        link = self._link(peer, "emitter", active=True)
        request = link.get("request")
        if not request:
            raise ActionRefused("no_request", "aucune demande en attente")
        link["request"] = None
        if request.get("snapshot"):
            reply = {"accepted": bool(accept), "snapshot": True}
            if accept:
                link["report_due"] = True                 # fabriqué et envoyé au cycle (peut prendre du temps)
        elif accept:
            until = pr.assist_until(self.clock(), int(request["assist"]))
            link["assist_until"] = until
            reply = {"accepted": True, "until": int(until)}
        else:
            reply = {"accepted": False}
        self.store.save()
        self._assist_flag(self.clock())
        await self._send(peer, "an", reply)
        return reply

    def send_report(self, peer: object) -> dict:
        """Station AIDÉE : envoyer son rapport de dépannage sans attendre de demande (au prochain cycle)."""
        link = self._link(peer, "emitter", active=True)
        if self.make_report is None:
            raise ActionRefused("no_report", "rapport indisponible sur cette station")
        link["report_due"] = True
        self.store.save()
        return {"queued": True}

    def received(self, peer: object, limit: int = 50) -> list[dict]:
        self._link(peer, "receiver")
        return self.store.recent(peer, ("ev",), limit)

    def last_report(self, peer: object) -> dict:
        """Station qui AIDE : chemin du dernier rapport reçu (la console le copie elle-même sur SON Bureau)."""
        link = self._link(peer, "receiver")
        reports = [r for r in link.get("reports", []) if Path(r).is_file()]
        if not reports:
            raise ActionRefused("no_report", "aucun rapport reçu de cette station")
        return {"path": reports[-1]}

    # ------------------------------------------------------------ cycle
    async def cycle(self) -> float:
        now = self.clock()
        try:
            await self.ensure_registered()
            await self._inbox(now)
            await self._emit(now)
            await self._check_links(now)
            self._check_silence(now)
            if self.problem:
                log.info("relais du monitoring de nouveau joignable")
            self.problem = ""
        except RelayUnavailable as exc:
            if self.problem != "relay":
                emit_event(codes.ORT_7040, logger=log, relais="relais du monitoring", detail=str(exc)[:200])
            self.problem = "relay"
        except RelayRefused as exc:
            if self.problem != exc.reason:
                emit_event(codes.ORT_7040, logger=log, relais="relais du monitoring", detail=str(exc)[:200])
            self.problem = exc.reason
        for address, item in list(self.store.data["invites"].items()):
            if item["e"] <= now:
                del self.store.data["invites"][address]
        self.store.data["journal"] = self.journal.positions
        self.store.save()
        self._assist_flag(now)
        fast = any(l["state"] == "confirm" or (l.get("assist_until") or 0) > now or l.get("request")
                   for l in self.store.links.values())
        return FAST_CYCLE_S if fast else CYCLE_S

    async def _inbox(self, now: float) -> None:
        after = int(self.store.data.get("inbox_after", 0))
        while True:
            reply = await self.relay.call("get", {"after": after})
            msgs = reply.get("msgs") or []
            for m in msgs:
                self._receive(m, now)
            if msgs:
                after = int(msgs[-1]["id"])
                self.store.data["inbox_after"] = after
                self.store.save()
                await self.relay.call("ack", {"upto": after})
            if not reply.get("more"):
                return

    def _receive(self, m: dict, now: float) -> None:
        frm = m.get("from")
        if m.get("k") == "pair":
            pending = {a: pairing.PendingInvite(inv.CodeKeys(a, bytes.fromhex(i["key"])), i["e"])
                       for a, i in self.store.data["invites"].items()}
            try:
                peer = pairing.check_pair(m.get("msg"), self.identity, pending, now=now)
            except pairing.PairRefused as exc:
                emit_event(codes.ORT_7031, logger=log, station=str(frm)[:8], motif=exc.reason)
                return
            self.store.data["invites"].pop(m["msg"]["a"], None)                    # usage unique
            fp = pairing.fingerprint(self.identity.ed_pub, peer.ed)
            self.store.links[peer.id] = self._new_link("receiver", peer.ed, peer.x, peer.pseudo, fp)
            self.store.save()
            return
        link = self.store.links.get(frm)
        if link is None:
            log.info("message d'une station sans liaison ignoré (%s)", str(frm)[:8])
            return
        window = env.ReplayWindow.from_dict(link.get("window"))
        try:
            kind, seq, content = env.open_message(self._key(frm), m.get("msg"), me=self.me, peer=frm,
                                                  peer_is_emitter=link["role"] == "receiver")
            window.accept(seq)
        except env.MessageRefused as exc:
            emit_event(codes.ORT_7031, logger=log, station=_label(link, frm), motif=exc.reason)
            return
        link["window"] = window.to_dict()
        if link["role"] == "receiver" and link.get("silent_since"):          # retour à la normale
            self._alert(codes.ORT_7051, frm, station=_label(link, frm),
                        minutes=int(now - link["silent_since"]) // 60)
            link["silent_since"] = None
        link["last_rx"] = int(now)
        if kind == "end":
            self._drop(frm, by="partenaire")
            return
        if link["role"] == "receiver":
            self._receive_as_helper(frm, link, kind, content, now)
        elif kind == "rq":
            duration = content.get("assist")
            if content.get("snapshot") is True:
                link["request"] = {"snapshot": True, "at": int(now)}
            elif isinstance(duration, int) and not isinstance(duration, bool) \
                    and pr.ASSIST_MIN_S <= duration <= pr.ASSIST_MAX_S:
                link["request"] = {"assist": duration, "at": int(now)}
        self.store.save()

    def _receive_as_helper(self, peer: str, link: dict, kind: str, content: dict, now: float) -> None:
        if kind == "sn":
            self._receive_report(peer, link, content, now)
        elif kind == "lg":
            lines = content.get("lines") if isinstance(content.get("lines"), list) else []
            for line in lines[:EVENTS_PER_MESSAGE]:
                if isinstance(line, dict):
                    self.store.keep(peer, "lg", line, now)
        elif kind == "cf":
            link["profile"] = content.get("profile")
            link["paused"] = bool(content.get("paused"))
        elif kind in ("hb", "st"):
            link["last_" + kind] = content
            self.store.keep(peer, kind, content, now)
        elif kind == "ev":
            events = content.get("events") if isinstance(content.get("events"), list) else []
            for event in events[:EVENTS_PER_MESSAGE]:
                if isinstance(event, dict):
                    self.store.keep(peer, "ev", event, now)
                    if event.get("gravite") == "critique" and isinstance(event.get("code"), str):
                        self._alert(codes.ORT_7052, f"{peer}:{event['code']}", station=_label(link, peer),
                                    code_recu=event["code"][:16], titre=str(event.get("titre") or "")[:120])
            link["events"] = int(link.get("events", 0)) + len(events)
        elif kind == "an":
            link["answer"] = {**content, "at": int(now)}

    def _receive_report(self, peer: str, link: dict, frag: dict, now: float) -> None:
        """Fragments du rapport de dépannage ; complet = vérifié puis rangé (5 derniers gardés par liaison)."""
        key = (peer, str(frag.get("id", ""))[:32])
        rebuilt = self._snaps.setdefault(key, env.Reassembler())
        try:
            data = rebuilt.add(frag)
            if data is None:
                return
            snapshot.check_received(data)
        except (env.MessageRefused, ValueError) as exc:
            self._snaps.pop(key, None)
            emit_event(codes.ORT_7031, logger=log, station=_label(link, peer), motif=f"rapport : {exc}")
            return
        except Exception as exc:                  # zip illisible
            self._snaps.pop(key, None)
            emit_event(codes.ORT_7031, logger=log, station=_label(link, peer), motif=f"rapport : {type(exc).__name__}")
            return
        self._snaps.pop(key, None)
        folder = self.store.folder / "rapports"
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", link.get("pseudo") or peer[:8]).strip("-") or "station"
        path = folder / f"rapport-{name}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}.zip"
        path.write_bytes(data)
        try:
            os.chmod(path, 0o644)                 # lisible par le compte de la console (Bureau de l'opérateur)
        except OSError:
            pass
        reports = link.get("reports", []) + [str(path)]
        for old in reports[:-REPORTS_KEPT]:
            try:
                Path(old).unlink()
            except OSError:
                pass
        link["reports"] = reports[-REPORTS_KEPT:]
        emit_event(codes.ORT_7053, logger=log, station=_label(link, peer), taille_ko=len(data) // 1024)

    async def _send_report(self, peer: str, link: dict) -> None:
        """Station AIDÉE : rapport du menu 2.3 fabriqué ici, entièrement masqué, envoyé en fragments."""
        link["report_due"] = False
        self.store.save()
        try:
            raw = await asyncio.to_thread(self.make_report)
            data = await asyncio.to_thread(snapshot.redact_zip, raw, self._redactor(peer))
        except Exception as exc:
            emit_event(codes.ORT_7054, logger=log, station=_label(link, peer), detail=f"{type(exc).__name__}: {exc}"[:200])
            return
        snap_id = os.urandom(8).hex()
        try:
            for frag in env.split_snapshot(data, snap_id):
                await self._send(peer, "sn", frag, assist=True)
        except RelayRefused as exc:
            emit_event(codes.ORT_7054, logger=log, station=_label(link, peer), detail=f"refus du relais : {exc.reason}")
            if exc.reason not in ("quota", "too_large"):
                raise
        log.info("rapport de dépannage envoyé à %s (%d ko)", _label(link, peer), len(data) // 1024)

    def _check_silence(self, now: float) -> None:
        """Station qui AIDE : alerte quand une station suivie (hors pause) ne donne plus de nouvelles."""
        for peer, link in self.store.links.items():
            if link["role"] != "receiver" or link["state"] != "active" or link.get("paused") or link.get("silent_since"):
                continue
            last = link.get("last_rx")
            if not last:
                continue
            period = int((link.get("profile") or {}).get("period_s") or 300)
            answer = link.get("answer") or {}
            if answer.get("accepted") and int(answer.get("until") or 0) > now:
                period = pr.ASSIST_PERIOD_S
            if now - last > max(3 * period, SILENCE_MIN_S):
                link["silent_since"] = last
                self._alert(codes.ORT_7050, peer, station=_label(link, peer), minutes=int(now - last) // 60)

    async def _emit(self, now: float) -> None:
        """Station AIDÉE : ce que le profil de chaque liaison permet, masqué, au rythme du profil."""
        fresh = self.journal.read()
        for peer, link in list(self.store.links.items()):
            if link["role"] != "emitter" or link["state"] not in ("active", "paused") or not link.get("profile"):
                continue
            if link.get("cf_pending"):
                try:
                    if not await self._send_cf(peer):
                        continue                 # la station qui aide n'a pas encore confirmé : rien d'autre ne part
                except RelayRefused as exc:
                    if exc.reason == "not_linked":
                        continue                 # liaison finie par l'autre côté (déjà retirée par _send)
                    raise
            if link["state"] != "active":
                continue
            if link.get("request") and now - link["request"]["at"] > REQUEST_TTL_S:
                link["request"] = None                                            # demande ignorée : expirée
            eff = pr.effective(pr.Profile.from_dict(link["profile"]), link.get("assist_until"), now)
            red = self._redactor(peer)
            pending = list(link.get("pending_ev", []))
            pending += [red.obj(e) for e in fresh if pr.severity_passes(str(e.get("gravite", "")), eff.events_min)]
            link["pending_ev"] = pending[-PENDING_EVENTS_MAX:]
            if eff.logs_every_s:                 # assistance : toutes les lignes des journaux JSON
                lines = list(link.get("pending_lg", [])) + [red.obj(l) for l in self.journal.lines]
                link["pending_lg"] = lines[-PENDING_EVENTS_MAX:]
            else:
                link["pending_lg"] = []
            try:
                if now - float(link.get("sent_hb", 0)) >= eff.period_s:
                    await self._send(peer, "hb", red.obj(collect.heartbeat(self.status_path, self.state_dir,
                                                                           started=self.started, clock=self.clock)),
                                     assist=eff.assistance)
                    state: dict = {}
                    if eff.system and self.monitor is not None:
                        state["system"] = collect.system_state(self.monitor)
                    rig = pr.filter_rig(collect.rig_state(self.status_path), eff)
                    if rig is not None:
                        state["rig"] = rig
                    if state:
                        await self._send(peer, "st", red.obj(state), assist=eff.assistance)
                    link["sent_hb"] = int(now)
                while link.get("pending_ev"):
                    batch = link["pending_ev"][:EVENTS_PER_MESSAGE]
                    await self._send(peer, "ev", {"events": batch}, assist=eff.assistance)
                    link["pending_ev"] = link["pending_ev"][len(batch):]
                if eff.logs_every_s and now - float(link.get("sent_lg", 0)) >= eff.logs_every_s:
                    while link.get("pending_lg"):
                        batch = link["pending_lg"][:EVENTS_PER_MESSAGE]
                        await self._send(peer, "lg", {"lines": batch}, assist=True)
                        link["pending_lg"] = link["pending_lg"][len(batch):]
                    link["sent_lg"] = int(now)
                if link.get("report_due") and self.make_report is not None:
                    await self._send_report(peer, link)
            except RelayRefused as exc:
                if exc.reason == "quota" and self._quota_day.get(peer) != int(now // 86400):
                    self._quota_day[peer] = int(now // 86400)
                    emit_event(codes.ORT_7020, logger=log, station=_label(link, peer),
                               taille_ko=len(str(link.get("pending_ev", ""))) // 1024)
                elif exc.reason not in ("quota", "not_linked", "not_allowed"):
                    raise

    async def _check_links(self, now: float) -> None:
        """Station qui AIDE : une liaison finie par la station aidée se voit au relais (`allow` -> not_linked)."""
        for peer, link in list(self.store.links.items()):
            if link["role"] != "receiver" or link["state"] != "active":
                continue
            if now - float(link.get("checked", 0)) < CHECK_LINK_S:
                continue
            try:
                await self.relay.call("allow", {"peer": peer})
                link["checked"] = int(now)
            except RelayRefused as exc:
                if exc.reason != "not_linked":
                    raise
                self._drop(peer, by="partenaire")

    # ------------------------------------------------------------ vue (TRX Console, trx-monitor)
    def view(self) -> dict:
        now = self.clock()
        links = []
        for peer, l in sorted(self.store.links.items(), key=lambda kv: (kv[1]["role"], kv[1].get("pseudo", ""))):
            item = {"peer": peer, "pseudo": l.get("pseudo", ""), "role": l["role"], "state": l["state"],
                    "last_rx_age": None if not l.get("last_rx") else int(now - l["last_rx"])}
            if l["state"] == "confirm":
                item["fingerprint"] = l["fingerprint"]
            if l["role"] == "emitter":
                item["profile"] = l.get("profile")
                item["request"] = l.get("request")
                until = l.get("assist_until") or 0
                item["assist_left_s"] = int(until - now) if until > now else 0
                item["report_due"] = bool(l.get("report_due"))
            else:
                item.update(paused=bool(l.get("paused")), profile=l.get("profile"), events=int(l.get("events", 0)),
                            last_hb=l.get("last_hb"), last_st=l.get("last_st"), answer=l.get("answer"),
                            reports=len(l.get("reports", [])), silent=bool(l.get("silent_since")))
            links.append(item)
        return {"id": self.me, "pseudo": self.store.data["pseudo"], "registered": self.store.data["registered"],
                "problem": self.problem, "invites": len(self.store.data["invites"]), "links": links}


def default_known_words() -> dict[str, str]:
    """Mots propres à cette machine, remplacés dans tout ce qui part : nom de machine et compte de l'utilisateur."""
    words: dict[str, str] = {}
    try:
        host = socket.gethostname()
        if host:
            words[host] = "<host>"
    except OSError:
        pass
    try:
        user = getpass.getuser()
        if user and user not in ("root", "trx"):
            words[user] = "<user>"
    except Exception:
        pass
    return words
