"""Catalogue du format de mise en page : appareils, grilles, cibles et types de widgets.

Chaque type de widget déclare :
  * sa liaison (`bind`) : "func" (fonction marche/arrêt Hamlib), "level" (niveau Hamlib), "none" ;
  * s'il accepte une CIBLE (récepteur Main/Sub, VFO A/B) ;
  * ses apparences possibles (la première est l'apparence par défaut) ;
  * sa taille minimale en cases de grille (largeur, hauteur) ;
  * s'il est VERROUILLÉ (sécurité : toujours présent, jamais caché) ou s'il est un CONTENEUR.
Ajouter un type ici ne donne aucun droit : la station filtre toujours les commandes (protocole fermé).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FORMAT_VERSION = 1
DEVICES = ("phone", "tablet", "desktop")                       # du plus petit au plus grand : la cascade monte
DEVICE_LABELS = {"phone": "smartphone", "tablet": "tablette", "desktop": "ordinateur"}
ORIENTATIONS = ("portrait", "landscape")
GRID_COLUMNS = {"phone": 4, "tablet": 8, "desktop": 12}
MAX_ROWS = 200
TARGETS = ("current", "main", "sub", "vfoa", "vfob")            # « current » : poste à un seul récepteur
GESTURES = ("tap", "double_tap", "long_press", "swipe")
HAMLIB_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,23}$")        # NR, NB, SQL, RFPOWER_METER...
WIDGET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

MAX_WIDGETS = 400               # dans tout le profil, conteneurs compris
MAX_PROFILE_BYTES = 60_000      # au-delà, le profil ne passerait plus dans le canal de contrôle
MAX_LABEL = 40
MAX_NAME = 60


@dataclass(frozen=True)
class WidgetType:
    bind: str = "none"                      # "func" | "level" | "none"
    target: bool = False                    # accepte une cible (Main/Sub...)
    appearances: tuple[str, ...] = ("default",)
    min_size: tuple[int, int] = (1, 1)      # (largeur, hauteur) en cases
    locked: bool = False                    # sécurité : présent dans chaque variante, jamais dans un conteneur
    container: str = ""                     # "" | "accordion" | "layers"


WIDGETS: dict[str, WidgetType] = {
    # --- sécurité (verrouillés, §5 du cahier des charges)
    "ptt": WidgetType(appearances=("toggle",), min_size=(2, 2), locked=True),
    "tx_indicator": WidgetType(appearances=("badge",), locked=True),
    "link_status": WidgetType(appearances=("badge",), locked=True),
    "tx_armed": WidgetType(appearances=("checkbox",), locked=True),
    # --- commandes d'émission non verrouillées
    "stop": WidgetType(appearances=("button",)),
    "tot": WidgetType(appearances=("countdown",)),
    # --- affichage
    "frequency": WidgetType(target=True, appearances=("digits", "field", "keypad"), min_size=(2, 1)),
    "mode": WidgetType(target=True, appearances=("pill", "select", "buttons")),
    "smeter": WidgetType(target=True, appearances=("bargraph", "needle", "value"), min_size=(2, 1)),
    "meter": WidgetType(bind="level", target=True, appearances=("bargraph", "needle", "value")),
    "waterfall": WidgetType(target=True, appearances=("waterfall", "spectrum"), min_size=(2, 2)),
    "scope": WidgetType(target=True, appearances=("scope",), min_size=(2, 2)),
    # --- commandes du poste
    "switch": WidgetType(bind="func", target=True, appearances=("button", "toggle", "slider2")),
    "slider": WidgetType(bind="level", target=True, appearances=("hslider", "vslider", "knob")),
    "select": WidgetType(bind="level", target=True, appearances=("buttons", "dropdown", "rotary", "cycle")),
    "filter": WidgetType(target=True, appearances=("cycle", "buttons", "dropdown")),
    "antenna": WidgetType(appearances=("buttons", "dropdown", "rotary")),
    "bands": WidgetType(target=True, appearances=("buttons", "dropdown"), min_size=(2, 1)),
    "steps": WidgetType(target=True, appearances=("buttons",), min_size=(2, 1)),
    "memories": WidgetType(appearances=("list",), min_size=(2, 2)),
    # --- divers (les réglages de l'application — audio, affichage, diagnostic — restent toujours disponibles hors profil)
    "label": WidgetType(appearances=("text",)),
    "separator": WidgetType(appearances=("line",)),
    # --- conteneurs
    "accordion": WidgetType(appearances=("accordion",), min_size=(2, 1), container="accordion"),
    "layers": WidgetType(appearances=("layers",), min_size=(2, 2), container="layers"),
}

LOCKED = tuple(name for name, spec in WIDGETS.items() if spec.locked)
