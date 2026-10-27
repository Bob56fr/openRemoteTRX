# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Actions réelles du superviseur : sonde rigctld, alertes, et un backend de gestion des processus.

Aucune logique de décision ici : elle est dans core.py.
"""
from __future__ import annotations

from ..config import Config
from .backends import Backend
from .notify import Notifier
from .rigctl import RigctlProbe
from .usb import find_usb_authorized  # noqa: F401  (réexporté : chemin d'import historique)


class SystemActions:
    def __init__(self, cfg: Config, backend: Backend, notifier: Notifier | None = None):
        self.cfg, self.backend = cfg, backend
        self.probe = RigctlProbe(cfg.network.rigctld_host, cfg.network.rigctld_port)
        self.notifier = notifier or Notifier(cfg.supervisor.notify_url)

    def force_rx(self) -> bool:
        return self.probe.force_rx()          # direct vers rigctld, sans passer par la passerelle

    def kill_gateway(self) -> None: self.backend.kill_gateway()
    def restart_gateway(self) -> None: self.backend.restart_gateway()
    def stop_gateway(self) -> None: self.backend.stop_gateway()
    def restart_rigctld(self) -> None: self.backend.restart_rigctld()
    def reset_usb(self) -> None: self.backend.reset_usb()
    def reboot(self) -> None: self.backend.reboot()

    def notify(self, title: str, message: str) -> None:
        self.notifier.send(title, message)
