# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglage du Cluster DX en quatre langues (lot L3) : catalogues `trxstation/i18n/cluster.<langue>.json` complets et
cohérents, aucun texte en dur dans ce que l'éditeur (et l'essai autonome) dit ou demande, langue suivie à l'exécution."""
from __future__ import annotations

import ast
import json
import re
import string
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.answers import yes_no
from trxstation.cluster import setup as editor_mod
from trxstation.cluster.bandplan import MODES
from trxstation.i18n import FOLDER, LANGS

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "trxstation" / "cluster" / "setup.py", ROOT / "trxstation" / "cluster" / "cli.py"]


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((FOLDER / f"cluster.{lang}.json").read_text(encoding="utf-8"))


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_the_four_catalogs_have_the_same_keys_and_the_same_fields():
    fr = _catalog("fr")
    for lang in LANGS:
        other = _catalog(lang)
        assert set(other) == set(fr), f"cluster.{lang}.json : clés différentes {set(other) ^ set(fr)}"
        for key, text in fr.items():
            assert _fields(other[key]) == _fields(text), f"cluster.{lang}.json, {key} : variables différentes"
            assert other[key].strip(), f"cluster.{lang}.json, {key} : texte vide"


def test_yes_no_letters_shown_in_each_language_are_accepted():
    for lang in LANGS:
        cat = _catalog(lang)
        for key in ("yesno.default_yes", "yesno.default_no"):
            yes, no = cat[key].split("/")
            assert yes_no(yes) is True and yes_no(no) is False, (lang, key)


def _used_keys(tree: ast.AST) -> set[str]:
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_t" and node.args:
            arg = node.args[0]
            candidates = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
            keys |= {c.value for c in candidates if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return keys


def test_every_key_used_exists_in_french():
    fr = _catalog("fr")
    missing = set()
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        missing |= {k for k in _used_keys(tree) if k not in fr}
    # clés construites : flux.<type>, mode.<mode>, menu.<action>, invites de pick_existing
    missing |= {f"flux.{kind}" for kind, _ in editor_mod.FLUX} - set(fr)
    missing |= {f"mode.{mode}" for mode in MODES} - set(fr)
    missing |= {f"menu.{key}" for _, key, _ in editor_mod.ClusterEditor.ACTIONS} - set(fr)
    tree = ast.parse(SOURCES[0].read_text(encoding="utf-8"))
    missing |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and re.fullmatch(r"pick\.\w+", n.value) and n.value not in fr}
    assert not missing, f"clés absentes de cluster.fr.json : {sorted(missing)}"


SHOWN = ("say", "ask", "yes", "choose", "print", "ask_secret", "input", "getpass", "SystemExit",
         "ArgumentTypeError")


def test_no_text_is_left_hard_coded_in_what_the_editor_says_or_asks():
    left = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

        def skipped(node, shown) -> bool:
            """Pas du texte affiché : argument d'un autre appel (_t, describe…)."""
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
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name not in SHOWN:
                continue
            for arg in node.args:
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


def _editor(answers: list[str], out: list[str]) -> editor_mod.ClusterEditor:
    cfg = cfgmod.Config()
    cfg.cluster.call = "F4XXX"
    cfg.cluster.source = [cfgmod.ClusterSource("on0dxk", "telnet", "on0dxk.example", 7300)]

    def ask(prompt: str) -> str:
        out.append(prompt)
        return answers.pop(0)
    return editor_mod.ClusterEditor(cfg, Path("station.toml"), ask=ask, say=out.append,
                                    write=lambda c, s: None)


def test_the_editor_speaks_english_when_the_console_runs_in_english(monkeypatch):
    monkeypatch.setenv("TRX_LANG", "en")
    out: list[str] = []
    assert _editor(["x", "s", "1", "y", "q", "y"], out).run() == 1
    text = "\n".join(out)
    assert "=== DX cluster: disabled — callsign F4XXX, CB callsign (none) ===" in text
    assert "  a) Add a source" in text and "  w) Save and quit\n  q) Quit without saving" in text
    assert "Unknown choice." in text
    assert "Delete on0dxk (y/N): " in out
    assert "Changes will be lost. Quit (y/N): " in out
    assert "  (no source)" in text                                  # source supprimée
    assert "Choice: " in out


@pytest.mark.parametrize("lang, prompt", [("fr", "Activer le Cluster DX (O/n) : "),
                                          ("de", "DX-Cluster aktivieren (J/n): "),
                                          ("es", "Activar el DX cluster (S/n): ")])
def test_yes_no_prompt_follows_the_language_at_run_time(monkeypatch, lang, prompt):
    monkeypatch.setenv("TRX_LANG", lang)
    out: list[str] = []
    ed = _editor(["", "j" if lang == "de" else ""], out)
    assert ed.yes(editor_mod._t("run.enable"), True) is True
    assert out == [prompt]


def test_menu_letters_are_the_same_in_every_language(monkeypatch):
    letters = {}
    for lang in LANGS:
        monkeypatch.setenv("TRX_LANG", lang)
        out: list[str] = []
        _editor(["q"], out).run()
        letters[lang] = [m.group(1) for line in "\n".join(out).splitlines()
                         if (m := re.match(r"^\s{2}([a-z])\) ", line))]
    assert letters["fr"] == list("famspdricewq")
    assert all(v == letters["fr"] for v in letters.values())
