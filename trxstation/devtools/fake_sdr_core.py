# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Faux sdr-core (essais sans SDR ni compilateur) : mêmes arguments utiles, mêmes trames, mêmes commandes.

    python -m trxstation.devtools.fake_sdr_core --serial TEST --fs 2000000 --freq 7100000 --rate 8
Lignes : bruit à -95 dBFS et une porteuse à +100 kHz du centre. Pannes simulées par --fail :
absent (code 3), service (code 4), crash (sortie 1 après --crash-after secondes).
"""
from __future__ import annotations

import argparse
import random
import sys
import threading
import time

from ..sdr.frames import DB_MIN, DB_STEP, TYPE_AUDIO, encode_frame, encode_json, encode_line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fake_sdr_core")
    ap.add_argument("--serial", default="TEST")
    ap.add_argument("--fs", type=float, default=2e6)
    ap.add_argument("--freq", type=float, default=7.1e6)
    ap.add_argument("--rate", type=float, default=8)
    ap.add_argument("--bins", type=int, default=1024)
    ap.add_argument("--lna", type=int, default=2)
    ap.add_argument("--gr", type=int, default=50)
    ap.add_argument("--ant", default="A")
    ap.add_argument("--bw", type=int, default=1536)
    ap.add_argument("--fft", type=int, default=4096)
    ap.add_argument("--agc", type=int, default=1)
    ap.add_argument("--zoom", type=int, default=1)
    ap.add_argument("--zoom-off", type=float, default=0)
    ap.add_argument("--fail", choices=("absent", "service", "crash"), default=None)
    ap.add_argument("--crash-after", type=float, default=1.0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--overloads", type=int, default=0, help="rafale de surcharges du CAN au démarrage")
    a, _ = ap.parse_known_args(argv)
    out = sys.stdout.buffer
    if a.list:
        print('{"api":3.15,"devices":[{"serial":"%s","hw":2}]}' % a.serial)
        return 0
    if a.fail == "absent":
        out.write(encode_json({"t": "error", "code": "absent", "detail": a.serial})); out.flush()
        return 3
    if a.fail == "service":
        out.write(encode_json({"t": "error", "code": "service", "detail": "service SDRplay injoignable"})); out.flush()
        return 4
    state = {"freq": a.freq, "lna": a.lna, "gr": a.gr, "rate": a.rate, "agc": a.agc, "stop": False, "audio": 0,
             "demod": None, "zoom": a.zoom, "zoom_off": a.zoom_off}

    def commands() -> None:
        for line in sys.stdin:
            parts = line.split()
            if parts[:1] == ["freq"] and len(parts) == 2:
                state["freq"] = float(parts[1])
            elif parts[:1] == ["gain"] and len(parts) == 3:
                state["lna"], state["gr"] = int(parts[1]), int(parts[2])
            elif parts[:1] == ["audio"] and len(parts) == 2:
                state["audio"] = int(parts[1])
            elif parts[:1] == ["demod"] and len(parts) == 4:
                state["demod"] = (int(float(parts[1])), parts[2], int(parts[3]))
            elif parts[:1] == ["agc"] and len(parts) == 2:
                state["agc"] = int(parts[1])
            elif parts[:1] == ["zoom"] and len(parts) == 3:
                state["zoom"], state["zoom_off"] = int(parts[1]), float(parts[2])
            elif parts[:1] == ["rate"] and len(parts) == 2:
                state["rate"] = float(parts[1])
            elif parts[:1] == ["quit"]:
                break
        state["stop"] = True

    threading.Thread(target=commands, daemon=True).start()
    out.write(encode_json({"t": "started", "serial": a.serial, "hw": 2, "api": 3.15, "core": "fake"})); out.flush()
    for i in range(2 * a.overloads):                       # surcharge qui bascule en rafale (vu sur le vrai RSP)
        out.write(encode_json({"t": "event", "name": "overload", "on": int(i % 2 == 0)}))
    out.flush()
    rng = random.Random(1)
    noise = int((-95 - DB_MIN) / DB_STEP)
    carrier = a.bins // 2 + int(100e3 / a.fs * a.bins)
    t0 = last_status = time.monotonic()
    try:
        while not state["stop"]:
            now = time.monotonic()
            if a.fail == "crash" and now - t0 >= a.crash_after:
                return 1
            values = bytes(min(255, max(0, noise + rng.randint(-6, 6))) for _ in range(a.bins))
            if 0 <= carrier < a.bins:
                values = values[:carrier] + bytes([int((-40 - DB_MIN) / DB_STEP)]) + values[carrier + 1:]
            zoom = max(1, state["zoom"])               # zoom : même ligne, centre et largeur de la fenêtre
            out.write(encode_line(state["freq"] + (state["zoom_off"] if zoom > 1 else 0), a.fs / zoom, values))
            if state["audio"]:                              # son : 1 kHz à -20 dBFS, 20 ms par trame
                import math
                import struct
                for _ in range(max(1, int(round(50 / max(1.0, state["rate"]))))):
                    out.write(encode_frame(TYPE_AUDIO, struct.pack("<960h", *(int(3277 * math.sin(2 * math.pi * 1000 * i / 48000))
                                                                             for i in range(960)))))
            if now - last_status >= 1.0:
                last_status = now
                out.write(encode_json({"t": "status", "fs": a.fs, "freq": state["freq"], "lna": state["lna"],
                                       "gr": state["gr"], "ant": a.ant, "rate": state["rate"], "bins": a.bins,
                                       "agc": state["agc"], "gr_now": 38 if state["agc"] else state["gr"],
                                       "audio": state["audio"], "sql_open": 1, "chan_db": -60.0 if state["audio"] else -200,
                                       "noise_db": -95.0 if state["audio"] else -200,
                                       "gain_db": 61.5,
                                       "overload": 0, "samples": 0, "drops": 0, "gaps": 0,
                                       "zoom": state["zoom"]}))
            out.flush()
            time.sleep(1.0 / max(1.0, state["rate"]))
        out.write(encode_json({"t": "stopped"})); out.flush()
    except (BrokenPipeError, OSError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
