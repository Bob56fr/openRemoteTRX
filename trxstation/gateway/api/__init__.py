# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""API client de la passerelle : authentification, protocole de commandes, session de contrôle.

La logique (auth, protocole, session) ne dépend d'aucune bibliothèque réseau. Le transport
WebRTC (webrtc.py) et la signalisation HTTP (server.py) sont de fines couches par-dessus.
"""
