# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Textes de la page web (lot T4 du cahier docs/application-traduction-cahier-des-charges.md).

Catalogues `trxstation/i18n/page.<langue>.json` (textes propres à la page) et `shared.<langue>.json` (textes communs à
la page et à l'application, même clé des deux côtés) ; CLIQUET : aucun texte humain écrit en dur dans les scripts de
la page ni dans index.html (hors marque `i18n-ok` sur la ligne) ; toute clé écrite existe ; le texte français gardé
dans index.html est celui du catalogue.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "trxstation" / "i18n"
STATIC = ROOT / "trxstation" / "gateway" / "api" / "static"
APP = ROOT / "android" / "logic" / "src" / "main" / "resources" / "i18n" / "app.fr.json"
LANGS = ("fr", "en", "de", "es")
KEY = re.compile(r"^[a-z0-9]+(\.[a-z0-9_]+)+$")
FIELD = re.compile(r"\{([a-z_]+)\}")

ACCENT = re.compile(r"[àâäçéèêëîïôöùûüÿœÀÂÇÉÈÊËÎÏÔÖÙÛÜŒ«»…’]")
CAPITALIZED = re.compile(r"^[A-ZÀ-Ý][a-zà-ÿ]{2,}$")
WORDS = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
TEMPLATE = re.compile(r"\$\{[^}]*\}")
JS_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"' + r"|'((?:[^'\\\n]|\\.)*)'" + r"|`((?:[^`\\]|\\.)*)`")
JS_CALL = re.compile(r"""I18N\.(?:t|has|plural)\(\s*"([a-z0-9_.]+)"\s*[,)]""")
ATTRS = ("title", "placeholder", "aria-label", "alt")


def load(name: str) -> dict[str, str]:
    path = FOLDER / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def is_human(text: str) -> bool:
    """Même règle que le cliquet de l'application (I18nAppTest.isHuman)."""
    plain = TEMPLATE.sub(" ", text)
    if not any(len(w) >= 3 for w in WORDS.findall(plain)):
        return False
    if ACCENT.search(plain) or CAPITALIZED.match(plain.strip()):
        return True
    return len(WORDS.findall(plain)) >= 2 and " " in plain.strip()


def known_keys() -> set[str]:
    return {*load("client.fr.json"), *load("shared.fr.json"), *load("page.fr.json")}


def test_page_and_shared_catalogues_are_well_formed_and_consistent_between_languages():
    client = load("client.fr.json")
    app = json.loads(APP.read_text(encoding="utf-8"))
    seen: dict[str, str] = {}
    for domain in ("shared", "page"):
        fr = load(f"{domain}.fr.json")
        assert (FOLDER / f"{domain}.fr.json").is_file()
        for key, text in fr.items():
            assert KEY.match(key), (domain, key)
            assert isinstance(text, str) and text.strip(), (domain, key)
            assert not re.search(r"\{[^a-z_}]", text), (domain, key, text)
            assert key not in client and key not in seen, (domain, key)       # une clé n'existe qu'à un endroit
            seen[key] = domain
        for lang in LANGS[1:]:
            if not (FOLDER / f"{domain}.{lang}.json").is_file():
                continue                                                      # langue pas encore traduite (T5, T6)
            other = load(f"{domain}.{lang}.json")
            assert list(other) == list(fr), (domain, lang)
            for key, text in fr.items():
                assert set(FIELD.findall(other[key])) == set(FIELD.findall(text)), (domain, lang, key)
    assert not set(load("shared.fr.json")) & set(app), "texte partagé encore dans app.fr.json"
    assert not set(load("page.fr.json")) & set(app), "clé de la page déjà prise par l'application"


def test_every_key_written_in_the_page_scripts_exists_in_french():
    known = known_keys()
    missing = []
    for path in sorted(STATIC.glob("*.js")):
        for key in JS_CALL.findall(path.read_text(encoding="utf-8")):
            if key not in known and f"{key}_one" not in known:
                missing.append(f"{path.name} : {key}")
    assert missing == []


def human_strings_js(path: Path) -> list[str]:
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "/*")) or "i18n-ok" in line:
            continue
        for match in JS_STRING.finditer(line):
            text = next(g for g in match.groups() if g is not None)
            if is_human(text):
                found.append(f"{path.name}:{number} : {text!r}")
    return found


def test_ratchet_no_human_text_written_in_the_page_scripts():
    found = [item for path in sorted(STATIC.glob("*.js")) for item in human_strings_js(path)]
    assert found == [], "textes à passer par I18N.t (ou marque i18n-ok)"


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Page(HTMLParser):
    """Relève les textes d'index.html : marqués (data-t…) ou en dur."""

    def __init__(self, lines: list[str]):
        super().__init__(convert_charrefs=True)
        self.lines = lines
        self.stack: list[tuple[str, str | None]] = []           # (balise, clé data-t)
        self.marked: list[tuple[int, str, str]] = []            # (ligne, clé, texte)
        self.bare: list[str] = []
        self.children_of_marked: list[str] = []
        self.texts: dict[str, list[str]] = {}

    def _ok(self) -> bool:
        line = self.getpos()[0]
        return "i18n-ok" in self.lines[line - 1]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        if self.stack and self.stack[-1][1]:
            self.children_of_marked.append(f"ligne {line} : <{tag}> dans data-t={self.stack[-1][1]}")
        for attr in ATTRS + ("label",):
            value = a.get(attr)
            if value is None:
                continue
            key = a.get(f"data-t-{attr}")
            if key:
                self.marked.append((line, key, value))
            elif is_human(value) and not self._ok():
                self.bare.append(f"ligne {line} : {attr}={value!r}")
        if tag not in VOID:
            self.stack.append((tag, a.get("data-t")))
            if a.get("data-t"):
                self.texts[f"{line}:{a['data-t']}"] = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack:
            self.stack.pop()

    def handle_endtag(self, tag):
        while self.stack:
            name, key = self.stack.pop()
            if key:
                pending = [k for k in self.texts if k.endswith(":" + key)]
                if pending:
                    where = pending[-1]
                    text = " ".join("".join(self.texts.pop(where)).split())
                    self.marked.append((int(where.split(":")[0]), key, text))
            if name == tag:
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            key = self.stack[-1][1]
            where = [k for k in self.texts if k.endswith(":" + key)][-1]
            self.texts[where].append(data)
            return
        if self.stack and self.stack[-1][0] in ("script", "style"):
            return
        text = " ".join(data.split())
        if text and is_human(text) and not self._ok():
            self.bare.append(f"ligne {self.getpos()[0]} : {text!r}")


def parse_page() -> _Page:
    source = (STATIC / "index.html").read_text(encoding="utf-8")
    page = _Page(source.splitlines())
    page.feed(source)
    return page


def test_ratchet_no_human_text_written_in_index_html():
    page = parse_page()
    assert page.bare == [], "texte d'index.html sans data-t (ou marque i18n-ok)"


def test_marked_texts_of_index_html_are_the_french_catalogue_and_have_no_child_element():
    page = parse_page()
    catalogue = {**load("client.fr.json"), **load("shared.fr.json"), **load("page.fr.json")}
    assert page.children_of_marked == [], "un élément data-t ne contient que du texte (apply le remplace)"
    wrong = [f"ligne {line} : {key}" for line, key, text in page.marked
             if " ".join(catalogue.get(key, "\0").split()) != text]
    assert wrong == [], "texte d'index.html différent du catalogue français (ou clé absente)"


TOP_TABLE = re.compile(r"^  (?:const|let|var) [A-Za-z_$][\w$]* = (?![^=]*=>)(?!function)")


def texts_read_at_load(path: Path) -> list[str]:
    """`I18N.t(…)` dans une déclaration du corps principal du script (hors fonction) : lu AVANT le chargement des
    catalogues dans le navigateur (la clé s'afficherait). Une table se relit à l'affichage (fonction ou getter)."""
    found, inside = [], False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if TOP_TABLE.match(line):
            inside = True
        if inside and re.search(r"I18N\.(?:t|plural)\(", line) and "get " not in line and "=>" not in line \
                and "function" not in line:
            found.append(f"{path.name}:{number}")
        if inside and (line.rstrip().endswith(";") and line.startswith("  ") and not line.startswith("   ")
                       or re.match(r"^  [}\]]", line)):
            inside = False
    return found


def test_no_text_is_read_when_a_page_script_loads():
    found = [item for path in sorted(STATIC.glob("*.js")) for item in texts_read_at_load(path)]
    assert found == [], "table de textes calculée au chargement : la relire à l'affichage (fonction, getter)"


def test_offered_languages_have_complete_catalogues_and_real_translations():
    """Une langue PROPOSÉE par la page (OFFERED d'i18n.js) a ses trois catalogues ; un texte humain n'y est jamais
    laissé en français (abréviations, noms propres, unités : permis, ils ne sont pas « humains » pour le cliquet)."""
    script = (STATIC / "i18n.js").read_text(encoding="utf-8")
    offered = re.findall(r'"([a-z]{2})"', re.search(r"const OFFERED = \[([^\]]*)\]", script).group(1))
    assert offered[0] == "fr"
    identical = json.loads((FOLDER / "identical.json").read_text(encoding="utf-8"))
    for lang in offered[1:]:
        allowed = set(identical.get(lang, []))
        for domain in ("client", "shared", "page"):
            fr, other = load(f"{domain}.fr.json"), load(f"{domain}.{lang}.json")
            assert list(other) == list(fr), (domain, lang)
            same = [k for k, v in fr.items() if other[k] == v and is_human(v) and v not in allowed]
            assert same == [], (domain, lang, same)
