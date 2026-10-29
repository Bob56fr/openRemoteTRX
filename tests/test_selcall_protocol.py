# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""SELCALL, lot 1 : protocole, générateur et décodeur sur signaux synthétiques (cahier des charges § 12)."""
from __future__ import annotations

import time
import wave

import numpy as np
import pytest

from trxstation.selcall import decoder as dec
from trxstation.selcall import protocol as p
from trxstation.selcall import signal as sg

RATE = 8000
TONE_POWER = (10 ** (p.TX_LEVEL_DBFS / 20)) ** 2 / 2


def band_noise(rng: np.random.Generator, n: int, snr_db: float) -> np.ndarray:
    """Bruit blanc filtré à 300-2 700 Hz, réglé pour un SNR donné du ton (à -6 dBFS) dans cette bande de 2,4 kHz."""
    w = rng.standard_normal(n)
    spec = np.fft.rfft(w)
    f = np.fft.rfftfreq(n, 1 / RATE)
    spec[(f < 300) | (f > 2700)] = 0
    w = np.fft.irfft(spec, n)
    return w * np.sqrt(TONE_POWER / 10 ** (snr_db / 10) / np.mean(w ** 2))


def on_air(code: str, rng, *, offset=0.0, snr=20.0, drift=0.0, lead=None, qsb_db=0.0) -> np.ndarray:
    frame = sg.synthesize(code, offset_hz=offset, drift_hz=drift).astype(np.float64)
    if qsb_db:
        t = np.arange(len(frame)) / RATE
        frame *= 10 ** (-qsb_db / 20 * (0.5 - 0.5 * np.cos(2 * np.pi * 0.4 * t)))          # évanouissement lent
    head = int(rng.integers(200, 6000)) if lead is None else lead
    x = np.concatenate([np.zeros(head), frame, np.zeros(4000)])
    return x + band_noise(rng, len(x), snr)


def voice(rng, seconds: float, steady: bool = False) -> np.ndarray:
    """Voix synthétique : harmoniques d'un fondamental qui varie (ou tenu, voyelle longue), formants, syllabes."""
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    f0 = np.full(n, 125.0) if steady else 120 + 40 * np.sin(2 * np.pi * 0.7 * t) + 15 * np.sin(2 * np.pi * 3.1 * t)
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    x = np.zeros(n)
    for h in range(1, 25):
        formant = np.exp(-((h * 125 - 700) / 400) ** 2) + 0.6 * np.exp(-((h * 125 - 1800) / 500) ** 2)
        x += formant * np.sin(h * phase)
    x *= 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 2.0 * t)) if not steady else 1.0
    return 0.3 * x / np.max(np.abs(x))


def sweep(seconds: float, f_lo: float, f_hi: float) -> np.ndarray:
    n = int(seconds * RATE)
    f = np.linspace(f_lo, f_hi, n)
    return 0.4 * np.sin(2 * np.pi * np.cumsum(f) / RATE)


# ------------------------------------------------------------------ protocole


def test_frame_construction_repeat_rule_and_durations():
    assert p.check_digit("4477") == 2
    assert p.symbols("4477") == ["4", "R", "7", "R", "2"]
    assert p.symbols("1111") == ["1", "R", "R", "R", "4"]
    assert p.symbols("909") == ["9", "0", "9", "8"]
    assert p.symbols("190") == ["1", "9", "0", "R"]                              # contrôle égal au dernier chiffre : R
    assert p.symbol_hz("0") == 1200 and p.symbol_hz("9") == 2100 and p.symbol_hz("R") == 2200
    assert [p.duration_s(c) for c in ("123", "4477", "12345678")] == pytest.approx([2.2, 2.5, 3.7])
    for bad in ("12", "123456789", "12a", "١٢٣", "", None):
        with pytest.raises(p.CodeError):
            p.validate_code(bad)
    lo = min(f for f, _ in p.tones("12345678", -300)); hi = max(f for f, _ in p.tones("99999999", 300))
    assert lo >= 700 and hi <= 2500                                              # dans un filtre BLU de 2,4 kHz


def test_unpack_rejects_bad_check_length_and_encoding():
    assert p.unpack(["4", "R", "7", "R", "2"]) == "4477"
    assert p.unpack(["4", "R", "7", "R", "3"]) is None                          # contrôle faux
    assert p.unpack(["1", "1"]) is None and p.unpack(["R", "1", "2", "3"]) is None
    assert p.unpack(["4", "4", "7", "R", "2"]) is None                          # répétition non codée en R
    assert p.unpack(list("1234567890")) is None                                 # trop long


def test_generator_level_phase_continuity_and_wav(tmp_path):
    x = sg.synthesize("4477", offset_hz=0)
    assert len(x) == int(2.5 * RATE)
    assert np.max(np.abs(x)) <= 10 ** (-6 / 20) + 1e-6
    assert abs(x[0]) < 1e-3 and abs(x[-1]) < 1e-3                                # rampes : pas de clic
    jumps = np.abs(np.diff(x))
    assert jumps.max() < 2 * np.pi * 2200 / RATE * 10 ** (-6 / 20)              # phase continue entre les tons
    path = tmp_path / "trame.wav"
    sg.write_wav(path, x)
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (RATE, 1, len(x))


# ------------------------------------------------------------------ décodeur : matrice


@pytest.mark.parametrize("offset", list(range(-300, 301, 50)))
def test_detection_over_offsets_codes_and_snr(offset):
    rng = np.random.default_rng(1000 + offset)
    for code in ("123", "4477", "1111", "190", "90817", "98765432"):
        for snr in (20, 12, 6, 3, 0):
            frames = dec.decode(on_air(code, rng, offset=offset, snr=snr))
            assert [f.code for f in frames if f.valid] == [code], (code, offset, snr, frames)
            assert frames[0].delta_hz == pytest.approx(offset, abs=2.0)          # Δ à ±2 Hz


def test_detection_rate_at_6_db_is_at_least_95_percent():
    rng = np.random.default_rng(7)
    ok = total = 0
    for offset in range(-300, 301, 25):
        for _ in range(8):
            code = "".join(str(d) for d in rng.integers(0, 10, int(rng.integers(3, 9))))
            frames = dec.decode(on_air(code, rng, offset=offset, snr=6))
            total += 1
            ok += [f.code for f in frames if f.valid] == [code]
    assert ok / total >= 0.95, f"{ok}/{total}"


def test_snr_is_measured_in_2_4_khz():
    rng = np.random.default_rng(3)
    for snr in (20, 6, 0):
        (frame,) = dec.decode(on_air("4721", rng, snr=snr))
        assert frame.snr_db == pytest.approx(snr, abs=1.5)


@pytest.mark.parametrize("drift", [-10.0, 10.0])
def test_drift_and_qsb_are_tolerated(drift):
    rng = np.random.default_rng(11)
    for offset in (-300, 0, 300):
        frames = dec.decode(on_air("2718281", rng, offset=offset, snr=6, drift=drift, qsb_db=10))
        assert [f.code for f in frames if f.valid] == ["2718281"]


def test_offset_of_350_hz_is_beyond_the_limit_but_never_gives_a_wrong_code():
    rng = np.random.default_rng(5)
    for offset in (-350, 350):
        frames = dec.decode(on_air("4477", rng, offset=offset, snr=20))
        assert all(f.code in (None, "4477") for f in frames)


# ------------------------------------------------------------------ rejets


def test_rejects_wrong_check_truncated_frame_and_lone_carrier():
    rng = np.random.default_rng(9)
    # contrôle faux : trame fabriquée à la main (4477 avec contrôle 3)
    plan = [(p.F0_HZ, p.PILOT_S)] + [(p.symbol_hz(s), p.SYMBOL_S) for s in ["4", "R", "7", "R", "3"]]
    x = np.concatenate([0.5 * np.sin(2 * np.pi * np.cumsum(np.full(int(d * RATE), f)) / RATE) for f, d in plan])
    x = np.concatenate([np.zeros(2000), x, np.zeros(4000)]) + band_noise(rng, len(x) + 6000, 20)
    frames = dec.decode(x)
    assert frames and not any(f.valid for f in frames)
    # trame tronquée : coupée après deux chiffres
    full = on_air("98765432", rng, snr=20, lead=2000)
    cut = full[: 2000 + int((p.PILOT_S + 2 * p.SYMBOL_S) * RATE)]
    assert not any(f.valid for f in dec.decode(np.concatenate([cut, band_noise(rng, 8000, 20)])))
    # porteuse fixe à F0, sans chiffres
    carrier = 0.4 * np.sin(2 * np.pi * 1000 * np.arange(8 * RATE) / RATE) + band_noise(rng, 8 * RATE, 20)
    frames = dec.decode(carrier)
    assert not any(f.valid for f in frames)
    assert any("sans chiffres" in f.reason for f in frames)


def test_voice_whistles_and_noise_never_give_a_frame():
    rng = np.random.default_rng(21)
    signals = [voice(rng, 6), voice(rng, 3, steady=True), sweep(3, 600, 1400), sweep(3, 1400, 600),
               sweep(2, 900, 1100), band_noise(rng, 6 * RATE, 0)]
    for s in signals:
        frames = dec.decode(s + band_noise(rng, len(s), 10))
        assert not any(f.valid for f in frames)


def test_no_false_opening_over_five_minutes_of_mixed_audio():
    """Bruit, voix, voyelles tenues, sifflements glissants et porteuses : aucune trame valide (et le temps de calcul
    reste très en dessous du temps réel : moins de 10 % d'un cœur visé sur Raspberry Pi 4)."""
    rng = np.random.default_rng(42)
    parts = []
    while sum(len(x) for x in parts) < 5 * 60 * RATE:
        kind = int(rng.integers(0, 5))
        seconds = float(rng.uniform(1, 6))
        if kind == 0:
            parts.append(voice(rng, seconds))
        elif kind == 1:
            parts.append(voice(rng, seconds, steady=True))
        elif kind == 2:
            lo, hi = sorted(rng.uniform(500, 2500, 2))
            parts.append(sweep(seconds, lo, hi) if rng.random() < 0.5 else sweep(seconds, hi, lo))
        elif kind == 3:
            parts.append(0.3 * np.sin(2 * np.pi * rng.uniform(600, 2400) * np.arange(int(seconds * RATE)) / RATE))
        else:
            parts.append(np.zeros(int(seconds * RATE)))
    audio = np.concatenate(parts)
    audio = audio + band_noise(rng, len(audio), float(rng.uniform(0, 20)))
    start = time.process_time()
    decoder = dec.SelcallDecoder()
    frames = []
    for i in range(0, len(audio), 960):                                            # morceaux de 120 ms, comme en flux
        frames += decoder.feed(audio[i:i + 960])
    spent = time.process_time() - start
    assert not any(f.valid for f in frames)
    assert spent < 0.1 * len(audio) / RATE * 2                                    # marge : PC de développement


# ------------------------------------------------------------------ trames successives, appel manuel


def test_voice_right_after_the_frame_does_not_spoil_it():
    rng = np.random.default_rng(23)
    for code in ("4721", "12345678", "190"):
        x = np.concatenate([np.zeros(2000), sg.synthesize(code, offset_hz=-120).astype(np.float64), voice(rng, 3)])
        frames = dec.decode(x + band_noise(rng, len(x), 15))
        assert [f.code for f in frames if f.valid] == [code]


def test_two_successive_frames_and_streaming_in_small_chunks():
    rng = np.random.default_rng(13)
    x = np.concatenate([on_air("4721", rng, snr=12, lead=1000), on_air("5555", rng, snr=12, lead=3000)])
    decoder = dec.SelcallDecoder()
    frames = []
    for i in range(0, len(x), 160):                                                # 20 ms par morceau
        frames += decoder.feed(x[i:i + 160])
    frames += decoder.flush()
    assert [f.code for f in frames if f.valid] == ["4721", "5555"]
    assert frames[0].end_s < frames[1].start_s


def manual_call(code: str, repeat=3, gap_ms=500) -> np.ndarray:
    frame = sg.synthesize(code).astype(np.float64)
    gap = np.zeros(int(gap_ms / 1000 * RATE))
    parts = []
    for i in range(repeat):
        parts += [frame] + ([gap] if i < repeat - 1 else [])
    return np.concatenate(parts)


def test_manual_call_three_frames_are_each_decoded():
    rng = np.random.default_rng(17)
    x = manual_call("12345678")
    x = np.concatenate([np.zeros(2000), x, np.zeros(4000)])
    frames = dec.decode(x + band_noise(rng, len(x), 6))
    assert [f.code for f in frames if f.valid] == ["12345678"] * 3


def test_manual_call_first_frame_lost_in_noise_the_next_ones_still_decode():
    rng = np.random.default_rng(19)
    x = manual_call("4477")
    x = np.concatenate([np.zeros(2000), x, np.zeros(4000)])
    burst = np.zeros(len(x))
    first = slice(2000, 2000 + int(2.5 * RATE))
    burst[first] = band_noise(rng, first.stop - first.start, -20)                  # première trame noyée
    frames = dec.decode(x + burst + band_noise(rng, len(x), 10))
    assert [f.code for f in frames if f.valid] == ["4477", "4477"]
