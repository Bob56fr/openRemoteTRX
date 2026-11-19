# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Infos du poste montrées aux auditeurs de la diffusion (étape 248, repris du POC du 2026-11-17) : S-mètre, état
indicatif du squelch, largeur du filtre, voyants. Calculs purs : la passerelle les fait sur son état du poste et les
passe au module (paquet « ORDI », diffusion/audio.py) ; le module ne fait que les relayer au serveur.
"""
from __future__ import annotations

import math
from typing import Any


def width_text(hz: Any) -> str | None:
    """Largeur du filtre : 2400 -> « 2.4k », 500 -> « 500 » ; None si inconnue."""
    if not isinstance(hz, (int, float)) or isinstance(hz, bool) or hz <= 0:
        return None
    return f"{hz / 1000:.1f}k".replace(".0k", "k") if hz >= 1000 else str(int(hz))


def squelch_open(levels: dict, strength_db: Any, rms_db: float) -> bool | None:
    """État INDICATIF du squelch : None si le squelch n'est pas réglé (SQL = 0 ou inconnu), sinon True / False.
    SQL de 0 à 1 (échelle 0-255 du poste, celle du S-mètre : 120 = S9, 241 = S9+60 dB, squelchMarkerFraction de
    client.js). Ouvert = S-mètre au-dessus du seuil ET son reçu pas au silence (un poste qui coupe aussi son son USB
    tombe sous -70 dBFS squelch fermé)."""
    sql = levels.get("SQL") if isinstance(levels, dict) else None
    if not isinstance(sql, (int, float)) or isinstance(sql, bool) or sql <= 0:
        return None
    if not isinstance(strength_db, (int, float)) or isinstance(strength_db, bool):
        return None
    raw = min(1.0, float(sql)) * 255
    threshold = -54 + raw * 54 / 120 if raw <= 120 else (raw - 120) * 60 / 121
    return bool(strength_db >= threshold and rms_db > -70)


def indicators(functions: dict, levels: dict, split: Any, offsets: dict, preamps: tuple | list) -> list[list]:
    """TOUS les voyants que le poste publie, allumés ou éteints, dans l'ordre de la page de la station
    (indicatorsView de client.js) : [[texte, allumé], …]."""
    fn = functions if isinstance(functions, dict) else {}
    lv = levels if isinstance(levels, dict) else {}
    out: list[list] = []
    if "PREAMP" in lv:
        v = round(lv.get("PREAMP") or 0)
        out.append([f"P.AMP {list(preamps).index(v) + 1 if v in preamps else v}" if v > 0 else "P.AMP", v > 0])
    if "ATT" in lv:
        v = round(lv.get("ATT") or 0)
        out.append([f"ATT {v}" if v > 0 else "ATT", v > 0])
    if "RIT" in fn:
        off = (offsets or {}).get("RIT") or 0
        out.append([f"RIT {int(off):+d}" if fn["RIT"] else "RIT", bool(fn["RIT"])])
    if "XIT" in fn:
        out.append(["ΔTX", bool(fn["XIT"])])
    if isinstance(split, bool):
        out.append(["SPLIT", split])
    if "ANF" in fn or "MN" in fn:
        out.append(["NOTCH", bool(fn.get("ANF") or fn.get("MN"))])
    if "NB" in fn:
        out.append(["NB", bool(fn["NB"])])
    if "NR" in fn:
        out.append(["NR", bool(fn["NR"])])
    return out[:10]


def s_text(db: Any) -> str | None:
    """« S7 », « S9 », « S9+20 » (dB relatifs à S9, un point S = 6 dB, comme la page de la station)."""
    if not isinstance(db, (int, float)) or isinstance(db, bool) or math.isnan(db):
        return None
    if db >= 0.5:
        return f"S9+{min(99, round(db))}"
    return "S9" if db >= 0 else f"S{max(0, round(9 + db / 6))}"


def snapshot(state: Any, preamps: tuple | list, rms_db: float) -> dict:
    """Infos du poste à envoyer au module : {"s": dB ou None, "q": squelch, "w": filtre, "v": voyants, "off": poste
    éteint (fonction « power »)}."""
    s = getattr(state, "strength_db", None)
    s = float(s) if isinstance(s, (int, float)) and not isinstance(s, bool) else None
    if s is not None:
        s = max(-80.0, min(100.0, round(s, 1)))
    levels = getattr(state, "levels", None) or {}
    return {"s": s, "q": squelch_open(levels, s, rms_db) if s is not None else None,
            "w": width_text(getattr(state, "passband_hz", None)),
            "v": indicators(getattr(state, "functions", None) or {}, levels, getattr(state, "split", None),
                            getattr(state, "offsets", None) or {}, tuple(preamps or ())),
            "off": getattr(state, "power", None) == "off"}
