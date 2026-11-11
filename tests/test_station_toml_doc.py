# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Notice des réglages de station.toml (scripts/build_station_toml_doc.py) : chaque réglage du code est expliqué, la
page publiée (site rf-diy.com, par une iframe) et sa version Markdown sont à jour, le contenu reste public."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_station_toml_doc", ROOT / "scripts" / "build_station_toml_doc.py")
doc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doc)


def test_every_setting_of_the_code_is_explained_and_nothing_else():
    content = doc.load_content()
    doc.check(content)
    content["reglages"].pop("safety.tot_s")
    with pytest.raises(doc.DocError, match="safety.tot_s"):
        doc.check(content)
    content = doc.load_content()
    content["reglages"]["safety.fantome"] = {"role": "x", "niveau": "courant"}
    with pytest.raises(doc.DocError, match="safety.fantome"):
        doc.check(content)
    content = doc.load_content()
    content["reglages"]["swr.enabled"]["niveau"] = "débutant"
    with pytest.raises(doc.DocError, match="niveau"):
        doc.check(content)


def test_published_page_and_markdown_are_up_to_date():
    version = doc.base.project_version()
    for path, text in doc.build().items():
        assert path.is_file(), f"{path} absent : lancer python scripts/build_station_toml_doc.py"
        assert path.read_text(encoding="utf-8") == text, f"{path} pas à jour : lancer python scripts/build_station_toml_doc.py"
    assert (doc.SITE / "station-toml" / version / "index.html").is_file()


def test_page_is_public_self_contained_and_reports_its_height():
    page = (doc.SITE / "station-toml" / "index.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>\n<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->")
    assert not re.search(r"<(link|img|iframe)\b|\bsrc\s*=", page, re.I)                # tout est dans la page
    assert set(re.findall(r'href="(https?://[^"]+)"', page)) <= {doc.base.REPO_URL, doc.base.SITE_URL,
                                                                    "https://bob56fr.github.io/openRemoteTRX/erreurs/"}   # liste des codes (même site)
    assert "trx-doc-height" in page
    ips = set(re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", page))
    assert ips <= {"127.0.0.1", "0.0.0.0", "1.1.1.1"}, ips     # aucune adresse réelle ; 1.1.1.1 : cible Internet par défaut de [netprobe]
    for private in ("minix", "bob@", "192.168.", "Bob56fr/openRemoteTRX/blob"):
        assert private not in page.replace(doc.base.REPO_URL, "")
    for section, cls, _ in doc.SECTIONS:
        for key, _ in doc.fields_of(section, cls):
            assert f'id="{doc.base._slug(section + "-" + key)}"' in page


def test_wordpress_block_trusts_only_github_pages():
    block = (ROOT / "docs" / "wordpress" / "station-toml-iframe.html").read_text(encoding="utf-8")
    assert 'event.origin !== "https://bob56fr.github.io"' in block and "event.source !== frame.contentWindow" in block
    assert "allow-same-origin" not in block and "sandbox=" in block
    assert "https://bob56fr.github.io/openRemoteTRX/station-toml/" in block
