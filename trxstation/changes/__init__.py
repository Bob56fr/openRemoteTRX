# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Changements d'openRemoteTRX poste par poste (étape 407, demande de l'utilisateur du 2026-11-28).

`changes.toml` (livré avec la station) dit, pour chaque changement visible, sa date, sa version, son type et les postes
concernés : "*" (tous), une marque ("icom", "yaesu", "kenwood" : famille Hamlib = numéro // 1000) ou un numéro de
modèle Hamlib. openRemoteTRX Console en montre au plus `LIMIT` pour le poste de la station (menu « Changements pour mon
poste »). Calculs purs, sans réseau.
"""
from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

LIMIT = 50
TYPES = ("correctif", "nouveaute", "securite")
BRANDS = {"yaesu": 1, "kenwood": 2, "icom": 3}       # familles Hamlib (RIG_BACKEND_*) : numéro du modèle // 1000
LANGS = ("fr", "en", "de", "es")
FILE = Path(__file__).with_name("changes.toml")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_VERSION = re.compile(r"\d+\.\d+\.\d+")


class ChangesError(ValueError):
    pass


@dataclass(frozen=True)
class Change:
    date: str
    version: str
    type: str
    postes: tuple[str, ...]
    texts: dict[str, str]

    def text(self, lang: str) -> str:
        return self.texts.get(lang) or self.texts["fr"]

    @property
    def common(self) -> bool:
        return "*" in self.postes

    def concerns(self, model: int) -> bool:
        """Ce changement vise-t-il CE modèle (par son numéro ou sa marque) ? Les changements communs : non."""
        brand = next((name for name, family in BRANDS.items() if model // 1000 == family), None)
        return str(model) in self.postes or (brand is not None and brand in self.postes)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def parse(data: dict) -> list[Change]:
    """Entrées validées (la plus récente d'abord). ChangesError au premier défaut : un fichier faux n'est jamais lu à moitié."""
    entries = data.get("change")
    if not isinstance(entries, list):
        raise ChangesError("aucune entrée [[change]]")
    out: list[Change] = []
    for n, e in enumerate(entries, 1):
        if not isinstance(e, dict):
            raise ChangesError(f"entrée {n} illisible")
        date, version, kind, postes = e.get("date"), e.get("version"), e.get("type"), e.get("postes")
        if not (isinstance(date, str) and _DATE.fullmatch(date)):
            raise ChangesError(f"entrée {n} : date invalide")
        if not (isinstance(version, str) and _VERSION.fullmatch(version)):
            raise ChangesError(f"entrée {n} : version invalide")
        if kind not in TYPES:
            raise ChangesError(f"entrée {n} : type invalide ({', '.join(TYPES)})")
        if not (isinstance(postes, list) and postes and all(isinstance(p, str) and (p == "*" or p in BRANDS or p.isdigit())
                                                              for p in postes)):
            raise ChangesError(f"entrée {n} : postes invalides (\"*\", marque ou numéro Hamlib)")
        texts = {lang: e.get(lang) for lang in LANGS}
        if not all(isinstance(t, str) and t.strip() and len(t) <= 300 for t in texts.values()):
            raise ChangesError(f"entrée {n} : texte manquant ou trop long dans une langue")
        out.append(Change(date, version, kind, tuple(postes), texts))
    out.sort(key=lambda c: (c.date, version_key(c.version)), reverse=True)
    return out


def load(path: Path | None = None) -> list[Change]:
    with open(path or FILE, "rb") as f:
        return parse(tomllib.load(f))


def for_model(changes: list[Change], model: int, common: bool = True, limit: int = LIMIT) -> list[Change]:
    """Changements du poste (et, si `common`, ceux de tous les postes), les plus récents d'abord, `limit` au plus."""
    return [c for c in changes if c.concerns(model) or (common and c.common)][:limit]


# ------------------------------------------------------------------ liste publiée (lot 2, étape 408)
# Copie JSON de changes.toml publiée sur GitHub Pages (scripts/build_changes_doc.py) ; trx-update-check la télécharge
# avec la recherche de mise à jour et la garde dans <state_dir>/update/changes.json : la station connaît ainsi les
# changements d'une version AVANT de l'installer (menus 7.1 et 7.4).
PUBLIC_URL = "https://bob56fr.github.io/openRemoteTRX/changements/changes.json"
MAX_BYTES = 512 * 1024
SCHEMA = 1


def to_public(changes: list[Change]) -> dict:
    return {"schema": SCHEMA, "change": [{"date": c.date, "version": c.version, "type": c.type, "postes": list(c.postes),
                                          **c.texts} for c in changes]}


def parse_public(raw: bytes) -> list[Change]:
    """Liste téléchargée : JSON du bon schéma, chaque entrée validée comme le fichier livré ; ChangesError sinon."""
    if len(raw) > MAX_BYTES:
        raise ChangesError("liste trop grande")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChangesError("liste illisible") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ChangesError("schéma inattendu")
    return parse(data)


def cache_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "update" / "changes.json"


def load_cached(state_dir: str | Path) -> list[Change]:
    """Dernière liste téléchargée ; [] si absente ou abîmée (jamais d'exception)."""
    try:
        return parse_public(cache_path(state_dir).read_bytes())
    except (OSError, ChangesError):
        return []


def merged(local: list[Change], cached: list[Change]) -> list[Change]:
    """Liste livrée + liste téléchargée (plus récente : changements des versions pas encore installées), sans doublon."""
    seen, out = set(), []
    for c in [*cached, *local]:
        key = (c.version, c.texts["fr"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    out.sort(key=lambda c: (c.date, version_key(c.version)), reverse=True)
    return out


def between(changes: list[Change], installed: str, offered: str) -> list[Change]:
    """Changements apportés par une mise à jour : version > installée et <= proposée."""
    low, high = version_key(installed), version_key(offered)
    return [c for c in changes if low < version_key(c.version) <= high]
