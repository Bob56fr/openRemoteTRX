# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mode démonstration (`--demo`) : fausse station qui passe en boucle par réception, émission et mise en sécurité.

Sert à essayer la page sans station (poste de développement Windows compris). Rien n'est lu ni écrit ailleurs.
"""
from __future__ import annotations

import math
import random
import time

ACCOUNTS = [{"id": "S25", "pseudo": None}, {"id": "PC", "pseudo": None}, {"id": "tablette", "pseudo": "BOB"}, {"id": "Android8", "pseudo": "Andro-8"}]   # comptes opérateurs fictifs (station.toml)
CYCLE_S = 60                     # 0-30 s réception, 30-45 s émission, 45-60 s mise en sécurité


def vitals(t: float | None = None) -> dict:
    t = time.time() if t is None else t
    phase = t % CYCLE_S
    rnd = random.Random(int(t))
    tx, safe = 30 <= phase < 45, phase >= 45
    s_db = -12 + 8 * math.sin(t / 3) + rnd.uniform(-3, 3)
    rig = {"model": "IC-7300MK2", "connected": not safe, "lost_s": (phase - 45) + 120 if safe else None,
           "power": "on", "tx_allowed": True, "freq_hz": 14_195_000, "mode": "USB", "passband_hz": 2400,
           "strength_db": s_db, "vfo": "A", "vfo_a_hz": 14_195_000, "vfo_b_hz": 7_074_000, "split": False,
           "rit_hz": 120, "xit_hz": 0, "tuner": True, "nb": False, "nr": True, "nr_level": "5", "notch": "auto",
           "att_db": 0, "preamp": "P1", "agc": "LENTE", "comp": tx, "comp_level": "12" if tx else None,
           "vox": False, "squelch": False, "monitor": tx, "power_set_w": 50, "temp_c": 41 if tx else 36,
           "vd_v": 13.6 if tx else 13.8, "po_w": 48 if tx else None, "swr": 1.2 if tx else None,
           "alc_pct": 32 if tx else None, "last_freq_hz": 14_195_000, "last_mode": "USB"}
    services = [{"name": "Passerelle", "level": "ok", "text": "OK"},
                {"name": "Superviseur", "level": "warn" if safe else "ok", "text": "a coupé" if safe else "OK"},
                {"name": "rigctld", "level": "crit" if safe else "ok", "text": "ARRÊTÉ" if safe else "OK"},
                {"name": "Cluster DX", "level": "off" if safe else "ok", "text": "en pause" if safe else "OK"}]
    return {
        "station": {"ok": True, "age_s": 0.2 + rnd.random() / 5, "version": "0.279.0"},
        "safe": {"active": safe, "reason": "Le superviseur a coupé l'émission : poste injoignable par la CAT." if safe else None},
        "rig": rig,
        "ptt": {"tx": tx, "elapsed_s": phase - 30 if tx else None, "tot_s": 90 if tx else None, "warn_s": 80 if tx else None,
                "owner": "S25" if tx else None, "local": False, "heartbeat_s": 0.4 if tx else None},
        "operators": [] if safe else [{"id": "S25", "name": "S25", "tx": tx}, {"id": "PC", "name": "PC", "tx": False}],
        "visitors": 0 if safe else 2,
        "services": services,
        "sdr": {"present": not safe, "model": "SDRplay" if not safe else "RTL-SDR", "state": "running",
                "freq_hz": 7_074_000, "mode": "FT8", "rate": "2 MS/s", "load_pct": 18, "seen_ago_s": 360 if safe else 1},
    }


def host(t: float | None = None) -> dict:
    t = time.time() if t is None else t
    rnd = random.Random(int(t // 60))
    return {"cpu": 22 + 8 * math.sin(t / 3000) + rnd.uniform(-5, 5), "mem": 41 + rnd.uniform(-1, 1),
            "disk": 62.0, "temp": 50 + 4 * math.sin(t / 3000) + rnd.uniform(-1, 1), "uptime_s": 3 * 86400 + 4 * 3600,
            "os": "Debian 13"}


def fill_history(history, now: float | None = None) -> None:
    """24 h fictives, avec deux coupures d'Internet et quelques alertes."""
    now = time.time() if now is None else now
    start = now - 86400
    for i in range(0, 1440):
        t = start + i * 60
        h = host(t)
        net = not (420 <= i < 440 or 1000 <= i < 1004)
        history.samples.append({"t": t, "cpu": round(h["cpu"], 1), "mem": round(h["mem"], 1),
                                "temp": round(h["temp"], 1), "net": int(net)})
    history.add_alert("demo-1", "warn", "Coupure Internet", start + 430 * 60)
    history.add_alert("demo-2", "warn", "Température du poste", start + 820 * 60)
    history.add_alert("demo-3", "crit", "Liaison CAT perdue", start + 1380 * 60)
