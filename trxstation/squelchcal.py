# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Étalonnage du squelch (étape 411, demande de l'utilisateur du 2026-11-28) : dix valeurs du réglage SQL de Hamlib
(0 à 1) relevées quand le poste AFFICHE un squelch sur 1, 2… 9, 9+10. La page et l'application en tirent la position
du repère orange au-dessus du S-mètre et une valeur décimale (« S5,4 ») par interpolation, le même rendu que l'afficheur
du poste dans tous les modes (FM compris, décision du 2026-11-28).

Priorité : étalonnage de la station (`[squelch_cal]` de station.toml, pour CE numéro Hamlib), sinon table du modèle
(fiche technique `rigspec`, tables envoyées par les opérateurs avec l'export du menu 2.10), sinon rien (repère
estimé d'avant). Calculs purs ; l'interpolation elle-même est faite par les clients (client.js, Radio.kt).
"""
from __future__ import annotations

import io
import json
import time
import zipfile

from . import __version__

LABELS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "9+10")   # ce qu'affiche le poste
LEVELS_DB = (-48, -42, -36, -30, -24, -18, -12, -6, 0, 10)        # mêmes niveaux, en dB par rapport à S9 (6 dB par S)
POINTS = len(LABELS)
SCHEMA = 1


def problem(points) -> str | None:
    """None si `points` est un étalonnage valable : 10 nombres de 0 à 1, strictement croissants."""
    if not isinstance(points, (list, tuple)) or len(points) != POINTS:
        return f"{POINTS} valeurs attendues"
    for v in points:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0:
            return "valeurs de 0 à 1 attendues"
    if any(float(b) <= float(a) for a, b in zip(points, points[1:])):
        return "valeurs strictement croissantes attendues (squelch tourné dans le bon sens)"
    return None


def effective(cfg, spec) -> dict | None:
    """Étalonnage envoyé aux clients (`hello.squelch_cal`) : {"points", "levels_db", "source"} ou None."""
    own = getattr(cfg, "squelch_cal", None)
    if own is not None and own.points and own.model == cfg.rig.model and problem(own.points) is None:
        return {"points": [round(float(v), 4) for v in own.points], "levels_db": list(LEVELS_DB), "source": "station"}
    table = tuple(getattr(getattr(spec, "squelch", None), "calibration", ()) or ())
    if table and problem(list(table)) is None:
        return {"points": [round(float(v), 4) for v in table], "levels_db": list(LEVELS_DB), "source": "model"}
    return None


def to_db(sql: float, points) -> float | None:
    """Niveau (dB / S9) du repère pour une valeur SQL : même calcul que les clients (tests croisés). None si ouvert."""
    if sql is None or sql <= 0:
        return None
    pts = [0.0, *[float(v) for v in points]]
    lv = [-54.0, *[float(v) for v in LEVELS_DB]]
    for i in range(1, len(pts)):
        if sql <= pts[i]:
            return lv[i - 1] + (sql - pts[i - 1]) * (lv[i] - lv[i - 1]) / (pts[i] - pts[i - 1])
    slope = (lv[-1] - lv[-2]) / (pts[-1] - pts[-2])
    return min(60.0, lv[-1] + (sql - pts[-1]) * slope)


def export_zip(model: int, rig_name: str, points, hamlib: str, now: float | None = None) -> bytes:
    """Zip à joindre à un ticket GitHub : poste, numéro Hamlib, version de Hamlib, les 10 valeurs ; ni numéro de
    série, ni adresse, ni nom de machine."""
    now = time.time() if now is None else now
    data = {"schema": SCHEMA, "kind": "squelch_calibration", "model": int(model), "rig": str(rig_name)[:60],
            "hamlib": str(hamlib)[:60], "station": __version__,
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "labels": list(LABELS), "levels_db": list(LEVELS_DB), "points": [round(float(v), 4) for v in points]}
    toml = (f"# Fiche technique (trxstation/rigspec/models/{int(model)}.toml), section [squelch]\n"
            f"calibration = [{', '.join(f'{float(v):.4f}' for v in points)}]\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("squelch-calibration.json", json.dumps(data, ensure_ascii=False, indent=1) + "\n")
        z.writestr("rigspec-extrait.toml", toml)
    return buf.getvalue()
