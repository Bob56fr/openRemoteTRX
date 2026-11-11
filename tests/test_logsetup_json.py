# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Journal structuré JSON Lines de la passerelle et du superviseur (lot M1 du monitoring, étape 174)."""
from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

import pytest

from trxstation.errors import codes, emit
from trxstation.logsetup import JsonFormatter, add_json_journal


@pytest.fixture
def journal(tmp_path: Path):
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    root.setLevel(logging.DEBUG)
    path = add_json_journal("passerelle", tmp_path)
    yield path
    for h in list(root.handlers):
        if h not in before:
            root.removeHandler(h)
            h.close()
    root.setLevel(level)


def _lines(path: Path) -> list[dict]:
    for h in logging.getLogger().handlers:
        h.flush()
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_warnings_and_catalog_events_go_to_the_journal_plain_info_does_not(journal: Path) -> None:
    log = logging.getLogger("trxstation.essai")
    log.info("information ordinaire")
    log.warning("poste lent : %d ms", 850)
    emit.emit_event(codes.ORT_8012, logger=log)                     # info du catalogue : gardée
    lines = _lines(journal)
    assert [x["message"] for x in lines][0] == "poste lent : 850 ms"
    assert all("information ordinaire" != x["message"] for x in lines)
    event = lines[-1]
    assert event["code"] == "ORT-8012" and event["gravite"] == "info" and event["processus"] == "passerelle"
    assert event["ts"].endswith("Z") and event["niveau"] == "INFO" and event["source"] == "trxstation.essai"


def test_context_and_exceptions_are_kept_and_never_break_the_line(journal: Path) -> None:
    log = logging.getLogger("trxstation.essai")
    emit.emit_event(codes.ORT_1002, logger=log, pct=93, seuil=90, chemin=Path("/var/lib"))
    try:
        raise ValueError("à l'essai")
    except ValueError:
        log.exception("erreur inattendue")
    first, second = _lines(journal)[-2:]
    assert first["contexte"] == {"pct": 93, "seuil": 90, "chemin": str(Path("/var/lib"))}
    assert "93" in first["message"] and second["niveau"] == "ERROR" and "ValueError" in second["exception"]


def test_no_journal_without_state_folder_and_no_duplicate(tmp_path: Path, journal: Path) -> None:
    assert add_json_journal("x", tmp_path / "absent") is None and not (tmp_path / "absent").exists()
    count = sum(isinstance(h, logging.handlers.RotatingFileHandler) for h in logging.getLogger().handlers)
    assert add_json_journal("passerelle", journal.parent) == journal
    assert sum(isinstance(h, logging.handlers.RotatingFileHandler) for h in logging.getLogger().handlers) == count


def test_formatter_survives_odd_messages() -> None:
    record = logging.LogRecord("t", logging.WARNING, __file__, 1, "valeur %s", (object(),), None)
    record.event = {"code": "ORT-0000", "contexte": {"x": object()}}
    line = json.loads(JsonFormatter("superviseur").format(record))
    assert line["code"] == "ORT-0000" and isinstance(line["contexte"]["x"], str)
