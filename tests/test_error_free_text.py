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
    # étape 209 : monitoring inter-stations (module « monlink », né avec les codes)
    "monlink/engine.py",
    "monlink/service.py",
    "monlink/collect.py",
    "monlink/store.py",
    "monlink/relay.py",
    # étape 244 : diffusion en direct (module « diffusion », né avec les codes ; son vers le module)
    "diffusion/service.py",
    "diffusion/source.py",
    "diffusion/meta.py",
    "gateway/audio/diffusion_out.py",
    # étape 214 : partie 2b, lot 1 (bus et pont des modules, Cluster DX, SELCALL)
    "modules/bus.py",
    "modules/client.py",
    "modules/gateway_bridge.py",
    "modules/launcher.py",
    "modules/supervisor_glue.py",
    "modules/demo_module.py",
    "cluster/service.py",
    "selcall/receiver.py",
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


# Le moteur des codes lui-même : il ne peut pas s'émettre (catalogue illisible, abonné en erreur).
ENGINE = {("errors/emit.py", "catalog"), ("errors/emit.py", "publish")}


def test_no_free_text_error_anywhere_in_the_station() -> None:
    """Étape 214 : partie 2b du catalogue terminée, TOUTE la station passe par les codes ; un nouveau
    `log.warning / error / critical / exception` est refusé partout (sauf `ALLOWED` et le moteur des codes)."""
    bad = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        bad += [b for b in _free_text_calls(rel) if (rel, b.rsplit("(", 1)[1].rstrip(")")) not in ENGINE]
    assert not bad, "texte d'erreur libre (utiliser emit_event et un code du catalogue) : " + ", ".join(bad)


def test_every_emitted_code_receives_all_the_variables_of_its_message() -> None:
    """`emit_event(codes.ORT_X, …)` avec un code écrit en dur : chaque {variable} du message reçoit sa valeur (sinon le
    texte publié garde « {variable} », illisible au téléphone et chez la station qui aide). Appels avec `**contexte`
    non vérifiables ici : ignorés."""
    import json
    import re
    entries = json.loads((ROOT / "errors" / "catalog.json").read_text(encoding="utf-8"))["codes"]
    missing = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "emit_event"
                    and node.args and isinstance(node.args[0], ast.Attribute) and node.args[0].attr.startswith("ORT_")):
                continue
            if any(k.arg is None for k in node.keywords):
                continue
            entry = entries.get(node.args[0].attr.replace("_", "-"))
            assert entry is not None, f"{rel}:{node.lineno} : code absent du catalogue"
            lack = set(re.findall(r"\{(\w+)\}", entry["message"])) - {k.arg for k in node.keywords}
            if lack:
                missing.append(f"{rel}:{node.lineno} {node.args[0].attr} sans {sorted(lack)}")
    assert not missing, "variables du message non fournies : " + ", ".join(missing)


def test_the_ratchet_list_names_existing_files() -> None:
    assert all((ROOT / rel).is_file() for rel in CONVERTED)
    assert all(rel in CONVERTED for rel, _ in ALLOWED)


def test_the_detector_sees_a_free_text_error(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "x.py").write_text('import logging\nlog = logging.getLogger()\ndef f():\n    log.error("oups")\n',
                                   encoding="utf-8")
    monkeypatch.setattr(__import__(__name__), "ROOT", tmp_path)
    assert _free_text_calls("x.py") == ["x.py:4 (f)"]
