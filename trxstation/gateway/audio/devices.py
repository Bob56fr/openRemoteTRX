# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sources (son reçu du poste) et puits (son envoyé au poste).

Pour le développement sans matériel : `file:rx.wav` (boucle un WAV 48 kHz 16 bits), `tone:1000`,
`click:1.0`, et côté sortie `file:tx.wav` ou `null`. Un autre texte = nom d'un périphérique
audio (sounddevice / PortAudio). Les trames font toujours 20 ms (960 échantillons mono).
"""
from __future__ import annotations

import asyncio
import time
import wave
from collections.abc import Callable

from ...audio_devices import resolve_device
from .pcm import (FRAME_BYTES, FRAME_S, FRAME_SAMPLES, SAMPLE_RATE, downmix_stereo, rms_dbfs, silence, tone)
from .ring import RingBuffer


class AudioConfigError(Exception):
    pass


class _Pacer:
    """Cadence temps réel : une trame toutes les 20 ms, sans dérive cumulée."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep=asyncio.sleep):
        self._clock, self._sleep, self._next = clock, sleep, None

    async def wait(self) -> None:
        now = self._clock()
        if self._next is None or now - self._next > 1.0:      # premier appel, ou grosse panne : on resynchronise
            self._next = now
        else:
            self._next += FRAME_S
            delay = self._next - now
            if delay > 0:
                await self._sleep(delay)


class _PacedSource:
    async def start(self) -> None:
        self._pacer = _Pacer()

    async def stop(self) -> None:
        pass

    def _frame(self) -> bytes:
        raise NotImplementedError

    async def read(self) -> bytes:
        await self._pacer.wait()
        return self._frame()


class SilenceSource(_PacedSource):
    def __init__(self):
        self._pacer = _Pacer()

    def _frame(self) -> bytes:
        return silence()


class ToneSource(_PacedSource):
    def __init__(self, freq_hz: float = 1000.0, level_db: float = -20.0):
        self.freq_hz, self.level_db, self._pos = freq_hz, level_db, 0
        self._pacer = _Pacer()

    def _frame(self) -> bytes:
        frame = tone(self.freq_hz, self.level_db, self._pos)
        self._pos += FRAME_SAMPLES
        return frame


class ClickSource(_PacedSource):
    """Silence avec une salve de 10 ms toutes les `period_s` ; mémorise l'instant de chaque salve."""

    def __init__(self, period_s: float = 1.0, level_db: float = -3.0):
        self.period_frames = max(2, round(period_s / FRAME_S))
        self.level_db, self._count = level_db, 0
        self.click_times: list[float] = []
        self._pacer = _Pacer()

    def _frame(self) -> bytes:
        index, self._count = self._count, self._count + 1
        if index % self.period_frames:
            return silence()
        self.click_times.append(time.monotonic())
        return tone(1000.0, self.level_db, 0, FRAME_SAMPLES // 2) + silence(FRAME_SAMPLES // 2)


class WavFileSource(_PacedSource):
    def __init__(self, path: str, loop: bool = True):
        try:
            with wave.open(path, "rb") as wav:
                channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
                raw = wav.readframes(wav.getnframes())
        except (OSError, wave.Error, EOFError) as exc:
            raise AudioConfigError(f"WAV illisible ({path}) : {exc}") from exc
        if width != 2 or rate != SAMPLE_RATE or channels not in (1, 2):
            raise AudioConfigError(f"{path} : il faut du PCM 16 bits, 48000 Hz, mono ou stéréo "
                                   f"(trouvé : {width * 8} bits, {rate} Hz, {channels} canal(aux))")
        pcm = downmix_stereo(raw) if channels == 2 else raw
        pcm += bytes((-len(pcm)) % FRAME_BYTES)                # complète la dernière trame par du silence
        if not pcm:
            raise AudioConfigError(f"{path} : fichier vide")
        self._pcm, self._pos, self.loop = pcm, 0, loop
        self._pacer = _Pacer()

    def _frame(self) -> bytes:
        frame = self._pcm[self._pos:self._pos + FRAME_BYTES]
        self._pos += FRAME_BYTES
        if self._pos >= len(self._pcm):
            self._pos = 0 if self.loop else len(self._pcm)
        return frame or silence()


class NullSink:
    def write(self, pcm: bytes) -> None: pass
    def flush(self) -> None: pass
    def close(self) -> None: pass


class RecordingSink:
    """Garde les trames reçues (tests)."""

    def __init__(self):
        self.frames: list[bytes] = []
        self.times: list[float] = []
        self.flushes = 0

    def write(self, pcm: bytes) -> None:
        self.frames.append(pcm)
        self.times.append(time.monotonic())

    def flush(self) -> None:
        self.flushes += 1

    def close(self) -> None: pass


class WavSink:
    def __init__(self, path: str):
        try:
            self._file = open(path, "wb")          # ouvert ici : un échec ne laisse pas d'objet wave à moitié construit
        except OSError as exc:
            raise AudioConfigError(f"fichier de sortie impossible ({path}) : {exc}") from exc
        self._wav = wave.open(self._file, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(SAMPLE_RATE)

    def write(self, pcm: bytes) -> None:
        self._wav.writeframes(pcm)

    def flush(self) -> None: pass

    def close(self) -> None:
        self._wav.close()
        self._file.close()


class ClickDetectSink(RecordingSink):
    """Note l'instant d'arrivée de chaque salve (mesure de latence, voir devtools/latency.py)."""

    def __init__(self, threshold_db: float = -20.0, hold_s: float = 0.5):
        super().__init__()
        self.threshold_db, self.hold_s = threshold_db, hold_s
        self.click_times: list[float] = []

    def write(self, pcm: bytes) -> None:
        super().write(pcm)
        now = time.monotonic()
        if rms_dbfs(pcm) > self.threshold_db and (not self.click_times or now - self.click_times[-1] > self.hold_s):
            self.click_times.append(now)


# --------------------------------------------------------------------------- vrais périphériques

def _import_sd():
    try:
        import sounddevice
        return sounddevice
    except Exception as exc:
        raise AudioConfigError("sounddevice indisponible (pip install -e \".[audio]\" ; Linux : "
                               f"sudo apt install libportaudio2) : {exc}") from exc


def _extra_settings(sd, index: int):
    """WASAPI partagé : laisse Windows convertir la fréquence d'échantillonnage si besoin."""
    try:
        hostapi = sd.query_hostapis(sd.query_devices(index)["hostapi"])["name"]
        if "wasapi" in hostapi.lower() and hasattr(sd, "WasapiSettings"):
            return sd.WasapiSettings(auto_convert=True)
    except Exception:
        pass
    return None


class SoundDeviceSource:
    def __init__(self, device: str, sd=None):
        self.device, self._sd = device, sd
        self.overruns = self.xruns = 0
        self._stream = None

    async def start(self) -> None:
        sd = self._sd or _import_sd()
        try:
            index = resolve_device(self.device, "capture", sd)
        except LookupError as exc:
            raise AudioConfigError(str(exc)) from exc
        loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=50)

        def offer(data: bytes) -> None:
            if self._queue.full():
                self._queue.get_nowait()
                self.overruns += 1
            self._queue.put_nowait(data)

        def callback(indata, frames, time_info, status) -> None:      # fil PortAudio
            if status:
                self.xruns += 1
            loop.call_soon_threadsafe(offer, bytes(indata))

        kwargs = dict(samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES, device=index, channels=1,
                      dtype="int16", callback=callback, latency="low")
        if (extra := _extra_settings(sd, index)) is not None:
            kwargs["extra_settings"] = extra
        try:
            self._stream = sd.RawInputStream(**kwargs)
            self._stream.start()
        except Exception as exc:
            raise AudioConfigError(f"ouverture de la capture « {self.device} » impossible : {exc}") from exc

    async def read(self) -> bytes:
        return await self._queue.get()

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class SoundDeviceSink:
    MAX_BACKLOG_S = 0.20        # au-delà, on jette le plus ancien : un retard d'émission est pire qu'une coupure
    PREFILL_S = 0.06            # réserve contre la gigue du réseau (Wi-Fi, 4G) : sans elle, chaque paquet en retard
                                # faisait un trou dans l'émission (constat de l'utilisateur, 2026-10-29)

    def __init__(self, device: str, sd=None):
        self.device, self._sd = device, sd
        self._ring = RingBuffer(int(SAMPLE_RATE * 2 * self.MAX_BACKLOG_S), int(SAMPLE_RATE * 2 * self.PREFILL_S))
        self._stream = None

    @property
    def underruns(self) -> int:
        """Trous dans le son envoyé au poste (le réseau n'a pas livré à temps)."""
        return self._ring.underruns

    @property
    def overruns(self) -> int:
        """Son jeté parce qu'il arrivait trop en retard (plus de MAX_BACKLOG_S d'avance accumulée)."""
        return self._ring.overruns

    def open(self) -> None:
        sd = self._sd or _import_sd()
        try:
            index = resolve_device(self.device, "playback", sd)
        except LookupError as exc:
            raise AudioConfigError(str(exc)) from exc

        def callback(outdata, frames, time_info, status) -> None:    # fil PortAudio
            outdata[:] = self._ring.read(len(outdata))

        kwargs = dict(samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES, device=index, channels=1,
                      dtype="int16", callback=callback, latency="low")
        if (extra := _extra_settings(sd, index)) is not None:
            kwargs["extra_settings"] = extra
        try:
            self._stream = sd.RawOutputStream(**kwargs)
            self._stream.start()
        except Exception as exc:
            raise AudioConfigError(f"ouverture de la lecture « {self.device} » impossible : {exc}") from exc

    def write(self, pcm: bytes) -> None:
        self._ring.write(pcm)

    def flush(self) -> None:
        self._ring.clear()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


# --------------------------------------------------------------------------- fabrique

def make_source(spec: str, sd=None):
    spec = (spec or "").strip()
    try:
        if not spec:
            return SilenceSource()
        if spec.startswith("tone:"):
            return ToneSource(float(spec[5:]))
        if spec.startswith("click:"):
            return ClickSource(float(spec[6:]))
        if spec.startswith("file:"):
            return WavFileSource(spec[5:])
    except ValueError as exc:
        raise AudioConfigError(f"source audio « {spec} » invalide : {exc}") from exc
    return SoundDeviceSource(spec, sd)


def make_sink(spec: str, sd=None):
    spec = (spec or "").strip()
    if not spec or spec == "null":
        return NullSink()
    if spec.startswith("file:"):
        return WavSink(spec[5:])
    sink = SoundDeviceSink(spec, sd)
    sink.open()
    return sink
