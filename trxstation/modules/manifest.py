# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Manifestes de modules (modules/<nom>/manifest.toml).

Le superviseur lit chaque manifeste au démarrage. Le bus s'en sert pour
n'accorder à un module que les droits qu'il a déclarés.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import API_VERSION

# Événements diffusés par le cœur (section 5 du cahier des charges).
KNOWN_EVENTS = frozenset({"ptt", "freq_mode", "trx_state", "client", "degrade"})
# Commandes qu'un module peut être autorisé à demander au cœur.
KNOWN_COMMANDS = frozenset({"qsy"})
START_MODES = ("auto", "on_demand", "disabled")
DEGRADATION_LEVELS = (1, 2, 3, 4, 5)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?([-+][0-9A-Za-z.]+)?$")
_ENTRY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class ManifestError(ValueError):
    """Manifeste refusé ; le message dit pourquoi, en français."""


@dataclass(frozen=True)
class Rights:
    events: frozenset[str] = frozenset()
    commands: frozenset[str] = frozenset()
    client_messages: bool = False
    verify_tokens: bool = False


@dataclass(frozen=True)
class Resources:
    cpu_quota: int = 25          # % d'un cœur (CPUQuota systemd)
    memory_max_mb: int = 256     # MemoryMax
    nice: int = 10               # priorité basse (0..19)


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    api: str
    entry: str
    start: str = "auto"
    description: str = ""
    rights: Rights = field(default_factory=Rights)
    resources: Resources = field(default_factory=Resources)
    degradation_levels: tuple[int, ...] = ()
    ports: tuple[int, ...] = ()
    path: Path | None = None


def api_compatible(required: str, provided: str = API_VERSION) -> bool:
    """Même version majeure, et mineure demandée <= mineure fournie."""
    try:
        r_major, r_minor = (int(x) for x in required.split(".")[:2])
        p_major, p_minor = (int(x) for x in provided.split(".")[:2])
    except ValueError:
        return False
    return r_major == p_major and r_minor <= p_minor


def _str_list(value, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ManifestError(f"{label} doit être une liste de textes")
    return value


def parse_manifest(data: dict, path: Path | None = None) -> Manifest:
    mod = data.get("module")
    if not isinstance(mod, dict):
        raise ManifestError("section [module] absente")
    name = mod.get("name", "")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ManifestError(f"nom de module invalide : {name!r} "
                            "(minuscules, chiffres, - ou _, 2 à 32 caractères)")
    version = mod.get("version", "")
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise ManifestError(f"{name} : version invalide {version!r}")
    api = mod.get("api", "")
    if not isinstance(api, str) or not re.match(r"^\d+\.\d+$", api):
        raise ManifestError(f"{name} : version d'API invalide {api!r}")
    entry = mod.get("entry", "")
    if not isinstance(entry, str) or not _ENTRY_RE.match(entry):
        raise ManifestError(f"{name} : point d'entrée invalide {entry!r}")
    start = mod.get("start", "auto")
    if start not in START_MODES:
        raise ManifestError(f"{name} : démarrage {start!r} inconnu "
                            f"(attendu : {', '.join(START_MODES)})")

    r = data.get("rights", {}) or {}
    events = set(_str_list(r.get("events", []), f"{name} : rights.events"))
    unknown = events - KNOWN_EVENTS
    if unknown:
        raise ManifestError(f"{name} : événements inconnus {sorted(unknown)}")
    commands = set(_str_list(r.get("commands", []), f"{name} : rights.commands"))
    unknown = commands - KNOWN_COMMANDS
    if unknown:
        raise ManifestError(f"{name} : commandes non autorisables {sorted(unknown)}")
    rights = Rights(events=frozenset(events), commands=frozenset(commands),
                    client_messages=bool(r.get("client_messages", False)),
                    verify_tokens=bool(r.get("verify_tokens", False)))

    res = data.get("resources", {}) or {}
    try:
        resources = Resources(cpu_quota=int(res.get("cpu_quota", 25)),
                              memory_max_mb=int(res.get("memory_max_mb", 256)),
                              nice=int(res.get("nice", 10)))
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{name} : section [resources] invalide") from exc
    if not 1 <= resources.cpu_quota <= 400:
        raise ManifestError(f"{name} : cpu_quota hors limites (1 à 400 %)")
    if not 16 <= resources.memory_max_mb <= 8192:
        raise ManifestError(f"{name} : memory_max_mb hors limites (16 à 8192)")
    if not 0 <= resources.nice <= 19:
        raise ManifestError(f"{name} : nice hors limites (0 à 19) ; "
                            "un module ne peut pas être prioritaire sur le cœur")

    levels = (data.get("degradation", {}) or {}).get("levels", [])
    if not isinstance(levels, list) or any(l not in DEGRADATION_LEVELS for l in levels):
        raise ManifestError(f"{name} : paliers de dégradation invalides (1 à 5)")
    ports = (data.get("network", {}) or {}).get("ports", [])
    if not isinstance(ports, list) or any(
            not isinstance(p, int) or not 1024 <= p <= 65535 for p in ports):
        raise ManifestError(f"{name} : ports invalides (1024 à 65535)")

    return Manifest(name=name, version=version, api=api, entry=entry, start=start,
                    description=str(mod.get("description", "")), rights=rights,
                    resources=resources, degradation_levels=tuple(sorted(set(levels))),
                    ports=tuple(ports), path=path)


def load_manifest(path: Path) -> Manifest:
    path = Path(path)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"{path} : TOML invalide ({exc})") from exc
    return parse_manifest(data, path=path)


def discover(modules_dir: Path) -> tuple[list[Manifest], list[str]]:
    """Charge tous les modules/<nom>/manifest.toml.

    Retourne (manifestes valides, erreurs lisibles). Un manifeste invalide
    n'empêche jamais les autres de se charger.
    """
    found: list[Manifest] = []
    errors: list[str] = []
    modules_dir = Path(modules_dir)
    if not modules_dir.is_dir():
        return found, errors
    seen: set[str] = set()
    for mpath in sorted(modules_dir.glob("*/manifest.toml")):
        try:
            m = load_manifest(mpath)
        except ManifestError as exc:
            errors.append(str(exc))
            continue
        if m.name in seen:
            errors.append(f"{mpath} : module {m.name} déclaré deux fois")
            continue
        seen.add(m.name)
        found.append(m)
    return found, errors
