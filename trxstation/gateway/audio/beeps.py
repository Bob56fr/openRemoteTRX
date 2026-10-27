# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Bips de fin d'émission produits PAR LA STATION et émis juste avant « PTT off ».

- Roger bip : quand le PROPRIÉTAIRE relâche le PTT lui-même (toggle). Tonalité et motif (1, 2 ou 3 bips) au choix.
- Bip de liaison perdue : quand la station coupe parce que le terminal ne répond plus (battement perdu,
  connexion fermée) ; motif FIXE, trois tons descendants, distinct de tout roger bip. Il prévient les autres
  stations. EXCEPTION ASSUMÉE à « retour RX immédiat si la connexion tombe » (décision de l'utilisateur,
  2026-10-27) : seulement si l'émission est DÉJÀ en cours, jamais une nouvelle prise, durée bornée.

Bornes imposées ici, quels que soient les réglages : 600 ms de son au plus (`MAX_TAIL_S`), niveau ≤ -10 dBFS,
fondus de 5 ms (pas de claquement, donc pas d'éclaboussure de spectre). Aucun bip sur une coupure de sécurité
(TOT, STOP, défaut, CAT perdue, superviseur...) : c'est le PttController qui décide, et un STOP interrompt le
bip net (`stop()` vide le tampon de lecture).

Réglages : `<state_dir>/beeps.json`, modifiables depuis le téléphone (onglet Audio), désactivés par défaut.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import tempfile
from array import array
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .pcm import FRAME_BYTES, FRAME_S, SAMPLE_RATE

log = logging.getLogger(__name__)

MAX_TAIL_S = 0.6
BEEP_MS = 100
GAP_MS = 60
RAMP_MS = 5
LEVEL_DB = -15.0
MAX_LEVEL_DB = -10.0
LEAD_S = 0.06                     # avance d'écriture sur la lecture (le tampon de la carte garde 150 ms au plus)

# tonalité -> tons d'UN bip (Hz, ms) ; « duo » = deux tons montants
TONES: dict[str, tuple[tuple[int, int], ...]] = {
    "600": ((600, BEEP_MS),), "800": ((800, BEEP_MS),), "1000": ((1000, BEEP_MS),), "1500": ((1500, BEEP_MS),),
    "2000": ((2000, BEEP_MS),), "2500": ((2500, BEEP_MS),), "duo": ((1000, 50), (1500, 50)),
}
PATTERNS = (1, 2, 3)
LINK_LOST: tuple[tuple[int, int], ...] = ((1200, 120), (0, 40), (900, 120), (0, 40), (600, 120))
KINDS = ("roger", "link_lost")


def roger_sequence(tone: str, pattern: int) -> list[tuple[int, int]]:
    """Segments (Hz, ms) ; 0 Hz = silence."""
    seq: list[tuple[int, int]] = []
    for i in range(pattern):
        if i:
            seq.append((0, GAP_MS))
        seq.extend(TONES[tone])
    return seq


def sequence_ms(seq) -> int:
    return sum(ms for _, ms in seq)


def render(seq, level_db: float) -> list[bytes]:
    """PCM 16 bits mono 48 kHz en trames de 20 ms, fondus aux bords de chaque ton, borné à MAX_TAIL_S."""
    amp = 32767 * 10 ** (min(level_db, MAX_LEVEL_DB) / 20)
    ramp = int(SAMPLE_RATE * RAMP_MS / 1000)
    samples = array("h")
    for freq, ms in seq:
        n = int(SAMPLE_RATE * ms / 1000)
        if freq <= 0:
            samples.extend([0] * n)
            continue
        step = 2 * math.pi * freq / SAMPLE_RATE
        for i in range(n):
            edge = min(i, n - 1 - i)
            gain = 0.5 - 0.5 * math.cos(math.pi * edge / ramp) if edge < ramp else 1.0
            samples.append(int(amp * gain * math.sin(step * i)))
    samples = samples[:int(SAMPLE_RATE * MAX_TAIL_S)]
    data = samples.tobytes()
    if len(data) % FRAME_BYTES:
        data += bytes(FRAME_BYTES - len(data) % FRAME_BYTES)
    return [data[i:i + FRAME_BYTES] for i in range(0, len(data), FRAME_BYTES)]


@dataclass(frozen=True)
class BeepConfig:
    roger_enabled: bool = False
    roger_tone: str = "1000"
    roger_pattern: int = 1
    link_lost_enabled: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["roger_sequence"] = roger_sequence(self.roger_tone, self.roger_pattern)
        d["link_lost_sequence"] = [list(s) for s in LINK_LOST]
        d["roger_sequence"] = [list(s) for s in d["roger_sequence"]]
        d["tones"], d["patterns"] = list(TONES), list(PATTERNS)
        return d


def validate_changes(changes: dict) -> dict:
    """Changements demandés (téléphone) ; ValueError si une clé ou une valeur est hors liste fermée."""
    out = {}
    for key, value in changes.items():
        if key in ("roger_enabled", "link_lost_enabled"):
            if not isinstance(value, bool):
                raise ValueError(f"{key} : true ou false")
        elif key == "roger_tone":
            if value not in TONES:
                raise ValueError(f"roger_tone : {', '.join(TONES)}")
        elif key == "roger_pattern":
            if isinstance(value, bool) or value not in PATTERNS:
                raise ValueError("roger_pattern : 1, 2 ou 3")
        else:
            raise ValueError(f"réglage inconnu : {key}")
        out[key] = value
    if not out:
        raise ValueError("aucun réglage")
    return out


class BeepStore:
    """Réglages des bips (`beeps.json`) ; fichier absent ou illisible = tout désactivé."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.config = BeepConfig()
        self._listeners: list[Callable[[dict], None]] = []
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.config = replace(BeepConfig(), **validate_changes({k: v for k, v in data.items()
                                                                    if k in BeepConfig.__dataclass_fields__}))
        except (OSError, ValueError, TypeError) as exc:
            log.warning("réglages des bips illisibles (%s) : bips désactivés", exc)
            self.config = BeepConfig()

    def add_listener(self, callback: Callable[[dict], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[dict], None]) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(callback)

    def update(self, changes: dict) -> BeepConfig:
        new = replace(self.config, **validate_changes(changes))
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".beeps-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(asdict(new), fh)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        self.config = new
        for callback in list(self._listeners):
            try:
                callback(new.to_dict())
            except Exception:
                log.exception("écouteur des bips en erreur")
        return new


class TailPlayer:
    """Joue un bip sur la sortie vers le poste, au rythme réel (le tampon de la carte ne garde que 150 ms)."""

    def __init__(self, sink, store: BeepStore, *, gain_db: float = 0.0, sleep=asyncio.sleep,
                 clock: Callable[[], float] | None = None) -> None:
        self.sink, self.store, self.gain_db = sink, store, gain_db
        self._sleep = sleep
        self._clock = clock
        self._stopped = False
        self.played: list[str] = []

    def wanted(self, kind: str) -> bool:
        c = self.store.config
        return c.roger_enabled if kind == "roger" else c.link_lost_enabled if kind == "link_lost" else False

    def frames(self, kind: str) -> list[bytes]:
        c = self.store.config
        seq = LINK_LOST if kind == "link_lost" else roger_sequence(c.roger_tone, c.roger_pattern)
        return render(seq, LEVEL_DB + self.gain_db)

    async def play(self, kind: str) -> None:
        self._stopped = False
        frames = self.frames(kind)
        self.played.append(kind)
        clock = self._clock or asyncio.get_running_loop().time
        start = clock()
        for i, frame in enumerate(frames):
            if self._stopped:
                return
            delay = start + i * FRAME_S - LEAD_S - clock()
            if delay > 0:
                await self._sleep(delay)
                if self._stopped:
                    return
            self.sink.write(frame)
        await self._sleep(LEAD_S + FRAME_S)                 # la carte joue la fin avant « PTT off »

    def stop(self) -> None:
        """Coupure : plus rien n'est écrit et ce qui attendait est jeté."""
        self._stopped = True
        try:
            self.sink.flush()
        except Exception:
            log.exception("vidage du tampon de lecture impossible")
