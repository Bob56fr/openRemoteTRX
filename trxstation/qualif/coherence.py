# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Constats d'une qualification ou d'une exploration : incohérences de `dump_caps` (sans toucher au poste) et
écarts entre ce que Hamlib déclare et ce que le poste répond.

Hamlib DÉCLARE, il ne garantit pas : chaque constat est une piste à vérifier, jamais une décision. Les constats
dont la source est Hamlib portent un texte anglais pour le brouillon de rapport aux développeurs de Hamlib.

Gravités :
  bloquant  : TRX Remote ne peut pas piloter le poste ainsi (fréquence, mode ou PTT illisibles)
  attention : un comportement à vérifier à la main avant de faire confiance à la fonction
  info      : à savoir (plage non renseignée, lecture seule…)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .profile import HamlibProfile, LevelRange
from .texts import _t, has

BLOQUANT, ATTENTION, INFO = "bloquant", "attention", "info"
SEVERITIES = (BLOQUANT, ATTENTION, INFO)
HAMLIB, POSTE, TRX = "hamlib", "poste", "trx"   # source supposée : déclaration Hamlib, poste (ou firmware), TRX Remote
DATA_MODE_PREFIXES = ("PKT",)
DATA_MODE_SUFFIX = "-D"


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    source: str
    title: str
    detail: str = ""
    title_en: str = ""          # pour le rapport aux développeurs de Hamlib (source « hamlib »)
    detail_en: str = ""
    # Affichage traduit (lot L3) : clé `finding.<key>.title` / `.detail` de qualif.<langue>.json et ses variables
    # (une liste = termes `term.<nom>` à traduire). Jamais écrits dans les documents (to_dict).
    key: str = field(default="", compare=False)
    args: dict = field(default_factory=dict, compare=False, hash=False)

    def to_dict(self) -> dict:
        data = asdict(self)
        del data["key"], data["args"]
        return data

    def shown(self) -> tuple[str, str]:
        """(titre, détail) dans la langue de l'outil ; le texte enregistré (français) si aucune clé ne le décrit."""
        if not self.key:
            return self.title, self.detail
        fields = {k: ", ".join(_t(f"term.{x}") for x in v) if isinstance(v, list) else v for k, v in self.args.items()}
        title = _t(f"finding.{self.key}.title", **fields)
        detail_key = f"finding.{self.key}.detail"
        detail = _t(detail_key, **fields) if self.detail and has(detail_key) else self.detail
        return title, detail


def _on_grid(value: float, rng: LevelRange) -> bool:
    if not rng.low <= value <= rng.high:
        return False
    if rng.step <= 0:
        return True
    ratio = (value - rng.low) / rng.step
    return abs(ratio - round(ratio)) < 1e-6


def _fmt(values) -> str:
    return ", ".join(f"{v:g}" for v in values)


def _list_vs_range(profile: HamlibProfile, name: str, values: tuple[int, ...], what: str, what_en: str,
                   example: str = "") -> Finding | None:
    rng = profile.level_ranges.get(name) or profile.get_level_ranges.get(name)
    if not values or rng is None or (rng.low == rng.high == 0):
        return None
    off = [v for v in values if not _on_grid(v, rng)]
    if not off:
        return None
    return Finding(
        f"list_vs_range_{name}", ATTENTION, HAMLIB,
        f"{what} : la liste ({_fmt(values)} dB) ne suit pas la plage {name}({rng.low:g}..{rng.high:g}/{rng.step:g})",
        f"Valeurs hors de la plage : {_fmt(off)}. TRX Remote prend la LISTE déclarée ; vérifier sur le poste quelle valeur "
        f"active quoi{example}.",
        f"{what_en}: declared list ({_fmt(values)} dB) does not match the {name}({rng.low:g}..{rng.high:g}/{rng.step:g}) range",
        f"Values outside the range: {_fmt(off)}.",
        key=f"list_vs_range_{name}",
        args={"values": _fmt(values), "name": name, "low": f"{rng.low:g}", "high": f"{rng.high:g}", "step": f"{rng.step:g}",
              "off": _fmt(off)})


def _is_data_mode(mode: str) -> bool:
    return mode.startswith(DATA_MODE_PREFIXES) or mode.endswith(DATA_MODE_SUFFIX)


def analyse_caps(profile: HamlibProfile) -> list[Finding]:
    """Incohérences visibles dans dump_caps seul (aucune commande envoyée au poste)."""
    found: list[Finding] = []
    can = profile.can
    for key, why in (("set Frequency", "changer la fréquence"), ("get Frequency", "lire la fréquence"),
                     ("set Mode", "changer le mode"), ("get Mode", "lire le mode"), ("get PTT", "relire l'état d'émission")):
        if can.get(key) is False:
            slug = f"cannot_{key.replace(' ', '_').lower()}"
            found.append(Finding(slug, BLOQUANT, TRX,
                                 f"Hamlib déclare « Can {key}: N »", f"TRX Remote doit pouvoir {why} : poste inutilisable tel quel.",
                                 key=slug, args={"can": key}))
    status = profile.backend_status
    if status and status.lower() != "stable":
        found.append(Finding("backend_status", ATTENTION, HAMLIB, f"Backend Hamlib au statut « {status} »",
                             "Pilote moins éprouvé : chaque fonction doit être essayée sur le poste avant de lui faire confiance.",
                             f"Backend status is \"{status}\"",
                             "Every item below was checked on a real rig; it may help to move the backend towards Stable.",
                             key="backend_status", args={"status": status}))
    if profile.backend_warnings:
        found.append(Finding("backend_warnings", ATTENTION, HAMLIB,
                             f"dump_caps signale {profile.backend_warnings} avertissement(s) du backend",
                             "Lire la fin de dump_caps.txt (« Overall backend warnings »).",
                             f"dump_caps reports {profile.backend_warnings} backend warning(s)",
                             key="backend_warnings", args={"count": profile.backend_warnings}))
    if profile.ptt_declared.lower().startswith("none") and can.get("set PTT"):
        found.append(Finding(
            "ptt_type_none", ATTENTION, HAMLIB, "« PTT type: None » mais « Can set PTT: Y »",
            "Selon la version de Hamlib, le PTT par CAT n'est pas annoncé (IC-7300MK2 : None avec 4.7.2, Rig capable avec "
            "5.0). trx-setup choisit la méthode PTT ; l'essai PTT (trx-hwtest, sur charge fictive) tranche.",
            "\"PTT type: None\" while \"Can set PTT: Y\"",
            "The rig keys fine through CAT; the PTT type is reported as \"Rig capable\" by other Hamlib versions.",
            key="ptt_type_none"))
    for finding in (_list_vs_range(profile, "PREAMP", profile.preamps, "Préamplis", "Preamp",
                                   " (IC-7300MK2 : 1 et 2 = P.AMP1 et P.AMP2, pas des dB)"),
                    _list_vs_range(profile, "ATT", profile.attenuators, "Atténuateurs", "Attenuator")):
        if finding:
            found.append(finding)
    agc = profile.level_ranges.get("AGC") or profile.get_level_ranges.get("AGC")
    if agc is not None and agc.low == agc.high and profile.agc_levels:
        found.append(Finding("agc_range_empty", INFO, HAMLIB, f"Plage AGC({agc.low:g}..{agc.high:g}) non renseignée",
                             f"Valeurs prises dans « AGC levels » : {_fmt(profile.agc_levels)}.",
                             f"AGC range AGC({agc.low:g}..{agc.high:g}) is empty while AGC levels lists {_fmt(profile.agc_levels)}",
                             key="agc_range_empty",
                             args={"low": f"{agc.low:g}", "high": f"{agc.high:g}", "values": _fmt(profile.agc_levels)}))
    empty = sorted(n for n, r in {**profile.get_level_ranges, **profile.level_ranges}.items()
                   if r.low == r.high == 0 and r.step == 0 and n != "AGC")
    if empty:
        found.append(Finding("ranges_empty", INFO, HAMLIB, "Niveaux déclarés sans plage : " + ", ".join(empty),
                             "Valeurs admises inconnues : l'exploration ne les écrit pas.",
                             "Levels declared with an empty range (0..0/0): " + ", ".join(empty),
                             key="ranges_empty", args={"names": ", ".join(empty)}))
    for kind, getters, setters, word in (("func", profile.get_functions, profile.set_functions, "Fonctions"),
                                        ("level", profile.get_levels, profile.set_levels, "Niveaux")):
        blind = sorted(set(setters) - set(getters))
        if blind:
            found.append(Finding(f"{kind}_write_only", ATTENTION, HAMLIB, f"{word} réglables mais non relisibles : " + ", ".join(blind),
                                 "Une écriture qu'on ne peut pas relire ne se vérifie pas : TRX Remote ne s'y fie pas.",
                                 f"{'Functions' if kind == 'func' else 'Levels'} settable but not readable: " + ", ".join(blind),
                                 key=f"{kind}_write_only", args={"names": ", ".join(blind)}))
    if profile.tx_ranges:
        tx_modes = {m for r in profile.tx_ranges for m in r.modes}
        missing = [m for m in profile.modes if _is_data_mode(m) and m not in tx_modes]
        if missing:
            found.append(Finding(
                "tx_ranges_data_modes", INFO, HAMLIB, "Modes absents des plages d'émission déclarées : " + ", ".join(missing),
                "Hamlib ne les annonce pas en émission ; seul un essai sur charge fictive dit s'ils émettent.",
                "Modes missing from every TX range: " + ", ".join(missing),
                key="tx_ranges_data_modes", args={"names": ", ".join(missing)}))
    elif "transmitter" in profile.rig_type.lower():
        found.append(Finding("no_tx_ranges", ATTENTION, HAMLIB, "Aucune plage d'émission déclarée",
                             "Les bandes d'émission de station.toml ne peuvent pas être comparées à Hamlib.",
                             "No TX range declared for a transmitter", key="no_tx_ranges"))
    if profile.caps.complete:
        no_filter = [m for m in profile.modes if m not in profile.caps.filters]
        if no_filter:
            found.append(Finding("modes_without_filters", INFO, HAMLIB, "Modes sans largeur de filtre déclarée : " + ", ".join(no_filter),
                                 "La page ne proposera pas de largeur pour ces modes.",
                                 key="modes_without_filters", args={"names": ", ".join(no_filter)}))
    if can.get("get VFO") is False:
        found.append(Finding("vfo_unreadable", INFO, HAMLIB, "VFO actif illisible (« Can get VFO: N »)",
                             "Le voyant VFO A / B / mémoire ne pourra pas s'afficher.", key="vfo_unreadable"))
    if profile.async_data:
        found.append(Finding("async_data", INFO, TRX, "« Has async data support: Y »",
                             "Ne pas lancer rigctld avec async=1 (réponses décalées vues sous Windows avec Hamlib 4.7.2) : "
                             "TRX Remote ne l'utilise pas.", key="async_data"))
    if profile.get_levels and "STRENGTH" not in profile.get_levels:
        found.append(Finding("no_s_meter", ATTENTION, TRX, "Pas de S-mètre (niveau STRENGTH absent)",
                             "La page n'affichera pas de S-mètre ; RAWSTR éventuel non exploité.", key="no_s_meter"))
    return found


def render_findings(findings: list[Finding], shown: bool = False) -> str:
    """Texte lisible, par gravité : document constats.txt (français) ; `shown` = affichage dans la langue de l'outil
    (option --plan, bilan de l'exploration)."""
    if not findings:
        return _t("findings.none") if shown else "Aucun constat."
    lines = []
    titles = {BLOQUANT: "BLOQUANT", ATTENTION: "À vérifier", INFO: "Pour information"}
    for severity in SEVERITIES:
        items = [f for f in findings if f.severity == severity]
        if items:
            lines.append(_t(f"findings.{severity}") if shown else f"{titles[severity]} :")
            for f in items:
                title, detail = f.shown() if shown else (f.title, f.detail)
                lines.append(f"  - [{f.source}] {title}")
                if detail:
                    lines.append(f"      {detail}")
    return "\n".join(lines)
