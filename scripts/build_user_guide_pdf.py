#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Version PDF du guide de l'opérateur (A4, police réduite, une partie par page), imprimée par Chromium (Playwright)
à partir de la page fabriquée par scripts/build_user_guide.py.

Lancé par la publication GitHub Pages (.github/workflows/pages.yml) : le PDF n'est PAS dans le dépôt (fichier binaire
qui changerait à chaque correction), il est fabriqué juste avant la mise en ligne, à côté de la page.

    python scripts/build_user_guide.py         # d'abord la page
    python scripts/build_user_guide_pdf.py     # puis docs/site/guide/<PDF_NAME>

Exige `pip install playwright` puis `python -m playwright install chromium`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site" / "guide"
PDF_NAME = "guide-openRemoteTRX-{lang}.pdf"      # même nom dans le lien de la page (build_user_guide.py)
LANGS = ("fr", "en", "de", "es")
FOOTER = {"fr": "openRemoteTRX — Guide de l'opérateur", "en": "openRemoteTRX — Operator guide",
          "de": "openRemoteTRX — Bedieneranleitung", "es": "openRemoteTRX — Guía del operador"}

# Ajouté à la page pour l'impression : police de 9,5 pt (environ 20 pages A4), marges serrées, une partie par page,
# liens de navigation et boutons masqués.
PRINT_CSS = """
@media print {
  html, body { font-size: 9.5pt !important; line-height: 1.32 !important; }
  body, main { max-width: none !important; padding: 0 !important; margin: 0 !important; }
  h2 { font-size: 1.55em !important; margin: .2em 0 .4em !important; }
  h3 { font-size: 1.2em !important; margin: .9em 0 .3em !important; }
  p, ul, ol, table, blockquote, pre { margin-top: .35em !important; margin-bottom: .45em !important; }
  li { margin: .1em 0 !important; }
  th, td { padding: .2em .4em !important; }
  pre { font-size: .9em !important; padding: .4em .6em !important; white-space: pre-wrap !important; }
  .schema-svg { max-height: 150mm !important; width: auto !important; display: block; margin: 0 auto; }
  .capture img { max-height: 120mm !important; width: auto !important; }
  .capture { break-inside: avoid; }
  tr, figure, blockquote { break-inside: avoid; }
  h2, h3 { break-after: avoid; }
  .outils, .telecharger, figcaption a { display: none !important; }
}
"""


def page_path(lang: str) -> Path:
    return (SITE if lang == "fr" else SITE / lang) / "index.html"


def pdf_path(lang: str) -> Path:
    return page_path(lang).parent / PDF_NAME.format(lang=lang)


def build_pdf(lang: str) -> int:
    """Écrit le PDF d'une langue ; renvoie son nombre de pages."""
    from playwright.sync_api import sync_playwright
    page_file, out = page_path(lang), pdf_path(lang)
    if not page_file.exists():
        raise FileNotFoundError(f"{page_file} absent : lancer d'abord python scripts/build_user_guide.py")
    footer = ('<div style="font-size:7pt;width:100%;text-align:center;color:#555">'
              f'{FOOTER[lang]} — <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(page_file.as_uri())
            page.add_style_tag(content=PRINT_CSS)
            page.evaluate("document.querySelectorAll('details').forEach(function (d) { d.open = true; })")
            page.emulate_media(media="print")
            page.pdf(path=str(out), format="A4", print_background=False, display_header_footer=True,
                     header_template="<span></span>", footer_template=footer,
                     margin={"top": "12mm", "bottom": "14mm", "left": "11mm", "right": "11mm"})
        finally:
            browser.close()
    return len(re.findall(rb"/Type\s*/Page[^s]", out.read_bytes()))


def main() -> int:
    for lang in LANGS:
        try:
            pages = build_pdf(lang)
        except (ImportError, FileNotFoundError) as exc:
            print(f"Erreur : {exc}", file=sys.stderr)
            return 1
        print(f"Écrit : {pdf_path(lang).relative_to(ROOT).as_posix()} ({pages} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
