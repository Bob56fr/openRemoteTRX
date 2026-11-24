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
        expected = text if isinstance(text, bytes) else text.encode("utf-8")
        assert path.read_bytes() == expected, \
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
    assert names[1] == "demarrage-rapide.md", "le démarrage rapide suit l'introduction"
    assert names[-2] == "glossaire.md", "le glossaire se place juste avant le récapitulatif"
    assert names.index("postes/ftdx10.md") == names.index(next(n for n in names if n.startswith("01-"))) + 1
    page = builder.render_page("fr")
    positions = [page.index(f'id="{builder.anchor_of(p, "fr")}"') for p in files]
    assert positions == sorted(positions)


def test_relative_links_of_the_markdown_point_to_existing_files() -> None:
    for md in GUIDE.rglob("*.md"):
        text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8"), flags=re.S)   # exemples de syntaxe
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
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


def test_diagram_is_inlined_and_published_without_script() -> None:
    builder = _builder()
    pages = builder.build()
    page = pages[builder.SITE / "index.html"]
    assert '<figure class="schema"><svg class="schema-svg"' in page
    published = builder.SITE / "images" / "briques.svg"
    assert published in pages and published.exists()
    for svg in GUIDE.rglob("*.svg"):
        text = svg.read_text(encoding="utf-8").lower()
        assert "<script" not in text and "href=\"http" not in text and "<foreignobject" not in text, svg.name


def test_every_glossary_term_used_by_the_diagram_is_defined() -> None:
    glossary = (GUIDE / "fr" / "glossaire.md").read_text(encoding="utf-8")
    for term in ("Passerelle", "Superviseur", "rigctld", "openRemoteTRX Console", "station.toml", "ntfy", "CAT", "WebRTC",
                 "Hamlib", "TOT", "PTT", "Mise en sécurité"):
        assert term in glossary, f"terme absent du glossaire : {term}"


def test_pdf_link_of_the_page_matches_the_file_printed_at_publication() -> None:
    builder = _builder()
    spec = importlib.util.spec_from_file_location("build_user_guide_pdf", ROOT / "scripts" / "build_user_guide_pdf.py")
    pdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pdf)
    assert pdf.PDF_NAME == builder.PDF_NAME and pdf.LANGS == builder.LANGS
    for lang in builder.LANGS:
        page = builder.render_page(lang)
        assert f'href="{builder.PDF_NAME.format(lang=lang)}" target="_blank"' in page
        assert pdf.page_path(lang) in builder.build()
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "python scripts/build_user_guide_pdf.py" in workflow and "playwright install" in workflow
    assert "docs/site/guide/**/*.pdf" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def _png(width: int, height: int, padding: int = 0) -> bytes:
    import struct
    import zlib
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + \
        struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"tEXt", b"x" * padding) + chunk(b"IEND", b""))


def _capture_renderer(tmp_path: Path, monkeypatch):
    builder = _builder()
    monkeypatch.setattr(builder, "GUIDE", tmp_path)
    (tmp_path / "fr").mkdir()
    (tmp_path / "captures").mkdir()
    page = tmp_path / "fr" / "99-essai.md"
    page.write_text("# Essai\n", encoding="utf-8")
    return builder, builder.Renderer("fr", page, {page.resolve(): "p-99"})


def test_screenshot_is_published_beside_the_page_with_its_size(tmp_path: Path, monkeypatch) -> None:
    builder, renderer = _capture_renderer(tmp_path, monkeypatch)
    (tmp_path / "captures" / "page-connexion.png").write_bytes(_png(1080, 2340))
    jpeg = b"\xff\xd8" + b"\xff\xe0\x00\x04xx" + b"\xff\xc0\x00\x11\x08" + (768).to_bytes(2, "big") + \
        (1366).to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    (tmp_path / "captures" / "console.jpg").write_bytes(jpeg)
    html = renderer.render(["![Page de connexion](../captures/page-connexion.png)", "",
                            "![Console](../captures/console.jpg)"])
    assert '<figure class="capture portrait">' in html
    assert 'src="captures/page-connexion.png" alt="Page de connexion" width="1080" height="2340"' in html
    assert 'width="1366" height="768"' in html and '<figure class="capture">' in html
    assert [p.name for p in renderer.images] == ["page-connexion.png", "console.jpg"]
    page = tmp_path / "fr" / "99-essai.md"
    english = builder.Renderer("en", page, {page.resolve(): "p-99"})       # autre langue : page dans guide/en/
    assert 'src="../captures/console.jpg"' in english.render(["![Console](../captures/console.jpg)"])


def test_screenshot_too_heavy_or_not_an_image_is_refused(tmp_path: Path, monkeypatch) -> None:
    builder, renderer = _capture_renderer(tmp_path, monkeypatch)
    (tmp_path / "captures" / "lourde.png").write_bytes(_png(10, 10, builder.CAPTURE_MAX_BYTES))
    (tmp_path / "captures" / "fausse.png").write_bytes(b"pas une image")
    for name in ("lourde", "fausse"):
        try:
            renderer.render([f"![x](../captures/{name}.png)"])
        except builder.GuideError:
            continue
        raise AssertionError(f"{name}.png aurait dû être refusée")


def test_every_screenshot_of_the_guide_is_used_and_light() -> None:
    builder = _builder()
    used = {p.resolve() for p in builder.build() if p.suffix in (".png", ".jpg")}
    for image in list(GUIDE.rglob("*.png")) + list(GUIDE.rglob("*.jpg")):
        assert image.parent == GUIDE / "captures", f"{image.name} : une capture se place dans User-Guide/captures/"
        assert image.stat().st_size <= builder.CAPTURE_MAX_BYTES, f"{image.name} trop lourde"
        published = builder.SITE / "captures" / image.name
        assert published.resolve() in used, f"{image.name} : capture citée par aucune page du guide"


def test_glossary_bubbles_mark_the_first_occurrence_per_section_outside_code_and_links() -> None:
    builder = _builder()
    files = builder.guide_files("fr")
    bubbles = builder.Bubbles("fr", {p.resolve(): builder.anchor_of(p, "fr") for p in files})
    html = bubbles.apply('<h3 id="a">TOT</h3><p>Le TOT coupe, le TOT encore ; <code>TOT</code> '
                         '<a href="#x">TOT</a> une charge fictive, des charges fictives.</p>'
                         '<h3 id="b">B</h3><p>Le TOT, le CATalogue.</p>')
    assert html.count('data-def="def-tot"') == 2, "une fois par section"
    assert "<code>TOT</code>" in html and '<a href="#x">TOT</a>' in html and '<h3 id="a">TOT</h3>' in html
    assert html.count('data-def="def-charge-fictive"') == 1 and "CATalogue" in html and "def-cat" not in html
    footer = bubbles.footer(builder.UI["fr"])
    assert '<div id="defs" hidden data-more="#' in footer and 'id="def-tot" data-terme="TOT"' in footer


def test_published_guide_has_bubbles_but_not_in_the_glossary() -> None:
    builder = _builder()
    page = builder.render_page("fr")
    glossary = page[page.index('id="s-glossaire"'):]
    glossary = glossary[:glossary.index("</section>")]
    assert 'class="terme"' in page and 'class="terme"' not in glossary
    for svg in re.findall(r"<svg.*?</svg>", page, flags=re.S):                  # schéma intégré : jamais de bulle
        assert "<span" not in svg, "bulle posée dans un schéma SVG (le dessin s'arrête là)"
    for ident in set(re.findall(r'data-def="([^"]+)"', page)):
        assert f'<div id="{ident}" data-terme=' in page, f"définition absente : {ident}"


def test_every_language_has_the_same_files_tabs_and_safety_notes_as_the_french_reference() -> None:
    builder = _builder()
    reference = [p.relative_to(GUIDE / "fr").as_posix() for p in builder.guide_files("fr")]
    french = builder.render_page("fr")
    for lang in builder.LANGS:
        names = [p.relative_to(GUIDE / lang).as_posix() for p in builder.guide_files(lang)]
        assert names == reference, f"{lang} : fichiers différents du guide français"
        page = builder.render_page(lang)
        ids = re.findall(r'\sid="([^"]+)"', page)
        assert len(ids) == len(set(ids)), f"{lang} : identifiants en double"
        missing = [t for t in re.findall(r'href="#([^"]+)"', page) if t not in ids]
        assert not missing, f"{lang} : ancres absentes {missing[:3]}"
        for marker in ('class="onglets"', "<details>", 'class="note danger"', 'type="checkbox"'):
            assert page.count(marker) == french.count(marker), f"{lang} : nombre de {marker} différent du français"


def test_tabs_are_named_after_the_systems_and_shared_by_every_language() -> None:
    for md in GUIDE.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        for block in re.findall(r"<!-- onglets -->(.*?)<!-- /onglets -->", text, flags=re.S):
            names = re.findall(r"^#### (.+)$", block, flags=re.M)
            assert names and set(names) <= {"Debian", "Raspberry Pi", "Windows"}, \
                f"{md.relative_to(ROOT)} : onglets {names} (noms de système, jamais traduits)"


def test_tabs_and_accordion_render_and_refuse_broken_blocks() -> None:
    builder = _builder()
    page = GUIDE / "fr" / "02-installer-la-station.md"
    renderer = builder.Renderer("fr", page, {page.resolve(): "p-02"})
    html = renderer.render(["<!-- onglets -->", "#### Debian", "", "texte D", "", "#### Windows", "", "texte W",
                            "<!-- /onglets -->", "", "<details>", "<summary>Plus</summary>", "", "caché", "</details>"])
    assert '<div class="onglets"><div class="onglets-barre" role="tablist"' in html and " hidden>" in html
    assert 'data-os="debian"' in html and 'data-os="windows"' in html
    assert 'id="p-02-o1-debian" aria-labelledby="p-02-o1-debian-b"' in html
    assert "<details><summary>Plus</summary><p>caché</p></details>" in html
    for broken in (["<!-- onglets -->", "#### Debian", "x"],                         # jamais fermé
                   ["<!-- onglets -->", "texte", "#### Debian", "<!-- /onglets -->"],   # texte avant le 1er onglet
                   ["<!-- onglets -->", "#### Debian", "x", "<!-- /onglets -->"],       # un seul onglet
                   ["<details>", "sans titre", "</details>"]):
        try:
            builder.Renderer("fr", page, {page.resolve(): "p-02"}).render(broken)
        except builder.GuideError:
            continue
        raise AssertionError(f"bloc accepté à tort : {broken}")


def test_language_bar_links_every_published_language() -> None:
    builder = _builder()
    french = builder.render_page("fr")
    assert '<strong aria-current="page" lang="fr">Français</strong>' in french
    assert '<a href="en/" lang="en"' in french and '<a href="es/" lang="es"' in french
    german = builder.render_page("de")
    assert '<a href="../" lang="fr"' in german and '<a href="../en/" lang="en"' in german
    pages = builder.build()
    for lang in builder.LANGS:
        assert (builder.SITE if lang == "fr" else builder.SITE / lang) / "index.html" in pages
