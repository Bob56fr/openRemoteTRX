# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Présence de groupe (docs/presence-cahier-des-charges.md), lot 1 : calculs purs.

- codec    : base64url, JSON compact, identifiants ;
- crypto   : Ed25519, X25519, XChaCha20-Poly1305 (HChaCha20 + ChaCha20-Poly1305), sceau d'une clé ;
- identity : clés et identifiant de la station, fichier `presence.key` ;
- pow      : preuve de travail de l'enregistrement ;
- wire     : signature des requêtes au relais, filtres du pseudo et du texte libre ;
- status   : statut de l'opérateur (En QSO, En RX, Au shack, Absent), tri, âge lisible ;
- state    : état publié dans un groupe, signé puis chiffré, de taille fixe ;
- roster   : liste des membres signée par un administrateur ;
- invite   : invitation, demande d'adhésion, clé de groupe remise à un membre ;
- vectors  : vecteurs partagés avec le relais (tests/protocol/presence_vectors.json).

Ce paquet n'a AUCUN droit sur le poste : il n'importe ni la sécurité d'émission, ni le CAT, ni la passerelle
(un test l'impose).
"""
