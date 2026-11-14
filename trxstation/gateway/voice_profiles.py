# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Profils d'égaliseur et d'effets de voix de chaque OPÉRATEUR, enregistrés sur la station (étape 102) : le même
compte les retrouve sur la page et sur l'application, sur tous ses appareils. Ils s'affichent après les trois
préréglages (Neutre, DX, Ragchew) et comprennent la réverbération et le chorus.

La station ne fait que RANGER ces réglages : le traitement de la voix se fait sur le client (voice.js, VoiceDsp.kt),
qui revalide tout ce qu'il charge. Ici, les réglages sont quand même normalisés avec les MÊMES bornes que
`voice.js validate` (aucune clé inconnue, nombres bornés) pour ne jamais ranger n'importe quoi.
Le fichier est un petit JSON écrit de façon atomique ; un fichier illisible n'empêche jamais de démarrer.
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

MAX_PROFILES = 10                    # par compte
MAX_NAME = 32
BANDS_HZ = (100, 160, 250, 370, 570, 880, 1350, 2100, 3250, 5000)     # voice.js BANDS_HZ
GAIN_MAX_DB, Q_MIN, Q_MAX = 12.0, 0.3, 8.0
CHORUS_TYPES = ("classic", "ensemble", "double")
REVERB_TYPES = ("room", "hall", "plate", "spring")


class VoiceProfileError(OSError):
    """Écriture du fichier de profils impossible (disque plein, droits...)."""


def _num(value, low: float, high: float, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return min(high, max(low, float(value)))


def validate_name(name) -> str:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME or not name.strip().isprintable():
        raise ValueError(f"nom de profil invalide (1 à {MAX_NAME} caractères imprimables)")
    return name.strip()


def validate_settings(raw) -> dict:
    """Réglages reçus -> réglages complets et bornés (mêmes règles que voice.js validate). Jamais d'exception."""
    raw = raw if isinstance(raw, dict) else {}
    s: dict = {"version": 1, "enabled": raw.get("enabled") is True}
    s["highpassHz"] = _num(raw.get("highpassHz"), 20, 1000, 100)
    s["lowpassHz"] = _num(raw.get("lowpassHz"), 1500, 8000, 3000)
    if s["lowpassHz"] <= s["highpassHz"] + 300:
        s["lowpassHz"] = min(8000.0, s["highpassHz"] + 300)
    bands = raw.get("bands") if isinstance(raw.get("bands"), list) else []
    out = []
    for i, hz in enumerate(BANDS_HZ):
        b = bands[i] if i < len(bands) and isinstance(bands[i], dict) else {}
        edge = i in (0, len(BANDS_HZ) - 1)
        out.append({"hz": _num(b.get("hz"), hz / 1.5, hz * 1.5, hz), "gainDb": _num(b.get("gainDb"), -GAIN_MAX_DB, GAIN_MAX_DB, 0),
                    "q": _num(b.get("q"), Q_MIN, Q_MAX, 1.4), "shelf": b.get("shelf") is not False if edge else False})
    s["bands"] = out
    c = raw.get("chorus") if isinstance(raw.get("chorus"), dict) else {}
    s["chorus"] = {"on": c.get("on") is True, "type": c.get("type") if c.get("type") in CHORUS_TYPES else "classic",
                   "mix": _num(c.get("mix"), 0, 100, 30), "rateHz": _num(c.get("rateHz"), 0.1, 5, 0.8),
                   "depthMs": _num(c.get("depthMs"), 0.5, 8, 3)}
    r = raw.get("reverb") if isinstance(raw.get("reverb"), dict) else {}
    s["reverb"] = {"on": r.get("on") is True, "type": r.get("type") if r.get("type") in REVERB_TYPES else "room",
                   "mix": _num(r.get("mix"), 0, 100, 20), "seconds": _num(r.get("seconds"), 0.2, 4, 0.5)}
    m = raw.get("mic") if isinstance(raw.get("mic"), dict) else {}
    s["mic"] = {"gainDb": _num(m.get("gainDb"), -12, 20, 0), "gateOn": m.get("gateOn") is True,
                "gateDb": _num(m.get("gateDb"), -80, -20, -50)}
    return s


class VoiceProfileStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._data: dict[str, list[dict]] = {}
        self._load()

    def list(self, account: str) -> list[dict]:
        """Profils du compte, dans l'ordre d'enregistrement : [{name, settings}]."""
        return [dict(p) for p in self._data.get(account, [])]

    def save(self, account: str, name, settings) -> list[dict]:
        """Crée le profil, ou remplace celui du même nom (sans tenir compte des majuscules)."""
        name = validate_name(name)
        if not isinstance(settings, dict):
            raise ValueError("réglages attendus (objet JSON)")
        previous = {k: list(v) for k, v in self._data.items()}
        items = [p for p in self._data.get(account, []) if p["name"].lower() != name.lower()]
        replaced = len(items) != len(self._data.get(account, []))
        if not replaced and len(items) >= MAX_PROFILES:
            raise ValueError(f"{MAX_PROFILES} profils au maximum par compte")
        items.append({"name": name, "settings": validate_settings(settings)})
        self._data[account] = items
        self._commit(previous)
        return self.list(account)

    def delete(self, account: str, name) -> list[dict]:
        if not isinstance(name, str):
            raise ValueError("nom de profil attendu")
        items = self._data.get(account, [])
        kept = [p for p in items if p["name"].lower() != name.strip().lower()]
        if len(kept) == len(items):
            raise ValueError("profil inconnu")
        previous = {k: list(v) for k, v in self._data.items()}
        self._data[account] = kept
        self._commit(previous)
        return self.list(account)

    # ------------------------------------------------------------------ fichier

    def _commit(self, previous: dict[str, list[dict]]) -> None:
        try:
            self._persist()
        except OSError as exc:
            self._data = previous                                   # rien n'est annoncé qui n'ait été enregistré
            raise VoiceProfileError(f"profils de voix non enregistrés : {exc}") from exc

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "accounts": self._data}, ensure_ascii=False, indent=1)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".voice-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            accounts = data.get("accounts", {}) if isinstance(data, dict) else {}
            for account, items in accounts.items():
                if not isinstance(account, str) or not isinstance(items, list):
                    continue
                kept = []
                for p in items[:MAX_PROFILES]:
                    try:
                        kept.append({"name": validate_name(p.get("name")), "settings": validate_settings(p.get("settings"))})
                    except (ValueError, AttributeError):
                        continue
                self._data[account] = kept
        except (OSError, ValueError, AttributeError) as exc:
            emit_event(codes.ORT_9712, logger=log, fichier=str(self.path), erreur=str(exc), repli="profils ignorés")
