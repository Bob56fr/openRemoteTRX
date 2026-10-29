# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Aides de configuration propres à une famille de postes (trx-setup) : débit, PTT, menus du poste, port USB à choisir.

Ce ne sont que des PROPOSITIONS de l'assistant (aucun code de pilotage propre à un modèle : tout passe par Hamlib).
Yaesu FTDX10 / FTDX101D / FTDX101MP : d'après le manuel CAT du FTDX10 et les capacités Hamlib (1042, 1040, 1044),
NON VALIDÉ sur un vrai poste (voir docs/postes/yaesu-ftdx10-ftdx101.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RigHint:
    name: str
    speed: int                        # débit proposé (doit être celui du menu CAT RATE du poste)
    ptt_type: str                     # méthode PTT proposée
    usb_voice_question: str           # question : la voix (BLU, FM...) part-elle aussi par l'USB ?
    checklist: tuple[str, ...]        # menus du poste à régler avant d'aller plus loin


_YAESU_CHECKLIST = (
    "CAT RATE = 38400 bps (même valeur que le débit ci-dessous)",
    "CAT TIME OUT = 1000 msec ; CAT RTS = ON (Hamlib utilise le contrôle de flux RTS/CTS)",
    "Port CAT = « Enhanced COM Port » (Silicon Labs CP2105) ; jamais le « Standard COM Port » pour le CAT",
    "RPTT SELECT : ni RTS ni DTR si le PTT passe par CAT (une ligne RTS/DTR mal placée peut mettre le poste en émission)",
    "SSB MOD SOURCE = REAR, AM MOD SOURCE = REAR, FM MOD SOURCE = REAR, DATA MOD SOURCE = REAR ; REAR SELECT = USB",
    "USB MOD GAIN / RPORT GAIN : à régler avec l'ALC (réglage automatique SELCALL ou voyant OVERLOAD ALC)",
    "TX TIME OUT TIMER du poste : 3 min (seconde sécurité, en plus du TOT de la station)",
    "Pas de spectre HF dans l'application avec ce poste (Yaesu n'envoie pas les données du scope par CAT) : spectre audio seul",
)

HINTS: dict[int, RigHint] = {
    model: RigHint(name=name, speed=38400, ptt_type="RIG", checklist=_YAESU_CHECKLIST,
                   usb_voice_question="SSB MOD SOURCE (et AM, FM) = REAR et REAR SELECT = USB sont réglés sur le poste")
    for model, name in ((1042, "Yaesu FTDX10"), (1040, "Yaesu FTDX101D"), (1044, "Yaesu FTDX101MP"))
}

# Double port USB Silicon Labs CP2105 (Yaesu FTDX10, FTDX101, FT-991A, FT-710...) : interface 0 = « Enhanced » (CAT),
# interface 1 = « Standard » (PTT/CW par RTS/DTR). Noms stables Linux : ...CP2105..._<série>-if00-port0 / -if01-port0.
_CP2105 = re.compile(r"CP2105.*-if(\d\d)", re.IGNORECASE)


def hint_for(model: int) -> RigHint | None:
    return HINTS.get(model)


def port_role(port: str) -> str:
    """« enhanced » (CAT), « standard » (PTT/CW, pas de CAT) ou « » (inconnu : Windows, autre interface)."""
    match = _CP2105.search(port)
    if not match:
        return ""
    return {"00": "enhanced", "01": "standard"}.get(match.group(1), "")


def port_label(port: str) -> str:
    role = port_role(port)
    if role == "enhanced":
        return f"{port}   <- Enhanced COM Port : CAT"
    if role == "standard":
        return f"{port}   (Standard COM Port : PTT/CW, pas le CAT)"
    return port


def windows_port_advice() -> str:
    return ("Sous Windows : Gestionnaire de périphériques > Ports (COM et LPT) : prendre le port nommé "
            "« Silicon Labs Dual CP2105 USB to UART Bridge: Enhanced COM Port » pour le CAT.")
