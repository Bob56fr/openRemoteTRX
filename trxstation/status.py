# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fichier d'état de la passerelle : contrat entre la passerelle (écrivain), le superviseur
et trx-monitor (lecteurs).

La fraîcheur se juge sur le CHANGEMENT de `seq` mesuré avec l'horloge monotone du lecteur,
jamais sur `written_at` : le Pi n'a pas toujours d'horloge fiable (pas de RTC, saut NTP).
Écriture atomique (fichier temporaire + os.replace) : un lecteur ne voit jamais un fichier
à moitié écrit. Sous Windows, le remplacement est refusé (PermissionError) tant qu'un lecteur
tient le fichier ouvert : quelques millisecondes plus tard il passe, d'où `replace_atomic`.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA = 1
REPLACE_RETRIES = 3               # au pire 5 + 10 + 15 ms d'attente, puis l'erreur remonte
REPLACE_RETRY_S = 0.005


def replace_atomic(tmp: str | Path, path: str | Path, *, retries: int = REPLACE_RETRIES,
                   sleep: Callable[[float], None] = time.sleep) -> None:
    """os.replace, réessayé brièvement si le fichier de destination est momentanément ouvert (Windows)."""
    for attempt in range(retries + 1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == retries:
                raise
            sleep(REPLACE_RETRY_S * (attempt + 1))


@dataclass
class GatewayStatus:
    pid: int
    seq: int                      # +1 à chaque écriture ; figé = passerelle gelée ou morte
    written_at: float             # horloge murale, pour l'affichage seulement
    ptt: dict                     # PttSnapshot.to_dict() : state, owner, fault, tot_remaining_s...
    rig: dict                     # RigState.to_dict()
    clients: list[str] = field(default_factory=list)
    schema: int = SCHEMA
    audio: dict = field(default_factory=dict)   # niveaux et compteurs audio (facultatif)
    spectrum: dict = field(default_factory=dict)  # spectre HF : state (off|waiting|starting|ok|error), code, message, compteurs


def write_status(path: str | Path, status: GatewayStatus) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(status), ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".status-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        if os.name == "posix":
            os.chmod(tmp, 0o644)       # mkstemp crée en 0600 : trx-monitor et le diagnostic (compte de bureau) doivent lire
        replace_atomic(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_status(path: str | Path) -> GatewayStatus | None:
    """None si le fichier est absent, illisible ou d'un format inattendu (jamais d'exception)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            return None
        pid, seq = data["pid"], data["seq"]
        ptt, rig, clients = data["ptt"], data["rig"], data.get("clients", [])
        if (isinstance(pid, bool) or not isinstance(pid, int) or isinstance(seq, bool)
                or not isinstance(seq, int) or not isinstance(ptt, dict) or "state" not in ptt
                or not isinstance(rig, dict) or not isinstance(clients, list)):
            return None
        audio, spectrum = data.get("audio", {}), data.get("spectrum", {})
        return GatewayStatus(pid=pid, seq=seq, written_at=float(data.get("written_at", 0.0)),
                             ptt=ptt, rig=rig, clients=[str(c) for c in clients],
                             audio=audio if isinstance(audio, dict) else {},
                             spectrum=spectrum if isinstance(spectrum, dict) else {})
    except (OSError, ValueError, KeyError, TypeError):
        return None


class GatewayWatch:
    """Suit la fraîcheur de la passerelle d'après le changement de `seq` (horloge monotone locale)."""

    def __init__(self, stale_after_s: float):
        self.stale_after_s = stale_after_s
        self.status: GatewayStatus | None = None
        self._key: tuple[int, int] | None = None
        self._last_change: float | None = None

    def update(self, status: GatewayStatus | None, now: float) -> None:
        self.status = status
        if status is not None and (status.pid, status.seq) != self._key:
            self._key = (status.pid, status.seq)
            self._last_change = now

    def age(self, now: float) -> float | None:
        """Secondes écoulées depuis le dernier changement de `seq` (None si jamais vu)."""
        return None if self._last_change is None else now - self._last_change

    def fresh(self, now: float) -> bool:
        age = self.age(now)
        return self.status is not None and age is not None and age <= self.stale_after_s
