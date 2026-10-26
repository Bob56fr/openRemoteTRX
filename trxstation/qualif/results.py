"""Résultats d'une qualification, verdict et brouillon de fiche.

Le verdict est recalculé à partir des résultats bruts (jamais d'un verdict saisi) :
  - un test du socle en échec               -> refuse
  - un test du socle non fait ou ignoré     -> incomplet (à relancer : le poste n'est pas utilisable)
  - tout le socle réussi                    -> validation_en_cours (proposé ; « valide » est une décision de l'éditeur)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .plan import SOCLE_ITEMS
from .profile import HamlibProfile
from .sheet import RigSheet, validate_sheet

REFUSE, INCOMPLETE, IN_VALIDATION = "refuse", "incomplet", "validation_en_cours"
DEFAULT_HAMLIB_MIN = "4.5"


@dataclass
class Check:
    id: str
    label: str
    category: str
    ok: bool | None             # None = non testé, ignoré ou réponse « je ne sais pas »
    detail: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Verdict:
    status: str
    reasons: list[str]

    def to_dict(self) -> dict:
        return {"statut": self.status, "raisons": list(self.reasons)}


def latest(checks: list[Check]) -> dict[str, Check]:
    """Dernier résultat de chaque test (un test relancé remplace le précédent)."""
    found: dict[str, Check] = {}
    for check in checks:
        found[check.id] = check
    return found


def compute_verdict(checks: list[Check]) -> Verdict:
    by_id = latest(checks)
    failed, missing = [], []
    for item_id, item_label in SOCLE_ITEMS:
        check = by_id.get(item_id)
        if check is None or check.ok is None:
            missing.append(item_label)
        elif check.ok is False:
            failed.append(f"{item_label} : {check.detail}")
    if failed:
        return Verdict(REFUSE, ["socle en échec — " + f for f in failed])
    if missing:
        return Verdict(INCOMPLETE, ["socle non testé — " + m for m in missing])
    return Verdict(IN_VALIDATION, ["socle complet et réussi"])


# --------------------------------------------------------------------------- brouillon de fiche

def _feature_sources(profile: HamlibProfile) -> dict[str, list[str]]:
    """Fonction de la fiche -> tests qui la conditionnent (tous doivent réussir)."""
    sources: dict[str, list[str]] = {"freq": ["freq_rw"], "mode": ["mode_rw"], "ptt": ["ptt_cycle", "cat_loss_rx"],
                                     "audio_rx": ["audio_rx"], "audio_tx": ["audio_tx"]}
    if "STRENGTH" in profile.get_levels:
        sources["smetre"] = ["read_level_STRENGTH"]
    for name in ("NR", "NB", "AIP", "COMP", "ANF"):
        if name in profile.set_functions and name != "ANF":
            sources[name.lower()] = [f"write_func_{name}"]
        elif name in profile.get_functions:
            sources[name.lower()] = [f"read_func_{name}"]
    for name in ("PREAMP", "AGC", "SQL", "RFPOWER"):
        if name in profile.set_levels:
            sources[name.lower()] = [f"write_level_{name}"]
    for name in ("ATT", "RFPOWER_METER", "SWR", "ALC", "COMP_METER", "VD_METER", "TEMP_METER"):
        if name in profile.get_levels:
            sources[name.lower()] = [f"read_level_{name}"]
    if profile.caps.filters:
        sources["filtres"] = ["filters"]
    return sources


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text or "")
    return float(match.group(1).replace(",", ".")) if match else None


def collect_measures(checks: list[Check]) -> dict[str, float]:
    by_id = latest(checks)
    measures: dict[str, float] = {}
    if (c := by_id.get("latency")) and c.ok:
        for key in ("latence_cat_ms", "latence_cat_p95_ms", "polling_max_hz"):
            if key in c.data:
                measures[key] = c.data[key]
    if (c := by_id.get("freq_rw")) and "resolution_hz" in c.data:
        measures["resolution_hz"] = c.data["resolution_hz"]
    if (c := by_id.get("ptt_cycle")) and c.ok:
        if (v := _number(r"prise max (\d+) ms", c.detail)) is not None:
            measures["ptt_prise_ms"] = v
        if (v := _number(r"coupure max (\d+) ms", c.detail)) is not None:
            measures["ptt_coupure_ms"] = v
    if (c := by_id.get("cat_loss_rx")) and c.ok and (v := _number(r"coupée en ([\d.,]+) s", c.detail)) is not None:
        measures["retour_rx_perte_cat_s"] = v
    return measures


def draft_sheet(checks: list[Check], profile: HamlibProfile, *, firmware: str = "") -> tuple[RigSheet, Verdict]:
    """Brouillon de fiche, à relire par l'éditeur. Toute fonction non prouvée est marquée indisponible."""
    verdict = compute_verdict(checks)
    by_id = latest(checks)
    fonctions: dict[str, bool] = {}
    avertissements: dict[str, str] = {}
    for feature, ids in _feature_sources(profile).items():
        results = [by_id.get(i) for i in ids]
        ok = all(r is not None and r.ok is True for r in results)
        fonctions[feature] = ok
        if not ok:
            bad = next((r for r in results if r is not None and r.ok is False), None)
            if bad is not None:
                avertissements[feature] = f"en échec à la qualification : {bad.detail}"[:300]
            else:
                avertissements[feature] = "non testé à la qualification"
    if "TUNER" in profile.set_functions or "TUNER" in profile.get_functions:
        fonctions["tuner"] = False
        avertissements["tuner"] = "écriture non qualifiée automatiquement (peut lancer un accord) : à valider à la main"
    if "SCOPE" in profile.declared():
        fonctions["scope"] = False
        avertissements["scope"] = "spectre non qualifié dans cette version"
    status = IN_VALIDATION if verdict.status == IN_VALIDATION else REFUSE
    sheet = RigSheet(
        nom=profile.caps.model_name or f"Modèle {profile.model}", fabricant=profile.caps.manufacturer,
        hamlib_model=profile.model, firmware=[firmware] if firmware else [],
        hamlib_min=profile.hamlib_version or DEFAULT_HAMLIB_MIN, hamlib_teste=profile.hamlib_version,
        statut=status, fiche_version=1, backend_hamlib=profile.backend_status,
        fonctions=fonctions, avertissements=avertissements, mesures=collect_measures(checks),
        validation={"installations": 0, "heures_cumulees": 0, "rapports_qualif": 1})
    problems = validate_sheet(sheet)
    if problems:                                  # sécurité : jamais un brouillon utilisable incohérent
        sheet.statut = REFUSE
    return sheet, verdict
