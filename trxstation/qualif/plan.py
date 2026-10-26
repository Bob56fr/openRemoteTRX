"""Cahier de test d'un modèle : partie FIXE (socle et exercices, communs à tous les postes) plus partie
GÉNÉRÉE depuis le profil Hamlib (fonctions déclarées que TRX Remote sait utiliser).

Les tests générés passent par la couche CAT de l'application (PttController, CatLink), jamais par
`rigctl` directement : on qualifie notre implémentation, pas seulement Hamlib.

Catégories :
  socle     : un échec refuse le poste ; non testé = qualification incomplète
  genere    : fonction déclarée par Hamlib et utilisée par TRX Remote ; un échec la masque
  fixe      : exercices communs (pannes, endurance USB) ; informatifs pour la fiche
  declaratif: réponses de l'opérateur, jamais suffisantes seules
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..gateway.cat.client import WRITABLE_FUNCS, WRITABLE_LEVELS
from ..gateway.cat.link import EXTRA_FUNCTIONS, EXTRA_LEVELS, POWER_METER, TX_METERS
from .profile import HamlibProfile

SOCLE, GENERE, FIXE, DECLARATIF = "socle", "genere", "fixe", "declaratif"

# Ce que TRX Remote lit et écrit aujourd'hui (repris de la couche CAT : une seule source).
READ_FUNCS = tuple(dict.fromkeys(EXTRA_FUNCTIONS))
READ_LEVELS = tuple(dict.fromkeys(("STRENGTH", *EXTRA_LEVELS, POWER_METER, *TX_METERS)))
WRITE_FUNCS = tuple(WRITABLE_FUNCS)
WRITE_LEVELS = tuple(WRITABLE_LEVELS)
# Écritures jamais lancées automatiquement : leur effet peut être une émission.
NO_AUTO_WRITE = {"TUNER": "l'activation du tuner peut lancer un accord, donc une porteuse"}
CORE_MODES = ("USB", "LSB", "CW", "AM", "FM")

LABELS = {
    "NR": "réducteur de bruit (NR)", "NB": "noise blanker (NB)", "AIP": "IP+", "COMP": "compresseur",
    "TUNER": "tuner d'antenne", "ANF": "filtre notch auto (ANF)", "STRENGTH": "S-mètre", "PREAMP": "préampli",
    "ATT": "atténuateur", "AGC": "AGC", "SQL": "squelch", "RFPOWER": "puissance réglée",
    "VD_METER": "tension d'alimentation", "TEMP_METER": "température", "RFPOWER_METER": "puissance mesurée",
    "SWR": "ROS", "ALC": "ALC", "COMP_METER": "taux de compression",
}

# Socle fixe : identique pour tous les postes (cahier des charges, section 5).
SOCLE_ITEMS = (
    ("cat", "Connexion CAT et lecture de l'état PTT"),
    ("cat_endurance", "Endurance de la liaison CAT"),
    ("freq_rw", "Fréquence : écriture et relecture"),
    ("mode_rw", "Mode : écriture et relecture"),
    ("audio_rx", "Audio en réception"),
    ("ptt_cycle", "PTT activé puis désactivé, avec relecture"),
    ("cat_loss_rx", "Retour en réception sur perte de la liaison CAT"),
)
FIXED_ITEMS = (
    ("latency", "Temps de réponse CAT"),
    ("usb_replug", "Reprise après débranchement USB"),
    ("audio_tx", "Audio en émission"),
    ("drill_heartbeat", "Panne : perte du heartbeat"),
    ("drill_tot", "Panne : TOT"),
    ("drill_disconnect", "Panne : déconnexion du client"),
    ("filters", "Filtres (largeur de bande)"),
)


@dataclass(frozen=True)
class PlanItem:
    id: str
    label: str
    category: str
    action: str = ""        # read_func, read_level, write_func, write_level, mode, manual, fixed
    target: str = ""        # nom Hamlib visé
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TestPlan:
    items: list[PlanItem]
    unused: list[str]       # déclaré par Hamlib, non exploité par TRX Remote (piste d'évolution)

    def by_id(self, item_id: str) -> PlanItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    def of(self, category: str) -> list[PlanItem]:
        return [i for i in self.items if i.category == category]

    def to_dict(self) -> dict:
        return {"tests": [i.to_dict() for i in self.items], "disponibles_non_exploitees": list(self.unused)}


def label(name: str) -> str:
    return LABELS.get(name, name)


def core_modes(profile: HamlibProfile) -> tuple[str, ...]:
    """Modes du socle présents sur le poste ; tous ses modes s'il n'en a aucun (poste FM seul, etc.)."""
    core = tuple(m for m in CORE_MODES if m in profile.modes)
    return core or profile.modes


def build_plan(profile: HamlibProfile) -> TestPlan:
    items = [PlanItem(i, lbl, SOCLE, "fixed") for i, lbl in SOCLE_ITEMS]
    items += [PlanItem(i, lbl, FIXE, "fixed") for i, lbl in FIXED_ITEMS]
    for mode in profile.modes:
        items.append(PlanItem(f"mode_{mode}", f"Mode {mode}", GENERE, "mode", mode,
                              "fait partie du socle" if mode in core_modes(profile) else ""))
    for name in READ_FUNCS:
        if name in profile.get_functions:
            items.append(PlanItem(f"read_func_{name}", f"Lecture : {label(name)}", GENERE, "read_func", name))
    for name in READ_LEVELS:
        if name in profile.get_levels:
            note = "valeur significative en émission seulement" if name in (POWER_METER, *TX_METERS) else ""
            items.append(PlanItem(f"read_level_{name}", f"Lecture : {label(name)}", GENERE, "read_level", name, note))
    for name in WRITE_FUNCS:
        if name in profile.set_functions:
            if name in NO_AUTO_WRITE:
                items.append(PlanItem(f"write_func_{name}", f"Écriture : {label(name)}", GENERE, "manual", name,
                                      f"non testé automatiquement : {NO_AUTO_WRITE[name]}"))
            else:
                items.append(PlanItem(f"write_func_{name}", f"Écriture : {label(name)}", GENERE, "write_func", name))
    for name in WRITE_LEVELS:
        if name in profile.set_levels:
            items.append(PlanItem(f"write_level_{name}", f"Écriture : {label(name)}", GENERE, "write_level", name))
    used = set(READ_FUNCS) | set(READ_LEVELS) | set(WRITE_FUNCS) | set(WRITE_LEVELS)
    unused = sorted(profile.declared() - used)
    return TestPlan(items, unused)


def render_plan(plan: TestPlan, profile: HamlibProfile) -> str:
    """Texte lisible du cahier de test (option --plan)."""
    lines = [f"Cahier de test : {profile.name} (modèle Hamlib {profile.model}, "
             f"backend {profile.backend_status or 'statut inconnu'}, Hamlib {profile.hamlib_version or '?'})", ""]
    titles = {SOCLE: "Socle obligatoire (un échec refuse le poste)", FIXE: "Tests fixes (communs à tous les postes)",
              GENERE: "Tests générés depuis Hamlib"}
    for category in (SOCLE, FIXE, GENERE):
        lines.append(titles[category])
        for item in plan.of(category):
            lines.append(f"  - {item.label}" + (f"  ({item.note})" if item.note else ""))
        lines.append("")
    if plan.unused:
        lines.append("Déclaré par Hamlib, non exploité par TRX Remote : " + ", ".join(plan.unused))
    return "\n".join(lines)
