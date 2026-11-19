# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Gain et limiteur du son reçu (étape 295) : `[audio] rx_gain_db` / `rx_limiter`, RxHub, menu 2.9 de la console."""
from __future__ import annotations

import math
from array import array
from types import SimpleNamespace

from trxstation import config as cfgmod
from trxstation.gateway.audio.hub import RxHub
from trxstation.gateway.audio.limiter import CEILING_DBFS
from trxstation.gateway.audio.pcm import FRAME_SAMPLES, to_samples
from trxstation.profiles import MIGRATIONS, PROFILE_FORMAT

CEILING = 32768 * 10 ** (CEILING_DBFS / 20)


def sine(level_dbfs: float, freq: float = 1000.0, start: int = 0) -> bytes:
    amp = 32767 * 10 ** (level_dbfs / 20)
    return array("h", (int(amp * math.sin(2 * math.pi * freq * (start + i) / 48000))
                       for i in range(FRAME_SAMPLES))).tobytes()


def run_frames(hub: RxHub, level_dbfs: float, n: int = 25) -> list[int]:
    queue = hub.subscribe(maxsize=n)
    for k in range(n):
        hub.publish(sine(level_dbfs, start=k * FRAME_SAMPLES))
    out: list[int] = []
    while not queue.empty():
        out.extend(to_samples(queue.get_nowait()))
    return out


def test_a_strong_gain_on_a_loud_signal_never_goes_above_the_ceiling_and_the_meter_shows_it():
    hub = RxHub(source=None, gain_db=20.0)                       # -6 dBFS + 20 dB : 14 dB au-dessus du plafond
    samples = run_frames(hub, -6.0)
    assert max(abs(s) for s in samples) <= CEILING + 1
    assert hub.limited > 0
    assert hub.meter.value > 0                                   # niveau sans plafond : la saturation se voit


def test_limiter_off_keeps_the_old_behaviour_clipping_included():
    hub = RxHub(source=None, gain_db=20.0, limiter=False)
    samples = run_frames(hub, -6.0)
    assert max(abs(s) for s in samples) >= 32767                 # écrêté en 16 bits, comme avant l'étape 295
    assert hub.limited == 0 and hub.limiter is None


def test_the_limiter_does_not_touch_a_signal_below_the_ceiling():
    with_limiter, without = RxHub(source=None, gain_db=10.0), RxHub(source=None, gain_db=10.0, limiter=False)
    a, b = run_frames(with_limiter, -30.0), run_frames(without, -30.0)
    assert with_limiter.limited == 0
    assert max(abs(x - y) for x, y in zip(a, b)) <= 1            # arrondi près : même son


def test_decoders_get_the_limited_sound_not_a_clipped_one():
    hub = RxHub(source=None, gain_db=20.0)
    seen: list[int] = []

    def processor(pcm: bytes) -> bytes:
        seen.extend(to_samples(pcm))
        return pcm
    hub.processor = processor
    run_frames(hub, -6.0)
    assert seen and max(abs(s) for s in seen) <= CEILING + 1


def test_station_toml_limiter_is_on_by_default_written_and_checked():
    cfg = cfgmod.Config()
    assert cfg.audio.rx_limiter is True
    assert "rx_limiter = true" in cfgmod.render_toml(cfg)
    cfg.audio.rx_limiter = "oui"
    assert any("rx_limiter" in p for p in cfgmod.validate(cfg))


def test_pipeline_publishes_gain_and_limiter_figures():
    from trxstation.gateway.audio.pipeline import AudioPipeline
    pipeline = AudioPipeline(cfgmod.Audio(rx_gain_db=6.0, rx_limiter=False), source=object(),
                             sink=SimpleNamespace(close=lambda: None))
    stats = pipeline.stats()
    assert stats["rx_gain_db"] == 6.0 and stats["rx_limiter"] is False and stats["rx_limited"] == 0


def test_an_old_profile_gets_the_limiter_on():
    sections = {"rig": {}, "audio": {"rx_gain_db": 3.0}, "spectrum": {}}
    assert PROFILE_FORMAT == 4 and MIGRATIONS[3](sections)["audio"]["rx_limiter"] is True


def test_console_menu_2_9_proposes_a_gain_from_the_received_level_and_writes_station_toml(tmp_path, monkeypatch):
    from test_console_tools import make, write_config
    from trxstation.console import Console, menu_number
    assert menu_number("rx_gain") == "2.9"
    path = write_config(tmp_path)
    status = SimpleNamespace(audio={"rx_db": -40, "rx_gain_db": 0.0, "rx_limited": 0, "rx_frames": 100})
    monkeypatch.setattr(Console, "_gateway_status", lambda self: status)
    con, fake, out = make(tmp_path, answers=["12", "", "o"])     # gain 12 dB, limiter gardé, enregistrer
    con.rx_gain()
    text = "\n".join(out)
    assert "-40 dBFS" in text and "+20 dB" in text               # -20 visé - (-40) = +20 proposé
    cfg = cfgmod.load(path)
    assert cfg.audio.rx_gain_db == 12.0 and cfg.audio.rx_limiter is True


def test_console_menu_2_9_accepts_a_negative_gain_and_warns_when_the_limiter_is_off(tmp_path, monkeypatch):
    from test_console_tools import make, write_config
    from trxstation.console import Console
    path = write_config(tmp_path)
    monkeypatch.setattr(Console, "_gateway_status", lambda self: None)
    con, fake, out = make(tmp_path, answers=["-6", "n", "o"])
    con.rx_gain()
    text = "\n".join(out)
    assert "inconnu" in text and "ATTENTION" in text
    cfg = cfgmod.load(path)
    assert cfg.audio.rx_gain_db == -6.0 and cfg.audio.rx_limiter is False


def test_console_menu_2_9_refuses_a_gain_out_of_bounds(tmp_path, monkeypatch):
    from test_console_tools import make, write_config
    from trxstation.console import Console
    path = write_config(tmp_path)
    monkeypatch.setattr(Console, "_gateway_status", lambda self: None)
    con, fake, out = make(tmp_path, answers=["25", "-41", "3", "", "o"])
    con.rx_gain()
    assert sum("-40" in line and "20" in line for line in out) >= 2   # refus à la question, bornes données
    assert cfgmod.load(path).audio.rx_gain_db == 3.0
