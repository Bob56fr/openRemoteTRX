# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Choix de la variante à afficher sur un appareil (§3 du cahier des charges).

Règle : chaque appareil utilise sa propre variante, sinon la plus proche EN DESSOUS ; la cascade ne descend
jamais (une interface d'ordinateur n'est pas affichée sur un téléphone). S'il n'existe aucune variante de
taille inférieure ou égale, l'interface ne se charge pas : le client affiche l'écran de sécurité minimal.
Une variante plus petite n'est jamais étirée : elle est affichée à sa largeur, centrée (« centered »).
"""
from __future__ import annotations

from dataclasses import dataclass

from .catalog import DEVICES, ORIENTATIONS


@dataclass(frozen=True)
class Choice:
    device: str             # variante retenue
    orientation: str        # orientation retenue dans cette variante
    display: str            # "native" | "centered" (variante plus petite ou autre orientation) | "rotate" (tourner l'appareil)

    def to_dict(self) -> dict:
        return {"device": self.device, "orientation": self.orientation, "display": self.display}


def select_variant(variants: dict, device: str, orientation: str, forced: str | None = None) -> Choice | None:
    """Variante à afficher, ou None : aucune variante utilisable => écran de sécurité.

    `forced` : catégorie choisie par l'utilisateur ; acceptée seulement si elle n'est pas plus grande que l'appareil.
    """
    if device not in DEVICES or orientation not in ORIENTATIONS:
        raise ValueError("appareil ou orientation inconnu")
    effective = device
    if forced in DEVICES and DEVICES.index(forced) <= DEVICES.index(device):
        effective = forced
    for candidate in reversed(DEVICES[:DEVICES.index(effective) + 1]):
        available = variants.get(candidate) if isinstance(variants, dict) else None
        if not isinstance(available, dict) or not available:
            continue
        smaller = candidate != device
        if orientation in available:
            return Choice(candidate, orientation, "centered" if smaller else "native")
        if orientation == "landscape" and "portrait" in available:
            return Choice(candidate, "portrait", "centered")            # le portrait s'affiche centré en paysage
        if orientation == "portrait" and "landscape" in available:
            return Choice(candidate, "landscape", "rotate")             # trop étroit : demander de tourner l'appareil
    return None
