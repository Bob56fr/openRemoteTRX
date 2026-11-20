# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fiche Google Play en 4 langues (lot T9 du cahier docs/application-traduction-cahier-des-charges.md).

`docs/play-store/listing/<langue>/` (format « supply » de fastlane, à coller ou à envoyer dans la Play Console) :
`title.txt`, `short_description.txt`, `full_description.txt`, `changelogs/default.txt`. Limites de Google : titre 30,
description courte 80, description complète 4 000, notes de version 500 caractères.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LISTING = ROOT / "docs" / "play-store" / "listing"
LOCALES = ("fr-FR", "en-US", "de-DE", "es-ES")
LIMITS = {"title.txt": 30, "short_description.txt": 80, "full_description.txt": 4000, "changelogs/default.txt": 500}


def read(locale: str, name: str) -> str:
    return (LISTING / locale / name).read_text(encoding="utf-8").strip()


def test_every_language_of_the_app_has_its_store_listing():
    i18n = (ROOT / "trxstation" / "gateway" / "api" / "static" / "i18n.js").read_text(encoding="utf-8")
    offered = re.findall(r'"([a-z]{2})"', re.search(r"const OFFERED = \[([^\]]*)\]", i18n).group(1))
    assert sorted(locale[:2] for locale in LOCALES) == sorted(offered)
    assert sorted(p.name for p in LISTING.iterdir() if p.is_dir()) == sorted(LOCALES)


def test_store_texts_respect_the_limits_of_google_play():
    for locale in LOCALES:
        for name, limit in LIMITS.items():
            text = read(locale, name)
            assert text, (locale, name)
            assert len(text) <= limit, (locale, name, len(text))


def test_full_description_gives_the_sources_and_the_licence_warning():
    for locale in LOCALES:
        text = read(locale, "full_description.txt")
        assert "https://github.com/Bob56fr/openRemoteTRX" in text, locale         # AGPL : lien vers les sources
        assert "AGPL-3.0" in text and "TOT" in text and "STOP" in text, locale
        assert read(locale, "title.txt") == "openRemoteTRX", locale
    assert len({read(locale, "short_description.txt") for locale in LOCALES}) == len(LOCALES)   # vraiment traduites
