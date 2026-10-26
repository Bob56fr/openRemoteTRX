"""Trames CI-V Icom et données du spectre (commande 27 00) : code commun à la station et aux outils d'essai.

Stdlib seule. Sécurité : seules les commandes de la liste FERMÉE `ALLOWED` peuvent être encodées (identification,
lecture de la fréquence, marche/arrêt de l'affichage du spectre et de sa sortie CI-V) ; la commande d'émission 1C
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
