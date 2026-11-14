# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Guide de l'opérateur (User-Guide/) : page web à jour, liens valides, cases du récapitulatif, contenu public."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "User-Guide"


def _builder():
    spec = importlib.util.spec_from_file_location("build_user_guide", ROOT / "scripts" / "build_user_guide.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_guide_page_is_up_to_date() -> None:
    for path, text in _builder().build().items():
        assert path.exists(), f"{path} absent : lancer python scripts/build_user_guide.py"
        assert path.read_bytes().decode("utf-8") == text, \
            f"{path.relative_to(ROOT)} périmé : lancer python scripts/build_user_guide.py"


def test_every_anchor_of_the_page_exists_and_checkboxes_are_unique() -> None:
    page = _builder().render_page("fr")
    ids = re.findall(r'\sid="([^"]+)"', page)
    assert len(ids) == len(set(ids)), "identifiants en double dans la page"
    for target in re.findall(r'href="#([^"]+)"', page):
        assert target in ids, f"ancre absente : #{target}"
    boxes = re.findall(r'type="checkbox" id="([^"]+)"', page)
    assert len(boxes) >= 30
    assert page.index('id="p-10"') < page.index('type="checkbox"'), "les cases sont dans le récapitulatif"


def test_every_part_and_rig_sheet_is_in_the_page_in_order() -> None:
    builder = _builder()
    files = builder.guide_files("fr")
    names = [p.relative_to(GUIDE / "fr").as_posix() for p in files]
    assert names[0] == "README.md" and names[-1].startswith("10-")
    assert names.index("postes/ftdx10.md") == names.index(next(n for n in names if n.startswith("01-"))) + 1
    page = builder.render_page("fr")
    positions = [page.index(f'id="{builder.anchor_of(p, "fr")}"') for p in files]
    assert positions == sorted(positions)


def test_relative_links_of_the_markdown_point_to_existing_files() -> None:
    for md in GUIDE.rglob("*.md"):
        for target in re.findall(r"\]\(([^)\s]+)\)", md.read_text(encoding="utf-8")):
            if re.match(r"^(https?:|#)", target):
                continue
            assert (md.parent / target.split("#")[0]).exists(), f"{md.relative_to(ROOT)} : lien cassé {target}"


def test_public_guide_has_no_ip_address_nor_private_name() -> None:
    for md in GUIDE.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text), f"{md.name} : adresse IP"
        assert "minix" not in text.lower() and "@" not in text, f"{md.name} : nom de machine ou adresse"


def test_unknown_guide_file_link_is_refused(tmp_path: Path) -> None:
    builder = _builder()
    renderer = builder.Renderer("fr", GUIDE / "fr" / "README.md",
                                {p.resolve(): builder.anchor_of(p, "fr") for p in builder.guide_files("fr")})
    try:
        renderer.inline("[x](99-absent.md)")
    except builder.GuideError:
        return
    raise AssertionError("un lien vers une partie absente doit être refusé")
