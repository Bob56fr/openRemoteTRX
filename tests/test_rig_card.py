# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Carte son du poste qui disparaît et revient (gateway/audio/rigcard.py ; minix-bzh, 2026-11-19 : poste débranché
= passerelle arrêtée puis mode sûr). Tests de panne avec la VRAIE sécurité PTT et le faux poste Hamlib : carte
absente au démarrage (émission refusée, aucune émission), carte retrouvée (émission permise), carte perdue PENDANT
une émission (coupure `audio_lost`, micro fermé), annonces ORT-3012 / ORT-3013 une seule fois par absence."""
from __future__ import annotations

import asyncio
import threading

from test_safety import beating, refusal, run, station, until

from trxstation.gateway.audio import rigcard
from trxstation.gateway.audio.rigcard import RigCard

CARD = "USB Audio Device: - (hw:0,0)"


class FakeStream:
    """Flux PortAudio factice : appelle le rappel d'un fil, comme PortAudio, tant que la carte est branchée."""

    def __init__(self, sd, kwargs):
        self.sd, self.kwargs, self.alive = sd, kwargs, False

    def start(self):
        self.alive = True
        if "callback" in self.kwargs and self.sd.is_input(self.kwargs):
            threading.Thread(target=self._feed, daemon=True).start()

    def _feed(self):
        import time
        while self.alive and self.sd.plugged:
            self.kwargs["callback"](bytes(1920), 960, None, None)
            time.sleep(0.02)

    def stop(self):
        self.alive = False

    def close(self):
        self.alive = False


class FakeSd:
    def __init__(self, plugged=True):
        self.plugged = plugged
        self.streams = []

    def is_input(self, kwargs):
        return kwargs.get("_input", False)

    def query_hostapis(self, index=None):
        apis = [{"name": "ALSA"}]
        return apis if index is None else apis[index]

    def query_devices(self, index=None):
        devices = [{"name": CARD, "hostapi": 0, "max_input_channels": 1, "max_output_channels": 2}] if self.plugged else []
        devices.append({"name": "HDA Intel PCH: ALC897 Analog (hw:1,0)", "hostapi": 0, "max_input_channels": 2,
                        "max_output_channels": 2})
        return devices if index is None else devices[index]

    def RawInputStream(self, **kwargs):
        s = FakeStream(self, dict(kwargs, _input=True))
        self.streams.append(s)
        return s

    def RawOutputStream(self, **kwargs):
        s = FakeStream(self, kwargs)
        self.streams.append(s)
        return s


def _card(sd, alerts):
    card = RigCard(CARD, CARD, sd, alert=lambda code, detail: alerts.append(code), retry_s=0.1, stall_s=0.5)
    return card


def test_a_missing_card_refuses_transmission_then_the_card_found_again_allows_it():
    alerts: list[str] = []

    async def scenario(fake):
        sd = FakeSd(plugged=False)
        card = _card(sd, alerts)
        async with station(fake) as (ctrl, link, gate):
            ctrl.audio_ready = lambda: card.available
            assert await card.open() is False                    # au démarrage : absente, la passerelle continue
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            stop = asyncio.Event()
            watch = asyncio.ensure_future(card.watch(stop))
            try:
                assert await refusal(ctrl.toggle("phone")) == "audio_missing"
                await asyncio.sleep(0.35)                        # plusieurs recherches : UNE seule annonce
                assert fake.ptt == 0 and alerts == ["ORT-3012"]
                sd.plugged = True                                # poste rebranché
                await until(lambda: card.available)
                assert alerts == ["ORT-3012", "ORT-3013"]
                await ctrl.toggle("phone")
                assert ctrl.snapshot().state == "TX" and fake.ptt == 1
                await ctrl.toggle("phone")
                await until(lambda: fake.ptt == 0)
            finally:
                stop.set()
                beat.cancel()
                await asyncio.gather(watch, return_exceptions=True)
                await card.close()
    run(scenario)


def test_a_card_lost_during_a_transmission_cuts_it_and_closes_the_microphone():
    alerts: list[str] = []

    async def scenario(fake):
        sd = FakeSd(plugged=True)
        card = _card(sd, alerts)
        async with station(fake) as (ctrl, link, gate):
            ctrl.audio_ready = lambda: card.available
            card.on_lost = lambda: asyncio.get_running_loop().create_task(ctrl.force_rx("audio_lost"))
            assert await card.open() is True and alerts == []    # présente : aucune annonce
            reader = asyncio.ensure_future(_read_forever(card))
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            try:
                await ctrl.toggle("phone")
                assert ctrl.snapshot().state == "TX" and fake.ptt == 1
                sd.plugged = False                               # câble USB du poste retiré pendant l'émission
                await until(lambda: ctrl.snapshot().state == "RX", timeout=5.0)
                assert fake.ptt == 0 and ctrl.snapshot().last_cut_reason == "audio_lost"
                assert gate[-1][0] is False                      # micro du client fermé
                assert not card.available and alerts == ["ORT-3012"]
                assert await refusal(ctrl.toggle("phone")) == "audio_missing"
            finally:
                beat.cancel()
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
                await card.close()
    run(scenario)


async def _read_forever(card):
    while True:
        await card.source.read()                                 # comme RxHub : lit la source sans fin


def test_the_missing_card_gives_silence_at_real_time_pace_without_error():
    async def scenario():
        card = RigCard(CARD, CARD, FakeSd(plugged=False), retry_s=0.1, stall_s=0.5)
        await card.source.start()                                # ne lève rien : la passerelle démarre
        frame = await asyncio.wait_for(card.source.read(), 1.0)
        assert frame == rigcard.SILENCE
        card.sink.write(b"\x01\x02" * 960)                       # jeté sans erreur
        assert card.sink.underruns == 0 and card.source.xruns == 0
        await card.source.stop()
    asyncio.run(scenario())
