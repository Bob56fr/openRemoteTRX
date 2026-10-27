# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Clés publiques Ed25519 acceptées pour les paquets de mise à jour (32 octets bruts en base64).

La clé privée correspondante n'est JAMAIS dans le dépôt : elle reste sur le PC de l'auteur
(scripts/gen_update_key.py). Plusieurs clés peuvent être listées pour changer de clé sans
couper la chaîne : on ajoute la nouvelle, on publie, puis on retire l'ancienne.
Liste vide = aucune mise à jour automatique possible (toute signature est refusée).
"""
from __future__ import annotations

PUBLIC_KEYS: tuple[str, ...] = (
    "+OHSKZvVD/FJegCBdXi21HcBRdNvBhvsVQhbLu5adGY=",
)
