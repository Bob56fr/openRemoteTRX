# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Unique action de trx-monitor : STOP TX. Elle ne peut que couper l'émission.

L'ordre « T 0 » part directement vers rigctld (sonde indépendante du superviseur) : il
fonctionne même si la passerelle est gelée.
"""
from __future__ import annotations

from ..config import Config
from ..i18n import Translator
from ..supervisor.rigctl import RigctlProbe
from .model import translator


def stop_tx(cfg: Config, t: Translator | None = None) -> tuple[bool, str]:
    probe = RigctlProbe(cfg.network.rigctld_host, cfg.network.rigctld_port, timeout=1.0)
    ok = probe.force_rx()
    t = translator(t)
    return (True, t("stop.ok")) if ok else (False, t("stop.failed"))
