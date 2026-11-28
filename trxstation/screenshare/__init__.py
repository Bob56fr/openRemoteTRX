# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Écran partagé de TRX Console (étape 403, docs/protocole-ecran.md) : l'opérateur aidé montre sa console texte à
un aidant, en LECTURE SEULE, par le relais de rf-diy.com.

- `calc` : calculs purs (code dicté, clés, images chiffrées, bande de l'écran) ;
- `relay` : transport vers le relais (POST JSON, aiohttp dans un fil à part) ;
- `share` : côté opérateur aidé, Linux seulement (console relancée dans un pseudo-terminal) ;
- `view` : côté aidant (Linux et Windows).

Rien ne remonte de l'aidant vers la station : aucune touche, aucune commande.
"""
