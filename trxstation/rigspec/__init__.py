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

import re
import tomllib
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

FORMAT = 1
FOLDER = Path(__file__).resolve().parent
FILTER_KINDS = ("unknown", "presets", "steps", "none")
SQUELCH_SOURCES = ("estimate", "busy", "dcd")
MAX_DELAY_S = 30.0
READ_QUERY_RE = re.compile(r"[A-Z]{2};")           # lecture CAT ASCII sans paramètre (jamais une écriture)
MODE_RE = re.compile(r"[A-Z][A-Z0-9-]{0,15}")      # nom de mode Hamlib (USB, PKTUSB, CWR...)


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
    # steps : paliers permis par mode Hamlib (Hz, croissants), d'après le manuel CAT ; un mode absent = paliers inconnus
    steps: dict = field(default_factory=dict)
    # Appui BREF sur FIL (steps) : liste courte parcourue en boucle (décision de l'utilisateur du 2026-11-25 : 1.8 à
    # 4.0 k, du DX à la HIFI), seulement dans les modes dont les paliers la contiennent toute
    quick: tuple = ()
    # Largeur envoyée avec un mode quand la station n'en choisit pas (étape 402) : 0 = largeur « normale » de Hamlib
    # (Icom : préréglage FIL, comportement validé sur l'IC-7300MK2) ; -1 = largeur INCHANGÉE (Hamlib
    # RIG_PASSBAND_NOCHANGE : chez Yaesu newcat, 0 deviendrait 2400 Hz et réécrirait le filtre de toit, lu dans le code)
    mode_width: int = 0


@dataclass(frozen=True)
class Squelch:
    # estimate = repère du squelch comparé au S-mètre (approximatif) ; busy = état « occupé » lu sur le poste
    # (Yaesu `BY`) ; dcd = détection de porteuse de Hamlib (`get_dcd`)
    source: str = "estimate"
    # Source « busy » : LECTURE brute de la fiche (étape 402 ; Hamlib n'a pas get_dcd pour les Yaesu newcat, lu dans
    # son code) : `query` (deux lettres et « ; », ex. « BY; »), `reply` (expression, UN groupe), `open_value` (valeur
    # du groupe quand le squelch est ouvert). Vides pour les autres sources.
    query: str = ""
    reply: str = ""
    open_value: str = ""
    # Étalonnage du squelch du MODÈLE (étape 411) : 10 valeurs SQL de Hamlib (0 à 1) quand le poste affiche 1 à 9 puis
    # 9+10, d'après les exports du menu 2.10 envoyés par les opérateurs ; vide = aucune table (trxstation/squelchcal.py)
    calibration: tuple = ()


@dataclass(frozen=True)
class Transmit:
    """Côté d'émission d'un poste à deux récepteurs (étape 397, Yaesu FTDX101 : touches TX du MAIN et du SUB, commande
    FT, que Hamlib ne lit pas : il lit le split par ST). La station envoie ces LECTURES brutes (deux lettres et « ; »,
    jamais un paramètre : aucune écriture possible) avant chaque prise d'émission et pendant l'émission."""
    side_query: str = ""         # ex. « FT; » : côté qui émet ; vide = poste sans côté d'émission à lire
    side_reply: str = ""         # expression de la réponse, UN groupe = valeur (ex. « FT([01]); »)
    sub_value: str = ""          # valeur du groupe quand le SUB émet (ex. « 1 ») ; toute autre valeur connue = MAIN
    main_value: str = ""         # valeur du groupe quand le MAIN émet (ex. « 0 ») ; autre chose = illisible (refus)
    main_freq_query: str = ""    # ex. « FA; » : fréquence du MAIN
    sub_freq_query: str = ""     # ex. « FB; » : fréquence du SUB
    freq_reply: str = ""         # ex. « F[AB](\d{9}); » : UN groupe = fréquence en Hz


@dataclass(frozen=True)
class RigSpec:
    model: int = 0                       # 0 = fiche générique
    name: str = ""
    receivers: int = 1                   # 2 = deux récepteurs indépendants (MAIN / SUB, Yaesu FTDX101)
    verified: bool = False               # valeurs relevées sur un vrai poste (qualification), sinon d'après le manuel
    timing: Timing = field(default_factory=Timing)
    filters: Filters = field(default_factory=Filters)
    squelch: Squelch = field(default_factory=Squelch)
    transmit: Transmit = field(default_factory=Transmit)

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
    raw_filters = data.pop("filters", {})
    if isinstance(raw_filters, dict):
        raw_filters = dict(raw_filters)
        if isinstance(raw_filters.get("quick"), list):
            raw_filters["quick"] = tuple(raw_filters["quick"])
    filters = _section(Filters, raw_filters, f"{where} [filters]")
    raw_squelch = data.pop("squelch", {})
    if isinstance(raw_squelch, dict) and isinstance(raw_squelch.get("calibration"), list):
        raw_squelch = {**raw_squelch, "calibration": tuple(raw_squelch["calibration"])}
    squelch = _section(Squelch, raw_squelch, f"{where} [squelch]")
    transmit = _section(Transmit, data.pop("transmit", {}), f"{where} [transmit]")
    spec = _section(RigSpec, data, where)
    spec = RigSpec(model=spec.model, name=spec.name, receivers=spec.receivers, verified=spec.verified,
                   timing=timing, filters=filters, squelch=squelch, transmit=transmit)
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
    for mode, values in spec.filters.steps.items():
        if not isinstance(mode, str) or not MODE_RE.fullmatch(mode) or not _widths(values):
            return f"filters.steps.{mode} : largeurs entières croissantes de 10 à 20 000 Hz"
    if spec.filters.steps and spec.filters.kind != "steps":
        return "filters.steps seulement pour kind = steps"
    if spec.filters.quick and (spec.filters.kind != "steps" or not _widths(list(spec.filters.quick))):
        return "filters.quick : largeurs croissantes, seulement pour kind = steps"
    t = spec.transmit
    values = (t.side_query, t.side_reply, t.sub_value, t.main_value, t.main_freq_query, t.sub_freq_query, t.freq_reply)
    if any(values) and not all(values):
        return "[transmit] : tous les champs, ou aucun"
    if any(values):
        for query in (t.side_query, t.main_freq_query, t.sub_freq_query):
            if not READ_QUERY_RE.fullmatch(query):
                return f"[transmit] : « {query} » n'est pas une lecture (deux lettres et « ; »)"
        for pattern in (t.side_reply, t.freq_reply):
            try:
                if re.compile(pattern).groups != 1:
                    return f"[transmit] : « {pattern} » doit avoir un seul groupe"
            except re.error:
                return f"[transmit] : expression illisible « {pattern} »"
        if t.sub_value == t.main_value or spec.receivers != 2:
            return "[transmit] : valeurs MAIN et SUB distinctes, seulement pour receivers = 2"
    if spec.filters.mode_width not in (0, -1):
        return "filters.mode_width : 0 (largeur normale) ou -1 (inchangée)"
    if spec.squelch.source not in SQUELCH_SOURCES:
        return f"squelch.source parmi {SQUELCH_SOURCES}"
    s = spec.squelch
    raw_read = (s.query, s.reply, s.open_value)
    if s.source == "busy":
        if not all(raw_read):
            return "[squelch] source = busy : query, reply et open_value exigés"
        if not READ_QUERY_RE.fullmatch(s.query):
            return f"[squelch] : « {s.query} » n'est pas une lecture (deux lettres et « ; »)"
        try:
            if re.compile(s.reply).groups != 1:
                return f"[squelch] : « {s.reply} » doit avoir un seul groupe"
        except re.error:
            return f"[squelch] : expression illisible « {s.reply} »"
    elif any(raw_read):
        return "[squelch] : query, reply et open_value seulement pour source = busy"
    if s.calibration:
        from ..squelchcal import problem as cal_problem
        if (bad := cal_problem(list(s.calibration))) is not None:
            return f"[squelch] calibration : {bad}"
    return None


def _widths(values: object) -> bool:
    return (isinstance(values, list) and len(values) >= 2
            and all(isinstance(v, int) and not isinstance(v, bool) and 10 <= v <= 20_000 for v in values)
            and all(a < b for a, b in zip(values, values[1:])))


def quick_widths(spec: RigSpec, mode: str | None) -> tuple[int, ...]:
    """Liste courte de l'appui bref sur FIL dans ce mode ; () si le mode n'a pas tous ces paliers."""
    steps = spec.filters.steps.get(mode or "", [])
    return spec.filters.quick if spec.filters.quick and set(spec.filters.quick) <= set(steps) else ()


def read_queries() -> frozenset[str]:
    """Liste FERMÉE des lectures brutes que la station peut envoyer : celles des fiches livrées."""
    out: set[str] = set()
    for path in sorted((FOLDER / "models").glob("*.toml")):
        spec = parse(path.read_text(encoding="utf-8"), path.name)
        t = spec.transmit
        out.update(q for q in (t.side_query, t.main_freq_query, t.sub_freq_query, spec.squelch.query) if q)
    return frozenset(out)


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
