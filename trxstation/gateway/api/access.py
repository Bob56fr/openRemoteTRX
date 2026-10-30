# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Rôles et présence : opérateurs et visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md).

  * rôle lu dans [[clients]] à l'admission, jamais choisi par le client ;
  * quotas séparés : un visiteur ne prend jamais la place d'un opérateur ;
  * `listeners_need_operator` : visiteurs admis seulement si un opérateur est connecté, et déconnectés
    `operator_grace_s` après la perte du dernier opérateur s'il ne revient pas ;
  * pseudos à la place des identifiants dans tout ce qui part vers un autre client ;
  * liste blanche des commandes d'un visiteur : rien qui touche au poste ni à la station.
Pur Python, horloges injectables : testé sans aiortc. N'a AUCUN lien avec le PTT : un visiteur n'est jamais
enregistré auprès du PttController (session.py).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from ...config import Access, ClientAuth
from .protocol import COMMANDS

OPERATOR, LISTENER = "operator", "listener"

# Liste blanche d'un visiteur : relire l'état, recevoir (ou non) les balayages du spectre HF chez lui. Tout le reste
# est refusé, y compris une commande ajoutée plus tard. LISTENER_REFUSED n'est là que pour le test qui oblige à
# classer chaque nouvelle commande (tests/test_access.py) : le refus ne dépend PAS de cette liste.
LISTENER_COMMANDS = frozenset({"get_state", "spectrum_watch"})
LISTENER_REFUSED = frozenset({
    "toggle", "stop", "heartbeat", "set_frequency", "set_mode", "set_squelch", "set_function", "set_level",
    "set_offset", "memory_save", "memory_delete", "memory_recall", "layout_get", "layout_save", "layout_reset",
    "spectrum_set", "beeps_set", "local_release", "bug_report", "selcall_activate", "selcall_rearm",
    "selcall_deactivate", "selcall_options", "selcall_send", "selcall_calibrate", "listener_kick", "listeners_reopen"})
assert LISTENER_COMMANDS <= set(COMMANDS)

MESSAGES = {
    "account_disabled": "Ce compte est désactivé sur la station.",
    "account_expired": "Ce compte a expiré.",
    "account_changed": "Compte modifié sur la station : reconnecte-toi.",
    "listeners_off": "L'écoute des visiteurs n'est pas ouverte sur cette station.",
    "listeners_full": "Nombre maximal de visiteurs atteint.",
    "operators_full": "La station est occupée (trop de connexions).",
    "operator_absent": "L'opérateur n'est pas connecté à la station : l'écoute des visiteurs n'est possible qu'en sa présence.",
    "too_many_forbidden": "Trop de commandes refusées : connexion fermée.",
    "kicked": "Déconnecté par l'opérateur de la station.",
    "station_overload": "Station surchargée : écoute des visiteurs suspendue pour protéger la station.",
}
HTTP_STATUS = {"listeners_full": 503, "operators_full": 503}     # le reste : 403


class AccessRefused(Exception):
    def __init__(self, reason: str, message: str = ""):
        self.reason, self.message = reason, message or MESSAGES.get(reason, reason)
        self.status = HTTP_STATUS.get(reason, 403)
        super().__init__(self.message)


@dataclass
class Connection:
    client_id: str
    role: str
    secret: str                      # empreinte à l'admission : un mot de passe changé ferme la connexion
    number: int                      # « Visiteur 3 » quand le compte n'a pas de pseudo
    source: str = ""
    since: float = 0.0               # horloge monotone
    open: bool = False               # canal de contrôle ouvert (session démarrée)


@dataclass
class _Grace:
    started: float
    members: set[str] = field(default_factory=set)     # visiteurs présents au départ : peuvent se reconnecter pendant l'attente


class AccessControl:
    def __init__(self, clients: list[ClientAuth], settings: Access, *, clock: Callable[[], float] = time.monotonic,
                 today: Callable[[], date] = date.today):
        self.clock, self.today = clock, today
        self.accounts: dict[str, ClientAuth] = {}
        self.settings = settings
        self.connections: dict[str, Connection] = {}
        self._grace: _Grace | None = None
        self._numbers = 0
        self.guard = None                # OverloadGuard (overload.py) : écoute suspendue quand la station souffre
        self.reload(clients, settings)

    # ------------------------------------------------------------------ comptes

    def reload(self, clients: list[ClientAuth], settings: Access) -> None:
        """Nouvelle liste de comptes et réglages (station.toml relu et VALIDE). Les connexions devenues invalides
        sont rendues par `due()`."""
        self.accounts = {c.id: c for c in clients}
        self.settings = settings

    def role(self, client_id: str) -> str:
        account = self.accounts.get(client_id)
        return account.role if account is not None and account.role == LISTENER else OPERATOR

    def _problem(self, client_id: str, conn: Connection | None = None) -> str:
        """Motif qui interdit ce compte (vide = admis côté compte)."""
        account = self.accounts.get(client_id)
        if account is None:
            return "account_changed"
        if account.enabled is not True:
            return "account_disabled"
        if account.expired(self.today()):
            return "account_expired"
        if conn is not None and (conn.role != self.role(client_id) or conn.secret != _secret(account)):
            return "account_changed"
        return ""

    # ------------------------------------------------------------------ admission

    def operator_present(self) -> bool:
        return any(c.role == OPERATOR and c.open for c in self.connections.values())

    def admit(self, client_id: str, source: str = "") -> Connection:
        """Appelé APRÈS la vérification du mot de passe et la fermeture d'une ancienne connexion du même compte, sans
        attente entre la vérification et l'enregistrement (boucle asyncio : pas de course entre deux offres)."""
        reason = self._problem(client_id)
        if reason:
            raise AccessRefused(reason)
        role = self.role(client_id)
        others = [c for c in self.connections.values() if c.client_id != client_id]
        s = self.settings
        if role == LISTENER:
            if s.max_listeners <= 0:
                raise AccessRefused("listeners_off")
            if self.guard is not None and self.guard.suspended:
                raise AccessRefused("station_overload", self.guard.message())
            if sum(c.role == LISTENER for c in others) >= s.max_listeners:
                raise AccessRefused("listeners_full")
            if s.listeners_need_operator and not self.operator_present():
                grace = self._grace
                if grace is None or client_id not in grace.members:     # pendant l'attente : seul un visiteur déjà là revient
                    raise AccessRefused("operator_absent")
        elif sum(c.role == OPERATOR for c in others) >= s.max_operators:
            raise AccessRefused("operators_full")
        self._numbers += 1
        conn = Connection(client_id, role, _secret(self.accounts[client_id]), self._numbers, source[:64], self.clock())
        self.connections[client_id] = conn
        return conn

    def opened(self, client_id: str) -> None:
        conn = self.connections.get(client_id)
        if conn is not None:
            conn.open = True
            if conn.role == OPERATOR:
                self._grace = None                      # un opérateur revient : rien n'est coupé

    def closed(self, client_id: str) -> None:
        conn = self.connections.pop(client_id, None)
        if conn is not None and conn.role == OPERATOR and conn.open and not self.operator_present():
            self._start_grace()

    def _start_grace(self) -> None:
        self._grace = _Grace(self.clock(), {c.client_id for c in self.connections.values() if c.role == LISTENER})

    def due(self) -> list[tuple[str, str]]:
        """Connexions à fermer maintenant, avec leur motif (appelé chaque seconde par la passerelle)."""
        out = [(cid, reason) for cid, conn in self.connections.items() if (reason := self._problem(cid, conn))]
        listeners = [cid for cid, c in self.connections.items() if c.role == LISTENER]
        if not self.settings.listeners_need_operator or self.operator_present():
            self._grace = None
        elif listeners:
            if self._grace is None:                     # commutateur passé à true sans opérateur connecté
                self._start_grace()
            elif self.clock() - self._grace.started >= self.settings.operator_grace_s:
                out += [(cid, "operator_absent") for cid in listeners]
        if self.settings.max_listeners <= 0:            # fonction coupée sur la station
            out += [(cid, "listeners_off") for cid in listeners]
        seen: set[str] = set()
        return [(cid, reason) for cid, reason in out if not (cid in seen or seen.add(cid))]

    def grace_remaining(self) -> float | None:
        if self._grace is None or not self.settings.listeners_need_operator or self.operator_present():
            return None
        return max(0.0, self.settings.operator_grace_s - (self.clock() - self._grace.started))

    # ------------------------------------------------------------------ noms et présence

    def pseudo(self, client_id: str) -> str:
        """Nom montré aux AUTRES connectés : jamais l'identifiant du compte."""
        account = self.accounts.get(client_id)
        if account is not None and account.pseudo:
            return account.pseudo
        conn = self.connections.get(client_id)
        if self.role(client_id) == LISTENER:
            return f"Visiteur {conn.number}" if conn is not None else "Visiteur"
        return "Opérateur"

    def public_owner(self, owner: str | None) -> str | None:
        """Propriétaire de l'émission tel qu'un visiteur le voit (pseudo ; « local » et None inchangés)."""
        if owner is None or owner not in self.accounts:
            return owner
        return self.pseudo(owner)

    def presence(self, role: str) -> dict:
        """`state.presence` : nombres et pseudos pour tous ; identifiants et origines pour un opérateur seulement."""
        now = self.clock()
        live = [c for c in self.connections.values() if c.open]
        people: dict[tuple[str, str], dict] = {}
        for c in sorted(live, key=lambda c: c.since):
            key = (c.role, self.pseudo(c.client_id))
            entry = people.setdefault(key, {"pseudo": key[1], "role": c.role, "since_s": int(now - c.since), "count": 0})
            entry["count"] += 1
        remaining = self.grace_remaining()
        out = {"operators": sum(c.role == OPERATOR for c in live), "listeners": sum(c.role == LISTENER for c in live),
               "max_listeners": self.settings.max_listeners,
               "suspended": self.guard.status() if self.guard is not None else None,
               "grace_remaining_s": None if remaining is None else round(remaining),
               "people": list(people.values())}
        if role == OPERATOR:
            out["connections"] = [{"id": c.client_id, "pseudo": self.pseudo(c.client_id), "role": c.role,
                                   "source": c.source, "since_s": int(now - c.since)} for c in live]
        return out


def _secret(account: ClientAuth) -> str:
    return account.password_hash or account.token


def listener_muted(settings: Access, cfg, frequency_hz) -> bool:
    """Silence pour les visiteurs : réception hors [[bands]] (sauf listeners_outside_bands). Fréquence inconnue :
    silence, par prudence. Liste de bandes vide : silence permanent."""
    if settings.listeners_outside_bands:
        return False
    if not isinstance(frequency_hz, (int, float)) or isinstance(frequency_hz, bool) or frequency_hz <= 0:
        return True
    return not cfg.tx_allowed(frequency_hz)
