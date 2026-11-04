# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Liaison UDP de la station avec Breizh Audio Box (client du protocole v1, docs/breizh-cahier-des-charges.md § 5).

Ouvre la session (HELLO toutes les 2 s), la garde en vie (PING toutes les 1 s, perdue après 3 s sans réponse),
envoie les blocs de son et n'accepte que le retour d'un bloc RÉELLEMENT envoyé, une seule fois.
États (§ 5.6) : connecting, ready, fallback, refused. La route d'émission (gateway/audio/route.py) ajoute « active ».
Réactivation après un repli : `reactivate_after_s` de réponses sans faute, ou `reactivate()` demandé par l'opérateur.
Rien ici ne touche au PTT ni à la porte d'émission ; aucune erreur réseau ne remonte (la passerelle ne doit pas quitter).
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from collections import Counter
from collections.abc import Callable

from . import protocol as p

log = logging.getLogger(__name__)

HELLO_EVERY_S = 2.0
PING_EVERY_S = 1.0
IDLE_LOST_S = 3.0
REFUSED_RETRY_S = 60.0
SOCKET_RETRY_S = 5.0
BAD_REPORT_S = 60.0
TICK_S = 0.1
NOT_BAD = frozenset({"late", "icmp", "send_error", "ack_changed"})   # pas des paquets suspects : retards, réseau
MAX_OUTSTANDING = 400            # blocs envoyés en attente de retour (4 s de son) : au-delà, les plus anciens sont oubliés

REFUSALS = {"cat_on": "Breizh n'a pas coupé son CAT", "proto": "version de protocole de Breizh incompatible",
            "format": "format du son refusé", "latency": "traitement annoncé par Breizh trop long (> 50 ms)",
            "nonce": "réponse de Breizh mal formée", "json": "réponse de Breizh mal formée",
            "mode_off": "mode OpenRemoteTRX non activé dans Breizh", "busy": "Breizh sert déjà une autre station"}


class BreizhLink(asyncio.DatagramProtocol):
    def __init__(self, host: str, port: int, key: bytes, *, reactivate_after_s: int, station_version: str,
                 notify: Callable[[str, str], None], clock: Callable[[], float] = time.monotonic) -> None:
        self.host, self.port, self.key = host, port, key
        self.address = ipaddress.ip_address(host)
        self.reactivate_after_s, self.station_version = reactivate_after_s, station_version
        self.notify, self.clock = notify, clock
        self.on_return: Callable[[int, bytes | None], None] | None = None   # (bloc, son traité ; None = arrivé trop tard)
        self.transport: asyncio.DatagramTransport | None = None
        self.state = "connecting"
        self.peer_version = ""
        self.rtt_ms: int | None = None
        self.rejected: Counter[str] = Counter()
        self._reported_bad = 0
        self._next_bad_report = clock() + BAD_REPORT_S
        self._refused_code = ""
        self._refused_until = 0.0
        self._reactivate_requested = False
        self._stable_since: float | None = None
        self._new_attempt()

    # ---------------------------------------------------------------- session
    def _new_attempt(self) -> None:
        self.session = p.new_session()
        self.session_key: bytes | None = None
        self._nonce = p.new_nonce()
        self._ack_nonce = b""
        self.seq = 0
        self.guard = p.SeqGuard()
        self.outstanding: dict[int, float] = {}
        self.next_ref = 0
        self._pings: dict[int, float] = {}
        self._next_hello = 0.0
        self._next_ping = 0.0
        self._last_valid = self.clock()

    @property
    def ready(self) -> bool:
        return self.state == "ready" and self.session_key is not None

    def reactivate_in_s(self) -> int | None:
        if self.state != "fallback":
            return None
        if self._stable_since is None or self.reactivate_after_s <= 0:
            return None
        return max(0, round(self._stable_since + self.reactivate_after_s - self.clock()))

    def reactivate(self) -> bool:
        """Demande de l'opérateur. Vrai si elle attend que Breizh réponde, faux si Breizh est repris tout de suite."""
        if self.state == "ready":
            return False
        if self.state == "fallback" and self.session_key is not None:
            self.state = "ready"
            self.notify("reactivated", "Breizh repris à la demande de l'opérateur")
            return False
        self._reactivate_requested = True
        if self.state == "refused":
            self._refused_until = 0.0                   # nouvel essai tout de suite
        return True

    def _lose(self, event: str, detail: str) -> None:
        had_session = self.session_key is not None
        if self.state == "ready":
            self.state = "fallback"
        self._stable_since = None
        self._new_attempt()
        if had_session:
            self.notify(event, detail)

    def mark_lost(self, detail: str) -> None:
        """Route d'émission : plus aucun retour pendant `lost_ms`. Session abandonnée, repli jusqu'à la réactivation."""
        if self.state == "ready":
            self.state = "fallback"
        self._stable_since = None
        self._new_attempt()
        self.notify("fallback", detail)

    def _refuse(self, code: str) -> None:
        if self.state != "fallback":                    # en repli : reste en repli, nouvel essai dans 60 s
            self.state = "refused"
        self._refused_until = self.clock() + REFUSED_RETRY_S
        self._new_attempt()
        if code != self._refused_code:
            self._refused_code = code
            self.notify("refused", f"liaison refusée : {REFUSALS.get(code, code)} (nouvel essai dans 60 s)")

    # ---------------------------------------------------------------- envoi
    def _send(self, kind: p.Type, *, ref: int = 0, payload: bytes = b"", flags: int = 0) -> bool:
        if self.transport is None:
            return False
        key = self.key if kind in p.PAIRING_TYPES else self.session_key
        if key is None:
            return False
        self.seq += 1
        try:
            self.transport.sendto(p.encode(p.Packet(kind, self.session, self.seq, ref, payload, flags), key))
        except OSError as exc:                          # réseau tombé : la session se perdra d'elle-même
            self.rejected["send_error"] += 1
            log.debug("envoi vers Breizh impossible : %s", exc)
            return False
        return True

    def send_audio(self, block: bytes, flags: int = 0) -> int | None:
        """Numéro du bloc envoyé, ou None sans session (la route repasse alors en direct)."""
        if self.session_key is None or self.transport is None:
            return None
        ref = self.next_ref
        self.next_ref = (self.next_ref + 1) & p.U32
        if not self._send(p.Type.AUDIO, ref=ref, payload=block, flags=flags):
            return None
        self.outstanding[ref] = self.clock()
        if len(self.outstanding) > MAX_OUTSTANDING:
            self.outstanding.pop(next(iter(self.outstanding)))
        return ref

    def forget(self, ref: int) -> None:
        """Bloc parti sans traitement : son retour éventuel sera refusé (« late »)."""
        self.outstanding.pop(ref, None)

    def bye(self, reason: str = "shutdown") -> None:
        if self.session_key is not None:
            self._send(p.Type.BYE, payload=p.bye_payload(reason))

    # ---------------------------------------------------------------- réception
    def connection_made(self, transport) -> None:
        self.transport = transport

    def error_received(self, exc) -> None:              # ICMP « port fermé » (Breizh arrêté), réseau coupé...
        self.rejected["icmp"] += 1

    def connection_lost(self, exc) -> None:
        self.transport = None

    def _from_peer(self, addr) -> bool:
        try:
            return ipaddress.ip_address(str(addr[0]).split("%")[0]) == self.address and addr[1] == self.port
        except (ValueError, IndexError, TypeError):
            return False

    def datagram_received(self, data: bytes, addr) -> None:
        if not self._from_peer(addr):
            self.rejected["foreign"] += 1
            return
        try:
            packet = p.decode(data, self.key, self.session_key)
        except p.PacketError as exc:
            self.rejected[exc.reason] += 1
            return
        if packet.session != self.session:
            self.rejected["session"] += 1
            return
        if packet.type == p.Type.HELLO_ACK:
            self._on_ack(packet)
        elif packet.type == p.Type.ERROR:
            try:
                self._refuse(p.parse_error(packet.payload))
            except p.PacketError as exc:
                self._refuse(exc.reason)
        elif not self.guard.accept(packet.seq):
            self.rejected["replay"] += 1
        elif packet.type == p.Type.AUDIO_RET:
            sent = self.outstanding.pop(packet.ref, None)
            if sent is None and packet.ref >= self.next_ref:
                self.rejected["unsolicited"] += 1         # bloc jamais envoyé
                return
            self._last_valid = now = self.clock()
            if sent is None:                              # parti sans traitement : refusé, mais Breizh est VIVANT (lent)
                self.rejected["late"] += 1
                if self.on_return is not None:
                    self.on_return(packet.ref, None)
                return
            self.rtt_ms = round((now - sent) * 1000)
            if self.on_return is not None:
                self.on_return(packet.ref, packet.payload)
        elif packet.type == p.Type.PONG:
            sent = self._pings.pop(packet.ref, None)
            if sent is None:
                self.rejected["unsolicited"] += 1
                return
            now = self.clock()
            self._last_valid = now
            self.rtt_ms = round((now - sent) * 1000)
        elif packet.type == p.Type.BYE:
            self._lose("lost", f"Breizh a quitté le mode OpenRemoteTRX ({p.parse_bye(packet.payload)})")
        else:
            self.rejected["type"] += 1

    def _on_ack(self, packet: p.Packet) -> None:
        try:
            ack = p.parse_hello_ack(packet.payload)
        except p.PacketError as exc:
            self._refuse(exc.reason)
            return
        if self.session_key is not None:
            if ack.nonce != self._ack_nonce:            # Breizh doit répéter le MÊME HELLO_ACK pour la même session (§ 5.4)
                self.rejected["ack_changed"] += 1
            return
        self.guard.accept(packet.seq)
        self._ack_nonce = ack.nonce
        self.session_key = p.session_key(self.key, self.session, self._nonce, ack.nonce)
        self.peer_version = ack.breizh
        now = self.clock()
        self._last_valid, self._stable_since, self._refused_code = now, now, ""
        detail = f"{ack.breizh or 'Breizh'} joint (traitement annoncé : {ack.latency_ms} ms)"
        if self.state in ("connecting", "refused"):
            self.state = "ready"
            self._reactivate_requested = False
            self.notify("connected", detail)
        elif self._reactivate_requested:
            self.state = "ready"
            self._reactivate_requested = False
            self.notify("reactivated", f"Breizh repris à la demande de l'opérateur : {detail}")
        else:
            wait = f"repris dans {self.reactivate_after_s} s sans faute" if self.reactivate_after_s > 0 else \
                "repris seulement à la demande de l'opérateur"
            self.notify("back", f"Breizh répond de nouveau : {detail} ; {wait}")

    # ---------------------------------------------------------------- horloge
    def tick(self) -> None:
        now = self.clock()
        if now >= self._next_bad_report:
            self._next_bad_report = now + BAD_REPORT_S
            reasons = sorted(r for r in self.rejected if r not in NOT_BAD)
            bad = sum(self.rejected[r] for r in reasons)
            if bad > self._reported_bad:
                self.notify("bad_packets", f"{bad - self._reported_bad} paquet(s) refusé(s) en une minute ({', '.join(reasons)})")
            self._reported_bad = bad
        if self.transport is None:
            return
        if self.session_key is None:
            if self.state == "refused" and now < self._refused_until:
                return
            if self.state == "fallback" and self._refused_code and now < self._refused_until:
                return
            if now >= self._next_hello:
                self._next_hello = now + HELLO_EVERY_S
                self._send(p.Type.HELLO, payload=p.hello_payload(self._nonce, self.station_version))
            return
        if now - self._last_valid > IDLE_LOST_S:
            self._lose("lost", f"Breizh ne répond plus depuis {IDLE_LOST_S:g} s : prochaines émissions en direct")
            return
        if now >= self._next_ping:
            self._next_ping = now + PING_EVERY_S
            if self._send(p.Type.PING):
                self._pings[self.seq] = now
                for old in [s for s, t in self._pings.items() if now - t > IDLE_LOST_S]:
                    del self._pings[old]
        if (self.state == "fallback" and self.reactivate_after_s > 0 and self._stable_since is not None
                and now - self._stable_since >= self.reactivate_after_s):
            self.state = "ready"
            self.notify("reactivated", f"Breizh repris après {self.reactivate_after_s} s sans faute")

    async def run(self, stop: asyncio.Event) -> None:
        """Tourne jusqu'à `stop` ; une erreur de socket ne fait que retarder le prochain essai."""
        loop = asyncio.get_running_loop()
        next_socket = 0.0
        try:
            while not stop.is_set():
                if self.transport is None and self.clock() >= next_socket:
                    try:
                        await loop.create_datagram_endpoint(lambda: self, remote_addr=(self.host, self.port))
                    except OSError as exc:
                        next_socket = self.clock() + SOCKET_RETRY_S
                        log.warning("Breizh %s:%s injoignable (%s) : nouvel essai dans %g s",
                                    self.host, self.port, exc, SOCKET_RETRY_S)
                try:
                    self.tick()
                except Exception:                       # jamais de sortie : la station continue en direct
                    log.exception("liaison avec Breizh")
                try:
                    await asyncio.wait_for(stop.wait(), TICK_S)
                except asyncio.TimeoutError:
                    pass
        finally:
            self.bye()
            if self.transport is not None:
                self.transport.close()
