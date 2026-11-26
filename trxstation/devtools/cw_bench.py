# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Banc du rejeu CW (lot CW-0 de la branche exp/cw) : tableau gigue x pertes, sans réseau ni poste.

    python -m trxstation.devtools.cw_bench [--delay 300] [--wpm 20] [--seeds 5] [--adaptive]

Pour chaque case : écart de timing retrouvé dans le son (p95 et max, ms), séquences incomplètes (élément tronqué
ou perdu), fronts en retard (ré-ancrage) et coupures de bail, sur `--seeds` tirages.
"""
from __future__ import annotations

import argparse

from ..cw import analysis as an
from ..cw import sim
from ..cw.player import CwParams

TEXT = "CQ CQ DE F4XYZ F4XYZ PSE K"


def cell(jitter: float, loss: float, params: CwParams, wpm: float, seeds: int, stall_ms: float = 0.0,
         stalls_per_min: float = 0.0) -> str:
    p95s: list[float] = []
    worst = 0.0
    incomplete = late = cuts = 0
    for seed in range(1, seeds + 1):
        sq = sim.Sequence(0, 1000.0, sim.morse_timeline(TEXT, wpm))
        net = sim.Network(jitter_ms=jitter, loss=loss, seed=seed, stalls_per_min=stalls_per_min,
                          stall_max_ms=stall_ms)
        r = sim.run([sq], net, params)
        rep = an.compare(sq.edges, an.detect_edges(r.audio, r.fs, params.tone_hz, params.level), r.fs)
        late += r.player.late
        cuts += r.player.lease_cuts
        if not rep.complete:
            incomplete += 1
            continue
        p95s.append(rep.p95_ms)
        worst = max(worst, rep.max_ms)
    p95 = max(p95s) if p95s else float("nan")
    return f"{p95:5.2f}/{worst:6.2f} i{incomplete} l{late} c{cuts}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--delay", type=float, default=300.0)
    ap.add_argument("--wpm", type=float, default=20.0)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--adaptive", action="store_true")
    ap.add_argument("--stalls", type=float, default=6.0, help="gels par minute (défaut 6)")
    a = ap.parse_args(argv)
    params = CwParams(delay_ms=a.delay, adaptive=a.adaptive)
    losses = [0.0, 0.05, 0.10, 0.20]
    print(f"rejeu {a.delay:.0f} ms, {a.wpm:.0f} mots/min, {a.seeds} tirages ; case = p95/max ms, "
          "i = incomplètes, l = en retard, c = coupures de bail")
    print("gigue  " + "".join(f"pertes {int(x * 100):>2} %{'':16}" for x in losses))
    for jitter in (0, 50, 100, 150, 200, 300, 400):
        print(f"{jitter:4d}   " + "".join(f"{cell(jitter, x, params, a.wpm, a.seeds):27}" for x in losses))
    print()
    print(f"gels de liaison (4G), {a.stalls:.0f} par minute, gigue 50 ms, pertes 2 % ; durée tirée entre 0 et :")
    for stall in (100, 200, 300, 400, 600, 1000):
        print(f"{stall:4d}   {cell(50, 0.02, params, a.wpm, a.seeds, stall, a.stalls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
