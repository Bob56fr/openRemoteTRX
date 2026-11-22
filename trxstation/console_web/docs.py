# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Tuiles « Guides » et « Références » de la console web (étape 349) : documentations publiées sur GitHub Pages,
classées par pertinence, sans numéro de menu. Titres dans la langue de la console (`web.docs.*` des catalogues
console.<langue>.json) ; une documentation pas encore traduite mène à sa version française."""
from __future__ import annotations

from typing import Callable

SITE = "https://bob56fr.github.io/openRemoteTRX/"
ISSUES = "https://github.com/Bob56fr/openRemoteTRX/issues/new/choose"
# Langues publiées : mêmes listes que scripts/build_user_guide.py et scripts/build_console_doc.py (vérifié par les tests).
GUIDE_LANGS = ("fr",)
CONSOLE_LANGS = ("fr", "en", "de", "es")


def _in(langs: tuple[str, ...], lang: str) -> str:
    """Sous-dossier de la langue ("" pour le français, à la racine ; français aussi si la langue n'est pas publiée)."""
    return f"{lang}/" if lang in langs and lang != "fr" else ""


def _guide_lang(lang: str) -> str:
    return lang if lang in GUIDE_LANGS else "fr"


# (clé, pictogramme, couleur, [(clé du lien, adresse selon la langue)]) ; ordre = pertinence.
GROUPS: tuple[tuple[str, str, str, tuple[tuple[str, Callable[[str], str]], ...]], ...] = (
    ("guides", "📚", "#38bdf8", (
        ("console", lambda lg: f"{SITE}console/{_in(CONSOLE_LANGS, lg)}"),
        ("quick", lambda lg: f"{SITE}guide/{_in(GUIDE_LANGS, lg)}#demarrage-rapide"),
        ("guide", lambda lg: f"{SITE}guide/{_in(GUIDE_LANGS, lg)}"),
        ("pdf", lambda lg: f"{SITE}guide/{_in(GUIDE_LANGS, lg)}guide-openRemoteTRX-{_guide_lang(lg)}.pdf"),
    )),
    ("refs", "🔎", "#a3a3a3", (
        ("errors", lambda lg: f"{SITE}erreurs/"),            # la page choisit seule la langue du navigateur
        ("rigs", lambda lg: f"{SITE}postes/"),
        ("toml", lambda lg: f"{SITE}station-toml/"),
        ("autotest", lambda lg: f"{SITE}autotest/"),
        ("github", lambda lg: ISSUES),
    )),
)

KEYS = tuple(f"web.docs.{g}" for g, *_ in GROUPS) + tuple(f"web.docs.{k}" for *_, links in GROUPS for k, _ in links)


def doc_tiles(t: Callable[[str], str], lang: str) -> list[dict]:
    """[{id, title, icon, color, links: [{key, label, url}]}] pour la page."""
    return [{"id": group, "title": t(f"web.docs.{group}"), "icon": icon, "color": color,
             "links": [{"key": key, "label": t(f"web.docs.{key}"), "url": url(lang)} for key, url in links]}
            for group, icon, color, links in GROUPS]
