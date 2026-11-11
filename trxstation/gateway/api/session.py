# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""ControlSession : la conversation d'UN client authentifié avec la passerelle.

Le client est déjà authentifié (jeton vérifié avant la création de la connexion). La session :
  * enregistre le client auprès du PttController, et le désenregistre à la fermeture (ce qui
    COUPE l'émission si ce client la détenait : perte de connexion = retour RX) ; un VISITEUR (rôle listener,
    access.py) n'y est jamais enregistré et ne peut envoyer que get_state et spectrum_watch ;
  * traite les commandes (toggle, stop, heartbeat, fréquence, mode) ;
  * diffuse l'état toutes les 0,25 s (changement, ou au moins chaque seconde) ;
  * limite le débit des messages.
Rien ici ne dépend d'un transport : `send` est une fonction fournie par la couche réseau.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable

from ... import __version__
from ...hostinfo import hamlib_version, host_details, shared_monitor
from ...layout import LayoutInvalid, LayoutStorageError, LayoutStore, validate_profile
from ..bugreports import ReportRefused
from ..cat import Capabilities, CatConnectionError, CatLink, RigError
from ..memories import MemoryStore, MemoryStoreError
from ..voice_profiles import VoiceProfileError
from ..safety import PttController, Refused
from .access import LISTENER, LISTENER_COMMANDS, MESSAGES, OPERATOR
from ...modules.bus import CommandRefused
from .protocol import BASE_FEATURES, MAX_MESSAGE_BYTES, PROTOCOL_VERSION, Command, ProtocolError, parse_command

log = logging.getLogger(__name__)


# Commandes qui ne disent pas qu'un opérateur est actif (présence de groupe) : battement, état, consultations.
PASSIVE_COMMANDS = frozenset({"heartbeat", "get_state", "layout_get", "spectrum_watch", "host_info", "voice_profiles",
                              "swr_last", "swr_plan", "breizh_log"})
_hamlib_version: str | None = None                # version de Hamlib (synthèse host_info), lue une fois
FORBIDDEN_LIMIT, FORBIDDEN_WINDOW_S = 20, 60.0
# Pendant une mesure de TOS, aucun client ne change les réglages du poste (la mesure les a pris et les remettra) ;
# STOP et toute coupure restent TOUJOURS possibles (ils arrêtent la mesure).
SWR_BLOCKED = frozenset({"set_frequency", "set_mode", "set_function", "set_level", "set_offset", "memory_recall",
                         "spectrum_set", "selcall_send", "selcall_calibrate", "local_release"})    # visiteur : au-delà, connexion fermée et alerte


def build_state(link: CatLink, ctrl: PttController, pipeline=None, spectrum=None, access=None,
                role: str = OPERATOR, net: dict | None = None) -> dict:
    """`spectrum` : SpectrumService (facultatif) ; seul son état (state, code, message) part vers les clients.
    `access` (AccessControl, facultatif) : présence ; pour un visiteur, pseudos à la place des identifiants."""
    rig, ptt = link.state, ctrl.snapshot()
    listener = role == LISTENER
    remaining = None if ptt.tot_remaining_s is None else round(ptt.tot_remaining_s, 1)
    local_left = None if ptt.local_remaining_s is None else round(ptt.local_remaining_s, 1)
    return {
        "type": "state",
        "ptt": {"state": ptt.state, "owner": access.public_owner(ptt.owner) if listener and access else ptt.owner,
                "tot_remaining_s": remaining,
                "tot_warning": ptt.tot_warning, "last_cut_reason": ptt.last_cut_reason, "fault": ptt.fault,
                # poste utilisé sur place et température : bandeaux et « Reprendre la main » de la page
                "local_remaining_s": local_left, "local_reason": ptt.local_reason, "local_tx": ptt.local_tx,
                "temp_alert": ptt.temp_alert, "temp_c": ptt.temp_c},
        "rig": {"connected": rig.connected, "frequency_hz": rig.frequency_hz, "mode": rig.mode,
                "passband_hz": rig.passband_hz, "strength_db": rig.strength_db,
                "functions": dict(rig.functions), "levels": dict(rig.levels),
                # split (fréquence d'émission = autre VFO) et décalages du clarifieur (RIT, XIT = ΔTX) ; None = inconnu
                "split": rig.split, "tx_frequency_hz": rig.tx_frequency_hz, "offsets": dict(rig.offsets),
                "vfo": rig.vfo},
        "audio": pipeline.stats() if pipeline is not None else {},
        "clients": [] if listener else ctrl.clients,             # identifiants : jamais vers un visiteur
        "spectrum": spectrum.snapshot() if spectrum is not None else {"state": "off", "code": "", "message": ""},
        "presence": access.presence(role) if access is not None else None,
        # santé de la machine de la station (petit bargraph) : opérateurs seulement, jamais vers un visiteur
        "host": None if listener else shared_monitor().summary(),
        # Breizh Audio Box : opérateurs seulement, et seulement si la station l'emploie ([breizh] enabled)
        **({} if listener or getattr(pipeline, "route", None) is None else {"breizh": pipeline.route.snapshot()}),
        # sonde de qualité réseau : la liaison de CE client (docs/netprobe-cahier-des-charges.md), si la station l'a
        **({} if net is None else {"net": net}),
        # FreeDV en réception ([freedv] enabled) : mode, synchro, SNR, indicatifs ; visiteurs compris
        **({} if getattr(pipeline, "freedv", None) is None else {"freedv": pipeline.freedv.snapshot()}),
    }


class ControlSession:
    def __init__(self, client_id: str, ctrl: PttController, link: CatLink, pipeline,
                 capabilities: Capabilities | None, send: Callable[[dict], None], *,
                 max_msgs_per_s: int = 30, state_interval_s: float = 0.25,
                 clock: Callable[[], float] = time.monotonic, memories: MemoryStore | None = None,
                 layouts: LayoutStore | None = None, spectrum=None,
                 spectrum_watch: Callable[[bool], None] | None = None, reports=None,
                 role: str = OPERATOR, access=None, disconnect: Callable[[str], None] | None = None,
                 alert: Callable[[str, str], None] | None = None,
                 kick_listener: Callable[[str], bool] | None = None, voices=None, swr=None,
                 netprobe=None, device: str = "", agent: str = "", source: str = ""):
        self.client_id, self.ctrl, self.link, self.pipeline = client_id, ctrl, link, pipeline
        self.role = LISTENER if role == LISTENER else OPERATOR
        self.access = access                     # AccessControl (access.py) ou None : tout client est opérateur
        self.disconnect = disconnect             # (motif) -> None : la couche réseau ferme CETTE connexion
        self.alert = alert                       # (titre, message) -> None : alerte ntfy (refus répétés d'un visiteur)
        self.kick_listener = kick_listener       # (compte) -> bool : « Déconnecter » un visiteur (opérateur seulement)
        self._forbidden: deque[float] = deque()
        self._forbidden_logged = 0.0
        self.spectrum = spectrum
        self.spectrum_watch = spectrum_watch     # vue HF ouverte/fermée chez ce client (SpectrumFanout.watch)
        self.reports = reports                   # ReportStore : rapports de problème de la page (bugreports.py)
        self.hf_view = False                     # vue HF affichée chez ce client (dernier spectrum_watch accepté)
        self.on_hf_view: Callable[["ControlSession", bool], None] | None = None   # ModuleBridge.replay (gateway/main)
        # Présence de groupe : commande relayée au module « presence » (ModuleBridge.call), activité de l'opérateur
        # (ModuleBridge.operator_activity) ; posés par gateway/main, None sans le module. Jamais pour un visiteur.
        self.friends_call: Callable[[dict], Awaitable] | None = None
        self.on_operator_activity: Callable[[], None] | None = None
        self.capabilities, self._send = capabilities, send
        self.memories = memories
        self.layouts = layouts
        self.voices = None if role == LISTENER else voices   # VoiceProfileStore : profils d'égaliseur du COMPTE (opérateurs)
        self.swr = None if role == LISTENER else swr         # SwrRunner : mesure de TOS (opérateurs seulement)
        self._memories_listener = lambda items: self.send({"type": "memories", "items": items})
        self._beeps_listener = lambda settings: self.send({"type": "beeps", "settings": settings})
        self._selcall_listener = lambda status: self.send({"type": "selcall", "status": status.to_dict()})
        self._breizh_listener = lambda entry: self.send({"type": "breizh_event", **entry})
        self._freedv_listener = lambda event: self.send({"type": "freedv_event", **event})
        self.freedv = getattr(pipeline, "freedv", None)   # FreedvService (freedv/service.py) ou None : [freedv] enabled = false
        self.breizh = None if role == LISTENER else getattr(pipeline, "route", None)   # TxRoute ou None
        receiver = getattr(pipeline, "selcall", None)
        self.selcall = getattr(receiver, "store", None)   # SELCALL (selcall/receiver.py) ou None : [selcall] enabled = false
        tail = getattr(ctrl, "tail", None)
        self.beeps = getattr(tail, "store", None)  # réglages des bips de fin (gateway/audio/beeps.py) ou None
        if self.role == LISTENER:
            self.beeps = None                    # réglage de la station : rien vers un visiteur
            self.selcall = None                  # code de groupe : jamais vers un visiteur (hello, messages, fonctions) ;
                                                 # le squelch s'applique quand même au son qu'il reçoit
        self.netprobe = netprobe                 # NetProbeHub (netprobe/probe.py) ou None : [netprobe] enabled = false
        self.probe = None                        # ClientProbe de CETTE connexion (ouverte au démarrage)
        self._net_export: tuple[str, bytes] | None = None   # dernier export fabriqué (envoyé par morceaux)
        self.device, self.agent, self.source = device, agent, source   # appareil (aléatoire), « page Windows »..., adresse
        self.max_msgs_per_s, self.state_interval_s, self.clock = max_msgs_per_s, state_interval_s, clock
        self._times: deque[float] = deque()
        self._state_task: asyncio.Task | None = None
        self.closed = False

    def send(self, message: dict) -> None:
        try:
            self._send(message)
        except Exception:
            log.exception("envoi vers %s impossible", self.client_id)

    @property
    def listener(self) -> bool:
        return self.role == LISTENER

    async def start(self) -> None:
        if not self.listener:
            self.ctrl.connect_client(self.client_id)     # un visiteur ne peut JAMAIS devenir propriétaire de l'émission
        if self.access is not None:
            self.access.opened(self.client_id)
        self.send({"type": "hello", "protocol": PROTOCOL_VERSION, "client_id": self.client_id,
                   "role": self.role,
                   "pseudo": self.access.pseudo(self.client_id) if self.access is not None else "",
                   "version": __version__,                          # affichée par la page (clients authentifiés seulement)
                   "capabilities": self.capabilities.to_dict() if self.capabilities else None,
                   "tx_modes": list(self.ctrl.config.rig.tx_modes),
                   "max_power_w": self.ctrl.config.rig.max_power_w,
                   "memories": self.memories.list() if self.memories else [],
                   "layouts": self.layouts is not None,
                   "spectrum": self.spectrum.capability() if self.spectrum is not None else None,
                   "beeps": self.beeps.config.to_dict() if self.beeps is not None else None,
                   "selcall": self.selcall.status.to_dict() if self.selcall is not None else None,
                   "freedv": self.freedv.snapshot() if self.freedv is not None else None,
                   # rediffusion d'un enregistrement (application) : accordée sur la station, durée bornée au TOT - 5 s
                   "replay": {"max_s": max(0, int(self.ctrl.limits.tot_s) - 5)} if self._replay_allowed() else None,
                   "features": self.features()})
        # « spectrum » : canal du même nom ; « layouts » : mises en page personnalisées (layout_get)
        if self.beeps is not None:
            self.beeps.add_listener(self._beeps_listener)             # réglé depuis un autre téléphone : affiché ici
        if self.selcall is not None:
            self.selcall.add_listener(self._selcall_listener)         # armé ailleurs, ou appel reçu : affiché ici
        if self.memories:
            self.memories.add_listener(self._memories_listener)       # une mémoire créée ailleurs apparaît ici aussitôt
        if self.breizh is not None:
            self.breizh.store.add_listener(self._breizh_listener)     # repli, retour, refus : prévenir l'opérateur
        if self.freedv is not None:
            self.freedv.add_listener(self._freedv_listener)           # indicatifs, fins de séquence, abandon : tous
        if self.netprobe is not None:
            try:
                self.probe = self.netprobe.open(self.client_id, self.role, self.device, self.agent, self.source, self.send)
            except Exception:                            # la sonde ne doit jamais empêcher une connexion
                log.exception("sonde réseau de %s non ouverte", self.client_id)
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
                   "selcall_calibrate": self.selcall is not None and getattr(self.ctrl, "tail", None) is not None,
                   "presence": self.access is not None,
                   "host": not self.listener,
                   "voice_profiles": self.voices is not None,
                   "swr": self.swr is not None and self.ctrl.config.swr.enabled,
                   "replay": self._replay_allowed(),
                   "breizh": self.breizh is not None,
                   "netprobe": self.netprobe is not None,
                   "friends": self.friends_call is not None and not self.listener,
                   "freedv": self.freedv is not None}
        return [*BASE_FEATURES, *(name for name, on in offered.items() if on)]

    def _replay_allowed(self) -> bool:
        return not self.listener and self.ctrl.config.safety.allow_replay is True

    def _state(self) -> dict:
        net = None
        if self.probe is not None:
            try:
                net = self.probe.state()
            except Exception:
                log.exception("état de la sonde réseau de %s", self.client_id)
        return build_state(self.link, self.ctrl, self.pipeline, self.spectrum, self.access, self.role, net)

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
        if self.breizh is not None:
            self.breizh.store.remove_listener(self._breizh_listener)
        if self.freedv is not None:
            self.freedv.remove_listener(self._freedv_listener)
        if self.probe is not None:
            try:
                self.netprobe.close(self.probe)
            except Exception:
                log.exception("sonde réseau de %s non fermée", self.client_id)
        if self._state_task is not None:
            self._state_task.cancel()
            await asyncio.gather(self._state_task, return_exceptions=True)
        if not self.listener:
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

    async def _swr_command(self, cmd) -> None:
        """Mesure de TOS (docs/tos-cahier-des-charges.md). swr_start : prises d'émission NORMALES de CE client, une par
        point (swr/runner.py) ; la progression arrive par les messages « swr » envoyés à CE client seulement."""
        from ...swr.plan import PlanError
        if self.swr is None or not self.ctrl.config.swr.enabled:
            self._result(cmd.id, False, reason="swr_unavailable")
            return
        p = cmd.params
        if cmd.name == "swr_plan":
            try:
                plan = self.swr.make_plan(p["low_hz"], p["high_hz"], p["points"], p["power_pct"])
            except PlanError as exc:
                self._result(cmd.id, False, reason=exc.code, detail=str(exc))
            else:
                self._result(cmd.id, True, plan=plan, choices=self.swr.store.choices(self.client_id))
        elif cmd.name == "swr_start":
            plan = await self.swr.start(self.client_id, p["low_hz"], p["high_hz"], p["points"], p["power_pct"], self.send)
            log.warning("mesure de TOS lancée par %s : %d points, %s %% en %s", self.client_id, len(plan["points"]),
                        plan["power_pct"], plan["fm_mode"])
            self._result(cmd.id, True, plan=plan)
        elif cmd.name == "swr_cancel":
            await self.swr.cancel(self.client_id)
            self._result(cmd.id, True)
        else:                                            # swr_last
            self._result(cmd.id, True, last=self.swr.store.last(), choices=self.swr.store.choices(self.client_id))

    async def _freedv_set(self, cmd) -> None:
        """Mode FreeDV de la station (réception) : n'agit JAMAIS sur le poste ; refusé pendant toute émission (de la
        station ou au micro du poste), comme le cahier FreeDV le demande pour l'entrée et la sortie du mode."""
        from ...freedv.service import FreedvUnavailable
        if self.freedv is None:
            self._result(cmd.id, False, reason="freedv_unavailable")
            return
        if self.ctrl.snapshot().state != "RX" or bool(getattr(self.link.state, "ptt", False)):
            self._result(cmd.id, False, reason="freedv_tx", detail="émission en cours : mode FreeDV changé après")
            return
        try:
            await self.freedv.set_on(cmd.params["on"])
        except FreedvUnavailable as exc:
            self._result(cmd.id, False, reason=exc.reason, detail=exc.detail)
            return
        log.info("mode FreeDV %s par %s", "choisi" if cmd.params["on"] else "quitté", self.client_id)
        self._result(cmd.id, True, freedv=self.freedv.snapshot())

    def _breizh_command(self, cmd) -> None:
        """Breizh Audio Box : réglages de la route du micro, jamais d'effet sur le PTT ; pris à la PROCHAINE émission."""
        route = self.breizh
        if route is None:
            self._result(cmd.id, False, reason="breizh_unavailable")
            return
        if cmd.name == "breizh_log":
            self._result(cmd.id, True, entries=route.store.last(50))
        elif cmd.name == "breizh_reactivate":
            pending = route.link.reactivate()
            log.warning("Breizh : réactivation demandée par %s", self.client_id)
            self._result(cmd.id, True, pending=pending, breizh=route.snapshot())
        else:                                            # breizh_set
            before = route.store.settings.bypass
            try:
                settings = route.store.update(**cmd.params)
            except OSError as exc:
                log.error("réglages de Breizh non enregistrés : %s", exc)
                self._result(cmd.id, False, reason="breizh_storage_error")
                return
            if settings.bypass != before:
                route.store.event("bypass" if settings.bypass else "unbypass",
                                  f"« Direct » {'choisi' if settings.bypass else 'quitté'} par {self.client_id} "
                                  "(à la prochaine émission)")
            self._result(cmd.id, True, breizh=route.snapshot())

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

    def _net_command(self, cmd) -> None:
        """Sonde de qualité réseau. net_ping / net_pong / net_report : sans réponse (fréquents) ; les autres : `result`.
        Toute erreur reste ici : la sonde ne gêne jamais la session ni l'émission."""
        silent = cmd.name in ("net_ping", "net_pong", "net_report")
        if self.probe is None:
            if not silent:
                self._result(cmd.id, False, reason="netprobe_unavailable")
            return
        try:
            if cmd.name == "net_ping":
                self.probe.on_ping(cmd.params)
            elif cmd.name == "net_pong":
                self.probe.on_pong(cmd.params)
            elif cmd.name == "net_report":
                self.probe.on_report(cmd.params["report"])
            elif cmd.name == "net_backlog":
                self.probe.on_backlog(cmd.params["reports"])
                self._result(cmd.id, True, count=len(cmd.params["reports"]))
            elif cmd.name == "net_stats":
                self._result(cmd.id, True, stats=self.netprobe.stats(cmd.params["days"], cmd.params["device"]))
            elif cmd.name == "net_clear":
                self.netprobe.clear(self.client_id)
                self._result(cmd.id, True)
            elif cmd.name == "net_thresholds":
                self._result(cmd.id, True, thresholds=self.netprobe.set_thresholds(cmd.params))
            elif cmd.name == "net_vpn_ignore":
                self.netprobe.vpn.ignore(cmd.params["address"])
                self._result(cmd.id, True)
            elif cmd.name == "net_export":                      # zip anonyme, par morceaux de 36 ko (base64 : 48 ko)
                part = cmd.params["part"]
                if part == 0 or self._net_export is None:
                    self._net_export = self.netprobe.export()
                name, blob = self._net_export
                chunk = 36_000
                parts = max(1, -(-len(blob) // chunk))
                if part >= parts:
                    self._result(cmd.id, False, reason="invalid", detail=f"{parts} morceau(x) seulement")
                else:
                    self._result(cmd.id, True, name=name, part=part, parts=parts, size=len(blob),
                                 data=base64.b64encode(blob[part * chunk:(part + 1) * chunk]).decode("ascii"))
        except Exception:
            log.exception("sonde réseau : commande %s de %s", cmd.name, self.client_id)
            if not silent:
                self._result(cmd.id, False, reason="netprobe_error")

    def bye(self, reason: str, message: str = "") -> None:
        """Dernier message avant que la station ferme cette connexion : le client affiche le motif et ne se
        reconnecte pas tout seul."""
        self.send({"type": "bye", "reason": reason, "message": message or MESSAGES.get(reason, reason)})

    def _forbid(self, name: str, ident) -> None:
        """Commande refusée à un visiteur : réponse, journal limité, fermeture au-delà de 20 refus par minute."""
        now = self.clock()
        self._forbidden.append(now)
        while self._forbidden and now - self._forbidden[0] > FORBIDDEN_WINDOW_S:
            self._forbidden.popleft()
        if now - self._forbidden_logged >= 1.0:
            self._forbidden_logged = now
            log.warning("visiteur %s : commande « %s » refusée (réception seule)", self.client_id, name[:40])
        self._result(ident, False, reason="forbidden", detail="visiteur : réception seule, aucune commande")
        if len(self._forbidden) > FORBIDDEN_LIMIT and self.disconnect is not None:
            log.error("visiteur %s : %d commandes refusées en une minute, connexion fermée", self.client_id, len(self._forbidden))
            if self.alert is not None:
                self.alert("TRX distant : visiteur deconnecte",
                           f"Le visiteur {self.client_id} a envoyé plus de {FORBIDDEN_LIMIT} commandes refusées en une "
                           "minute (client modifié ?) : connexion fermée.")
            self._forbidden.clear()
            self.disconnect("too_many_forbidden")

    async def _friends(self, cmd: Command) -> None:
        """Présence de groupe : relayée au module, qui n'agit JAMAIS sur le poste ; son refus revient tel quel."""
        if self.friends_call is None or self.listener:
            self._result(cmd.id, False, reason="friends_unavailable", detail="présence de groupe non disponible")
            return
        try:
            data = await self.friends_call({"action": cmd.params["action"], "args": cmd.params["args"],
                                            "client": self.client_id})
        except CommandRefused as exc:
            self._result(cmd.id, False, reason=exc.code, detail=str(exc))
            return
        except Exception:
            log.exception("commande friends de %s en erreur", self.client_id)
            self._result(cmd.id, False, reason="friends_error")
            return
        if cmd.params["action"] == "view":
            self._friends_bands(data)
        self._result(cmd.id, True, action=cmd.params["action"], data=data)

    def _friends_bands(self, view) -> None:
        """Vue des amis : `tx_ok` sur chaque fréquence partagée, d'après les [[bands]] de CETTE station (le module ne
        les connaît pas) ; seulement si la station impose ses bandes. Une indication : l'émission reste jugée à l'instant."""
        safety = getattr(self.ctrl.config, "safety", None)
        if not isinstance(view, dict) or not getattr(safety, "enforce_bands", False):
            return
        for group in view.get("groups") or []:
            for member in (group.get("members") or []) if isinstance(group, dict) else []:
                f = member.get("f") if isinstance(member, dict) else None
                if isinstance(f, int) and not isinstance(f, bool):
                    member["tx_ok"] = bool(self.ctrl.config.tx_allowed(f))

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
        if self.listener and len(raw) > MAX_MESSAGE_BYTES:
            self._forbid("(message trop long)", None)            # rapport, mise en page : jamais d'un visiteur
            return
        try:
            cmd = parse_command(raw)
        except ProtocolError as exc:
            self.send({"type": "error", "code": exc.code, "detail": exc.detail})
            return
        if self.listener and cmd.name not in LISTENER_COMMANDS:   # LISTE BLANCHE : tout le reste est refusé
            if cmd.name != "heartbeat":                          # battement : ignoré sans réponse, comme pour un non-propriétaire
                self._forbid(cmd.name, cmd.id)
            return
        if self.swr is not None and self.swr.busy and (
                cmd.name in SWR_BLOCKED or (cmd.name == "toggle" and self.ctrl.snapshot().state == "RX")):
            self._result(cmd.id, False, reason="swr_busy", detail="mesure de TOS en cours : STOP pour l'arrêter")
            return
        if cmd.name.startswith("net_"):
            self._net_command(cmd)                               # sonde réseau : n'agit JAMAIS sur le poste
            return
        if (not self.listener and self.on_operator_activity is not None and cmd.name not in PASSIVE_COMMANDS
                and not (cmd.name == "friends" and cmd.params.get("action") in ("view", "stats"))):
            try:
                self.on_operator_activity()                      # statut « En RX » de la présence de groupe
            except Exception:
                log.exception("activité de l'opérateur non transmise aux modules")
        if cmd.name == "friends":
            await self._friends(cmd)                             # opérateur seulement (liste blanche des visiteurs)
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
            elif cmd.name == "listener_kick":            # opérateur seulement (liste blanche : jamais d'un visiteur)
                ok = self.kick_listener is not None and self.kick_listener(cmd.params["account"])
                if ok:
                    log.warning("visiteur %s déconnecté par l'opérateur %s", cmd.params["account"], self.client_id)
                self._result(cmd.id, ok, **({} if ok else {"reason": "unknown_listener"}))
            elif cmd.name == "listeners_open":          # opérateur : commutateur « Écoute des visiteurs »
                if self.access is None:
                    self._result(cmd.id, False, reason="listeners_unavailable")
                elif cmd.params["on"] and self.access.settings.max_listeners <= 0:
                    self._result(cmd.id, False, reason="listeners_off",
                                 detail="écoute des visiteurs fermée sur la station ([access] max_listeners, TRX Console menu 20)")
                else:
                    self.access.switch.set(cmd.params["on"])
                    log.warning("écoute des visiteurs %s par l'opérateur %s", "OUVERTE" if cmd.params["on"] else "fermée",
                                self.client_id)
                    self._result(cmd.id, True, open=self.access.switch.open)
            elif cmd.name == "host_info":                # opérateur seulement (liste blanche) ; n'agit sur rien
                global _hamlib_version
                if _hamlib_version is None:              # `rigctld --version` : une fois, hors de la boucle (3 s au plus)
                    _hamlib_version = await asyncio.to_thread(hamlib_version, self.ctrl.config.tools.hamlib_dir)
                self._result(cmd.id, True, sections=host_details(shared_monitor(), self.ctrl.config, self.capabilities,
                                                                 _hamlib_version, self.link.state.levels))
            elif cmd.name.startswith("swr_"):
                await self._swr_command(cmd)
            elif cmd.name.startswith("breizh_"):
                self._breizh_command(cmd)
            elif cmd.name == "freedv_set":
                await self._freedv_set(cmd)
            elif cmd.name.startswith("voice_profile"):     # opérateur seulement ; un fichier sur la station, rien vers le poste
                if self.voices is None:
                    self._result(cmd.id, False, reason="voice_profiles_unavailable")
                else:
                    try:
                        if cmd.name == "voice_profile_save":
                            profiles = self.voices.save(self.client_id, cmd.params["name"], cmd.params["settings"])
                        elif cmd.name == "voice_profile_delete":
                            profiles = self.voices.delete(self.client_id, cmd.params["name"])
                        else:
                            profiles = self.voices.list(self.client_id)
                    except VoiceProfileError as exc:
                        log.error("%s", exc)
                        self._result(cmd.id, False, reason="voice_profiles_storage_error")
                    except ValueError as exc:
                        self._result(cmd.id, False, reason="voice_profile_refused", detail=str(exc))
                    else:
                        self._result(cmd.id, True, profiles=profiles)
            elif cmd.name == "listeners_reopen":
                guard = getattr(self.access, "guard", None)
                refusal = guard.reopen() if guard is not None else ""
                if not refusal:
                    log.warning("écoute des visiteurs rouverte par l'opérateur %s", self.client_id)
                self._result(cmd.id, not refusal, **({"reason": "still_overloaded", "detail": refusal} if refusal else {}))
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
