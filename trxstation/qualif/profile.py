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


@dataclass(frozen=True)
class FreqRange:
    """Plage de fréquences déclarée (« RX ranges » / « TX ranges ») avec ses modes et, en émission, ses puissances."""
    low_hz: int
    high_hz: int
    modes: tuple[str, ...] = ()
    low_w: float | None = None
    high_w: float | None = None

    def to_dict(self) -> dict:
        found = {"min_hz": self.low_hz, "max_hz": self.high_hz, "modes": list(self.modes)}
        if self.high_w is not None:
            found.update({"puissance_min_w": self.low_w, "puissance_max_w": self.high_w})
        return found


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
    get_level_ranges: dict[str, LevelRange] = field(default_factory=dict)  # plages des niveaux en lecture
    get_params: tuple[str, ...] = ()
    set_params: tuple[str, ...] = ()
    ptt_declared: str = ""            # « PTT type » de dump_caps (« Rig capable », « None »…) ; vide = absent
    rig_type: str = ""
    async_data: bool | None = None    # « Has async data support »
    backend_warnings: int | None = None   # « Overall backend warnings »
    rx_ranges: tuple[FreqRange, ...] = ()
    tx_ranges: tuple[FreqRange, ...] = ()

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
            "parametres_lecture": list(self.get_params), "parametres_ecriture": list(self.set_params),
            "ptt_declare": self.ptt_declared, "type": self.rig_type, "async": self.async_data,
            "avertissements_backend": self.backend_warnings,
            "plages_rx": [r.to_dict() for r in self.rx_ranges], "plages_tx": [r.to_dict() for r in self.tx_ranges],
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


_RANGE_HEADER_RE = re.compile(r"^(TX|RX) ranges #\d+ for [^:]*:\s*$")
_FREQ_RANGE_RE = re.compile(r"^\s+(\d+) Hz - (\d+) Hz\s*$")
_POWER_RE = re.compile(r"Low power:\s*([\d.]+)\s*W,\s*High power:\s*([\d.]+)\s*W")


def _freq_ranges(text: str) -> tuple[tuple[FreqRange, ...], tuple[FreqRange, ...]]:
    """Plages RX et TX de dump_caps (format relevé sur Hamlib 4.7.2 et 5.0 : en-tête, puis plages indentées)."""
    found: dict[str, list[dict]] = {"RX": [], "TX": []}
    kind, current = None, None
    for line in text.splitlines():
        header = _RANGE_HEADER_RE.match(line)
        if header:
            kind, current = header.group(1), None
            continue
        if kind is None:
            continue
        if not line.startswith(("	", " ")):
            kind, current = None, None          # fin du bloc (ligne d'état, autre rubrique)
            continue
        rng = _FREQ_RANGE_RE.match(line)
        if rng:
            current = {"low_hz": int(rng.group(1)), "high_hz": int(rng.group(2)), "modes": ()}
            found[kind].append(current)
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("Mode list:"):
            current["modes"] = tuple(stripped.split(":", 1)[1].split())
        power = _POWER_RE.search(stripped)
        if power:
            current["low_w"], current["high_w"] = float(power.group(1)), float(power.group(2))
    return tuple(FreqRange(**r) for r in found["RX"]), tuple(FreqRange(**r) for r in found["TX"])


def _flag(text: str, label: str) -> bool | None:
    value = _line(text, label)
    return None if not value else value.upper().startswith("Y")


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
    profile.get_level_ranges = _ranges(text, "Get level")
    profile.get_params = _names(text, "Get parameters")
    profile.set_params = _names(text, "Set parameters")
    profile.ptt_declared = (_line(text, "PTT type") or "")[:40]
    profile.rig_type = (_line(text, "Rig type") or "")[:80]
    profile.async_data = _flag(text, "Has async data support")
    warnings = re.search(r"^Overall backend warnings:\s*(\d+)", text, re.MULTILINE)
    profile.backend_warnings = int(warnings.group(1)) if warnings else None
    profile.rx_ranges, profile.tx_ranges = _freq_ranges(text)
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
