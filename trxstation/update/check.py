# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Recherche d'une nouvelle version sur GitHub (API publique, sans jeton) : `python -m trxstation.update.check`.

Lancé par le timer systemd trx-update-check (compte trx, jamais root) au démarrage puis toutes les 24 h.
Il n'installe RIEN : il écrit `<state_dir>/update/latest.json`, que TRX Console affiche.
Tout ce qui vient de GitHub est une donnée non fiable : versions et adresses vérifiées, notes nettoyées
(aucun caractère de contrôle ne doit atteindre le terminal). Le paquet lui-même est vérifié par sa
signature avant toute installation (signing.py) ; ce fichier ne sert qu'à le proposer.
Hors ligne ou limite de l'API atteinte : la dernière version connue est gardée, avec l'erreur.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import __version__
from ..status import replace_atomic

REPO = "Bob56fr/openRemoteTRX"
API_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
PAGE_PREFIX = f"https://github.com/{REPO}/releases/"
SCHEMA = 1
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_SIG_BYTES = 4096
MAX_NOTES_CHARS = 4000
MAX_NAME_CHARS = 120
MAX_CHANGES = 12                  # versions sautées dont les notes sont gardées (de la plus récente à la plus ancienne)
MAX_CHANGES_CHARS = 16000         # total des notes gardées pour le journal des changements
TIMEOUT_S = 20.0

_VERSION_RE = re.compile(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:(a|b|rc)(\d{1,4}))?")
_STAGES = {"a": 0, "b": 1, "rc": 2, None: 3}
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b.")
_BIDI = {chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C)}

Fetch = Callable[[str], bytes]


class CheckError(Exception):
    pass


# ------------------------------------------------------------------ versions

def parse_version(text: object) -> tuple[int, int, int, int, int] | None:
    """Clé de tri de « 0.23.0 », « v0.23.0 », « 0.23.0rc1 » (forme PEP 440 de pyproject) ; None sinon."""
    if not isinstance(text, str) or (m := _VERSION_RE.fullmatch(text)) is None:
        return None
    major, minor, patch, stage, number = m.groups()
    return int(major), int(minor), int(patch), _STAGES[stage], int(number or 0)


def is_prerelease_version(text: str) -> bool:
    key = parse_version(text)
    return key is not None and key[3] != _STAGES[None]


# ------------------------------------------------------------------ nettoyage du texte venu de GitHub

def clean_text(text: object, max_chars: int, *, single_line: bool = False) -> str:
    """Retire séquences d'échappement, caractères de contrôle et de direction ; tronque."""
    if not isinstance(text, str):
        return ""
    text = _CSI_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n")).replace("\t", "    ")
    kept = []
    for ch in text:
        if ch == "\n":
            kept.append(" " if single_line else ch)
        elif ch in _BIDI or unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue
        else:
            kept.append(ch)
    text = re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()
    if single_line:
        text = re.sub(r" {2,}", " ", text)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + " […] (suite sur GitHub)"
    return text


# ------------------------------------------------------------------ Releases

def package_name(version: str) -> str:
    return f"trx-remote-debian-{version}.zip"


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    name: str
    notes: str
    published_at: str
    page_url: str
    prerelease: bool
    zip_name: str
    zip_url: str
    zip_size: int
    sig_url: str

    @classmethod
    def from_dict(cls, data: object) -> Release | None:
        """Relecture STRICTE (latest.json est écrit par un autre compte) ; None au moindre écart."""
        if not isinstance(data, dict):
            return None
        try:
            release = cls(**{k: data[k] for k in cls.__dataclass_fields__})
        except (KeyError, TypeError):
            return None
        return release if release.problem() is None else None

    def problem(self) -> str | None:
        if not all(isinstance(getattr(self, k), str) for k in
                   ("version", "tag", "name", "notes", "published_at", "page_url", "zip_name", "zip_url", "sig_url")):
            return "champ de type inattendu"
        if parse_version(self.version) is None or self.version.startswith("v") or self.tag != f"v{self.version}":
            return f"version ou étiquette refusée : {self.tag!r}"
        if self.zip_name != package_name(self.version):
            return f"nom de paquet inattendu : {self.zip_name!r}"
        expected = f"{DOWNLOAD_PREFIX}{self.tag}/"
        if self.zip_url != expected + self.zip_name or self.sig_url != expected + self.zip_name + ".sig":
            return "adresse de téléchargement hors du dépôt officiel"
        if not self.page_url.startswith(PAGE_PREFIX):
            return "page de la version hors du dépôt officiel"
        if isinstance(self.zip_size, bool) or not isinstance(self.zip_size, int) or not 0 < self.zip_size <= MAX_PACKAGE_BYTES:
            return "taille du paquet invalide"
        if not isinstance(self.prerelease, bool):
            return "indicateur de pré-version invalide"
        return None


def release_from_github(item: object) -> Release | None:
    """Release utilisable tirée d'une entrée de l'API ; None si brouillon, incomplète ou suspecte."""
    if not isinstance(item, dict) or item.get("draft") is not False:
        return None
    tag = item.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v") or parse_version(tag[1:]) is None:
        return None
    version = tag[1:]
    assets = {a.get("name"): a for a in item.get("assets") or [] if isinstance(a, dict)}
    zip_asset, sig_asset = assets.get(package_name(version)), assets.get(package_name(version) + ".sig")
    if zip_asset is None or sig_asset is None:
        return None
    sig_size = sig_asset.get("size")
    if not isinstance(sig_size, int) or not 0 < sig_size <= MAX_SIG_BYTES:
        return None
    release = Release(
        version=version, tag=tag,
        name=clean_text(item.get("name") or tag, MAX_NAME_CHARS, single_line=True),
        notes=clean_text(item.get("body") or "", MAX_NOTES_CHARS),
        published_at=clean_text(item.get("published_at") or "", 40, single_line=True),
        page_url=item.get("html_url") if isinstance(item.get("html_url"), str) else "",
        prerelease=bool(item.get("prerelease")) or is_prerelease_version(version),
        zip_name=package_name(version), zip_url=zip_asset.get("browser_download_url"),
        zip_size=zip_asset.get("size"), sig_url=sig_asset.get("browser_download_url"))
    return release if release.problem() is None else None


def choose_release(items: object, installed: str, *, allow_prerelease: bool) -> Release | None:
    """La plus haute version publiée, plus récente que `installed`, ou None."""
    if not isinstance(items, list):
        raise CheckError("réponse de GitHub inattendue (liste de versions attendue)")
    current = parse_version(installed)
    if current is None:
        raise CheckError(f"version installée illisible : {installed!r}")
    best: Release | None = None
    for item in items:
        release = release_from_github(item)
        if release is None or (release.prerelease and not allow_prerelease):
            continue
        key = parse_version(release.version)
        if key > current and (best is None or key > parse_version(best.version)):
            best = release
    return best


@dataclass(frozen=True)
class Change:
    """Notes d'une version publiée entre la version installée et celle proposée (journal des changements)."""
    version: str
    name: str
    published_at: str
    notes: str

    @classmethod
    def from_dict(cls, data: object) -> Change | None:
        if not isinstance(data, dict) or parse_version(data.get("version")) is None:
            return None
        return cls(version=data["version"], name=clean_text(data.get("name"), MAX_NAME_CHARS, single_line=True),
                   published_at=clean_text(data.get("published_at"), 40, single_line=True),
                   notes=clean_text(data.get("notes"), MAX_NOTES_CHARS))


def collect_changes(items: object, installed: str, offered: str, *, allow_prerelease: bool) -> list[Change]:
    """Notes de TOUTES les versions publiées après `installed` jusqu'à `offered` incluse, la plus récente d'abord.
    Une version sans paquet signé compte aussi (ses notes décrivent des changements contenus dans `offered`)."""
    low, high = parse_version(installed), parse_version(offered)
    if not isinstance(items, list) or low is None or high is None:
        return []
    found: dict[tuple, Change] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("draft") is not False:
            continue
        tag = item.get("tag_name")
        key = parse_version(tag[1:]) if isinstance(tag, str) and tag.startswith("v") else None
        if key is None or not low < key <= high:
            continue
        if (bool(item.get("prerelease")) or is_prerelease_version(tag[1:])) and not allow_prerelease:
            continue
        found[key] = Change(version=tag[1:], name=clean_text(item.get("name") or tag, MAX_NAME_CHARS, single_line=True),
                            published_at=clean_text(item.get("published_at") or "", 40, single_line=True),
                            notes=clean_text(item.get("body") or "", MAX_NOTES_CHARS))
    changes, budget = [], MAX_CHANGES_CHARS
    for key in sorted(found, reverse=True)[:MAX_CHANGES]:
        change = found[key]
        if len(change.notes) > budget:
            change = Change(change.version, change.name, change.published_at,
                            (change.notes[:budget].rstrip() + " […] (suite sur GitHub)") if budget > 0 else "(voir GitHub)")
        budget -= len(change.notes)
        changes.append(change)
    return changes


# ------------------------------------------------------------------ réseau

def http_get(url: str, *, max_bytes: int = MAX_RESPONSE_BYTES, timeout: float = TIMEOUT_S,
             accept: str = "application/vnd.github+json") -> bytes:
    """GET HTTPS (certificat vérifié), taille bornée ; CheckError lisible en cas d'échec."""
    if not url.startswith("https://"):
        raise CheckError("seules les adresses https:// sont autorisées")
    request = urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": f"trx-remote/{__version__}", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise CheckError("limite de requêtes de GitHub atteinte : nouvel essai plus tard") from exc
        raise CheckError(f"GitHub a répondu {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise CheckError(f"GitHub injoignable ({reason})") from exc
    if len(data) > max_bytes:
        raise CheckError("réponse trop grande")
    return data


# ------------------------------------------------------------------ état écrit pour TRX Console

@dataclass
class UpdateState:
    installed: str
    checked_at: float = 0.0           # horloge murale, pour l'affichage seulement
    ok: bool = False                  # dernière interrogation réussie
    error: str = ""
    release: Release | None = None    # version plus récente disponible (None = à jour ou inconnu)
    schema: int = SCHEMA
    changes: list[Change] = field(default_factory=list)   # facultatif (ajouté en 0.70.0, même schéma)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["release"] = asdict(self.release) if self.release else None
        return data


def state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "update" / "latest.json"


def write_state(path: str | Path, state: UpdateState) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".latest-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state.to_dict(), handle, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o644)
        replace_atomic(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_state(path: str | Path) -> UpdateState | None:
    """None si absent ou illisible (jamais d'exception) ; une Release suspecte est écartée."""
    try:
        return parse_state(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None


def parse_state(text: str) -> UpdateState | None:
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("installed"), str):
            return None
        raw_changes = data.get("changes")
        changes = [c for c in (Change.from_dict(x) for x in raw_changes[:MAX_CHANGES]) if c is not None]             if isinstance(raw_changes, list) else []
        return UpdateState(installed=data["installed"], checked_at=float(data.get("checked_at", 0.0)),
                           ok=data.get("ok") is True, error=clean_text(data.get("error", ""), 300, single_line=True),
                           release=Release.from_dict(data.get("release")), changes=changes)
    except (ValueError, TypeError):
        return None


def check(*, installed: str = __version__, allow_prerelease: bool = False, fetch: Fetch = http_get,
          previous: UpdateState | None = None, now: Callable[[], float] = time.time) -> UpdateState:
    """Interroge GitHub. En cas d'échec, garde la version connue de `previous` (si toujours plus récente)."""
    try:
        try:
            items = json.loads(fetch(API_URL))
        except ValueError as exc:
            raise CheckError("réponse de GitHub illisible") from exc
        release = choose_release(items, installed, allow_prerelease=allow_prerelease)
        changes = collect_changes(items, installed, release.version, allow_prerelease=allow_prerelease) if release else []
        return UpdateState(installed=installed, checked_at=now(), ok=True, release=release, changes=changes)
    except CheckError as exc:
        kept = previous.release if previous else None
        if kept is not None and (parse_version(kept.version) or ()) <= (parse_version(installed) or ()):
            kept = None
        if kept is not None and kept.prerelease and not allow_prerelease:
            kept = None
        changes = [c for c in previous.changes if (parse_version(c.version) or ()) > (parse_version(installed) or ())]             if kept is not None and previous is not None else []
        return UpdateState(installed=installed, checked_at=now(), ok=False, error=str(exc), release=kept, changes=changes)


def main(argv: list[str] | None = None, *, fetch: Fetch = http_get) -> int:
    from .. import config as cfgmod
    from ..paths import default_config_path

    ap = argparse.ArgumentParser(prog="trx-update-check", description="Cherche une nouvelle version (n'installe rien)")
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--output", type=Path, default=None, help="fichier d'état (défaut : <state_dir>/update/latest.json)")
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    if not cfg.update.enabled:
        print("Recherche de mise à jour désactivée ([update] enabled = false).")
        return 0
    path = args.output or state_path(cfg.supervisor.state_dir)
    state = check(allow_prerelease=cfg.update.allow_prerelease, fetch=fetch, previous=read_state(path))
    try:
        write_state(path, state)
    except OSError as exc:
        print(f"État de mise à jour non écrit ({path}) : {exc}", file=sys.stderr)
        return 1
    if not state.ok:
        print(f"Recherche de mise à jour impossible : {state.error}")
    elif state.release:
        print(f"Nouvelle version disponible : {state.release.version} (installée : {state.installed}).")
    else:
        print(f"TRX distant est à jour ({state.installed}).")
    return 0                                  # un échec réseau n'est pas une panne du service


if __name__ == "__main__":
    raise SystemExit(main())
