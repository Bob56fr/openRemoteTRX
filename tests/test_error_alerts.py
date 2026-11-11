# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Alertes ntfy par les codes du catalogue d'erreurs (lot M1, partie 2b, étape 173).

Titre « ORT-NNNN titre », priorité, marche à suivre et lien de la page du code pris dans le catalogue ;
`ntfy_defaut: false` = journal seulement ; aucun appel d'alerte avec un titre en texte libre dans le code.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from trxstation.errors import codes, emit
from trxstation.supervisor import core
from trxstation.supervisor.notify import Notifier, ascii_title

ROOT = Path(__file__).resolve().parents[1] / "trxstation"
ALERT_CALLS = {"alert", "_alert", "_alert_now"}


def _notifier(sent: list) -> Notifier:
    return Notifier("https://ntfy.sh/x", post=lambda *a: sent.append(a), threaded=False)


def test_alert_takes_title_priority_advice_and_page_from_the_catalog() -> None:
    sent: list = []
    assert _notifier(sent).alert(codes.ORT_5024, "émission de 136 s coupée") is True
    url, title, body, priority = sent[0]
    e = emit.entry(codes.ORT_5024)
    assert title == f"ORT-5024 {e['titre']}" and priority == "5"
    assert body.startswith("émission de 136 s coupée") and e["preconisation"] in body
    assert "https://bob56fr.github.io/openRemoteTRX/erreurs/ORT-5024/" in body


def test_alert_without_detail_uses_the_catalog_message() -> None:
    sent: list = []
    _notifier(sent).alert(codes.ORT_1002, pct=93, seuil=90)
    assert "93" in sent[0][2] and "{pct}" not in sent[0][2]


def test_code_without_ntfy_by_default_is_only_logged(caplog: pytest.LogCaptureFixture) -> None:
    sent: list = []
    code = next(c for c, e in emit.catalog().items() if not e["ntfy_defaut"] and e["gravite"] == "erreur")
    with caplog.at_level(logging.INFO):
        assert _notifier(sent).alert(code, "détail") is False
    assert sent == [] and any(code in r.getMessage() and r.levelno == logging.ERROR for r in caplog.records)
    assert any(getattr(r, "event", {}).get("code") == code for r in caplog.records)


def test_unknown_code_is_still_sent_in_doubt() -> None:
    sent: list = []
    assert _notifier(sent).alert("ORT-0000", "quelque chose") is True
    assert sent[0][1].startswith("ORT-0000")


def test_rate_limit_is_per_code_and_key() -> None:
    sent: list = []
    now = [0.0]
    n = Notifier("https://ntfy.sh/x", post=lambda *a: sent.append(a), clock=lambda: now[0], threaded=False)
    assert n.alert(codes.ORT_8001, "a", key="restart_gateway")
    assert n.alert(codes.ORT_8001, "b", key="restart_rigctld")      # deux niveaux de reprise : deux alertes
    assert not n.alert(codes.ORT_8001, "c", key="restart_gateway")  # même sujet dans la minute : une seule
    now[0] = 61.0
    assert n.alert(codes.ORT_8001, "d", key="restart_gateway")


def test_alert_never_raises() -> None:
    def boom(*a):
        raise OSError("réseau")
    assert Notifier("https://ntfy.sh/x", post=boom, threaded=False).alert(codes.ORT_8008, "x") is True


def test_ascii_title_keeps_letters() -> None:
    assert ascii_title("ORT-8008 Mode sûr : émission coupée") == "ORT-8008 Mode sur : emission coupee"


def test_every_supervisor_problem_and_recovery_level_has_a_code() -> None:
    names = set()
    for node in ast.walk(ast.parse((ROOT / "supervisor" / "core.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Problem" and node.args \
                and isinstance(node.args[0], ast.Constant):
            names.add(node.args[0].value)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Problem" and node.args \
                and isinstance(node.args[0], ast.IfExp):
            names |= {node.args[0].body.value, node.args[0].orelse.value}
    names |= set(core.HOST_PROBLEMS)
    assert {"tot_absolu", "rig_warm", "memory_high"} <= names
    missing = sorted(n for n in names if emit.by_machine(n) is None)
    assert not missing, f"problèmes du superviseur sans code : {missing}"
    assert set(core.LADDER) == set(core.LADDER_CODES)


def test_no_alert_is_sent_with_a_free_text_title() -> None:
    """Toute alerte part d'un code : premier argument jamais un texte (« titre » libre) ; Notifier.send réservé
    aux essais."""
    bad = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            where = f"{path.relative_to(ROOT.parent)}:{node.lineno}"
            if name in ALERT_CALLS and node.args and isinstance(node.args[0], (ast.Constant, ast.JoinedStr)):
                bad.append(where)
            if name == "send" and isinstance(node.func, ast.Attribute) and "notifier" in ast.unparse(node.func.value) \
                    and path.name != "notify.py":
                bad.append(where + " (Notifier.send)")
            if name == "notify" and isinstance(node.func, ast.Attribute) and path.parent.name == "supervisor" and node.args \
                    and isinstance(node.args[0], (ast.Constant, ast.JoinedStr)):
                bad.append(where)
    assert not bad, "alertes sans code du catalogue : " + ", ".join(bad)
