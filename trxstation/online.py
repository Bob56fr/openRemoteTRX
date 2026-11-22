# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Services en ligne (étape 351) : ce que chaque fonction sait DÉJÀ de son serveur, relevé à chaque échange réel,
sans aucune sonde de plus. Lu par le panneau « Services en ligne » du tableau de bord (trx-monitor, console web).

- `LinkHealth` : dernier échange réussi (heure, temps de réponse) et échec en cours (depuis quand, code ORT) ;
  tenu par le client HTTP du relais (présence, monitoring) et celui du serveur de diffusion, publié dans le
  `status.json` de leur module (clé `server`).
- alertes ntfy : chaque processus qui envoie des alertes (superviseur, passerelle) écrit son propre fichier
  `state_dir/ntfy/<processus>.json` (jamais l'adresse) ; `read_ntfy` les fusionne."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

NTFY_DIR = "ntfy"


class LinkHealth:
    """État d'une liaison vers un serveur, mis à jour par le client lui-même (aucun échange ajouté)."""

    def __init__(self, code: str, clock: Callable[[], float] = time.time) -> None:
        self.code = code                       # code ORT d'un échec (catalogue d'erreurs)
        self.clock = clock
        self.ok_at: float | None = None
        self.rtt_ms: int | None = None
        self.fail_at: float | None = None
        self.fail_since: float | None = None

    def ok(self, rtt_s: float) -> None:
        self.ok_at = self.clock()
        self.rtt_ms = max(0, round(rtt_s * 1000))
        self.fail_since = None

    def fail(self) -> None:
        self.fail_at = self.clock()
        if self.fail_since is None:
            self.fail_since = self.fail_at

    def to_dict(self) -> dict:
        out: dict = {"ok_at": _int(self.ok_at), "rtt_ms": self.rtt_ms, "fail_at": _int(self.fail_at),
                     "fail_since": _int(self.fail_since)}
        if self.fail_since is not None:
            out["code"] = self.code
        return out


def _int(v: float | None) -> int | None:
    return None if v is None else int(v)


def write_json(path: Path, data: dict) -> None:
    """Écriture atomique, 0644 (rien de secret), jamais d'exception."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError:
        pass


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class NtfyRecord:
    """Résultat des envois ntfy d'UN processus (`state_dir/ntfy/<who>.json`) : configuré ou non, dernier envoi
    réussi, dernier échec. Écrit à la création (configuré ou non) puis après chaque envoi ; garde l'historique
    du fichier précédent (redémarrage)."""

    def __init__(self, state_dir: str | Path, who: str, configured: bool, clock: Callable[[], float] = time.time):
        self.path = Path(state_dir) / NTFY_DIR / f"{who}.json"
        self.clock = clock
        old = read_json(self.path) or {}
        self.data = {"configured": bool(configured), "ok_at": old.get("ok_at"), "fail_at": old.get("fail_at")}
        write_json(self.path, self.data)

    def sent(self, ok: bool) -> None:
        old = read_json(self.path) or {}                  # plusieurs Notifier dans un même processus : relire
        self.data.update({k: old.get(k, self.data.get(k)) for k in ("ok_at", "fail_at")})
        self.data["ok_at" if ok else "fail_at"] = int(self.clock())
        write_json(self.path, self.data)


_RECORDS: dict[Path, NtfyRecord] = {}


def ntfy_record(cfg, who: str) -> NtfyRecord | None:
    """Le relevé ntfy de ce processus (un seul par fichier) ; None si le dossier d'état n'est pas utilisable."""
    try:
        state_dir = Path(cfg.supervisor.state_dir)
        path = state_dir / NTFY_DIR / f"{who}.json"
        if path not in _RECORDS:
            _RECORDS[path] = NtfyRecord(state_dir, who, configured=bool(cfg.supervisor.notify_url))
        return _RECORDS[path]
    except (AttributeError, TypeError, OSError):
        return None


def read_ntfy(state_dir: str | Path) -> dict | None:
    """Fusion des fichiers des processus : None si aucun ; `configured` si l'un l'est ; derniers envois."""
    folder = Path(state_dir) / NTFY_DIR
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        return None
    records = [r for r in (read_json(f) for f in files) if r is not None]
    if not records:
        return None

    def latest(key: str) -> int | None:
        values = [r.get(key) for r in records if isinstance(r.get(key), (int, float))]
        return int(max(values)) if values else None
    return {"configured": any(r.get("configured") for r in records), "ok_at": latest("ok_at"),
            "fail_at": latest("fail_at")}


def online_section(state_dir: str | Path, lang: str = "fr") -> dict | None:
    """Section « Services en ligne » de la synthèse du matériel (commande host_info : opérateurs seulement, page et
    application) : mêmes lignes que le tableau de bord, dans la langue du client ; None si aucune fonction en service."""
    from .i18n import LANGS, Translator
    from .monitor.model import Snapshot, _online_panel
    folder = Path(state_dir)
    snap = Snapshot(status=None, gateway_fresh=False, stale_s=None, safe_mode=None,
                    presence=read_json(folder / "presence" / "status.json"),
                    monlink=read_json(folder / "monlink" / "status.json"),
                    diffusion=read_json(folder / "diffusion" / "status.json"), ntfy=read_ntfy(folder))
    panel = _online_panel(snap, Translator(lang if lang in LANGS else "fr", "monitor"))
    if panel is None:
        return None
    return {"title": panel.title, "rows": [[r.label, r.text] for r in panel.rows]}
