# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mesure du son CW recréé par la station factice (WAV en cours d'écriture : données lues après l'en-tête de 44 octets).

Durées des éléments et des espaces, comparées à la vitesse réglée (20 wpm : point 60 ms, trait 180 ms, espace 60 ms),
plus grand saut d'un échantillon à l'autre (clics) et énergie hors de ±150 Hz autour de la tonalité.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from trxstation.cw import analysis  # noqa: E402

FS = 48_000
raw = Path(sys.argv[1]).read_bytes()[44:]
audio = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(float) / 32768.0
print(f"{audio.size / FS:.2f} s de son, crête {np.abs(audio).max():.3f}")
peak = np.abs(audio).max()
edges = [(t / FS, d) for t, d in analysis.detect_edges(audio, FS, 700.0, peak)]  # échantillons -> s
print(f"{len(edges)} fronts")
dit = 1200 / 20
groups: list[list[str]] = [[]]
last = None
for t, down in edges:
    if last is not None:
        ms = (t - last[0]) * 1000
        if last[1]:
            kind = "point" if ms < 2 * dit else "trait"
            groups[-1].append(f"{kind[0]}{ms:.2f}")
        else:
            if ms > 500:
                groups.append([])
            else:
                groups[-1].append(f"_{ms:.2f}")
    last = (t, down)
for g in groups:
    if g:
        print(" ".join(g))
marks = [(edges[i + 1][0] - edges[i][0]) * 1000 for i in range(len(edges) - 1) if edges[i][1]]
gaps = [(edges[i + 1][0] - edges[i][0]) * 1000 for i in range(len(edges) - 1) if not edges[i][1]]
gaps = [g for g in gaps if g < 500]
if marks:
    pts = [m for m in marks if m < 2 * dit]
    trs = [m for m in marks if m >= 2 * dit]
    if pts:
        print(f"points : {len(pts)}, {min(pts):.3f} à {max(pts):.3f} ms (attendu {dit:.0f})")
    if trs:
        print(f"traits : {len(trs)}, {min(trs):.3f} à {max(trs):.3f} ms (attendu {3 * dit:.0f})")
if gaps:
    print(f"espaces : {len(gaps)}, {min(gaps):.3f} à {max(gaps):.3f} ms (attendu {dit:.0f})")
step = analysis.max_step(audio / peak)
print(f"plus grand saut : {step:.4f} (sinusoïde pure : {analysis.sine_step(1.0, 700.0, FS):.4f})")
print(f"hors de ±150 Hz : {analysis.out_of_band_db(audio, FS, 700.0, 150.0):.1f} dB")
