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
TAIL_WAIT_S = 1.2                 # attente maximale d'un bip de fin par le PttController (0,6 s de son + marge)
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


SELCALL_MARGIN_S = 0.6            # trame SELCALL de fin : sa durée + cette marge, au plus (exception étendue, 2026-10-29)


def selcall_frames(code: str, level_dbfs: float, gap_s: float = 0.0, repeat: int = 1) -> tuple[list[bytes], list[int]]:
    """Trame SELCALL (selcall/signal.py) en trames PCM de 20 ms, `repeat` fois séparées de `gap_s` de silence ;
    rend aussi l'indice de la première trame PCM de chaque répétition (progression de l'appel manuel)."""
    import numpy as np                                      # seulement quand le SELCALL sert

    from ...selcall import signal as sg

    one = sg.synthesize(code, rate=SAMPLE_RATE, level_dbfs=min(level_dbfs, -1.0)).astype(np.float64)
    gap = np.zeros(int(round(gap_s * SAMPLE_RATE)))
    parts, marks, pos = [], [], 0
    per = FRAME_BYTES // 2
    for k in range(repeat):
        marks.append(pos // per)
        parts.append(one)
        pos += len(one)
        if k < repeat - 1:
            parts.append(gap)
            pos += len(gap)
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2").tobytes()
    pcm += bytes((-len(pcm)) % FRAME_BYTES)
    return [pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)], marks


class TailPlayer:
    """Joue un bip (ou la trame SELCALL) sur la sortie vers le poste, au rythme réel (le tampon de la carte est court)."""

    def __init__(self, sink, store: BeepStore, *, gain_db: float = 0.0, sleep=asyncio.sleep,
                 clock: Callable[[], float] | None = None) -> None:
        self.sink, self.store, self.gain_db = sink, store, gain_db
        self._sleep = sleep
        self._clock = clock
        self._stopped = False
        self.played: list[str] = []
        # SELCALL (gateway/main) : code à émettre en fin d'émission À LA PLACE du roger bip, ou None (fonction absente,
        # désactivée, ou option « send_on_tx_end » coupée) ; niveau de la trame (dBFS, sous le seuil d'ALC).
        self.selcall_code: Callable[[], str | None] = lambda: None
        self.selcall_level_db = -6.0

    def wanted(self, kind: str) -> bool:
        c = self.store.config
        if kind == "selcall":
            return self.selcall_code() is not None
        return c.roger_enabled if kind == "roger" else c.link_lost_enabled if kind == "link_lost" else False

    def max_wait(self, kind: str) -> float:
        """Attente maximale du PttController pour ce son de fin (au-delà : coupure quoi qu'il arrive)."""
        if kind == "selcall":
            from ...selcall import protocol as sp
            code = self.selcall_code()
            return (sp.duration_s(code) if code else 0.0) + SELCALL_MARGIN_S + getattr(self.sink, "PREFILL_S", 0.0)
        return TAIL_WAIT_S

    def frames(self, kind: str) -> list[bytes]:
        c = self.store.config
        if kind == "selcall":
            return selcall_frames(self.selcall_code(), self.selcall_level_db + self.gain_db)[0]
        seq = LINK_LOST if kind == "link_lost" else roger_sequence(c.roger_tone, c.roger_pattern)
        return render(seq, LEVEL_DB + self.gain_db)

    async def play(self, kind: str) -> None:
        self._stopped = False
        frames = self.frames(kind)
        self.played.append(kind)
        await self._play_frames(frames)

    async def play_selcall_call(self, code: str, repeat: int, gap_s: float,
                                progress: Callable[[int, int], None] = lambda k, n: None) -> None:
        """Appel manuel : la trame `repeat` fois séparées de `gap_s` (silence écrit, pas de trou compté), progression
        annoncée au début de chaque trame. Le PttController la lance en émission confirmée, micro du client fermé."""
        self._stopped = False
        frames, marks = selcall_frames(code, self.selcall_level_db + self.gain_db, gap_s, repeat)
        self.played.append("selcall_call")
        await self._play_frames(frames, {m: k + 1 for k, m in enumerate(marks)}, lambda k: progress(k, repeat))

    async def _play_frames(self, frames: list[bytes], marks: dict[int, int] | None = None,
                           on_mark: Callable[[int], None] = lambda k: None) -> None:
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
            if marks and i in marks:
                on_mark(marks[i])
            self.sink.write(frame)
        # la carte joue la fin (avance d'écriture + réserve contre la gigue de la sortie) avant « PTT off »
        await self._sleep(LEAD_S + FRAME_S + getattr(self.sink, "PREFILL_S", 0.0))

    def stop(self) -> None:
        """Coupure : plus rien n'est écrit et ce qui attendait est jeté."""
        self._stopped = True
        try:
            self.sink.flush()
        except Exception:
            log.exception("vidage du tampon de lecture impossible")
