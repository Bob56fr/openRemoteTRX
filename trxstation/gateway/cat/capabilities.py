# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Descripteur de capacités d'un poste, extrait de `rigctl -m <modèle> -u` (dump_caps Hamlib).

L'application construit son interface à partir de ce descripteur : aucun modèle n'est codé
en dur. Si le format de Hamlib n'est pas reconnu, on retombe sur un jeu minimal marqué
`complete=False`, jamais sur des suppositions présentées comme exactes.

À valider sur le Pi avec le vrai Hamlib : l'analyse est tolérante mais le format exact
de dump_caps varie un peu selon les versions.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import asdict, dataclass, field

from ...hamlib import find_tool
from .client import MODE_RE

FALLBACK_MODES = ("USB", "LSB", "FM", "AM")
# Modes « données » (audio USB émis) : le nom dépend de la version de Hamlib (4.7 : FM-D et AM-D au lieu de PKTFM, PKTAM).
DATA_MODES = {"USB": ("PKTUSB",), "LSB": ("PKTLSB",), "FM": ("PKTFM", "FM-D"), "AM": ("PKTAM", "AM-D")}
ALL_DATA_MODES = tuple(name for names in DATA_MODES.values() for name in names)


def data_mode_for(mode: str | None, available) -> str | None:
    """Mode données correspondant à `mode` parmi `available` (None si aucun) ; sans liste connue, le nom habituel."""
    names = DATA_MODES.get(mode or "", ())
    if not available:
        return names[0] if names else None
    return next((n for n in names if n in available), None)


class CapabilitiesError(RuntimeError):
    pass


@dataclass
class Capabilities:
    model: int = 0
    model_name: str = ""
    manufacturer: str = ""
    modes: tuple[str, ...] = FALLBACK_MODES
    can_set_frequency: bool = True
    can_get_frequency: bool = True
    can_set_mode: bool = True
    can_get_mode: bool = True
    can_get_ptt: bool = False          # lecture de l'état PTT
    has_s_meter: bool = False          # niveau STRENGTH lisible
    functions: tuple[str, ...] = ()    # fonctions lisibles (NR, NB, AIP...) ; vide = inconnu
    levels: tuple[str, ...] = ()       # niveaux lisibles (PREAMP, SQL, SWR...) ; vide = inconnu
    complete: bool = False             # False = valeurs de repli, format Hamlib non reconnu
    filters: dict[str, list[int]] = field(default_factory=dict)  # mode -> largeurs en Hz, de la plus large à la plus étroite
    preamps: tuple[int, ...] = ()      # valeurs de préampli en dB (sans le 0 = arrêt) ; vide = inconnu
    attenuators: tuple[int, ...] = ()  # valeurs d'atténuateur en dB (« Attenuator: 20dB ») ; vide = inconnu
    level_ranges: dict[str, list[float]] = field(default_factory=dict)   # niveau réglable -> [min, max, pas] (« Set level »)
    can_get_split: bool | None = None  # « Can get Split VFO » ; None = non déclaré (la sécurité tente quand même la lecture)
    max_rit_hz: int = 0                # « Max RIT: -9.999kHz/+9.999kHz » -> 9999 ; 0 = inconnu
    max_xit_hz: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["modes"] = list(self.modes)
        data["functions"], data["levels"] = list(self.functions), list(self.levels)
        data["preamps"], data["attenuators"] = list(self.preamps), list(self.attenuators)
        return data


def _flag(text: str, verb: str, what: str) -> bool | None:
    m = re.search(rf"^Can {verb} {what}:\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
    return None if m is None else m.group(1).upper().startswith("Y")


def _max_offset(text: str, what: str) -> int:
    """« Max RIT: -9.999kHz/+9.999kHz » -> 9999 (Hz) ; 0 si absent ou illisible."""
    m = re.search(rf"^Max {what}:\s*-?\s*([\d.]+)\s*(k?)Hz\s*/\s*\+?\s*([\d.]+)\s*(k?)Hz", text, re.MULTILINE | re.IGNORECASE)
    if m is None:
        return 0
    try:
        return round(float(m.group(3)) * (1000 if m.group(4).lower() == "k" else 1))
    except ValueError:
        return 0


def _names(text: str, label: str) -> tuple[str, ...]:
    """Noms d'une liste « Get level: AF(0..1/0.004) STRENGTH(...) » ou « Get functions: NB NR AIP »."""
    match = re.search(rf"^{label}:\s*(.*)$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ()
    return tuple(dict.fromkeys(re.findall(r"\b([A-Z][A-Z0-9_]+)(?=\(|\s|$)", match.group(1))))


def _ranges(text: str, label: str = "Set level") -> dict[str, list[float]]:
    """« Set level: NB(0.000000..10.000000/1.000000) NR(0..1/0.0667) » -> {"NB": [0, 10, 1], ...} (plages non vides)."""
    match = re.search(rf"^{label}:\s*(.*)$", text, re.MULTILINE | re.IGNORECASE)
    found: dict[str, list[float]] = {}
    if not match:
        return found
    for name, low, high, step in re.findall(r"\b([A-Z][A-Z0-9_]+)\(\s*(-?[\d.]+)\.\.(-?[\d.]+)/(-?[\d.]+)\s*\)", match.group(1)):
        try:
            lo, hi, st = float(low), float(high), float(step)
        except ValueError:
            continue
        if hi > lo:                                   # « 0..0 » : plage inconnue, ignorée
            found[name] = [lo, hi, st]
    return found


def _hertz(text: str) -> int | None:
    """« 2.4 kHz » -> 2400 ; « 500 Hz » -> 500."""
    match = re.match(r"\s*([\d.]+)\s*(MHz|kHz|Hz)?", text.strip(), re.IGNORECASE)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    unit = (match.group(2) or "Hz").lower()
    hertz = round(value * {"mhz": 1_000_000, "khz": 1000, "hz": 1}[unit])
    return hertz if hertz > 0 else None


def _bandwidths(text: str) -> dict[str, list[int]]:
    """Section « Bandwidths: » de dump_caps : une ligne par mode avec Normal, Narrow et Wide."""
    found: dict[str, list[int]] = {}
    for mode, normal, narrow, wide in re.findall(
            r"^[ \t]*([A-Za-z0-9\-]+)[ \t]+Normal:\s*([^,\n]+),\s*Narrow:\s*([^,\n]+),\s*Wide:\s*([^\n]+)$", text, re.MULTILINE):
        widths = sorted({w for w in (_hertz(wide), _hertz(normal), _hertz(narrow)) if w}, reverse=True)
        if widths:
            found[mode] = widths
    return found


def parse_dump_caps(text: str, model: int = 0) -> Capabilities:
    caps = Capabilities(model=model)
    if m := re.search(r"^Model name:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE):
        caps.model_name = m.group(1).strip()
    if m := re.search(r"^Mfg name:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE):
        caps.manufacturer = m.group(1).strip()

    modes_line = re.search(r"^Mode list:\s*(.*)$", text, re.MULTILINE | re.IGNORECASE)
    modes = tuple(t for t in (modes_line.group(1).split() if modes_line else []) if MODE_RE.fullmatch(t))
    caps.complete = bool(modes)
    if modes:
        caps.modes = modes

    for attr, verb, what in (("can_set_frequency", "set", "Frequency"), ("can_get_frequency", "get", "Frequency"),
                             ("can_set_mode", "set", "Mode"), ("can_get_mode", "get", "Mode"),
                             ("can_get_ptt", "get", "PTT")):
        value = _flag(text, verb, what)                    # (split et clarifieur : plus bas)
        if value is not None:
            setattr(caps, attr, value)

    levels = re.search(r"^Get level:\s*(.*)$", text, re.MULTILINE | re.IGNORECASE)
    caps.has_s_meter = bool(levels and re.search(r"\bSTRENGTH\b", levels.group(1)))
    caps.levels = _names(text, "Get level")
    caps.functions = _names(text, "Get functions")
    caps.can_get_split = _flag(text, "get", "Split VFO")
    caps.max_rit_hz, caps.max_xit_hz = _max_offset(text, "RIT"), _max_offset(text, "XIT")
    caps.filters = _bandwidths(text)
    preamp = re.search(r"^Preamp:\s*(.*)$", text, re.MULTILINE | re.IGNORECASE)
    caps.preamps = tuple(int(v) for v in re.findall(r"\d+", preamp.group(1))) if preamp else ()
    att = re.search(r"^Attenuator:\s*(.*)$", text, re.MULTILINE | re.IGNORECASE)
    caps.attenuators = tuple(int(v) for v in re.findall(r"\d+", att.group(1)) if int(v) > 0) if att else ()
    caps.level_ranges = _ranges(text)
    return caps


def _run_dump_caps(model: int, hamlib_dir: str = "") -> str:
    rigctl = find_tool("rigctl", hamlib_dir)
    if not rigctl:
        raise CapabilitiesError("`rigctl` introuvable : installe Hamlib ou renseigne [tools] hamlib_dir.")
    try:
        done = subprocess.run([rigctl, "-m", str(int(model)), "-u"], capture_output=True,
                              text=True, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise CapabilitiesError("`rigctl -u` : délai dépassé") from exc
    if done.returncode != 0 or not done.stdout.strip():
        raise CapabilitiesError(f"`rigctl -u` a échoué : {done.stderr.strip()[:200]}")
    return done.stdout


async def load_capabilities(model: int, hamlib_dir: str = "") -> Capabilities:
    """Interroge Hamlib hors ligne (sans poste branché) pour décrire le modèle."""
    text = await asyncio.to_thread(_run_dump_caps, model, hamlib_dir)
    return parse_dump_caps(text, model)
