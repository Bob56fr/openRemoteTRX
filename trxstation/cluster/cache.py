"""Cache des spots : normalisation, filtres, dédoublonnage, expiration, taille bornée.

- Même indicatif à ±1 kHz = même spot : heure mise à jour, spotteurs comptés.
- Durée de vie selon la source (15 min cluster et cibistes, 10 min RBN par
  défaut) ; un spot vu par un humain ET par le RBN garde la plus longue.
- Au plus `max_spots` (2 000) ; au-delà, les plus anciens partent.
- L'âge se mesure à la RÉCEPTION (horloge monotone), pas à l'heure « HHMMZ »
  du spot, à la minute près et parfois fausse ; seule exception : une source
  web donne l'âge exact de spots déjà anciens (`age_s`).
- Les modes numériques (FT8, FT4, RTTY, autres) sont TOUJOURS écartés.
- Spots des cibistes (« cb ») : indicatifs hors cty.dat, donc ni pays ni
  filtre de continent.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field

from .bandplan import BAND_NAMES, DIGITAL, MODES, band_of, guess_mode
from .cty import CONTINENTS, Cty
from .parse import RawSpot

DEDUP_KHZ = 1.0
MAX_SPOTTERS = 50
KINDS = ("cluster", "cb", "rbn")      # ordre de préférence de la couleur du marqueur


@dataclass
class SpotFilter:
    bands: frozenset[str] = frozenset()            # vide = toutes
    modes: frozenset[str] = frozenset()            # bandplan.MODES ; vide = tous (jamais le numérique)
    continents: frozenset[str] = frozenset()       # continent du SPOTTEUR ; vide = tous
    blacklist: frozenset[str] = frozenset()        # indicatifs (spotté ou spotteur) ; « XX* » = préfixe

    def __post_init__(self) -> None:
        for name, values, allowed in (("bande", self.bands, BAND_NAMES), ("mode", self.modes, MODES),
                                      ("continent", self.continents, CONTINENTS)):
            bad = sorted(set(values) - set(allowed))
            if bad:
                raise ValueError(f"{name} inconnu : {', '.join(bad)} (possibles : {' '.join(allowed)})")

    def blacklisted(self, call: str) -> bool:
        for item in self.blacklist:
            if item.endswith("*") and call.startswith(item[:-1]) or call == item:
                return True
        return False


@dataclass
class Spot:
    id: int
    freq_khz: float
    dx: str
    spotter: str
    mode: str | None
    mode_guessed: bool             # mode déduit du plan de bande, pas lu dans le spot
    band: str | None
    comment: str
    time_utc: str
    source: str                    # nom de la source
    kinds: set[str]                # sous-ensemble de KINDS
    country: str | None
    continent: str | None
    cq_zone: int | None
    spotter_continent: str | None
    first_seen: float
    last_seen: float
    expires: float
    spotters: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        """Couleur du marqueur : un spot vu par un humain reste humain."""
        return next(k for k in KINDS if k in self.kinds)

    @property
    def count(self) -> int:
        return len(self.spotters)

    def to_dict(self, now: float) -> dict:
        return {"id": self.id, "freq_khz": self.freq_khz, "dx": self.dx, "spotter": self.spotter,
                "mode": self.mode, "mode_guessed": self.mode_guessed, "band": self.band,
                "comment": self.comment, "time_utc": self.time_utc, "source": self.source,
                "kind": self.kind, "country": self.country, "continent": self.continent,
                "cq_zone": self.cq_zone, "spotters": self.count,
                "age_s": max(0, int(now - self.last_seen))}


class SpotCache:
    def __init__(self, cty: Cty | None = None, flt: SpotFilter | None = None, *,
                 ttl_s: dict[str, float] | None = None, max_spots: int = 2000) -> None:
        self.cty = cty or Cty()
        self.filter = flt or SpotFilter()
        self.ttl_s = {"cluster": 15 * 60.0, "cb": 15 * 60.0, "rbn": 10 * 60.0, **(ttl_s or {})}
        self.max_spots = max_spots
        self._spots: OrderedDict[int, Spot] = OrderedDict()     # du plus ancien au plus récent (last_seen)
        self._by_call: dict[str, list[int]] = {}
        self._next_id = 1
        self.counters: Counter[str] = Counter()

    def __len__(self) -> int:
        return len(self._spots)

    # ------------------------------------------------------------------ entrée

    def _reject(self, reason: str) -> None:
        self.counters["filtered"] += 1
        self.counters[f"filtered_{reason}"] += 1

    def add(self, raw: RawSpot, *, source: str, kind: str, now: float,
            age_s: float = 0.0) -> tuple[Spot, bool] | None:
        """(spot, nouveau) ou None si filtré ou déjà expiré."""
        if kind not in KINDS:
            raise ValueError(f"type de source inconnu : {kind}")
        self.counters["received"] += 1
        ttl = self.ttl_s[kind]
        if age_s >= ttl:
            self.counters["too_old"] += 1
            return None
        seen = now - max(0.0, age_s)
        f = self.filter
        if f.blacklisted(raw.dx) or f.blacklisted(raw.spotter):
            self._reject("blacklist")
            return None
        band = band_of(raw.freq_khz)
        if f.bands and band not in f.bands:
            self._reject("band")
            return None
        mode, guessed = raw.mode, False
        if mode is None:
            mode, guessed = guess_mode(raw.freq_khz), True
        if mode in DIGITAL:
            self._reject("digital")
            return None
        if f.modes and mode not in f.modes:
            self._reject("mode")
            return None
        sp_match = None if kind == "cb" else self.cty.lookup(raw.spotter)
        sp_cont = sp_match.continent if sp_match else None
        if f.continents and len(self.cty) and kind != "cb" and sp_cont not in f.continents:
            self._reject("continent")       # sans cty.dat, le filtre de continent est inopérant (diagnostic)
            return None

        existing = self._find(raw.dx, raw.freq_khz)
        if existing is not None:
            s = existing
            self.counters["duplicates"] += 1
            if raw.spotter not in s.spotters and len(s.spotters) < MAX_SPOTTERS:
                s.spotters.append(raw.spotter)
            s.kinds.add(kind)
            if seen < s.last_seen:
                return s, False             # plus ancien que celui connu : spotteur compté seulement
            s.freq_khz, s.last_seen, s.time_utc = raw.freq_khz, seen, raw.time_utc
            s.expires = max(s.expires, seen + ttl)
            s.band = band
            if raw.mode is not None or s.mode_guessed:
                s.mode, s.mode_guessed = mode, guessed
            if kind != "rbn" or not s.comment:
                s.comment, s.source = raw.comment, source
            self._spots.move_to_end(s.id)
            return s, False

        match = None if kind == "cb" else self.cty.lookup(raw.dx)
        s = Spot(id=self._next_id, freq_khz=raw.freq_khz, dx=raw.dx, spotter=raw.spotter, mode=mode,
                 mode_guessed=guessed, band=band, comment=raw.comment, time_utc=raw.time_utc,
                 source=source, kinds={kind}, country=match.entity.name if match else None,
                 continent=match.continent if match else None, cq_zone=match.cq_zone if match else None,
                 spotter_continent=sp_cont, first_seen=seen, last_seen=seen, expires=seen + ttl,
                 spotters=[raw.spotter])
        self._next_id += 1
        self._spots[s.id] = s
        self._by_call.setdefault(s.dx, []).append(s.id)
        self.counters["new"] += 1
        while len(self._spots) > self.max_spots:
            self._remove(next(iter(self._spots)))
            self.counters["evicted"] += 1
        return s, True

    def _find(self, dx: str, freq: float) -> Spot | None:
        for sid in self._by_call.get(dx, ()):
            s = self._spots[sid]
            if abs(s.freq_khz - freq) <= DEDUP_KHZ:
                return s
        return None

    def _remove(self, sid: int) -> Spot:
        s = self._spots.pop(sid)
        ids = self._by_call[s.dx]
        ids.remove(sid)
        if not ids:
            del self._by_call[s.dx]
        return s

    # ------------------------------------------------------------------ sortie

    def expire(self, now: float) -> list[Spot]:
        gone = [sid for sid, s in self._spots.items() if s.expires <= now]
        removed = [self._remove(sid) for sid in gone]
        self.counters["expired"] += len(removed)
        return removed

    def spots(self) -> list[Spot]:
        return list(self._spots.values())

    def in_range(self, lo_khz: float, hi_khz: float) -> list[Spot]:
        return sorted((s for s in self._spots.values() if lo_khz <= s.freq_khz <= hi_khz),
                      key=lambda s: s.freq_khz)
