# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""PowerControl : allumage et extinction du poste à distance (docs/alimentation-poste-cahier-des-charges.md).

SEUL composant autorisé à envoyer « \\set_powerstat » (un test le vérifie dans le code source). Règles :
  * Hors service par défaut (`[power] enabled = false`, menu 2.8 de TRX Console) ; refus si le poste ne déclare pas
    « set / get Power Stat ». Jamais automatique, sauf : la connexion d'un OPÉRATEUR (c'est le CLIENT qui envoie
    `power_on`) et l'extinction après N heures sans connexion (`[power] idle_off`, hors service par défaut).
  * Éteindre : jamais pendant une émission (station, micro du poste) ni dans les 2 min qui suivent une action sur le
    poste ; PTT relu à 0 sur le poste juste avant l'ordre, sous le verrou de l'émission (PttController.power_window).
  * Allumer : ports série vérifiés AVANT l'ordre (port présent, identité USB relevée = celle du poste ; un poste
    retrouvé sur un autre port est NOMMÉ, jamais ouvert ; usbports.py ne fait que lire) ; poste lu éteint ; après
    l'allumage, PTT relu : à 1 => « T 0 » immédiat et alerte ; VOX coupé comme à une connexion.
  * Pendant l'allumage et poste éteint : toute prise d'émission et tout réglage refusés (PttController).
  * « Éteint » lu par Hamlib n'est JAMAIS une preuve de réception (Yaesu : 0 = éteint OU muet).
Le superviseur ne commande jamais l'alimentation : il lit seulement l'état publié.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .. import ports as portsmod
from .. import usbports
from ..config import Config
from ..errors import codes
from ..errors.emit import emit_event
from .cat import CatConnectionError, CatLink, CatProtocolError, RigError
from .safety import PttController, Refused

log = logging.getLogger(__name__)

ORDER_TIMEOUT_S = 20.0        # réponse de rigctld à l'ordre (FTDX10 : 7,9 s pour l'allumage)
OFF_CONFIRM_S = 15.0          # extinction relue dans ce délai
READBACK_S = 10.0             # poste allumé : fréquence relue dans ce délai
IDLE_CHECK_S = 60.0           # extinction automatique : vérifiée toutes les minutes
IDLE_RETRY_S = 600.0          # refusée (émission, action sur le poste) : nouvel essai 10 min plus tard
RX_SETTLE_WAIT_S = 8.0        # extinction : attente d'un retour en réception encore en cours (STOP juste avant)
STEPS = ("ports", "check_off", "order", "wait", "readback", "done")
_CAT_ERRORS = (CatConnectionError, CatProtocolError, RigError, OSError)

Progress = Callable[[dict], None]


@dataclass
class PowerError(Exception):
    """Échec d'une étape de l'allumage : code ORT, motif stable, texte pour l'opérateur."""
    step: str
    reason: str
    ort: str
    detail: str

    def __str__(self) -> str:
        return self.detail


class PowerControl:
    def __init__(self, cfg: Config, link: CatLink, ctrl: PttController, *,
                 alert: Callable[..., object] | None = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 port_present: Callable[[str], bool] = portsmod.port_present,
                 identity: Callable[[str], usbports.UsbIdentity | None] = usbports.identity,
                 list_ports: Callable[[], list[str]] = portsmod.list_serial_ports,
                 sleep: Callable[[float], Awaitable] = asyncio.sleep):
        self.cfg, self.link, self.ctrl = cfg, link, ctrl
        self.alert = alert                     # Notifier.alert (code, détail) ou None
        self.clock, self.wall = clock, wall
        self.port_present, self.identity, self.list_ports = port_present, identity, list_ports
        self.sleep = sleep
        self._phase = ""                       # "" | "starting" | "stopping"
        self._task: asyncio.Task | None = None
        self.by = ""                           # dernier qui a allumé ou éteint (pseudo, « extinction automatique »)
        self.how = ""                          # "stop_hold", "connect", "button", "idle"
        self.since: float | None = None        # horloge murale du dernier changement commandé
        self.last = ""                         # "on" | "off" : dernier ordre RÉUSSI (superviseur : éteint exprès ?)
        self._last_activity = clock()
        self._idle_next = 0.0
        ctrl.power_busy = lambda: bool(self._phase)

    # ------------------------------------------------------------------ état

    @property
    def busy(self) -> bool:
        return bool(self._phase)

    def unavailable_reason(self) -> str:
        """« » = fonction offerte ; sinon le motif stable du refus."""
        if self.cfg.power.enabled is not True:
            return "power_disabled"
        caps = self.link.capabilities
        if caps is None or not (getattr(caps, "can_set_power", False) and getattr(caps, "can_get_power", False)):
            return "power_unsupported"
        return ""

    @property
    def available(self) -> bool:
        return not self.unavailable_reason()

    def snapshot(self) -> dict:
        state = self._phase or self.link.state.power or "unknown"
        return {"state": state, "available": self.available, "by": self.by, "how": self.how, "last": self.last,
                "since": None if self.since is None else round(self.since, 3)}

    def touch(self) -> None:
        """Activité (connexion, fin de connexion) : l'extinction automatique repart de zéro."""
        self._last_activity = self.clock()

    def _check_available(self) -> None:
        reason = self.unavailable_reason()
        if reason == "power_disabled":
            raise Refused(reason, "allumage et extinction à distance hors service sur cette station (TRX Console, menu 2.8)")
        if reason:
            raise Refused(reason, "le poste ne peut pas être allumé ou éteint par la CAT d'après Hamlib")
        if self._phase:
            raise Refused("power_busy", "allumage ou extinction du poste déjà en cours")

    def _notify(self, code: str, detail: str) -> None:
        if self.cfg.power.notify and self.alert is not None:
            try:
                self.alert(code, detail)
            except Exception:                       # une alerte ratée ne change rien au poste
                emit_event(codes.ORT_8013, logger=log, trace=True, detail=f"{code} : alerte de l'alimentation")

    # ------------------------------------------------------------------ extinction

    async def power_off(self, by: str, how: str = "stop_hold") -> dict:
        """Éteint le poste. Refused (motif stable) si ce n'est pas permis ; aucun ordre n'est alors envoyé."""
        self._check_available()
        state = self.link.state
        if not state.connected:
            raise Refused("cat_down", "liaison avec rigctld absente")
        if state.power == "off":
            raise Refused("rig_off", "le poste est déjà éteint")
        snap = self.ctrl.snapshot()
        if snap.local_tx:
            raise Refused("local_tx", "le poste émet en ce moment depuis son micro")
        if self.ctrl.local.active():
            left = self.ctrl.local.remaining() or 0
            raise Refused("local_active", f"poste utilisé sur place, encore {left:.0f} s")
        # STOP maintenu 3 s : l'appui a lancé un retour en réception (« T 0 » relu) ; sur un poste lent (FTDX10) il peut
        # tourner encore quand l'opérateur confirme l'arrêt (essai réel du 2026-11-20) : on l'attend un peu, puis on
        # refuse avec la VRAIE raison (jamais « pendant l'émission » quand le poste est en réception)
        for _ in range(int(RX_SETTLE_WAIT_S / 0.2)):       # tours comptés : jamais d'attente sans fin
            if not (self.ctrl.starting or not self.ctrl.rx_settled) or self.ctrl.snapshot().state != "RX":
                break                                    # réception confirmée, ou vraie émission (refus tx_active)
            await self.sleep(0.2)
        if self.ctrl.snapshot().state == "RX" and (self.ctrl.starting or not self.ctrl.rx_settled):
            raise Refused("starting" if self.ctrl.starting else "not_idle",
                          "retour en réception pas encore confirmé par le poste : réessayez dans quelques secondes")
        self._phase = "stopping"
        client = self.link.client
        try:
            async with self.ctrl.power_window(False):
                try:
                    keyed = await client.get_ptt()             # relu sur le poste (cache de rigctld coupé)
                except _CAT_ERRORS as exc:
                    raise Refused("ptt_unreadable", f"PTT illisible : {exc}") from exc
                if keyed:
                    raise Refused("tx_active", "le poste est lu en émission")
                self.link.paused = True
                try:
                    await client.set_powerstat(False, timeout=ORDER_TIMEOUT_S)
                except _CAT_ERRORS as exc:
                    emit_event(codes.ORT_2803, logger=log, par=by, cause=f"ordre d'extinction refusé ({exc})")
                    raise Refused("power_off_failed", f"ordre d'extinction refusé : {exc}") from exc
                off = await self._wait_power(False, OFF_CONFIRM_S)
        finally:
            self.link.paused = False
            self._phase = ""
        self.link.mark_power(False)
        self.by, self.how, self.since, self.last = by, how, self.wall(), "off"
        detail = f"par {by}" + ("" if off else " (extinction non relue : poste muet ?)")
        emit_event(codes.ORT_2801, logger=log, par=by, comment=_how_text(how), relu="oui" if off else "non")
        self._notify(codes.ORT_2801, detail)
        return {"power": self.snapshot()}

    # ------------------------------------------------------------------ allumage

    def power_on(self, by: str, how: str = "connect", progress: Progress | None = None) -> asyncio.Task:
        """Lance l'allumage dans une tâche PROPRE (une connexion fermée ne l'interrompt pas). Refused tout de suite si
        la fonction n'est pas offerte ou déjà en cours. La tâche rend {"result": "on" | "already_on", ...} ou lève
        PowerError (étape, motif, code ORT, texte)."""
        self._check_available()
        self._phase = "starting"
        task = asyncio.get_running_loop().create_task(self._power_on(by, how, progress or (lambda message: None)))
        self._task = task
        return task

    async def _power_on(self, by: str, how: str, progress: Progress) -> dict:
        started = self.clock()

        def step(name: str, status: str, detail: str = "", ort: str | None = None, remaining_s: float | None = None):
            message = {"step": name, "status": status, "detail": detail}
            if ort:
                message["ort"] = ort
            if remaining_s is not None:
                message["remaining_s"] = round(max(0.0, remaining_s), 1)
            try:
                progress(message)
            except Exception:                           # le client qui suit l'allumage ne doit jamais le casser
                log.debug("suivi de l'allumage : envoi impossible", exc_info=True)

        try:
            try:
                step("ports", "running")
                warning = self._check_ports()
                step("ports", "ok", warning)
                step("check_off", "running")
                if not self.link.state.connected:
                    raise PowerError("check_off", "cat_down", codes.ORT_2803,
                                     "pas de liaison avec rigctld : la station ne peut pas joindre le poste")
                client = self.link.client
                self.link.paused = True
                try:
                    on = await client.get_powerstat(timeout=6.0)
                except RigError as exc:
                    # Icom (IC-7300MK2, essai réel du 2026-11-19) : poste éteint = lecture REFUSÉE (RPRT -9), pas « 0 ».
                    # rigctld répond (liaison en place), le poste ne répond pas : c'est le cas qu'on vient allumer.
                    log.info("alimentation illisible (%s) : poste éteint, l'ordre d'allumage part quand même", exc)
                    on = False
                except _CAT_ERRORS as exc:
                    raise PowerError("check_off", "rig_silent", codes.ORT_2803,
                                     f"le poste ne répond pas ({exc}) : câble USB, alimentation, interrupteur arrière") from exc
                if on:
                    step("check_off", "ok", "poste déjà allumé")
                    self.link.mark_power(True)
                    step("done", "ok", "poste déjà allumé")
                    return {"result": "already_on", "power": self.snapshot()}
                if self.link.state.power != "off":
                    self.link.mark_power(False)
                step("check_off", "ok")
                async with self.ctrl.power_window(True):
                    step("order", "running")
                    try:
                        await client.set_powerstat(True, timeout=ORDER_TIMEOUT_S)
                        step("order", "ok")
                    except RigError as exc:
                        raise PowerError("order", "power_on_failed", codes.ORT_2803,
                                         f"ordre d'allumage refusé par rigctld : {exc}") from exc
                    except (CatConnectionError, CatProtocolError, OSError) as exc:
                        step("order", "ok", f"réponse de rigctld manquante ({exc}) : attente du poste quand même")
                    timeout = float(self.cfg.power.on_timeout_s)
                    step("wait", "running", remaining_s=timeout)
                    if not await self._wait_power(True, timeout,
                                                  lambda left: step("wait", "running", remaining_s=left)):
                        raise PowerError("wait", "power_on_timeout", codes.ORT_2803,
                                         f"le poste ne s'est pas allumé en {timeout:.0f} s")
                    step("wait", "ok")
                    step("readback", "running")
                    self.link.settle()
                    readback = await self._readback()
                self.link.mark_power(True)
                self.ctrl.local.station_busy()          # ce que le poste relit maintenant vient de la station
                for kind in ("frequency", "mode"):
                    self.ctrl.local.expect(kind)
            finally:
                self.link.paused = False
            if readback["ptt"]:
                await self.ctrl.force_rx("power_on_tx", by="allumage du poste")
                ctx = {"par": by}
                emit_event(codes.ORT_2808, logger=log, **ctx)
                if self.alert is not None:             # toujours, même sans [power] notify : émission inattendue
                    try:
                        self.alert(codes.ORT_2808, f"poste allumé en émission par {by}, remis en réception")
                    except Exception:
                        emit_event(codes.ORT_8013, logger=log, trace=True, detail="ORT-2808 : alerte")
                raise PowerError("readback", "power_on_tx", codes.ORT_2808,
                                 "le poste s'est allumé EN ÉMISSION : remis en réception ; vérifier la ligne PTT (RTS / DTR)")
            try:
                await self.ctrl.vox_guard(by)          # VOX coupé comme à une connexion (le poste vient de démarrer)
            except Exception:                           # jamais fatal
                log.debug("VOX non vérifié après l'allumage", exc_info=True)
            seconds = self.clock() - started
            text = _rig_text(readback)
            step("readback", "ok", text)
            self.by, self.how, self.since, self.last = by, how, self.wall(), "on"
            emit_event(codes.ORT_2802, logger=log, par=by, comment=_how_text(how), secondes=f"{seconds:.0f}", poste=text)
            self._notify(codes.ORT_2802, f"par {by} en {seconds:.0f} s : {text}")
            step("done", "ok", text)
            return {"result": "on", "seconds": round(seconds, 1), "rig": text, "power": self.snapshot()}
        except PowerError as exc:
            if exc.ort == codes.ORT_2803:
                emit_event(codes.ORT_2803, logger=log, par=by, cause=exc.detail)
                self._notify(codes.ORT_2803, f"par {by} : {exc.detail}")
            elif exc.ort == codes.ORT_2809:
                emit_event(codes.ORT_2809, logger=log, par=by, detail=exc.detail)
                self._notify(codes.ORT_2809, f"par {by} : {exc.detail}")
            step(exc.step, "error", exc.detail, ort=exc.ort)
            raise
        except Refused as exc:
            detail = str(exc)
            step("order", "error", detail, ort=codes.ORT_2803)
            raise PowerError("order", exc.reason, codes.ORT_2803, detail) from exc
        finally:
            self._phase = ""

    def _check_ports(self) -> str:
        """Vérifications du § 4.1, LECTURE SEULE (aucun port ouvert). Lève PowerError ; rend un avertissement ou « »."""
        rig = self.cfg.rig
        checks = [("port", rig.port, rig.port_usb)]
        if rig.ptt_type in ("RTS", "DTR") and rig.ptt_port and rig.ptt_port.strip().lower() != rig.port.strip().lower():
            checks.append(("ptt_port", rig.ptt_port, rig.ptt_port_usb))
        warning = ""
        for name, port, expected_text in checks:
            what = "du poste" if name == "port" else "du PTT"
            if not port:
                continue                                 # modèle factice : pas de port
            if not self.port_present(port):
                raise PowerError("ports", "port_missing", codes.ORT_2809,
                                 f"port {what} {port} absent : poste débranché ou câble USB ?")
            if not expected_text:
                warning = "identité du port non relevée : refaire la mise en service au menu 2.8 de TRX Console"
                continue
            expected = usbports.parse_identity(expected_text)
            if expected is None:
                raise PowerError("ports", "port_identity", codes.ORT_2809,
                                 f"identité USB du port {what} illisible dans station.toml : menu 2.8 de TRX Console")
            found = self.identity(port)
            if usbports.same_device(expected, found):
                continue
            elsewhere = [p for p in self.list_ports()            # numéro de série exigé pour désigner un autre port
                         if p != port and expected.serial and usbports.same_device(expected, self.identity(p))]
            if elsewhere:
                raise PowerError("ports", "port_moved", codes.ORT_2809,
                                 f"le poste est maintenant sur {', '.join(elsewhere)} (station.toml dit {port}) : "
                                 "refaire le menu 2.5 de TRX Console sur la station")
            seen = str(found) if found is not None else "aucun périphérique USB lisible"
            raise PowerError("ports", "port_mismatch", codes.ORT_2809,
                             f"le port {port} n'est plus celui {what} ({seen} au lieu de {expected}) : "
                             "refaire le menu 2.5 de TRX Console sur la station")
        return warning

    async def _wait_power(self, on: bool, timeout: float, tick: Callable[[float], None] | None = None) -> bool:
        """Relit l'alimentation jusqu'à l'état voulu (`timeout` s au plus). Une connexion perdue est refaite (rigctld
        a pu la fermer pendant l'ordre)."""
        client = self.link.client
        deadline = self.clock() + timeout
        while True:
            left = deadline - self.clock()
            if left <= 0:
                return False
            if tick is not None:
                tick(left)
            try:
                if not client.connected:
                    await client.connect()
                if await client.get_powerstat(timeout=min(6.0, max(1.0, left))) is on:
                    return True
            except RigError:
                if not on:
                    return True                           # Icom éteint : lecture refusée (RPRT -9) = poste qui ne répond plus
            except _CAT_ERRORS:
                pass
            await self.sleep(1.0)

    async def _readback(self) -> dict:
        """Poste allumé : fréquence relue (il démarre : quelques secondes), puis mode et PTT."""
        client = self.link.client
        deadline = self.clock() + READBACK_S
        freq = mode = None
        while self.clock() < deadline:
            try:
                if not client.connected:
                    await client.connect()
                freq = await client.get_frequency()
                break
            except _CAT_ERRORS:
                await self.sleep(1.0)
        try:
            mode, _ = await client.get_mode()
        except _CAT_ERRORS:
            mode = None
        try:
            ptt = await client.get_ptt()
        except _CAT_ERRORS:
            ptt = None                                    # illisible : la passerelle le relit et refuse l'émission
        return {"frequency_hz": freq, "mode": mode, "ptt": ptt is True}

    # ------------------------------------------------------------------ extinction automatique

    async def run_idle(self, stop: asyncio.Event, connections: Callable[[], int],
                       busy: Callable[[], str] = lambda: "") -> None:
        """[power] idle_off : poste éteint après idle_off_hours SANS aucune connexion (opérateur ni visiteur), ni
        diffusion (`busy`), ni action sur le poste. Refusée (émission, poste utilisé sur place) : reportée, jamais forcée."""
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), IDLE_CHECK_S)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self.idle_tick(connections, busy)
            except Exception:                           # jamais d'arrêt de la passerelle pour ce motif
                emit_event(codes.ORT_2810, logger=log, trace=True, cause="erreur inattendue (voir la trace)")

    async def idle_tick(self, connections: Callable[[], int], busy: Callable[[], str] = lambda: "") -> bool:
        """Un passage ; True si le poste vient d'être éteint."""
        pw, now = self.cfg.power, self.clock()
        if not (pw.idle_off and self.available) or self.link.state.power != "on":
            self._last_activity = now
            return False
        snap = self.ctrl.snapshot()
        if connections() > 0 or busy() or snap.state != "RX" or snap.local_tx or self.ctrl.local.active():
            self._last_activity = now
            return False
        if now - self._last_activity < pw.idle_off_hours * 3600 or now < self._idle_next:
            return False
        try:
            await self.power_off("extinction automatique", how="idle")
        except Refused as exc:
            self._idle_next = now + IDLE_RETRY_S
            emit_event(codes.ORT_2810, logger=log, cause=str(exc))
            return False
        return True


def _how_text(how: str) -> str:
    return {"stop_hold": "STOP maintenu", "connect": "connexion", "button": "bouton", "idle": "sans connexion depuis le délai"}.get(how, how)


def _rig_text(readback: dict) -> str:
    freq, mode = readback.get("frequency_hz"), readback.get("mode")
    from ..power_trial import khz_text
    shown = khz_text(freq) if isinstance(freq, int) else "fréquence non relue"
    return f"{shown} {mode or ''}".strip() + ", en réception"
