# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mode d'emploi de TRX Console (GitHub Pages) : chaque menu expliqué, page publiée à jour, aucune ressource externe,
bloc WordPress qui n'accepte que les messages de GitHub Pages."""
from __future__ import annotations

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
    assert [key for key, _, _ in menus] == [str(n) for n in range(1, len(menus) + 1)]
    content["menus"].pop("temperature")
    with pytest.raises(doc.DocError, match="menu 16"):
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
    for key in range(1, len(doc.console_menus()) + 1):
        assert f'id="menu-{key}"' in page


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
