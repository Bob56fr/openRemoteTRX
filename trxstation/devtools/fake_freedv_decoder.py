# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Faux freedv-ka9q / radae_rx : tests de panne du moteur de réception RADE (tests/test_freedv_rx.py) et essais
de la page sans les vrais décodeurs.

  python -m trxstation.devtools.fake_freedv_decoder ka9q  [--voice] [--callsign X] [--crash-after S] [--freeze-after S] [--no-read]
  python -m trxstation.devtools.fake_freedv_decoder radae [--states search|sync:SNR,...] [--crash-after S] [--freeze-after S] [--mute-after S]
Les secondes comptent le SON REÇU (pas l'horloge) : les tests sont reproductibles.
Les messages imitent ceux des vrais programmes (formats relevés le 2026-11-10).
"""
from __future__ import annotations

import argparse, math, os, struct, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("role", choices=["ka9q", "radae"])
ap.add_argument("--voice", action="store_true")
ap.add_argument("--callsign")
ap.add_argument("--callsign-at", type=float, default=1.0)
ap.add_argument("--states", default="search")
ap.add_argument("--crash-after", type=float)
ap.add_argument("--freeze-after", type=float)
ap.add_argument("--mute-after", type=float)
ap.add_argument("--bad-line", action="store_true")
ap.add_argument("--no-read", action="store_true")
ap.add_argument("--pause-every", type=float)   # secondes de son reçu
ap.add_argument("--pause-for", type=float, default=0.8)   # secondes d'horloge sans lire
a, rest = ap.parse_known_args()
if os.environ.get("FAKE_ARGV_DIR"):
    with open(os.path.join(os.environ["FAKE_ARGV_DIR"], a.role + ".txt"), "w") as f:
        f.write(" ".join(rest))
inp, out, err = sys.stdin.buffer, sys.stdout.buffer, sys.stderr

if a.role == "ka9q":
    rate_in = int(rest[rest.index("-i") + 1]) if "-i" in rest else 8000
    rate_out = int(rest[rest.index("-o") + 1]) if "-o" in rest else 16000
    bps = rate_in * 2
else:
    bps = 8000 * 8          # complexe float32 à 8 kHz

if a.no_read:
    time.sleep(3600)

if a.bad_line:
    err.write("x" * 200000 + "\n"); err.flush()

got, said_call, sym, next_pause = 0, False, 0, a.pause_every
states = a.states.split(",")
tone = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(960))
while True:
    b = inp.read(4096)
    if not b:
        sys.exit(0)
    got += len(b)
    t = got / bps
    if a.crash_after is not None and t >= a.crash_after:
        err.write("Segmentation fault\n"); err.flush()
        os._exit(3)
    if a.freeze_after is not None and t >= a.freeze_after:
        time.sleep(3600)
    if next_pause is not None and t >= next_pause:
        time.sleep(a.pause_for)
        next_pause += a.pause_every
    if a.role == "ka9q":
        if a.voice:
            n = int(len(b) / 2 * rate_out / rate_in)
            out.write((tone * (n // 960 + 1))[: 2 * n]); out.flush()
        if a.callsign and not said_call and t >= a.callsign_at:
            said_call = True
            err.write(f"12:00:00 INFO x/rade_text.cpp:401: rxCRC: 63, calcCRC: 63, decodedStr: {a.callsign}\n")
            err.write(f"12:00:00 INFO x/ReportingController.cpp:228: Reporting RX callsign {a.callsign} (SNR 9) to FreeDV Reporter\n")
            err.flush()
    else:
        if a.mute_after is not None and t >= a.mute_after:
            continue
        while sym < int(t / 0.12):
            st = states[sym % len(states)]
            name, _, snr = st.partition(":")
            out.write(b"\x00" * 1728)            # paramètres de parole (12 trames x 144 octets), comme radae_rx
            err.write(f"{sym:4d} state: {name:>10s} valid: 1 0  1 Dthresh:     0.70 Dtmax12:     1.04     0.28 "
                      f"tmax:  299 fmax:   1.50 SNRdB: {float(snr or 0):6.2f}\n")
            sym += 1
        out.flush()
        err.flush()
