# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglage automatique du niveau de la trame SELCALL d'après l'ALC du poste (demande de l'utilisateur, 2026-10-29).

Une ÉMISSION ordinaire du client (PttController.send_selcall : mêmes vérifications que le PTT, micro du client
fermé, toute coupure l'interrompt) : un ton à F0 monte par paliers de 2 dB depuis -30 dBFS ; à chaque palier, l'ALC
est relu (la passerelle le lit pendant toute émission). Dès que l'ALC décolle de son niveau de départ (ou dépasse le
seuil de surcharge), on s'arrête ; le niveau retenu est le dernier palier propre MOINS 2 dB de marge.

En modes données (USB-D…), un signal propre ne fait pas agir l'ALC : c'est le critère. Seuils à ajuster après
essais sur le poste (`ALC_RISE`, `ALC_OVERLOAD`).
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

STEPS_DBFS = tuple(range(-30, 0, 2))     # -30, -28, ..., -2
DWELL_S = 1.2                            # par palier : l'ALC est relu au moins une fois (environ toutes les 0,75 s)
ALC_RISE = 0.1                           # l'ALC décolle de son niveau de départ
ALC_OVERLOAD = 0.5                       # surcharge (même seuil que le voyant « OVERLOAD ALC » des clients)
MARGIN_DB = 2.0
LEVEL_MIN, LEVEL_MAX = -30.0, -3.0
TONE_HZ = 1000.0


def duration_s(steps=STEPS_DBFS, dwell=DWELL_S) -> float:
    return len(steps) * dwell


def decide(samples: list[tuple[float, float | None]]) -> tuple[float | None, str]:
    """Paliers mesurés (niveau dBFS, ALC lu ou None) -> (niveau retenu ou None, explication)."""
    readable = [(lvl, alc) for lvl, alc in samples if alc is not None]
    if not readable:
        return None, "ALC illisible sur ce poste : niveau inchangé"
    base = readable[0][1]
    clean = None
    for lvl, alc in readable:
        if alc >= ALC_OVERLOAD or alc - base >= ALC_RISE:
            if clean is None:
                return LEVEL_MIN, f"l'ALC agit dès {lvl:g} dBFS : niveau au plus bas ({LEVEL_MIN:g} dBFS), réduisez le gain d'entrée du poste"
            level = max(LEVEL_MIN, min(LEVEL_MAX, clean - MARGIN_DB))
            return level, f"l'ALC agit à {lvl:g} dBFS (ALC {round(alc * 100)} %) : niveau réglé à {level:g} dBFS"
        clean = lvl
    level = max(LEVEL_MIN, min(LEVEL_MAX, clean - MARGIN_DB))
    return level, f"l'ALC n'a pas agi jusqu'à {clean:g} dBFS : niveau réglé à {level:g} dBFS"


async def run(play_step: Callable[[float, float], Awaitable[None]], read_alc: Callable[[], float | None],
              progress: Callable[[str], None], steps=STEPS_DBFS, dwell: float = DWELL_S) -> tuple[float | None, str]:
    """Joue les paliers (`play_step(niveau, durée)`), relit l'ALC à la fin de chacun, s'arrête dès qu'il agit."""
    samples: list[tuple[float, float | None]] = []
    for lvl in steps:
        progress(f"réglage {lvl:g} dBFS")
        await play_step(float(lvl), dwell)
        alc = read_alc()
        samples.append((float(lvl), alc))
        progress(f"réglage {lvl:g} dBFS : ALC " + ("?" if alc is None else f"{round(alc * 100)} %"))
        if alc is not None and samples[0][1] is not None and (alc >= ALC_OVERLOAD or alc - samples[0][1] >= ALC_RISE):
            break
        await asyncio.sleep(0)
    return decide(samples)
