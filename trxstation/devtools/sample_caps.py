# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Exemple de sortie `rigctl -u` (dump_caps), cohérent avec FakeRigctld, pour tester la qualification.

Inspiré du format de Hamlib 4.x (tabulation après les deux-points). Ce n'est PAS la sortie exacte
d'un vrai poste : toute hypothèse sur le format réel doit être vérifiée avec un vrai rigctl.
"""

SAMPLE_DUMP_CAPS = """Caps dump for model: 3094
Model name:\tIC-7300MK2
Mfg name:\tIcom
Hamlib version:\tHamlib 4.6.2 2025-01-15
Backend version:\t20240511.0
Backend copyright:\tLGPL
Backend status:\tStable
Rig type:\tTransceiver
PTT type:\tRig capable
Port type:\tRS-232
Get functions:\tNB COMP VOX TONE TSQL ANF NR MON MN RF LOCK TUNER AIP SCOPE
Set functions:\tNB COMP VOX TONE TSQL ANF NR MON MN RF LOCK TUNER AIP SCOPE
Extra functions:
Get level:\tPREAMP(0..20/10) ATT(0..20/20) AF(0..1/0.00392157) RF(0..1/0.00392157) SQL(0..1/0.00392157) RFPOWER(0..1/0.00392157) MICGAIN(0..1/0.00392157) AGC(0..6/0) STRENGTH(-54..60/0) RFPOWER_METER(0..1/0.00392157) COMP_METER(0..1/0.00392157) VD_METER(0..1/0.00392157) ID_METER(0..1/0.00392157) SWR(0..1/0.00392157) ALC(0..1/0.00392157) TEMP_METER(0..1/0.00392157)
Set level:\tPREAMP(0..20/10) ATT(0..20/20) AF(0..1/0.00392157) RF(0..1/0.00392157) SQL(0..1/0.00392157) RFPOWER(0..1/0.00392157) MICGAIN(0..1/0.00392157) AGC(0..6/0)
Extra levels:
Mode list:\tAM CW USB LSB RTTY FM CWR RTTYR PKTLSB PKTUSB PKTFM PKTAM
VFO list:\tVFOA VFOB MEM
Preamp:\t10dB 20dB
Attenuator:\t20dB
AGC levels:\t1=FAST 2=MEDIUM 3=SLOW
Bandwidths:
\tUSB\tNormal: 2.4 kHz,\tNarrow: 1.8 kHz,\tWide: 3 kHz
\tLSB\tNormal: 2.4 kHz,\tNarrow: 1.8 kHz,\tWide: 3 kHz
\tCW\tNormal: 500 Hz,\tNarrow: 250 Hz,\tWide: 1.2 kHz
Can set Frequency:\tY
Can get Frequency:\tY
Can set Mode:\tY
Can get Mode:\tY
Can set VFO:\tY
Can get VFO:\tN
Can set PTT:\tY
Can get PTT:\tY
Can get DCD:\tN
Can set Split VFO:\tE
"""
