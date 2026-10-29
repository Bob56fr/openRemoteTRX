# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Décodeur SELCALL en flux (cahier des charges § 4), sur l'audio reçu ramené à 8 kHz mono.

Analyse glissante : fenêtre de Hann de 128 ms (1024 points), pas de 32 ms, plancher de bruit = médiane des bins de
300 à 2 800 Hz. Étapes :
1. PILOTE : pic entre F0 - 350 et F0 + 350 Hz, au moins 12 dB au-dessus du plancher sur 80 % des trames de 800 ms,
   fréquence stable à ±5 Hz autour de sa médiane (la voix et les sifflements glissants sont rejetés). Δ = médiane - F0.
2. FIN DU PILOTE : le pic du pilote disparaît et un ton de la grille (chiffres, R, corrigés de Δ) le domine.
3. SYMBOLES : cases de 300 ms calées sur cette fin ; vote majoritaire sur les trames centrales ; symbole rejeté si
   l'écart avec le second candidat est < 6 dB ou s'il est sous le seuil de présence. Une case sans ton = fin de trame.
4. VALIDATION : R remplacés, contrôle juste, 3 à 8 chiffres (`protocol.unpack`).

Aucune décision de squelch ici : le décodeur rend des trames (valides ou non) ; la machine d'états est au lot 2.
"""
from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field

import numpy as np

from . import protocol as p

RATE = 8000
WIN = 1024                      # 128 ms
HOP = 256                       # 32 ms
BIN_HZ = RATE / WIN
FLOOR_LO_HZ, FLOOR_HI_HZ = 300.0, 2800.0
PILOT_SEARCH_HZ = 350.0
PILOT_SNR_DB = 12.0             # pic du pilote au-dessus du plancher
PILOT_SPAN_S = 0.8              # durée observée pour valider le pilote
PILOT_FILL = 0.8                # part des trames où le pilote doit être vu
PILOT_STABLE_HZ = 5.0
PILOT_MAX_S = 2.5               # pilote verrouillé sans chiffres au-delà : porteuse fixe, abandon
TONE_TOL_HZ = 40.0
PRESENCE_DB = 14.0              # un ton de la grille au-dessus du plancher. Dans le bruit seul, le plus fort des ~120 bins
                                # regardés (11 symboles × ±40 Hz) dépasse souvent 10 dB : 14 dB ne l'est presque jamais,
                                # et un ton à 0 dB de SNR dans 2,4 kHz donne environ 23 dB par bin
SYMBOL_MARGIN_DB = 6.0          # meilleur candidat contre le second
CELL_MARGIN_S = 0.056           # trames centrales d'une case : fenêtre presque entière dans la case
MAX_CELLS = p.CODE_MAX + 1
PRE_DETECT_S = 0.15            # pré-détecteur du filtrage : ton stable depuis 150 ms


@dataclass
class Frame:
    """Trame décodée : `code` si elle est valide, sinon `reason`. Temps en secondes depuis le début du flux."""
    valid: bool
    code: str | None
    symbols: list[str]
    delta_hz: float
    snr_db: float
    start_s: float
    end_s: float
    reason: str = ""


@dataclass
class _Locked:
    pilot_hz: float
    delta_hz: float
    snr_db: float
    start_s: float
    since_s: float
    boundary_s: float | None = None
    frames: list[tuple[float, np.ndarray]] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    cell: int = 0
    quiet_since: float | None = None


class SelcallDecoder:
    def __init__(self) -> None:
        self._buf = np.zeros(0, dtype=np.float64)
        self._consumed = 0                       # échantillons déjà retirés du tampon
        self._window = np.hanning(WIN)
        freqs = np.fft.rfftfreq(WIN, 1 / RATE)
        self._floor_bins = (freqs >= FLOOR_LO_HZ) & (freqs <= FLOOR_HI_HZ)
        self._pilot_lo = int(math.floor((p.F0_HZ - PILOT_SEARCH_HZ) / BIN_HZ))
        self._pilot_hi = int(math.ceil((p.F0_HZ + PILOT_SEARCH_HZ) / BIN_HZ))
        self._recent: deque[tuple[float, float | None, float, float]] = deque(maxlen=int(round(PILOT_SPAN_S * RATE / HOP)))
        self._locked: _Locked | None = None
        self.rejected = 0                         # trames invalides (compteur pour la supervision)

    # ------------------------------------------------------------------ pour le squelch (lot 2)

    @property
    def busy(self) -> bool:
        """Pilote verrouillé : une trame est en cours."""
        return self._locked is not None

    @property
    def busy_since(self) -> float | None:
        return self._locked.start_s if self._locked is not None else None

    def tone_since(self, min_s: float = PRE_DETECT_S) -> float | None:
        """Pré-détecteur (§ 6) : début d'un ton stable (±5 Hz) dans la zone du pilote, présent depuis `min_s` au moins ;
        None sinon. Le début rendu est celui de la fenêtre d'analyse de la première trame du ton (prudent : un peu tôt)."""
        run: list[tuple[float, float]] = []
        for t, hz, _db, _snr in reversed(self._recent):
            if hz is None or (run and abs(hz - run[0][1]) > PILOT_STABLE_HZ):
                break
            run.append((t, hz))
        if not run or run[0][0] - run[-1][0] < min_s:
            return None
        return run[-1][0] - WIN / 2 / RATE

    def reset(self) -> None:
        """Oublie toute trame en cours (début d'une émission : le décodeur est suspendu)."""
        self._reset()

    # ------------------------------------------------------------------ entrée

    def feed(self, samples: np.ndarray) -> list[Frame]:
        """Échantillons à 8 kHz (-1..1) ; rend les trames terminées pendant ce morceau."""
        self._buf = np.concatenate([self._buf, np.asarray(samples, dtype=np.float64)])
        out: list[Frame] = []
        while len(self._buf) >= WIN:
            center = (self._consumed + WIN / 2) / RATE
            power = np.abs(np.fft.rfft(self._buf[:WIN] * self._window)) ** 2
            frame = self._analyse(center, power)
            if frame is not None:
                out.append(frame)
            self._buf = self._buf[HOP:]
            self._consumed += HOP
        return out

    def flush(self) -> list[Frame]:
        """Fin du flux (essais) : un peu de silence pour terminer une trame en cours."""
        return self.feed(np.zeros(int(0.8 * RATE)))

    # ------------------------------------------------------------------ analyse d'une trame d'analyse

    def _analyse(self, t: float, power: np.ndarray) -> Frame | None:
        floor = float(np.median(power[self._floor_bins])) + 1e-20
        if self._locked is None:
            self._search(t, power, floor)
            return None
        return self._follow(t, power, floor)

    def _peak(self, power: np.ndarray, lo: int, hi: int) -> tuple[float, int]:
        """Fréquence interpolée (parabole sur le logarithme) et bin du pic entre lo et hi."""
        k = lo + int(np.argmax(power[lo:hi + 1]))
        if 0 < k < len(power) - 1:
            a, b, c = (math.log(power[k - 1] + 1e-30), math.log(power[k] + 1e-30), math.log(power[k + 1] + 1e-30))
            den = a - 2 * b + c
            delta = 0.5 * (a - c) / den if den < 0 else 0.0
        else:
            delta = 0.0
        return (k + max(-0.5, min(0.5, delta))) * BIN_HZ, k

    def _band_db(self, power: np.ndarray, hz: float, floor: float, tol_hz: float = TONE_TOL_HZ) -> float:
        lo = max(0, int(math.floor((hz - tol_hz) / BIN_HZ)))
        hi = min(len(power) - 1, int(math.ceil((hz + tol_hz) / BIN_HZ)))
        return 10 * math.log10(float(power[lo:hi + 1].max()) / floor + 1e-20)

    def _snr_2400(self, power: np.ndarray, k: int, floor: float) -> float:
        """SNR du ton dans 2,4 kHz : puissance du ton contre bruit moyen (médiane / ln 2) sur 2,4 kHz."""
        mean_noise = floor / math.log(2)
        tone = float(power[max(0, k - 3):k + 4].sum()) - 7 * mean_noise
        return 10 * math.log10(max(tone, 1e-20) / (mean_noise * 2400 / BIN_HZ))

    def _search(self, t: float, power: np.ndarray, floor: float) -> None:
        hz, k = self._peak(power, self._pilot_lo, self._pilot_hi)
        db = 10 * math.log10(float(power[k]) / floor + 1e-20)
        self._recent.append((t, hz if db >= PILOT_SNR_DB else None, db, self._snr_2400(power, k, floor)))
        if len(self._recent) < self._recent.maxlen:
            return
        seen = [(f, s) for _, f, _, s in self._recent if f is not None]
        if len(seen) < PILOT_FILL * len(self._recent):
            return
        med = float(np.median([f for f, _ in seen]))
        stable = [s for f, s in seen if abs(f - med) <= PILOT_STABLE_HZ]
        if len(stable) < PILOT_FILL * len(self._recent) or abs(med - p.F0_HZ) > PILOT_SEARCH_HZ:
            return
        start = self._recent[0][0] - WIN / 2 / RATE
        self._locked = _Locked(pilot_hz=med, delta_hz=med - p.F0_HZ, snr_db=float(np.median(stable)), start_s=start, since_s=t)

    def _grid_db(self, power: np.ndarray, floor: float, delta: float) -> np.ndarray:
        return np.array([self._band_db(power, p.symbol_hz(s, delta), floor) for s in p.GRID])

    def _follow(self, t: float, power: np.ndarray, floor: float) -> Frame | None:
        lk = self._locked
        grid = self._grid_db(power, floor, lk.delta_hz)
        if lk.boundary_s is None:
            pilot_db = self._band_db(power, lk.pilot_hz, floor, tol_hz=2 * PILOT_STABLE_HZ)
            if grid.max() >= PRESENCE_DB and grid.max() > pilot_db:
                lk.boundary_s = t - HOP / 2 / RATE            # premier instant où la grille domine : fin du pilote
            elif pilot_db < PILOT_SNR_DB:
                return self._end("pilote sans chiffres", t)
            elif t - lk.since_s > PILOT_MAX_S:
                return self._end("porteuse fixe sans chiffres", t)
            else:
                return None
        lk.frames.append((t, grid))
        cell_start = lk.boundary_s + lk.cell * p.SYMBOL_S
        cell_end = cell_start + p.SYMBOL_S
        if t < cell_end + CELL_MARGIN_S:
            return None
        central = [g for c, g in lk.frames if cell_start + CELL_MARGIN_S <= c <= cell_end - CELL_MARGIN_S]
        lk.frames = [(c, g) for c, g in lk.frames if c > cell_end - CELL_MARGIN_S]
        lk.cell += 1
        symbol, _present = self._vote(central)
        if symbol is None:
            # Case sans ton NET de la grille (silence, bruit ou voix qui suit la trame) : fin de trame (§ 4.3 : « aucun
            # ton de la grille »). Le contrôle et la longueur valident ce qui a été reçu ; un symbole perdu en cours de
            # trame donne une trame trop courte, rejetée par le contrôle dans 9 cas sur 10, et le squelch ne s'ouvre
            # de toute façon que sur le code armé.
            return self._finish(cell_start)
        lk.symbols.append(symbol)
        if len(lk.symbols) > MAX_CELLS:
            return self._end("trame trop longue", cell_end)
        return None

    def _vote(self, central: list[np.ndarray]) -> tuple[str | None, bool]:
        """(symbole, ton présent) : vote majoritaire des trames centrales nettes."""
        if not central:
            return None, False
        present = [g for g in central if g.max() >= PRESENCE_DB]
        if len(present) * 2 < len(central):
            return None, False
        votes: Counter[int] = Counter()
        for g in present:
            order = np.argsort(g)
            best, second = g[order[-1]], g[order[-2]]
            if best - second >= SYMBOL_MARGIN_DB:
                votes[int(order[-1])] += 1
        if not votes:
            return None, True
        idx, count = votes.most_common(1)[0]
        if count * 2 <= len(central):
            return None, True
        return p.GRID[idx], True

    def _finish(self, end_s: float) -> Frame:
        lk = self._locked
        code = p.unpack(lk.symbols)
        frame = Frame(valid=code is not None, code=code, symbols=list(lk.symbols), delta_hz=round(lk.delta_hz, 1),
                      snr_db=round(lk.snr_db, 1), start_s=round(lk.start_s, 3), end_s=round(end_s, 3),
                      reason="" if code is not None else "contrôle faux ou longueur invalide")
        self._reset()
        if not frame.valid:
            self.rejected += 1
        return frame

    def _end(self, reason: str, end_s: float) -> Frame:
        lk = self._locked
        frame = Frame(valid=False, code=None, symbols=list(lk.symbols), delta_hz=round(lk.delta_hz, 1),
                      snr_db=round(lk.snr_db, 1), start_s=round(lk.start_s, 3), end_s=round(end_s, 3), reason=reason)
        self._reset()
        self.rejected += 1
        return frame

    def _reset(self) -> None:
        self._locked = None
        self._recent.clear()


def decode(samples: np.ndarray) -> list[Frame]:
    """Décodage hors ligne (essais) : tout le signal, puis un peu de silence."""
    dec = SelcallDecoder()
    return dec.feed(samples) + dec.flush()
