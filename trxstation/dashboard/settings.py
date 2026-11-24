# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglages du tableau de bord, tirés de station.toml ([dashboard], [network], [supervisor], [rig]).

Pas de clé d'accès (décision de l'utilisateur du 2026-11-24). Les pastilles des terminaux sont les comptes opérateurs de
station.toml ([[clients]] hors visiteurs), relus par `station.StationReader` toutes les 10 s : rien à régler ici. Adresses écoutées : automatiques si
`[dashboard] listen` est vide (étape 386, `listen_addresses`).
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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
    reresolve: Callable[[], list[str]] | None = None    # adresses automatiques : relues pour suivre un changement


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return addr == "localhost"


LOOPBACK = "127.0.0.1"


def _usable(addr: str) -> bool:
    """Adresse où le tableau de bord peut écouter tout seul : privée ou de VPN, jamais une adresse d'Internet."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (ip.is_global or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast)


def listen_addresses(cfg: StationConfig, found: Callable[[], list[str]] | None = None) -> list[str]:
    """Adresses écoutées (étape 386). `[dashboard] listen` rempli : pris tel quel. Vide (défaut) : AUTOMATIQUE, comme la
    page de pilotage : 127.0.0.1, plus son adresse si `[network] gateway_bind` en donne une, ou les adresses privées de
    la machine si elle écoute partout ; rien sur le réseau si la page n'y est pas, ni sans HTTPS (sauf
    allow_insecure_http, VPN déclaré) ; jamais une adresse d'Internet (aucun mot de passe)."""
    listen = cfg.dashboard.listen
    if isinstance(listen, list) and listen:
        return list(listen)
    n = cfg.network
    bind = (n.gateway_bind or "").strip()
    if bind in ("", LOOPBACK, "localhost", "::1"):
        return [LOOPBACK]
    if not ((n.tls_cert and n.tls_key) or n.allow_insecure_http is True):
        return [LOOPBACK]
    if bind in ("0.0.0.0", "::"):
        if found is None:
            from ..setup_wizard import local_addresses
            found = local_addresses
        try:
            candidates = found()
        except Exception:                                   # adresse introuvable : l'écran de la station seulement
            candidates = []
    else:
        candidates = [bind]
    out = [LOOPBACK]
    for addr in candidates:
        if _usable(addr) and addr not in out:
            out.append(addr)
    return out


def is_auto(cfg: StationConfig) -> bool:
    return not (isinstance(cfg.dashboard.listen, list) and cfg.dashboard.listen)


def from_station(cfg: StationConfig, station_toml: Path,
                 found: Callable[[], list[str]] | None = None) -> Settings:
    db, state_dir = cfg.dashboard, Path(cfg.supervisor.state_dir)
    s = Settings(
        status_path=Path(cfg.supervisor.status_path), state_dir=state_dir,
        station_toml=station_toml, rig_name=db.rig_name, rig_max_w=float(cfg.rig.max_power_w or 100),
        port=db.port, listen=listen_addresses(cfg, found), tls_cert=cfg.network.tls_cert, tls_key=cfg.network.tls_key,
        history_path=state_dir / "dashboard" / "history.json",
    )
    if is_auto(cfg):
        # adresses relues toutes les minutes : une adresse arrivée après le démarrage (DHCP lent, VPN qui monte) ou
        # changée fait relancer le service (systemd), qui écoute alors au bon endroit
        s.reresolve = lambda: listen_addresses(cfg, found)
    if any(not is_loopback(a) for a in s.listen):          # nom de la machine : couvert par le certificat de la station
        host = socket.gethostname()
        s.hosts = [host, f"{host}.local"]
    return s


def check(s: Settings) -> None:
    if any(a in ("0.0.0.0", "::") for a in s.listen):
        raise SettingsError("écouter sur toutes les adresses est refusé")
    if not 1024 <= s.port <= 65535:
        raise SettingsError(f"port {s.port} hors de 1024..65535")
