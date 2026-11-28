# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Champ « Modèle de TRX » des formulaires de tickets : LISTE DÉROULANTE « Nom du poste (Hamlib N) » (étape 409).

Demande de l'utilisateur du 2026-11-28 : un champ libre ne donne pas le bon couple nom / numéro Hamlib. La liste vient de
docs/postes/usb-integre.toml (postes à USB intégré) ; le numéro entre parenthèses pose l'étiquette `poste:N` sur le
ticket (.github/workflows/issue-labels.yml), que chaque station lit pour montrer les tickets de SON poste (menu 7.4).
À relancer après toute modification de usb-integre.toml (tests/test_issue_forms.py refuse des formulaires périmés).
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
RIGS = ROOT / "docs" / "postes" / "usb-integre.toml"

TEXTS = {   # langue : (description bug, description amélioration, autre poste, sans rapport)
    "fr": ("Choisissez votre poste. Absent de la liste : « Autre poste », et précisez marque, modèle et numéro Hamlib "
           "dans la description.",
           "Si l'idée dépend du poste (facultatif).",
           "Autre poste (préciser dans la description)", "Sans rapport avec un poste"),
    "en": ("Choose your transceiver. Not in the list: “Other transceiver”, and give make, model and Hamlib number in "
           "the description.",
           "If the idea depends on the radio (optional).",
           "Other transceiver (give it in the description)", "Not related to a transceiver"),
    "de": ("Wählen Sie Ihr Funkgerät. Nicht in der Liste: „Anderes Funkgerät“, und geben Sie Hersteller, Modell und "
           "Hamlib-Nummer in der Beschreibung an.",
           "Falls die Idee vom Gerät abhängt (optional).",
           "Anderes Funkgerät (in der Beschreibung angeben)", "Unabhängig vom Funkgerät"),
    "es": ("Elija su transceptor. Si no está en la lista: «Otro transceptor», e indique marca, modelo y número Hamlib "
           "en la descripción.",
           "Si la idea depende del equipo (opcional).",
           "Otro transceptor (indicarlo en la descripción)", "Sin relación con un transceptor"),
}
_BLOCK = re.compile(r"  - type: (?:input|dropdown)\n    id: trx\n(?:    .*\n|      .*\n|        .*\n)*")
_LABEL = re.compile(r"^      label: (.*)$", re.M)


def rig_options() -> list[str]:
    data = tomllib.loads(RIGS.read_text(encoding="utf-8"))
    return [f"{r['fabricant']} {r['modele']} (Hamlib {r['hamlib_model']})" for r in data["usb"]]


def form_lang(path: Path) -> str:
    return path.stem.rsplit("-", 1)[1]


def block(path: Path, label: str) -> str:
    lang = form_lang(path)
    bug = "-bug-" in path.name
    desc, idea, other, none = TEXTS[lang]
    options = rig_options() + [other] + ([] if bug else [none])
    lines = ["  - type: dropdown", "    id: trx", "    attributes:", f"      label: {label}",
             f'      description: "{desc if bug else idea}"', "      options:"]
    lines += [f'        - "{o}"' for o in options]
    lines += ["    validations:", f"      required: {'true' if bug else 'false'}"]
    return "\n".join(lines) + "\n"


def render(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = _BLOCK.search(text)
    if match is None:
        raise SystemExit(f"champ « trx » introuvable dans {path.name}")
    label = _LABEL.search(match.group(0)).group(1)
    return text[:match.start()] + block(path, label) + text[match.end():]


def forms() -> list[Path]:
    return sorted(p for p in FORMS.glob("[1-9]-*.yml"))


def main() -> int:
    for path in forms():
        path.write_bytes(render(path).encode("utf-8"))
        print(f"écrit : {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
