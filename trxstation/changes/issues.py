# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Tickets GitHub d'un poste (étape 409) : ceux qui portent l'étiquette `poste:<numéro Hamlib>`, posée par
.github/workflows/issue-labels.yml d'après la liste déroulante des formulaires.

API publique de GitHub, sans compte ni jeton (60 requêtes par heure et par adresse : trx-update-check une fois par
jour, plus « Chercher maintenant » du menu 7.4). Titres écrits par des inconnus : texte nettoyé (codes du terminal,
caractères de contrôle, longueur), jamais interprété ; adresses limitées aux tickets du dépôt officiel.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..update.check import REPO, clean_text

LIMIT = 50
SCHEMA = 1
MAX_BYTES = 1024 * 1024
ISSUE_PREFIX = f"https://github.com/{REPO}/issues/"


def label(model: int) -> str:
    return f"poste:{model}"


def api_url(model: int) -> str:
    return f"https://api.github.com/repos/{REPO}/issues?labels={label(model)}&state=all&per_page={LIMIT}"


def page_url(model: int) -> str:
    """Page GitHub des tickets du poste (pour tout voir dans le navigateur)."""
    return f"https://github.com/{REPO}/issues?q=label%3A{label(model).replace(':', '%3A')}"


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    open: bool
    created: str            # AAAA-MM-JJ
    closed: str             # AAAA-MM-JJ ou ""
    url: str


def parse_api(raw: bytes) -> list[Issue]:
    """Réponse de l'API (liste) -> tickets (les demandes de fusion sont écartées). ValueError si illisible."""
    if len(raw) > MAX_BYTES:
        raise ValueError("réponse trop grande")
    items = json.loads(raw.decode("utf-8"))
    if not isinstance(items, list):
        raise ValueError("réponse inattendue")
    out: list[Issue] = []
    for item in items:
        if not isinstance(item, dict) or "pull_request" in item:
            continue
        number, url = item.get("number"), item.get("html_url")
        if isinstance(number, bool) or not isinstance(number, int) or url != f"{ISSUE_PREFIX}{number}":
            continue
        out.append(Issue(number=number, title=clean_text(item.get("title") or "", 120, single_line=True) or "—",
                         open=item.get("state") == "open",
                         created=clean_text(item.get("created_at") or "", 40, single_line=True)[:10],
                         closed=clean_text(item.get("closed_at") or "", 40, single_line=True)[:10], url=url))
    return out[:LIMIT]


def cache_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "update" / "issues.json"


def to_cache(model: int, issues: list[Issue], now: float | None = None) -> bytes:
    data = {"schema": SCHEMA, "model": model, "fetched_at": time.time() if now is None else now,
            "issues": [asdict(i) for i in issues]}
    return (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def load_cached(state_dir: str | Path, model: int) -> tuple[list[Issue], float] | None:
    """(tickets, date du relevé) du dernier relevé pour CE poste ; None si absent, abîmé ou pour un autre poste."""
    try:
        data = json.loads(cache_path(state_dir).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("model") != model:
            return None
        issues = []
        for d in data.get("issues", [])[:LIMIT]:
            i = Issue(**{k: d[k] for k in Issue.__dataclass_fields__})
            if not (isinstance(i.number, int) and i.url == f"{ISSUE_PREFIX}{i.number}"):
                return None
            issues.append(Issue(i.number, clean_text(i.title, 120, single_line=True), i.open is True,
                                clean_text(i.created, 10, single_line=True), clean_text(i.closed, 10, single_line=True),
                                i.url))
        return issues, float(data.get("fetched_at", 0.0))
    except (OSError, ValueError, TypeError, KeyError):
        return None
