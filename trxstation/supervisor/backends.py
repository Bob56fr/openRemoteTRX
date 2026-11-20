# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Gestion des processus de la station : systemd (Linux / Raspberry Pi) ou « mode géré ».

Mode géré : le superviseur LANCE lui-même rigctld et la passerelle comme processus enfants,
les redémarre s'ils s'arrêtent, les tue en cas de gel. Aucun outil externe : il fonctionne
sous Windows comme sous Linux sans systemd. Si un rigctld répond déjà sur son port (lancé à
la main, ou faux poste de développement), il est ADOPTÉ au lieu d'être relancé.

Contrepartie assumée : en mode géré, la passerelle surveille son parent (--parent-pid) et
s'arrête en coupant l'émission si le superviseur disparaît. Sans superviseur, pas de station.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import Config
from ..errors import codes
from ..errors.emit import emit_event
from ..hamlib import rigctld_command
from ..logsetup import log_dir
from ..packaging import python_executable
from . import guard as guard_mod
from .usb import reset_usb_sysfs

log = logging.getLogger(__name__)

CREATE_BREAKAWAY_FROM_JOB = 0x01000000
GUARD_READY_S = 0.5                      # la garde doit être encore en vie après ce délai


class GuardUnavailable(RuntimeError):
    """La garde de fin n'a pas pu être lancée : la station ne démarre pas (ORT-8026)."""


class Backend(Protocol):
    def start(self) -> None: ...
    def maintain(self) -> None: ...
    def stop_all(self, force_rx: Callable[[], object] | None = None) -> None: ...
    def kill_gateway(self) -> None: ...
    def restart_gateway(self) -> None: ...
    def stop_gateway(self) -> None: ...
    def restart_rigctld(self) -> None: ...
    def reset_usb(self) -> None: ...
    def reboot(self) -> None: ...


def reboot_command(platform: str | None = None) -> list[str]:
    if (platform or sys.platform) == "win32":
        return ["shutdown", "/r", "/t", "0"]
    return ["systemctl", "reboot"] if shutil.which("systemctl") else ["shutdown", "-r", "now"]


class SystemdBackend:
    """Linux / Raspberry Pi : les services vivent indépendamment du superviseur."""

    def __init__(self, cfg: Config, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.cfg, self._run = cfg, runner

    def _systemctl(self, *args: str) -> None:
        try:
            done = self._run(["systemctl", *args], capture_output=True, text=True, timeout=30)
            if done.returncode != 0:
                emit_event(codes.ORT_8010, logger=log, action="systemctl " + " ".join(args),
                           detail=(done.stderr or "").strip()[:200] or f"code {done.returncode}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            emit_event(codes.ORT_8010, logger=log, action="systemctl " + " ".join(args), detail=str(exc))

    def start(self) -> None: pass
    def maintain(self) -> None: pass
    def stop_all(self, force_rx: Callable[[], object] | None = None) -> None:
        pass                                   # arrêter le superviseur ne doit pas arrêter la station

    def kill_gateway(self) -> None:
        self._systemctl("kill", "--signal=SIGKILL", self.cfg.supervisor.gateway_unit)   # tout le cgroup

    def restart_gateway(self) -> None:
        self._systemctl("restart", self.cfg.supervisor.gateway_unit)

    def stop_gateway(self) -> None:
        self._systemctl("stop", self.cfg.supervisor.gateway_unit)

    def restart_rigctld(self) -> None:
        self._systemctl("restart", self.cfg.supervisor.rigctld_unit)

    def reset_usb(self) -> None:
        reset_usb_sysfs(self.cfg.rig.port)
        self.restart_rigctld()

    def reboot(self) -> None:
        self._systemctl("reboot")


@dataclass
class _Child:
    name: str
    proc: subprocess.Popen | None = None
    stopped: bool = False        # arrêt voulu : maintain() ne le relance pas
    safe_mode_hold: bool = False  # retenu à cause du mode sûr
    last_start: float = -1e9
    restarts: int = 0


class ManagedBackend:
    def __init__(self, cfg: Config, *, commands: dict[str, list[str]] | None = None,
                 config_path: str | Path | None = None, safe_mode: Callable[[], str | None] = lambda: None,
                 clock: Callable[[], float] = time.monotonic, restart_delay_s: float = 1.0,
                 rigctld_wait_s: float = 3.0, platform: str | None = None,
                 runner: Callable[..., object] = subprocess.run,
                 port_open: Callable[[], bool] | None = None, guard: bool | None = None):
        self.cfg, self.config_path, self._safe_mode = cfg, config_path, safe_mode
        self._clock, self.restart_delay_s, self.rigctld_wait_s = clock, restart_delay_s, rigctld_wait_s
        self.platform, self._run = platform or sys.platform, runner
        self._commands = commands or {}
        self._port_open = port_open or self._rigctld_answers
        self.children = {"rigctld": _Child("rigctld"), "gateway": _Child("gateway")}
        # Garde de fin (Windows, cahier du Microsoft Store § 4.1) : remet le poste en réception si le superviseur est
        # tué (mise à jour forcée, désinstallation, Gestionnaire des tâches). Lancée la PREMIÈRE, arrêtée la dernière.
        self.guard = (self.platform == "win32") if guard is None else guard
        if self.guard:
            self.children["guard"] = _Child("guard")
        # TRX Console sur le réseau (étape 233, menu 4.6) : sous Windows, c'est le superviseur qui la lance (Debian :
        # service systemd à part). Indépendante du mode sûr : c'est justement par elle qu'on dépanne.
        if getattr(getattr(cfg, "remote_console", None), "enabled", False) is True:
            self.children["console_web"] = _Child("console_web")
        self.rigctld_adopted = False

    # ------------------------------------------------------------------ commandes

    def _command(self, name: str) -> list[str]:
        if name in self._commands:
            return self._commands[name]
        if name == "rigctld":
            return rigctld_command(self.cfg)         # résolu à la demande : pas besoin de Hamlib si adopté
        if name == "guard":
            command = [python_executable(windowed=True), "-m", "trxstation.supervisor.guard", "--parent", str(os.getpid()),
                       "--host", self.cfg.network.rigctld_host, "--port", str(self.cfg.network.rigctld_port),
                       "--state-dir", str(self.cfg.supervisor.state_dir)]
            if self.cfg.supervisor.notify_url:
                command += ["--notify-lang", self.cfg.supervisor.notify_lang]
            return command
        if name == "console_web":
            command = [python_executable(), "-m", "trxstation.console", "--reseau"]
            return command + (["--config", str(self.config_path)] if self.config_path is not None else [])
        command = [python_executable(), "-m", "trxstation.gateway.main", "--parent-pid", str(os.getpid())]
        if self.config_path is not None:
            command += ["--config", str(self.config_path)]
        return command

    def _rigctld_answers(self) -> bool:
        try:
            with socket.create_connection((self.cfg.network.rigctld_host, self.cfg.network.rigctld_port), 0.3):
                return True
        except OSError:
            return False

    # ------------------------------------------------------------------ processus

    def _spawn_guard(self, child: _Child) -> None:
        """Garde lancée HORS DU TRAVAIL de l'application (elle survit à la fermeture d'un paquet MSIX, essai S0 bis),
        sans fenêtre, jamais avec DETACHED_PROCESS (powershell et pythonw s'y arrêtent). L'adresse ntfy passe par
        l'environnement, pas par la ligne de commande (lisible par tous les comptes du PC)."""
        command = self._command("guard")
        env = dict(os.environ)
        if self.cfg.supervisor.notify_url:
            env[guard_mod.NOTIFY_URL_ENV] = self.cfg.supervisor.notify_url
        base = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        try:
            child.proc = subprocess.Popen(command, creationflags=base | (CREATE_BREAKAWAY_FROM_JOB if os.name == "nt" else 0),
                                          **kwargs)
        except OSError:
            if os.name != "nt":
                raise
            child.proc = subprocess.Popen(command, creationflags=base, **kwargs)   # travail sans « breakaway » permis
        child.last_start, child.stopped, child.safe_mode_hold = self._clock(), False, False
        log.info("garde de fin lancée (pid %d)", child.proc.pid)

    def _spawn(self, child: _Child) -> None:
        if child.name == "guard":
            self._spawn_guard(child)
            return
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # permet CTRL_BREAK ciblé
        output = None
        if os.name == "nt" and sys.stdout is None:
            # Station sans fenêtre (tâche planifiée, pythonw) : rigctld n'ouvre pas de console noire ; sa sortie va dans
            # son journal (ou nulle part). La passerelle (pythonw) écrit elle-même le sien.
            flags |= subprocess.CREATE_NO_WINDOW
            folder = log_dir()
            output = subprocess.DEVNULL
            if folder is not None and child.name == "rigctld":
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    output = open(folder / "rigctld.log", "ab")          # noqa: SIM115 - gardé ouvert par le processus
                except OSError:
                    output = subprocess.DEVNULL
        if output is None:
            child.proc = subprocess.Popen(self._command(child.name), creationflags=flags)
        else:
            child.proc = subprocess.Popen(self._command(child.name), creationflags=flags, stdin=subprocess.DEVNULL,
                                          stdout=output, stderr=subprocess.STDOUT)
        child.last_start, child.stopped, child.safe_mode_hold = self._clock(), False, False
        log.info("%s lancé (pid %d)", child.name, child.proc.pid)
        if child.name == "rigctld" and self.guard:
            guard_mod.write_rigctld_pid(self.cfg.supervisor.state_dir, child.proc.pid, None)

    @staticmethod
    def _alive(child: _Child) -> bool:
        return child.proc is not None and child.proc.poll() is None

    def _terminate(self, child: _Child, grace_s: float = 3.0) -> None:
        proc = child.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)   # type: ignore[attr-defined]
            else:
                proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(grace_s)
        except subprocess.TimeoutExpired:
            self._kill(child)

    @staticmethod
    def _kill(child: _Child) -> None:
        proc = child.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.kill()
            proc.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            emit_event(codes.ORT_8010, logger=log, action=f"arrêt forcé de {child.name}",
                       detail=f"processus {proc.pid} impossible à tuer")

    def _wait_for_rigctld(self) -> None:
        deadline = self._clock() + self.rigctld_wait_s
        child = self.children["rigctld"]
        while self._clock() < deadline and self._alive(child):
            if self._port_open():
                return
            time.sleep(0.1)

    # ------------------------------------------------------------------ cycle de vie

    def start_guard(self) -> None:
        """Lance la garde et vérifie qu'elle tient : sinon GuardUnavailable (la station ne démarre pas, fail-safe)."""
        child = self.children["guard"]
        try:
            self._spawn(child)
        except OSError as exc:
            raise GuardUnavailable(f"lancement refusé : {exc}") from exc
        deadline = time.monotonic() + GUARD_READY_S
        while time.monotonic() < deadline:
            if child.proc is not None and child.proc.poll() is not None:
                raise GuardUnavailable(f"arrêtée aussitôt (code {child.proc.returncode})")
            time.sleep(0.05)

    def start(self) -> None:
        if self.guard:
            self.start_guard()                     # AVANT rigctld : aucune émission possible sans garde
        rig = self.children["rigctld"]
        if self._port_open():
            self.rigctld_adopted = True
            log.info("rigctld répond déjà sur %s:%s : adopté, non relancé",
                     self.cfg.network.rigctld_host, self.cfg.network.rigctld_port)
        else:
            self._spawn(rig)
            self._wait_for_rigctld()
        gateway = self.children["gateway"]
        if self._safe_mode():
            gateway.stopped = gateway.safe_mode_hold = True
            emit_event(codes.ORT_8008, logger=log, raison="mode sûr mémorisé, la passerelle n'est pas lancée")
        else:
            self._spawn(gateway)
        if "console_web" in self.children:
            self._spawn(self.children["console_web"])

    def maintain(self) -> None:
        now = self._clock()
        gateway = self.children["gateway"]
        if gateway.safe_mode_hold and not self._safe_mode():
            log.info("mode sûr désactivé : la passerelle est relancée")
            self._spawn(gateway)
        for child in self.children.values():
            if child.proc is None or child.stopped or child.proc.poll() is None:
                continue
            if child.name == "gateway" and self._safe_mode():
                child.stopped = child.safe_mode_hold = True
                continue
            if child.name == "console_web" and child.proc.returncode == 2:
                child.stopped = True                     # configuration ou certificat refusés : ORT-4024, menu 4.6
                continue
            if now - child.last_start < self.restart_delay_s:
                continue
            emit_event(codes.ORT_8001, logger=log, niveau="-", action=f"relance de {child.name}",
                       problemes=f"{child.name} arrêté (code {child.proc.returncode})")
            child.restarts += 1
            try:
                self._spawn(child)
            except OSError as exc:
                if child.name != "guard":
                    raise
                # Plus de garde : plus d'émission à distance possible (fail-safe), la réception continue.
                child.stopped = True
                emit_event(codes.ORT_8026, logger=log, raison=f"relance refusée : {exc}")
                self.stop_gateway()

    def stop_all(self, force_rx: Callable[[], object] | None = None) -> None:
        """La passerelle d'abord (elle coupe le PTT), puis « T 0 » envoyé par le superviseur lui-même, puis rigctld.
        Sous Windows sans fenêtre, la passerelle ne reçoit pas la demande d'arrêt polie (pas de console commune) et
        finit tuée sans son retour en réception : le « T 0 » garantit la réception avant que rigctld ne s'arrête."""
        gateway = self.children["gateway"]
        gateway.stopped = True
        self._terminate(gateway)
        rig = self.children["rigctld"]
        if force_rx is not None and (self._alive(rig) or self.rigctld_adopted):
            try:
                if force_rx() is False:
                    emit_event(codes.ORT_5027, logger=log, moment="arrêt de la station")
                else:
                    log.info("arrêt : poste remis en réception (T 0) avant l'arrêt de rigctld")
            except Exception:                             # noqa: BLE001 - l'arrêt continue quoi qu'il arrive
                emit_event(codes.ORT_5027, logger=log, trace=True, moment="arrêt de la station")
        rig.stopped = True
        self._terminate(rig)
        if "console_web" in self.children:
            self.children["console_web"].stopped = True
            self._terminate(self.children["console_web"])
        if "guard" in self.children:
            # En DERNIER, après le « T 0 » et l'arrêt de rigctld : tuée, elle n'agit pas (arrêt normal).
            self.children["guard"].stopped = True
            self._kill(self.children["guard"])

    # ------------------------------------------------------------------ actions du superviseur

    def kill_gateway(self) -> None:
        self._kill(self.children["gateway"])             # gel possible : pas de demande polie

    def restart_gateway(self) -> None:
        child = self.children["gateway"]
        self._kill(child)
        self._spawn(child)

    def stop_gateway(self) -> None:
        child = self.children["gateway"]
        child.stopped = True
        self._terminate(child)

    def restart_rigctld(self) -> None:
        child = self.children["rigctld"]
        if self.rigctld_adopted and child.proc is None:
            emit_event(codes.ORT_8010, logger=log, action="restart_rigctld",
                       detail="rigctld lancé hors du superviseur (adopté) : redémarrage impossible")
            return
        self._terminate(child)
        self._spawn(child)
        self._wait_for_rigctld()

    def reset_usb(self) -> None:
        if self.platform == "win32":
            emit_event(codes.ORT_8005, logger=log, detail="non prise en charge sous Windows : rebrancher le câble si besoin")
            return
        reset_usb_sysfs(self.cfg.rig.port)
        self.restart_rigctld()

    def reboot(self) -> None:
        self._run(reboot_command(self.platform), timeout=30)


def choose_backend(cfg: Config, config_path: str | Path | None = None, store=None, *,
                   platform: str | None = None, systemd_present: bool | None = None, **kwargs) -> Backend:
    plat = platform or sys.platform
    mode = cfg.supervisor.service_mode
    if systemd_present is None:
        systemd_present = os.path.isdir("/run/systemd/system")
    if mode == "auto":
        mode = "systemd" if plat.startswith("linux") and systemd_present else "managed"
    if mode == "systemd":
        return SystemdBackend(cfg)
    return ManagedBackend(cfg, config_path=config_path, platform=plat,
                          safe_mode=store.safe_mode if store is not None else (lambda: None), **kwargs)
