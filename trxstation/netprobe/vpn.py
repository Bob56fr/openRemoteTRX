# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Profil VPN partagé par deux appareils (docs/netprobe-cahier-des-charges.md § 8).

Le serveur VPN ne garde qu'une adresse d'origine par profil : deux appareils sur le même profil se la volent et la
liaison tombe toutes les 15 à 30 s (incident du 2026-11-09). Seul le serveur VPN le voit directement ; la station en
repère les EFFETS :
  D1  deux connexions ouvertes en même temps, d'appareils différents, depuis la même adresse PRIVÉE ;
  D2  la même adresse privée sert à deux appareils différents à moins de 10 minutes d'écart ;
  D3  coupures très régulières (calc.regular_pattern), signalées par la sonde du client.
Un avertissement n'est jamais un refus. Adresses ignorées : boucle locale (client sur la station) et adresses
publiques (plusieurs appareils derrière une même box distante, cas légitime).
"""
from __future__ import annotations

import ipaddress
import logging
import time

from ..errors import codes
from ..errors.emit import emit_event

log = logging.getLogger(__name__)
ALTERNATE_MS = 600_000                 # D2 : deux appareils sur une adresse à moins de 10 min d'écart
WARNING_MS = 86_400_000                # un avertissement reste affiché 24 h
ALERT_EVERY_MS = 86_400_000            # au plus une alerte ntfy par adresse et par 24 h
PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
                                                  "fc00::/7"))
ADVICE = "Créez un profil VPN par appareil : c'est une cause connue de coupures toutes les 15 à 30 s."


def private_address(source: str) -> bool:
    try:
        ip = ipaddress.ip_address(source)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return not ip.is_loopback and any(ip in net for net in PRIVATE)


class VpnWatch:
    def __init__(self, store, enabled: bool = True, alert=None, wall_ms=lambda: int(time.time() * 1000)) -> None:
        self.store, self.enabled, self.alert, self.wall_ms = store, enabled, alert, wall_ms
        data = store.vpn()
        self.seen: dict[str, dict] = data.get("seen", {}) if isinstance(data.get("seen"), dict) else {}
        self.ignored: list[str] = [a for a in data.get("ignored", []) if isinstance(a, str)]
        self.alerted: dict[str, int] = data.get("alerted", {}) if isinstance(data.get("alerted"), dict) else {}
        self.warnings: dict[str, dict] = {}

    def _save(self) -> None:
        self.store.save_vpn({"seen": self.seen, "ignored": self.ignored, "alerted": self.alerted})

    def opened(self, source: str, device: str, agent: str, others: list[tuple[str, str, str]]) -> dict | None:
        """Connexion ouverte. `others` : (adresse, appareil, agent) des AUTRES connexions ouvertes."""
        if not device or not private_address(source):
            return None
        now = self.wall_ms()
        warning = None
        for addr, other_device, other_agent in others:
            if addr == source and other_device and other_device != device:
                warning = self._warn(source, "same_time", [other_agent, agent])
                break
        last = self.seen.get(source)
        if warning is None and isinstance(last, dict) and last.get("device") and last["device"] != device \
                and now - int(last.get("last_ms", 0)) < ALTERNATE_MS:
            warning = self._warn(source, "alternate", [str(last.get("agent", "")), agent])
        self.seen[source] = {"device": device, "agent": agent, "last_ms": now}
        self._save()
        return warning

    def closed(self, source: str, device: str, agent: str) -> None:
        if device and private_address(source):
            self.seen[source] = {"device": device, "agent": agent, "last_ms": self.wall_ms()}
            self._save()

    def pattern(self, device: str, agent: str, period_ms: int) -> dict | None:
        """D3 : coupures très régulières sur un appareil (diagnostic « vpn_shared »)."""
        return self._warn("appareil " + device[:8], "pattern", [agent], period_ms=period_ms)

    def _warn(self, key: str, kind: str, agents: list[str], period_ms: int | None = None) -> dict | None:
        if not self.enabled or key in self.ignored:
            return None
        now = self.wall_ms()
        warning = {"address": key, "kind": kind, "agents": [a for a in agents if a] or ["appareil inconnu"],
                   "since_ms": now, "period_ms": period_ms}
        fresh = key not in self.warnings
        self.warnings[key] = warning
        if fresh:
            emit_event(codes.ORT_4503, logger=log, adresse=key, appareils=", ".join(warning["agents"]), type=kind,
                       periode_ms=period_ms)
        if self.alert is not None and now - int(self.alerted.get(key, 0)) >= ALERT_EVERY_MS:
            self.alerted[key] = now
            self._save()
            try:
                self.alert(codes.ORT_4503, text(warning))
            except Exception:                      # une alerte ratée ne gêne jamais la station
                emit_event(codes.ORT_8013, logger=log, trace=True, detail="ORT-4503 (profil VPN partagé)")
        return warning

    def ignore(self, address: str) -> None:
        if address not in self.ignored:
            self.ignored.append(address)
        self.warnings.pop(address, None)
        self._save()

    def active(self) -> list[dict]:
        now = self.wall_ms()
        for key in [k for k, w in self.warnings.items() if now - w["since_ms"] > WARNING_MS]:
            del self.warnings[key]
        return sorted(self.warnings.values(), key=lambda w: -w["since_ms"])

    def clear(self) -> None:
        self.seen, self.ignored, self.alerted, self.warnings = {}, [], {}, {}


def text(warning: dict) -> str:
    """Message de l'avertissement (alerte, journal) ; la page et l'application ont le leur, plus court."""
    agents = " / ".join(warning["agents"])
    if warning["kind"] == "pattern":
        period = round((warning.get("period_ms") or 0) / 1000)
        return (f"Coupures très régulières (toutes les ~{period} s) sur {agents}, signal correct : un autre appareil "
                f"partage probablement le même profil VPN. {ADVICE}")
    when = "en même temps" if warning["kind"] == "same_time" else "à quelques minutes d'écart"
    return (f"Deux appareils ({agents}) arrivent {when} par la même adresse {warning['address']}. S'ils passent par un "
            f"VPN, ils partagent probablement le même profil. {ADVICE}")
