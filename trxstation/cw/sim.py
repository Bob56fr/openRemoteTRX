# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Banc de simulation du canal `cw` (lot CW-0) : manipulateur, client, réseau, rendu par blocs de 20 ms.

Tout est déterministe (graine) : le même scénario rejoue le même son. Le client suit le cahier § 5.1 :
paquet à chaque front et toutes les 20 ms pendant la séquence (clé fermée OU ouverte : constat du banc, le
front d'ouverture doit être répété avant que le bail n'expire), puis toutes les 200 ms en silence armé ; chaque
paquet porte les fronts des 500 dernières ms (32 au plus) et le bail = heure d'envoi du client.
Réseau : gigue uniforme (réordonnancement compris), pertes, coupures (perdues ou retenues) et gels aléatoires
façon 4G (paquets retenus puis livrés en rafale : le cas difficile, une gigue uniforme est rattrapée par la
redondance de la fenêtre).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import numpy as np

from ..gateway.audio.pcm import FRAME_SAMPLES, SAMPLE_RATE
from .player import CwParams, CwPlayer
from .protocol import CwPacket, parse_packet

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....", "I": "..",
    "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.", "/": "-..-.", "?": "..--..", "=": "-...-", ".": ".-.-.-",
}

WINDOW_MS = 500.0
MAX_WINDOW = 32
EVERY_MS = 20.0
SEQ_GAP_MS = 1500.0
SILENCE_EVERY_MS = 200.0


def morse_timeline(text: str, wpm: float = 20.0, start_ms: float = 0.0) -> list[tuple[float, bool]]:
    """Fronts (ts ms, clé fermée) d'un texte à `wpm` mots/min (PARIS : point = 1200 / wpm ms)."""
    dot = 1200.0 / wpm
    t = start_ms
    edges: list[tuple[float, bool]] = []
    for w, word in enumerate(text.upper().split()):
        if w:
            t += 4 * dot                         # 7 points entre mots (3 déjà comptés après la lettre)
        for c, char in enumerate(word):
            if c:
                t += 2 * dot                     # 3 points entre lettres (1 déjà compté après l'élément)
            for symbol in MORSE[char]:
                edges.append((t, True))
                t += dot if symbol == "." else 3 * dot
                edges.append((t, False))
                t += dot
    return edges


@dataclass
class Sequence:
    seq: int
    start_ms: float                              # heure absolue (client) du ts 0 de la séquence
    edges: list[tuple[float, bool]]              # ts relatifs à la séquence
    tail_ms: float = 2000.0                      # paquets envoyés après le dernier front


@dataclass
class Sent:
    send_ms: float                               # heure absolue (client) d'envoi
    msg: dict


def client_packets(sequences: list[Sequence]) -> list[Sent]:
    out: list[Sent] = []
    next_id = 1
    for sq in sequences:
        ids = list(range(next_id, next_id + len(sq.edges)))
        next_id += len(sq.edges)
        last = sq.edges[-1][0]
        end = last + sq.tail_ms
        busy_end = min(end, last + SEQ_GAP_MS)  # séquence en cours : toutes les 20 ms, clé fermée ou ouverte
        times: set[float] = {ts for ts, _ in sq.edges}
        t = sq.edges[0][0] + EVERY_MS
        while t < busy_end:
            times.add(round(t, 6))
            t += EVERY_MS
        t = busy_end + SILENCE_EVERY_MS
        while t <= end:
            times.add(round(t, 6))
            t += SILENCE_EVERY_MS
        for t in sorted(times):
            window = [[ids[i], 1 if d else 0, ts] for i, (ts, d) in enumerate(sq.edges) if t - WINDOW_MS <= ts <= t]
            out.append(Sent(sq.start_ms + t, {"type": "cw", "seq": sq.seq, "edges": window[-MAX_WINDOW:],
                                                "lease": t}))
    return out


@dataclass
class Network:
    base_ms: float = 40.0
    jitter_ms: float = 0.0                       # gigue uniforme 0..jitter_ms (réordonnancement compris)
    loss: float = 0.0                            # probabilité de perte de chaque paquet
    cuts: list[tuple[float, float]] = field(default_factory=list)   # (début, fin) ms client : liaison coupée
    hold: bool = False                           # coupure qui RETIENT les paquets (livrés en rafale à la fin)
    stalls_per_min: float = 0.0                  # gels aléatoires (4G) : paquets retenus puis livrés en rafale
    stall_max_ms: float = 0.0                    # durée d'un gel tirée entre 0 et stall_max_ms
    seed: int = 1

    def _stalls(self, until_ms: float) -> list[tuple[float, float]]:
        if self.stalls_per_min <= 0 or self.stall_max_ms <= 0:
            return []
        rng = random.Random(self.seed + 1_000_003)
        out: list[tuple[float, float]] = []
        t = 0.0
        while True:
            t += rng.expovariate(self.stalls_per_min / 60000.0)
            if t > until_ms:
                return out
            d = rng.uniform(0.0, self.stall_max_ms)
            out.append((t, t + d))
            t += d

    def deliver(self, sent: list[Sent]) -> list[tuple[float, dict]]:
        rng = random.Random(self.seed)
        out: list[tuple[float, dict]] = []
        stalls = self._stalls(max((s.send_ms for s in sent), default=0.0) + 1000.0)
        for s in sent:
            delay = self.base_ms + rng.uniform(0.0, self.jitter_ms)
            lost = rng.random() < self.loss
            stall = next(((a, b) for a, b in stalls if a <= s.send_ms < b), None)
            if stall is not None:
                if not lost:
                    out.append((stall[1] + delay, s.msg))
                continue
            cut = next(((a, b) for a, b in self.cuts if a <= s.send_ms < b), None)
            if cut is not None:
                if not self.hold:
                    continue
                out.append((cut[1] + delay, s.msg))
                continue
            if not lost:
                out.append((s.send_ms + delay, s.msg))
        out.sort(key=lambda x: x[0])
        return out


@dataclass
class SimResult:
    audio: np.ndarray
    player: CwPlayer
    events: list[dict]
    sequences: list[Sequence]
    arrivals: list[tuple[float, dict]]
    fs: int = SAMPLE_RATE


def run(sequences: list[Sequence], network: Network | None = None, params: CwParams | None = None,
        extra_ms: float = 2500.0, stop_at_ms: float | None = None, fs: int = SAMPLE_RATE) -> SimResult:
    """Rejoue le scénario bloc par bloc ; les paquets arrivés avant un bloc sont reçus avant son rendu."""
    network = network or Network()
    player = CwPlayer(params, fs, record=True)
    arrivals = network.deliver(client_packets(sequences))
    end_ms = max(sq.start_ms + sq.edges[-1][0] + sq.tail_ms for sq in sequences) + extra_ms
    blocks: list[np.ndarray] = []
    events: list[dict] = []
    k = 0
    while player.pos * 1000.0 / fs < end_ms:
        now_ms = player.pos * 1000.0 / fs
        if stop_at_ms is not None and now_ms >= stop_at_ms and player.active:
            player.stop("stop")
        while k < len(arrivals) and arrivals[k][0] <= now_ms:
            pkt: CwPacket = parse_packet(arrivals[k][1])
            player.receive(pkt, arrivals[k][0] / 1000.0)
            k += 1
        blocks.append(player.render(FRAME_SAMPLES))
        events.extend(player.drain_events())
    return SimResult(np.concatenate(blocks), player, events, sequences, arrivals, fs)
