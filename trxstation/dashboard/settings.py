# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglages du tableau de bord, tirés de station.toml ([dashboard], [network], [supervisor], [rig]).

Pas de clé d'accès (décision de l'utilisateur du 2026-11-24). Les pastilles des terminaux sont les comptes opérateurs de
station.toml ([[clients]] hors visiteurs), relus par `station.StationReader` toutes les 10 s : rien à régler ici.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config as StationConfig


class SettingsError(ValueError):
    pass


@dataclass
class Settings:
    status_path: Path = Path("/run/trx-remote/gateway-status.json")
    state_dir: Path = Path("/var/lib/trx-remote")
    station_toml: Path = Path("/etc/trx-remote/station.toml")
    rig_name: str = ""
    rig_max_w: float = 100.0
    port: int = 8450
    listen: list[str] = field(default_factory=lambda: ["127.0.0.1"])
    hosts: list[str] = field(default_factory=list)
    tls_cert: str = ""
    tls_key: str = ""
    history_path: Path | None = None
    internet_targets: list[str] = field(default_factory=lambda: ["1.1.1.1:443", "9.9.9.9:443"])
    internet_every_s: float = 30.0


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return addr == "localhost"


def from_station(cfg: StationConfig, station_toml: Path) -> Settings:
    db, state_dir = cfg.dashboard, Path(cfg.supervisor.state_dir)
    return Settings(
        status_path=Path(cfg.supervisor.status_path), state_dir=state_dir,
        station_toml=station_toml, rig_name=db.rig_name, rig_max_w=float(cfg.rig.max_power_w or 100),
        port=db.port, listen=list(db.listen), tls_cert=cfg.network.tls_cert, tls_key=cfg.network.tls_key,
        history_path=state_dir / "dashboard" / "history.json",
    )


def check(s: Settings) -> None:
    if any(a in ("0.0.0.0", "::") for a in s.listen):
        raise SettingsError("écouter sur toutes les adresses est refusé")
    if not 1024 <= s.port <= 65535:
        raise SettingsError(f"port {s.port} hors de 1024..65535")
