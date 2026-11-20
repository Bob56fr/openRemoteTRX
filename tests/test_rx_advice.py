# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Avis sur le niveau reçu (étape 301) : jugé sur 30 s, renvoyé au menu 2.9 par trx-monitor et le tableau de bord."""
from __future__ import annotations

from trxstation.gateway.audio.rxadvice import RxAdvice
from trxstation.monitor.model import _rx_advice_rows


def feed(adv: RxAdvice, levels, start=0.0, limited_per_s=0, frames_per_s=50):
    lim = fr = 0
    for i, level in enumerate(levels):
        lim += limited_per_s
        fr += frames_per_s
        adv.feed(start + i, level, lim, fr)


def test_no_advice_without_enough_sound():
    adv = RxAdvice()
    feed(adv, [-120] * 25 + [-20] * 5)               # squelch fermé, quelques mots
    assert adv.verdict() is None


def test_ok_low_and_high_on_the_typical_level():
    adv = RxAdvice(); feed(adv, [-22, -18, -120, -25] * 8)
    assert adv.verdict()["verdict"] == "ok"
    adv = RxAdvice(); feed(adv, [-50, -46, -120] * 10)
    assert adv.verdict() == {"verdict": "low", "typical_db": -48, "limited_pct": 0.0}
    adv = RxAdvice(); feed(adv, [-5, -4, -6] * 10)
    assert adv.verdict()["verdict"] == "high"


def test_limiter_at_work_means_too_loud_even_with_a_moderate_typical_level():
    adv = RxAdvice()
    feed(adv, [-15] * 30, limited_per_s=2, frames_per_s=50)        # 4 % des trames limitées
    v = adv.verdict()
    assert v["verdict"] == "high" and v["limited_pct"] == 4.0


def test_window_forgets_old_samples_and_one_sample_per_second():
    adv = RxAdvice()
    feed(adv, [-5] * 30)
    feed(adv, [-22] * 31, start=40.0)
    assert adv.verdict()["verdict"] == "ok"
    adv.feed(70.5, -5, 0, 10_000)                  # moins d'une seconde après : ignoré
    assert adv.verdict()["verdict"] == "ok"


def test_counters_reset_restart_the_window():
    adv = RxAdvice()
    feed(adv, [-22] * 20)
    adv.feed(25.0, -22, 0, 10)                     # audio relancé : compteurs repartis de zéro
    assert adv.verdict() is None


def test_monitor_row_points_to_menu_2_9():
    high = _rx_advice_rows({"rx_advice": {"verdict": "high", "typical_db": -5, "limited_pct": 4.2}})[0]
    low = _rx_advice_rows({"rx_advice": {"verdict": "low", "typical_db": -48, "limited_pct": 0}})[0]
    assert high.level == low.level == "warn" and "menu 2.9" in high.text and "menu 2.9" in low.text
    assert _rx_advice_rows({"rx_advice": {"verdict": "ok", "typical_db": -21, "limited_pct": 0}})[0].level == "ok"
    assert _rx_advice_rows({"rx_advice": None})[0].level == "dim"
    assert _rx_advice_rows({}) == ()                  # passerelle plus ancienne : rien
