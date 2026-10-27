# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Thèmes de couleurs de la page : 21 rôles (docs/themes.json) et teintes dérivées calculées à partir d'eux.

Un thème fournit les rôles ; `derive` calcule les autres teintes (fond du PTT au repos, fond d'alerte, palette du
waterfall...) par des mélanges simples dans l'espace RVB, pour qu'un nouveau thème n'ait que 21 couleurs à choisir.
Le thème d'usine (« defaut ») garde ses teintes exactes d'origine (apparence inchangée) et n'est pas contrôlé.
`check` applique les règles du cahier des charges du designer : contraste WCAG AA (4,5:1 pour le texte, 3:1 pour les
graphiques et les grands chiffres) et couleur d'émission réservée (aucune autre couleur ne doit s'en approcher).
Stdlib seule : sert aussi à scripts/build_themes.py (génère client.css et docs/themes.json) et aux tests.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .theme import MIN_EMISSION_DISTANCE, MIN_GRAPHIC_CONTRAST, MIN_TEXT_CONTRAST, contrast, distance

THEMES_FILE = Path(__file__).resolve().parents[2] / "docs" / "themes.json"
WHITE, BLACK = "#ffffff", "#000000"
HEX = re.compile(r"#[0-9a-f]{6}")

ROLES = ("fond", "fond-entete", "fond-panneau", "fond-champ", "texte", "texte-secondaire", "texte-sur-accent", "frequence",
         "accent", "mesure", "bouton-fond", "bouton-texte", "bouton-bord", "smetre-bas", "smetre-haut", "mesure-haut",
         "tx", "erreur", "alerte", "succes", "favori")

# (texte, fond, seuil) : couples lus par l'utilisateur ; les rôles comme les teintes dérivées.
TEXT_PAIRS = (("texte", "fond"), ("texte", "fond-panneau"), ("texte", "fond-champ"), ("texte-secondaire", "fond"),
              ("texte-secondaire", "fond-panneau"), ("bouton-texte", "bouton-fond"), ("texte-sur-accent", "accent"),
              ("texte", "commande-fond"), ("texte-sur-primaire", "accent"), ("texte-sur-erreur", "erreur"),
              ("texte-sur-danger", "danger-fond"), ("texte-sur-tx", "tx"), ("tx-texte", "tx-fond"), ("stop-texte", "stop-fond"),
              ("succes", "succes-fond"), ("succes-sur", "succes"), ("alerte", "alerte-sombre"), ("alerte-sur", "alerte"),
              ("alerte-texte", "alerte-fond"), ("selection-texte", "selection-fond"), ("texte", "memoire-active"),
              ("alerte", "securite-fond"))
# grands textes en gras (WCAG : 3:1 suffit) : l'étiquette du PTT en émission
GRAPHIC_PAIRS = (("ptt-texte", "tx"), ("frequence", "fond-entete"), ("bouton-bord", "fond-entete"), ("accent", "fond-panneau"),
                 ("mesure", "fond-entete"), ("smetre-bas", "fond-entete"), ("smetre-haut", "fond-entete"),
                 ("mesure-haut", "fond-entete"), ("tx", "fond-entete"), ("tx", "fond-panneau"), ("erreur", "fond-panneau"),
                 ("alerte", "fond-panneau"), ("succes", "fond-panneau"), ("favori", "fond-panneau"), ("tx-bord", "fond-entete"))


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def mix(a: str, b: str, weight: float) -> str:
    """`weight` de a, le reste de b."""
    return _hex(x * weight + y * (1 - weight) for x, y in zip(_rgb(a), _rgb(b)))


def rgba(color: str, alpha: float) -> str:
    r, g, b = _rgb(color)
    return f"rgba({r}, {g}, {b}, {f'{alpha:g}'.lstrip('0')})"           # « .85 », comme dans client.css


def readable_on(background: str) -> str:
    return WHITE if contrast(WHITE, background) >= contrast(BLACK, background) else BLACK


def derive(c: dict[str, str]) -> dict[str, str]:
    """Teintes dérivées d'un thème (mêmes noms que le thème d'usine)."""
    tx, fond, alerte = c["tx"], c["fond"], c["alerte"]
    return {
        "ligne": mix(c["texte-secondaire"], fond, .22), "fond-accueil": c["fond-entete"], "fond-instrument": c["fond-champ"],
        "commande-fond": mix(c["texte-secondaire"], c["fond-panneau"], .25), "champ-bord": mix(c["texte-secondaire"], c["fond-champ"], .30),
        "selection-fond": mix(c["accent"], fond, .30), "selection-texte": c["frequence"], "memoire-active": mix(c["accent"], fond, .18),
        "etoile": c["texte-secondaire"], "texte-sur-tx": readable_on(tx), "ptt-texte": WHITE if contrast(WHITE, tx) >= MIN_GRAPHIC_CONTRAST else readable_on(tx), "tx-fond": mix(tx, fond, .14),
        "tx-bord": mix(tx, fond, .75), "tx-texte": mix(tx, WHITE, .25), "tx-actif-bord": mix(tx, WHITE, .55),
        "stop-fond": mix(tx, fond, .20), "stop-bord": mix(tx, fond, .32), "stop-texte": WHITE, "txflag-fond": mix(tx, fond, .12),
        "tx-voile": rgba(mix(tx, BLACK, .5), .85), "danger-fond": mix(c["erreur"], fond, .40),
        "alerte-fond": mix(alerte, fond, .35), "alerte-texte": mix(alerte, WHITE, .55), "alerte-sombre": mix(alerte, fond, .22),
        "alerte-sur": mix(alerte, BLACK, .15), "alerte-vive": alerte, "alerte-halo": rgba(alerte, .55),
        "erreur-halo": rgba(c["erreur"], .55), "securite-fond": mix(alerte, fond, .10), "succes-fond": mix(c["succes"], fond, .18),
        "succes-sur": mix(c["succes"], BLACK, .12), "voile": "rgba(0, 0, 0, .6)", "contour": BLACK,
        "halo-accueil": rgba(c["accent"], .35), "texte-sur-erreur": readable_on(c["erreur"]),
        "texte-sur-primaire": c["texte-sur-accent"], "texte-sur-danger": readable_on(mix(c["erreur"], fond, .40)),
        "spectre-remplissage": rgba(c["mesure"], .35), "spectre-grille": rgba(c["texte"], .11),
        "spectre-grille-forte": rgba(c["texte"], .24),
        "waterfall-degrade": " ".join((mix(c["texte-secondaire"], fond, .05), mix(c["texte-secondaire"], fond, .25),
                                       mix(c["accent"], fond, .60), c["mesure"], mix(c["mesure"], WHITE, .40), WHITE)),
    }


def check(colors: dict[str, str], derived: dict[str, str]) -> list[str]:
    """Problèmes de lisibilité et de sécurité d'un thème (vide = conforme)."""
    problems = [f"rôle manquant : {r}" for r in ROLES if r not in colors]
    problems += [f"{r} : {colors[r]} n'est pas #rrggbb" for r in ROLES if r in colors and not HEX.fullmatch(colors[r])]
    if problems:
        return problems
    every = {**colors, **{k: v for k, v in derived.items() if HEX.fullmatch(v)}}
    for pairs, minimum in ((TEXT_PAIRS, MIN_TEXT_CONTRAST), (GRAPHIC_PAIRS, MIN_GRAPHIC_CONTRAST)):
        for fg, bg in pairs:
            value = contrast(every[fg], every[bg])
            if value < minimum:
                problems.append(f"contraste {fg} sur {bg} : {value:.2f} < {minimum:g}")
    for role in ROLES:
        if role != "tx" and distance(colors["tx"], colors[role]) < MIN_EMISSION_DISTANCE:
            problems.append(f"couleur d'émission trop proche de « {role} » ({colors[role]}) : elle doit rester réservée")
    return problems


def parse_gradient(text: str) -> list[str] | None:
    """Palette du waterfall : 6 couleurs #rrggbb séparées par des espaces (même règle que waterfall.js)."""
    colors = str(text or "").lower().split()
    return colors if len(colors) == 6 and all(HEX.fullmatch(c) for c in colors) else None


def load(path: Path | None = None) -> dict:
    return json.loads((path or THEMES_FILE).read_text(encoding="utf-8"))
