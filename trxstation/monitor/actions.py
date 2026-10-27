# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Unique action de trx-monitor : STOP TX. Elle ne peut que couper l'émission.

L'ordre « T 0 » part directement vers rigctld (sonde indépendante du superviseur) : il
fonctionne même si la passerelle est gelée.
"""
from __future__ import annotations

from ..config import Config
from ..supervisor.rigctl import RigctlProbe


def stop_tx(cfg: Config) -> tuple[bool, str]:
    probe = RigctlProbe(cfg.network.rigctld_host, cfg.network.rigctld_port, timeout=1.0)
    if probe.force_rx():
        return True, "PTT coupé : ordre « T 0 » envoyé, le poste n'est pas en émission"
    return False, "ÉCHEC : le poste n'est pas confirmé en réception (rigctld injoignable ou poste bloqué)"
