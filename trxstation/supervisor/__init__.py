# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Superviseur autonome : seconde couche de sécurité, indépendante de la passerelle.

Volontairement minimal : bibliothèque standard uniquement, synchrone, un seul fil. Il
n'importe RIEN de la passerelle (pas de code partagé qui pourrait porter le même bug) ;
il ne partage que la configuration et le format du fichier d'état.
"""
