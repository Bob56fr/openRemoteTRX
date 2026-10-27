# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Thèmes de couleurs : toutes les couleurs de la page en variables, cohérentes avec docs/themes.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "trxstation" / "gateway" / "api" / "static"
THEMES = json.loads((ROOT / "docs" / "themes.json").read_text(encoding="utf-8"))
CSS = (STATIC / "client.css").read_text(encoding="utf-8")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)")


def norm(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip().lower())
    return re.sub(r"\s*([(),])\s*", r"\1", value)


def root_block() -> tuple[str, str]:
    match = re.search(r":root\s*\{(.*?)\n\}", CSS, re.S)
    assert match, "bloc :root introuvable"
    return match.group(1), CSS[match.end():]


def css_variables() -> dict[str, str]:
    block = re.sub(r"/\*.*?\*/", "", root_block()[0], flags=re.S)
    return {name[2:]: value.strip() for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block)}


def generated_block() -> str:
    from scripts_build_themes import BEGIN, END
    return CSS[CSS.index(BEGIN):CSS.index(END) + len(END)]


def test_no_hardcoded_color_outside_the_variables():
    rest = root_block()[1].replace(generated_block(), "")
    rest = re.sub(r"/\*.*?\*/", "", rest, flags=re.S)
    assert COLOR_RE.findall(rest) == []


def test_old_variable_names_are_gone():
    assert not re.search(r"var\(--(bg|panel|line|text|dim|blue2?|red|amber|green)\)", CSS)


def test_every_variable_used_is_defined():
    defined = set(css_variables())
    used = set(re.findall(r"var\(--([a-z0-9-]+)\)", CSS))
    assert used <= defined, sorted(used - defined)


def test_default_theme_matches_the_reference_file_exactly():
    default = THEMES["themes"]["defaut"]
    expected = {**default["colors"], **default["derived"]}
    assert css_variables() == expected
    assert default["factory"] is True


def test_reference_file_structure():
    roles, derived = THEMES["roles"], THEMES["derived"]
    assert len(roles) == 21 and len(set(roles)) == 21 and not set(roles) & set(derived)
    for key in ("fond", "texte", "frequence", "accent", "tx", "alerte", "succes", "favori", "smetre-bas", "smetre-haut"):
        assert key in roles
    for theme_id, theme in THEMES["themes"].items():
        assert set(theme["colors"]) == set(roles), f"{theme_id} : rôles manquants ou en trop"
        for value in theme["colors"].values():
            assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{theme_id} : {value} n'est pas #rrggbb"


def test_javascript_fallbacks_are_the_default_theme():
    default = {**THEMES["themes"]["defaut"]["colors"], **THEMES["themes"]["defaut"]["derived"]}
    ui = (STATIC / "ui.js").read_text(encoding="utf-8")
    block = re.search(r"const CANVAS_DEFAULTS = \{(.*?)\};", ui, re.S).group(1)
    fallbacks = dict(re.findall(r'"--([a-z0-9-]+)": "([^"]+)"', block))
    assert fallbacks and all(norm(v) == norm(default[k]) for k, v in fallbacks.items()), fallbacks
    outside = COLOR_RE.findall(ui.replace(block, ""))
    assert outside == [], f"couleurs codées en dur dans ui.js : {outside}"
    wf = (STATIC / "waterfall.js").read_text(encoding="utf-8")
    gradient = re.search(r"const DEFAULT_GRADIENT = \[(.*?)\];", wf).group(1)
    assert re.findall(r'"(#[0-9a-f]{6})"', gradient) == default["waterfall-degrade"].split()


# ------------------------------------------------------------------ chartes générées (scripts/build_themes.py)

import importlib.util  # noqa: E402
import sys  # noqa: E402

_spec = importlib.util.spec_from_file_location("scripts_build_themes", ROOT / "scripts" / "build_themes.py")
_builder = importlib.util.module_from_spec(_spec)
sys.modules["scripts_build_themes"] = _builder
_spec.loader.exec_module(_builder)

from trxstation.layout import palette  # noqa: E402

BRANDS = ("icom", "yaesu", "kenwood")


def test_brand_themes_exist_and_are_dark_only():
    for theme_id in BRANDS:
        theme = THEMES["themes"][theme_id]
        assert theme["name"] == "Style " + theme_id.capitalize() and not theme.get("factory")
        assert palette.contrast(theme["colors"]["texte"], theme["colors"]["fond"]) > 7          # fond sombre, texte clair


def test_generated_files_are_up_to_date():
    assert _builder.main(["--check"]) == 0


def test_brand_themes_pass_contrast_and_reserved_emission_color():
    for theme_id in BRANDS:
        theme = THEMES["themes"][theme_id]
        assert palette.check(theme["colors"], theme["derived"]) == [], theme_id
        assert theme["derived"] == palette.derive(theme["colors"])


def test_every_variable_of_the_default_theme_exists_in_every_theme():
    default = set(THEMES["themes"]["defaut"]["colors"]) | set(THEMES["themes"]["defaut"]["derived"])
    for theme_id in BRANDS:
        theme = THEMES["themes"][theme_id]
        assert set(theme["colors"]) | set(theme["derived"]) == default, theme_id
        block = re.search(r':root\[data-theme="%s"\] \{(.*?)\}' % theme_id, CSS).group(1)
        assert set(re.findall(r"--([a-z0-9-]+):", block)) == default
        assert palette.parse_gradient(theme["derived"]["waterfall-degrade"]) is not None


def test_checker_refuses_a_bad_theme():
    colors = dict(THEMES["themes"]["icom"]["colors"])
    colors["smetre-haut"] = colors["tx"]                                                         # couleur d'émission réutilisée
    colors["texte"] = colors["fond-panneau"]                                                     # texte invisible
    problems = palette.check(colors, palette.derive(colors))
    assert any("réservée" in p and "smetre-haut" in p for p in problems)
    assert any(p.startswith("contraste texte sur fond") for p in problems)
    assert palette.check({"fond": "rouge"}, {}) != []


def test_generator_refuses_to_write_a_non_compliant_theme(tmp_path, monkeypatch, capsys):
    doc = json.loads(json.dumps(THEMES))
    doc["themes"]["yaesu"]["colors"]["smetre-haut"] = doc["themes"]["yaesu"]["colors"]["tx"]
    path = tmp_path / "themes.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    css = tmp_path / "client.css"
    css.write_text(CSS, encoding="utf-8")
    monkeypatch.setattr(palette, "THEMES_FILE", path)
    monkeypatch.setattr(_builder, "CSS_FILE", css)
    assert _builder.main([]) == 1
    assert "yaesu" in capsys.readouterr().err and css.read_text(encoding="utf-8") == CSS


# ------------------------------------------------------------------ sélecteur et application du thème

import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_selector_offers_exactly_the_themes_of_the_reference_file():
    select = re.search(r'<select id="theme-select">(.*?)</select>', HTML, re.S).group(1)
    options = re.findall(r'<option value="([^"]+)">([^<]+)</option>', select)
    assert options == [(k, t["name"]) for k, t in THEMES["themes"].items()]
    assert options[0][0] == "defaut"


def test_theme_is_applied_before_the_stylesheet_and_served_by_the_station():
    head = HTML.split("</head>")[0]
    assert head.index('<script src="theme.js"></script>') < head.index('href="client.css"')
    server = (ROOT / "trxstation" / "gateway" / "api" / "server.py").read_text(encoding="utf-8")
    assert '"/theme.js": ("theme.js", "text/javascript")' in server
    assert "<script>" not in HTML                                                      # aucun script en ligne (CSP)


def test_theme_logic_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js absent")
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "theme_test.js")], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
