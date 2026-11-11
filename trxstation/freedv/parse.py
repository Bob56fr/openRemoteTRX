# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lecture des messages de radae_rx (rade_c) et de freedv-ka9q (freedv-integrations).

Formats relevés sur les VRAIS programmes (rade_c c8a3dc1, freedv-ka9q 2.4.1, 2026-11-10) :
  radae_rx -v 1 (une ligne par symbole OFDM, ~8 par seconde) :
    "2000 state:       sync valid: 1 0 25 Dthresh: ... fmax:   0.77 SNRdB:  6.80 uw_err: 0"
    "End-of-over detected"
  freedv-ka9q (sortie d'erreur) :
    "... rade_text.cpp:401: rxCRC: 63, calcCRC: 63, decodedStr: VK5KVA"
    "... ReportingController.cpp:228: Reporting RX callsign VK5KVA (SNR 19) to FreeDV Reporter"
Hors synchro, le SNR écrit par radae_rx n'a pas de sens (17 dB relevé sur du bruit) : il est ignoré.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RE_STATE = re.compile(r"state:\s+(search|candidate|sync)\b.*?fmax:\s*(-?[\d.]+)\s+SNRdB:\s*(-?[\d.]+)")
RE_EOO = re.compile(r"End-of-over")
RE_CALL = re.compile(r"Reporting RX callsign (\S+) \(SNR (-?\d+)\)")
RE_TEXT = re.compile(r"rxCRC:\s*(\d+),\s*calcCRC:\s*(\d+),\s*decodedStr:\s*(\S+)")
# Indicatif plausible : lettres et chiffres, '/' pour les préfixes et suffixes ; 3 à 12 caractères.
RE_CALLSIGN_OK = re.compile(r"^[A-Z0-9/]{3,12}$")


@dataclass(frozen=True)
class DemodState:
    state: str                 # "search", "candidate" ou "sync"
    snr_db: float | None       # seulement en synchro
    foff_hz: float | None      # décalage de fréquence, seulement en synchro


def parse_radae_line(line: str) -> DemodState | str | None:
    """DemodState pour une ligne d'état, "eoo" pour une fin d'émission, None sinon."""
    m = RE_STATE.search(line)
    if m:
        st = m.group(1)
        if st == "sync":
            return DemodState(st, float(m.group(3)), float(m.group(2)))
        return DemodState(st, None, None)
    if RE_EOO.search(line):
        return "eoo"
    return None


def clean_callsign(raw: str) -> str | None:
    cs = raw.strip().upper()
    return cs if RE_CALLSIGN_OK.match(cs) else None


def parse_ka9q_line(line: str) -> tuple[str, int | None] | None:
    """(indicatif, SNR) pour un indicatif décodé avec un CRC bon, None sinon.

    La ligne « Reporting RX callsign » suit « decodedStr » et porte le SNR ; « decodedStr » seul
    (CRC égaux) donne l'indicatif sans SNR. L'appelant ignore un doublon proche dans le temps.
    """
    m = RE_CALL.search(line)
    if m:
        cs = clean_callsign(m.group(1))
        return (cs, int(m.group(2))) if cs else None
    m = RE_TEXT.search(line)
    if m and m.group(1) == m.group(2):
        cs = clean_callsign(m.group(3))
        return (cs, None) if cs else None
    return None
