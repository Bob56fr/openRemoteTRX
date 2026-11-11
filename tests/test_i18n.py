# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Langues de TRX Console (trxstation/i18n/) : catalogues complets et cohérents dans TOUTES les langues, choix de la
langue (fichier par compte, langue du système), réponses oui / non des quatre langues."""
from __future__ import annotations

import json
import re

import pytest

from trxstation import i18n
from trxstation.answers import yes_no
from trxstation.console import MENU_THEMES

FIELD = re.compile(r"\{(\w+(?:![rsa])?(?::[^{}]*)?)\}")      # champ, conversion et format compris ({v:.3f})


def test_every_language_has_exactly_the_keys_and_fields_of_the_french_reference():
    ref = i18n.catalog("fr")
    assert ref, "catalogue français absent"
    for lang in i18n.LANGS:
        cat = i18n.catalog(lang)
        assert list(cat) == list(ref), f"console.{lang}.json : clés différentes du français (ordre compris)"
        for key, text in ref.items():
            assert set(FIELD.findall(cat[key])) == set(FIELD.findall(text)), f"{lang} {key} : champs {{…}} différents"
            assert cat[key].strip() or not text.strip(), f"{lang} {key} : texte vide"
    assert set(i18n.NAMES) == set(i18n.LANGS)


def test_every_menu_and_theme_has_a_label_in_every_language():
    for lang in i18n.LANGS:
        cat = i18n.catalog(lang)
        for _, tid, methods in MENU_THEMES:
            assert cat.get(f"theme.{tid}") and f"theme.{tid}.desc" in cat
            for name in methods:
                assert cat.get(f"menu.{name}"), f"{lang} : menu.{name} sans libellé"
        if lang != "fr":
            assert cat["menu.start"] != i18n.catalog("fr")["menu.start"], f"{lang} : pas traduit"


def test_translator_falls_back_to_french_then_to_the_key_and_never_raises():
    t = i18n.Translator("de")
    assert t("loop.unknown") != i18n.Translator("fr")("loop.unknown")
    assert i18n.Translator("xx").lang == "fr"
    assert t("clé.inexistante") == "clé.inexistante"
    assert i18n.Translator("fr")("head.station_id", id="abc") == "Identifiant de la station : abc"
    assert i18n.Translator("fr")("head.station_id") == "Identifiant de la station : {id}"     # champ manquant : tel quel


@pytest.mark.parametrize("env,expected", [
    ({"LANG": "de_DE.UTF-8"}, "de"), ({"LANGUAGE": "es:fr"}, "es"), ({"LC_ALL": "en_US.UTF-8", "LANG": "fr_FR"}, "en"),
    ({"LANG": "it_IT.UTF-8"}, "fr"), ({"LANG": "C.UTF-8"}, "fr"), ({}, "fr")])
def test_system_language(env, expected):
    assert i18n.system_lang(env) == expected


def test_choice_is_saved_per_account_and_wins_over_the_system(tmp_path):
    path = tmp_path / ".config" / "trx-remote" / "console.json"
    assert i18n.load_lang(path, env={"LANG": "es_ES.UTF-8"}) == "es"
    assert i18n.save_lang(path, "en") and json.loads(path.read_text())["lang"] == "en"
    assert i18n.load_lang(path, env={"LANG": "es_ES.UTF-8"}) == "en"
    assert not i18n.save_lang(path, "xx")
    path.write_text("pas du json")
    assert i18n.load_lang(path, env={}) == "fr"
    assert i18n.prefs_path(tmp_path) == path


@pytest.mark.parametrize("word,value", [("o", True), ("oui", True), ("y", True), ("yes", True), ("j", True), ("Ja", True),
                                        ("s", True), ("sí", True), ("SI", True), ("n", False), ("non", False),
                                        ("no", False), ("nein", False), ("peut-être", None), ("", None)])
def test_yes_no_in_the_four_languages(word, value):
    assert yes_no(word) is value


def test_yes_prompt_letters_match_accepted_answers():
    for lang in i18n.LANGS:
        t = i18n.Translator(lang)
        for key in ("yes.default_yes", "yes.default_no"):
            letters = t(key).split("/")
            assert len(letters) == 2 and yes_no(letters[0]) is True and yes_no(letters[1]) is False, (lang, key)


# ---------------------------------------------------------------- textes de la console (lot L2)
def _console_source() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "trxstation" / "console.py").read_text(encoding="utf-8")


def test_every_key_used_by_the_console_exists_in_the_french_catalogue():
    keys = set(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", _console_source()))
    keys |= set(re.findall(r"""["']((?:friends|breizh)\.(?:level|role|status|code|state)\.\w+)["']""", _console_source()))
    assert len(keys) > 300
    missing = sorted(k for k in keys if k not in i18n.catalog("fr"))
    assert not missing, f"clés absentes de console.fr.json : {missing}"


def test_no_french_text_is_left_hard_coded_in_what_the_console_says_or_asks():
    import ast
    src = _console_source()
    tree = ast.parse(src)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def skipped(node) -> bool:        # clé du catalogue, indice, comparaison, valeur par défaut d'un .get : pas du texte affiché
        p = parents.get(node)
        if isinstance(p, (ast.Subscript, ast.Compare)):
            return True
        return isinstance(p, ast.Call) and isinstance(p.func, (ast.Attribute, ast.Name)) and             (p.func.attr if isinstance(p.func, ast.Attribute) else p.func.id) in ("t", "get", "label")
    left = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("say", "ask", "yes")
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and not isinstance(parents.get(sub), ast.JoinedStr):
                    text = sub.value
                elif isinstance(sub, ast.JoinedStr):
                    text = "".join(v.value for v in sub.values if isinstance(v, ast.Constant))
                else:
                    continue
                if not skipped(sub) and re.search(r"[A-Za-zÀ-ÿ]{3,}", text):     # des mots : passer par self.t(...)
                    left.append((sub.lineno, text[:60]))
    assert not left, f"textes en dur dans console.py : {left}"
