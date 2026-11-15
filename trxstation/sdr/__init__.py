# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module SDR (docs/sdr-cahier-des-charges.md) : récepteur SDR en parallèle du TRX, RÉCEPTION SEULE.

- core/sdr_core.c : cœur natif (API du fabricant, FFT liquid-dsp), compilé par install.sh ;
- frames.py : trames écrites par sdr-core ;
- devices.py : liste des SDR (libres / pris) et commande trx-sdr ;
- service.py : module « sdr » (lancé par le superviseur, parle au cœur par le bus des modules).
Le module n'a AUCUN droit sur le poste : « envoyer cette fréquence au TRX » est une commande du client.
"""
