# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Carte son du poste qui peut DISPARAÎTRE et REVENIR (poste débranché puis rebranché, numéro changé).

Avant (constat du 2026-11-19 sur minix-bzh) : carte absente au démarrage = passerelle arrêtée (code 5), relancée en
boucle par le superviseur puis MODE SÛR ; il fallait la console pour repartir. Désormais :
  * la passerelle démarre quand même : CAT, page, état publiés ; son reçu = silence ;
  * l'ÉMISSION EST REFUSÉE tant que la carte manque (`audio_missing`, PttController) : en cas de doute, pas
    d'émission (une porteuse sans modulation, en FM ou en AM, n'a rien à faire sur l'air) ;
  * la carte est recherchée toutes les RETRY_S secondes ; retrouvée, le son reprend, l'émission redevient possible ;
  * carte PERDUE en marche (plus aucun son reçu pendant STALL_S) : elle est fermée, recherchée de nouveau, et une
    émission en cours est COUPÉE (`audio_lost`) ;
  * chaque changement est dit : ORT-3012 (absente, alerte ntfy) et ORT-3013 (retrouvée).
Rien ne change pour une carte présente : mêmes objets `SoundDeviceSource` / `SoundDeviceSink` qu'avant, enveloppés.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from ...errors import codes
from ...errors.emit import emit_event
from .devices import AudioConfigError, SoundDeviceSink, SoundDeviceSource
from .pcm import FRAME_SAMPLES, SAMPLE_RATE

log = logging.getLogger(__name__)

RETRY_S = 5.0                     # recherche de la carte absente
STALL_S = 2.0                     # carte présente mais plus aucun son reçu : perdue (débranchée)
FRAME_S = FRAME_SAMPLES / SAMPLE_RATE
SILENCE = bytes(FRAME_SAMPLES * 2)


class RigCard:
    """Les deux sens de la carte du poste, ouverts ensemble ; `available` = les deux ouverts et vivants."""

    def __init__(self, capture: str, playback: str, sd=None, *, alert: Callable[[str, str], None] | None = None,
                 retry_s: float = RETRY_S, stall_s: float = STALL_S) -> None:
        self.capture, self.playback, self._sd = capture, playback, sd
        self.alert = alert                      # Notifier.alert(code, détail) : ntfy (facultatif)
        self.on_lost: Callable[[], None] | None = None   # carte perdue EN MARCHE : la passerelle coupe une émission
        self.retry_s, self.stall_s = retry_s, stall_s
        self.available = False
        self.detail = ""
        self._source: SoundDeviceSource | None = None
        self._sink: SoundDeviceSink | None = None
        self._announced: bool | None = None     # dernier état annoncé (None = rien encore)
        self.source = _CardSource(self)
        self.sink = _CardSink(self)

    # ------------------------------------------------------------------ ouverture, perte

    async def open(self) -> bool:
        if self.available:
            return True
        source = SoundDeviceSource(self.capture, self._sd)
        try:
            await source.start()
        except AudioConfigError as exc:
            self._missing(str(exc))
            return False
        sink = SoundDeviceSink(self.playback, self._sd)
        try:
            sink.open()
        except AudioConfigError as exc:
            await _quiet(source.stop())
            self._missing(str(exc))
            return False
        self._source, self._sink, self.available, self.detail = source, sink, True, ""
        if self._announced is False:
            emit_event(codes.ORT_3013, logger=log, entree=self.capture, sortie=self.playback)
            self._send(codes.ORT_3013, f"{self.capture} / {self.playback}")
        self._announced = True
        return True

    async def lose(self, detail: str) -> None:
        """Carte qui ne donne plus de son : fermée, émission coupée par la passerelle, recherchée de nouveau."""
        if not self.available:
            return
        source, sink = self._source, self._sink
        self._source = self._sink = None
        self.available = False
        if self.on_lost is not None:
            try:
                self.on_lost()
            except Exception:                    # noqa: BLE001 : la coupure ne doit jamais empêcher la suite
                emit_event(codes.ORT_3012, logger=log, trace=True, detail="coupure de l'émission en erreur")
        if source is not None:
            await _quiet(source.stop())
        if sink is not None:
            try:
                sink.close()
            except Exception:                    # noqa: BLE001 : carte déjà partie
                pass
        self._missing(detail)

    def _missing(self, detail: str) -> None:
        self.available, self.detail = False, detail
        if self._announced is not False:         # une seule annonce par absence (pas une toutes les 5 s)
            emit_event(codes.ORT_3012, logger=log, detail=detail)
            self._send(codes.ORT_3012, detail)
        self._announced = False

    def _send(self, code: str, detail: str) -> None:
        if self.alert is not None:
            try:
                self.alert(code, detail)
            except Exception:                    # noqa: BLE001 : une alerte ratée ne change rien au son
                pass

    async def watch(self, stop: asyncio.Event) -> None:
        """Recherche de la carte absente, toutes les `retry_s` secondes, jusqu'à l'arrêt de la passerelle."""
        while not stop.is_set():
            if not self.available:
                await self.open()
            try:
                await asyncio.wait_for(stop.wait(), self.retry_s)
            except asyncio.TimeoutError:
                pass

    async def close(self) -> None:
        source, sink = self._source, self._sink
        self._source = self._sink = None
        self.available = False
        if source is not None:
            await _quiet(source.stop())
        if sink is not None:
            try:
                sink.close()
            except Exception:                    # noqa: BLE001
                pass


async def _quiet(coro) -> None:
    try:
        await coro
    except Exception:                            # noqa: BLE001 : carte déjà débranchée
        pass


class _CardSource:
    """Source de l'AudioPipeline : le son de la carte, ou du silence au rythme réel quand elle manque."""

    def __init__(self, card: RigCard) -> None:
        self.card = card

    @property
    def xruns(self) -> int:
        return getattr(self.card._source, "xruns", 0)

    @property
    def overruns(self) -> int:
        return getattr(self.card._source, "overruns", 0)

    async def start(self) -> None:
        await self.card.open()                   # absente : la passerelle démarre quand même (recherche ensuite)

    async def read(self) -> bytes:
        source = self.card._source
        if source is None:
            await asyncio.sleep(FRAME_S)
            return SILENCE
        try:
            return await asyncio.wait_for(source.read(), self.card.stall_s)
        except asyncio.TimeoutError:
            await self.card.lose(f"plus aucun son reçu de « {self.card.capture} » depuis {self.card.stall_s:.0f} s "
                                 "(poste débranché ou éteint ?)")
            return SILENCE

    async def stop(self) -> None:
        await self.card.close()


class _CardSink:
    """Puits de l'AudioPipeline : vers la carte, ou jeté quand elle manque (l'émission est alors refusée)."""

    def __init__(self, card: RigCard) -> None:
        self.card = card

    @property
    def underruns(self) -> int:
        return getattr(self.card._sink, "underruns", 0)

    @property
    def overruns(self) -> int:
        return getattr(self.card._sink, "overruns", 0)

    def write(self, pcm: bytes) -> None:
        sink = self.card._sink
        if sink is not None:
            sink.write(pcm)

    def flush(self) -> None:
        sink = self.card._sink
        if sink is not None:
            sink.flush()

    def close(self) -> None:
        pass                                     # fermé par RigCard.close (source.stop de l'AudioPipeline)
