# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Ce que la station SURVEILLÉE peut envoyer (cahier § 17.6), lu sans aucun droit sur le poste :

- fichier d'état de la passerelle (`[supervisor] status_path`, 0644) : liaison CAT, émission, fréquence et mode,
  connexions ; sa fraîcheur dit si la passerelle tourne ;
- mode sûr du superviseur (`state_dir/safe_mode`) ;
- santé de la machine (`hostinfo.HostMonitor`, stdlib) ;
- événements du catalogue des journaux JSON (`state_dir/journal-*.jsonl`, étape 174), lus à partir de LÀ OÙ ILS EN
  ÉTAIENT (jamais l'historique au premier démarrage), rotation des fichiers comprise.
Le masquage (`redact.py`) et le profil (`profiles.py`) s'appliquent ensuite, dans engine.py, avant tout envoi.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import __version__
from ..status import read_status

GATEWAY_STALE_S = 10.0
MAX_EVENTS_PER_READ = 200
MAX_LINE = 16 * 1024


def heartbeat(status_path: str | Path, state_dir: str | Path, *, started: float, clock=time.time) -> dict:
    """Battement : version, temps de marche du module, mode sûr, passerelle vivante ou non."""
    gw = read_status(status_path)
    now = clock()
    safe = None
    try:
        safe = (Path(state_dir) / "safe_mode").read_text(encoding="utf-8").strip() or "raison inconnue"
    except FileNotFoundError:
        pass
    except OSError:
        safe = "mode sûr (fichier illisible)"
    return {"v": __version__, "up": int(now - started), "safe": safe,
            "gateway": "absent" if gw is None else ("ok" if now - gw.written_at <= GATEWAY_STALE_S else "stale")}


def rig_state(status_path: str | Path) -> dict:
    """État du poste vu par la passerelle, aux noms de `profiles.RIG_SECRET_FIELDS` (fréquence et mode retirés ensuite
    sauf autorisation de l'opérateur) ; {} si la passerelle n'a jamais écrit son état."""
    gw = read_status(status_path)
    if gw is None:
        return {}
    rig, ptt = gw.rig or {}, gw.ptt or {}
    return {"cat": bool(rig.get("connected")), "cat_error": rig.get("last_error") or "",
            "tx": ptt.get("state"), "fault": ptt.get("fault") or "", "clients": len(gw.clients),
            "freq": rig.get("frequency_hz"), "mode": rig.get("mode"), "tx_freq": rig.get("tx_frequency_hz"),
            "vfo": rig.get("vfo"), "width": rig.get("passband_hz")}


def system_state(monitor) -> dict:
    """Charge, mémoire, disque, température (ce que montre déjà le bargraph des opérateurs)."""
    try:
        return dict(monitor.summary())
    except Exception:                           # mesure impossible sur cette machine : rien plutôt qu'une panne
        return {}


class JournalTail:
    """Nouveaux événements du catalogue des journaux JSON de la station, fichier par fichier.

    `positions` (gardé par engine.py dans monlink.json) : chemin -> [taille connue, position]. Fichier plus court
    qu'avant = rotation : relu depuis le début. Fichier déjà là à la PREMIÈRE lecture et jamais vu : on part de sa fin
    (pas d'historique) ; fichier apparu ENSUITE (passerelle démarrée après le module) : lu depuis son début (étape
    213 : ses premiers événements étaient perdus)."""

    def __init__(self, folder: str | Path, positions: dict | None = None) -> None:
        self.folder = Path(folder)
        self.positions: dict[str, list[int]] = dict(positions or {})
        self.lines: list[dict] = []
        self._first = True

    def read(self) -> list[dict]:
        """Événements du catalogue lus depuis la dernière fois ; `self.lines` reçoit TOUTES les lignes lues
        (avertissements sans code compris) pour les journaux envoyés pendant le mode assistance."""
        events: list[dict] = []
        self.lines: list[dict] = []
        for path in sorted(self.folder.glob("journal-*.jsonl")):
            key = path.name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            known = self.positions.get(key)
            if known is None and self._first:
                self.positions[key] = [size, size]
                continue
            if known is None:
                known = [0, 0]
            pos = 0 if size < known[1] else known[1]
            if size == pos:
                self.positions[key] = [size, pos]
                continue
            try:
                with path.open("rb") as fh:
                    fh.seek(pos)
                    chunk = fh.read(min(size - pos, 4 * 1024 * 1024))
            except OSError:
                continue
            end = chunk.rfind(b"\n")
            if end < 0:
                continue                         # ligne en cours d'écriture : au prochain tour
            for raw in chunk[:end].split(b"\n"):
                line = _line(raw)
                if line is None:
                    continue
                if len(self.lines) < MAX_EVENTS_PER_READ:
                    self.lines.append(line)
                if isinstance(line.get("code"), str) and len(events) < MAX_EVENTS_PER_READ:
                    events.append(line)
            self.positions[key] = [size, pos + end + 1]
        self._first = False
        return events


def _line(raw: bytes) -> dict | None:
    """Une ligne du journal JSON, champs connus seulement (pas de trace d'exception : chemins, variables)."""
    if not raw.strip() or len(raw) > MAX_LINE:
        return None
    try:
        line = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(line, dict):
        return None
    out = {k: line[k] for k in ("ts", "processus", "niveau", "source", "code", "gravite", "titre", "contexte",
                                "module") if k in line}
    if "message" in line:
        out["message"] = str(line["message"])[:500]
    return out
