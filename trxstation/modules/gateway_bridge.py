"""Pont entre la passerelle (cœur TRX) et les modules.

- S'abonne aux écouteurs EXISTANTS du PttController et du CatLink : aucune
  logique de sécurité n'est modifiée, le pont ne fait qu'observer.
- Publie sur le bus : « ptt » (émission active ou non), « freq_mode »,
  « trx_state ». publish() ne bloque jamais : le cœur n'attend pas les modules.
- Applique les demandes de QSY d'un module via le PttController, donc avec
  les mêmes règles que pour le client (refus hors RX confirmé, bandes…).
  Aucun module ne peut demander le PTT : la commande n'existe pas.
- Relaie vers les clients connectés les messages des modules
  ({"type": "module", "module": nom, "data": …}).

Toute erreur du pont est journalisée et laisse la passerelle tourner :
sans modules, la station fonctionne comme avant.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Iterable

from ..gateway.cat import CatConnectionError, RigError
from ..gateway.safety import Refused
from .bus import BusServer, CommandRefused
from .keys import key_path, load_or_create_key, module_secrets
from .registry import selected_manifests

log = logging.getLogger(__name__)

MIN_QSY_HZ, MAX_QSY_HZ = 100_000, 3_000_000_000
RETAIN_MAX = 500                    # messages retenus par module (instantané + changements) pour les clients qui arrivent
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

    # ------------------------------------------------------------- cycle de vie
    async def start(self) -> bool:
        """Démarre le bus si des modules sont demandés. Ne lève jamais."""
        if not self.cfg.modules.enabled:
            return False
        try:
            manifests, problems = selected_manifests(self.cfg.modules)
            for problem in problems:
                log.warning("modules : %s", problem)
            if not manifests:
                log.warning("modules : aucun module utilisable, bus non démarré")
                return False
            key = load_or_create_key(key_path(self.cfg.supervisor.state_dir))
            bus = BusServer({m.name: m for m in manifests},
                            module_secrets(key, [m.name for m in manifests]),
                            state_provider=self.state, command_handler=self.command,
                            client_sink=self.to_clients, health_sink=self._on_health,
                            port=self.port)
            await bus.start()
        except Exception as exc:          # port occupé, clé illisible… : la station continue
            log.error("modules indisponibles (%s) : la station fonctionne sans eux", exc)
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
                log.exception("arrêt du bus des modules incomplet")

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

    # ------------------------------------------------------------- vers les clients
    def to_clients(self, module: str, message: dict) -> None:
        """Relaie un message de module aux pages.

        `scope: "hf_view"` : seulement aux clients qui affichent la vue HF (données mobiles).
        `retain: "snapshot"|"delta"` : le dernier instantané et les changements qui l'ont suivi sont gardés
        et rejoués au client qui ouvre la vue (il voit tout de suite les spots, sans attendre le suivant).
        """
        payload = {"type": "module", "module": module, "data": message}
        retain = message.get("retain")
        if retain == "snapshot":
            self._retained[module] = [payload]
        elif retain == "delta" and module in self._retained:
            if len(self._retained[module]) >= RETAIN_MAX:
                del self._retained[module]           # trop de changements : le prochain instantané reprendra
            else:
                self._retained[module].append(payload)
        only_hf = message.get("scope") == "hf_view"
        for session in list(self.clients()):
            if only_hf and not getattr(session, "hf_view", False):
                continue
            try:
                session.send(payload)
            except Exception:
                log.exception("message du module %s non transmis", module)

    def on_hf_view(self, session, opened: bool) -> None:
        """Un client ouvre la vue HF : lui renvoyer les messages retenus (instantané puis changements)."""
        if not opened:
            return
        for payloads in list(self._retained.values()):
            for payload in payloads:
                try:
                    session.send(payload)
                except Exception:
                    log.exception("rejeu vers un client impossible")
                    return
