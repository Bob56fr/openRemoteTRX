# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Pont entre la passerelle (cœur TRX) et les modules.

- S'abonne aux écouteurs EXISTANTS du PttController et du CatLink : aucune
  logique de sécurité n'est modifiée, le pont ne fait qu'observer.
- Publie sur le bus : « ptt » (émission active ou non), « freq_mode »,
  « trx_state ». publish() ne bloque jamais : le cœur n'attend pas les modules.
- Applique les demandes de QSY d'un module via le PttController, donc avec
  les mêmes règles que pour le client (refus hors RX confirmé, bandes…).
  Aucun module ne peut demander le PTT : la commande n'existe pas.
- Relaie vers les clients connectés les messages des modules
  ({"type": "module", "module": nom, "data": …}) ; `scope: "operators"` : jamais
  à un visiteur.
- Relaie à un module (droit client_commands) la commande d'un client OPÉRATEUR
  (call) et publie « operator_activity » (au plus une fois par 30 s).

Toute erreur du pont est journalisée et laisse la passerelle tourner :
sans modules, la station fonctionne comme avant.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Iterable

from ..gateway.cat import CatConnectionError, RigError
from ..gateway.safety import Refused
from .bus import BusServer, CommandRefused
from .keys import key_path, load_or_create_key, module_secrets
from .registry import selected_manifests

from ..errors import codes
from ..errors.emit import emit_event
log = logging.getLogger(__name__)

MIN_QSY_HZ, MAX_QSY_HZ = 100_000, 3_000_000_000
OPERATOR_ACTIVITY_EVERY_S = 30.0
SDR_WINDOW_EVERY_S = 30.0           # fenêtre du SDR republiée aux modules au moins toutes les 30 s
RETAIN_MAX = 500                    # messages retenus par module et par sorte (instantané + changements) pour les clients qui arrivent
_MODE_RE = re.compile(r"[A-Za-z0-9\-]{1,16}")


class ModuleBridge:
    def __init__(self, cfg, ctrl, link, *,
                 clients: Callable[[], Iterable] = lambda: (),
                 port: int | None = None) -> None:
        self.cfg, self.ctrl, self.link = cfg, ctrl, link
        self.clients = clients          # sessions client ouvertes (méthode send)
        self.port = cfg.modules.bus_port if port is None else port
        self.bus: BusServer | None = None
        self.health: dict[str, dict] = {}
        self._last_ptt: str | None = None
        self._last_freq_mode: tuple | None = None
        self._last_connected: bool | None = None
        self._retained: dict[str, list[dict]] = {}
        self._last_activity = float("-inf")
        self._sdr_window: tuple | None = None          # dernière fenêtre du SDR publiée (spots du Cluster sur le SDR)
        self._sdr_window_at = float("-inf")

    # ------------------------------------------------------------- cycle de vie
    async def start(self) -> bool:
        """Démarre le bus si des modules sont demandés. Ne lève jamais."""
        if not self.cfg.modules.enabled:
            return False
        try:
            manifests, problems = selected_manifests(self.cfg.modules)
            for problem in problems:
                emit_event(codes.ORT_6511, logger=log, module="[modules] run", probleme=problem)
            if not manifests:
                emit_event(codes.ORT_6513, logger=log)
                return False
            key = load_or_create_key(key_path(self.cfg.supervisor.state_dir))
            bus = BusServer({m.name: m for m in manifests},
                            module_secrets(key, [m.name for m in manifests]),
                            state_provider=self.state, command_handler=self.command,
                            client_sink=self.to_clients, health_sink=self._on_health,
                            port=self.port)
            await bus.start()
        except Exception as exc:          # port occupé, clé illisible… : la station continue
            emit_event(codes.ORT_6514, logger=log, detail=str(exc) or type(exc).__name__)
            return False
        self.bus = bus
        self._last_ptt = self.ctrl.snapshot().state
        state = self.link.state
        self._last_freq_mode = (state.frequency_hz, state.mode)
        self._last_connected = state.connected
        self.ctrl.add_listener(self._on_ptt)
        self.link.add_listener(self._on_rig)
        log.info("modules : bus démarré sur 127.0.0.1:%s (%s)", bus.port,
                 ", ".join(m.name for m in manifests))
        return True

    async def stop(self) -> None:
        """Ne lève jamais : la coupure de l'émission qui suit doit toujours avoir lieu."""
        bus, self.bus = self.bus, None    # les écouteurs voient None et ne font plus rien
        if bus is not None:
            try:
                await asyncio.wait_for(bus.stop(), 3.0)
            except Exception:
                emit_event(codes.ORT_6527, logger=log, trace=True, contexte="arrêt du bus des modules", detail="voir la trace")

    # ------------------------------------------------------------- état
    def state(self) -> dict:
        snap, rig = self.ctrl.snapshot(), self.link.state
        return {"ptt": snap.state != "RX",           # KEYING et UNKEYING comptent comme émission
                "ptt_state": snap.state,
                "freq": rig.frequency_hz, "mode": rig.mode,
                "trx_connected": rig.connected}

    def _on_ptt(self, snap) -> None:
        if self.bus is None or snap.state == self._last_ptt:
            return
        self._last_ptt = snap.state
        self.bus.publish("ptt", {"active": snap.state != "RX", "state": snap.state})

    def _on_rig(self, state) -> None:
        if self.bus is None:
            return
        freq_mode = (state.frequency_hz, state.mode)
        if freq_mode != self._last_freq_mode:
            self._last_freq_mode = freq_mode
            self.bus.publish("freq_mode", {"freq": state.frequency_hz, "mode": state.mode})
        if state.connected != self._last_connected:
            self._last_connected = state.connected
            self.bus.publish("trx_state", {"connected": state.connected})

    def _on_health(self, module: str, metrics: dict) -> None:
        self.health[module] = metrics

    # ------------------------------------------------------------- commandes
    async def command(self, name: str, params: dict, module: str):
        if name != "qsy":
            raise CommandRefused("unknown_command", f"commande {name!r} inconnue")
        freq, mode = params.get("freq"), params.get("mode")
        if isinstance(freq, bool) or not isinstance(freq, int) or not MIN_QSY_HZ <= freq <= MAX_QSY_HZ:
            raise CommandRefused("invalid", "fréquence invalide (entier en Hz attendu)")
        if mode is not None and (not isinstance(mode, str) or not _MODE_RE.fullmatch(mode)):
            raise CommandRefused("invalid", "mode invalide")
        try:
            if mode and self.link.state.mode != mode:
                await self.ctrl.set_mode(mode)       # mode d'abord, comme le rappel de mémoire
            await self.ctrl.set_frequency(freq)
        except Refused as exc:
            raise CommandRefused(exc.reason, str(exc)) from exc
        except ValueError as exc:
            raise CommandRefused("invalid", str(exc)) from exc
        except RigError as exc:
            raise CommandRefused("rig_error", str(exc)) from exc
        except CatConnectionError as exc:
            raise CommandRefused("cat_down", str(exc)) from exc
        log.info("QSY %s Hz %s demandé par le module %s", freq, mode or "", module)
        return {"freq": freq, "mode": mode}

    # ------------------------------------------------------------- commandes des clients opérateurs
    async def call(self, module: str, data: dict):
        """Commande d'un client OPÉRATEUR relayée à un module ; CommandRefused si absent, refusé ou trop lent."""
        if self.bus is None:
            raise CommandRefused("module_absent", "modules non démarrés")
        return await self.bus.call(module, data)

    def has_client_commands(self, module: str) -> bool:
        """Le module est-il demandé (station.toml) et autorisé à recevoir les commandes des clients ?"""
        try:
            manifests, _ = selected_manifests(self.cfg.modules)
        except Exception:
            return False
        return any(m.name == module and m.rights.client_commands for m in manifests)

    def operator_activity(self, now: float | None = None) -> None:
        """Un client opérateur agit : événement « operator_activity » (statut « En RX » de la présence)."""
        now = time.monotonic() if now is None else now
        if self.bus is None or now - self._last_activity < OPERATOR_ACTIVITY_EVERY_S:
            return
        self._last_activity = now
        self.bus.publish("operator_activity", {})

    # ------------------------------------------------------------- vers les clients
    def to_clients(self, module: str, message: dict) -> None:
        """Relaie un message de module aux pages.

        `scope: "hf_view"` : seulement aux clients qui affichent la vue HF (données mobiles).
        `retain: "snapshot"|"delta"` : le dernier instantané et les changements qui l'ont suivi sont gardés
        et rejoués au client qui ouvre la vue (il voit tout de suite les spots, sans attendre le suivant).
        """
        payload = {"type": "module", "module": module, "data": message}
        if module == "sdr" and message.get("kind") == "sdr_state":
            self._publish_sdr_window(message)
        retain = message.get("retain")
        key = f"{module}/{message.get('kind', '')}"     # un fil retenu par sorte de message (spots, recent…)
        if retain == "snapshot":
            self._retained[key] = [payload]
        elif retain == "delta" and key in self._retained:
            if len(self._retained[key]) >= RETAIN_MAX:
                del self._retained[key]              # trop de changements : le prochain instantané reprendra
            else:
                self._retained[key].append(payload)
        only_hf = message.get("scope") == "hf_view"
        only_sdr = message.get("scope") == "sdr_view"              # lignes du SDR : opérateurs qui l'affichent
        operators = message.get("scope") in ("operators", "sdr_view")
        for session in list(self.clients()):
            if only_hf and not getattr(session, "hf_view", False):
                continue
            if only_sdr and not getattr(session, "sdr_view", False):
                continue
            if operators and getattr(session, "listener", True):     # inconnu = visiteur : rien
                continue
            try:
                session.send(payload)
            except Exception:
                emit_event(codes.ORT_6527, logger=log, trace=True, contexte=f"message du module {module} vers un client",
                           detail="non transmis")

    def _publish_sdr_window(self, state: dict) -> None:
        """Fenêtre du SDR vers les modules abonnés (Cluster : spots de cette fenêtre) : à chaque changement, et toutes
        les 30 s (un module relancé la retrouve). SDR arrêté ou en panne : fenêtre fermée (on = false)."""
        center, fs = state.get("center"), state.get("fs")
        ok = (state.get("state") == "running" and isinstance(center, (int, float)) and isinstance(fs, (int, float))
              and not isinstance(center, bool) and not isinstance(fs, bool) and 0 < fs <= 20_000_000 and 0 < center < 3e9)
        window = (int(center), int(fs)) if ok else None
        now = time.monotonic()
        if self.bus is None or (window == self._sdr_window and now - self._sdr_window_at < SDR_WINDOW_EVERY_S):
            return
        self._sdr_window, self._sdr_window_at = window, now
        self.bus.publish("sdr_window", {"on": True, "center": window[0], "fs": window[1]} if window else {"on": False})

    def on_sdr_view(self, session, opened: bool) -> None:
        """Un opérateur ouvre la rubrique SDR : lui renvoyer l'état retenu du module « sdr »."""
        if not opened or getattr(session, "listener", True):
            return
        for key, payloads in list(self._retained.items()):
            if not key.startswith("sdr/") and key != "cluster/sdr_spots":    # état du SDR et spots de sa fenêtre
                continue
            for payload in payloads:
                try:
                    session.send(payload)
                except Exception:
                    emit_event(codes.ORT_6527, logger=log, trace=True, contexte="rejeu de l'état du SDR", detail="impossible")
                    return

    def on_hf_view(self, session, opened: bool) -> None:
        """Un client ouvre la vue HF : lui renvoyer les messages retenus (instantané puis changements)."""
        if not opened:
            return
        for payloads in list(self._retained.values()):
            for payload in payloads:
                if payload["data"].get("scope") == "sdr_view":             # spots du SDR : rejoués par on_sdr_view
                    continue
                if payload["data"].get("scope") == "operators" and getattr(session, "listener", True):
                    continue
                try:
                    session.send(payload)
                except Exception:
                    emit_event(codes.ORT_6527, logger=log, trace=True, contexte="rejeu vers un client", detail="impossible")
                    return
