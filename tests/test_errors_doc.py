# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Pages publiques du catalogue d'erreurs (scripts/build_errors_doc.py) : à jour, une par code, liens `doc` justes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_errors_doc as doc  # noqa: E402


def test_pages_are_up_to_date_with_the_catalog() -> None:
    stale = doc.stale_pages()
    assert not stale, ("pages des codes périmées (relancer python scripts/build_errors_doc.py) : "
                       + ", ".join(str(p.relative_to(ROOT)) for p in stale[:10]))


def test_every_code_has_its_page_and_points_to_it() -> None:
    data = doc.load_catalog()
    for code, entry in data["codes"].items():
        assert entry["doc"] == f"https://bob56fr.github.io/openRemoteTRX/erreurs/{code}/", code
        assert (doc.SITE / "erreurs" / code / "index.html").is_file(), code


def test_page_content_is_escaped_and_bilingual(tmp_path: Path) -> None:
    data = doc.load_catalog()
    entry = json.loads(json.dumps(data["codes"]["ORT-2104"]))
    entry["titre"] = "<script>alert(1)</script>"
    entry["message"] = "Lecture {cmd} & co"
    page = doc.render_code("ORT-2104", entry, data["codes"])
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "<code>{cmd}</code> &amp; co" in page
    assert 'lang="fr"' in page and 'lang="en"' in page and entry["en"]["titre"] in page


def test_retired_code_links_to_its_replacements_and_a_wrong_doc_stops_the_build() -> None:
    data = doc.load_catalog()
    page = doc.render_code("ORT-9504", data["codes"]["ORT-9504"], data["codes"])
    assert '<a href="../AND-1001/">AND-1001</a>' in page
    broken = json.loads(json.dumps(data))
    broken["codes"]["ORT-1001"]["doc"] = "https://example.invalid/ORT-1001"
    with pytest.raises(doc.DocError, match="ORT-1001"):
        doc.check(broken)
    broken = json.loads(json.dumps(data))
    broken["codes"]["ORT-9504"]["remplace_par"] = "AND-9999"
    with pytest.raises(doc.DocError, match="AND-9999"):
        doc.check(broken)
