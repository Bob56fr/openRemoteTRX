"""Faux client (le rôle du smartphone) : connexion WebRTC complète à la passerelle.

Nécessite aiortc et aiohttp. Sert aux tests de bout en bout et à la mesure de latence.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
from fractions import Fraction

import aiohttp
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

from ..gateway.api.webrtc import as_list, frame_to_pcm, pcm_to_frame
from ..gateway.audio.devices import ClickSource, WavSink
from ..gateway.audio.pcm import FRAME_SAMPLES, SAMPLE_RATE, rms_dbfs, silence, tone

import av


class ToneTrack(MediaStreamTrack):
    """Micro simulé : une tonalité (ou du silence tant que `active` est faux), cadencée en temps réel."""

    kind = "audio"

    def __init__(self, freq_hz: float = 1000.0, level_db: float = -20.0, active: bool = True):
        super().__init__()
        self.freq_hz, self.level_db, self.active = freq_hz, level_db, active
        self._pts, self._start = 0, None

    def _pcm(self) -> bytes:
        return tone(self.freq_hz, self.level_db, self._pts) if self.active else silence()

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        if self._start is None:
            self._start = time.monotonic()
        else:
            wait = self._start + self._pts / SAMPLE_RATE - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        frame = pcm_to_frame(self._pcm())
        frame.pts, frame.time_base = self._pts, Fraction(1, SAMPLE_RATE)
        self._pts += FRAME_SAMPLES
        return frame


class ClickTrack(ToneTrack):
    """Micro simulé qui émet des salves de 10 ms (mesure de latence) ; mémorise leurs instants."""

    def __init__(self, period_s: float = 1.0):
        super().__init__(active=True)
        self._clicks = ClickSource(period_s)

    @property
    def click_times(self) -> list[float]:
        return self._clicks.click_times

    def _pcm(self) -> bytes:
        return self._clicks._frame()


class FakeClient:
    def __init__(self, base_url: str, client_id: str, password: str, *, track: ToneTrack | None = None,
                 record_wav: str | None = None):
        self._recorder = WavSink(record_wav) if record_wav else None
        self.base_url, self.client_id, self.password = base_url.rstrip("/"), client_id, password
        self.track = track or ToneTrack(active=False)
        self.pc = RTCPeerConnection()
        self.channel = None
        self.messages: list[dict] = []
        self.state: dict | None = None
        self.hello: dict | None = None
        self.rx_frames = 0
        self.spectrum_frames: list[bytes] = []      # balayages reçus sur le canal « spectrum » (binaire)
        self.rx_loud_times: list[float] = []         # instants où une salve/tonalité est arrivée
        self._ids = itertools.count(1)
        self._waiting: dict[int, asyncio.Future] = {}
        self._tasks: list[asyncio.Task] = []
        self._opened = asyncio.Event()

    async def connect(self, timeout: float = 15.0) -> None:
        self.pc.addTrack(self.track)
        self.channel = self.pc.createDataChannel("control")
        self.spectrum_channel = self.pc.createDataChannel("spectrum", ordered=False, maxRetransmits=0)

        @self.spectrum_channel.on("message")
        def on_spectrum(raw) -> None:
            if isinstance(raw, (bytes, bytearray)):
                self.spectrum_frames.append(bytes(raw))

        @self.channel.on("open")
        def on_open() -> None:
            self._opened.set()

        @self.channel.on("message")
        def on_message(raw) -> None:
            message = json.loads(raw)
            self.messages.append(message)
            if message.get("type") == "hello":
                self.hello = message
            elif message.get("type") == "state":
                self.state = message
            elif message.get("type") == "result" and message.get("id") in self._waiting:
                self._waiting.pop(message["id"]).set_result(message)

        @self.pc.on("track")
        def on_track(track) -> None:
            if track.kind == "audio":
                self._tasks.append(asyncio.ensure_future(self._consume(track)))

        await self.pc.setLocalDescription(await self.pc.createOffer())
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{self.base_url}/offer", json={
                    "client_id": self.client_id, "password": self.password,
                    "sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}) as response:
                if response.status != 200:
                    raise ConnectionRefusedError(f"offre refusée : HTTP {response.status}")
                answer = await response.json()
        await self.pc.setRemoteDescription(RTCSessionDescription(**answer))
        await asyncio.wait_for(self._opened.wait(), timeout)
        deadline = time.monotonic() + timeout
        while self.hello is None and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        if self.hello is None:
            raise TimeoutError("pas de « hello » de la passerelle")

    async def _consume(self, track) -> None:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        try:
            while True:
                frame = await track.recv()
                for out in as_list(resampler.resample(frame)):
                    pcm = frame_to_pcm(out)
                    self.rx_frames += 1
                    if self._recorder is not None:
                        self._recorder.write(pcm)
                    if rms_dbfs(pcm) > -25.0:
                        self.rx_loud_times.append(time.monotonic())
        except MediaStreamError:
            pass

    async def command(self, name: str, timeout: float = 5.0, **params) -> dict:
        ident = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._waiting[ident] = future
        self.channel.send(json.dumps({"cmd": name, "id": ident, **params}))
        return await asyncio.wait_for(future, timeout)

    def start_heartbeat(self, every_s: float = 0.2) -> asyncio.Task:
        async def beat() -> None:
            while True:
                self.channel.send(json.dumps({"cmd": "heartbeat"}))
                await asyncio.sleep(every_s)
        task = asyncio.ensure_future(beat())
        self._tasks.append(task)
        return task

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await self.pc.close()
        except asyncio.InvalidStateError:
            pass                                       # aiortc : fermeture simultanée, sans conséquence
        if self._recorder is not None:
            self._recorder.close()
