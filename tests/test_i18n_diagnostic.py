# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diagnostic de la station en quatre langues (lot L3) : catalogues `trxstation/i18n/diagnostic.<langue>.json`
complets et cohérents, marques reconnues par la page web, langue suivie à l'exécution (`TRX_LANG`)."""
from __future__ import annotations

import ast
import json
import re
import string
from pathlib import Path

import pytest

from test_diagnostics import FakeSystem, healthy, station
from trxstation import diagnostics as d
from trxstation.i18n import FOLDER, LANGS

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "trxstation" / "diagnostics.py"


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((FOLDER / f"diagnostic.{lang}.json").read_text(encoding="utf-8"))


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_the_four_catalogs_have_the_same_keys_and_the_same_fields():
    fr = _catalog("fr")
    for lang in LANGS:
        other = _catalog(lang)
        assert set(other) == set(fr), f"diagnostic.{lang}.json : clés différentes {set(other) ^ set(fr)}"
        for key, text in fr.items():
            assert _fields(other[key]) == _fields(text), f"diagnostic.{lang}.json, {key} : variables différentes"
            assert other[key].strip(), f"diagnostic.{lang}.json, {key} : texte vide"


def test_every_key_used_by_the_diagnostic_exists_in_french():
    fr = _catalog("fr")
    used = set()
    for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_t" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                used.add(arg.value)
    # clés construites (f-string) : rôle des modules, marques, états du Cluster DX, cartes son, son du bureau
    used |= {f"module.role.{module}" for module, _ in d.MODULES}
    used |= {f"label.{status}" for status in d.LABELS}
    used |= {f"cluster.state.{state}" for state in d.CLUSTER_STATES}
    used |= {"name.card_capture", "name.card_playback"}
    used |= {f"audio.desktop_default_{which}" for which in ("out", "in", "both")}
    assert len(used) > 100
    assert not used - set(fr), f"clés absentes de diagnostic.fr.json : {sorted(used - set(fr))}"


# Mêmes motifs que TONES de trxstation/console_web/static/flow.js (couleurs de la page)
TONES = {"warn": r"^\s*(!|\[(ATTENTION|WARNING|WARN|ACHTUNG|AVISO)\])",
         "bad": r"^\s*\[(ERREUR|ERROR|FEHLER|ÉCHEC|FAIL)\]|^\s*(Erreur|Error|Fehler)\b", "ok": r"^\s*\[(OK)\]"}


def test_markers_are_recognised_by_the_web_page_in_every_language():
    flow = (ROOT / "trxstation" / "console_web" / "static" / "flow.js").read_text(encoding="utf-8")
    for word in ("ATTENTION", "WARNING", "ACHTUNG", "AVISO", "ERREUR", "ERROR", "FEHLER"):
        assert word in flow                                       # la page connaît toujours ces marques
    for lang in LANGS:
        cat = _catalog(lang)
        for status, tone in ((d.OK, "ok"), (d.WARN, "warn"), (d.FAIL, "bad")):
            line = "  " + cat["format.line"].format(label=cat[f"label.{status}"], name="x", message="y")
            assert re.search(TONES[tone], line, re.I), (lang, status, line)


def test_french_markers_are_unchanged():
    fr = _catalog("fr")
    assert {s: fr[f"label.{s}"] for s in d.LABELS} == d.LABELS


def _broken_station(tmp_path):
    """Station saine puis beaucoup de pannes : tous les textes du diagnostic, ou presque, sont affichés."""
    sysm, path = healthy(tmp_path)
    sysm.present.discard("/dev/serial/by-id/usb-IC-7300")
    sysm.devices = []
    sysm.modules -= {"aiortc", "textual"}
    sysm.gids = [996]
    sysm.ports = []
    sysm.listening = False
    sysm.commands["/usr/bin/rigctl -l"] = (0, "     1  Hamlib  Dummy  20240101.0  Stable  RIG_MODEL_DUMMY\n")
    sysm.commands["systemctl is-active trx-gateway.service"] = (3, "failed\n")
    sysm.commands["systemctl is-active rigctld.service"] = (3, "inactive\n")
    sysm.commands["systemctl is-active ModemManager"] = (0, "active\n")
    sysm.present.add("/usr/lib/udev/rules.d/85-brltty.rules")
    sysm.files[(tmp_path / "state" / "safe_mode").as_posix()] = "3 restarts"
    sysm.mtimes[str(tmp_path / "status.json")] = 900.0
    return sysm, path


FRENCH = re.compile(r"[àâçéèêëîïôùû]|\b(le|la|les|du|des|est|et|ou|une|pas|dans|pour|avec|puis|carte|poste|"
                    r"aucun|aucune|arrêté|relance|vérifie)\b", re.I)


def test_an_english_diagnostic_has_no_common_french_word(tmp_path, monkeypatch):
    monkeypatch.setenv("TRX_LANG", "en")
    sysm, path = _broken_station(tmp_path)
    checks = d.run_all(sysm, path)
    checks += d.check_network(sysm, d.cfgmod.load(station(tmp_path, network__gateway_bind="0.0.0.0")))
    text = d.format_checks(checks)
    for marker in ("[WARNING]", "[ERROR]", "== Hardware ==", "-> ", "Summary:", "Rig model", "CAT port"):
        assert marker in text, marker
    # Textes venus d'ailleurs, gardés tels quels : avertissements de station.toml (config.py), sécurité de l'accès
    foreign = {(c.section, c.name) for c in checks if c.name in ("Setting", "Access security")}
    lines = [c for c in checks if (c.section, c.name) not in foreign]
    left = [f"{c.name} : {c.message} -> {c.fix}" for c in lines if FRENCH.search(f"{c.name} {c.message} {c.fix}")]
    assert not left, left


@pytest.mark.parametrize("lang", LANGS)
def test_language_is_read_at_each_call(tmp_path, monkeypatch, lang):
    monkeypatch.setenv("TRX_LANG", lang)
    sysm, path = healthy(tmp_path)
    text = d.format_checks(d.run_all(sysm, path))
    assert _catalog(lang)["section.hardware"] in text
    assert _catalog(lang)["format.summary"].split("{")[0].strip() in text


def test_french_output_is_the_reference(tmp_path):
    sysm, path = _broken_station(tmp_path)
    text = d.format_checks(d.run_all(sysm, path))
    assert "[ERREUR] Port CAT : /dev/serial/by-id/usb-IC-7300 absent : poste éteint ou débranché" in text
    assert "Bilan : " in text and "== Matériel ==" in text and "      -> " in text
