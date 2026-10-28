# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Température du poste (TEMP_METER de Hamlib) : avertissement, puis coupure de l'émission à distance.

Seuils dans station.toml ([safety] rig_temp_warn_c, rig_temp_cut_c ; 40 et 50 °C par défaut), réglables par
TRX Console. Niveaux :
  * "" : rien à signaler, ou température inconnue (poste sans TEMP_METER, comme l'IC-7300MK2 sous Hamlib) ;
  * "warn" : au moins rig_temp_warn_c ; la page l'affiche, le superviseur prévient (ntfy) ;
  * "hot" : au moins rig_temp_cut_c ; l'émission À DISTANCE est coupée et refusée (`rig_hot`). On n'en sort
    qu'avec une mesure revenue SOUS rig_temp_warn_c (hystérésis : pas de reprise à 49,9 °C).
Une mesure aberrante (hors MIN_C..MAX_C) est ignorée. Une mesure qui ne vient plus ne fait pas sortir de "hot".
Rien ici ne commande le poste : ce module ne fait que juger.
"""
from __future__ import annotations

import math

MIN_C, MAX_C = -40.0, 150.0      # en dehors : lecture fausse (échelle inconnue, poste muet), ignorée


class ThermalGuard:
    def __init__(self, warn_c: float, cut_c: float):
        if not warn_c < cut_c:
            raise ValueError("il faut rig_temp_warn_c < rig_temp_cut_c")
        self.warn_c, self.cut_c = float(warn_c), float(cut_c)
        self.level = ""
        self.temp_c: float | None = None

    @property
    def hot(self) -> bool:
        return self.level == "hot"

    def observe(self, value) -> bool:
        """Nouvelle mesure (ou None). Renvoie True si le niveau a changé."""
        if value is None or isinstance(value, bool):
            return False
        try:
            temp = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(temp) or not MIN_C <= temp <= MAX_C:
            return False
        self.temp_c = temp
        before = self.level
        if temp >= self.cut_c:
            self.level = "hot"
        elif self.level == "hot" and temp >= self.warn_c:
            pass                                    # hystérésis : reste coupé tant qu'on n'est pas sous le 1er seuil
        else:
            self.level = "warn" if temp >= self.warn_c else ""
        return self.level != before
