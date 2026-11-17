# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""trx-hwtest en quatre langues (lot L3) : catalogues `trxstation/i18n/hwtest.<langue>.json` complets et cohérents,
aucun texte en dur dans ce que l'essai dit ou demande, et SÉCURITÉ : la traduction ne change jamais ce qui confirme
une émission (mot de la langue OU mot français, rien d'autre)."""
from __future__ import annotations

import ast
import json
import re
import string
from pathlib import Path

import pytest

from trxstation.answers import yes_no
from trxstation.devtools import hwtest
from trxstation.i18n import FOLDER, LANGS

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "trxstation" / "devtools" / "hwtest.py"


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((FOLDER / f"hwtest.{lang}.json").read_text(encoding="utf-8"))


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_the_four_catalogs_have_the_same_keys_and_the_same_fields():
    fr = _catalog("fr")
    for lang in LANGS:
        other = _catalog(lang)
        assert set(other) == set(fr), f"hwtest.{lang}.json : clés différentes {set(other) ^ set(fr)}"
        for key, text in fr.items():
            assert _fields(other[key]) == _fields(text), f"hwtest.{lang}.json, {key} : variables différentes"
            assert other[key].strip(), f"hwtest.{lang}.json, {key} : texte vide"


def test_catalog_files_are_written_like_the_others():
    for lang in LANGS:
        raw = (FOLDER / f"hwtest.{lang}.json").read_bytes()
        assert raw.endswith(b"\n") and not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
        data = json.loads(raw.decode("utf-8"))
        assert raw.decode("utf-8") == json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _used_keys(tree: ast.AST) -> set[str]:
    """Clés passées en constante à `_t(...)` (et les clés choisies par une expression conditionnelle)."""
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_t" and node.args:
            arg = node.args[0]
            candidates = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
            keys |= {c.value for c in candidates if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return keys


def test_every_key_used_by_the_rig_test_exists_in_french_and_every_french_key_is_used():
    fr = _catalog("fr")
    used = _used_keys(ast.parse(SOURCE.read_text(encoding="utf-8")))
    assert used, "aucune clé trouvée : l'analyse ne voit plus les appels _t"
    assert not used - set(fr), f"clés absentes de hwtest.fr.json : {sorted(used - set(fr))}"
    # notice.preflight est aussi lue par catalog() (constante PREFLIGHT gardée pour trx-qualif)
    assert not set(fr) - used - {"notice.preflight"}, f"clés inutilisées : {sorted(set(fr) - used)}"


# Appels qui montrent ou demandent un texte, et les arguments affichés (None = tous).
SHOWN = {"say": None, "out": None, "prompt": None, "ask": None, "print": None, "ValueError": None,
         "confirm_emission": None, "record": (0, 2), "_drill": (0,)}


def test_no_text_is_left_hard_coded_in_what_the_rig_test_says_or_asks():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    left = []

    def skipped(node, shown) -> bool:
        """Pas du texte affiché : argument d'un autre appel (_t, render, str…)."""
        child = node
        while child in parents and child is not shown:
            parent = parents[child]
            if isinstance(parent, ast.Call) and parent is not shown:
                return True
            child = parent
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name not in SHOWN:
            continue
        positions = SHOWN[name]
        args = node.args if positions is None else [node.args[i] for i in positions if i < len(node.args)]
        for arg in args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                        and not isinstance(parents.get(sub), ast.JoinedStr):
                    text = sub.value
                elif isinstance(sub, ast.JoinedStr):
                    text = "".join(v.value for v in sub.values if isinstance(v, ast.Constant))
                else:
                    continue
                if not skipped(sub, node) and re.search(r"[A-Za-zÀ-ÿ]{3,}", text):
                    left.append((sub.lineno, text[:60]))
    assert not left, f"textes en dur dans hwtest.py (passer par _t) : {left}"


def test_the_marks_coloured_by_the_page_are_kept_in_every_language():
    for lang in LANGS:
        cat = _catalog(lang)
        assert cat["tag.ok"] == "OK"
        assert cat["report.title"].strip().startswith("=====") and cat["report.title"].strip().endswith("=====")
        assert cat["notice.preflight"].strip().startswith("=====")
        assert cat["teardown.cut_error"].startswith("!!!") and cat["filters.not_restored"].strip().startswith("!!!")
        assert cat["unkey.now"].strip().startswith(">>>") and cat["emit.title"].strip().startswith(">>>")


def test_yes_no_letters_shown_in_each_language_are_accepted_and_defaults_unchanged():
    for lang in LANGS:
        cat = _catalog(lang)
        for key in ("yn.default_yes", "yn.default_no"):
            yes, no = cat[key].strip("[]").split("/")
            assert yes_no(yes) is True and yes_no(no) is False, (lang, key)
        # la lettre en majuscule est le défaut : oui pour [O/n], non pour [o/N]
        assert cat["yn.default_yes"][1].isupper() and cat["yn.default_no"][3].isupper(), lang
        assert yes_no(cat["word.yes"]) is True


@pytest.mark.parametrize("lang, word", [("fr", "EMETTRE"), ("en", "TRANSMIT"), ("de", "SENDEN"), ("es", "TRANSMITIR")])
def test_the_emission_word_of_the_language_and_the_french_word_are_accepted_nothing_else(monkeypatch, lang, word):
    monkeypatch.setenv("TRX_LANG", lang)
    assert hwtest.emit_word() == word
    for good in (word, word.lower(), "EMETTRE", "émettre", f"  {word}  "):
        assert hwtest.typed_emit(good), (lang, good)
    for bad in ("", "o", "y", "oui", "yes", "OUI", "ja", "si", "non", "EMET", word[:-1], f"{word} !", "oui je confirme",
                "TRANSMIT" if lang != "en" else "SENDEN"):
        assert not hwtest.typed_emit(bad), (lang, bad)


@pytest.mark.parametrize("lang, word", [("fr", "OUI"), ("en", "YES"), ("de", "JA"), ("es", "SÍ")])
def test_the_preflight_word_of_the_language_and_the_french_oui_are_accepted_nothing_else(monkeypatch, lang, word):
    monkeypatch.setenv("TRX_LANG", lang)
    for good in (word, word.lower(), "OUI", "oui"):
        assert hwtest.typed_yes(good), (lang, good)
    for bad in ("", "o", "y", "j", "s", "non", "no", "nein", "EMETTRE", "OUI OUI"):
        assert not hwtest.typed_yes(bad), (lang, bad)


def test_emission_prompt_shows_the_word_of_the_language_and_accepts_the_french_word(monkeypatch):
    """De bout en bout sur confirm_emission : anglais affiché, EMETTRE accepté, « yes » refusé."""
    import asyncio
    from trxstation.setup_wizard import dummy_config

    monkeypatch.setenv("TRX_LANG", "en")
    prompts, out = [], []

    def run(answer):
        hw = hwtest.HwTest(dummy_config(), ask=lambda p: prompts.append(p) or answer, out=out.append, tot_s=10.0)
        return asyncio.run(hw.confirm_emission("Step 4"))

    assert run("TRANSMIT") and run("EMETTRE") and not run("yes") and not run("")
    assert prompts[0] == "    To go on, type TRANSMIT (anything else = skip): "
    assert "    Dummy load connected, minimum power, you are near the rig." in out


def test_preflight_is_shown_in_the_language_and_the_french_constant_stays_for_trx_qualif(monkeypatch):
    monkeypatch.setenv("TRX_LANG", "de")
    assert "DUMMY-LOAD" in hwtest.preflight_text()
    assert "CHARGE FICTIVE" in hwtest.PREFLIGHT
    monkeypatch.setenv("TRX_LANG", "fr")
    assert hwtest.preflight_text() == hwtest.PREFLIGHT
