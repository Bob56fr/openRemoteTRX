# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Rapport d'une exploration (`trx-qualif --explorer`) : dossier `explore-<modèle>-<date>/`.

  exploration.json   tout, pour une machine (sondes, constats, temps de réponse, profil Hamlib)
  constats.txt       constats par gravité, lisibles
  fiche-poste.md     BROUILLON de fiche pour docs/postes/ (à relire : rien n'y est validé en émission)
  rapport-hamlib.md  BROUILLON en anglais des écarts imputables à Hamlib (s'il y en a), pour les développeurs de Hamlib
  dump_caps.txt, cat_trace.log, journal.txt
Contenu sans donnée personnelle : ni indicatif, ni adresse, ni nom de machine (le port série est réduit à son nom).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .coherence import ATTENTION, BLOQUANT, HAMLIB, INFO, SEVERITIES, Finding, render_findings
from .explore import ExplorationResult
from .profile import HamlibProfile

FORMAT = 1
TOOL = "trx-qualif --explorer"


def _version() -> str:
    from .. import __version__
    return __version__


def _ok_names(result: ExplorationResult, kind: str, value: bool | None = True) -> list[str]:
    return [p.target for p in result.probes if p.kind == kind and p.ok is value]


def render_sheet_md(profile: HamlibProfile, result: ExplorationResult, *, date: datetime, firmware: str = "") -> str:
    counts = {s: sum(1 for f in result.findings if f.severity == s) for s in SEVERITIES}
    lines = [
        f"# {profile.name} (modèle Hamlib {profile.model}) — BROUILLON",
        "",
        f"> Brouillon écrit par `{TOOL}` (station {_version()}) le {date:%Y-%m-%d}. Rien n'y est validé en ÉMISSION :",
        "> l'exploration n'émet jamais. Relire, compléter (menus du poste, câblage, débit) et faire la qualification",
        "> complète (`trx-qualif`, sur charge fictive) avant de publier.",
        "",
        "## Identité",
        "",
        f"- Hamlib {profile.hamlib_version or '?'}, backend « {profile.backend_status or '?'} »",
        f"- Firmware du poste : {firmware or 'non relevé'}",
        f"- Type déclaré : {profile.rig_type or '?'} ; PTT déclaré : {profile.ptt_declared or '?'}",
        f"- Modes : {' '.join(profile.modes) or '?'}",
        "",
        "## Ce qui répond (lecture)",
        "",
        f"- Fonctions lues : {', '.join(_ok_names(result, 'read_func')) or 'aucune'}",
        f"- Niveaux lus : {', '.join(_ok_names(result, 'read_level')) or 'aucun'}",
        f"- Paramètres lus : {', '.join(_ok_names(result, 'read_param')) or 'aucun'}",
        "",
        "## Ce qui est refusé alors que Hamlib le déclare",
        "",
    ]
    refused = [f"{p.target} ({p.detail})" for p in result.probes if p.kind.startswith("read_") and p.ok is False]
    lines += [f"- {r}" for r in refused] or ["- rien"]
    lines += ["", "## Écritures essayées (réception seule, remises à leur valeur)", ""]
    writes = [p for p in result.probes if p.kind in ("write_func", "write_level")]
    lines += [f"- {p.target} : {'OK' if p.ok else 'non tenté' if p.ok is None else 'ÉCHEC'} — {p.detail}" for p in writes] or ["- aucune"]
    lines += ["", "## Temps de réponse CAT (ms)", "", "| Commande | n | médiane | 95 % | max |", "| --- | --- | --- | --- | --- |"]
    for name, s in sorted(result.timings.items()):
        lines.append(f"| `{name}` | {s['n']} | {s['mediane']} | {s['p95']} | {s['max']} |")
    lines += ["", f"## Constats ({counts[BLOQUANT]} bloquant(s), {counts[ATTENTION]} à vérifier, {counts[INFO]} pour information)", ""]
    for severity in SEVERITIES:
        for f in (f for f in result.findings if f.severity == severity):
            lines.append(f"- **{severity}** [{f.source}] {f.title}" + (f" — {f.detail}" if f.detail else ""))
    if result.stopped:
        lines += ["", f"**Exploration arrêtée** : {result.stopped}"]
    lines += ["", "## À faire", "", "- [ ] Qualification complète sur charge fictive (`trx-qualif`)",
              "- [ ] Menus du poste à régler (débit CAT, source de modulation USB, TOT du poste)",
              "- [ ] Aides de `rig_hints.py` si une famille de postes en a besoin", ""]
    return "\n".join(lines)


def hamlib_findings(result: ExplorationResult) -> list[Finding]:
    return [f for f in result.findings if f.source == HAMLIB and f.title_en and f.severity in (BLOQUANT, ATTENTION, INFO)]


def render_hamlib_md(profile: HamlibProfile, result: ExplorationResult, *, date: datetime) -> str:
    items = hamlib_findings(result)
    lines = [
        f"# {profile.name} (model {profile.model}): differences between dump_caps and the rig (draft)",
        "",
        f"Found by the receive-only exploration of TRX Remote (openRemoteTRX {_version()}) on {date:%Y-%m-%d}.",
        f"Hamlib {profile.hamlib_version or '?'}, backend status \"{profile.backend_status or '?'}\". Nothing was transmitted.",
        "Before sending: check each item against current Hamlib master, attach `dump_caps.txt` and the relevant part of",
        "`cat_trace.log`, and add a `rigctld -vvvvv` log of a failing command. One subject per message.",
        "",
    ]
    if not items:
        lines.append("No difference attributable to Hamlib was found.")
    for n, f in enumerate(items, 1):
        lines += [f"## {n}. {f.title_en}", ""]
        if f.detail_en:
            lines += [f.detail_en, ""]
    return "\n".join(lines) + "\n"


def write_report(directory: Path, profile: HamlibProfile, result: ExplorationResult, *, dump_text: str = "",
                 journal: list[str] | None = None, proxy=None, firmware: str = "", date: datetime | None = None) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    date = date or datetime.now()
    data = {"outil": TOOL, "version": _version(), "format": FORMAT, "date": date.isoformat(timespec="seconds"),
            "poste": {"modele_hamlib": profile.model, "nom": profile.name, "firmware": firmware},
            "hamlib": profile.to_dict(), **result.to_dict()}
    (directory / "exploration.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "constats.txt").write_text(render_findings(result.findings) + "\n", encoding="utf-8")
    (directory / "fiche-poste.md").write_text(render_sheet_md(profile, result, date=date, firmware=firmware), encoding="utf-8")
    if hamlib_findings(result):
        (directory / "rapport-hamlib.md").write_text(render_hamlib_md(profile, result, date=date), encoding="utf-8")
    if dump_text:
        (directory / "dump_caps.txt").write_text(dump_text, encoding="utf-8")
    if proxy is not None:
        proxy.write(directory / "cat_trace.log")
    if journal is not None:
        (directory / "journal.txt").write_text("\n".join(journal) + "\n", encoding="utf-8")
    return directory
