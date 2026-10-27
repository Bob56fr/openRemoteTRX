# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Profil Hamlib d'un modèle, plus complet que le descripteur de la passerelle, pour la qualification.

On lit la sortie de `rigctl -m <modèle> -u` (dump_caps) : fonctions et niveaux en LECTURE et en
ÉCRITURE (avec leurs plages), indicateurs « Can set/get … », statut du backend, préamplis,
atténuateurs, valeurs d'AGC. Le descripteur de la passerelle (`Capabilities`) n'est pas modifié :
il reste la seule source pour l'application.

Hamlib DÉCLARE, il ne garantit pas : ce profil sert à générer le cahier de test, jamais à décider
qu'une fonction marche.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

from ..gateway.cat import Capabilities, parse_dump_caps
from ..hamlib import find_tool

_RANGE_RE = re.compile(r"\b([A-Z][A-Z0-9_]+)\((-?[\d.eE+]+?)\.\.(-?[\d.eE+]+)/(-?[\d.eE+]+)\)")
_NAME_RE = re.compile(r"\b([A-Z][A-Z0-9_]+)(?=\(|\s|$)")
BACKEND_STATUSES = ("Stable", "Beta", "Alpha", "Untested", "New", "Buggy")


@dataclass
class LevelRange:
    low: float
    high: float
    step: float

    def to_dict(self) -> dict:
        return {"min": self.low, "max": self.high, "pas": self.step}


@dataclass
class HamlibProfile:
    caps: Capabilities
    model: int = 0
    backend_status: str = ""          # Stable, Beta, Alpha, Untested… ; vide = inconnu
    hamlib_version: str = ""          # « 4.6.2 » ; vide = inconnue
    get_functions: tuple[str, ...] = ()
    set_functions: tuple[str, ...] = ()
    get_levels: tuple[str, ...] = ()
    set_levels: tuple[str, ...] = ()
    level_ranges: dict[str, LevelRange] = field(default_factory=dict)   # plages des niveaux en écriture
    can: dict[str, bool] = field(default_factory=dict)                   # « set Frequency » -> True
    preamps: tuple[int, ...] = ()
    attenuators: tuple[int, ...] = ()
    agc_levels: tuple[int, ...] = ()  # valeurs Hamlib d'AGC proposées par le backend ; vide = inconnues

    @property
    def modes(self) -> tuple[str, ...]:
        return self.caps.modes if self.caps.complete else ()

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.caps.manufacturer, self.caps.model_name) if p) or f"modèle {self.model}"

    def declared(self) -> set[str]:
        """Tous les noms de fonctions et de niveaux déclarés, en lecture ou en écriture."""
        return set(self.get_functions) | set(self.set_functions) | set(self.get_levels) | set(self.set_levels)

    def to_dict(self) -> dict:
        return {
            "modele": self.model, "nom": self.name, "statut_backend": self.backend_status,
            "hamlib": self.hamlib_version, "modes": list(self.modes),
            "fonctions_lecture": list(self.get_functions), "fonctions_ecriture": list(self.set_functions),
            "niveaux_lecture": list(self.get_levels), "niveaux_ecriture": list(self.set_levels),
            "plages": {k: v.to_dict() for k, v in self.level_ranges.items()},
            "peut": dict(self.can), "preamplis_db": list(self.preamps), "attenuateurs_db": list(self.attenuators),
            "agc": list(self.agc_levels), "filtres": {k: list(v) for k, v in self.caps.filters.items()},
        }


def _line(text: str, label: str) -> str | None:
    match = re.search(rf"^{label}:[ \t]*(.*)$", text, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else None


def _names(text: str, label: str) -> tuple[str, ...]:
    value = _line(text, label)
    return tuple(dict.fromkeys(_NAME_RE.findall(value))) if value else ()


def _ranges(text: str, label: str) -> dict[str, LevelRange]:
    value = _line(text, label) or ""
    found: dict[str, LevelRange] = {}
    for name, low, high, step in _RANGE_RE.findall(value):
        try:
            found[name] = LevelRange(float(low), float(high), float(step))
        except ValueError:
            continue
    return found


def _decibels(text: str, label: str) -> tuple[int, ...]:
    value = _line(text, label)
    return tuple(int(v) for v in re.findall(r"\d+", value) if int(v) > 0) if value else ()


def _version(text: str) -> str:
    match = re.search(r"Hamlib\s+(\d+\.\d+(?:\.\d+)*)", text)
    return match.group(1) if match else ""


def parse_profile(text: str, model: int = 0) -> HamlibProfile:
    caps = parse_dump_caps(text, model)
    profile = HamlibProfile(caps=caps, model=model)
    status = _line(text, "Backend status") or ""
    profile.backend_status = next((s for s in BACKEND_STATUSES if status.lower().startswith(s.lower())), status[:20])
    profile.hamlib_version = _version(_line(text, "Hamlib version") or "")
    profile.get_functions = _names(text, "Get functions")
    profile.set_functions = _names(text, "Set functions")
    profile.get_levels = _names(text, "Get level")
    profile.set_levels = _names(text, "Set level")
    profile.level_ranges = _ranges(text, "Set level")
    for verb, what, flag in re.findall(r"^Can (set|get) ([A-Za-z ]+?):[ \t]*(\S+)", text, re.MULTILINE):
        profile.can[f"{verb} {what.strip()}"] = flag.upper()[:1] in ("Y", "E")     # E = émulé par Hamlib
    profile.preamps = _decibels(text, "Preamp")
    profile.attenuators = _decibels(text, "Attenuator")
    agc = _line(text, "AGC levels")
    if agc:
        profile.agc_levels = tuple(dict.fromkeys(int(v) for v in re.findall(r"(\d+)=", agc)))
    return profile


def hamlib_version(hamlib_dir: str = "") -> str:
    """Version de Hamlib installée (« 4.6.2 »), ou chaîne vide si `rigctl -V` est introuvable ou muet."""
    rigctl = find_tool("rigctl", hamlib_dir)
    if not rigctl:
        return ""
    try:
        done = subprocess.run([rigctl, "-V"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return _version(done.stdout + done.stderr)


def version_tuple(text: str) -> tuple[int, ...]:
    """« 4.6.2 » -> (4, 6, 2) ; texte illisible -> ()."""
    parts = re.findall(r"\d+", text or "")
    return tuple(int(p) for p in parts[:4])
