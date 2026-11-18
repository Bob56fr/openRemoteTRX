# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglages de menu d'un poste Icom LUS par le second port CI-V (commande 1A 05, LECTURE SEULE : la liste fermée de
civ.py n'accepte que la demande sans valeur). Les numéros de menu sont PROPRES À CHAQUE MODÈLE : table de données,
remplie à la qualification d'un poste d'après son manuel CI-V ; un modèle absent n'est pas vérifié.

Coupleur d'antenne (décision de l'utilisateur, 2026-11-19) : à distance, l'accord doit partir tout seul à la prise
d'émission sur une nouvelle fréquence. IC-7300MK2 (manuel CI-V, « SET > Function > Tuner ») : 00 37 = [TUNER] Switch
(00 Manual, 01 Auto = état du coupleur mémorisé par bande), 00 38 = PTT Start (00 OFF, 01 ON). La station ne les
écrit JAMAIS : elle prévient l'opérateur."""
from __future__ import annotations

# modèle Hamlib -> réglage -> (octets du menu après « 1A 05 », valeur attendue, nom affiché, libellé de la valeur attendue)
RIG_MENUS: dict[int, dict[str, tuple[bytes, int, str, str]]] = {
    3094: {   # Icom IC-7300MK2 (manuel CI-V relevé et lu sur le poste le 2026-11-19)
        "tuner_switch": (b"\x00\x37", 0x01, "[TUNER] Switch", "Auto"),
        "ptt_start": (b"\x00\x38", 0x01, "PTT Start", "ON"),
        # SET > Connectors > MOD Input > DATA MOD : source de la modulation en mode données (la voix de la station passe
        # par l'USB, seulement en PKTUSB / PKTLSB sur un Icom). Le poste n'accepte l'USB que dans DATA MOD OU DATA OFF MOD.
        "data_mod": (b"\x00\x85", 0x01, "DATA MOD", "USB"),
    },
}
TUNER_MENUS = ("tuner_switch", "ptt_start")
# valeurs affichées des réglages à liste (manuel CI-V de l'IC-7300MK2, 00 84 / 00 85)
VALUE_NAMES: dict[int, dict[str, dict[int, str]]] = {
    3094: {"data_mod": {0: "MIC", 1: "USB", 2: "ACC", 3: "MIC,USB", 4: "MIC,ACC", 5: "LAN"}},
}


def menu_reads() -> set[bytes]:
    """Toutes les demandes de lecture de la table (pour la liste fermée de civ.py)."""
    return {entry[0] for menus in RIG_MENUS.values() for entry in menus.values()}


def decode_menu(sub: bytes, payload: bytes) -> int | None:
    """Valeur d'une réponse « 1A 05 <menu> <valeur> » ; None si la trame ne répond pas à ce menu."""
    head = b"\x1a\x05" + sub
    if not payload.startswith(head) or len(payload) != len(head) + 1:
        return None
    return payload[-1]


def tuner_check(model: int, values: dict | None) -> tuple[str, dict]:
    """(« » si les réglages sont bons, « tuner_settings » avec la liste à revoir, « tuner_unverified » avec la raison)."""
    menus = RIG_MENUS.get(model)
    if menus is None or not all(m in menus for m in TUNER_MENUS):
        return "tuner_unverified", {"raison": "réglages de ce modèle pas encore relevés"}
    if not values:
        return "tuner_unverified", {"raison": "second port CI-V non réglé ou pas encore ouvert"}
    wrong = []
    for name in TUNER_MENUS:
        _, expected, label, wanted = menus[name]
        value = values.get(name)
        if value is None:
            return "tuner_unverified", {"raison": f"{label} illisible"}
        if value != expected:
            wrong.append(f"{label} à mettre sur {wanted}")
    return ("tuner_settings", {"reglages": ", ".join(wrong)}) if wrong else ("", {})


def data_mod_check(model: int, values: dict | None) -> tuple[str, dict]:
    """(« data_mod » avec la valeur lue si DATA MOD n'est pas sur la valeur attendue (USB), sinon « ») ; rien à dire si
    le modèle n'a pas ce réglage dans la table ou s'il n'a pas pu être lu (pas d'avis à chaque connexion sans port B)."""
    entry = RIG_MENUS.get(model, {}).get("data_mod")
    value = (values or {}).get("data_mod")
    if entry is None or value is None or value == entry[1]:
        return "", {}
    name = VALUE_NAMES.get(model, {}).get("data_mod", {}).get(value, f"valeur {value}")
    return "data_mod", {"valeur": name, "attendu": entry[3]}
