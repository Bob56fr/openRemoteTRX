# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Étape 215 : 1) lignes INFO des journaux JSON pendant une assistance acceptée (monitoring inter-stations) ;
2) code du catalogue joint aux refus envoyés à la page et à l'application."""
from __future__ import annotations

import json
import logging

from trxstation import logsetup
from trxstation.errors import emit
from trxstation.gateway.api.session import with_error_code
from trxstation.logsetup import ASSIST_FLAG, _JournalFilter


def record(level: int, msg: str = "x", event: dict | None = None) -> logging.LogRecord:
    rec = logging.LogRecord("trx.essai", level, __file__, 1, msg, (), None)
    if event is not None:
        rec.event = event
    return rec


# ------------------------------------------------------------------ 1) lignes INFO pendant l'assistance
def test_journal_filter_lets_info_through_only_during_an_assistance(tmp_path):
    t = {"mono": 0.0, "wall": 1_000_000.0}
    f = _JournalFilter(tmp_path, clock=lambda: t["mono"], wall=lambda: t["wall"])
    assert f.filter(record(logging.WARNING)) and f.filter(record(logging.INFO, event={"code": "ORT-1"}))
    assert not f.filter(record(logging.INFO))                              # ordinaire : pas d'INFO
    flag = tmp_path / ASSIST_FLAG
    flag.parent.mkdir()
    flag.write_text(f"{t['wall'] + 600:.0f}\n", encoding="ascii")
    assert not f.filter(record(logging.INFO))                              # relu toutes les 5 s au plus
    t["mono"] += logsetup.ASSIST_CHECK_S
    assert f.filter(record(logging.INFO))
    assert not f.filter(record(logging.DEBUG))                             # jamais le niveau DEBUG
    t["wall"] += 601
    assert not f.filter(record(logging.INFO))                              # échéance passée
    flag.write_text("abîmé", encoding="utf-8")
    t["mono"] += logsetup.ASSIST_CHECK_S
    t["wall"] -= 601
    assert not f.filter(record(logging.INFO))                              # illisible = filtre ordinaire
    assert not _JournalFilter(None).filter(record(logging.INFO))


def test_info_lines_reach_the_json_journal_during_an_assistance(tmp_path):
    import time
    (tmp_path / ASSIST_FLAG).parent.mkdir()
    (tmp_path / ASSIST_FLAG).write_text(f"{time.time() + 600:.0f}\n", encoding="ascii")
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.INFO)
    path = logsetup.add_json_journal("essai", tmp_path)
    try:
        logging.getLogger("trx.essai").info("ligne d'information pour la station qui aide")
    finally:
        for h in list(root.handlers):
            if getattr(h, "baseFilename", "") == str(path.resolve()):
                root.removeHandler(h)
                h.close()
        root.setLevel(old_level)
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert any(l["niveau"] == "INFO" and "station qui aide" in l["message"] for l in lines)


# ------------------------------------------------------------------ 2) code joint aux refus
def test_refusals_and_errors_carry_their_catalog_code():
    emit._reset_for_tests()
    assert with_error_code({"type": "result", "id": 1, "ok": False, "reason": "out_of_band"})["ort"] == "ORT-5107"
    assert with_error_code({"type": "error", "code": "rate_limited"})["ort"] == "ORT-4013"
    assert with_error_code({"type": "result", "id": 2, "ok": False, "reason": "beeps_unavailable"})["ort"] == "ORT-4014"
    ok = {"type": "result", "id": 3, "ok": True}
    assert with_error_code(ok) is ok                                        # succès : inchangé
    unknown = {"type": "result", "id": 4, "ok": False, "reason": "motif_inconnu"}
    assert with_error_code(unknown) == unknown                              # pas de code connu : inchangé
    assert with_error_code({"type": "state", "reason": "out_of_band"}).get("ort") is None


def test_every_refusal_reason_sent_by_the_station_has_a_code():
    """Tout motif de refus écrit dans la passerelle, les modules et la mesure de TOS trouve son code (directement ou
    par un motif générique comme `*_unavailable`)."""
    import pathlib
    import re
    emit._reset_for_tests()
    root = pathlib.Path(__file__).resolve().parents[1] / "trxstation"
    src = "".join(p.read_text(encoding="utf-8") for d in ("gateway", "swr", "modules") for p in (root / d).rglob("*.py"))
    reasons = set(re.findall(r'reason="([a-z_]+)"', src)) | set(re.findall(r'["\']code["\']\s*:\s*["\']([a-z_]+)["\']', src))
    missing = sorted(r for r in reasons if emit.by_machine(r) is None)
    assert not missing, f"motifs de refus sans code du catalogue : {missing}"
