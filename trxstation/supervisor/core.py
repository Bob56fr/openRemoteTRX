# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Cœur du superviseur : décide, n'agit que par l'intermédiaire d'`actions` injectées.

Toute la logique est déterministe (horloge, sondes et actions injectées) : on la teste sans
attendre ni toucher au système.

Garde TX (priorité absolue) : si le poste émet réellement (lu directement sur rigctld) et que
 - il émet depuis plus que le TOT absolu, ou
 - la passerelle est muette/gelée, ou déclare ne pas pouvoir couper, ou
 - l'émission n'est pas expliquée par la passerelle (sauf `allow_local_tx`),
alors on envoie « T 0 » à chaque passage tant que le poste émet, et on lance l'échelle de
reprise. Le superviseur ne déclenche JAMAIS d'émission.

Émission LOCALE (micro du poste, pédale, VOX : non expliquée par la passerelle) : avec `allow_local_tx` (défaut,
« station partagée »), elle n'est pas coupée, sauf par le TOT absolu ; sans, elle est coupée à chaque passage. Dans les
deux cas, l'échelle de reprise n'est lancée que si l'émission RÉSISTE à « T 0 » depuis STUCK_S : une émission qui
revient après une coupure réussie est une nouvelle prise de l'opérateur, et relancer la passerelle n'y changerait rien.
Passerelle muette pendant une émission : coupée si son dernier état connu était une émission (ou s'il est inconnu).

Échelle de reprise : redémarrer la passerelle -> redémarrer rigctld -> réinitialiser l'USB ->
redémarrer le Pi. Redémarrages limités par heure ; au-delà, MODE SÛR : passerelle arrêtée,
retour RX forcé, intervention manuelle requise (`trx-supervisor --clear-safe-mode`).

rigctld INJOIGNABLE PENDANT UNE ÉMISSION : jugé après RIG_LOST_TX_S d'échecs continus (la sonde réessaie déjà une
fois chaque requête). rigctld 5.0 referme parfois une connexion : une seule lecture ratée relançait rigctld, et trois en
deux minutes menaient au mode sûr (étape 104). Une fois jugé : « T 0 » tenté à chaque passage, puis l'échelle.

BATTEMENT (`alive_every_h`, 0 = aucun) : message « Station en service » en priorité minimale (sans sonnerie), pour
distinguer une station vivante derrière un accès coupé d'une station éteinte.

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

from ..cpu_temp import cpu_celsius
from ..config import DUMMY_MODEL, Config
from ..errors import codes
from ..errors.emit import by_machine, emit_event
from ..status import GatewayStatus, GatewayWatch
from .rigctl import RigProbe
from .state import StateStore

log = logging.getLogger(__name__)

LADDER = ("restart_gateway", "restart_rigctld", "reset_usb", "reboot")
# Code d'alerte de chaque niveau de l'échelle de reprise (catalogue d'erreurs).
LADDER_CODES = {"restart_gateway": codes.ORT_8001, "restart_rigctld": codes.ORT_8001,
                "reset_usb": codes.ORT_8004, "reboot": codes.ORT_8006}
STUCK_S = 5.0              # émission non expliquée qui RÉSISTE à « T 0 » depuis ce délai : alors seulement, échelle de reprise
RIG_LOST_TX_S = 1.0        # rigctld injoignable depuis ce délai pendant une émission : panne (sinon connexion ratée)
RENOTIFY_S = 600.0
HOST_EVERY_S = 30.0         # mémoire, disque, ralentissement du Pi : relevés toutes les 30 s (vcgencmd est un processus)
HOST_SUSTAIN_S = 60.0       # seuil dépassé depuis ce délai : alerte (un pic passager n'alerte pas)
HOST_RENOTIFY_S = 3600.0    # puis une alerte par heure au plus (décision de l'utilisateur, 2026-11-09)
HOST_PROBLEMS = ("memory_high", "disk_high", "pi_throttled")
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
    def notify(self, code: str, detail: str = "", key: str = "") -> None: ...   # alerte du catalogue d'erreurs


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


@dataclass
class HostReading:
    """Relevé de la machine pour les alertes « alerte seule » (aucune action du superviseur)."""
    mem_pct: float | None = None
    disks: dict[str, float] = field(default_factory=dict)      # dossier -> % utilisé du disque qui le porte
    throttled: str = ""                                         # Raspberry Pi : ralentissement EN CE MOMENT, sinon ""


def default_read_host(paths: tuple[str, ...]) -> HostReading:
    """Mémoire, disques et ralentissement du Pi (hostinfo.py : bibliothèque standard seulement)."""
    from .. import hostinfo
    mem = hostinfo.memory()
    disks: dict[str, float] = {}
    for path in paths:
        usage = hostinfo.disk(path)
        if usage is not None:
            disks[path] = usage[0]
    flags = hostinfo.read_throttled()
    now_bits = (flags or 0) & 0xF
    throttled = ", ".join(label for bit, label in hostinfo.THROTTLE_BITS.items() if now_bits & (1 << bit))
    return HostReading(mem[0] if mem else None, disks, throttled)


def default_read_temp() -> float | None:
    """Température du PROCESSEUR (coretemp, k10temp... : cpu_temp.py), jamais celle de la carte mère."""
    return cpu_celsius()


class Supervisor:
    def __init__(self, cfg: Config, *, read_status: Callable[[], GatewayStatus | None],
                 probe_rig: Callable[[], RigProbe], actions: Actions, store: StateStore,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 port_exists: Callable[[str], bool] = os.path.exists,
                 read_temp: Callable[[], float | None] = default_read_temp,
                 read_host: Callable[[], HostReading] | None = None):
        self.cfg, self.sup = cfg, cfg.supervisor
        self.read_status, self.probe_rig, self.actions, self.store = read_status, probe_rig, actions, store
        self.clock, self.wall, self.port_exists, self.read_temp = clock, wall, port_exists, read_temp
        self.read_host = read_host or HostReading                  # main.py branche default_read_host ; tests : rien
        self._host: HostReading | None = None
        self._host_at = -1e9
        self._host_since: dict[str, float] = {}
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
        self._next_alive_at = self._started + self.sup.startup_grace_s   # premier battement après le délai de grâce

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
            emit_event(codes.ORT_8022, logger=log, trace=True, erreur="voir la trace")
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
            self._alive(now, rig, gateway_fresh, safe_reason, ["safe_mode"])
            return self._safe_mode_step(now, rig_tx, gateway_fresh, safe_reason, report)

        problems = self._collect(now, rig, rig_tx, gateway_fresh)
        report.problems = [p.name for p in problems]
        lost_tx = not rig.ok and self._tx_since is not None      # émission connue, rigctld injoignable
        if (rig_tx or lost_tx) and any(p.tx for p in problems):
            self._act(report, "force_rx", self.actions.force_rx)   # à chaque passage tant que le poste émet
        self._escalate(now, problems, report)
        self._notify(now, problems)
        self._alive(now, rig, gateway_fresh, "", report.problems)
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
            last = self.watch.status                 # dernier état publié par la passerelle (même figé)
            explained = gateway_fresh and last is not None and self._tx_explained(last)
            if duration >= s.tot_abs_s:
                # Émission de la passerelle au-delà du TOT absolu : la passerelle a failli, échelle de reprise.
                # Émission locale (micro du poste) : coupée et signalée ; l'échelle seulement si la coupure ne prend pas.
                stuck = explained or duration >= s.tot_abs_s + STUCK_S
                problems.append(Problem("tot_absolu", f"émission depuis {duration:.0f} s", 0 if stuck else None, True))
            if not gateway_fresh:
                remote = last is None or last.ptt.get("state") in ACTIVE_STATES   # inconnu = prudence : on coupe
                if not s.allow_local_tx or remote:
                    problems.append(Problem("gateway_silent_tx", "passerelle muette pendant l'émission", 0, True))
            else:
                status = last
                assert status is not None
                if status.ptt.get("fault") == "unkey_failed":
                    problems.append(Problem("gateway_cannot_unkey", "la passerelle ne parvient pas à couper", 0, True))
                if self._tx_explained(status):
                    self._unexplained_since = None
                else:
                    if self._unexplained_since is None:
                        self._unexplained_since = now
                    unexplained = now - self._unexplained_since
                    if not s.allow_local_tx and unexplained >= s.mismatch_grace_s:
                        # « T 0 » à chaque passage. Une émission qui revient après une coupure réussie est une
                        # nouvelle émission locale, pas une panne : l'échelle seulement si l'émission RÉSISTE.
                        stuck = unexplained >= s.mismatch_grace_s + STUCK_S
                        problems.append(Problem(
                            "ptt_mismatch",
                            f"poste en émission, passerelle en {status.ptt.get('state')}", 0 if stuck else None, True))

        if not rig.ok:
            if self._rig_fail_since is None:
                self._rig_fail_since = now
            lost = now - self._rig_fail_since
            if self._tx_since is not None:   # dernier état connu : émission, impossible de couper
                if lost >= RIG_LOST_TX_S:    # avant : une connexion ratée, pas une panne (aucune alerte)
                    problems.append(Problem("rigctld_down_during_tx", f"{rig.error} (depuis {lost:.1f} s)", 1, True))
            elif lost >= s.rigctld_fail_s and not in_grace:
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
        problems += self._host_problems(now)
        status = self.watch.status
        if gateway_fresh and status is not None and status.ptt.get("temp_alert") in ("warn", "hot"):
            # Température du POSTE (TEMP_METER) : la passerelle coupe et refuse elle-même ; ici, l'alerte seule.
            hot = status.ptt.get("temp_alert") == "hot"
            temp = status.ptt.get("temp_c")
            shown = f"{temp:.0f} °C" if isinstance(temp, (int, float)) else "?"
            problems.append(Problem("rig_hot" if hot else "rig_warm",
                                    f"poste à {shown}" + (" : émission à distance coupée" if hot else ""), None, False))
        return problems

    def _host_problems(self, now: float) -> list[Problem]:
        """Mémoire, disque, ralentissement du Pi : ALERTE SEULE (niveau None), après HOST_SUSTAIN_S de suite. Jamais de
        relance ni de mode sûr pour ce motif : ce n'est pas une émission dangereuse."""
        s = self.sup
        if now - self._host_at >= HOST_EVERY_S:
            self._host_at = now
            try:
                self._host = self.read_host()
            except Exception:                       # une mesure ratée ne doit jamais arrêter la supervision
                emit_event(codes.ORT_8023, logger=log, trace=True, erreur="voir la trace")
                self._host = None
        h = self._host
        found: dict[str, str] = {}
        if h is not None:
            if s.mem_alert_pct and h.mem_pct is not None and h.mem_pct >= s.mem_alert_pct:
                found["memory_high"] = f"mémoire utilisée à {h.mem_pct:.0f} % (seuil {s.mem_alert_pct} %)"
            full = [f"{path} à {pct:.0f} %" for path, pct in h.disks.items() if s.disk_alert_pct and pct >= s.disk_alert_pct]
            if full:
                found["disk_high"] = "disque presque plein : " + ", ".join(full) + f" (seuil {s.disk_alert_pct} %)"
            if h.throttled:
                found["pi_throttled"] = f"Raspberry Pi ralenti en ce moment : {h.throttled} (alimentation ? refroidissement ?)"
        for name in list(self._host_since):
            if name not in found:
                del self._host_since[name]
        problems = []
        for name, detail in found.items():
            since = self._host_since.setdefault(name, now)
            if now - since >= HOST_SUSTAIN_S:
                problems.append(Problem(name, detail, None, False))
        return problems

    # ------------------------------------------------------------------ reprise

    def _act(self, report: StepReport, name: str, fn: Callable[[], object]) -> None:
        report.actions.append(name)
        try:
            result = fn()
            if name == "force_rx" and result is False:
                emit_event(codes.ORT_5027, logger=log, moment="supervision")
        except Exception:
            emit_event(codes.ORT_8010, logger=log, trace=True, action=name, detail="erreur inattendue (voir la trace)")

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
        self._alert(LADDER_CODES[name], f"reprise niveau {level} ({name}) : {detail}", key=name)
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
            emit_event(codes.ORT_8007, logger=log)
            self._act(report, "force_rx", self.actions.force_rx)
            self._act(report, "stop_gateway", self.actions.stop_gateway)
            return
        self._act(report, "force_rx", self.actions.force_rx)
        self._act(report, "reboot", self.actions.reboot)

    def _enter_safe_mode(self, report: StepReport, reason: str) -> None:
        try:
            self.store.set_safe_mode(reason)
        except OSError:
            emit_event(codes.ORT_8009, logger=log, trace=True, detail="voir la trace")
        report.safe_mode = True
        self._act(report, "force_rx", self.actions.force_rx)
        self._act(report, "stop_gateway", self.actions.stop_gateway)
        self._alert(codes.ORT_8008, reason)

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

    def _alert(self, code: str, detail: str, key: str = "") -> None:
        """Alerte d'un code du catalogue (titre, priorité, marche à suivre : Notifier.alert)."""
        try:
            self.actions.notify(code, detail, key=key)
        except Exception:
            emit_event(codes.ORT_8013, logger=log, trace=True, detail=f"{code} : erreur inattendue (voir la trace)")

    def _alive(self, now: float, rig: RigProbe, gateway_fresh: bool, safe_reason: str, problems: list[str]) -> None:
        every_h = self.sup.alive_every_h
        if every_h <= 0 or now < self._next_alive_at:
            return
        self._next_alive_at = now + every_h * 3600
        if not rig.ok:
            radio = "rigctld injoignable"
        else:
            radio = {True: "en émission", False: "en réception"}.get(rig.ptt, "PTT illisible")
            if rig.frequency_hz:
                radio += f", {rig.frequency_hz / 1e6:.3f} MHz"
        lines = [
            f"passerelle : {'en marche' if gateway_fresh else 'muette ou arrêtée'}",
            f"poste : {radio}",
            f"mode sûr : {safe_reason or 'non'}",
            f"problèmes : {', '.join(problems) if problems else 'aucun'}",
            f"prochain message dans {every_h:g} h",
        ]
        self._alert(codes.ORT_8012, "\n".join(lines))

    def _notify(self, now: float, problems: list[Problem]) -> None:
        names = {p.name for p in problems}
        for problem in problems:
            last = self._notified.get(problem.name)
            if last is None or now - last >= (HOST_RENOTIFY_S if problem.name in HOST_PROBLEMS else RENOTIFY_S):
                self._notified[problem.name] = now
                # code absent (ne devrait pas arriver : test) => alerte quand même, sous le nom du problème
                self._alert(by_machine(problem.name) or problem.name, problem.detail, key=problem.name)
        for gone in [n for n in self._notified if n not in names]:
            del self._notified[gone]
        if not names and self._had_problems:
            self._alert(codes.ORT_8011, "plus aucun problème détecté")
        self._had_problems = bool(names)
