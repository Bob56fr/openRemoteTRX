# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Analyse des lignes « DX de » (DXSpider, AR-Cluster, CC Cluster, RBN).

Formats observés (colonnes variables, on ne s'y fie pas) :

    DX de F5XYZ:     14025.0  K1ABC        CW 599 tnx                     1847Z JN18
    DX de DL1ABC-12:14025.0  K1ABC        up 2                           1847Z
    DX de W3LPL:     14025.0  K1ABC        CW                             1847Z MD
    DX de DK8NE-#:   14025.10 OH2BH        CW    18 dB  25 WPM  CQ        1847Z
    DX de KM3T-#:    14074.0  JA1XXX       FT8   -12 dB  CQ               1847Z

Une ligne qui commence par « DX de » mais ne se lit pas est « mal formée » :
le flux continue et l'appelant la compte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import base_call, is_callsign

PREFIX = "DX de "
MAX_COMMENT = 60

_LINE_RE = re.compile(
    r"DX de\s+(?P<spotter>[A-Za-z0-9/#\-]{3,20}):\s*"
    r"(?P<freq>\d{2,8}(?:\.\d{1,3})?)\s+"
    r"(?P<dx>[A-Za-z0-9/]{3,20})"
    r"(?:\s+(?P<comment>.*?))?\s+"
    r"(?P<hh>\d{2})(?P<mm>\d{2})Z"
    r"(?:\s+(?P<extra>[A-Za-z0-9/<>\-]{1,14}))?\s*$")

# nom lu dans le spot -> mode suivi (bandplan.MODES) ou numérique à écarter (bandplan.DIGITAL)
_MODE_WORDS = {
    "CW": "CW", "SSB": "SSB", "USB": "SSB", "LSB": "SSB", "PH": "SSB", "PHONE": "SSB",
    "FM": "FM", "AM": "AM", "FREEDV": "FREEDV", "FDV": "FREEDV",
    "RTTY": "RTTY", "FT8": "FT8", "FT4": "FT4",
    "PSK": "DIGI", "PSK31": "DIGI", "PSK63": "DIGI", "BPSK": "DIGI", "BPSK31": "DIGI",
    "JT65": "DIGI", "JT9": "DIGI", "MSK144": "DIGI", "Q65": "DIGI", "JS8": "DIGI",
    "OLIVIA": "DIGI", "SSTV": "DIGI", "HELL": "DIGI", "MFSK": "DIGI", "DIGI": "DIGI",
    "DATA": "DIGI", "FSK441": "DIGI", "WSPR": "DIGI", "VARAC": "DIGI",
}
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class RawSpot:
    freq_khz: float
    dx: str
    spotter: str              # sans SSID ni « -# »
    mode: str | None          # lu dans le spot (bandplan.MODES ou DIGITAL) ; None = non indiqué
    comment: str
    time_utc: str             # « HHMM »
    skimmer: bool             # spotteur automatique (RBN, « -# »)


def is_dx_line(line: str) -> bool:
    return line.lstrip().startswith(PREFIX)


def mode_in(comment: str) -> str | None:
    """Premier mot du commentaire qui nomme un mode."""
    for word in _WORD_RE.findall(comment.upper()):
        if word in _MODE_WORDS:
            return _MODE_WORDS[word]
    return None


def parse_dx_line(line: str) -> RawSpot | None:
    """RawSpot, ou None si la ligne n'est pas un spot lisible."""
    m = _LINE_RE.fullmatch(line.strip())
    if m is None:
        return None
    hh, mm = int(m["hh"]), int(m["mm"])
    if hh > 23 or mm > 59:
        return None
    try:
        freq = float(m["freq"])
    except ValueError:
        return None
    if not 100.0 <= freq <= 300_000_000.0:          # 100 kHz .. 300 GHz
        return None
    dx = m["dx"].upper()
    raw_spotter = m["spotter"].upper()
    spotter = base_call(raw_spotter)
    if not is_callsign(dx) or not is_callsign(spotter):
        return None
    comment = " ".join((m["comment"] or "").split())[:MAX_COMMENT]
    return RawSpot(freq_khz=freq, dx=dx, spotter=spotter, mode=mode_in(comment), comment=comment,
                   time_utc=f"{hh:02d}{mm:02d}", skimmer=raw_spotter.endswith("-#"))
