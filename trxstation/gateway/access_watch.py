# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Surveillance des accès, chaque seconde, dans la boucle de la passerelle (docs/visiteurs-cahier-des-charges.md) :

  * station.toml modifié (TRX Console, menu 4.2) : [[clients]] et [access] relus SANS redémarrer, seulement si TOUT le
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
from ..errors import codes
from .api.access import LISTENER
from ..errors.emit import emit_event

log = logging.getLogger(__name__)
KICK_REQUEST = "visitor-kick.json"
REOPEN_REQUEST = "visitor-reopen.json"     # console : rouvrir l'écoute après une surcharge (acceptée seulement au vert)
KICK_MAX_AGE_S = 10.0


def kick_request(client_id: str, now: float | None = None) -> bytes:
    """Contenu du fichier de demande écrit par la console."""
    return json.dumps({"id": client_id, "at": time.time() if now is None else now}).encode("utf-8")


class AccessWatcher:
    def __init__(self, access, registry, manager, config_path: Path | None, state_dir: Path, *,
                 interval_s: float = 1.0, wall: Callable[[], float] = time.time):
        self.access, self.registry, self.manager = access, registry, manager
        self.config_path, self.kick_path = config_path, Path(state_dir) / KICK_REQUEST
        self.reopen_path = Path(state_dir) / REOPEN_REQUEST
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
            emit_event(codes.ORT_9706, logger=log, problemes="; ".join(exc.problems)[:500])
            return False
        except OSError as exc:
            emit_event(codes.ORT_9020, logger=log, fichier=str(self.config_path), detail=f"{exc} ; nouvel essai")
            return False
        self._mtime, self._refused_mtime = mtime, None
        self.registry.update(cfg.clients)
        self.access.reload(cfg.clients, cfg.access)
        if self.access.guard is not None:                 # seuils de surcharge relus aussi
            from .api.overload import Limits
            a = cfg.access
            self.access.guard.limits = Limits(a.overload_temp_c, a.overload_cpu_pct, a.overload_lag_ms, a.overload_mem_pct)
        log.info("comptes relus : %d opérateur(s), %d visiteur(s) ; visiteurs %s (%d au plus)",
                 sum(c.role != LISTENER for c in cfg.clients), sum(c.role == LISTENER for c in cfg.clients),
                 "ouverts" if cfg.access.max_listeners else "fermés", cfg.access.max_listeners)
        return True

    def take_kick_request(self, path: Path | None = None) -> str | None:
        """Identifiant du visiteur à déconnecter (demande lue puis effacée), ou None."""
        path = path or self.kick_path
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            emit_event(codes.ORT_4002, logger=log, raison=f"demande illisible ({exc})")
            return None
        try:
            path.unlink()
        except OSError as exc:
            emit_event(codes.ORT_4002, logger=log, raison=f"demande impossible à effacer ({exc})")
        try:
            data = json.loads(raw)
            client_id, at = data["id"], float(data["at"])
        except (ValueError, KeyError, TypeError):
            emit_event(codes.ORT_4002, logger=log, raison="demande mal formée")
            return None
        if not isinstance(client_id, str) or abs(self.wall() - at) > KICK_MAX_AGE_S:
            emit_event(codes.ORT_4002, logger=log, raison="demande trop ancienne ou invalide")
            return None
        return client_id

    async def step(self) -> None:
        self.check_config()
        guard = self.access.guard
        if guard is not None:
            if self.take_kick_request(self.reopen_path) is not None:
                refusal = guard.reopen()
                if refusal:
                    emit_event(codes.ORT_4310, logger=log, depassement=refusal, par="TRX Console")
                else:
                    emit_event(codes.ORT_4019, logger=log, compte="TRX Console", action="écoute des visiteurs rouverte")
            listeners = [cid for cid, c in self.access.connections.items() if c.role == LISTENER]
            if guard.step(len(listeners)):
                message = guard.message()
                emit_event(codes.ORT_4308, logger=log, depassement=message, n=len(listeners))
                alert = getattr(self.manager, "alert", None)
                if alert is not None:
                    alert(codes.ORT_4308, message)
                for client_id in listeners:
                    await self.manager.kick(client_id, "station_overload", message=message)
        wanted = self.take_kick_request()
        if wanted is not None:
            if self.access.role(wanted) == LISTENER and wanted in self.access.connections:
                await self.manager.kick(wanted, "kicked")
            else:
                emit_event(codes.ORT_4002, logger=log, raison=f"« {wanted[:32]} » n'est pas un visiteur connecté")
        for client_id, reason in self.access.due():
            await self.manager.kick(client_id, reason)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.step()
            except Exception:                         # jamais de sortie de la passerelle pour ça
                emit_event(codes.ORT_8018, logger=log, trace=True, detail="voir la trace")
            try:
                await asyncio.wait_for(stop.wait(), self.interval_s)
            except asyncio.TimeoutError:
                pass
