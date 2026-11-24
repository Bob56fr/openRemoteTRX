# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Tableau de bord des signes vitaux de la station (étape 385), en LECTURE SEULE.

Programme à part de la passerelle (service trx-dashboard, compte trx) : lit les fichiers que la station publie
(état de la passerelle, mise en sécurité, modules, journaux), mesure l'ordinateur et l'accès à Internet, garde 24 h
d'historique et sert une page pour le mini écran 960×480 de la station (127.0.0.1, mode kiosque) et pour un téléphone
par le VPN (HTTPS, sans clé d'accès : décision du 2026-11-24). Aucune commande vers le poste, rigctld ou la passerelle. Réglages : [dashboard].
"""
from .. import __version__

__all__ = ["__version__"]
