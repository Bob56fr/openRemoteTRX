"""Fiche TRX : ce que TRX Remote sait d'un modèle qualifié, au-delà de Hamlib.

Une fiche par modèle et par plage de firmware (fichier TOML). L'application ne propose que les
fonctions marquées disponibles. Le catalogue est un dossier de fiches ; sa signature viendra au lot Q3.

Règle de sécurité (bloquante, pas un avertissement) : un poste dont le statut le rend utilisable
(valide, restreint, validation_en_cours) doit avoir TOUT le socle disponible.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .profile import version_tuple

STATUSES = ("valide", "restreint", "validation_en_cours", "refuse")
USABLE_STATUSES = ("valide", "restreint", "validation_en_cours")
SOCLE_FEATURES = ("freq", "mode", "ptt", "audio_rx")
FEATURES = {
    "freq": "fréquence", "mode": "mode", "ptt": "PTT avec relecture", "audio_rx": "audio réception",
    "audio_tx": "audio émission", "smetre": "S-mètre", "filtres": "filtres", "scope": "spectre (scope)",
    "nr": "réducteur de bruit", "nb": "noise blanker", "aip": "IP+", "comp": "compresseur", "anf": "notch auto",
    "tuner": "tuner d'antenne", "preamp": "préampli", "att": "atténuateur", "agc": "AGC", "sql": "squelch",
    "rfpower": "réglage de puissance", "rfpower_meter": "puissance mesurée", "swr": "ROS", "alc": "ALC",
    "comp_meter": "taux de compression", "vd_meter": "tension", "temp_meter": "température",
}
MEASURES = ("latence_cat_ms", "latence_cat_p95_ms", "polling_max_hz", "resolution_hz", "ptt_prise_ms", "ptt_coupure_ms",
            "retour_rx_perte_cat_s")
VALIDATION_KEYS = ("installations", "heures_cumulees", "rapports_qualif")
_VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")
MAX_TEXT = 300


class SheetError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("fiche invalide : " + " ; ".join(problems))


@dataclass
class RigSheet:
    nom: str
    hamlib_model: int
    hamlib_min: str
    statut: str
    fiche_version: int = 1
    fabricant: str = ""
    firmware: list[str] = field(default_factory=list)
    hamlib_teste: str = ""
    backend_hamlib: str = ""
    fonctions: dict[str, bool] = field(default_factory=dict)
    avertissements: dict[str, str] = field(default_factory=dict)
    mesures: dict[str, float] = field(default_factory=dict)
    validation: dict[str, int] = field(default_factory=lambda: {k: 0 for k in VALIDATION_KEYS})
    source: str = ""        # fichier d'origine (non écrit)

    @property
    def usable(self) -> bool:
        return self.statut in USABLE_STATUSES

    def available(self, feature: str) -> bool:
        """Fonction proposée par l'application : poste utilisable ET fonction marquée disponible."""
        return self.usable and self.fonctions.get(feature, False)


# --------------------------------------------------------------------------- validation

def validate_sheet(sheet: RigSheet) -> list[str]:
    problems: list[str] = []
    if not isinstance(sheet.nom, str) or not sheet.nom.strip() or len(sheet.nom) > 80:
        problems.append("rig.nom : texte de 1 à 80 caractères attendu")
    if isinstance(sheet.hamlib_model, bool) or not isinstance(sheet.hamlib_model, int) or sheet.hamlib_model <= 0:
        problems.append("rig.hamlib_model : entier positif attendu")
    if sheet.statut not in STATUSES:
        problems.append(f"rig.statut : une valeur parmi {', '.join(STATUSES)}")
    if isinstance(sheet.fiche_version, bool) or not isinstance(sheet.fiche_version, int) or sheet.fiche_version < 1:
        problems.append("rig.fiche_version : entier >= 1 attendu")
    for key in ("hamlib_min", "hamlib_teste"):
        value = getattr(sheet, key)
        if (value or key == "hamlib_min") and not (isinstance(value, str) and _VERSION_RE.fullmatch(value)):
            problems.append(f"rig.{key} : version au format 4.6 ou 4.6.2 attendue")
    if sheet.hamlib_teste and _VERSION_RE.fullmatch(str(sheet.hamlib_teste)) and _VERSION_RE.fullmatch(str(sheet.hamlib_min)) \
            and version_tuple(sheet.hamlib_teste) < version_tuple(sheet.hamlib_min):
        problems.append("rig.hamlib_teste est plus ancienne que rig.hamlib_min")
    if not isinstance(sheet.firmware, list) or not all(isinstance(f, str) and 0 < len(f) <= 20 for f in sheet.firmware):
        problems.append("rig.firmware : liste de versions (texte court) attendue")
    for key, value in sheet.fonctions.items():
        if key not in FEATURES:
            problems.append(f"fonctions.{key} : fonction inconnue")
        elif not isinstance(value, bool):
            problems.append(f"fonctions.{key} : true ou false attendu")
    for key, value in sheet.avertissements.items():
        if key not in FEATURES:
            problems.append(f"avertissements.{key} : fonction inconnue")
        elif not isinstance(value, str) or len(value) > MAX_TEXT:
            problems.append(f"avertissements.{key} : texte de {MAX_TEXT} caractères au plus")
    for key, value in sheet.mesures.items():
        if key not in MEASURES:
            problems.append(f"mesures.{key} : mesure inconnue")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            problems.append(f"mesures.{key} : nombre positif attendu")
    for key, value in sheet.validation.items():
        if key not in VALIDATION_KEYS:
            problems.append(f"validation.{key} : compteur inconnu")
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            problems.append(f"validation.{key} : entier positif attendu")
    if sheet.statut in USABLE_STATUSES:
        missing = [f for f in SOCLE_FEATURES if sheet.fonctions.get(f) is not True]
        if missing:
            problems.append(f"statut « {sheet.statut} » impossible : socle non disponible ({', '.join(missing)})")
    return problems


# --------------------------------------------------------------------------- lecture

def sheet_from_dict(data: dict, source: str = "") -> RigSheet:
    problems: list[str] = []
    rig = data.get("rig")
    if not isinstance(rig, dict):
        raise SheetError(["section [rig] absente"])
    for section in ("fonctions", "avertissements", "mesures", "validation"):
        if section in data and not isinstance(data[section], dict):
            problems.append(f"[{section}] doit être une table")
    unknown = set(data) - {"rig", "fonctions", "avertissements", "mesures", "validation"}
    if unknown:
        problems.append("sections inconnues : " + ", ".join(sorted(unknown)))
    unknown_rig = set(rig) - {"nom", "fabricant", "hamlib_model", "firmware", "hamlib_min", "hamlib_teste",
                              "statut", "fiche_version", "backend_hamlib"}
    if unknown_rig:
        problems.append("champs inconnus dans [rig] : " + ", ".join(sorted(unknown_rig)))
    if problems:
        raise SheetError(problems)
    sheet = RigSheet(
        nom=rig.get("nom", ""), hamlib_model=rig.get("hamlib_model", 0), hamlib_min=rig.get("hamlib_min", ""),
        statut=rig.get("statut", ""), fiche_version=rig.get("fiche_version", 0), fabricant=rig.get("fabricant", ""),
        firmware=rig.get("firmware", []), hamlib_teste=rig.get("hamlib_teste", ""),
        backend_hamlib=rig.get("backend_hamlib", ""), fonctions=dict(data.get("fonctions", {})),
        avertissements=dict(data.get("avertissements", {})), mesures=dict(data.get("mesures", {})),
        validation=dict(data.get("validation", {k: 0 for k in VALIDATION_KEYS})), source=source)
    problems = validate_sheet(sheet)
    if problems:
        raise SheetError(problems)
    return sheet


def load_sheet(path: Path) -> RigSheet:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SheetError([f"lecture impossible : {exc}"]) from exc
    except tomllib.TOMLDecodeError as exc:
        raise SheetError([f"TOML invalide : {exc}"]) from exc
    return sheet_from_dict(data, str(path))


# --------------------------------------------------------------------------- écriture

def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(round(value, 3))
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    text = "".join(c if c.isprintable() else " " for c in text)
    return f'"{text}"'


def render_sheet(sheet: RigSheet, header: list[str] | None = None) -> str:
    problems = validate_sheet(sheet)
    if problems:
        raise SheetError(problems)
    lines = [f"# {h}" for h in header or []]
    if lines:
        lines.append("")
    lines.append("[rig]")
    for key in ("nom", "fabricant", "hamlib_model", "firmware", "hamlib_min", "hamlib_teste", "statut",
                "fiche_version", "backend_hamlib"):
        value = getattr(sheet, key)
        if value not in ("", None) or key in ("nom", "hamlib_model", "hamlib_min", "statut", "fiche_version"):
            lines.append(f"{key} = {_toml_value(value)}")
    for section in ("fonctions", "avertissements", "mesures", "validation"):
        table = getattr(sheet, section)
        if not table:
            continue
        lines += ["", f"[{section}]"]
        order = list(FEATURES) if section in ("fonctions", "avertissements") else \
            list(MEASURES) if section == "mesures" else list(VALIDATION_KEYS)
        for key in sorted(table, key=lambda k: order.index(k) if k in order else len(order)):
            lines.append(f"{key} = {_toml_value(table[key])}")
    text = "\n".join(lines) + "\n"
    sheet_from_dict(tomllib.loads(text))          # relecture : le fichier écrit doit être valide
    return text


# --------------------------------------------------------------------------- catalogue

@dataclass
class Catalog:
    sheets: dict[int, list[RigSheet]] = field(default_factory=dict)
    problems: dict[str, list[str]] = field(default_factory=dict)

    def lookup(self, model: int, firmware: str = "", hamlib: str = "") -> tuple[RigSheet | None, list[str]]:
        """Fiche du modèle (celle du firmware s'il est connu) et avertissements à afficher."""
        candidates = self.sheets.get(model, [])
        if not candidates:
            return None, ["poste absent du catalogue : non qualifié"]
        warnings: list[str] = []
        exact = [s for s in candidates if firmware and firmware in s.firmware]
        pool = exact or candidates
        sheet = max(pool, key=lambda s: s.fiche_version)
        if firmware and not exact:
            warnings.append(f"firmware {firmware} non qualifié (qualifiés : {', '.join(sheet.firmware) or 'aucun'})")
        if hamlib and version_tuple(hamlib) and version_tuple(hamlib) < version_tuple(sheet.hamlib_min):
            warnings.append(f"Hamlib {hamlib} plus ancien que la version minimale qualifiée ({sheet.hamlib_min})")
        if sheet.statut == "validation_en_cours":
            warnings.append("poste en validation : pas encore assez de retours d'utilisateurs")
        warnings += [f"{FEATURES[k]} : {v}" for k, v in sheet.avertissements.items()]
        return sheet, warnings


def load_catalog(directory: Path) -> Catalog:
    """Charge toutes les fiches *.toml ; une fiche invalide est écartée et signalée, jamais à moitié utilisée."""
    catalog = Catalog()
    directory = Path(directory)
    if not directory.is_dir():
        catalog.problems[str(directory)] = ["dossier du catalogue introuvable"]
        return catalog
    for path in sorted(directory.glob("*.toml")):
        try:
            sheet = load_sheet(path)
        except SheetError as exc:
            catalog.problems[path.name] = exc.problems
            continue
        catalog.sheets.setdefault(sheet.hamlib_model, []).append(sheet)
    return catalog
