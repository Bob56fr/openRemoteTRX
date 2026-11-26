# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Ordonnanceur du rejeu CW (cahier § 5.3) : paquets du client -> fronts joués à l'échantillon près.

- Ancre d'une séquence = arrivée du premier paquet + rejeu (`delay_ms`) ; un front de ts se joue à ancre + ts
  (l'ancre est ramenée de façon que le PREMIER front connu se joue à arrivée + rejeu).
- Front de fermeture (début de tonalité) en retard : ré-ancrage, la suite est décalée d'autant, compté `late`.
  Front d'ouverture (fin de tonalité) en retard : joué tout de suite, compté `late` (le bail borne l'allongement).
- BAIL : clé fermée, la tonalité ne dépasse jamais ancre + bail + `lease_grace_ms` ; au-delà, fermeture adoucie,
  séquence abandonnée, défaut `lease_expired`. Appui continu > `max_keydown_ms` : même chose, `keydown_too_long`.
- Fin de séquence : clé ouverte, plus rien en attente, `seq_gap_ms` après le dernier front joué.
- Tout se décide dans `render` sur la position en échantillons, jamais par minuterie.

Aucun effet hors de ce calcul : la passerelle (lot CW-1) lit `events` et `silent`, puis décide « T 0 ».
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

import numpy as np

from ..gateway.audio.pcm import SAMPLE_RATE
from .jitter import JitterMeter
from .protocol import CwPacket
from .tone import DEFAULT_LEVEL, ToneRenderer

DELAY_MIN_MS = 150.0
DELAY_MAX_MS = 500.0
KEYDOWN_CEILING_MS = 5000.0          # plafond de `max_keydown_ms` (§ 3)


@dataclass(frozen=True)
class CwParams:
    tone_hz: float = 700.0
    edge_ms: float = 5.0
    level: float = DEFAULT_LEVEL
    delay_ms: float = 300.0                  # rejeu fixe, ou valeur de départ du rejeu adaptatif
    adaptive: bool = False
    delay_min_ms: float = DELAY_MIN_MS
    delay_max_ms: float = DELAY_MAX_MS
    lease_grace_ms: float = 60.0
    max_keydown_ms: float = 2000.0
    seq_gap_ms: float = 1500.0

    def check(self) -> None:
        if not DELAY_MIN_MS <= self.delay_min_ms <= self.delay_max_ms <= DELAY_MAX_MS:
            raise ValueError("bornes du rejeu invalides (150 à 500 ms)")
        if not self.delay_min_ms <= self.delay_ms <= self.delay_max_ms:
            raise ValueError("rejeu hors de ses bornes")
        if not 20.0 <= self.lease_grace_ms <= 200.0:
            raise ValueError("marge du bail hors limites (20 à 200 ms)")
        if not 100.0 <= self.max_keydown_ms <= KEYDOWN_CEILING_MS:
            raise ValueError("appui continu maximal hors limites (100 à 5000 ms)")
        if not 500.0 <= self.seq_gap_ms <= 10000.0:
            raise ValueError("silence de fin de séquence hors limites (500 à 10000 ms)")


@dataclass(frozen=True)
class PlayedEdge:
    seq: int
    id: int
    down: bool
    sample: int
    late: bool
    reason: str = ""                         # "" = front du client ; sinon motif de la coupure


class CwPlayer:
    def __init__(self, params: CwParams | None = None, sample_rate: int = SAMPLE_RATE, record: bool = False) -> None:
        self.p = params or CwParams()
        self.p.check()
        self.fs = sample_rate
        self.tone = ToneRenderer(self.p.tone_hz, self.p.edge_ms, self.p.level, sample_rate)
        self.jitter = JitterMeter()
        self.record = record
        self.played: list[PlayedEdge] = []
        self.events: list[dict] = []             # cw_fault / seq_end, à vider par l'appelant
        self.seq: int | None = None
        self.closed_seq = -1                     # séquences terminées ou abandonnées : paquets ignorés
        self.active = False
        self.faulted = False
        # Variante V2 (« hang », cahier § 5.4) : PTT relâché par la passerelle ; le rendu avance (silence) sans jouer
        # aucun front, jusqu'à la reprise de l'émission ; le premier front de fermeture est alors ré-ancré tout de suite.
        self.holding = False
        self._resuming = False
        self.hang_reanchors = 0
        # compteurs de la session
        self.packets = 0
        self.ignored = 0
        self.duplicates = 0
        self.late = 0
        self.lease_cuts = 0
        self.keydown_cuts = 0
        self.max_timing_err_ms = 0.0
        self._new_seq_state()

    # --- état d'une séquence ----------------------------------------------------------------------------------
    def _new_seq_state(self) -> None:
        self.anchor = 0.0                        # en échantillons (flottant)
        self.lease = 0.0                         # ms, horloge du client
        self.delay_used_ms = self.p.delay_ms
        self._seen: set[int] = set()
        self._pending: list[tuple[float, int, bool]] = []
        self.key_down = False
        self._down_since = 0
        self._last_edge_sample = 0
        self._last_ts = -math.inf
        self._seq_late = 0

    def _ms_to_samples(self, ms: float) -> float:
        return ms * self.fs / 1000.0

    def _at(self, ts: float) -> int:
        return round(self.anchor + self._ms_to_samples(ts))

    @property
    def pos(self) -> int:
        return self.tone.pos

    @property
    def state(self) -> str:
        if self.active:
            return "playing"
        return "fault" if self.faulted else "idle"

    @property
    def silent(self) -> bool:
        """Plus aucune tonalité produite (fermeture adoucie terminée) : « T 0 » possible sans clic."""
        return not self.key_down and self.tone.silent

    @property
    def buffer_ms(self) -> float:
        """Avance couverte par le bail sur le rejeu (négatif = le bail est dépassé)."""
        if not self.active:
            return 0.0
        return (self.anchor + self._ms_to_samples(self.lease) - self.pos) * 1000.0 / self.fs

    @property
    def idle_ms(self) -> float:
        """Silence depuis le dernier front joué, clé ouverte et rien en attente (0 sinon) : décide le relâché V2."""
        if self.key_down or self._pending:
            return 0.0
        return (self.pos - self._last_edge_sample) * 1000.0 / self.fs

    @property
    def wants_key(self) -> bool:
        """Un front de fermeture attend d'être joué (V2 : l'émission doit être reprise d'abord)."""
        return self.active and any(down for _ts, _id, down in self._pending)

    def hold(self) -> None:
        """V2 : PTT relâché ; plus aucun front joué (clé ouverte), le rendu ne produit que du silence."""
        self._close_key("hold")
        self.holding = True

    def resume(self) -> None:
        """V2 : émission reprise ; le front de fermeture en attente se joue au prochain rendu, sans compter un retard."""
        self.holding = False
        self._resuming = True

    def next_delay_ms(self) -> float:
        if not self.p.adaptive:
            return self.p.delay_ms
        return self.jitter.adaptive_delay(self.p.delay_min_ms, self.p.delay_max_ms, self.p.delay_ms)

    # --- réception ----------------------------------------------------------------------------------------------
    def receive(self, pkt: CwPacket, arrival_s: float) -> None:
        """Paquet arrivé à `arrival_s` (secondes sur l'horloge du rendu : position / fréquence d'échantillonnage)."""
        self.packets += 1
        arrival = arrival_s * self.fs
        if pkt.seq <= self.closed_seq or (self.seq is not None and pkt.seq < self.seq):
            self.ignored += 1
            return
        if not self.active or pkt.seq != self.seq:
            first = next((e for e in pkt.edges if e.down), None)
            if first is None:
                self.ignored += 1                # rien à jouer : la séquence commence par un front de fermeture
                return
            if self.active:
                # Le client ouvre une séquence après `seq_gap_ms` de silence À SON HEURE, la station ne l'a pas encore
                # constaté dans son rejeu (retardé) : séquence finie si rien ne joue ni n'attend, chevauchement sinon.
                if self.key_down or self._pending:
                    self._abandon("seq_overlap")
                else:
                    self._finish("end")
            self.seq = pkt.seq
            self.active = True
            self.faulted = False
            self._new_seq_state()
            self.jitter.start_sequence()
            self.delay_used_ms = self.next_delay_ms()
            self.anchor = arrival + self._ms_to_samples(self.delay_used_ms - first.ts)
            self._last_ts = first.ts - 1e-9      # les fronts d'ouverture d'avant le premier sont inutiles
        self.jitter.packet(arrival_s * 1000.0, pkt.lease)
        for e in pkt.edges:
            if e.id in self._seen:
                self.duplicates += 1
                continue
            self._seen.add(e.id)
            if e.ts < self._last_ts:
                self.ignored += 1                # plus ancien que ce qui a déjà été joué
                continue
            bisect.insort(self._pending, (e.ts, e.id, e.down))
        self.lease = max(self.lease, pkt.lease)

    # --- coupures -------------------------------------------------------------------------------------------------
    def _close_key(self, reason: str) -> None:
        if self.key_down:
            self.tone.set_key(self.pos, False)
            self.key_down = False
            if self.record and self.seq is not None:
                self.played.append(PlayedEdge(self.seq, -1, False, self.pos, False, reason))

    def _finish(self, reason: str) -> None:
        stats = self.jitter.end_sequence()
        self.events.append({"type": "seq_end", "seq": self.seq, "reason": reason, "late": self._seq_late,
                            "delay_ms": self.delay_used_ms, **stats})
        self.closed_seq = max(self.closed_seq, self.seq if self.seq is not None else -1)
        self.active = False
        self._pending = []

    def _abandon(self, reason: str) -> None:
        self._close_key(reason)
        self.events.append({"type": "cw_fault", "seq": self.seq, "reason": reason})
        self.faulted = True
        self._finish(reason)

    def stop(self, reason: str = "stop") -> None:
        """Désarmement, STOP, connexion perdue, toute coupure de la passerelle : tonalité coupée tout de suite."""
        if self.active:
            self._abandon(reason)
        else:
            self._close_key(reason)
            self.tone.set_key(self.pos, False)

    # --- rendu ------------------------------------------------------------------------------------------------------
    def _next_event(self, cur: int) -> tuple[int, str]:
        best = (math.inf, "")
        if not self.active:
            return best  # type: ignore[return-value]
        if self.holding:                         # V2 : rien ne se joue ; fin de séquence seulement sans front en attente
            if self._pending:
                return best  # type: ignore[return-value]
            gap_end = self._last_edge_sample + round(self._ms_to_samples(self.p.seq_gap_ms))
            return (max(gap_end, cur), "gap")  # type: ignore[return-value]
        if self._pending:
            ts, _id, down = self._pending[0]
            s = self._at(ts)
            if s <= cur:
                return cur, "edge"
            best = (s, "edge")
        if self.key_down:
            lease_end = round(self.anchor + self._ms_to_samples(self.lease + self.p.lease_grace_ms))
            if lease_end < best[0]:
                best = (max(lease_end, cur), "lease")
            keydown_end = self._down_since + round(self._ms_to_samples(self.p.max_keydown_ms))
            if keydown_end < best[0]:
                best = (max(keydown_end, cur), "keydown")
        elif not self._pending:
            gap_end = self._last_edge_sample + round(self._ms_to_samples(self.p.seq_gap_ms))
            best = (max(gap_end, cur), "gap")
        return best  # type: ignore[return-value]

    def _play_edge(self, cur: int) -> None:
        ts, eid, down = self._pending.pop(0)
        exact = self.anchor + self._ms_to_samples(ts)
        late = round(exact) < cur
        resumed = self._resuming and down        # V2 : premier front après la reprise du PTT
        if resumed:
            self._resuming = False
        if late and down and not self.key_down:
            self.anchor += cur - round(exact)    # ré-ancrage : la suite est décalée d'autant
        if resumed and late:
            self.hang_reanchors += 1             # décalage dû à la reprise du PTT, pas un retard du réseau
        elif late and down != self.key_down:
            self.late += 1
            self._seq_late += 1
        elif not late:
            self.max_timing_err_ms = max(self.max_timing_err_ms, abs(cur - exact) * 1000.0 / self.fs)
        self._last_ts = ts
        if down == self.key_down:
            return                               # confirmation d'un état déjà joué
        self.tone.set_key(cur, down)
        self.key_down = down
        self._last_edge_sample = cur
        if down:
            self._down_since = cur
        if self.record and self.seq is not None:
            self.played.append(PlayedEdge(self.seq, eid, down, cur, late))

    def render(self, n: int) -> np.ndarray:
        """`n` échantillons flottants ; tous les fronts et coupures tombent à leur échantillon exact."""
        parts: list[np.ndarray] = []
        end = self.pos + n
        guard = 0
        while self.pos < end:
            cur = self.pos
            when, kind = self._next_event(cur)
            if when > cur:
                parts.append(self.tone.render(int(min(when, end)) - cur))
                continue
            guard += 1
            if guard > 10000:                    # jamais atteint : aucune boucle sans fin dans le rendu
                self.stop("internal")
                parts.append(self.tone.render(end - cur))
                break
            if kind == "edge":
                self._play_edge(cur)
            elif kind == "lease":
                self.lease_cuts += 1
                self._abandon("lease_expired")
            elif kind == "keydown":
                self.keydown_cuts += 1
                self._abandon("keydown_too_long")
            elif kind == "gap":
                self._finish("end")
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float64)

    def drain_events(self) -> list[dict]:
        out, self.events = self.events, []
        return out
