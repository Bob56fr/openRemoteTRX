# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Laboratoire CW (étape 413, docs/exp-cw/cahier-des-charges.md).

Lot CW-0 : calculs purs, sans réseau, sans poste, sans son réel.
- `protocol` : validation des paquets du canal `cw` (§ 5.2) ;
- `tone`     : tonalité recréée à l'échantillon près, fronts en cosinus surélevé (§ 4) ;
- `player`   : ordonnanceur du rejeu, ancre, ré-ancrage, bail, appui trop long (§ 5.3) ;
- `jitter`   : gigue mesurée et rejeu adaptatif entre séquences ;
- `sim`      : banc de simulation (manipulateur, client, réseau avec gigue, pertes, coupures) ;
- `analysis` : analyse du son produit (fronts, durées, clics, largeur occupée).
Rien ici ne touche au PTT : la passerelle (lot CW-1) lira `CwPlayer.silent` avant « T 0 ».
"""
