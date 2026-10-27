# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Authentification des clients : identifiant + mot de passe, comparaison à temps constant, freinage des essais.

Menaces visées (l'API peut être exposée sur Internet) :
  * devinette de mot de passe : freinage par ORIGINE (5 échecs / minute) et par COMPTE (30 échecs / 15 min,
    quelle que soit l'origine), et coût de ~100 ms par essai (scrypt) ;
  * énumération des comptes : réponse et durée identiques que l'identifiant existe ou non ;
  * épuisement du processeur : quand une origine ou un compte est verrouillé, AUCUN hachage n'est calculé ;
  * usurpation de l'origine : X-Forwarded-For n'est cru que si la connexion directe vient d'un proxy de confiance.
`verify` est bloquant (scrypt) : le serveur l'appelle dans un fil, jamais dans la boucle asyncio.
"""
from __future__ import annotations

import hmac
import ipaddress
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable

from ...config import ClientAuth
from ...passwords import hash_password, verify_password

DEFAULT_PROXIES = ("127.0.0.1", "::1")
MAX_TRACKED = 10_000


def _in_networks(address: str, networks: list) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in networks)


def client_source(remote: str | None, forwarded_for: str | None = None,
                  trusted: Iterable[str] = DEFAULT_PROXIES) -> str:
    """Origine utilisée pour freiner les essais.

    Derrière un proxy (Caddy, nginx, routeur...), toutes les connexions arrivent de l'adresse du proxy : sans
    X-Forwarded-For, un seul attaquant verrouillerait tout le monde. L'en-tête n'est cru QUE si la connexion directe
    vient d'une adresse listée dans `trusted` (IP ou réseau CIDR) ; sinon un client pourrait en forger un.
    """
    networks = []
    for item in trusted:
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    if remote and forwarded_for and _in_networks(remote, networks):
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first[:64]
    return remote or ""


class ClientRegistry:
    def __init__(self, clients: list[ClientAuth], *, clock: Callable[[], float] = time.monotonic,
                 max_failures: int = 5, window_s: float = 60.0,
                 account_max_failures: int = 30, account_window_s: float = 900.0):
        self._secrets = {c.id: ("hash", c.password_hash) if c.password_hash else ("token", c.token) for c in clients}
        self._clock = clock
        self.max_failures, self.window_s = max_failures, window_s
        self.account_max_failures, self.account_window_s = account_max_failures, account_window_s
        self._by_source: dict[str, deque[float]] = defaultdict(deque)
        self._by_account: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._dummy_hash = hash_password("x" * 16)          # pour égaliser le temps quand l'identifiant est inconnu

    def __bool__(self) -> bool:
        return bool(self._secrets)

    @staticmethod
    def _recent(failures: deque, now: float, window: float) -> deque:
        while failures and now - failures[0] > window:
            failures.popleft()
        return failures

    def _prune(self, table: dict, window: float, now: float) -> None:
        if len(table) > MAX_TRACKED:                         # un attaquant ne doit pas pouvoir remplir la mémoire
            for key in [k for k, v in table.items() if not self._recent(v, now, window)]:
                del table[key]

    def locked(self, source: str, client_id: str = "") -> bool:
        with self._lock:
            now = self._clock()
            if len(self._recent(self._by_source[source], now, self.window_s)) >= self.max_failures:
                return True
            return bool(client_id in self._secrets
                        and len(self._recent(self._by_account[client_id], now, self.account_window_s)) >= self.account_max_failures)

    def verify(self, client_id: str, secret: str, source: str = "") -> bool:
        """Vrai si le couple est valide. Bloquant (scrypt) : à appeler dans un fil."""
        if not isinstance(client_id, str) or not isinstance(secret, str) or len(secret) > 256 or len(client_id) > 64:
            self._record_failure(source, "")
            return False
        if self.locked(source, client_id):
            return False                                     # verrouillé : on refuse sans calculer de hachage
        kind, stored = self._secrets.get(client_id, ("hash", self._dummy_hash))
        if kind == "hash":
            ok = verify_password(secret, stored)
        else:
            ok = hmac.compare_digest(stored.encode(), secret.encode())
        ok = ok and client_id in self._secrets
        if not ok:
            self._record_failure(source, client_id)
        return ok

    def _record_failure(self, source: str, client_id: str) -> None:
        with self._lock:
            now = self._clock()
            self._by_source[source].append(now)
            self._prune(self._by_source, self.window_s, now)
            if client_id in self._secrets:
                self._by_account[client_id].append(now)
                self._prune(self._by_account, self.account_window_s, now)
