"""Profil d'usine : la page de contrôle actuelle (étapes 16-17) décrite dans le format de mise en page.

Il est livré avec la station et toujours disponible : un nouvel utilisateur n'est jamais bloqué (§3).
Variante smartphone en portrait seulement : en paysage, elle s'affiche centrée ; tablette et ordinateur
l'utilisent par cascade. Partie haute fixe (état, fréquence, mesures, commandes, PTT), puis un accordéon.
Un fichier témoin (`tests/js/factory_profile.json`) en est la copie lue par les tests du navigateur.
"""
from __future__ import annotations

import copy

from .catalog import FORMAT_VERSION


def _w(wid: str, kind: str, x: int, y: int, w: int, h: int, **extra) -> dict:
    return {"id": wid, "type": kind, "x": x, "y": y, "w": w, "h": h, **extra}


_PHONE_PORTRAIT = [
    _w("mode", "mode", 0, 0, 3, 1),
    _w("link", "link_status", 3, 0, 1, 1),
    _w("freq", "frequency", 0, 1, 4, 1),
    _w("smeter", "smeter", 0, 2, 4, 1),
    _w("txzone", "layers", 0, 3, 4, 2, gestures={"next_layer": "tap", "next_group": "double_tap"}, groups=[[
        {"title": "Émission", "widgets": [
            _w("po", "meter", 0, 0, 4, 1, bind="RFPOWER_METER", label="Po"),
            _w("swr", "meter", 0, 1, 2, 1, bind="SWR", label="SWR"),
            _w("alc", "meter", 2, 1, 2, 1, bind="ALC", label="ALC"),
        ]},
        {"title": "Waterfall audio", "widgets": [_w("wf", "waterfall", 0, 0, 4, 2)]},
    ]]),
    _w("nr", "switch", 0, 5, 1, 1, bind="NR", label="NR"),
    _w("nb", "switch", 1, 5, 1, 1, bind="NB", label="NB"),
    _w("preamp", "select", 2, 5, 1, 1, bind="PREAMP", appearance="cycle", label="P.AMP"),
    _w("aip", "switch", 3, 5, 1, 1, bind="AIP", label="IP+"),
    _w("agc", "select", 0, 6, 1, 1, bind="AGC", appearance="cycle", label="AGC"),
    _w("comp", "switch", 1, 6, 1, 1, bind="COMP", label="COMP"),
    _w("fil", "filter", 2, 6, 1, 1, label="FIL"),
    _w("tuner", "switch", 3, 6, 1, 1, bind="TUNER", label="TUNER"),
    _w("pwr", "select", 0, 7, 1, 1, bind="RFPOWER", appearance="cycle", label="PWR"),

    _w("ptt", "ptt", 0, 8, 3, 2),
    _w("stop", "stop", 3, 8, 1, 2),
    _w("armed", "tx_armed", 0, 10, 2, 1),
    _w("sql", "slider", 2, 10, 2, 1, bind="SQL", label="SQL"),
    _w("tx", "tx_indicator", 0, 11, 2, 1),
    _w("tot", "tot", 2, 11, 2, 1),
    _w("more", "accordion", 0, 12, 4, 1, sections=[
        {"title": "Accord", "open": True, "widgets": [
            _w("bands", "bands", 0, 0, 4, 1),
            _w("steps", "steps", 0, 1, 4, 1),
            _w("freq-entry", "frequency", 0, 2, 4, 1, appearance="field"),
            _w("mode-entry", "mode", 0, 3, 4, 1, appearance="select"),
        ]},
        {"title": "Mémoires", "open": True, "widgets": [_w("mem", "memories", 0, 0, 4, 2)]},
    ]),
]

_FACTORY = {
    "format": FORMAT_VERSION,
    "name": "Interface d'usine",
    "rig_model": None,
    "theme": {"preset": "icom", "dark": True},
    "fonts": {"ui": "system", "display": "system", "numeric": "system", "base_size": 16},
    "variants": {"phone": {"portrait": {"widgets": _PHONE_PORTRAIT}}},
}


def factory_profile() -> dict:
    """Copie neuve du profil d'usine (le modifier n'altère jamais l'original)."""
    return copy.deepcopy(_FACTORY)
