# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Décrochages fréquents de la carte son du poste : événement ORT-3010 (mesure seule)."""
from __future__ import annotations

from trxstation.gateway.audio import xruns as xr


class Source:
    xruns = 0
    overruns = 0


def make():
    now = [0.0]
    events = []
    src = Source()
    w = xr.XrunWatch(src, clock=lambda: now[0], emit=lambda code, **ctx: events.append((code, ctx)))
    return w, src, now, events


def test_rare_xruns_stay_silent():
    w, src, now, events = make()
    for _ in range(40):
        src.xruns += 1
        now[0] += 30
        w.check()
    assert events == []                                         # 1 par 30 s : bien sous le seuil


def test_frequent_xruns_emit_once_then_wait_for_the_cooldown():
    w, src, now, events = make()
    w.check()
    for _ in range(5):
        src.xruns += 15
        src.overruns += 2
        now[0] += 30
        w.check()
    assert len(events) == 1
    code, ctx = events[0]
    assert code == "ORT-3010" and ctx["xruns"] + ctx["perdues"] >= xr.THRESHOLD and ctx["duree_min"] >= 1
    for _ in range(20):                                         # toujours mauvais, mais un seul événement par 30 min
        src.xruns += 30
        now[0] += 30
        w.check()
    assert len(events) == 1
    now[0] += xr.COOLDOWN_S
    w.check()
    for _ in range(3):                                          # après l'attente : de nouveau signalé
        src.xruns += 30
        now[0] += 30
        w.check()
    assert len(events) == 2


def test_source_without_counters_is_never_reported():
    events = []
    w = xr.XrunWatch(object(), clock=lambda: 0.0, emit=lambda *a, **k: events.append(a))
    assert w.check() is False and events == []


def test_real_event_text_is_complete():
    from trxstation.errors.emit import render
    _, message = render("ORT-3010", xruns=40, perdues=12, duree_min=5)
    assert "{" not in message and "40" in message
