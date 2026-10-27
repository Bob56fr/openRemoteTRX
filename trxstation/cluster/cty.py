"""Pays, continent et zone CQ d'un indicatif, d'après cty.dat (AD1C, country-files.com).

Format d'une entité :

    France:                   14:  27:  EU:   46.00:    -2.00:    -1.0:  F:
        F,HW,HX,=F6DXB/YL,TM0(14)[27];

Préfixes séparés par des virgules, fin par « ; ». « =CALL » = indicatif exact ;
suffixes de correction : (zone CQ) [zone UIT] <lat/lon> {continent} ~fuseau~.

Mise à jour : `download()` (HTTPS vérifié, taille bornée, fichier analysé
AVANT de remplacer l'ancien, écriture atomique). Un fichier absent ou
illisible n'arrête rien : le pays est simplement inconnu.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CTY_URL = "https://www.country-files.com/bigcty/cty.dat"     # vérifié le 2026-10-27
MAX_BYTES = 2_000_000
MIN_ENTITIES = 300                                           # en dessous : fichier suspect
REFRESH_S = 7 * 24 * 3600
CONTINENTS = ("AF", "AN", "AS", "EU", "NA", "OC", "SA")

_OVERRIDE_RE = re.compile(r"\((\d+)\)|\[(\d+)\]|<[^>]*>|\{([A-Z]{2})\}|~[^~]*~")
_DROP_SUFFIXES = {"P", "M", "MM", "AM", "QRP", "A", "B", "LH", "LGT", "J", "R"}


class CtyError(ValueError):
    pass


@dataclass(frozen=True)
class Entity:
    name: str
    prefix: str
    continent: str
    cq_zone: int


@dataclass(frozen=True)
class Match:
    entity: Entity
    continent: str
    cq_zone: int


class Cty:
    def __init__(self) -> None:
        self.prefixes: dict[str, Match] = {}
        self.exact: dict[str, Match] = {}
        self.entities: list[Entity] = []
        self._max_len = 0

    def __len__(self) -> int:
        return len(self.entities)

    # ------------------------------------------------------------------ lecture

    @classmethod
    def parse(cls, text: str) -> "Cty":
        cty = cls()
        body: list[str] = []
        header: list[str] | None = None
        for line in text.splitlines():
            if not line.strip():
                continue
            if not line[0].isspace():
                if header is not None:
                    raise CtyError(f"entité sans « ; » final : {header[0]}")
                fields = [f.strip() for f in line.split(":")]
                if len(fields) < 9 or fields[3] not in CONTINENTS:
                    raise CtyError(f"en-tête illisible : {line[:60]!r}")
                header, body = fields, []
                continue
            if header is None:
                raise CtyError("liste de préfixes sans en-tête")
            body.append(line.strip())
            if line.rstrip().endswith(";"):
                cty._add(header, "".join(body).rstrip(";"))
                header = None
        if header is not None:
            raise CtyError(f"entité sans « ; » final : {header[0]}")
        return cty

    def _add(self, header: list[str], prefixes: str) -> None:
        try:
            cq = int(header[1])
        except ValueError as exc:
            raise CtyError(f"zone CQ illisible : {header[0]}") from exc
        entity = Entity(name=header[0][:40], prefix=header[7].lstrip("*"), continent=header[3], cq_zone=cq)
        self.entities.append(entity)
        for item in prefixes.split(","):
            item = item.strip()
            if not item:
                continue
            zone, cont = cq, entity.continent
            for m in _OVERRIDE_RE.finditer(item):
                if m.group(1):
                    zone = int(m.group(1))
                elif m.group(3):
                    cont = m.group(3)
            key = _OVERRIDE_RE.sub("", item).upper()
            match = Match(entity, cont, zone)
            if key.startswith("="):
                self.exact[key[1:]] = match
            elif key:
                self.prefixes.setdefault(key, match)
                self._max_len = max(self._max_len, len(key))

    @classmethod
    def load(cls, path: Path) -> "Cty":
        data = Path(path).read_bytes()
        if len(data) > MAX_BYTES:
            raise CtyError("fichier cty.dat trop gros")
        cty = cls.parse(data.decode("latin-1"))
        if len(cty) < MIN_ENTITIES:
            raise CtyError(f"seulement {len(cty)} entités : fichier cty.dat incomplet")
        return cty

    # ------------------------------------------------------------------ recherche

    def _longest(self, text: str) -> Match | None:
        for n in range(min(len(text), self._max_len), 0, -1):
            if (m := self.prefixes.get(text[:n])) is not None:
                return m
        return None

    def lookup(self, call: str) -> Match | None:
        """Entité d'un indicatif ; None si inconnue (maritime mobile, préfixe inconnu, fichier vide)."""
        call = call.upper().strip()
        if not call:
            return None
        if (m := self.exact.get(call)) is not None:
            return m
        parts = [p for p in call.split("/") if p]
        if parts and parts[-1] == "MM":
            return None                                       # maritime mobile : aucun pays
        parts = [p for p in parts if p not in _DROP_SUFFIXES and not p.isdigit()]
        if not parts:
            return None
        if len(parts) == 1:
            return self.exact.get(parts[0]) or self._longest(parts[0])
        # « EA8/F4ABC » ou « F4ABC/EA8 » : la partie la plus courte est le préfixe d'emprunt
        prefix = min(parts, key=len)
        return self._longest(prefix)


def load_or_empty(path: Path) -> tuple[Cty, str | None]:
    """(Cty, problème) : un fichier absent ou illisible donne une table vide, jamais une exception."""
    try:
        return Cty.load(path), None
    except FileNotFoundError:
        return Cty(), f"{path} absent : pays et continents inconnus"
    except (OSError, CtyError, UnicodeDecodeError) as exc:
        return Cty(), f"{path} illisible : {exc}"


def is_stale(path: Path, now: float | None = None) -> bool:
    try:
        age = (time.time() if now is None else now) - Path(path).stat().st_mtime
    except OSError:
        return True
    return age >= REFRESH_S


def download(path: Path, url: str = CTY_URL, *, timeout: float = 30.0, opener=urllib.request.urlopen) -> Cty:
    """Télécharge cty.dat, le vérifie, puis remplace l'ancien. Exception = ancien fichier intact."""
    if not url.startswith("https://"):
        raise CtyError("adresse de cty.dat non HTTPS")
    with opener(url, timeout=timeout) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise CtyError("fichier cty.dat trop gros")
    cty = Cty.parse(data.decode("latin-1"))
    if len(cty) < MIN_ENTITIES:
        raise CtyError(f"seulement {len(cty)} entités : téléchargement incomplet")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cty-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return cty
