# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Contrôles montrés à l'opérateur en quatre langues (lot L3, domaine `checks`) : problèmes et avertissements de
station.toml (`config.py`), refus d'un mot de passe (`passwords.py`), second port CI-V (`spectrum/probe.py`).
Catalogues `trxstation/i18n/checks.<langue>.json` complets et cohérents, langue suivie à l'exécution (`TRX_LANG`)."""
from __future__ import annotations

import ast
import json
import string
from pathlib import Path

from trxstation import config as cfgmod
from trxstation.i18n import FOLDER, LANGS
from trxstation.passwords import MIN_LENGTH, password_problem
from trxstation.spectrum import probe

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "trxstation" / "config.py", ROOT / "trxstation" / "passwords.py",
           ROOT / "trxstation" / "spectrum" / "probe.py"]


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((FOLDER / f"checks.{lang}.json").read_text(encoding="utf-8"))


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_the_four_catalogs_have_the_same_keys_and_the_same_fields():
    fr = _catalog("fr")
    for lang in LANGS:
        other = _catalog(lang)
        assert set(other) == set(fr), f"checks.{lang}.json : clés différentes {set(other) ^ set(fr)}"
        for key, text in fr.items():
            assert _fields(other[key]) == _fields(text), f"checks.{lang}.json, {key} : variables différentes"
            assert other[key].strip(), f"checks.{lang}.json, {key} : texte vide"


def _used_keys(tree: ast.AST) -> set[str]:
    """Clés passées en constante à `_t(...)` ou `t(...)`."""
    return {node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_t", "t")
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}


def test_every_key_used_exists_in_french():
    fr = _catalog("fr")
    missing = set()
    for path in SOURCES:
        missing |= {k for k in _used_keys(ast.parse(path.read_text(encoding="utf-8"))) if k not in fr}
    missing |= {f"probe.{code}" for code in probe.MESSAGES if f"probe.{code}" not in fr}
    assert not missing, f"clés absentes de checks.fr.json : {sorted(missing)}"


def test_french_stays_the_reference_text_of_the_probe():
    fr = _catalog("fr")
    assert fr["probe.usb_send_warning"] == probe.USB_SEND_WARNING and fr["probe.fallback"] == probe.FALLBACK
    assert all(fr[f"probe.{code}"] == text for code, text in probe.MESSAGES.items())
    assert probe.usb_send_warning() == probe.USB_SEND_WARNING


def test_a_validate_problem_in_english(monkeypatch):
    cfg = cfgmod.Config()
    cfg.safety.tot_s = 500
    fr_problems = cfgmod.validate(cfg)
    assert any(p.startswith("Durée maximale d'une émission (TOT) de 500 s refusée") for p in fr_problems)
    monkeypatch.setenv("TRX_LANG", "en")
    problems = cfgmod.validate(cfg)
    assert any(p.startswith("Maximum transmission time (TOT) of 500 s refused") and "[safety] tot_s" in p
               for p in problems)
    assert len(problems) == len(fr_problems)
    assert "No band allowed: transmitting will be IMPOSSIBLE (receive only)." in cfgmod.warnings(cfgmod.Config())


def test_password_problem_in_english(monkeypatch):
    monkeypatch.setenv("TRX_LANG", "en")
    assert password_problem("court") == f"{MIN_LENGTH} characters minimum (a long passphrase is better)"
    assert password_problem("mon-phone-secret", "phone") == "must not contain the login"
    monkeypatch.setenv("TRX_LANG", "de")
    assert password_problem("aaaaaaaaaaaaaaaa") == "zu eintönig (mindestens 5 verschiedene Zeichen)"


def test_usb_send_warning_and_probe_messages_in_english(monkeypatch):
    monkeypatch.setenv("TRX_LANG", "en")
    assert probe.usb_send_warning().startswith("BEFORE OPENING THE SECOND PORT, check on the transceiver")
    assert probe.fallback() == "Normal mode: a single port, no HF waterfall."
    assert probe.CheckFailed("wrong_address", "94h").message("COM7", 0xB6).startswith(
        "The transceiver answers on COM7 at address 94h instead of B6h")
    monkeypatch.setenv("TRX_LANG", "fr")
    assert probe.CheckFailed("no_scope").message("COM7").startswith("Le poste refuse les réglages du spectre sur COM7")
