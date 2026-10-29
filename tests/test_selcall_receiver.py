# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""SELCALL, lot 2 : machine d'états persistante, audio retardé, squelch, filtrage des tonalités (cahier des charges § 5, § 6)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from trxstation.selcall import protocol as p
from trxstation.selcall import receiver as rc
from trxstation.selcall import signal as sg

RATE = 48000
CHUNK = 960


def noise(rng, n, level=0.01):
    return rng.standard_normal(n) * level


def voice_like(n, level=0.2):
    t = np.arange(n) / RATE
    return level * (np.sin(2 * np.pi * 180 * t) + 0.5 * np.sin(2 * np.pi * 540 * t)) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))


def run(receiver, audio: np.ndarray) -> np.ndarray:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    pad = (-len(pcm)) % CHUNK
    pcm = np.concatenate([pcm, np.zeros(pad, dtype="<i2")])
    out = [np.frombuffer(receiver.process(pcm[i:i + CHUNK].tobytes()), dtype="<i2") for i in range(0, len(pcm), CHUNK)]
    return np.concatenate(out).astype(np.float64) / 32768.0


def frame48(code, offset=0.0):
    return sg.synthesize(code, rate=RATE, offset_hz=offset).astype(np.float64)


def make(tmp_path, state=None, code="4721", mode="mute", **kw):
    store = rc.SelcallStore(tmp_path / "selcall.json", filter_mode=mode)
    if state in (rc.STANDBY, rc.OPEN):
        store.activate(code)
    if state == rc.OPEN:
        store._set(rc._replace(store.status, state=rc.OPEN))
    events = []
    receiver = rc.SelcallReceiver(store, on_frame=lambda f, opened: events.append((f, opened)), **kw)
    return store, receiver, events


# ------------------------------------------------------------------ état et persistance


def test_store_history_validation_and_restart_in_standby(tmp_path):
    store = rc.SelcallStore(tmp_path / "selcall.json", history_size=3)
    assert store.status.state == rc.DISABLED
    for code in ("111", "2222", "333", "2222", "44444"):
        store.activate(code)
    assert store.status.history == ("44444", "2222", "333")                        # récent en tête, sans doublon, borné
    with pytest.raises(p.CodeError):
        store.activate("12")
    store._set(rc._replace(store.status, state=rc.OPEN))
    again = rc.SelcallStore(tmp_path / "selcall.json", history_size=3)
    assert (again.status.state, again.status.code) == (rc.STANDBY, "44444")         # redémarrage : VEILLE, même code
    again.deactivate()
    assert rc.SelcallStore(tmp_path / "selcall.json").status.state == rc.DISABLED
    (tmp_path / "bad.json").write_text("{pas du json", encoding="utf-8")
    assert rc.SelcallStore(tmp_path / "bad.json").status.state == rc.DISABLED
    (tmp_path / "evil.json").write_text(json.dumps({"state": "open", "code": "1; rm", "history": ["12", 5, "777"]}), encoding="utf-8")
    evil = rc.SelcallStore(tmp_path / "evil.json")
    assert evil.status.state == rc.DISABLED and evil.status.history == ("777",)


def test_options_are_validated(tmp_path):
    store = rc.SelcallStore(None)
    assert store.set_options(filter_mode="chime", attenuation_db=30).filter_mode == "chime"
    with pytest.raises(ValueError):
        store.set_options(filter_mode="fort")
    with pytest.raises(ValueError):
        store.set_options(attenuation_db=3)


# ------------------------------------------------------------------ audio


def test_disabled_is_a_strict_passthrough(tmp_path):
    _, r, _ = make(tmp_path)
    rng = np.random.default_rng(1)
    pcm = (noise(rng, CHUNK, 0.2) * 32767).astype("<i2").tobytes()
    assert r.process(pcm) == pcm


def test_standby_sends_silence_until_the_right_code_then_opens_and_stays_open(tmp_path):
    store, r, events = make(tmp_path, rc.STANDBY, code="4721")
    rng = np.random.default_rng(2)
    wrong = np.concatenate([noise(rng, RATE), frame48("1234", 150) + noise(rng, int(p.duration_s("1234") * RATE)), noise(rng, RATE)])
    out = run(r, wrong)
    assert np.max(np.abs(out)) == 0 and store.status.state == rc.STANDBY          # autre code : rien ne passe
    assert [(f.code, opened) for f, opened in events] == [("1234", False)]
    right = np.concatenate([frame48("4721", -220) + noise(rng, int(p.duration_s("4721") * RATE)), voice_like(3 * RATE)])
    out = run(r, right)
    assert store.status.state == rc.OPEN
    assert store.status.last_call["code"] == "4721" and store.status.last_call["delta_hz"] == pytest.approx(-220, abs=2)
    assert np.sqrt(np.mean(out[-RATE:] ** 2)) > 0.05                               # la voix qui suit passe
    run(r, noise(rng, 5 * RATE))
    assert store.status.state == rc.OPEN                                           # aucune temporisation
    store.rearm()
    assert np.max(np.abs(run(r, voice_like(RATE)))) == 0                          # réarmé : silence


def test_open_audio_is_delayed_exactly_and_untouched_outside_frames(tmp_path):
    _, r, _ = make(tmp_path, rc.OPEN, delay_ms=500)
    x = voice_like(2 * RATE)
    out = run(r, x)
    d = int(0.5 * RATE)
    q = np.round(x * 32767) / 32768
    assert np.allclose(out[d:], q[:-d], atol=1e-4)
    assert np.max(np.abs(out[:d])) == 0


@pytest.mark.parametrize("delay_ms", [500, 1000])
def test_tones_are_removed_before_being_heard_mute_mode(tmp_path, delay_ms):
    _, r, events = make(tmp_path, rc.OPEN, mode="mute", delay_ms=delay_ms)
    rng = np.random.default_rng(3)
    lead, tail = voice_like(RATE), voice_like(RATE)
    fr = frame48("98765432", 120)
    x = np.concatenate([lead, fr, tail, np.zeros(2 * RATE)])
    x = x + noise(rng, len(x), 0.002)
    out = run(r, x)
    d = int(delay_ms / 1000 * RATE)
    a, b = len(lead) + d, len(lead) + len(fr) + d
    e_in = np.mean(fr ** 2)
    e_out = np.mean(out[a:b] ** 2)
    assert 10 * np.log10(e_out / e_in + 1e-20) < -30                                      # § 6 : -30 dB au moins
    assert [f.code for f, _ in events] == ["98765432"]
    voice_out = out[d + int(0.1 * RATE): d + len(lead) - int(0.3 * RATE)]
    voice_in = x[int(0.1 * RATE): len(lead) - int(0.3 * RATE)]
    assert np.mean(voice_out ** 2) > 0.8 * np.mean(voice_in ** 2)                 # voix avant la trame : non coupée
    after = out[b + int(0.2 * RATE): b + len(tail) - int(0.1 * RATE)]
    assert np.mean(after ** 2) > 0.8 * np.mean(tail[int(0.2 * RATE):-int(0.1 * RATE)] ** 2)
    assert np.max(np.abs(np.diff(out))) < 0.2                                     # fondus : pas de clic


def test_attenuate_mode_and_chime_mode(tmp_path):
    rng = np.random.default_rng(4)
    fr = frame48("4477")
    x = np.concatenate([np.zeros(RATE // 2), fr, np.zeros(2 * RATE)])
    _, r, _ = make(tmp_path / "a", rc.OPEN, mode="attenuate")
    out = run(r, x + noise(rng, len(x), 0.001))
    d = int(0.5 * RATE)
    mid = slice(RATE // 2 + d + int(1.2 * RATE), RATE // 2 + d + int(2.0 * RATE))   # chiffres, bien après le début
    ratio = 10 * np.log10(np.mean(out[mid] ** 2) / np.mean(x[mid.start - d: mid.stop - d] ** 2))
    assert -23 < ratio < -17                                                       # -20 dB par défaut
    _, r, _ = make(tmp_path / "c", rc.OPEN, mode="chime")
    out = run(r, x)
    end = RATE // 2 + len(fr) + d
    during = out[RATE // 2 + d + int(0.3 * RATE): end - int(0.1 * RATE)]
    chime = out[end: end + int(0.5 * RATE)]
    assert np.max(np.abs(during)) < 1e-3
    assert 0.01 < np.max(np.abs(chime)) < 0.08                                    # carillon doux, niveau bas


def test_decoder_is_suspended_while_transmitting(tmp_path):
    tx = [True]
    store, r, events = make(tmp_path, rc.STANDBY, code="4721", transmitting=lambda: tx[0])
    run(r, np.concatenate([frame48("4721"), np.zeros(RATE)]))
    assert store.status.state == rc.STANDBY and events == []
    tx[0] = False
    run(r, np.concatenate([np.zeros(RATE // 4), frame48("4721"), np.zeros(RATE)]))
    assert store.status.state == rc.OPEN


def test_manual_call_three_frames_open_once_and_are_all_filtered(tmp_path):
    store, r, events = make(tmp_path, rc.STANDBY, code="12345678", mode="mute")
    one = frame48("12345678", 80)
    gap = np.zeros(RATE // 2)
    x = np.concatenate([np.zeros(RATE // 3), one, gap, one, gap, one, voice_like(2 * RATE)])
    out = run(r, x + noise(np.random.default_rng(6), len(x), 0.002))         # toujours un fond de bruit sur l'air
    assert [(f.code, opened) for f, opened in events] == [("12345678", True), ("12345678", False), ("12345678", False)]
    d = int(0.5 * RATE)
    second = slice(RATE // 3 + len(one) + len(gap) + d, RATE // 3 + 2 * len(one) + len(gap) + d)
    assert 10 * np.log10(np.mean(out[second] ** 2) / np.mean(one ** 2) + 1e-20) < -30


def test_disabling_restarts_the_delay_line(tmp_path):
    store, r, _ = make(tmp_path, rc.OPEN)
    run(r, voice_like(RATE))
    store.deactivate()
    x = voice_like(CHUNK)
    pcm = (x * 32767).astype("<i2").tobytes()
    assert r.process(pcm) == pcm
    store.activate("4721")
    store._set(rc._replace(store.status, state=rc.OPEN))
    assert np.max(np.abs(run(r, voice_like(CHUNK * 5)))) == 0                     # ligne repartie de zéro (silence au début)


# ------------------------------------------------------------------ dans la passerelle


def test_hub_processor_error_never_stops_reception():
    from trxstation.gateway.audio.hub import RxHub
    hub = RxHub(source=None)
    queue = hub.subscribe()
    def broken(pcm):
        raise RuntimeError("panne")
    hub.processor = broken
    pcm = (voice_like(CHUNK) * 32767).astype("<i2").tobytes()
    hub.publish(pcm)
    hub.publish(pcm)
    assert queue.get_nowait() == pcm and queue.get_nowait() == pcm


def test_gateway_wiring_squelch_on_the_real_hub(tmp_path):
    from types import SimpleNamespace
    from trxstation import config as cfgmod
    from trxstation.gateway.audio.hub import RxHub
    from trxstation.gateway.main import _start_selcall
    cfg = cfgmod.Config()
    cfg.supervisor.state_dir = str(tmp_path)
    hub = RxHub(source=None)
    pipeline = SimpleNamespace(hub=hub)
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"))
    link = SimpleNamespace(state=SimpleNamespace(ptt=False))
    assert _start_selcall(cfg, pipeline, ctrl, link) is None and hub.processor is None    # désactivé : rien
    cfg.selcall.enabled = True
    receiver = _start_selcall(cfg, pipeline, ctrl, link)
    receiver.store.activate("4721")
    queue = hub.subscribe(maxsize=10_000)
    rng = np.random.default_rng(8)
    x = np.concatenate([frame48("4721"), voice_like(2 * RATE)])
    x = x + noise(rng, len(x), 0.002)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    for i in range(0, len(pcm) - CHUNK + 1, CHUNK):
        hub.publish(pcm[i:i + CHUNK].tobytes())
    got = [np.frombuffer(queue.get_nowait(), dtype="<i2") for _ in range(queue.qsize())]
    assert receiver.store.status.state == rc.OPEN
    assert np.max(np.abs(got[0])) == 0 and np.max(np.abs(got[-1])) > 1000          # silence en veille, voix une fois ouvert
    assert (tmp_path / "selcall.json").is_file()
