# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
from trxstation.dashboard.history import BUCKETS, DAY_S, History


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_buckets_and_gaps():
    c = Clock()
    h = History(clock=c)
    c.t -= DAY_S - 60
    for i in range(10):                    # 10 minutes au début de la journée
        h.add_sample(10 + i, 40, 50, True)
        c.t += 60
    c.t = 1_000_000.0
    h.add_sample(80, 50, 70, False)
    v = h.view()
    assert v["n"] == BUCKETS and len(v["cpu"]) == BUCKETS
    assert v["cpu"][0] == 19.0             # le pic du quart d'heure
    assert v["cpu"][50] is None            # rien mesuré : trou, pas de valeur inventée
    assert v["internet"][-1] == 0.0


def test_trim_after_24h():
    c = Clock()
    h = History(clock=c)
    h.add_sample(1, 1, 1, True)
    h.add_alert("a", "crit", "x")
    c.t += DAY_S + 1
    h.add_sample(2, 2, 2, True)
    assert len(h.samples) == 1 and h.alert_counts() == (0, 0)


def test_alert_once():
    h = History(clock=Clock())
    assert h.add_alert("k", "warn", "x") is True
    assert h.add_alert("k", "warn", "x") is False
    h.add_alert("k2", "crit", "y")
    assert h.alert_counts() == (1, 1)


def test_save_load(tmp_path):
    c = Clock()
    h = History(tmp_path / "h.json", clock=c)
    h.add_sample(12, 34, 56, True)
    h.add_alert("k", "crit", "x")
    h.save()
    h2 = History(tmp_path / "h.json", clock=c)
    h2.load()
    assert h2.samples[0]["cpu"] == 12 and h2.alert_counts() == (0, 1)


def test_damaged_file(tmp_path):
    (tmp_path / "h.json").write_text("{pas du json", encoding="utf-8")
    h = History(tmp_path / "h.json", clock=Clock())
    h.load()
    assert not h.samples
