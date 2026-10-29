# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""PttController : le SEUL composant autorisé à commander le PTT.

Principes (voir CLAUDE.md, « Règles de sécurité d'émission ») :
  * Toggle uniquement. L'état (RX / KEYING / TX / UNKEYING) appartient au serveur.
  * Couper est toujours permis et jamais refusé : n'importe quel client peut couper.
  * Prendre l'émission exige : client connu, liaison CAT active, fréquence d'ÉMISSION LUE À
    L'INSTANT dans une bande autorisée (en split : celle de l'autre VFO ; avec le ΔTX / XIT : décalée ;
    un split ou un XIT que le poste déclare mais qui ne se relit pas => refus), poste pas déjà en émission, PTT relisible,
    aucun défaut verrouillé, pas de coupure en cours, pas dans le délai anti-rebond.
  * Pendant l'émission : TOT (avec avertissement), heartbeat du client propriétaire,
    surveillance de la liaison CAT, et relecture périodique du poste (changement de
    fréquence, de split ou de ΔTX, ou PTT retombé => coupure).
  * Température du poste (thermal.py) : au second seuil, émission à distance coupée et refusée.
  * Changer fréquence ou mode est REFUSÉ tant que l'état n'est pas RX confirmé.
  * Le micro (porte audio) est coupé AVANT d'envoyer « PTT off ».
  * Bips de fin (gateway/audio/beeps.py), désactivés par défaut : roger bip quand le PROPRIÉTAIRE relâche
    lui-même ; bip de liaison perdue quand le terminal ne répond plus (battement, connexion fermée) —
    EXCEPTION assumée au retour RX immédiat (décision de l'utilisateur). Seulement depuis TX confirmé,
    jamais pour une autre coupure, durée bornée (TAIL_MAX_WAIT_S) ; toute coupure pendant le bip
    (STOP, autre client, TOT...) l'interrompt net et coupe aussitôt.
  * Le retour en RX est insistant : on réessaie jusqu'à confirmation par relecture.
    L'état n'affiche RX qu'une fois le retour confirmé. Si cela échoue au-delà du
    délai, un défaut `unkey_failed` est verrouillé (effacement manuel, côté Pi) et le
    superviseur autonome prend le relais.
"""
from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from ...config import Config
from ..cat import CatConnectionError, CatLink, CatProtocolError, RigError, RigState
from ..cat.client import RIG_ENAVAIL, RIG_ENIMPL
from .local import LocalPresence
from .thermal import ThermalGuard

log = logging.getLogger(__name__)

_CAT_ERRORS = (CatConnectionError, CatProtocolError, RigError, OSError)
TAIL_MAX_WAIT_S = 1.2      # bip de fin : 0,6 s de son au plus + marge ; au-delà, on coupe quoi qu'il arrive


class PttState(str, enum.Enum):
    RX = "RX"
    KEYING = "KEYING"      # prise d'émission en cours (à afficher comme émission)
    TX = "TX"
    UNKEYING = "UNKEYING"  # coupure demandée, pas encore confirmée (à afficher comme émission)


class Refused(Exception):
    """Une demande est refusée. `reason` est un code stable, utilisable par les clients."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        super().__init__(reason + (f" : {detail}" if detail else ""))


@dataclass
class PttLimits:
    tot_s: float = 90.0
    warn_before_s: float = 10.0
    heartbeat_timeout_s: float = 2.0
    tick_s: float = 0.05               # cadence du chien de garde
    rig_poll_s: float = 1.0            # relecture du poste pendant l'émission
    rekey_cooldown_s: float = 1.0      # anti-rebond RX->TX (relais, double appui)
    unkey_retry_s: float = 0.2
    unkey_deadline_s: float = 5.0      # au-delà : défaut verrouillé + alerte
    require_ptt_readback: bool = True  # exiger un état PTT relisible pour émettre

    def __post_init__(self) -> None:
        if not 0 < self.warn_before_s < self.tot_s:
            raise ValueError("il faut 0 < warn_before_s < tot_s")
        for name in ("heartbeat_timeout_s", "tick_s", "rig_poll_s", "unkey_retry_s", "unkey_deadline_s"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} doit être positif")
        if self.rekey_cooldown_s < 0:
            raise ValueError("rekey_cooldown_s ne peut pas être négatif")

    @classmethod
    def from_config(cls, cfg: Config) -> "PttLimits":
        s = cfg.safety
        return cls(tot_s=float(min(s.tot_s, s.tot_ceiling_s)), warn_before_s=float(s.warn_before_s),
                   heartbeat_timeout_s=s.heartbeat_timeout_ms / 1000)


@dataclass(frozen=True)
class PttSnapshot:
    state: str
    owner: str | None
    tot_remaining_s: float | None
    tot_warning: bool
    last_cut_reason: str
    fault: str
    event: str = ""
    local_remaining_s: float | None = None   # poste utilisé sur place : PTT à distance refusé encore N s (None = libre)
    local_reason: str = ""                   # "tx" (micro du poste), "frequency", "mode"
    local_tx: bool = False                   # émission locale EN COURS (reprise de la main impossible)
    temp_alert: str = ""                     # température du poste : "", "warn" ou "hot" (émission refusée)
    temp_c: float | None = None              # dernière température valable (None : poste sans TEMP_METER)

    def to_dict(self) -> dict:
        return asdict(self)


class PttController:
    def __init__(self, link: CatLink, config: Config, *, limits: PttLimits | None = None,
                 audio_gate: Callable[[bool], None] | None = None, tail=None):
        self.link = link
        self.config = config
        self.limits = limits or PttLimits.from_config(config)
        self._audio_gate = audio_gate or (lambda open_: None)  # appel synchrone et immédiat
        self._state = PttState.RX
        self._owner: str | None = None
        self._clients: set[str] = set()
        self._tx_lock = asyncio.Lock()      # prise d'émission et changements de fréquence/mode s'excluent
        self._epoch = 0                     # incrémenté à chaque coupure : annule les prises en cours
        self._cut_task: asyncio.Task | None = None
        self._watch_task: asyncio.Task | None = None
        self._rig_check: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._tx_started = 0.0
        self._last_heartbeat = 0.0
        self._tx_freq: int | None = None
        self._tx_mode: str | None = None       # mode relu à la prise d'émission (seulement si tx_modes est défini)
        self._tx_plan: tuple | None = None     # (split, fréquence en split, XIT, décalage) relus à la prise d'émission
        self._cooldown_until = 0.0
        self._warning = False
        self._last_cut_reason = ""
        self._fault = ""
        self._starting = True               # tant que le RX de démarrage n'est pas confirmé
        self._closing = False
        self._listeners: list[Callable[[PttSnapshot], None]] = []
        self.tail = tail                    # TailPlayer (bips de fin) ou None : aucun bip
        self._tail_task: asyncio.Task | None = None
        self.local = LocalPresence()        # poste utilisé sur place : PTT à distance refusé (local.py)
        self.thermal = ThermalGuard(config.safety.rig_temp_warn_c, config.safety.rig_temp_cut_c)   # thermal.py

    # ------------------------------------------------------------------ état

    @property
    def starting(self) -> bool:
        return self._starting

    def snapshot(self, event: str = "") -> PttSnapshot:
        remaining = None
        if self._state is PttState.TX:
            remaining = max(0.0, self.limits.tot_s - (time.monotonic() - self._tx_started))
        local_left = self.local.remaining()
        return PttSnapshot(self._state.value, self._owner, remaining, self._warning,
                           self._last_cut_reason, self._fault, event,
                           None if local_left is None else float(math.ceil(local_left)),   # à la seconde : pas plus d'un message d'état par seconde
                           self.local.reason if local_left is not None else "", self.local.transmitting,
                           self.thermal.level, self.thermal.temp_c)

    def add_listener(self, callback: Callable[[PttSnapshot], None]) -> None:
        self._listeners.append(callback)

    def _emit(self, event: str = "") -> None:
        snap = self.snapshot(event)
        for callback in self._listeners:
            try:
                callback(snap)
            except Exception:
                log.exception("écouteur PTT en erreur")

    def _set_state(self, new: PttState, event: str = "") -> None:
        if new is not PttState.RX or self._state is not PttState.RX:
            self.local.station_busy()       # émission de la station : le poste relu juste après ne dit rien de l'opérateur
        self._state = new
        self._emit(event)

    def _cut_running(self) -> bool:
        return self._cut_task is not None and not self._cut_task.done()

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                log.error("tâche de sécurité en erreur : %r", t.exception())
        task.add_done_callback(_done)

    # ------------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        """Démarre la surveillance et force un RX confirmé (toujours RX au démarrage)."""
        self.link.add_listener(self._on_rig_state)
        self._ensure_cut("startup", latch_fault=False)  # réessaie sans limite tant que le CAT est absent

    async def close(self) -> None:
        """Arrêt propre : coupe l'émission (bloque au plus ~unkey_deadline_s) puis arrête les tâches."""
        try:
            await self.force_rx("shutdown")
        finally:
            self._closing = True
            for task in (self._watch_task, self._cut_task, *self._tasks):
                if task is not None and not task.done():
                    task.cancel()

    def clear_fault(self) -> None:
        """Efface un défaut verrouillé. Action de l'opérateur, À NE PAS exposer au smartphone."""
        if self._state is not PttState.RX or self._cut_running():
            raise Refused("not_idle", "effacement impossible tant que le retour RX n'est pas confirmé")
        self._fault = ""
        self._emit("fault_cleared")

    # ------------------------------------------------------------------ clients

    @property
    def clients(self) -> list[str]:
        return sorted(self._clients)

    def connect_client(self, client_id: str) -> None:
        self._clients.add(client_id)

    async def disconnect_client(self, client_id: str) -> None:
        self._clients.discard(client_id)
        if client_id == self._owner and self._state is not PttState.RX:
            await self._end_with_tail("client_disconnected", "link_lost", by=client_id)

    def heartbeat(self, client_id: str) -> bool:
        """Battement du client propriétaire. Les battements des autres clients sont ignorés."""
        if self._state is PttState.TX and client_id == self._owner:
            self._last_heartbeat = time.monotonic()
            return True
        return False

    # ------------------------------------------------------------------ commandes publiques

    async def toggle(self, client_id: str) -> PttSnapshot:
        """RX -> prise d'émission (sous conditions). Autre état -> coupure, toujours acceptée."""
        if self._state is not PttState.RX:
            if self._state is PttState.TX and client_id == self._owner:
                await self._end_with_tail("toggle", "roger", by=client_id)     # relâché par son propriétaire
            else:
                await self.force_rx("toggle", by=client_id)
            return self.snapshot()
        return await self._key(client_id)

    async def force_rx(self, reason: str, by: str | None = None) -> None:
        """Coupure. Jamais refusée, idempotente, envoie toujours « PTT off »."""
        log.warning("coupure PTT : %s (demandée par %s)", reason, by or "interne")
        self._epoch += 1               # annule toute prise d'émission en préparation
        self._stop_tail()              # un bip de fin en cours s'arrête net
        self._audio_gate(False)        # micro coupé AVANT « PTT off »
        if self._state in (PttState.TX, PttState.KEYING):
            self._set_state(PttState.UNKEYING, "cutting")
        task = self._ensure_cut(reason)
        try:
            await asyncio.wait_for(asyncio.shield(task), self.limits.unkey_deadline_s + 0.5)
        except asyncio.TimeoutError:
            pass  # la coupure continue en tâche de fond ; l'état reste UNKEYING

    def _stop_tail(self) -> None:
        task, self._tail_task = self._tail_task, None
        if task is not None and not task.done():
            task.cancel()
            if self.tail is not None:
                self.tail.stop()       # ce qui attendait dans le tampon de lecture est jeté

    async def _end_with_tail(self, reason: str, kind: str, by: str | None = None) -> None:
        """Fin d'émission précédée d'un bip (roger ou liaison perdue) s'il est activé ; sinon coupure immédiate.

        Seulement depuis TX CONFIRMÉ. Micro du client fermé AVANT le bip ; état UNKEYING pendant le bip
        (affiché comme émission) ; borne TAIL_MAX_WAIT_S ; une coupure venue d'ailleurs pendant le bip
        (STOP, TOT, autre client...) l'interrompt et coupe, et on ne recoupe pas derrière elle.
        """
        tail = self.tail
        try:
            wanted = tail is not None and tail.wanted(kind)
        except Exception:
            log.exception("réglages des bips illisibles : coupure sans bip")
            wanted = False
        if self._state is not PttState.TX or not wanted or self._tail_task is not None:
            await self.force_rx(reason, by=by)
            return
        epoch = self._epoch
        log.info("bip %s avant la coupure (%s)", kind, reason)
        self._audio_gate(False)                       # micro du client fermé (et son reste jeté) AVANT le bip
        self._set_state(PttState.UNKEYING, "tail")
        task = asyncio.get_running_loop().create_task(tail.play(kind))
        self._tail_task = task
        try:
            await asyncio.wait_for(asyncio.shield(task), TAIL_MAX_WAIT_S)
        except asyncio.TimeoutError:
            log.error("bip de fin trop long : coupure sans attendre")
        except asyncio.CancelledError:
            if task.cancelled():
                pass                                  # interrompu par une coupure (force_rx)
            else:
                # C'est l'appelant qui est annulé (fermeture de connexion, arrêt d'une tâche) : le chien de
                # garde ne surveille plus (état UNKEYING), la coupure part donc quand même, en tâche à part.
                if self._epoch == epoch:
                    self._spawn(self.force_rx(reason, by=by))
                raise
        except Exception:
            log.exception("bip de fin en erreur : coupure")
        if self._epoch == epoch:                      # personne n'a coupé pendant le bip : on coupe maintenant
            await self.force_rx(reason, by=by)

    async def set_frequency(self, hz: int) -> None:
        async with self._tx_lock:
            self._require_rx_for_tuning()
            self.local.expect("frequency")  # ce changement-là est celui de la station, pas de l'opérateur
            await self.link.set_frequency(hz)

    async def set_mode(self, mode: str, passband_hz: int = 0) -> None:
        async with self._tx_lock:
            self._require_rx_for_tuning()
            self.local.expect("mode")
            await self.link.set_mode(mode, passband_hz)

    async def set_offset(self, which: str, hz: int) -> None:
        """Décalage RIT ou ΔTX / XIT : refusé pendant l'émission (le XIT déplace la fréquence d'émission ; il est revérifié
        à chaque prise d'émission)."""
        async with self._tx_lock:
            self._require_rx_for_tuning()
            await self.link.set_offset(which, hz)

    def release_local(self, client_id: str) -> PttSnapshot:
        """« Reprendre la main » avant la fin de l'attente. Refusé pendant une émission locale. Ne commande rien au poste."""
        if client_id not in self._clients:
            raise Refused("unknown_client")
        if not self.local.release():
            raise Refused("local_tx", "le poste émet en ce moment depuis son micro")
        log.warning("poste utilisé sur place : main reprise à distance par %s", client_id)
        self._emit("local_released")
        return self.snapshot("local_released")

    async def set_function(self, name: str, on: bool) -> None:
        """NR, NB, IP+, compresseur, tuner : refusé pendant l'émission (le tuner pourrait lancer un accord, donc une porteuse)."""
        async with self._tx_lock:
            self._require_rx_for_tuning()
            await self.link.set_function(name, on)

    async def set_level(self, name: str, value) -> None:
        async with self._tx_lock:
            self._require_rx_for_tuning()
            await self.link.set_level(name, value)

    @contextlib.asynccontextmanager
    async def rig_setting(self):
        """Réglage du poste passé par un autre chemin que rigctld (préréglage de filtre par le port B du spectre) :
        même verrou et même refus que fréquence et mode (Refused « tx_active » hors RX confirmé)."""
        async with self._tx_lock:
            self._require_rx_for_tuning()
            yield

    def _require_rx_for_tuning(self) -> None:
        if self._state is not PttState.RX or self._cut_running():
            raise Refused("tx_active", "changement de fréquence, de mode ou de réglage refusé tant que le PTT n'est pas en RX confirmé")

    # ------------------------------------------------------------------ prise d'émission

    def _check_idle(self, client_id: str) -> None:
        if self._fault:
            raise Refused("fault_latched", self._fault)
        if self._starting:
            raise Refused("starting", "retour RX de démarrage non confirmé")
        if self._state is not PttState.RX or self._cut_running():
            raise Refused("not_idle")
        if client_id not in self._clients:
            raise Refused("unknown_client")
        if self.config.safety.enforce_bands and not self.config.bands:
            raise Refused("tx_disabled", "aucune bande autorisée dans station.toml")
        if not self.link.state.connected:
            raise Refused("cat_down")
        if self.local.active():
            left = self.local.remaining()
            raise Refused("local_active", f"poste utilisé sur place, encore {left or 0:.0f} s")
        if self.thermal.hot:
            raise Refused("rig_hot", f"poste à {self.thermal.temp_c:.0f} °C : émission reprise sous {self.thermal.warn_c:.0f} °C")
        if time.monotonic() < self._cooldown_until:
            raise Refused("cooldown")

    async def _key(self, client_id: str) -> PttSnapshot:
        async with self._tx_lock:
            epoch = self._epoch
            self._check_idle(client_id)
            client = self.link.client
            try:
                freq = await client.get_frequency()
            except _CAT_ERRORS as exc:
                raise Refused("cat_error", str(exc)) from exc
            try:
                keyed = await client.get_ptt()
            except RigError as exc:
                if self.limits.require_ptt_readback:
                    raise Refused("ptt_unreadable", str(exc)) from exc
                keyed = False
            except _CAT_ERRORS as exc:
                raise Refused("cat_error", str(exc)) from exc

            allowed_modes = self.config.rig.tx_modes
            mode = None
            if allowed_modes:                      # ex. Icom : l'audio USB n'existe qu'en modes données ; sinon le poste module son micro
                try:
                    mode, _ = await client.get_mode()
                except _CAT_ERRORS as exc:
                    raise Refused("cat_error", f"mode illisible : {exc}") from exc

            tx_freq, plan = await self._transmit_plan(client, freq)

            if self._epoch != epoch:
                raise Refused("cancelled")
            if keyed:
                raise Refused("rig_already_tx")
            if allowed_modes and mode not in allowed_modes:
                raise Refused("mode_not_allowed", f"{mode} (autorisés : {', '.join(allowed_modes)})")
            if self.config.safety.enforce_bands and not self.config.tx_allowed(tx_freq):
                why = " (émission en split)" if plan[0] else ""
                why += f" (ΔTX {plan[3]:+d} Hz)" if plan[2] else ""
                raise Refused("out_of_band", f"{tx_freq / 1e6:.4f} MHz{why}")

            # Aucune attente entre la dernière vérification d'`epoch` et l'écriture.
            self._tx_freq = freq
            self._tx_mode = mode
            self._tx_plan = plan
            self._owner = client_id
            self._set_state(PttState.KEYING, "keying")
            try:
                await client.write_ptt(True)
            except _CAT_ERRORS as exc:
                await self.force_rx("ptt_write_failed")  # a-t-il émis ? on ne sait pas : on coupe
                raise Refused("ptt_write_failed", str(exc)) from exc
            if self._epoch != epoch:
                raise Refused("cancelled")                # une coupure est déjà en cours
            if self.limits.require_ptt_readback:
                try:
                    confirmed = await client.get_ptt()
                except _CAT_ERRORS:
                    confirmed = False
                if self._epoch != epoch:
                    raise Refused("cancelled")
                if not confirmed:
                    await self.force_rx("rig_did_not_key")
                    raise Refused("rig_did_not_key")

            self._tx_started = self._last_heartbeat = time.monotonic()
            self._warning = False
            self._set_state(PttState.TX, "tx_started")
            self._audio_gate(True)                        # micro ouvert seulement une fois en TX confirmé
            self._watch_task = asyncio.get_running_loop().create_task(self._watchdog())
            return self.snapshot("tx_started")

    async def _transmit_plan(self, client, rx_freq: int) -> tuple[int, tuple]:
        """Fréquence d'ÉMISSION réelle, lue à l'instant : en split, celle de l'autre VFO ; avec le ΔTX / XIT en service,
        décalée. Retourne (fréquence, (split, fréquence en split, XIT, décalage)). Un split ou un XIT que le poste déclare
        mais qui ne se relit pas => Refused (en cas de doute, ne pas émettre). Un poste qui ne les connaît pas du tout
        (RPRT -4 / -11 sans les avoir déclarés) n'a rien à vérifier."""
        caps = self.link.capabilities
        tx, split, split_freq, xit_on, xit = rx_freq, False, None, False, 0
        if caps is None or caps.can_get_split is not False:
            try:
                split = await client.get_split()
                if split:
                    split_freq = await client.get_split_frequency()
                    if not split_freq or split_freq <= 0:
                        raise Refused("split_unreadable", "fréquence d'émission du split inconnue")
                    tx = split_freq
            except RigError as exc:
                declared = caps is not None and caps.can_get_split is True
                if declared or exc.code not in (RIG_ENIMPL, RIG_ENAVAIL):
                    raise Refused("split_unreadable", str(exc)) from exc
                split, split_freq, tx = False, None, rx_freq
            except CatProtocolError as exc:
                raise Refused("split_unreadable", str(exc)) from exc
            except (CatConnectionError, OSError) as exc:
                raise Refused("cat_error", str(exc)) from exc
        declared_xit = caps is not None and caps.complete and "XIT" in caps.functions
        if caps is None or not caps.complete or not caps.functions or declared_xit:
            try:
                xit_on = await client.get_func("XIT")
                if xit_on:
                    xit = await client.get_offset("XIT")
                    tx += xit
            except RigError as exc:
                if declared_xit or exc.code not in (RIG_ENIMPL, RIG_ENAVAIL):
                    raise Refused("xit_unreadable", str(exc)) from exc
                xit_on, xit = False, 0
            except CatProtocolError as exc:
                raise Refused("xit_unreadable", str(exc)) from exc
            except (CatConnectionError, OSError) as exc:
                raise Refused("cat_error", str(exc)) from exc
        return tx, (split, split_freq, xit_on, xit)

    # ------------------------------------------------------------------ surveillance

    def _on_rig_state(self, state: RigState) -> None:
        """Appelé par CatLink à chaque changement : lien perdu ou poste muet pendant l'émission ; poste utilisé sur place."""
        if not self._starting and self.local.observe(state.connected, state.ptt, state.frequency_hz, state.mode,
                                                     self._state.value):
            log.info("poste utilisé sur place (%s) : PTT à distance refusé pendant %.0f s après la dernière action",
                     self.local.reason, self.local.hold_s)
            self._emit("local_active")
        if self.thermal.observe(state.levels.get("TEMP_METER")):
            log.warning("température du poste : %.0f °C (niveau %s)", self.thermal.temp_c, self.thermal.level or "normal")
            self._emit("temp_alert")
        if self._state is not PttState.TX:
            return
        reason = None
        if not state.connected:
            reason = "cat_down"
        elif state.frequency_hz is None:
            reason = "rig_silent"
        elif self.thermal.hot:
            reason = "rig_overheat"
        if reason:
            self._spawn(self.force_rx(reason, by="température du poste" if reason == "rig_overheat" else "liaison CAT"))

    async def _watchdog(self) -> None:
        lim = self.limits
        last_rig_check = time.monotonic()
        while self._state is PttState.TX:
            now = time.monotonic()
            elapsed = now - self._tx_started
            if elapsed >= lim.tot_s:
                await self.force_rx("tot", by="chien de garde")
                return
            if now - self._last_heartbeat > lim.heartbeat_timeout_s:
                await self._end_with_tail("heartbeat", "link_lost", by="chien de garde")
                return
            if not self._warning and elapsed >= lim.tot_s - lim.warn_before_s:
                self._warning = True
                self._emit("tot_warning")
            # La relecture du poste tourne en tâche séparée : une liaison lente ne doit pas
            # retarder le TOT, et une commande CAT en cours ne doit jamais être annulée.
            if self._rig_check is None and now - last_rig_check >= lim.rig_poll_s:
                last_rig_check = now
                self._rig_check = asyncio.get_running_loop().create_task(self._rig_disagrees())
            if self._rig_check is not None and self._rig_check.done():
                task, self._rig_check = self._rig_check, None
                reason = None if task.cancelled() else task.result()
                if reason:
                    await self.force_rx(reason, by="chien de garde")
                    return
            await asyncio.sleep(lim.tick_s)

    async def _rig_disagrees(self) -> str | None:
        client = self.link.client
        try:
            freq = await client.get_frequency()
        except _CAT_ERRORS:
            return None  # liaison et poste muet sont surveillés par _on_rig_state
        if self._state is PttState.TX and freq != self._tx_freq:
            return "frequency_changed"
        if self._tx_mode is not None:              # mode changé sur le poste pendant l'émission : la source audio change avec lui
            try:
                mode, _ = await client.get_mode()
            except _CAT_ERRORS:
                return None
            if self._state is PttState.TX and mode != self._tx_mode:
                return "mode_changed"
        if self._tx_plan is not None:              # split ou ΔTX changé sur le poste : la fréquence d'émission a bougé
            try:
                _, plan = await self._transmit_plan(client, freq)
            except Refused:
                plan = None                         # relecture impossible : liaison et poste muet sont surveillés ailleurs
            if plan is not None and self._state is PttState.TX and plan != self._tx_plan:
                return "split_changed" if plan[:2] != self._tx_plan[:2] else "xit_changed"
        try:
            keyed = await client.get_ptt()
        except _CAT_ERRORS:
            return None
        if self._state is PttState.TX and not keyed:
            return "rig_reported_rx"
        return None

    # ------------------------------------------------------------------ retour en RX

    def _ensure_cut(self, reason: str, latch_fault: bool = True) -> asyncio.Task:
        if not self._cut_running():
            self._cut_task = asyncio.get_running_loop().create_task(self._do_cut(reason, latch_fault))
        assert self._cut_task is not None
        return self._cut_task

    async def _rig_still_keyed(self) -> bool:
        try:
            return await self.link.client.get_ptt()
        except RigError:
            return False  # relecture impossible : on se fie à l'écriture réussie

    async def _do_cut(self, reason: str, latch_fault: bool) -> None:
        was_active = self._state is not PttState.RX
        deadline = time.monotonic() + self.limits.unkey_deadline_s
        faulted = False
        while not self._closing:
            try:
                await self.link.client.write_ptt(False)
                if not await self._rig_still_keyed():
                    break
                log.warning("le poste reste en émission après « PTT off », nouvelle tentative")
            except _CAT_ERRORS as exc:
                if isinstance(exc, CatConnectionError) and not latch_fault:
                    # RX de démarrage : la liaison CAT s'établit, c'est attendu et sans gravité
                    log.debug("RX de démarrage en attente de la liaison CAT (%s)", exc)
                else:
                    log.warning("échec du retour RX (%s), nouvelle tentative", exc)
            if not faulted and time.monotonic() >= deadline:
                faulted = True
                if latch_fault:
                    self._fault = "unkey_failed"
                    log.error("RETOUR RX IMPOSSIBLE depuis %.1f s : défaut verrouillé", self.limits.unkey_deadline_s)
                    self._emit("fault")
            await asyncio.sleep(self.limits.unkey_retry_s)
        else:
            return
        self._owner = None
        self._warning = False
        self._starting = False
        if was_active:
            self._last_cut_reason = reason
            self._cooldown_until = time.monotonic() + self.limits.rekey_cooldown_s
        self._set_state(PttState.RX, "cut" if was_active else "rx_confirmed")
