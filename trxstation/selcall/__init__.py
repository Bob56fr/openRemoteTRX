# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""SELCALL : squelch numérique par appel sélectif de groupe, utilisable en BLU (docs/selcall-cahier-des-charges.md).

- `protocol` : constantes et construction de la trame (Python pur) ;
- `signal` : générateur audio (numpy), réutilisé pour l'émission et les essais ;
- `decoder` : décodeur en flux (numpy), tolérant ±300 Hz de décalage.
"""
