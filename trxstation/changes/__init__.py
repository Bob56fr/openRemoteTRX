# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Changements d'openRemoteTRX poste par poste (étape 407, demande de l'utilisateur du 2026-11-28).

`changes.toml` (livré avec la station) dit, pour chaque changement visible, sa date, sa version, son type et les postes
concernés : "*" (tous), une marque ("icom", "yaesu", "kenwood" : famille Hamlib = numéro // 1000) ou un numéro de
modèle Hamlib. openRemoteTRX Console en montre au plus `LIMIT` pour le poste de la station (menu « Changements pour mon
poste »). Calculs purs, sans réseau.
"""
from __future__ import annotations

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
