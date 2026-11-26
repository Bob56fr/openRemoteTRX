# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lot CW-0 : tonalité recréée à l'échantillon près, fronts en cosinus surélevé, sans clic (cahier § 4)."""
from __future__ import annotations

import numpy as np
import pytest

from trxstation.cw import analysis as an
from trxstation.cw.tone import ToneRenderer, to_pcm16

FS = 48000


def _render(blocks: list[int], keys: list[tuple[int, bool]]) -> np.ndarray:
    """Fronts posés à leur échantillon exact, rendu découpé selon `blocks` (fronts au milieu des blocs)."""
    t = ToneRenderer()
    keys = sorted(keys)
    out = []
    for n in blocks:
        end = t.pos + n
        while keys and keys[0][0] < end:
            s, on = keys.pop(0)
            if s > t.pos:
                out.append(t.render(s - t.pos))
            t.set_key(s, on)
        out.append(t.render(end - t.pos))
    return np.concatenate(out)


KEYS = [(1000, True), (4123, False), (7777, True), (9001, False)]


def test_the_sound_does_not_depend_on_how_the_blocks_are_cut():
    whole = _render([12000], list(KEYS))
    small = _render([7] * (12000 // 7) + [12000 % 7], list(KEYS))
    frames = _render([960] * 12 + [480], list(KEYS))
    assert np.array_equal(whole, small) and np.array_equal(whole, frames)


def test_edges_fall_on_the_requested_sample():
    audio = _render([12000], list(KEYS))
    found = an.detect_edges(audio, FS, 700, 0.5)
    edge = round(5 * FS / 1000)
    # passage à 50 % = milieu du front, qui commence à l'échantillon demandé
    assert [s - edge / 2 for s, _ in found] == pytest.approx([k for k, _ in KEYS], abs=0.2)
    assert [d for _, d in found] == [d for _, d in KEYS]


def test_no_click_even_when_an_edge_reverses_another():
    audio = _render([6000], [(1000, True), (1100, False), (1150, True), (3000, False)])   # fronts croisés
    assert an.max_step(audio) <= an.sine_step(0.5, 700, FS) * 1.001


def test_rise_time_matches_a_raised_cosine():
    audio = _render([6000], [(1000, True), (5000, False)])
    rise = an.rise_time_ms(audio, FS, 700, 0.5, 1000 + 120)
    assert 2.6 <= rise <= 3.6                    # 10 -> 90 % d'un cosinus surélevé de 5 ms ≈ 2,95 ms


def test_shaped_keying_is_much_narrower_than_hard_keying():
    audio = _render([48000], [(k * 4000, k % 2 == 0) for k in range(12)])
    hard = np.zeros(48000)
    n = np.arange(48000)
    for k in range(0, 12, 2):
        a, b = k * 4000, (k + 1) * 4000
        hard[a:b] = 0.5 * np.sin(2 * np.pi * 700 * n[a:b] / FS)
    shaped_db = an.out_of_band_db(audio, FS, 700, 250)
    hard_db = an.out_of_band_db(hard, FS, 700, 250)
    assert shaped_db < -45 and hard_db > -40     # le test sait voir des clics


def test_silent_after_the_falling_edge_only():
    t = ToneRenderer()
    assert t.silent
    t.set_key(0, True)
    t.render(500)
    t.set_key(500, False)
    assert not t.silent
    t.render(239)
    assert not t.silent
    t.render(1)
    assert t.silent


def test_an_edge_in_the_past_is_played_now():
    t = ToneRenderer()
    t.render(1000)
    t.set_key(10, True)
    assert t._start == 1000


@pytest.mark.parametrize("kw", [{"tone_hz": 200}, {"tone_hz": 1500}, {"edge_ms": 2}, {"edge_ms": 9},
                                {"level": 0}, {"level": 1.5}])
def test_bounds(kw):
    with pytest.raises(ValueError):
        ToneRenderer(**kw)


def test_pcm16_conversion():
    assert to_pcm16(np.array([0.0, 1.0, -1.0, 2.0])) == np.array([0, 32767, -32767, 32767], "<i2").tobytes()
