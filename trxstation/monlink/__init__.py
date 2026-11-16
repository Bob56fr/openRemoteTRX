# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Monitoring inter-stations (docs/cdc-monitoring.md, § 17 : mode R, boîte aux lettres chiffrée sur le relais).

Lot R1 : calculs purs, sans réseau ni fichier d'état (identité, code d'invitation, appairage, empreinte, clé de
liaison, enveloppes, anti-rejeu, profils d'envoi, masquage). Contrat avec le relais : docs/protocole-monlink.md,
vecteurs tests/protocol/monlink_vectors.json (python -m trxstation.monlink.vectors).

Ce paquet ne parle JAMAIS au poste : ni PTT, ni CAT, ni porte audio (test « never touches »). Il ne transporte que
de la télémétrie et des journaux, dans le sens que l'opérateur de la station surveillée a accepté.
"""
