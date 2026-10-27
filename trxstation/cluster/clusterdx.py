"""Source « Cluster DX » des cibistes (https://clusterdx.org), bande des 11 m.

Pas de telnet ni d'API : la page publique `spots.php` est un tableau HTML des
100 derniers spots (n°, horodatage, spotteur, fréquence kHz, indicatif,
commentaire), sans mode ni pays. Relevé le 2026-10-27 : horodatage à l'heure
de PARIS (« 2026-10-27 15:47:58 » à 14:48 UTC), fréquences entières en kHz,
indicatifs cibistes (« 14LG56 », « 1AT/H688 », « 10/108AT150 »).

Bonne conduite : une requête par minute au plus (la page du site se
rafraîchit elle-même toutes les 60 s), réponse bornée, agent identifié,
aucune connexion au compte. Format NON documenté par le site : un changement
de page donne une erreur « format » (source en échec), jamais un faux spot.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from .parse import MAX_COMMENT, RawSpot, mode_in
from .text import base_call, clean_line, is_callsign

URL = "https://clusterdx.org/spots.php"          # vérifiée le 2026-10-27
POLL_S = 60.0                                    # jamais moins
MAX_BYTES = 1_000_000
USER_AGENT = "TRX-Remote (cluster DX, lecture seule, 1 requete/min)"
_COLUMNS = ("timestamp", "spotter", "freq", "dxcall", "comment")


class FormatError(ValueError):
    """La page ne ressemble plus au tableau attendu."""


@dataclass(frozen=True)
class WebSpot:
    id: int
    raw: RawSpot
    age_s: float


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self.has_header = False
        self._row: dict[str, str] | None = None
        self._cell: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and "spots" in (a.get("class") or "").split():
            self.has_header = True
        elif tag == "tr" and a.get("data-id") is not None:
            self._row = {"id": a.get("data-id") or ""}
        elif tag == "td" and self._row is not None:
            cls = (a.get("class") or "").strip()
            self._cell, self._text = (cls if cls in _COLUMNS else None), []

    def handle_data(self, data):
        if self._cell is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row[self._cell] = "".join(self._text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


# ------------------------------------------------------------------ heure de Paris -> UTC (règle européenne)

def _last_sunday(year: int, month: int) -> date:
    d = date(year, month, 31)                    # mars et octobre ont 31 jours
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _summer(utc: datetime) -> bool:
    start = datetime.combine(_last_sunday(utc.year, 3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(utc.year, 10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    return start <= utc < end


def paris_to_utc(local: datetime) -> datetime:
    """Heure de Paris (sans fuseau) -> UTC. Heure ambiguë d'octobre : l'heure d'été est retenue."""
    local = local.replace(tzinfo=timezone.utc)
    summer = local - timedelta(hours=2)
    return summer if _summer(summer) else local - timedelta(hours=1)


# ------------------------------------------------------------------ analyse

def parse_page(html: str, now_utc: datetime) -> tuple[list[WebSpot], int]:
    """(spots, mal formés). FormatError si la page n'a pas le tableau attendu."""
    table = _Table()
    table.feed(html)
    table.close()
    if not table.has_header or (not table.rows and "<tr data-id" in html):
        raise FormatError("tableau des spots introuvable : la page de clusterdx.org a changé")
    spots: list[WebSpot] = []
    bad = 0
    for row in table.rows:
        try:
            spots.append(_row_spot(row, now_utc))
        except (ValueError, KeyError):
            bad += 1
    if table.rows and not spots:
        raise FormatError("aucune ligne lisible : la page de clusterdx.org a changé")
    return spots, bad


def _clean(text: str) -> str:
    return " ".join(clean_line(text.encode("utf-8")).split())


def _row_spot(row: dict[str, str], now_utc: datetime) -> WebSpot:
    sid = int(row["id"])
    when = paris_to_utc(datetime.strptime(_clean(row["timestamp"]), "%Y-%m-%d %H:%M:%S"))
    age = (now_utc - when).total_seconds()
    if age < -300:
        raise ValueError("spot dans le futur")
    freq = float(_clean(row["freq"]))
    if not 100.0 <= freq <= 300_000_000.0:
        raise ValueError("fréquence")
    dx, spotter = _clean(row["dxcall"]).upper(), base_call(_clean(row["spotter"]))
    if not is_callsign(dx) or not is_callsign(spotter):
        raise ValueError("indicatif")
    comment = _clean(row.get("comment", ""))[:MAX_COMMENT]
    raw = RawSpot(freq_khz=freq, dx=dx, spotter=spotter, mode=mode_in(comment), comment=comment,
                  time_utc=when.strftime("%H%M"), skimmer=False)
    return WebSpot(id=sid, raw=raw, age_s=max(0.0, age))


def fetch(url: str = URL, *, timeout: float = 20.0, opener=urllib.request.urlopen) -> tuple[str, datetime]:
    """(page, heure du serveur) ; l'heure du serveur évite une horloge locale déréglée."""
    if not url.startswith("https://"):
        raise ValueError("adresse non HTTPS")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(req, timeout=timeout) as resp:
        data = resp.read(MAX_BYTES + 1)
        date_header = resp.headers.get("Date") if getattr(resp, "headers", None) is not None else None
    if len(data) > MAX_BYTES:
        raise FormatError("page trop grosse")
    now = datetime.now(timezone.utc)
    if date_header:
        try:
            now = parsedate_to_datetime(date_header).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    return data.decode("utf-8", "replace"), now
