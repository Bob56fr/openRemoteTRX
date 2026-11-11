# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mode d'emploi de TRX Console (GitHub Pages) : chaque menu expliqué, page publiée à jour, aucune ressource externe,
bloc WordPress qui n'accepte que les messages de GitHub Pages."""
from __future__ import annotations

import html
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_console_doc", ROOT / "scripts" / "build_console_doc.py")
doc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doc)


def test_every_console_menu_is_explained_and_nothing_else():
    menus, content = doc.console_menus(), doc.load_content()
    doc.check(menus, content)
    from trxstation.console import MENU_THEMES
    assert [m[0] for m in menus] == [f"{t}.{n}" for t, _, ms in MENU_THEMES for n in range(1, len(ms) + 1)]
    content["menus"].pop("temperature")
    with pytest.raises(doc.DocError, match="menu 3.4"):
        doc.check(menus, content)
    content = doc.load_content()
    content["menus"]["fantome"] = {"role": "", "quand": "", "modifie": "", "admin": False}
    with pytest.raises(doc.DocError, match="fantome"):
        doc.check(menus, content)


def test_published_page_is_up_to_date():
    version = doc.project_version()
    for path, text in doc.build().items():
        assert path.is_file(), f"{path} absent : lancer python scripts/build_console_doc.py"
        assert path.read_text(encoding="utf-8") == text, f"{path} pas à jour : lancer python scripts/build_console_doc.py"
    assert (doc.SITE / "console" / version / "index.html").is_file()


def test_page_is_self_contained_and_reports_its_height():
    page = (doc.SITE / "console" / "index.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>\n<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->")
    assert not re.search(r"<(link|img|iframe)\b|\bsrc\s*=", page, re.I)                # tout est dans la page
    urls = set(re.findall(r'href="(https?://[^"]+)"', page))                          # seuls liens sortants permis
    assert urls <= {doc.REPO_URL, doc.SITE_URL}, urls
    assert "trx-doc-height" in page and f"version {doc.project_version()}" in page
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", page)            # aucune adresse IP
    for m in doc.console_menus():
        assert f'id="menu-{m[0].replace(".", "-")}"' in page


def test_every_language_has_the_same_manual_and_its_own_page():
    from trxstation.i18n import LANGS
    assert doc.LANGS == LANGS
    contents = doc.load_all()
    doc.check_all(contents)
    for lang in LANGS:
        sub = "" if lang == "fr" else lang + "/"
        page = (doc.SITE / "console" / sub / "index.html").read_text(encoding="utf-8")
        assert f'<html lang="{lang}">' in page and html.escape(contents[lang]["page"]["titre"]) in page
        for other in LANGS:
            if other != lang:
                assert f'hreflang="{other}"' in page                      # lien vers chaque autre langue
        assert (doc.SITE / "console" / doc.project_version() / sub / "index.html").is_file()
    broken = {lang: dict(c) for lang, c in contents.items()}
    broken["es"] = dict(broken["es"], parcours=broken["es"]["parcours"][:-1])
    with pytest.raises(doc.DocError, match="parcours"):
        doc.check_all(broken)
    broken = doc.load_all()
    broken["de"]["menus"]["start"]["admin"] = not broken["de"]["menus"]["start"]["admin"]
    with pytest.raises(doc.DocError, match="admin"):
        doc.check_all(broken)


def test_wordpress_block_trusts_only_github_pages():
    block = (ROOT / "docs" / "wordpress" / "console-iframe.html").read_text(encoding="utf-8")
    assert 'event.origin !== "https://bob56fr.github.io"' in block and "event.source !== frame.contentWindow" in block
    assert "allow-same-origin" not in block and "sandbox=" in block
    assert "https://bob56fr.github.io/openRemoteTRX/console/" in block


def test_pages_workflow_publishes_the_site_folder():
    path = ROOT / ".github" / "workflows" / "pages.yml"
    if not path.is_file():
        pytest.skip("dépôt seulement (absent du paquet Debian)")
    workflow = path.read_text(encoding="utf-8")
    assert "path: docs/site" in workflow and "actions/deploy-pages" in workflow


def test_help_text_for_the_terminal_is_plain_and_wrapped():
    text = doc.html_to_text("<p>Un <strong>essai</strong> &amp; <code>trx-setup</code>.</p><ul><li>premier</li><li>second</li></ul>", width=30)
    assert text == "Un essai & trx-setup.\n\n- premier\n- second"
    long = doc.html_to_text("<p>" + "mot " * 40 + "</p>", width=30)
    assert all(len(line) <= 30 for line in long.splitlines())
