"""Thèmes : couleurs par RÔLE, chartes prêtes à l'emploi, contrôle du contraste, polices autorisées.

Règles (§9 du cahier des charges) :
  * texte principal et secondaire : contraste d'au moins 4,5:1 sur le fond et sur la surface des widgets
    (niveau AA des recommandations WCAG pour le texte courant) ;
  * éléments graphiques (accent, mesures, alerte, émission) : au moins 3:1 sur la surface ;
  * la couleur d'ÉMISSION est réservée : aucune autre couleur de rôle ne doit lui ressembler, pour que l'état
    d'émission reste reconnaissable d'un coup d'œil.
"""
from __future__ import annotations

import math
import re

ROLES = ("background", "surface", "text", "text_secondary", "accent", "measure", "alert", "emission")
TEXT_ROLES = ("text", "text_secondary")
GRAPHIC_ROLES = ("accent", "measure", "alert", "emission")
MIN_TEXT_CONTRAST = 4.5
MIN_GRAPHIC_CONTRAST = 3.0
MIN_EMISSION_DISTANCE = 80.0        # distance dans l'espace RVB (0-441) en dessous de laquelle deux couleurs se confondent
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Polices sous licence libre (OFL ou Apache) que le designer peut embarquer ; « system » = police du système.
FONTS = {
    "ui": ("system", "Inter", "Roboto", "Noto Sans", "Atkinson Hyperlegible"),
    "display": ("system", "DSEG7 Classic", "Share Tech Mono", "Orbitron"),
    "numeric": ("system", "JetBrains Mono", "Roboto Mono", "Noto Sans Mono"),
}
BASE_SIZE_RANGE = (12, 24)          # taille de base en px
MIN_PHONE_BASE_SIZE = 14

# « nuit » : tout est rouge atténué pour préserver la vision nocturne ; l'émission y est donc BLANCHE (le rouge
# ne se distinguerait plus du reste de l'écran).
PRESETS: dict[str, dict[str, dict[str, str]]] = {
    "icom": {
        "dark": {"background": "#05080d", "surface": "#0f1822", "text": "#e8f1f8", "text_secondary": "#9fb3c4",
                 "accent": "#3fa9f5", "measure": "#41d36a", "alert": "#f0b429", "emission": "#ff3b30"},
        "light": {"background": "#f4f7fa", "surface": "#ffffff", "text": "#0d1b2a", "text_secondary": "#425466",
                  "accent": "#0a6fc2", "measure": "#1a7f3c", "alert": "#a15c00", "emission": "#d70015"},
    },
    "nuit": {
        "dark": {"background": "#000000", "surface": "#140404", "text": "#ff8a7a", "text_secondary": "#d9685a",
                 "accent": "#c2410c", "measure": "#b45309", "alert": "#d97706", "emission": "#fff2cc"},
        "light": {"background": "#1a0606", "surface": "#260a0a", "text": "#ffb3a7", "text_secondary": "#f0897b",
                  "accent": "#ea580c", "measure": "#d97706", "alert": "#f59e0b", "emission": "#ffffff"},
    },
    "plein_soleil": {
        "dark": {"background": "#000000", "surface": "#111111", "text": "#ffffff", "text_secondary": "#e0e0e0",
                 "accent": "#4fc3f7", "measure": "#69f0ae", "alert": "#ffd54f", "emission": "#ff1744"},
        "light": {"background": "#ffffff", "surface": "#ffffff", "text": "#000000", "text_secondary": "#262626",
                  "accent": "#0047ab", "measure": "#006400", "alert": "#8a4b00", "emission": "#c8000f"},
    },
    "rack_studio": {
        "dark": {"background": "#16181b", "surface": "#2a2d31", "text": "#f2efe9", "text_secondary": "#c4beb3",
                 "accent": "#f5a623", "measure": "#7ed957", "alert": "#ffd166", "emission": "#ff4d4d"},
        "light": {"background": "#d9d6d0", "surface": "#ece9e3", "text": "#1c1c1c", "text_secondary": "#3d3a35",
                  "accent": "#8a4f00", "measure": "#2e6b12", "alert": "#7a5200", "emission": "#c1121f"},
    },
    "sobre": {
        "dark": {"background": "#121212", "surface": "#1e1e1e", "text": "#ededed", "text_secondary": "#b3b3b3",
                 "accent": "#8ab4f8", "measure": "#81c995", "alert": "#fdd663", "emission": "#f28b82"},
        "light": {"background": "#fafafa", "surface": "#ffffff", "text": "#202124", "text_secondary": "#4d5156",
                  "accent": "#1a73e8", "measure": "#188038", "alert": "#6b5900", "emission": "#c5221f"},
    },
}
DEFAULT_PRESET = "icom"


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _luminance(color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs « #rrggbb » (1 à 21)."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def distance(a: str, b: str) -> float:
    return math.dist(_rgb(a), _rgb(b))


def resolve_colors(theme: dict) -> dict[str, str]:
    """Couleurs effectives : charte (et variante claire/sombre) puis surcharges de l'utilisateur."""
    preset = PRESETS[theme.get("preset", DEFAULT_PRESET)]["dark" if theme.get("dark", True) else "light"]
    return {**preset, **theme.get("colors", {})}


def check_colors(colors: dict[str, str]) -> list[str]:
    """Problèmes de lisibilité et de sécurité d'une palette complète (liste vide = palette acceptée)."""
    problems = []
    for role in TEXT_ROLES:
        for ground in ("background", "surface"):
            ratio = contrast(colors[role], colors[ground])
            if ratio < MIN_TEXT_CONTRAST:
                problems.append(f"contraste insuffisant entre « {role} » et « {ground} » : {ratio:.1f}:1 "
                                f"(minimum {MIN_TEXT_CONTRAST}:1)")
    for role in GRAPHIC_ROLES:
        ratio = contrast(colors[role], colors["surface"])
        if ratio < MIN_GRAPHIC_CONTRAST:
            problems.append(f"contraste insuffisant entre « {role} » et « surface » : {ratio:.1f}:1 "
                            f"(minimum {MIN_GRAPHIC_CONTRAST}:1)")
    for role in ROLES:
        if role != "emission" and distance(colors[role], colors["emission"]) < MIN_EMISSION_DISTANCE:
            problems.append(f"la couleur « {role} » ressemble trop à la couleur d'émission, qui est réservée")
    return problems
