# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fiche technique du poste (étape 393, décision de l'utilisateur du 2026-11-25) : ce que Hamlib ne dit pas d'un modèle
et que la station, la page et l'application doivent savoir (délais de relecture, mémoire par bande, filtres, source du
squelch, récepteurs). DONNÉES seulement, jamais de code par modèle : un fichier `models/<numéro Hamlib>.toml` par poste
connu, `generic.toml` pour tous les autres ; validées strictement (fichiers livrés avec le code, `tests/test_rigspec.py`).

À ne pas confondre avec les « profils de poste » de profiles.py (réglages de station.toml enregistrés par l'opérateur).
La fiche est envoyée aux clients dans `hello.rig_spec` (docs/protocole.md) ; elle ne permet RIEN de plus au poste :
toute écriture reste filtrée par la passerelle comme avant.
"""
from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

FORMAT = 1
FOLDER = Path(__file__).resolve().parent
FILTER_KINDS = ("unknown", "presets", "steps", "none")
SQUELCH_SOURCES = ("estimate", "busy", "dcd")
MAX_DELAY_S = 30.0


class RigSpecError(ValueError):
    """Fiche technique invalide (fichier livré avec le code : défaut à corriger, jamais une entrée de l'opérateur)."""


@dataclass(frozen=True)
class Timing:
    # Marge ajoutée à l'attente d'une relecture après une commande de la station (poste lent : lectures facultatives
    # longues, relecture tous les quelques secondes) ; 0 = l'attente de base suffit
    read_delay_s: float = 0.0
    # De plus quand le coupleur est en service (relais du coupleur qui retardent les réponses du poste)
    tuner_delay_s: float = 2.0
    # Une commande de fréquence peut changer le mode (mémoire par bande du poste) et une commande de mode la fréquence :
    # les deux sont alors attribuées à la station (jamais une « action sur le poste »)
    linked_changes: bool = True


@dataclass(frozen=True)
class Filters:
    # unknown = rien de connu (bouton FIL comme aujourd'hui) ; presets = préréglages FIL1/2/3 (Icom) ; steps = largeur
    # par paliers imposés (Yaesu `SH`) ; none = aucun réglage de largeur
    kind: str = "unknown"
    presets: int = 0


@dataclass(frozen=True)
class Squelch:
    # estimate = repère du squelch comparé au S-mètre (approximatif) ; busy = état « occupé » lu sur le poste
    # (Yaesu `BY`) ; dcd = détection de porteuse de Hamlib (`get_dcd`)
    source: str = "estimate"


@dataclass(frozen=True)
class RigSpec:
    model: int = 0                       # 0 = fiche générique
    name: str = ""
    receivers: int = 1                   # 2 = deux récepteurs indépendants (MAIN / SUB, Yaesu FTDX101)
    verified: bool = False               # valeurs relevées sur un vrai poste (qualification), sinon d'après le manuel
    timing: Timing = field(default_factory=Timing)
    filters: Filters = field(default_factory=Filters)
    squelch: Squelch = field(default_factory=Squelch)

    def to_dict(self) -> dict:
        return asdict(self)


def _section(cls, data: object, where: str):
    if not isinstance(data, dict):
        raise RigSpecError(f"{where} : table attendue")
    known = {f for f in cls.__dataclass_fields__}
    unknown = set(data) - known
    if unknown:
        raise RigSpecError(f"{where} : réglage inconnu {sorted(unknown)}")
    defaults = cls()
    for key, value in data.items():
        expected = type(getattr(defaults, key))
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
            data[key] = value
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise RigSpecError(f"{where}.{key} : {expected.__name__} attendu")
    return cls(**data)


def parse(text: str, where: str = "fiche") -> RigSpec:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RigSpecError(f"{where} : TOML illisible ({exc})") from exc
    if data.pop("format", None) != FORMAT:
        raise RigSpecError(f"{where} : « format = {FORMAT} » attendu")
    timing = _section(Timing, data.pop("timing", {}), f"{where} [timing]")
    filters = _section(Filters, data.pop("filters", {}), f"{where} [filters]")
    squelch = _section(Squelch, data.pop("squelch", {}), f"{where} [squelch]")
    spec = _section(RigSpec, data, where)
    spec = RigSpec(model=spec.model, name=spec.name, receivers=spec.receivers, verified=spec.verified,
                   timing=timing, filters=filters, squelch=squelch)
    problem = check(spec)
    if problem:
        raise RigSpecError(f"{where} : {problem}")
    return spec


def check(spec: RigSpec) -> str | None:
    t = spec.timing
    if not 0.0 <= t.read_delay_s <= MAX_DELAY_S or not 0.0 <= t.tuner_delay_s <= MAX_DELAY_S:
        return f"délais entre 0 et {MAX_DELAY_S:.0f} s"
    if spec.receivers not in (1, 2):
        return "receivers = 1 ou 2"
    if spec.filters.kind not in FILTER_KINDS:
        return f"filters.kind parmi {FILTER_KINDS}"
    if (spec.filters.kind == "presets") != (spec.filters.presets > 0) or not 0 <= spec.filters.presets <= 3:
        return "filters.presets de 1 à 3 pour kind = presets, 0 sinon"
    if spec.squelch.source not in SQUELCH_SOURCES:
        return f"squelch.source parmi {SQUELCH_SOURCES}"
    return None


@lru_cache(maxsize=None)
def load(model: int) -> RigSpec:
    """Fiche du modèle Hamlib `model`, sinon la fiche générique (jamais d'exception pour un poste inconnu)."""
    path = FOLDER / "models" / f"{int(model)}.toml"
    if not path.is_file():
        return parse((FOLDER / "generic.toml").read_text(encoding="utf-8"), "generic.toml")
    spec = parse(path.read_text(encoding="utf-8"), path.name)
    if spec.model != int(model):
        raise RigSpecError(f"{path.name} : model = {spec.model}, {model} attendu")
    return spec
