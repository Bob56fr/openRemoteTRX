# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Modules à faire tourner, d'après [modules] de station.toml.

Partagé par la passerelle (qui n'accepte sur le bus que ces modules) et par
le superviseur (qui les lance) : les deux voient exactement la même liste.
"""

from __future__ import annotations

from pathlib import Path

from .manifest import Manifest, discover

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"


def selected_manifests(modules_cfg, builtin_dir: Path = BUILTIN_DIR) -> tuple[list[Manifest], list[str]]:
    """(manifestes des modules de `run`, problèmes lisibles).

    Un module du dossier supplémentaire ne peut pas remplacer un module fourni
    du même nom : le module fourni est gardé et le doublon signalé.
    """
    found, problems = discover(builtin_dir)
    by_name = {m.name: m for m in found}
    if modules_cfg.extra_dir:
        extra, extra_problems = discover(Path(modules_cfg.extra_dir))
        problems += extra_problems
        for m in extra:
            if m.name in by_name:
                problems.append(f"module {m.name} de {modules_cfg.extra_dir} ignoré : "
                                "un module fourni porte déjà ce nom")
            else:
                by_name[m.name] = m
    selected: list[Manifest] = []
    for name in modules_cfg.run:
        m = by_name.get(name)
        if m is None:
            problems.append(f"module « {name} » introuvable (cité dans [modules] run)")
        elif m.start == "disabled":
            problems.append(f"module « {name} » désactivé par son manifeste")
        else:
            selected.append(m)
    return selected, problems
