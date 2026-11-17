# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""trx-setup en quatre langues (lot L3) : catalogues `trxstation/i18n/setup.<langue>.json` complets et cohérents,
aucun texte en dur dans ce que l'assistant dit ou demande, langue suivie à l'exécution (`TRX_LANG`)."""
from __future__ import annotations

import ast
import json
import re
import string
from pathlib import Path

import pytest

from trxstation import setup_wizard
from trxstation.answers import yes_no
from trxstation.i18n import FOLDER, LANGS

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "trxstation" / "setup_wizard.py", ROOT / "trxstation" / "rig_hints.py"]


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((FOLDER / f"setup.{lang}.json").read_text(encoding="utf-8"))


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_the_four_catalogs_have_the_same_keys_and_the_same_fields():
    fr = _catalog("fr")
    for lang in LANGS:
        other = _catalog(lang)
        assert set(other) == set(fr), f"setup.{lang}.json : clés différentes {set(other) ^ set(fr)}"
        for key, text in fr.items():
            assert _fields(other[key]) == _fields(text), f"setup.{lang}.json, {key} : variables différentes"
            assert other[key].strip(), f"setup.{lang}.json, {key} : texte vide"


def test_yes_no_letters_shown_in_each_language_are_accepted():
    for lang in LANGS:
        cat = _catalog(lang)
        assert yes_no(cat["yesno.yes_letter"]) is True and yes_no(cat["yesno.no_letter"]) is False
        assert yes_no(cat["word.yes"]) is True
        for key in ("yesno.default_yes", "yesno.default_no"):
            yes, no = cat[key].split("/")
            assert yes_no(yes) is True and yes_no(no) is False, (lang, key)


def _used_keys(tree: ast.AST) -> set[str]:
    """Clés passées en constante à `_t(...)` (et les clés choisies par une expression conditionnelle)."""
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_t" and node.args:
            arg = node.args[0]
            candidates = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
            keys |= {c.value for c in candidates if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return keys


def test_every_key_used_by_the_wizard_exists_in_french():
    fr = _catalog("fr")
    missing = set()
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        missing |= {k for k in _used_keys(tree) if k not in fr}
        # clés construites : refuse_keyed("spectrum.when_…") et parts.<partie>
        missing |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and re.fullmatch(r"spectrum\.when_\w+", n.value) and n.value not in fr}
    missing |= {f"parts.{part}" for part in setup_wizard.PARTS if f"parts.{part}" not in fr}
    assert not missing, f"clés absentes de setup.fr.json : {sorted(missing)}"


SHOWN = ("print", "ask", "ask_yes_no", "choose", "ask_number", "SetupError", "say", "SystemExit", "_pick",
         "yes_no_fn", "chooser", "ask_password", "input")


def test_no_text_is_left_hard_coded_in_what_the_wizard_says_or_asks():
    left = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

        def skipped(node, shown) -> bool:
            """Pas du texte affiché : argument d'un autre appel (_t, list_audio_devices, CheckFailed…), valeur
            d'une option de `choose` (premier élément du couple)."""
            child = node
            while child in parents and child is not shown:
                parent = parents[child]
                if isinstance(parent, ast.Call) and parent is not shown:
                    return True
                if isinstance(parent, ast.Tuple) and parent.elts and parent.elts[0] is child:
                    return True
                child = parent
            return False

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SHOWN):
                continue
            args = node.args[:1] if node.func.id in ("ask", "ask_number") else node.args    # ask : défaut = valeur
            for arg in [*args, *(k.value for k in node.keywords if k.arg in ("manual_label",))]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                            and not isinstance(parents.get(sub), ast.JoinedStr):
                        text = sub.value
                    elif isinstance(sub, ast.JoinedStr):
                        text = "".join(v.value for v in sub.values if isinstance(v, ast.Constant))
                    else:
                        continue
                    if not skipped(sub, node) and re.search(r"[A-Za-zÀ-ÿ]{3,}", text):
                        left.append((path.name, sub.lineno, text[:60]))
    assert not left, f"textes en dur (passer par _t) : {left}"


def test_ask_accounts_speaks_english_when_the_console_runs_in_english(monkeypatch, capsys):
    monkeypatch.setenv("TRX_LANG", "en")
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "")
    cfg = setup_wizard.Config()
    setup_wizard.add_client(cfg, "phone")
    setup_wizard.ask_accounts(cfg)
    out = capsys.readouterr().out
    assert "Accounts already allowed (kept): phone" in out and "menu 4.3" in out
    assert prompts == ["Add other accounts besides the existing ones (y/N) [n]: "]


@pytest.mark.parametrize("lang, choice, manual", [("fr", "Choix", "Saisir à la main"), ("en", "Choice", "Type it in"),
                                                  ("de", "Auswahl", "Von Hand eingeben"),
                                                  ("es", "Opción", "Escribirlo a mano")])
def test_choose_follows_the_language_at_run_time(monkeypatch, capsys, lang, choice, manual):
    monkeypatch.setenv("TRX_LANG", lang)
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "2")
    assert setup_wizard.choose("Title", [("a", "A"), ("b", "B")], current="a") == "b"
    out = capsys.readouterr().out
    assert manual in out and _catalog(lang)["choose.current"].format(label="A") in out
    assert prompts[0].startswith(f"{choice} [1]")


def test_the_spectrum_confirmation_word_of_the_language_and_the_french_oui_are_both_accepted(monkeypatch):
    for lang, word in (("en", "yes"), ("de", "ja"), ("es", "sí"), ("en", "OUI"), ("fr", "oui")):
        monkeypatch.setenv("TRX_LANG", lang)
        assert setup_wizard._typed_yes(word), (lang, word)
    monkeypatch.setenv("TRX_LANG", "en")
    assert not setup_wizard._typed_yes("y") and not setup_wizard._typed_yes("JA")
