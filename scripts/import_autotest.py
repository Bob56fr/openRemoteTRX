# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Prépare la fiche publique d'une PRÉQUALIFICATION à partir d'un rapport JSON de l'openRemoteTRX-Autotest.

Usage : python scripts/import_autotest.py RAPPORT.json [--source projet|utilisateur]

Écrit `docs/postes/autotest/<fabricant>-<modèle>-<AAAAMMJJ-HHMM>.toml` (refuse d'écraser). Ne recopie QUE ce qui peut
être public : modèle, versions, système, résultat et texte de chaque essai, empreinte de la trace. Jamais les noms de
ports ni de cartes son, ni la trace elle-même. Les champs anglais (`resume_en`, `texte_en`) et le résumé restent VIDES :
la fabrication de la page (`scripts/build_rigs_doc.py`) les refuse tant qu'ils ne sont pas écrits à la main.
Une préqualification ne change JAMAIS une fiche de `docs/postes/donnees/` (cahier de la préqualification § 9).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "postes" / "autotest"
SCHEMA = "openremotetrx-autotest/1"
STATUTS = ("ok", "avert", "echec", "na", "saute")


def trace_digest(trace: list) -> str:
    """Même calcul que la page (`JSON.stringify` puis SHA-256)."""
    text = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _q(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)       # chaîne TOML de base (mêmes échappements que JSON)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def convert(report: dict, source: str = "projet") -> tuple[str, str]:
    """(nom du fichier, texte TOML). ValueError si le rapport n'est pas un rapport de l'Autotest."""
    if report.get("schema") != SCHEMA:
        raise ValueError(f"pas un rapport de l'Autotest (schema {report.get('schema')!r})")
    poste, outil = report.get("poste") or {}, report.get("outil") or {}
    hl = poste.get("hamlib") or {}
    model = poste.get("modele_reconnu") or poste.get("modele_choisi")
    if not model:
        raise ValueError("modèle du poste absent du rapport")
    maker = (hl.get("nom") or "").split(" ")[0] if poste.get("marque") in (None, "Hamlib") else poste["marque"]
    maker = maker or "?"
    date = str(report.get("date") or "")
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)", date)
    if not m:
        raise ValueError(f"date illisible {date!r}")
    stamp = f"{m[1]}{m[2]}{m[3]}-{m[4]}{m[5]}"
    trace = report.get("trace") or []
    digest = report.get("empreinte_trace") or ""
    if trace and digest and trace_digest(trace) != digest:
        raise ValueError("empreinte de la trace fausse : rapport modifié après coup ?")
    lines = ["# Préqualification par l'openRemoteTRX-Autotest (scripts/import_autotest.py) : NE VALIDE PAS le poste.",
             "# À compléter à la main : resume, resume_en, texte_en de chaque essai ; note / note_en si un résultat",
             "# est trompeur (défaut connu de l'outil, mesure sans portée).", "",
             "[rapport]",
             f"fabricant = {_q(maker)}",
             f"modele = {_q(model)}"]
    if poste.get("hamlib_model") is not None:
        lines.append(f"hamlib_model = {int(poste['hamlib_model'])}")
    lines += [f"date = {_q(date[:10])}",
              f"heure_utc = {_q(date[11:16])}",
              f"outil = {_q(str(outil.get('version') or '?'))}",
              f"mode = {_q(str(outil.get('mode') or '?'))}"]
    if hl.get("version"):
        lines.append(f"hamlib = {_q(str(hl['version']))}")
    lines += [f"systeme = {_q(str(report.get('systeme') or '?'))}",
              f"source = {_q(source)}"]
    if report.get("arret"):
        lines.append(f"arret = {_q(str(report['arret']))}")
    if digest:
        lines.append(f"empreinte_trace = {_q(digest)}")
    lines += ['resume = ""', 'resume_en = ""']
    for e in report.get("essais") or []:
        status = e.get("statut")
        if status not in STATUTS:
            raise ValueError(f"essai {e.get('code')!r} : statut inconnu {status!r}")
        lines += ["", "[[essais]]", f"code = {_q(str(e.get('code')))}", f"statut = {_q(status)}",
                  f"texte = {_q(str(e.get('texte') or ''))}", 'texte_en = ""']
    return f"{_slug(maker)}-{_slug(model)}-{stamp}.toml", "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rapport", type=Path)
    ap.add_argument("--source", choices=("projet", "utilisateur"), default="projet")
    args = ap.parse_args(argv)
    try:
        name, text = convert(json.loads(args.rapport.read_text(encoding="utf-8")), args.source)
    except (OSError, ValueError) as exc:
        print(f"Rapport refusé : {exc}", file=sys.stderr)
        return 1
    path = OUT / name
    if path.exists():
        print(f"Déjà importé : {path.relative_to(ROOT)}", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    print(f"Écrit : {path.relative_to(ROOT)} (compléter les textes anglais, puis python scripts/build_rigs_doc.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
