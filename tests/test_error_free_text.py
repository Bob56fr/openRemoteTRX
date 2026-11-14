# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Aucun texte d'erreur libre (cahier du monitoring, § 7 et § 15) : dans les fichiers CONVERTIS, tout avertissement
ou erreur du journal passe par `emit_event(codes.ORT_NNNN, …)` (code, gravité, contexte, journal JSON).

Cliquet : la liste `CONVERTED` s'allonge domaine par domaine (étape 178 : sécurité d'émission et superviseur) ;
un fichier qui y entre ne peut plus revenir au texte libre. `log.info` / `log.debug` restent libres (traces).
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "trxstation"
FORBIDDEN = {"warning", "error", "critical", "exception", "warn", "fatal"}
CONVERTED = [
    "gateway/safety/ptt.py",
    # étape 179 : poste, spectre, audio, mesure de TOS, état publié, mémoires, profils de voix
    "gateway/cat/link.py",
    "spectrum/service.py",
    "gateway/audio/beeps.py",
    "gateway/audio/hub.py",
    "swr/runner.py",
    "swr/store.py",
    "gateway/status/publisher.py",
    "gateway/memories.py",
    "gateway/voice_profiles.py",
    # étape 180 : réseau et accès
    "gateway/main.py",
    "gateway/access_watch.py",
    "gateway/api/session.py",
    "gateway/api/webrtc.py",
    "gateway/api/server.py",
    "gateway/api/access.py",
    "netprobe/probe.py",
    "netprobe/store.py",
    "netprobe/vpn.py",
    "netprobe/station_probes.py",
    "supervisor/actions.py",
    "supervisor/backends.py",
    "supervisor/core.py",
    "supervisor/main.py",
    "supervisor/notify.py",
    "supervisor/usb.py",
]
# Exceptions motivées : (fichier, fonction).
ALLOWED = {("supervisor/notify.py", "send")}      # envoi brut sans code, réservé aux essais (test_error_alerts)


class _Finder(ast.NodeVisitor):
    """Appels log.warning / error… avec la fonction qui les contient (la plus proche)."""

    def __init__(self, rel: str) -> None:
        self.rel, self.stack, self.bad = rel, ["<module>"], []

    def _func(self, node: ast.AST) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _func

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in FORBIDDEN and isinstance(f.value, ast.Name) \
                and f.value.id in {"log", "logger", "logging"} and (self.rel, self.stack[-1]) not in ALLOWED:
            self.bad.append(f"{self.rel}:{node.lineno} ({self.stack[-1]})")
        self.generic_visit(node)


def _free_text_calls(rel: str) -> list[str]:
    finder = _Finder(rel)
    finder.visit(ast.parse((ROOT / rel).read_text(encoding="utf-8")))
    return finder.bad


def test_converted_files_log_problems_only_through_catalog_codes() -> None:
    bad = sorted({b for rel in CONVERTED for b in _free_text_calls(rel)})
    assert not bad, "texte d'erreur libre (utiliser emit_event et un code du catalogue) : " + ", ".join(bad)


def test_the_ratchet_list_names_existing_files() -> None:
    assert all((ROOT / rel).is_file() for rel in CONVERTED)
    assert all(rel in CONVERTED for rel, _ in ALLOWED)


def test_the_detector_sees_a_free_text_error(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "x.py").write_text('import logging\nlog = logging.getLogger()\ndef f():\n    log.error("oups")\n',
                                   encoding="utf-8")
    monkeypatch.setattr(__import__(__name__), "ROOT", tmp_path)
    assert _free_text_calls("x.py") == ["x.py:4 (f)"]
