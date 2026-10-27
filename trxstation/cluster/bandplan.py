"""Bandes et plan de bande IARU Région 1 (simplifié) : bande d'une fréquence, mode probable.

Le mode n'est déduit de la fréquence que si le spot ne le donne pas. Les
segments sont ceux du plan IARU R1 (télégraphie en bas de bande, numérique,
puis phonie) ; FT8 et FT4 sont reconnus à 3 kHz au-dessus de leur fréquence
d'appel. Une déduction reste une supposition : le spot la marque comme telle.
"""

from __future__ import annotations

# nom, début kHz, fin kHz (Région 1)
BANDS: tuple[tuple[str, float, float], ...] = (
    ("2200m", 135.7, 137.8),
    ("630m", 472.0, 479.0),
    ("160m", 1810.0, 2000.0),
    ("80m", 3500.0, 3800.0),
    ("60m", 5351.5, 5366.5),
    ("40m", 7000.0, 7200.0),
    ("30m", 10100.0, 10150.0),
    ("20m", 14000.0, 14350.0),
    ("17m", 18068.0, 18168.0),
    ("15m", 21000.0, 21450.0),
    ("12m", 24890.0, 24990.0),
    ("11m", 25615.0, 27995.0),        # CB et fréquences des cibistes DX (source clusterdx.org)
    ("10m", 28000.0, 29700.0),
    ("6m", 50000.0, 52000.0),
    ("4m", 70000.0, 70500.0),
    ("2m", 144000.0, 146000.0),
    ("70cm", 430000.0, 440000.0),
    ("23cm", 1240000.0, 1300000.0),
)
BAND_NAMES = tuple(b[0] for b in BANDS)

# fréquences d'appel (kHz) ; le signal est entre f et f + 3 kHz
FT8_DIALS = (1840.0, 3573.0, 5357.0, 7074.0, 10136.0, 14074.0, 18100.0, 21074.0,
             24915.0, 28074.0, 50313.0, 70154.0, 144174.0)
FT4_DIALS = (3575.5, 7047.5, 10140.0, 14080.0, 18104.0, 21140.0, 24919.0, 28180.0, 50318.0, 144170.0)

# fin du segment CW, puis fin du segment « numérique » (au-delà : phonie)
_SEGMENTS: dict[str, tuple[float, float]] = {
    "160m": (1838.0, 1843.0),
    "80m": (3570.0, 3600.0),
    "60m": (5354.0, 5366.0),
    "40m": (7040.0, 7060.0),
    "30m": (10130.0, 10150.0),        # pas de phonie sur 30 m
    "20m": (14070.0, 14101.0),
    "17m": (18095.0, 18111.0),
    "15m": (21070.0, 21151.0),
    "12m": (24915.0, 24931.0),
    "10m": (28070.0, 28225.0),
    "6m": (50100.0, 50100.0),
    "4m": (70100.0, 70100.0),
    "2m": (144150.0, 144150.0),
    "70cm": (432150.0, 432150.0),
    "23cm": (1296150.0, 1296150.0),
}

# Modes suivis (décision de l'utilisateur, 2026-10-27 : phonie, FreeDV et CW ; pas de numérique)
MODES = ("CW", "SSB", "AM", "FM", "FREEDV")
# Modes numériques reconnus pour être ÉCARTÉS (jamais affichés)
DIGITAL = ("FT8", "FT4", "RTTY", "DIGI")


def band_of(freq_khz: float) -> str | None:
    for name, lo, hi in BANDS:
        if lo <= freq_khz <= hi:
            return name
    return None


def _near_dial(freq_khz: float, dials: tuple[float, ...]) -> bool:
    return any(d <= freq_khz <= d + 3.0 for d in dials)


def guess_mode(freq_khz: float) -> str | None:
    """Mode probable d'après le plan de bande ; None hors bande."""
    band = band_of(freq_khz)
    if band is None:
        return None
    if _near_dial(freq_khz, FT8_DIALS):
        return "FT8"
    if _near_dial(freq_khz, FT4_DIALS):
        return "FT4"
    if band == "11m":
        return "SSB"                  # l'essentiel du DX 11 m est en BLU
    seg = _SEGMENTS.get(band)
    if seg is None:
        return "CW" if band in ("2200m", "630m") else None
    cw_end, digi_end = seg
    if freq_khz < cw_end:
        return "CW"
    if freq_khz < digi_end:
        return "DIGI"
    if band == "10m" and freq_khz >= 29510.0:
        return "FM"
    return "SSB"


def hamlib_mode(mode: str, freq_khz: float) -> str | None:
    """Mode Hamlib proposé pour un QSY (lot 3) ; None si on ne sait pas (le poste garde son mode)."""
    if mode == "SSB":
        return "LSB" if freq_khz < 10000.0 else "USB"
    return {"CW": "CW", "FM": "FM", "AM": "AM", "FREEDV": "USB"}.get(mode)   # FreeDV : écoute en BLU
