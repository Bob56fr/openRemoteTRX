# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fichiers fabriqués du catalogue d'erreurs (codes.py, catalog.json) et API emit_event."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from trxstation.errors import codes, emit

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh():
    emit._reset_for_tests()
    yield
    emit._reset_for_tests()


def test_generated_files_are_up_to_date() -> None:
    pytest.importorskip("yaml", reason="PyYAML absent (extra « dev ») : fichiers fabriqués non vérifiés")
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_errors.py"), "--check"],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr


def test_constants_match_the_runtime_catalogue() -> None:
    data = json.loads((ROOT / "trxstation" / "errors" / "catalog.json").read_text(encoding="utf-8"))
    assert set(data["codes"]) == codes.ALL
    assert codes.ORT_2104 == "ORT-2104" and codes.ORT_6501 in codes.ALL
    assert {"ORT", "BZA", "FDV"} <= set(data["prefixes"])
    for name in dir(codes):
        if name.startswith("ORT_"):
            assert getattr(codes, name) == name.replace("_", "-")


def test_render_replaces_variables_in_both_languages() -> None:
    titre, message = emit.render(codes.ORT_6502, module="breizh", version_module=1, version_attendue=2)
    assert titre == "Version du module incompatible"
    assert "breizh" in message and "1" in message and "2" in message and "{" not in message
    titre_en, message_en = emit.render(codes.ORT_6502, lang="en", module="breizh", version_module=1, version_attendue=2)
    assert titre_en == "Incompatible module version" and "breizh" in message_en


def test_missing_variable_is_kept_instead_of_raising() -> None:
    _, message = emit.render(codes.ORT_6502, module="breizh")
    assert "{version_module}" in message


def test_emit_logs_at_the_level_of_the_severity_with_the_structured_event(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="trxstation.errors")
    ev = emit.emit_event(codes.ORT_6501, module="breizh", detail="introuvable")
    assert ev.code == "ORT-6501" and ev.gravite == "erreur" and ev.connu
    assert ev.contexte == {"module": "breizh", "detail": "introuvable"} and ev.module == "ORT"
    assert "breizh" in ev.message
    rec = caplog.records[-1]
    assert rec.levelno == logging.ERROR and rec.getMessage().startswith("ORT-6501 ")
    assert rec.event["code"] == "ORT-6501" and rec.event["contexte"]["detail"] == "introuvable"
    levels = {"info": logging.INFO, "avertissement": logging.WARNING, "critique": logging.CRITICAL}
    for gravite, level in levels.items():
        code = next(c for c, e in emit.catalog().items() if e["gravite"] == gravite)
        emit.emit_event(code)
        assert caplog.records[-1].levelno == level


def test_unknown_code_never_raises(caplog) -> None:
    ev = emit.emit_event("ORT-0000", valeur=3)
    assert not ev.connu and ev.gravite == "erreur"
    assert caplog.records[-1].levelno == logging.ERROR


def test_broken_sink_does_not_stop_other_sinks_nor_the_caller() -> None:
    seen = []

    def broken(_ev):
        raise RuntimeError("panne")

    emit.add_sink(broken)
    emit.add_sink(seen.append)
    ev = emit.emit_event(codes.ORT_1001, disques="/", seuil=90)
    assert seen == [ev]
    emit.remove_sink(seen.append)
    emit.emit_event(codes.ORT_1001)
    assert seen == [ev]


def test_missing_runtime_catalogue_keeps_the_station_running(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(emit, "CATALOG_JSON", tmp_path / "absent.json")
    ev = emit.emit_event(codes.ORT_1001)
    assert ev.code == "ORT-1001" and not ev.connu


def test_catalogue_is_read_without_pyyaml() -> None:
    # La station n'a pas PyYAML : emit.py ne doit dépendre que de la stdlib.
    src = (ROOT / "trxstation" / "errors" / "emit.py").read_text(encoding="utf-8")
    assert "import yaml" not in src
