# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Visiteurs, lot 2 (docs/visiteurs-cahier-des-charges.md § 5 et § 6) : voix de l'opérateur pendant l'émission,
fondu aux bascules, silence hors bandes, files bornées, cadence du spectre HF plafonnée. Jamais de retard ni de panne
côté poste à cause d'un visiteur."""
import asyncio

import pytest

from trxstation.config import Access
from trxstation.gateway.audio.devices import RecordingSink
from trxstation.gateway.audio.listeners import TAP_FRAMES, TX_HOLD_S, ListenerMix, TapSink, TxTap, crossfade
from trxstation.gateway.audio.pcm import FRAME_BYTES, rms_dbfs, silence, to_samples, tone
from trxstation.spectrum.frame import SpectrumFanout

RX, VOICE = tone(440, -10), tone(1000, -10)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def mixer(muted=None):
    tap, clock = TxTap(), Clock()
    return tap, clock, ListenerMix(tap, muted, clock)


def test_reception_passes_and_the_operator_voice_takes_over_with_a_crossfade():
    tap, clock, mix = mixer()
    assert mix.next(RX) == RX and not mix.transmitting
    tap.publish(VOICE)
    first = mix.next(RX)
    assert mix.transmitting and first not in (RX, VOICE)                  # fondu : ni l'un ni l'autre
    assert to_samples(first)[0] == to_samples(RX)[0]                       # part du son du poste...
    assert abs(to_samples(first)[-1] - to_samples(VOICE)[-1]) <= abs(to_samples(VOICE)[-1]) * 0.01 + 2
    tap.publish(VOICE)
    clock.t += 0.02
    assert mix.next(RX) == VOICE                                           # ensuite : la voix telle quelle


def test_short_gaps_in_the_voice_stay_silent_then_reception_comes_back_faded_in():
    tap, clock, mix = mixer()
    tap.publish(VOICE)
    mix.next(RX)
    clock.t += 0.06                                                        # trame du réseau en retard : silence, pas le poste
    assert mix.next(RX) == silence() and mix.transmitting
    clock.t += TX_HOLD_S
    back = mix.next(RX)
    assert not mix.transmitting and back != RX and to_samples(back)[0] == 0   # fondu depuis le silence
    clock.t += 0.02
    assert mix.next(RX) == RX


def test_out_of_band_silences_the_rig_but_never_the_operator_voice():
    muted = [True]
    tap, clock, mix = mixer(lambda: muted[0])
    assert mix.next(RX) == silence()
    tap.publish(VOICE)
    mix.next(RX)
    tap.publish(VOICE)
    assert mix.next(RX) == VOICE


def test_tap_queues_are_bounded_split_into_frames_and_idle_without_listeners():
    tap = TxTap()
    tap.publish(VOICE)
    assert tap.frames == 0                                                 # aucun visiteur : aucune copie
    queue = tap.subscribe()
    tap.publish(VOICE * 3)                                                 # bips : plusieurs trames d'un coup
    assert len(queue) == 3
    for _ in range(30):
        tap.publish(VOICE)
    assert len(queue) == TAP_FRAMES                                        # visiteur qui ne lit plus : jamais plus de 200 ms
    tap.unsubscribe(queue)
    assert tap.subscribers == 0


def test_tap_sink_writes_to_the_rig_first_and_a_broken_tap_never_blocks_it():
    inner = RecordingSink()
    sink = TapSink(inner, TxTap())
    queue = sink.tap.subscribe()
    sink.write(VOICE)
    assert inner.frames == [VOICE] and list(queue) == [VOICE]
    sink.flush()
    assert inner.flushes == 1 and sink.frames is inner.frames              # le reste est délégué

    class Broken(TxTap):
        def publish(self, pcm):
            raise RuntimeError("visiteur en panne")
    broken = TapSink(inner, Broken())
    broken.write(RX)
    assert inner.frames[-1] == RX


def test_crossfade_goes_from_a_to_b():
    out = to_samples(crossfade(RX, silence()))
    assert out[0] == to_samples(RX)[0] and abs(out[-1]) <= abs(to_samples(RX)[-1]) // 50 + 1
    assert len(crossfade(RX, VOICE)) == FRAME_BYTES


def test_pipeline_gate_and_tail_feed_the_listeners():
    from trxstation.config import Audio
    from trxstation.gateway.audio import AudioPipeline
    from trxstation.gateway.audio.devices import SilenceSource
    sink = RecordingSink()
    pipeline = AudioPipeline(Audio(), source=SilenceSource(), sink=sink, owner_provider=lambda: "phone")
    queue = pipeline.tx_tap.subscribe()
    pipeline.gate.set_open(True)
    assert pipeline.gate.push("phone", VOICE) and not pipeline.gate.push("car", RX)
    assert sink.frames and len(queue) == 1 and rms_dbfs(queue[0]) > -20     # seul le propriétaire, après la porte
    pipeline.gate.set_open(False)
    assert not pipeline.gate.push("phone", VOICE) and len(queue) == 1      # porte fermée : rien vers les visiteurs


def test_listener_spectrum_rate_is_capped_while_the_operator_keeps_full_rate():
    clock = Clock()
    fanout = SpectrumFanout(10, clock)
    got = {"op": 0, "club1": 0}
    fps = [2]
    fanout.add("op", lambda f: got.__setitem__("op", got["op"] + 1), lambda: 0)
    fanout.add("club1", lambda f: got.__setitem__("club1", got["club1"] + 1), lambda: 0, lambda: fps[0])
    fanout.watch("op", True)
    fanout.watch("club1", True)
    from trxstation.spectrum.civ import Sweep
    sweep = Sweep(t=0.0, mode="center", f1_hz=14_000_000, f2_hz=14_050_000, out_of_range=False, points=[1, 2, 3, 4])
    for _ in range(50):                                                    # 5 s à 10 balayages par seconde
        fanout.publish(sweep)
        clock.t += 0.100001                                                # (arrondi des flottants)
    assert got["op"] == 50 and 9 <= got["club1"] <= 11
    fps[0] = 20                                                            # plafond relu à chaud, jamais au-delà de max_fps
    got["club1"] = 0
    for _ in range(10):
        fanout.publish(sweep)
        clock.t += 0.100001                                                # (arrondi des flottants)
    assert got["club1"] == 10


def test_listener_spectrum_fps_is_validated():
    from trxstation import config as cfgmod
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.access = Access(listener_spectrum_fps=0)
    assert any("listener_spectrum_fps" in p for p in cfgmod.validate(cfg))


def _aiortc():
    try:
        import aiohttp, aiortc, av  # noqa: F401
        return True
    except ImportError:
        return False


def test_webrtc_listener_hears_the_operator_voice_and_the_operator_never_hears_himself():
    if not _aiortc():
        return
    from trxstation.devtools.fake_client import FakeClient, ToneTrack
    from trxstation.devtools.loopback import LISTENER_PASSWORDS, PASSWORDS, Loopback
    from trxstation.gateway.audio.devices import SilenceSource

    async def until(predicate, timeout):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while not predicate():
            if loop.time() > end:
                raise AssertionError("condition jamais atteinte")
            await asyncio.sleep(0.02)

    async def scenario():
        async with Loopback(source=SilenceSource(), access=Access(max_listeners=2)) as lb:
            phone = FakeClient(lb.url, "phone", PASSWORDS["phone"], track=ToneTrack(1000.0, -10.0, active=True))
            await phone.connect()
            visitor = FakeClient(lb.url, "club1", LISTENER_PASSWORDS["club1"])
            await visitor.connect()
            await until(lambda: visitor.rx_frames >= 20, 10)
            await asyncio.sleep(0.5)
            assert not visitor.rx_loud_times                               # poste silencieux, pas d'émission : rien
            assert (await phone.command("toggle"))["ok"] and lb.fake.ptt == 1
            phone.start_heartbeat()
            await until(lambda: len(visitor.rx_loud_times) >= 10, 10)       # la voix de l'opérateur arrive au visiteur
            assert not phone.rx_loud_times                                 # ... jamais à l'opérateur lui-même
            assert (await phone.command("toggle"))["ok"] and lb.fake.ptt == 0
            await asyncio.sleep(0.6)
            heard = len(visitor.rx_loud_times)
            await asyncio.sleep(0.6)
            assert len(visitor.rx_loud_times) == heard                     # porte fermée : plus rien
            await visitor.close()
            await phone.close()
    asyncio.run(asyncio.wait_for(scenario(), 90))
