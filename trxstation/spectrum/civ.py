# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Trames CI-V Icom et données du spectre (commande 27 00) : code commun à la station et aux outils d'essai.

Stdlib seule. Sécurité : seules les commandes de la liste FERMÉE `ALLOWED` peuvent être encodées (identification,
lecture de la fréquence, marche/arrêt de l'affichage du spectre et de sa sortie CI-V, préréglage de filtre
FIL1/2/3 du mode en cours) ; la commande d'émission 1C
n'y est pas et `encode_request` refuse tout le reste.
Format vérifié sur un IC-7300MK2 : trames 27 00 AVEC octet de choix du spectre, 11 divisions en BCD, division 1 =
en-tête de 12 octets (mode, deux fréquences BCD de 5 octets, hors plage), 475 points de 0 à 160.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

PREAMBLE, END, OK, NG, COLLISION = 0xFE, 0xFD, 0xFB, 0xFA, 0xFC
CONTROLLER = 0xE0                     # adresse CI-V habituelle d'un ordinateur
CONTROLLERS = (0xE0, 0xE1)            # E1 : second contrôleur (essai à deux ports, pour distinguer ses réponses)
BROADCAST = 0x00
MAX_FRAME = 256
LEVEL_MAX = 160                       # niveau maximal d'un point du spectre (0xA0)

# Liste FERMÉE : (commande, sous-commande) -> valeurs de données permises (None = lecture sans donnée).
ALLOWED: dict[tuple[int, int | None], set[bytes | None]] = {
    (0x19, 0x00): {None},             # identification du poste (renvoie son adresse)
    (0x03, None): {None},             # lecture de la fréquence affichée
    (0x27, 0x10): {None, b"\x00", b"\x01"},   # affichage du spectre : lecture, arrêt, marche
    (0x27, 0x11): {None, b"\x00", b"\x01"},   # sortie des données du spectre sur le CI-V : lecture, arrêt, marche
    # Réglages du spectre : LECTURE seulement (sans octet de choix, ou avec 00 = spectre principal). Formats relevés
    # sur le vrai poste avant toute écriture (civ_scope --reglages).
    (0x27, 0x14): {None, b"\x00"},   # mode centré / fixe
    (0x27, 0x15): {None, b"\x00"},   # largeur (SPAN) du mode centré
    (0x27, 0x19): {None, b"\x00"},   # niveau de référence
    (0x27, 0x1A): {None, b"\x00"},   # vitesse de balayage
}


class CivRefused(ValueError):
    """Commande hors de la liste fermée : jamais envoyée."""


# ------------------------------------------------------------------ trames

def encode_request(to: int, cmd: int, sub: int | None = None, data: bytes | None = None, *,
                   frm: int = CONTROLLER) -> bytes:
    if data is not None and len(data) == 0:
        data = None
    if (cmd, sub) not in ALLOWED or data not in ALLOWED[(cmd, sub)]:
        raise CivRefused(f"commande CI-V refusée : {cmd:02X}{'' if sub is None else f' {sub:02X}'}"
                         f"{'' if data is None else ' ' + data.hex(' ').upper()}")
    for value in (to, frm):
        if not 0 <= value <= 0xDF and value not in CONTROLLERS:
            raise CivRefused(f"adresse CI-V invalide : {value:02X}")
    body = bytes([to, frm, cmd]) + (bytes([sub]) if sub is not None else b"") + (data or b"")
    return bytes([PREAMBLE, PREAMBLE]) + body + bytes([END])


@dataclass(frozen=True)
class Frame:
    to: int
    frm: int
    payload: bytes                    # commande, sous-commande et données

    @property
    def cmd(self) -> int | None:
        return self.payload[0] if self.payload else None


class FrameReader:
    """Découpe le flux série en trames FE FE ... FD ; ignore le bruit, les collisions (FC) et les trames démesurées."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.dropped = 0

    def feed(self, chunk: bytes) -> Iterator[Frame]:
        self.buf += chunk
        while True:
            start = self.buf.find(bytes([PREAMBLE, PREAMBLE]))
            if start < 0:
                if self.buf[-1:] != bytes([PREAMBLE]):
                    self.dropped += len(self.buf)
                    self.buf.clear()
                else:
                    self.dropped += len(self.buf) - 1
                    del self.buf[:-1]
                return
            if start:
                self.dropped += start
                del self.buf[:start]
            while len(self.buf) > 2 and self.buf[2] == PREAMBLE:        # FE FE FE... : préambule plus long
                del self.buf[0]
            end = self.buf.find(bytes([END]), 2)
            restart = self.buf.find(bytes([PREAMBLE, PREAMBLE]), 2)
            if restart >= 0 and (end < 0 or restart < end):           # trame coupée : on se recale sur la suivante
                self.dropped += restart
                del self.buf[:restart]
                continue
            if end < 0:
                if len(self.buf) > MAX_FRAME:
                    self.dropped += len(self.buf)
                    self.buf.clear()
                return
            raw = bytes(self.buf[2:end])
            del self.buf[:end + 1]
            if len(raw) < 3 or COLLISION in raw or PREAMBLE in raw:
                self.dropped += len(raw) + 3
                continue
            yield Frame(raw[0], raw[1], raw[2:])


def is_bcd(byte: int) -> bool:
    return (byte >> 4) <= 9 and (byte & 0x0F) <= 9


def bcd_byte(byte: int) -> int:
    return (byte >> 4) * 10 + (byte & 0x0F)


def bcd_le(data: bytes) -> int | None:
    """Nombre BCD Icom, octet de poids faible en premier (fréquences) ; None si un chiffre est invalide."""
    if not all(is_bcd(b) for b in data):
        return None
    return sum(bcd_byte(b) * 100 ** i for i, b in enumerate(data))


# ------------------------------------------------------------------ assemblage des balayages (commande 27 00)

@dataclass
class Sweep:
    t: float                          # secondes depuis le début du relevé
    mode: int | None                  # 0 = centré, 1 = bornes fixes (selon le manuel CI-V)
    f1_hz: int | None                 # fréquence centrale (mode centré) ou borne basse
    f2_hz: int | None                 # largeur ou borne haute
    out_of_range: bool | None
    points: list[int] = field(default_factory=list)


class ScopeAssembler:
    """Recompose un balayage à partir de ses divisions (01..NN, numéros en BCD)."""

    def __init__(self) -> None:
        self.current: Sweep | None = None
        self.expected = 0
        self.complete = 0
        self.incomplete = 0
        self.unreadable = 0
        self.layouts: Counter[str] = Counter()     # « avec octet de choix » / « sans », nombre de divisions
        self.lengths: Counter[int] = Counter()

    def _split(self, data: bytes) -> tuple[int | None, int, int, bytes] | None:
        def valid(div: int, top: int) -> bool:
            return is_bcd(div) and is_bcd(top) and 1 <= bcd_byte(div) <= bcd_byte(top) <= 50
        if len(data) >= 3 and data[0] in (0, 1) and valid(data[1], data[2]):
            return data[0], bcd_byte(data[1]), bcd_byte(data[2]), data[3:]
        if len(data) >= 2 and valid(data[0], data[1]):
            return None, bcd_byte(data[0]), bcd_byte(data[1]), data[2:]
        return None

    def feed(self, data: bytes, t: float) -> Sweep | None:
        """`data` : octets qui suivent 27 00. Renvoie le balayage quand sa dernière division arrive."""
        parts = self._split(data)
        if parts is None:
            self.unreadable += 1
            return None
        selector, div, top, body = parts
        self.layouts[f"{'avec' if selector is not None else 'sans'} octet de choix, {top} division(s)"] += 1
        if div == 1:
            if self.current is not None:
                self.incomplete += 1
            header_ok = len(body) >= 12
            self.current = Sweep(t=t, mode=body[0] if header_ok else None,
                                 f1_hz=bcd_le(body[1:6]) if header_ok else None,
                                 f2_hz=bcd_le(body[6:11]) if header_ok else None,
                                 out_of_range=bool(body[11]) if header_ok else None,
                                 points=list(body[12:]) if header_ok else [])
            self.expected = 2
        elif self.current is None or div != self.expected:
            if self.current is not None:
                self.incomplete += 1
            self.current = None
            return None
        else:
            self.current.points.extend(body)
            self.expected += 1
        if div == top:
            sweep, self.current = self.current, None
            self.complete += 1
            self.lengths[len(sweep.points)] += 1
            return sweep
        return None


def ascii_line(points: list[int], width: int = 72) -> str:
    """Spectre en une ligne de terminal (maximum de chaque tranche)."""
    if not points:
        return ""
    marks = " ▁▂▃▄▅▆▇█"
    out = []
    n = len(points)
    for i in range(width):
        first = i * n // width
        chunk = points[first:max(first + 1, (i + 1) * n // width)]
        level = min(max(chunk), LEVEL_MAX) if chunk else 0
        out.append(marks[round(level / LEVEL_MAX * (len(marks) - 1))])
    return "".join(out)


# ------------------------------------------------------------------ réglages du spectre (relevés sur un IC-7300MK2)
# Toujours avec l'octet de choix 00 (spectre principal) : sans lui, le poste répond FA.
#   27 14 00 m        mode : 00 centré, 01 fixe, 02 défilement centré, 03 défilement fixe
#   27 15 00 + 5 o.   demi-largeur du mode centré, Hz, BCD octet faible d'abord (00 00 50 00 00 = ±500 kHz)
#   27 19 00 a b s    niveau de référence : « ab » = centièmes de dB en BCD (14 50 = 14,50), s = 01 négatif
#   27 1A 00 v        vitesse : 00 rapide, 01 moyenne, 02 lente
SCOPE_MODE, SCOPE_SPAN, SCOPE_REF, SCOPE_SPEED = 0x14, 0x15, 0x19, 0x1A
MODES = {"center": 0, "fixed": 1}                         # écrits ; 2 et 3 (défilement) seulement lus
MODE_NAMES = {0: "center", 1: "fixed", 2: "scroll_center", 3: "scroll_fixed"}
SPANS_HZ = (2_500, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000)
SPEEDS = {"fast": 0, "mid": 1, "slow": 2}
SPEED_NAMES = {v: k for k, v in SPEEDS.items()}
REF_MIN_DB, REF_MAX_DB, REF_STEP_DB = -20.0, 20.0, 0.5


def _to_bcd_le(value: int, size: int) -> bytes:
    out = []
    for _ in range(size):
        value, low = divmod(value, 10)
        value, high = divmod(value, 10)
        out.append(high << 4 | low)
    return bytes(out)


def _bcd(n: int) -> int:
    return (n // 10) << 4 | n % 10


def valid_ref(db) -> bool:
    return (isinstance(db, (int, float)) and not isinstance(db, bool) and REF_MIN_DB <= db <= REF_MAX_DB
            and abs(db / REF_STEP_DB - round(db / REF_STEP_DB)) < 1e-9)


def encode_setting(sub: int, value) -> bytes:
    """Données d'écriture (après 27 sub), octet de choix compris ; ValueError hors des valeurs permises."""
    if sub == SCOPE_MODE and value in MODES:
        return bytes([0, MODES[value]])
    if sub == SCOPE_SPAN and value in SPANS_HZ:
        return b"\x00" + _to_bcd_le(value, 5)
    if sub == SCOPE_REF and valid_ref(value):
        hundredths = round(abs(value) * 100)
        return bytes([0, _bcd(hundredths // 100), _bcd(hundredths % 100), 1 if value < 0 else 0])
    if sub == SCOPE_SPEED and value in SPEEDS:
        return bytes([0, SPEEDS[value]])
    raise ValueError(f"réglage du spectre refusé : 27 {sub:02X} = {value!r}")


def decode_setting(sub: int, payload: bytes):
    """Valeur lue dans une réponse « 27 sub 00 ... » ; None si illisible."""
    if len(payload) < 4 or payload[:3] != bytes([0x27, sub, 0x00]):
        return None
    data = payload[3:]
    if sub == SCOPE_MODE and len(data) == 1:
        return MODE_NAMES.get(data[0])
    if sub == SCOPE_SPAN and len(data) == 5:
        return bcd_le(data)
    if sub == SCOPE_REF and len(data) == 3 and is_bcd(data[0]) and is_bcd(data[1]) and data[2] in (0, 1):
        db = (bcd_byte(data[0]) * 100 + bcd_byte(data[1])) / 100
        return -db if data[2] == 1 else db
    if sub == SCOPE_SPEED and len(data) == 1:
        return SPEED_NAMES.get(data[0])
    return None


# Préréglages de filtre FIL1 / FIL2 / FIL3 : « 26 00 » = mode du VFO sélectionné (mode, mode données, filtre).
# Lecture, puis réécriture du MÊME mode et du MÊME mode données avec un autre filtre : le poste change de préréglage
# sans toucher à leurs largeurs (Hamlib, lui, réécrit la largeur du préréglage choisi).
FILTERS = (1, 2, 3)
CIV_MODES = (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x07, 0x08)    # LSB USB AM CW RTTY FM CW-R RTTY-R
DATA_MODES = (0, 1, 2, 3)                                       # 0 = arrêt, 1 à 3 = D1 à D3 (l'IC-7300 n'a que D1)


def decode_mode_filter(payload: bytes) -> tuple[int, int, int] | None:
    """(mode, données, filtre) lu dans une réponse « 26 00 mm dd ff » ; None si illisible ou hors des valeurs connues."""
    if len(payload) != 5 or payload[:2] != b"\x26\x00":
        return None
    mode, data, filt = payload[2], payload[3], payload[4]
    if mode not in CIV_MODES or data not in DATA_MODES or filt not in FILTERS:
        return None
    return mode, data, filt


def encode_mode_filter(mode: int, data: int, filt: int) -> bytes:
    """Données d'écriture après « 26 00 » ; ValueError hors des valeurs permises."""
    if mode not in CIV_MODES or data not in DATA_MODES or filt not in FILTERS or isinstance(filt, bool):
        raise ValueError(f"préréglage de filtre refusé : {mode!r} {data!r} {filt!r}")
    return bytes([mode, data, filt])


# Écritures permises : générées à partir des seules valeurs ci-dessus (liste fermée, jamais de valeur calculée ailleurs).
ALLOWED[(0x27, SCOPE_MODE)] |= {encode_setting(SCOPE_MODE, m) for m in MODES}
ALLOWED[(0x27, SCOPE_SPAN)] |= {encode_setting(SCOPE_SPAN, s) for s in SPANS_HZ}
ALLOWED[(0x27, SCOPE_REF)] |= {encode_setting(SCOPE_REF, i * REF_STEP_DB) for i in range(-40, 41)}
ALLOWED[(0x27, SCOPE_SPEED)] |= {encode_setting(SCOPE_SPEED, v) for v in SPEEDS}
ALLOWED[(0x26, 0x00)] = {None} | {encode_mode_filter(m, d, f) for m in CIV_MODES for d in DATA_MODES for f in FILTERS}
