# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique, depuis trxstation/errors/catalog.yaml et modules.yaml :

- trxstation/errors/codes.py     : une constante par code (ORT_2104 = "ORT-2104"), utilisée par le code de la station ;
- trxstation/errors/catalog.json : copie compacte lue par la station (stdlib seulement, sans PyYAML).

Les catalogues des modules livrés dans ce dossier (registre modules.yaml : AND-catalog.yaml…) y sont ajoutés.

À relancer après TOUTE modification du catalogue : `python scripts/build_errors.py` (PyYAML : extra « dev »).
`--check` : ne rien écrire, sortir en erreur si les fichiers fabriqués ne sont plus à jour (utilisé par les tests).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ERRORS_DIR = Path(__file__).resolve().parents[1] / "trxstation" / "errors"
CATALOG_YAML = ERRORS_DIR / "catalog.yaml"
MODULES_YAML = ERRORS_DIR / "modules.yaml"
CODES_PY = ERRORS_DIR / "codes.py"
CATALOG_JSON = ERRORS_DIR / "catalog.json"


def load_yaml(path: Path) -> dict:
    import yaml   # extra « dev » : jamais importé par la station
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def module_catalogs(modules: dict) -> dict[str, dict]:
    """Catalogues des modules livrés DANS le dépôt (registre : `catalogue` présent dans ce dossier, hors ORT)."""
    out = {}
    for prefix, entry in modules["prefixes"].items():
        name = entry.get("catalogue")
        if prefix != "ORT" and name and (ERRORS_DIR / name).is_file():
            out[prefix] = load_yaml(ERRORS_DIR / name)
    return out


def build_json(catalog: dict, modules: dict) -> str:
    data = {"format": 1, "codes": catalog, "prefixes": modules["prefixes"]}
    return json.dumps(data, ensure_ascii=False, sort_keys=False, separators=(",", ":")) + "\n"


def build_codes(catalog: dict) -> str:
    lines = ["# SPDX-License-Identifier: AGPL-3.0-or-later",
             "# Copyright (C) 2026 RF-DIY.COM",
             '"""Codes du catalogue d\'erreurs : FICHIER FABRIQUÉ par scripts/build_errors.py depuis catalog.yaml.',
             "",
             "Ne pas modifier à la main. Un code n'est jamais réutilisé ni renuméroté (cahier du monitoring, § 7).",
             '"""',
             "from __future__ import annotations",
             ""]
    for code, entry in catalog.items():
        flag = "  [abandonné]" if entry.get("deprecated") else ""
        lines.append(f'{code.replace("-", "_")} = "{code}"   # {entry["gravite"]} : {entry["titre"]}{flag}')
    lines += ["", "ALL: frozenset[str] = frozenset({"]
    names = [c.replace("-", "_") for c in catalog]
    for i in range(0, len(names), 8):
        lines.append("    " + ", ".join(names[i:i + 8]) + ",")
    lines += ["})", ""]
    return "\n".join(lines)


def outputs() -> dict[Path, str]:
    catalog, modules = load_yaml(CATALOG_YAML), load_yaml(MODULES_YAML)
    for extra in module_catalogs(modules).values():   # un seul espace de codes : préfixes différents, jamais en double
        catalog = {**catalog, **extra}
    return {CODES_PY: build_codes(catalog), CATALOG_JSON: build_json(catalog, modules)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="vérifier seulement que les fichiers sont à jour")
    args = parser.parse_args(argv)
    stale = []
    for path, text in outputs().items():
        data = text.encode("utf-8")              # octets : jamais de CRLF ajouté sous Windows
        # Git sous Windows peut rendre le fichier en CRLF : on compare sans les fins de ligne.
        if path.exists() and path.read_bytes().replace(b"\r\n", b"\n") == data:
            continue
        stale.append(path)
        if not args.check:
            path.write_bytes(data)
            print(f"Écrit : {path.relative_to(ERRORS_DIR.parents[1])}")
    if args.check and stale:
        print("Périmés (relancer python scripts/build_errors.py) : " + ", ".join(p.name for p in stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
