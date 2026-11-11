# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lecture de FreeDV Reporter (qso.freedv.org) en OBSERVATEUR : rien n'est envoyé sur la station (ni indicatif, ni
locator, ni fréquence), seulement le rôle « view », comme la page publique du service.

Protocole : socket.io v4 sur engine.io v4 en « long polling » HTTPS (pas de WebSocket, aucune dépendance) :
GET `…&transport=polling` -> `0{"sid": …}` ; POST `40{"role": "view", "protocol_version": 2}` ; puis des GET
successifs dont les paquets sont séparés par 0x1E : `2` = ping (réponse `3`), `42[nom, données]` = événement
(`bulk_update` = liste d'événements), `1` ou `41` = fermeture. Ce protocole n'est pas documenté par FreeDV : toute
réponse inattendue fait reprendre la connexion 15 s plus tard (puis 30, 60, 120 s), sans jamais toucher la station.

`ReporterClient.run(stop)` tourne dans un FIL (requêtes bloquantes) ; l'état partagé est protégé par `lock`.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from collections.abc import Callable

from .activity import ReporterState

log = logging.getLogger("trx.freedv.reporter")

URL = "https://qso.freedv.org/socket.io/?EIO=4&transport=polling"
SEP = "\x1e"
MAX_RESPONSE = 4 * 1024 * 1024        # bulk_update de plusieurs milliers de stations : ~1 Mo
POLL_TIMEOUT_S = 60.0
BACKOFF_S = (15.0, 30.0, 60.0, 120.0)

CONNECTING, OK, ERROR = "connexion", "ok", "erreur"


class ReporterError(Exception):
    pass


def http_get(url: str, user_agent: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT_S) as r:
        data = r.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise ReporterError("réponse trop grande")
    return data.decode("utf-8", errors="replace")


def http_post(url: str, body: str, user_agent: str) -> None:
    req = urllib.request.Request(url, data=body.encode("utf-8"),
                                 headers={"User-Agent": user_agent, "Content-Type": "text/plain;charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=30.0) as r:
        r.read(4096)


def parse_open(text: str) -> str:
    """Réponse d'ouverture `0{...}` -> identifiant de session."""
    if not text.startswith("0"):
        raise ReporterError("ouverture inattendue")
    try:
        sid = json.loads(text[1:]).get("sid")
    except (ValueError, AttributeError):
        raise ReporterError("ouverture illisible") from None
    if not isinstance(sid, str) or not 0 < len(sid) <= 100 or not sid.replace("-", "").replace("_", "").isalnum():
        raise ReporterError("identifiant de session illisible")
    return sid


def events_of(packet: str) -> list[tuple[str, dict]]:
    """Paquet `42[...]` -> [(nom, données)] (bulk_update déplié) ; [] si illisible."""
    try:
        ev = json.loads(packet[2:])
    except ValueError:
        return []
    if not isinstance(ev, list) or not ev or not isinstance(ev[0], str):
        return []
    items = ev[1] if ev[0] == "bulk_update" and len(ev) > 1 and isinstance(ev[1], list) else [ev]
    out = []
    for it in items:
        if isinstance(it, list) and len(it) >= 2 and isinstance(it[0], str) and isinstance(it[1], dict):
            out.append((it[0], it[1]))
    return out


class ReporterClient:
    def __init__(self, state: ReporterState, lock: threading.Lock, *, user_agent: str = "openRemoteTRX",
                 url: str = URL, get: Callable[[str, str], str] = http_get,
                 post: Callable[[str, str, str], None] = http_post) -> None:
        self.state, self.lock, self.url, self.user_agent = state, lock, url, user_agent
        self._get, self._post = get, post
        self.status, self.message = CONNECTING, "connexion à FreeDV Reporter…"

    def _set(self, status: str, message: str) -> None:
        with self.lock:
            self.status, self.message = status, message

    def session(self, stop: threading.Event) -> None:
        """Une connexion, jusqu'à sa fin (exception) ou à l'arrêt demandé."""
        sid = parse_open(self._get(self.url, self.user_agent))
        url = self.url + "&sid=" + sid
        with self.lock:
            self.state.clear()
        self._post(url, "40" + json.dumps({"role": "view", "protocol_version": 2}), self.user_agent)
        self._set(OK, "")
        while not stop.is_set():
            for packet in self._get(url, self.user_agent).split(SEP):
                if packet == "2":
                    self._post(url, "3", self.user_agent)
                elif packet.startswith("42"):
                    events = events_of(packet)
                    with self.lock:
                        for name, data in events:
                            self.state.apply(name, data)
                elif packet in ("1", "41") or packet.startswith("44"):
                    raise ReporterError("connexion fermée par FreeDV Reporter")

    def run(self, stop: threading.Event) -> None:
        failures = 0
        while not stop.is_set():
            try:
                self.session(stop)
                failures = 0
            except Exception as e:          # réseau, protocole changé... : jamais fatal
                delay = BACKOFF_S[min(failures, len(BACKOFF_S) - 1)]
                failures += 1
                text = str(e) if isinstance(e, ReporterError) else type(e).__name__
                log.warning("FreeDV Reporter : %s ; nouvel essai dans %.0f s", text, delay)
                with self.lock:
                    self.state.clear()
                self._set(ERROR, f"FreeDV Reporter injoignable ({text}) ; nouvel essai dans {delay:.0f} s")
                stop.wait(delay)
