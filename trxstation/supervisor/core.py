"""Cœur du superviseur : décide, n'agit que par l'intermédiaire d'`actions` injectées.

Toute la logique est déterministe (horloge, sondes et actions injectées) : on la teste sans
attendre ni toucher au système.

Garde TX (priorité absolue) : si le poste émet réellement (lu directement sur rigctld) et que
 - il émet depuis plus que le TOT absolu, ou
 - la passerelle est muette/gelée, ou déclare ne pas pouvoir couper, ou
 - l'émission n'est pas expliquée par la passerelle (sauf `allow_local_tx`),
alors on envoie « T 0 » à chaque passage tant que le poste émet, et on lance l'échelle de
reprise. Le superviseur ne déclenche JAMAIS d'émission.

Échelle de reprise : redémarrer la passerelle -> redémarrer rigctld -> réinitialiser l'USB ->
redémarrer le Pi. Redémarrages limités par heure ; au-delà, MODE SÛR : passerelle arrêtée,
retour RX forcé, intervention manuelle requise (`trx-supervisor --clear-safe-mode`).

Poste ABSENT (port du poste disparu : éteint ou débranché) sans émission connue : aucune reprise n'y peut rien
(on ne réinitialise pas un périphérique absent) et rien ne peut émettre. Alerte « rig_absent » seulement, aucune
action, jamais de mode sûr ; au retour du port, la reprise normale relance rigctld. Si la dernière émission connue
était en cours, l'escalade complète reste due (poste qui émet sans liaison).
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from ..config import DUMMY_MODEL, Config
from ..status import GatewayStatus, GatewayWatch
from .rigctl import RigProbe
from .state import StateStore

log = logging.getLogger(__name__)

LADDER = ("restart_gateway", "restart_rigctld", "reset_usb", "reboot")
RENOTIFY_S = 600.0
SAFE_MODE_STOP_EVERY_S = 30.0
ACTIVE_STATES = ("KEYING", "TX", "UNKEYING")


class Actions(Protocol):
    def force_rx(self) -> bool: ...
    def kill_gateway(self) -> None: ...
    def restart_gateway(self) -> None: ...
    def stop_gateway(self) -> None: ...
    def restart_rigctld(self) -> None: ...
    def reset_usb(self) -> None: ...
    def reboot(self) -> None: ...
    def notify(self, title: str, message: str) -> None: ...


@dataclass(frozen=True)
class Problem:
    name: str
    detail: str = ""
    level: int | None = 0      # niveau de départ dans l'échelle ; None = alerte seule
    tx: bool = False           # concerne une émission en cours


@dataclass
class StepReport:
    problems: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    safe_mode: bool = False


def default_read_temp() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
    except (OSError, ValueError):
        return None


class Supervisor:
    def __init__(self, cfg: Config, *, read_status: Callable[[], GatewayStatus | None],
                 probe_rig: Callable[[], RigProbe], actions: Actions, store: StateStore,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 port_exists: Callable[[str], bool] = os.path.exists,
                 read_temp: Callable[[], float | None] = default_read_temp):
        self.cfg, self.sup = cfg, cfg.supervisor
        self.read_status, self.probe_rig, self.actions, self.store = read_status, probe_rig, actions, store
        self.clock, self.wall, self.port_exists, self.read_temp = clock, wall, port_exists, read_temp
        self.watch = GatewayWatch(self.sup.stale_after_s)
        self._started = clock()
        self._tx_since: float | None = None
        self._unexplained_since: float | None = None
        self._rig_fail_since: float | None = None
        self._level = 0
        self._next_action_at = 0.0
        self._healthy_since: float | None = None
        self._notified: dict[str, float] = {}
        self._had_problems = False
        self._last_stop_gateway = -1e9

    @property
    def tx_active(self) -> bool:
        """Vrai si le poste émet (ou a émis lors de la dernière lecture) : cadence de sondage rapide."""
        return self._tx_since is not None

    # ------------------------------------------------------------------ un passage

    def step(self) -> StepReport:
        now = self.clock()
        report = StepReport()
        try:
            status = self.read_status()
        except Exception:
            log.exception("lecture du fichier d'état en erreur")
            status = None
        self.watch.update(status, now)
        try:
            rig = self.probe_rig()
        except Exception as exc:
            rig = RigProbe(False, error=repr(exc))
        gateway_fresh = self.watch.fresh(now)

        if rig.ok and rig.ptt is True:
            if self._tx_since is None:
                self._tx_since = now
        elif rig.ok and rig.ptt is False:
            self._tx_since = self._unexplained_since = None
        rig_tx = rig.ok and rig.ptt is True

        safe_reason = self.store.safe_mode()
        if safe_reason:
            return self._safe_mode_step(now, rig_tx, gateway_fresh, safe_reason, report)

        problems = self._collect(now, rig, rig_tx, gateway_fresh)
        report.problems = [p.name for p in problems]
        if rig_tx and any(p.tx for p in problems):
            self._act(report, "force_rx", self.actions.force_rx)   # à chaque passage tant que le poste émet
        self._escalate(now, problems, report)
        self._notify(now, problems)
        return report

    # ------------------------------------------------------------------ détection

    @staticmethod
    def _tx_explained(status: GatewayStatus) -> bool:
        state = status.ptt.get("state")
        if state == "UNKEYING":
            return True                    # coupure en cours : la passerelle fait son travail
        return state in ACTIVE_STATES and status.ptt.get("owner") in status.clients

    def _collect(self, now: float, rig: RigProbe, rig_tx: bool, gateway_fresh: bool) -> list[Problem]:
        s = self.sup
        problems: list[Problem] = []
        in_grace = now - self._started < s.startup_grace_s

        if rig_tx and self._tx_since is not None:
            duration = now - self._tx_since
            if duration >= s.tot_abs_s:
                problems.append(Problem("tot_absolu", f"émission depuis {duration:.0f} s", 0, True))
            if not gateway_fresh:
                if not s.allow_local_tx:
                    problems.append(Problem("gateway_silent_tx", "passerelle muette pendant l'émission", 0, True))
            else:
                status = self.watch.status
                assert status is not None
                if status.ptt.get("fault") == "unkey_failed":
                    problems.append(Problem("gateway_cannot_unkey", "la passerelle ne parvient pas à couper", 0, True))
                if self._tx_explained(status):
                    self._unexplained_since = None
                else:
                    if self._unexplained_since is None:
                        self._unexplained_since = now
                    if not s.allow_local_tx and now - self._unexplained_since >= s.mismatch_grace_s:
                        problems.append(Problem(
                            "ptt_mismatch",
                            f"poste en émission, passerelle en {status.ptt.get('state')}", 0, True))

        if not rig.ok:
            if self._rig_fail_since is None:
                self._rig_fail_since = now
            if self._tx_since is not None:   # dernier état connu : émission, impossible de couper
                problems.append(Problem("rigctld_down_during_tx", rig.error, 1, True))
            elif now - self._rig_fail_since >= s.rigctld_fail_s and not in_grace:
                problems.append(Problem("rigctld_down", rig.error, 1, False))
        else:
            self._rig_fail_since = None

        if not gateway_fresh and not in_grace:
            problems.append(Problem("gateway_silent", "fichier d'état de la passerelle figé ou absent", 0, False))

        if (self.cfg.rig.model != DUMMY_MODEL and self.cfg.rig.port
                and not self.port_exists(self.cfg.rig.port) and not in_grace):
            problems.append(Problem("usb_missing", self.cfg.rig.port, 2, False))

        if self._tx_since is None and any(p.name == "usb_missing" for p in problems):
            problems = [Problem("rig_absent", f"poste éteint ou débranché ({self.cfg.rig.port} absent) : la station "
                                "attend son retour, sans relancer", None, False)] + \
                       [replace(p, level=None) for p in problems if p.name != "usb_missing"]

        temperature = self.read_temp()
        if temperature is not None and temperature >= s.temp_alert_c:
            problems.append(Problem("cpu_hot", f"{temperature:.0f} °C", None, False))
        return problems

    # ------------------------------------------------------------------ reprise

    def _act(self, report: StepReport, name: str, fn: Callable[[], object]) -> None:
        report.actions.append(name)
        try:
            result = fn()
            if name == "force_rx" and result is False:
                log.warning("force_rx : le poste n'est pas confirmé en réception")
        except Exception:
            log.exception("action %s en erreur", name)

    def _escalate(self, now: float, problems: list[Problem], report: StepReport) -> None:
        actionable = [p for p in problems if p.level is not None]
        if not actionable:
            if self._healthy_since is None:
                self._healthy_since = now
            elif now - self._healthy_since >= self.sup.healthy_reset_s:
                self._level = 0
            return
        self._healthy_since = None
        self._level = max(self._level, min(p.level for p in actionable if p.level is not None))
        if now < self._next_action_at:
            return
        level = self._level
        self._run_level(level, actionable, report)
        self._level = min(level + 1, len(LADDER) - 1)
        self._next_action_at = now + self.sup.recovery_wait_s

    def _run_level(self, level: int, problems: list[Problem], report: StepReport) -> None:
        name = LADDER[level]
        detail = ", ".join(p.name for p in problems)
        log.error("reprise niveau %d (%s) : %s", level, name, detail)
        self._notify_text(f"Reprise : {name}", detail)
        if name == "restart_gateway":
            self._act(report, "kill_gateway", self.actions.kill_gateway)
            self._act(report, "restart_gateway", self.actions.restart_gateway)
        elif name == "restart_rigctld":
            self._act(report, "restart_rigctld", self.actions.restart_rigctld)
        elif name == "reset_usb":
            self._act(report, "reset_usb", self.actions.reset_usb)
        else:
            self._reboot_or_safe_mode(report, detail)

    def _reboot_or_safe_mode(self, report: StepReport, detail: str) -> None:
        wall = self.wall()
        recent = [t for t in self.store.reboot_times() if t > wall - 3600]  # futur = récent (prudent)
        if len(recent) >= self.sup.max_reboots_per_hour:
            self._enter_safe_mode(report, f"{len(recent)} redémarrage(s) sans succès : {detail}")
            return
        try:
            self.store.add_reboot(wall)
        except OSError:
            # Sans historique fiable, un redémarrage en boucle serait possible : on s'abstient.
            log.error("historique des redémarrages non inscriptible : pas de reboot, passerelle arrêtée")
            self._act(report, "force_rx", self.actions.force_rx)
            self._act(report, "stop_gateway", self.actions.stop_gateway)
            return
        self._act(report, "force_rx", self.actions.force_rx)
        self._act(report, "reboot", self.actions.reboot)

    def _enter_safe_mode(self, report: StepReport, reason: str) -> None:
        log.error("MODE SÛR : %s", reason)
        try:
            self.store.set_safe_mode(reason)
        except OSError:
            log.exception("mode sûr non persisté (il ne survivra pas à un redémarrage du superviseur)")
        report.safe_mode = True
        self._act(report, "force_rx", self.actions.force_rx)
        self._act(report, "stop_gateway", self.actions.stop_gateway)
        self._notify_text("MODE SÛR", reason)

    def _safe_mode_step(self, now: float, rig_tx: bool, gateway_fresh: bool, reason: str,
                        report: StepReport) -> StepReport:
        report.problems, report.safe_mode = ["safe_mode"], True
        if rig_tx:
            self._act(report, "force_rx", self.actions.force_rx)
        if gateway_fresh and now - self._last_stop_gateway >= SAFE_MODE_STOP_EVERY_S:
            self._last_stop_gateway = now
            self._act(report, "stop_gateway", self.actions.stop_gateway)
        self._notify(now, [Problem("safe_mode", reason, None, False)])
        return report

    # ------------------------------------------------------------------ alertes

    def _notify_text(self, title: str, message: str) -> None:
        try:
            self.actions.notify(title, message)
        except Exception:
            log.exception("alerte en erreur")

    def _notify(self, now: float, problems: list[Problem]) -> None:
        names = {p.name for p in problems}
        for problem in problems:
            last = self._notified.get(problem.name)
            if last is None or now - last >= RENOTIFY_S:
                self._notified[problem.name] = now
                self._notify_text(f"Problème : {problem.name}", problem.detail)
        for gone in [n for n in self._notified if n not in names]:
            del self._notified[gone]
        if not names and self._had_problems:
            self._notify_text("Station rétablie", "plus aucun problème détecté")
        self._had_problems = bool(names)
