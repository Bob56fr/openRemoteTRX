# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fichier d'état de la mesure de TOS (`state_dir/swr.json`, docs/tos-cahier-des-charges.md § 3) : derniers choix de
chaque opérateur (puissance, points), temps de lecture fiable du TOS étalonné par modèle de poste, dernière mesure.

Jamais dans station.toml : la passerelle ne doit pas pouvoir écrire dans le fichier des bandes autorisées.
Écriture atomique ; un fichier illisible n'empêche jamais de démarrer (on repart des défauts).
"""
from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import tempfile
from pathlib import Path
from ..errors import codes
from ..errors.emit import emit_event

log = logging.getLogger(__name__)

DEFAULT_POWER_PCT = 15
DEFAULT_POINTS = 11


class SwrStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._data: dict = {"version": 1, "choices": {}, "settle_s": {}, "last": None}
        self._load()

    # ------------------------------------------------------------------ lecture

    def choices(self, account: str) -> dict:
        c = self._data["choices"].get(account, {})
        return {"power_pct": c.get("power_pct", DEFAULT_POWER_PCT), "points": c.get("points", DEFAULT_POINTS)}

    def settle_s(self, model: int) -> float | None:
        value = self._data["settle_s"].get(str(model))
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 else None

    def last(self) -> dict | None:
        return self._data["last"]

    # ------------------------------------------------------------------ écriture (jamais d'exception vers la mesure)

    def save_choices(self, account: str, power_pct: float, points: int) -> None:
        self._data["choices"][account] = {"power_pct": power_pct, "points": points}
        self._persist()

    def save_settle(self, model: int, seconds: float) -> None:
        self._data["settle_s"][str(model)] = round(float(seconds), 2)
        self._persist()

    def forget_settle(self, model: int) -> None:
        self._data["settle_s"].pop(str(model), None)
        self._persist()

    def save_last(self, result: dict) -> None:
        self._data["last"] = result
        self._persist()

    def _persist(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".swr-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(self._data, ensure_ascii=False, indent=1))
                if os.name == "posix":
                    os.chmod(tmp, 0o644)               # TRX Console (compte de bureau) affiche la dernière mesure
                os.replace(tmp, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError as exc:                         # une mesure ne doit jamais échouer pour un fichier d'état
            emit_event(codes.ORT_1007, logger=log, cas="non enregistré", detail=str(exc))

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ("choices", "settle_s"):
                    if isinstance(data.get(key), dict):
                        self._data[key] = data[key]
                if isinstance(data.get("last"), dict):
                    self._data["last"] = data["last"]
        except (OSError, ValueError) as exc:
            emit_event(codes.ORT_1007, logger=log, cas="illisible (valeurs par défaut)", detail=str(exc))
