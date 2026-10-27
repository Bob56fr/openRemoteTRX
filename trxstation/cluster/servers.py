# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Serveurs proposés par défaut.

VÉRIFIÉS LE 2026-10-27 depuis le PC de développement (connexion TCP et
bannière lue, rien envoyé ; page clusterdx.org lue). Ces adresses changent :
à revérifier à chaque livraison (`python -m trxstation.cluster
--verifier-serveurs`, qui ne fait que lire la bannière ou la page).

Le RBN FT8 (port 7001) n'est PAS proposé : les modes numériques sont hors
périmètre (décision de l'utilisateur, 2026-10-27).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import clusterdx

VERIFIED_ON = "2026-10-27"


@dataclass(frozen=True)
class KnownServer:
    name: str
    kind: str          # « telnet » (cluster), « rbn » ou « web »
    host: str
    port: int
    software: str      # dxspider, ar, cc, rbn, web
    where: str
    url: str = ""

    @property
    def address(self) -> str:
        return self.url if self.kind == "web" else f"{self.host}:{self.port}"


KNOWN: tuple[KnownServer, ...] = (
    KnownServer("on0dxk", "telnet", "on0dxk.dyndns.org", 8000, "cc", "Belgique"),
    KnownServer("db0sue", "telnet", "db0sue.de", 8000, "dxspider", "Allemagne"),
    KnownServer("dxspider-uk", "telnet", "dxspider.co.uk", 7300, "dxspider", "Royaume-Uni"),
    KnownServer("hamserve", "telnet", "dxc.hamserve.uk", 7300, "dxspider", "Royaume-Uni"),
    KnownServer("w3lpl", "telnet", "dxc.w3lpl.net", 7373, "dxspider", "États-Unis"),
    KnownServer("ve7cc", "telnet", "dxc.ve7cc.net", 23, "cc", "Canada"),
    KnownServer("nc7j", "telnet", "dxc.nc7j.com", 7373, "ar", "États-Unis"),
    KnownServer("rbn-cw", "rbn", "telnet.reversebeacon.net", 7000, "rbn", "RBN : CW (le RTTY est écarté)"),
    KnownServer("clusterdx", "web", "", 0, "web", "Cluster DX des cibistes, 11 m", url=clusterdx.URL),
)


def by_name(name: str) -> KnownServer | None:
    return next((s for s in KNOWN if s.name == name), None)
