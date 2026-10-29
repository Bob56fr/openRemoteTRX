# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
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

from ... import __version__
from ...layout import LayoutInvalid, LayoutStorageError, LayoutStore, validate_profile
from ..bugreports import ReportRefused
from ..cat import Capabilities, CatConnectionError, CatLink, RigError
from ..memories import MemoryStore, MemoryStoreError
from ..safety import PttController, Refused
from .protocol import BASE_FEATURES, PROTOCOL_VERSION, ProtocolError, parse_command

log = logging.getLogger(__name__)


def build_state(link: CatLink, ctrl: PttController, pipeline=None, spectrum=None) -> dict:
    """`spectrum` : SpectrumService (facultatif) ; seul son état (state, code, message) part vers les clients."""
    rig, ptt = link.state, ctrl.snapshot()
    remaining = None if ptt.tot_remaining_s is None else round(ptt.tot_remaining_s, 1)
    local_left = None if ptt.local_remaining_s is None else round(ptt.local_remaining_s, 1)
    return {
        "type": "state",
        "ptt": {"state": ptt.state, "owner": ptt.owner, "tot_remaining_s": remaining,
                "tot_warning": ptt.tot_warning, "last_cut_reason": ptt.last_cut_reason, "fault": ptt.fault,
                # poste utilisé sur place et température : bandeaux et « Reprendre la main » de la page
                "local_remaining_s": local_left, "local_reason": ptt.local_reason, "local_tx": ptt.local_tx,
                "temp_alert": ptt.temp_alert, "temp_c": ptt.temp_c},
        "rig": {"connected": rig.connected, "frequency_hz": rig.frequency_hz, "mode": rig.mode,
                "passband_hz": rig.passband_hz, "strength_db": rig.strength_db,
                "functions": dict(rig.functions), "levels": dict(rig.levels),
                # split (fréquence d'émission = autre VFO) et décalages du clarifieur (RIT, XIT = ΔTX) ; None = inconnu
                "split": rig.split, "tx_frequency_hz": rig.tx_frequency_hz, "offsets": dict(rig.offsets)},
        "audio": pipeline.stats() if pipeline is not None else {},
        "clients": ctrl.clients,
        "spectrum": spectrum.snapshot() if spectrum is not None else {"state": "off", "code": "", "message": ""},
    }


class ControlSession:
    def __init__(self, client_id: str, ctrl: PttController, link: CatLink, pipeline,
                 capabilities: Capabilities | None, send: Callable[[dict], None], *,
                 max_msgs_per_s: int = 30, state_interval_s: float = 0.25,
                 clock: Callable[[], float] = time.monotonic, memories: MemoryStore | None = None,
                 layouts: LayoutStore | None = None, spectrum=None,
                 spectrum_watch: Callable[[bool], None] | None = None, reports=None):
        self.client_id, self.ctrl, self.link, self.pipeline = client_id, ctrl, link, pipeline
        self.spectrum = spectrum
        self.spectrum_watch = spectrum_watch     # vue HF ouverte/fermée chez ce client (SpectrumFanout.watch)
        self.reports = reports                   # ReportStore : rapports de problème de la page (bugreports.py)
        self.hf_view = False                     # vue HF affichée chez ce client (dernier spectrum_watch accepté)
        self.on_hf_view: Callable[["ControlSession", bool], None] | None = None   # ModuleBridge.replay (gateway/main)
        self.capabilities, self._send = capabilities, send
        self.memories = memories
        self.layouts = layouts
        self._memories_listener = lambda items: self.send({"type": "memories", "items": items})
        self._beeps_listener = lambda settings: self.send({"type": "beeps", "settings": settings})
        self._selcall_listener = lambda status: self.send({"type": "selcall", "status": status.to_dict()})
        receiver = getattr(pipeline, "selcall", None)
        self.selcall = getattr(receiver, "store", None)   # SELCALL (selcall/receiver.py) ou None : [selcall] enabled = false
        tail = getattr(ctrl, "tail", None)
        self.beeps = getattr(tail, "store", None)  # réglages des bips de fin (gateway/audio/beeps.py) ou None
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
                   "version": __version__,                          # affichée par la page (clients authentifiés seulement)
                   "capabilities": self.capabilities.to_dict() if self.capabilities else None,
                   "tx_modes": list(self.ctrl.config.rig.tx_modes),
                   "max_power_w": self.ctrl.config.rig.max_power_w,
                   "memories": self.memories.list() if self.memories else [],
                   "layouts": self.layouts is not None,
                   "spectrum": self.spectrum.capability() if self.spectrum is not None else None,
                   "beeps": self.beeps.config.to_dict() if self.beeps is not None else None,
                   "selcall": self.selcall.status.to_dict() if self.selcall is not None else None,
                   "features": self.features()})
        # « spectrum » : canal du même nom ; « layouts » : mises en page personnalisées (layout_get)
        if self.beeps is not None:
            self.beeps.add_listener(self._beeps_listener)             # réglé depuis un autre téléphone : affiché ici
        if self.selcall is not None:
            self.selcall.add_listener(self._selcall_listener)         # armé ailleurs, ou appel reçu : affiché ici
        if self.memories:
            self.memories.add_listener(self._memories_listener)       # une mémoire créée ailleurs apparaît ici aussitôt
        self.send(self._state())
        self._state_task = asyncio.get_running_loop().create_task(self._state_loop())

    def features(self) -> list[str]:
        """hello.features : ce que CETTE station offre. Un client affiche une fonction parce qu'elle est annoncée ici,
        jamais d'après un numéro de version (docs/protocole.md)."""
        offered = {"memories": self.memories is not None, "layouts": self.layouts is not None,
                   "spectrum": self.spectrum is not None and self.spectrum.capability() is not None,
                   "beeps": self.beeps is not None, "bug_report": self.reports is not None,
                   "selcall": self.selcall is not None,
                   "selcall_send": self.selcall is not None and getattr(self.ctrl, "tail", None) is not None,
                   "selcall_calibrate": self.selcall is not None and getattr(self.ctrl, "tail", None) is not None}
        return [*BASE_FEATURES, *(name for name, on in offered.items() if on)]

    def _state(self) -> dict:
        return build_state(self.link, self.ctrl, self.pipeline, self.spectrum)

    async def close(self) -> None:
        """Idempotent. Désenregistre le client : coupe l'émission s'il en était propriétaire."""
        if self.closed:
            return
        self.closed = True
        if self.memories:
            self.memories.remove_listener(self._memories_listener)
        if self.beeps is not None:
            self.beeps.remove_listener(self._beeps_listener)
        if self.selcall is not None:
            self.selcall.remove_listener(self._selcall_listener)    # la déconnexion ne change PAS l'état du SELCALL
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

    async def _selcall_send(self, cmd) -> None:
        """Appel SELCALL manuel : ÉMISSION par ce client (mêmes vérifications que toggle), code armé, trame N fois."""
        tail = getattr(self.ctrl, "tail", None)
        if self.selcall is None or tail is None:
            self._result(cmd.id, False, reason="selcall_unavailable")
            return
        status = self.selcall.status
        if status.state == "disabled" or not status.code:
            self._result(cmd.id, False, reason="selcall_not_armed")
            return
        from ...selcall import protocol as sp
        sc = self.ctrl.config.selcall
        code, repeat, gap = status.code, sc.manual_repeat, sc.manual_gap_ms / 1000
        duration = repeat * sp.duration_s(code) + (repeat - 1) * gap
        store = self.selcall

        async def sequence() -> None:
            try:
                await tail.play_selcall_call(code, repeat, gap, progress=lambda k, n: store.set_sending(f"{k}/{n}"))
            finally:
                store.set_sending("")

        log.warning("SELCALL : appel manuel %s (%d fois) demandé par %s", code, repeat, self.client_id)
        snapshot = await self.ctrl.send_selcall(self.client_id, sequence, duration)    # Refused : refus comme toggle
        self._result(cmd.id, True, ptt=snapshot.to_dict())

    async def _selcall_calibrate(self, cmd) -> None:
        """Réglage automatique du niveau de la trame d'après l'ALC : ÉMISSION d'un ton par paliers (mêmes vérifications que
        toggle, micro du client fermé, toute coupure l'interrompt) ; niveau retenu enregistré et annoncé à tous."""
        tail = getattr(self.ctrl, "tail", None)
        if self.selcall is None or tail is None:
            self._result(cmd.id, False, reason="selcall_unavailable")
            return
        from ...selcall import calibrate
        store, link = self.selcall, self.link

        def read_alc():
            value = link.state.levels.get("ALC")
            return float(value) if isinstance(value, (int, float)) else None

        async def step(level, seconds):
            await tail.play_tone(calibrate.TONE_HZ, level, seconds)

        async def sequence() -> None:
            try:
                level, why = await calibrate.run(step, read_alc, store.set_sending)
                if level is not None:
                    store.set_options(tx_level_dbfs=level)
                log.warning("SELCALL : réglage automatique : %s", why)
                store.set_calibration(why)
            finally:
                store.set_sending("")

        store.set_calibration("")
        log.warning("SELCALL : réglage automatique du niveau demandé par %s", self.client_id)
        snapshot = await self.ctrl.send_selcall(self.client_id, sequence, calibrate.duration_s())
        self._result(cmd.id, True, ptt=snapshot.to_dict())

    def _selcall_command(self, cmd) -> None:
        """SELCALL : n'agit que sur le son reçu par les clients (squelch), jamais sur le poste ni sur l'émission."""
        if self.selcall is None:
            self._result(cmd.id, False, reason="selcall_unavailable")
            return
        if cmd.name == "selcall_activate":
            status = self.selcall.activate(cmd.params["code"])
        elif cmd.name == "selcall_rearm":
            status = self.selcall.rearm()
        elif cmd.name == "selcall_deactivate":
            status = self.selcall.deactivate()
        else:
            status = self.selcall.set_options(**cmd.params)
        log.info("SELCALL : %s par %s -> %s", cmd.name, self.client_id, status.state)
        self._result(cmd.id, True, status=status.to_dict())

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
            elif cmd.name == "local_release":                    # ne commande rien au poste : lève seulement l'attente
                self._result(cmd.id, True, ptt=self.ctrl.release_local(self.client_id).to_dict())
            elif cmd.name == "bug_report":                       # aucun effet sur le poste : un fichier texte sur la station
                if self.reports is None:
                    self._result(cmd.id, False, reason="reports_unavailable")
                else:
                    try:
                        name = self.reports.save(self.client_id, cmd.params["text"])   # compte de la SESSION
                    except ReportRefused as exc:
                        self._result(cmd.id, False, reason=exc.reason)
                    else:
                        log.info("rapport de problème reçu de %s : %s", self.client_id, name)
                        self._result(cmd.id, True, name=name)
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
            elif cmd.name == "set_offset":
                await self.ctrl.set_offset(cmd.params["name"], cmd.params["hz"])          # refusé pendant l'émission
                self._result(cmd.id, True)
            elif cmd.name == "spectrum_set":
                if self.spectrum is None:
                    self._result(cmd.id, False, reason="spectrum_unavailable")
                else:                                    # aucun effet sur l'émission ; refusé hors réception par le service
                    ok, reason = await self.spectrum.set_setting(cmd.params["name"], cmd.params["value"])
                    extra = {} if ok else {"reason": reason}
                    self._result(cmd.id, ok, settings=self.spectrum.snapshot().get("settings", {}), **extra)
            elif cmd.name == "beeps_set":
                if self.beeps is None:
                    self._result(cmd.id, False, reason="beeps_unavailable")
                else:                                    # n'agit sur le poste qu'à la PROCHAINE fin d'émission
                    try:
                        config = self.beeps.update(cmd.params)
                    except OSError as exc:
                        log.error("réglages des bips non enregistrés : %s", exc)
                        self._result(cmd.id, False, reason="beeps_storage_error")
                    else:
                        log.info("bips réglés par %s : %s", self.client_id, cmd.params)
                        self._result(cmd.id, True, settings=config.to_dict())
            elif cmd.name == "selcall_send":
                await self._selcall_send(cmd)
            elif cmd.name == "selcall_calibrate":
                await self._selcall_calibrate(cmd)
            elif cmd.name.startswith("selcall_"):
                self._selcall_command(cmd)
            elif cmd.name == "spectrum_watch":
                if self.spectrum is None or self.spectrum_watch is None:
                    self._result(cmd.id, False, reason="spectrum_unavailable")
                else:                                    # n'agit que sur l'envoi des balayages à CE client
                    self.spectrum_watch(cmd.params["on"])
                    self.hf_view = cmd.params["on"]      # spots du cluster : envoyés seulement vue HF ouverte
                    self._result(cmd.id, True, on=cmd.params["on"])
                    if self.on_hf_view is not None:
                        try:
                            self.on_hf_view(self, self.hf_view)
                        except Exception:                # un module ne doit jamais gêner la session
                            log.exception("rejeu des messages des modules impossible")
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
