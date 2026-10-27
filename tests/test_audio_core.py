# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Cœur audio de la passerelle : tout ce qui ne dépend ni d'aiortc ni d'une vraie carte son."""
import asyncio
import threading
import wave
from array import array

import pytest

from trxstation.audio_devices import resolve_device
from trxstation.config import Audio
from trxstation.devtools.latency_math import describe, latencies
from trxstation.gateway.audio import AudioConfigError, AudioPipeline, RxHub, TxAudioGate, make_sink, make_source
from trxstation.gateway.audio.devices import (ClickDetectSink, ClickSource, NullSink, RecordingSink,
                                              SilenceSource, SoundDeviceSink, SoundDeviceSource, ToneSource,
                                              WavFileSource, WavSink, _Pacer)
from trxstation.gateway.audio.levels import LevelMeter
from trxstation.gateway.audio.pcm import (FLOOR_DB, FRAME_BYTES, FRAME_SAMPLES, FrameAssembler, apply_gain,
                                          downmix_stereo, rms_dbfs, silence, to_bytes, to_samples, tone)
from trxstation.gateway.audio.ring import RingBuffer


def frame(value=1000):
    return to_bytes(array("h", [value] * FRAME_SAMPLES))


# --------------------------------------------------------------------------- PCM

def test_levels_of_known_signals():
    assert rms_dbfs(silence()) == FLOOR_DB and rms_dbfs(b"") == FLOOR_DB
    square = to_bytes(array("h", [32767, -32768] * (FRAME_SAMPLES // 2)))
    assert rms_dbfs(square) > -0.1
    assert -23.5 < rms_dbfs(tone(1000, -20)) < -22.5          # sinus : crête -20 dBFS = efficace -23 dBFS


def test_gain_scales_and_clips():
    assert apply_gain(frame(1000), 0) == frame(1000)
    assert to_samples(apply_gain(frame(1000), 6.0206))[0] == 1999 or to_samples(apply_gain(frame(1000), 6.0206))[0] == 2000
    assert to_samples(apply_gain(frame(1000), -6.0206))[0] in (499, 500)
    assert to_samples(apply_gain(frame(30000), 12.0))[0] == 32767
    assert to_samples(apply_gain(frame(-30000), 12.0))[0] == -32768


def test_tone_is_continuous_across_frames():
    first, second = tone(1000, -10, 0), tone(1000, -10, FRAME_SAMPLES)
    assert first + second == tone(1000, -10, 0, FRAME_SAMPLES * 2)


def test_stereo_downmix_averages_channels():
    stereo = to_bytes(array("h", [1000, 3000, -2000, 2000]))
    assert list(to_samples(downmix_stereo(stereo))) == [2000, 0]


def test_frame_assembler_rechunks_exactly_and_bounds_backlog():
    assembler = FrameAssembler()
    assert assembler.feed(bytes(1000)) == []
    frames = assembler.feed(bytes(FRAME_BYTES * 2 - 1000))
    assert len(frames) == 2 and all(len(f) == FRAME_BYTES for f in frames)
    assert assembler.feed(bytes(FRAME_BYTES - 1)) == [] and len(assembler.feed(b"\x01")) == 1
    flood = FrameAssembler(max_backlog_frames=5)
    stream = b"".join(frame(i) for i in range(1, 21))
    out = flood.feed(stream)
    assert len(out) == 5 and out[-1] == frame(20)             # on garde le plus récent


# --------------------------------------------------------------------------- tampon, niveaux

def test_ring_buffer_keeps_newest_and_pads_underruns():
    ring = RingBuffer(10)
    ring.write(b"0123456789")
    ring.write(b"AB")
    assert ring.read(10) == b"23456789AB" and ring.overruns == 1
    assert ring.read(4) == bytes(4) and ring.underruns == 1
    ring.write(b"xyz")
    ring.clear()
    assert len(ring) == 0


def test_ring_buffer_is_thread_safe():
    ring = RingBuffer(100_000)

    def writer():
        for _ in range(500):
            ring.write(b"a" * 10)
    threads = [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ring) == 20_000


def test_level_meter_attacks_instantly_and_releases_slowly():
    now = [0.0]
    meter = LevelMeter(release_db_per_s=30.0, clock=lambda: now[0])
    loud = meter.update(tone(1000, -6))
    assert loud > -10
    now[0] = 1.0
    assert loud - 31 < meter.update(silence()) < loud - 29     # retombée de 30 dB en 1 s
    now[0] = 10.0
    assert meter.update(silence()) == FLOOR_DB
    meter.update(tone(1000, -6))
    meter.reset()
    assert meter.value == FLOOR_DB


# --------------------------------------------------------------------------- porte d'émission

def make_gate(owner="phone", gain=0.0):
    sink = RecordingSink()
    gate = TxAudioGate(sink, gain_db=gain, owner_provider=lambda: owner)
    return gate, sink


def test_closed_gate_drops_everything():
    gate, sink = make_gate()
    assert gate.push("phone", frame()) is False
    assert sink.frames == [] and gate.dropped_closed == 1


def test_open_gate_passes_only_the_owner():
    gate, sink = make_gate(owner="phone")
    gate.set_open(True)
    assert gate.push("phone", frame()) is True
    assert gate.push("car", frame()) is False and gate.push("intrus", frame()) is False
    assert len(sink.frames) == 1 and gate.passed == 1 and gate.dropped_not_owner == 2


def test_gate_without_owner_drops_even_when_open():
    gate = TxAudioGate(RecordingSink())
    gate.set_open(True)
    assert gate.push("phone", frame()) is False


def test_closing_flushes_sink_and_resets_meter_once():
    gate, sink = make_gate()
    gate.set_open(True)
    gate.push("phone", tone(1000, -6))
    assert gate.meter.value > -20
    gate.set_open(False)
    gate.set_open(False)
    assert sink.flushes == 1 and gate.meter.value == FLOOR_DB


def test_gate_applies_tx_gain():
    gate, sink = make_gate(gain=6.0206)
    gate.set_open(True)
    gate.push("phone", frame(1000))
    assert to_samples(sink.frames[0])[0] in (1999, 2000)


# --------------------------------------------------------------------------- diffusion RX

class ListSource:
    def __init__(self, frames):
        self._frames = list(frames)

    async def start(self): pass
    async def stop(self): pass

    async def read(self):
        return self._frames.pop(0) if self._frames else None


def test_hub_fans_out_to_every_subscriber_and_stops_when_unsubscribed():
    async def scenario():
        hub = RxHub(ListSource([]))
        a, b = hub.subscribe(), hub.subscribe()
        hub.publish(frame(1))
        hub.publish(frame(2))
        assert [a.get_nowait(), a.get_nowait()] == [frame(1), frame(2)]
        assert b.qsize() == 2
        hub.unsubscribe(b)
        hub.publish(frame(3))
        assert b.qsize() == 2 and a.qsize() == 1 and hub.subscribers == 1
    asyncio.run(scenario())


def test_hub_drops_oldest_for_a_slow_client():
    async def scenario():
        hub = RxHub(ListSource([]))
        slow = hub.subscribe(maxsize=2)
        for i in range(1, 6):
            hub.publish(frame(i))
        assert slow.qsize() == 2 and hub.dropped == 3
        assert slow.get_nowait() == frame(4) and slow.get_nowait() == frame(5)   # on garde le temps réel
    asyncio.run(scenario())


def test_hub_run_consumes_source_until_it_ends_and_applies_gain():
    async def scenario():
        hub = RxHub(ListSource([frame(1000), frame(1000)]), gain_db=6.0206)
        queue = hub.subscribe()
        await asyncio.wait_for(hub.run(), 2)
        assert hub.frames == 2 and to_samples(queue.get_nowait())[0] in (1999, 2000)
        assert hub.meter.value > FLOOR_DB
    asyncio.run(scenario())


# --------------------------------------------------------------------------- sources et puits

def test_pacer_keeps_a_steady_20ms_rhythm_and_resynchronises_after_a_stall():
    now, slept = [100.0], []

    async def fake_sleep(delay):
        slept.append(round(delay, 4))
        now[0] += delay

    async def scenario():
        pacer = _Pacer(clock=lambda: now[0], sleep=fake_sleep)
        await pacer.wait()                                    # première trame : immédiate
        await pacer.wait()
        await pacer.wait()
        assert slept == [0.02, 0.02]
        now[0] += 5.0                                         # grosse panne : on repart de zéro, sans rafale
        slept.clear()
        await pacer.wait()
        await pacer.wait()
        assert slept == [0.02]
    asyncio.run(scenario())


def test_tone_and_click_sources():
    tone_source = ToneSource(1000, -10)
    assert tone_source._frame() + tone_source._frame() == tone(1000, -10, 0, FRAME_SAMPLES * 2)
    clicks = ClickSource(period_s=0.1)                        # une salve toutes les 5 trames
    frames = [clicks._frame() for _ in range(11)]
    loud = [i for i, f in enumerate(frames) if rms_dbfs(f) > -20]
    assert loud == [0, 5, 10] and len(clicks.click_times) == 3
    assert rms_dbfs(frames[0][: FRAME_BYTES // 2]) > -10 and rms_dbfs(frames[0][FRAME_BYTES // 2:]) == FLOOR_DB


def write_wav(path, samples, channels=1, rate=48000, width=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(to_bytes(array("h", samples)) if width == 2 else bytes(samples))


def test_wav_source_loops_downmixes_and_validates(tmp_path):
    mono = tmp_path / "mono.wav"
    write_wav(mono, [100] * (FRAME_SAMPLES * 2 + 10))
    source = WavFileSource(str(mono))
    frames = [source._frame() for _ in range(4)]
    assert all(len(f) == FRAME_BYTES for f in frames)
    assert to_samples(frames[0])[0] == 100 and to_samples(frames[2])[9] == 100 and to_samples(frames[2])[10] == 0
    assert frames[3] == frames[0]                             # boucle

    stereo = tmp_path / "stereo.wav"
    write_wav(stereo, [1000, 3000] * FRAME_SAMPLES, channels=2)
    assert to_samples(WavFileSource(str(stereo))._frame())[0] == 2000

    once = WavFileSource(str(mono), loop=False)
    for _ in range(3):
        once._frame()
    assert once._frame() == silence()

    for name, kwargs in (("rate.wav", dict(rate=44100)), ("wide.wav", dict(width=1))):
        bad = tmp_path / name
        write_wav(bad, [0] * 100 if kwargs.get("width") != 1 else [0] * 100, **kwargs)
        with pytest.raises(AudioConfigError):
            WavFileSource(str(bad))
    with pytest.raises(AudioConfigError):
        WavFileSource(str(tmp_path / "absent.wav"))


def test_wav_sink_writes_a_readable_file(tmp_path):
    path = tmp_path / "tx.wav"
    sink = WavSink(str(path))
    sink.write(frame(5))
    sink.write(frame(6))
    sink.flush()
    sink.close()
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 48000, FRAME_SAMPLES * 2)
    with pytest.raises(AudioConfigError):
        WavSink(str(tmp_path / "pas_un_dossier" / "x.wav"))


def test_click_detect_sink_notes_each_burst_once():
    sink = ClickDetectSink(hold_s=0.5)
    sink.write(silence())
    sink.write(tone(1000, -3))
    sink.write(tone(1000, -3))                                # même salve : pas de doublon
    assert len(sink.click_times) == 1 and len(sink.frames) == 3


def test_factories_parse_specs(tmp_path):
    assert isinstance(make_source(""), SilenceSource) and isinstance(make_source("  "), SilenceSource)
    assert make_source("tone:440").freq_hz == 440.0 and make_source("click:2").period_frames == 100
    wav = tmp_path / "a.wav"
    write_wav(wav, [0] * FRAME_SAMPLES)
    assert isinstance(make_source(f"file:{wav}"), WavFileSource)
    with pytest.raises(AudioConfigError):
        make_source("tone:abc")
    assert isinstance(make_sink(""), NullSink) and isinstance(make_sink("null"), NullSink)
    sink = make_sink(f"file:{tmp_path / 'out.wav'}")
    assert isinstance(sink, WavSink)
    sink.close()
    assert isinstance(make_source("Mon périphérique"), SoundDeviceSource)


# --------------------------------------------------------------------------- périphériques simulés

class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs, self.callback = kwargs, kwargs["callback"]
        self.started = self.stopped = self.closed = False

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def close(self): self.closed = True


class FakeSd:
    def __init__(self, devices, hostapis=("MME", "Windows WASAPI")):
        self._devices, self._hostapis = devices, list(hostapis)
        self.inputs, self.outputs = [], []

    def query_devices(self, index=None):
        return self._devices if index is None else self._devices[index]

    def query_hostapis(self, index=None):
        apis = [{"name": n} for n in self._hostapis]
        return apis if index is None else apis[index]

    def RawInputStream(self, **kwargs):
        self.inputs.append(FakeStream(**kwargs))
        return self.inputs[-1]

    def RawOutputStream(self, **kwargs):
        self.outputs.append(FakeStream(**kwargs))
        return self.outputs[-1]


DEVICES = [
    {"name": "Micro (USB Audio CODEC)", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
    {"name": "Micro (USB Audio CODEC)", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 0},
    {"name": "Haut-parleurs (USB Audio CODEC)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
]


def test_resolve_device_prefers_best_api_and_accepts_substrings():
    sd = FakeSd(DEVICES)
    assert resolve_device("Micro (USB Audio CODEC)", "capture", sd) == 1            # WASAPI avant MME
    assert resolve_device("usb audio codec", "capture", sd) == 1                    # sous-chaîne, sans casse
    assert resolve_device("haut-parleurs", "playback", sd) == 2
    with pytest.raises(LookupError):
        resolve_device("Inconnu", "capture", sd)
    with pytest.raises(LookupError):
        resolve_device("Haut-parleurs", "capture", sd)                              # pas une entrée


def test_sounddevice_source_delivers_frames_and_counts_overruns():
    async def scenario():
        sd = FakeSd(DEVICES)
        source = SoundDeviceSource("usb audio codec", sd)
        await source.start()
        stream = sd.inputs[0]
        assert stream.started and stream.kwargs["device"] == 1 and stream.kwargs["samplerate"] == 48000
        assert stream.kwargs["blocksize"] == FRAME_SAMPLES and stream.kwargs["dtype"] == "int16"
        stream.callback(frame(7), FRAME_SAMPLES, None, None)
        assert await asyncio.wait_for(source.read(), 1) == frame(7)
        stream.callback(frame(1), FRAME_SAMPLES, None, "input overflow")           # statut PortAudio
        for _ in range(60):
            stream.callback(frame(2), FRAME_SAMPLES, None, None)
        await asyncio.sleep(0.05)                                                   # callbacks planifiés dans la boucle
        assert source.xruns == 1 and source.overruns >= 10
        await source.stop()
        assert stream.stopped and stream.closed
        with pytest.raises(AudioConfigError):
            await SoundDeviceSource("Inconnu", sd).start()
    asyncio.run(scenario())


def test_sounddevice_sink_plays_from_ring_and_flushes():
    sd = FakeSd(DEVICES)
    sink = SoundDeviceSink("haut-parleurs", sd)
    sink.open()
    stream = sd.outputs[0]
    assert stream.started and stream.kwargs["device"] == 2
    sink.write(frame(9))
    out = bytearray(FRAME_BYTES)
    stream.callback(out, FRAME_SAMPLES, None, None)
    assert bytes(out) == frame(9)
    sink.write(frame(9))
    sink.flush()                                                                    # coupure : plus de reste de son
    stream.callback(out, FRAME_SAMPLES, None, None)
    assert bytes(out) == silence()
    for _ in range(20):                                                             # retard borné à 150 ms
        sink.write(frame(1))
    assert len(sink._ring) <= int(48000 * 2 * 0.15)
    sink.close()
    assert stream.closed
    with pytest.raises(AudioConfigError):
        SoundDeviceSink("Inconnu", sd).open()


# --------------------------------------------------------------------------- pipeline

def test_pipeline_streams_rx_and_reports_stats():
    async def scenario():
        sink = RecordingSink()
        pipeline = AudioPipeline(Audio(), source=ToneSource(1000, -10), sink=sink)
        await pipeline.start()
        queue = pipeline.hub.subscribe()
        frames = [await asyncio.wait_for(queue.get(), 2) for _ in range(3)]
        assert all(len(f) == FRAME_BYTES for f in frames)
        stats = pipeline.stats()
        assert set(stats) == {"rx_db", "tx_db", "gate_open", "listeners", "rx_dropped", "tx_dropped_not_owner",
                              "rx_frames", "tx_frames", "tx_dropped_closed"}
        assert stats["rx_frames"] >= 3 and stats["tx_frames"] == 0
        assert stats["rx_db"] > -20 and stats["listeners"] == 1 and stats["gate_open"] is False
        pipeline.gate.owner_provider = lambda: "phone"
        pipeline.gate.set_open(True)
        assert pipeline.stats()["gate_open"] is True
        await pipeline.stop()
        assert pipeline.gate.is_open is False                                       # l'arrêt ferme la porte
    asyncio.run(scenario())


def test_pipeline_default_config_is_silent_and_safe():
    async def scenario():
        pipeline = AudioPipeline(Audio())
        assert isinstance(pipeline.source, SilenceSource) and isinstance(pipeline.sink, NullSink)
        await pipeline.start()
        await pipeline.stop()
    asyncio.run(scenario())


# --------------------------------------------------------------------------- mesure de latence

def test_latency_math():
    values = latencies([1.0, 2.0, 3.0, 10.0], [1.045, 2.05, 3.04, 5.0])
    assert [round(v, 3) for v in values] == [0.045, 0.05, 0.04]                     # 5.0 : trop loin de 3.0, ignoré
    assert "médiane 45 ms" in describe("RX", values) and "aucune mesure" in describe("TX", [])
