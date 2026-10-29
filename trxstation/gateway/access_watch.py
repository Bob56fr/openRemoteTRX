# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Surveillance des accès, chaque seconde, dans la boucle de la passerelle (docs/visiteurs-cahier-des-charges.md) :

  * station.toml modifié (TRX Console, menu 20) : [[clients]] et [access] relus SANS redémarrer, seulement si TOUT le
    fichier est valide (sinon l'ancienne liste reste et l'erreur est journalisée une fois) ;
  * connexions devenues invalides (compte désactivé, expiré, supprimé, mot de passe ou rôle changé) et visiteurs
    restés sans opérateur au-delà de l'attente : fermées avec leur motif ;
  * demande de déconnexion d'un visiteur écrite par la console (state_dir/visitor-kick.json) : ce canal ne peut que
    DÉCONNECTER un VISITEUR ; une demande de plus de 10 s est ignorée.
Une erreur ici ne fait jamais quitter la passerelle.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from .. import config as cfgmod
from .api.access import LISTENER

log = logging.getLogger(__name__)
KICK_REQUEST = "visitor-kick.json"
KICK_MAX_AGE_S = 10.0


def kick_request(client_id: str, now: float | None = None) -> bytes:
    """Contenu du fichier de demande écrit par la console."""
    return json.dumps({"id": client_id, "at": time.time() if now is None else now}).encode("utf-8")


class AccessWatcher:
    def __init__(self, access, registry, manager, config_path: Path | None, state_dir: Path, *,
                 interval_s: float = 1.0, wall: Callable[[], float] = time.time):
        self.access, self.registry, self.manager = access, registry, manager
        self.config_path, self.kick_path = config_path, Path(state_dir) / KICK_REQUEST
        self.interval_s, self.wall = interval_s, wall
        self._mtime = self._stat()
        self._refused_mtime: float | None = None

    def _stat(self) -> float | None:
        try:
            return self.config_path.stat().st_mtime if self.config_path is not None else None
        except OSError:
            return None

    def check_config(self) -> bool:
        """Vrai si une nouvelle liste de comptes a été prise."""
        mtime = self._stat()
        if mtime is None or mtime == self._mtime or mtime == self._refused_mtime:
            return False
        try:
            cfg = cfgmod.load(self.config_path)
        except cfgmod.ConfigError as exc:
            self._refused_mtime = mtime
            log.error("station.toml modifié mais INVALIDE : comptes et visiteurs inchangés (%s)", "; ".join(exc.problems)[:500])
            return False
        except OSError as exc:
            log.warning("station.toml illisible pour l'instant (%s) : nouvel essai", exc)
            return False
        self._mtime, self._refused_mtime = mtime, None
        self.registry.update(cfg.clients)
        self.access.reload(cfg.clients, cfg.access)
        log.info("comptes relus : %d opérateur(s), %d visiteur(s) ; visiteurs %s (%d au plus)",
                 sum(c.role != LISTENER for c in cfg.clients), sum(c.role == LISTENER for c in cfg.clients),
                 "ouverts" if cfg.access.max_listeners else "fermés", cfg.access.max_listeners)
        return True

    def take_kick_request(self) -> str | None:
        """Identifiant du visiteur à déconnecter (demande lue puis effacée), ou None."""
        try:
            raw = self.kick_path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("demande de déconnexion illisible : %s", exc)
            return None
        try:
            self.kick_path.unlink()
        except OSError as exc:
            log.warning("demande de déconnexion impossible à effacer : %s", exc)
        try:
            data = json.loads(raw)
            client_id, at = data["id"], float(data["at"])
        except (ValueError, KeyError, TypeError):
            log.warning("demande de déconnexion mal formée : ignorée")
            return None
        if not isinstance(client_id, str) or abs(self.wall() - at) > KICK_MAX_AGE_S:
            log.warning("demande de déconnexion trop ancienne ou invalide : ignorée")
            return None
        return client_id

    async def step(self) -> None:
        self.check_config()
        wanted = self.take_kick_request()
        if wanted is not None:
            if self.access.role(wanted) == LISTENER and wanted in self.access.connections:
                await self.manager.kick(wanted, "kicked")
            else:
                log.warning("demande de déconnexion de « %s » ignorée : pas un visiteur connecté", wanted[:32])
        for client_id, reason in self.access.due():
            await self.manager.kick(client_id, reason)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.step()
            except Exception:                         # jamais de sortie de la passerelle pour ça
                log.exception("surveillance des accès en erreur")
            try:
                await asyncio.wait_for(stop.wait(), self.interval_s)
            except asyncio.TimeoutError:
                pass
