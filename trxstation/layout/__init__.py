# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mises en page de l'interface (designer) : format, validation, cascade des variantes, profil d'usine, stockage.

Un PROFIL décrit l'interface d'un utilisateur pour trois catégories d'appareils (smartphone, tablette,
ordinateur). Il est purement déclaratif (JSON) : il ne contient jamais de code, et il ne donne aucun droit.
La station applique ses règles de sécurité quel que soit le profil ; le profil ne fait que les PRÉSENTER.
Voir le cahier des charges « Designer d'interface Remote TRX ».
"""
from __future__ import annotations

from .cascade import select_variant
from .catalog import DEVICES, FORMAT_VERSION, GRID_COLUMNS, ORIENTATIONS, TARGETS, WIDGETS
from .factory import factory_profile
from .store import LayoutInvalid, LayoutStorageError, LayoutStore
from .validate import Report, validate_profile

__all__ = ["DEVICES", "FORMAT_VERSION", "GRID_COLUMNS", "ORIENTATIONS", "TARGETS", "WIDGETS", "LayoutInvalid",
           "LayoutStorageError", "LayoutStore", "Report", "factory_profile", "select_variant", "validate_profile"]
