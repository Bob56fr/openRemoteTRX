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
from ..hamlib import rigctld_command
from .usb import reset_usb_sysfs

log = logging.getLogger(__name__)


class Backend(Protocol):
    def start(self) -> None: ...
    def maintain(self) -> None: ...
    def stop_all(self) -> None: ...
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
                log.error("systemctl %s a échoué : %s", " ".join(args), (done.stderr or "").strip()[:200])
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.error("systemctl %s impossible : %s", " ".join(args), exc)

    def start(self) -> None: pass
    def maintain(self) -> None: pass
    def stop_all(self) -> None: pass            # arrêter le superviseur ne doit pas arrêter la station

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
                 port_open: Callable[[], bool] | None = None):
        self.cfg, self.config_path, self._safe_mode = cfg, config_path, safe_mode
        self._clock, self.restart_delay_s, self.rigctld_wait_s = clock, restart_delay_s, rigctld_wait_s
        self.platform, self._run = platform or sys.platform, runner
        self._commands = commands or {}
        self._port_open = port_open or self._rigctld_answers
        self.children = {"rigctld": _Child("rigctld"), "gateway": _Child("gateway")}
        self.rigctld_adopted = False

    # ------------------------------------------------------------------ commandes

    def _command(self, name: str) -> list[str]:
        if name in self._commands:
            return self._commands[name]
        if name == "rigctld":
            return rigctld_command(self.cfg)         # résolu à la demande : pas besoin de Hamlib si adopté
        command = [sys.executable, "-m", "trxstation.gateway.main", "--parent-pid", str(os.getpid())]
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

    def _spawn(self, child: _Child) -> None:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # permet CTRL_BREAK ciblé
        child.proc = subprocess.Popen(self._command(child.name), creationflags=flags)
        child.last_start, child.stopped, child.safe_mode_hold = self._clock(), False, False
        log.info("%s lancé (pid %d)", child.name, child.proc.pid)

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
            log.error("%s : impossible de tuer le processus %s", child.name, proc.pid)

    def _wait_for_rigctld(self) -> None:
        deadline = self._clock() + self.rigctld_wait_s
        child = self.children["rigctld"]
        while self._clock() < deadline and self._alive(child):
            if self._port_open():
                return
            time.sleep(0.1)

    # ------------------------------------------------------------------ cycle de vie

    def start(self) -> None:
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
            log.warning("mode sûr actif : la passerelle n'est pas lancée")
        else:
            self._spawn(gateway)

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
            if now - child.last_start < self.restart_delay_s:
                continue
            log.warning("%s s'est arrêté (code %s) : redémarrage", child.name, child.proc.returncode)
            child.restarts += 1
            self._spawn(child)

    def stop_all(self) -> None:
        for name in ("gateway", "rigctld"):              # la passerelle d'abord : elle coupe le PTT
            child = self.children[name]
            child.stopped = True
            self._terminate(child)

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
            log.error("rigctld n'est pas géré par le superviseur (adopté) : redémarrage impossible")
            return
        self._terminate(child)
        self._spawn(child)
        self._wait_for_rigctld()

    def reset_usb(self) -> None:
        if self.platform == "win32":
            log.error("réinitialisation USB non prise en charge sous Windows : rebranche le câble si besoin")
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
