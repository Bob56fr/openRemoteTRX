"""ControlSession : la conversation d'UN client authentifié avec la passerelle.

Le client est déjà authentifié (jeton vérifié avant la création de la connexion). La session :
  * enregistre le client auprès du PttController, et le désenregistre à la fermeture (ce qui
    COUPE l'émission si ce client la détenait : perte de connexion = retour RX) ;
  * traite les commandes (toggle, stop, heartbeat, fréquence, mode) ;
  * diffuse l'état toutes les 0,25 s (changement, ou au moins chaque seconde) ;
  * limite le débit des messages.
Rien ici ne dépend d'un transport : `send` est une fonction fournie par la couche réseau.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable

from ...layout import LayoutInvalid, LayoutStorageError, LayoutStore, validate_profile
from ..cat import Capabilities, CatConnectionError, CatLink, RigError
from ..memories import MemoryStore, MemoryStoreError
from ..safety import PttController, Refused
from .protocol import PROTOCOL_VERSION, ProtocolError, parse_command

log = logging.getLogger(__name__)


def build_state(link: CatLink, ctrl: PttController, pipeline=None, spectrum=None) -> dict:
    """`spectrum` : SpectrumService (facultatif) ; seul son état (state, code, message) part vers les clients."""
    rig, ptt = link.state, ctrl.snapshot()
    remaining = None if ptt.tot_remaining_s is None else round(ptt.tot_remaining_s, 1)
    return {
        "type": "state",
        "ptt": {"state": ptt.state, "owner": ptt.owner, "tot_remaining_s": remaining,
                "tot_warning": ptt.tot_warning, "last_cut_reason": ptt.last_cut_reason, "fault": ptt.fault},
        "rig": {"connected": rig.connected, "frequency_hz": rig.frequency_hz, "mode": rig.mode,
                "passband_hz": rig.passband_hz, "strength_db": rig.strength_db,
                "functions": dict(rig.functions), "levels": dict(rig.levels)},
        "audio": pipeline.stats() if pipeline is not None else {},
        "clients": ctrl.clients,
        "spectrum": spectrum.snapshot() if spectrum is not None else {"state": "off", "code": "", "message": ""},
    }


class ControlSession:
    def __init__(self, client_id: str, ctrl: PttController, link: CatLink, pipeline,
                 capabilities: Capabilities | None, send: Callable[[dict], None], *,
                 max_msgs_per_s: int = 30, state_interval_s: float = 0.25,
                 clock: Callable[[], float] = time.monotonic, memories: MemoryStore | None = None,
                 layouts: LayoutStore | None = None, spectrum=None):
        self.client_id, self.ctrl, self.link, self.pipeline = client_id, ctrl, link, pipeline
        self.spectrum = spectrum
        self.capabilities, self._send = capabilities, send
        self.memories = memories
        self.layouts = layouts
        self._memories_listener = lambda items: self.send({"type": "memories", "items": items})
        self.max_msgs_per_s, self.state_interval_s, self.clock = max_msgs_per_s, state_interval_s, clock
        self._times: deque[float] = deque()
        self._state_task: asyncio.Task | None = None
        self.closed = False

    def send(self, message: dict) -> None:
        try:
            self._send(message)
        except Exception:
            log.exception("envoi vers %s impossible", self.client_id)

    async def start(self) -> None:
        self.ctrl.connect_client(self.client_id)
        self.send({"type": "hello", "protocol": PROTOCOL_VERSION, "client_id": self.client_id,
                   "capabilities": self.capabilities.to_dict() if self.capabilities else None,
                   "tx_modes": list(self.ctrl.config.rig.tx_modes),
                   "max_power_w": self.ctrl.config.rig.max_power_w,
                   "memories": self.memories.list() if self.memories else [],
                   "layouts": self.layouts is not None,
                   "spectrum": self.spectrum.capability() if self.spectrum is not None else None})   # canal « spectrum »                     # mises en page personnalisées : layout_get
        if self.memories:
            self.memories.add_listener(self._memories_listener)       # une mémoire créée ailleurs apparaît ici aussitôt
        self.send(self._state())
        self._state_task = asyncio.get_running_loop().create_task(self._state_loop())

    def _state(self) -> dict:
        return build_state(self.link, self.ctrl, self.pipeline, self.spectrum)

    async def close(self) -> None:
        """Idempotent. Désenregistre le client : coupe l'émission s'il en était propriétaire."""
        if self.closed:
            return
        self.closed = True
        if self.memories:
            self.memories.remove_listener(self._memories_listener)
        if self._state_task is not None:
            self._state_task.cancel()
            await asyncio.gather(self._state_task, return_exceptions=True)
        await self.ctrl.disconnect_client(self.client_id)

    async def _state_loop(self) -> None:
        last_key, last_sent = "", 0.0
        while not self.closed:
            message = self._state()
            key, now = json.dumps(message, sort_keys=True), self.clock()
            if key != last_key or now - last_sent >= 1.0:
                self.send(message)
                last_key, last_sent = key, now
            await asyncio.sleep(self.state_interval_s)

    # ------------------------------------------------------------------ commandes

    async def _memory_command(self, cmd) -> None:
        if self.memories is None:
            self._result(cmd.id, False, reason="memories_unavailable")
            return
        params = cmd.params
        if cmd.name == "memory_save":
            try:
                memory = self.memories.save(name=params["name"], hz=params["hz"], mode=params["mode"],
                                            favorite=params["favorite"], memory_id=params["memory_id"])
            except MemoryStoreError as exc:
                self._result(cmd.id, False, reason="storage_error", detail=str(exc))
                return
            self._result(cmd.id, True, memory=memory.to_dict())
        elif cmd.name == "memory_delete":
            try:
                deleted = self.memories.delete(params["memory_id"])
            except MemoryStoreError as exc:
                self._result(cmd.id, False, reason="storage_error", detail=str(exc))
                return
            self._result(cmd.id, deleted, **({} if deleted else {"reason": "unknown_memory"}))
        else:                                                                 # memory_recall : mode d'abord, puis fréquence
            memory = self.memories.get(params["memory_id"])
            if memory is None:
                self._result(cmd.id, False, reason="unknown_memory")
                return
            if self.link.state.mode != memory.mode:                           # inutile de toucher au filtre si le mode est le bon
                await self.ctrl.set_mode(memory.mode)
            await self.ctrl.set_frequency(memory.hz)
            self._result(cmd.id, True, memory=memory.to_dict())

    def _layout_command(self, cmd) -> None:
        """Profil de mise en page de CE client. Aucun effet sur le poste : le profil ne fait que présenter."""
        if self.layouts is None:
            self._result(cmd.id, False, reason="layouts_unavailable")
            return
        try:
            if cmd.name == "layout_save":
                report = self.layouts.save(self.client_id, cmd.params["profile"], self.capabilities)
                self._result(cmd.id, True, warnings=report.warnings)
                return
            if cmd.name == "layout_reset":
                self.layouts.reset(self.client_id)
        except LayoutInvalid as exc:
            self._result(cmd.id, False, reason="layout_invalid", detail=str(exc), errors=exc.report.errors)
            return
        except LayoutStorageError as exc:
            self._result(cmd.id, False, reason="layout_storage_error", detail=str(exc))
            return
        profile, source = self.layouts.get(self.client_id)
        warnings = validate_profile(profile, self.capabilities).warnings
        self._result(cmd.id, True, profile=profile, source=source, warnings=warnings)

    def _result(self, ident, ok: bool, **extra) -> None:
        self.send({"type": "result", "id": ident, "ok": ok, **extra})

    def _rate_limited(self) -> bool:
        now = self.clock()
        self._times.append(now)
        while self._times and now - self._times[0] > 1.0:
            self._times.popleft()
        return len(self._times) > self.max_msgs_per_s

    async def on_message(self, raw: str | bytes) -> None:
        if self.closed:
            return
        if self._rate_limited():
            self.send({"type": "error", "code": "rate_limited"})
            return
        try:
            cmd = parse_command(raw)
        except ProtocolError as exc:
            self.send({"type": "error", "code": exc.code, "detail": exc.detail})
            return
        try:
            if cmd.name == "heartbeat":
                self.ctrl.heartbeat(self.client_id)             # silencieux : 2 par seconde en émission
            elif cmd.name == "get_state":
                self._result(cmd.id, True, state=self._state())
            elif cmd.name == "toggle":
                snapshot = await self.ctrl.toggle(self.client_id)
                self._result(cmd.id, True, ptt=snapshot.to_dict())
            elif cmd.name == "stop":
                await self.ctrl.force_rx("stop", by=self.client_id)
                self._result(cmd.id, True, ptt=self.ctrl.snapshot().to_dict())
            elif cmd.name == "set_frequency":
                await self.ctrl.set_frequency(cmd.params["hz"])
                self._result(cmd.id, True)
            elif cmd.name == "set_mode":
                await self.ctrl.set_mode(cmd.params["mode"], cmd.params["passband"])
                self._result(cmd.id, True)
            elif cmd.name == "set_squelch":
                await self.link.set_squelch(cmd.params["value"])                # réception seulement : aucun effet sur l'émission
                self._result(cmd.id, True)
            elif cmd.name == "set_function":
                await self.ctrl.set_function(cmd.params["name"], cmd.params["on"])     # refusé pendant l'émission
                self._result(cmd.id, True)
            elif cmd.name == "set_level":
                await self.ctrl.set_level(cmd.params["name"], cmd.params["value"])
                self._result(cmd.id, True)
            elif cmd.name == "spectrum_set":
                if self.spectrum is None:
                    self._result(cmd.id, False, reason="spectrum_unavailable")
                else:                                    # aucun effet sur l'émission ; refusé hors réception par le service
                    ok, reason = await self.spectrum.set_setting(cmd.params["name"], cmd.params["value"])
                    extra = {} if ok else {"reason": reason}
                    self._result(cmd.id, ok, settings=self.spectrum.snapshot().get("settings", {}), **extra)
            elif cmd.name.startswith("memory_"):
                await self._memory_command(cmd)
            elif cmd.name.startswith("layout_"):
                self._layout_command(cmd)
        except Refused as exc:
            self._result(cmd.id, False, reason=exc.reason, detail=str(exc))
        except ValueError as exc:
            self._result(cmd.id, False, reason="invalid", detail=str(exc))
        except RigError as exc:
            self._result(cmd.id, False, reason="rig_error", detail=str(exc))
        except CatConnectionError as exc:
            self._result(cmd.id, False, reason="cat_down", detail=str(exc))
