"""Génère les thèmes de la page à partir de docs/themes.json :

    python scripts/build_themes.py            écrit les teintes dérivées dans docs/themes.json et les blocs de client.css
    python scripts/build_themes.py --check    vérifie seulement (code 1 si un fichier n'est pas à jour ou un thème non conforme)

On n'édite à la main que les 21 rôles de chaque thème dans docs/themes.json. Le thème d'usine (« defaut ») est dans le
bloc :root de client.css avec ses valeurs exactes et n'est jamais régénéré. Un thème non conforme (contraste, couleur
d'émission réservée) n'est pas écrit.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trxstation.layout import palette  # noqa: E402

CSS_FILE = ROOT / "trxstation" / "gateway" / "api" / "static" / "client.css"
BEGIN = "/* THÈMES : généré par scripts/build_themes.py depuis docs/themes.json, ne pas modifier à la main */"
END = "/* FIN DES THÈMES */"


def css_block(themes: dict) -> str:
    lines = [BEGIN]
    for theme_id, theme in themes.items():
        if theme.get("factory"):
            continue
        values = {**theme["colors"], **theme["derived"]}
        body = "; ".join(f"--{k}:{v}" for k, v in values.items())
        lines.append(f':root[data-theme="{theme_id}"] {{ {body}; }}')
    lines.append(END)
    return "\n".join(lines)


def build(doc: dict) -> tuple[dict, list[str]]:
    problems = []
    for theme_id, theme in doc["themes"].items():
        if theme.get("factory"):
            continue
        theme["derived"] = palette.derive(theme["colors"])
        problems += [f"{theme_id} : {p}" for p in palette.check(theme["colors"], theme["derived"])]
    return doc, problems


def with_block(css: str, block: str) -> str:
    if BEGIN in css:
        return re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: block, css, flags=re.S)
    root_end = re.search(r":root\s*\{.*?\n\}\n", css, re.S).end()
    return css[:root_end] + block + "\n" + css[root_end:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build_themes", description="Génère les thèmes de couleurs de la page")
    ap.add_argument("--check", action="store_true", help="vérifie sans rien écrire")
    args = ap.parse_args(argv)
    doc, problems = build(palette.load())
    if problems:
        print("Thèmes non conformes (rien n'est écrit) :\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 1
    new_json = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    css = CSS_FILE.read_text(encoding="utf-8")
    new_css = with_block(css, css_block(doc["themes"]))
    stale = [p.name for p, old, new in ((palette.THEMES_FILE, palette.THEMES_FILE.read_text(encoding="utf-8"), new_json),
                                        (CSS_FILE, css, new_css)) if old != new]
    if args.check:
        if stale:
            print("Pas à jour : " + ", ".join(stale) + " (lance python scripts/build_themes.py)", file=sys.stderr)
            return 1
        print("Thèmes à jour et conformes.")
        return 0
    palette.THEMES_FILE.write_text(new_json, encoding="utf-8", newline="\n")
    CSS_FILE.write_text(new_css, encoding="utf-8", newline="")
    names = [t["name"] for t in doc["themes"].values()]
    print("Thèmes écrits : " + ", ".join(names) + ("" if stale else " (déjà à jour)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
