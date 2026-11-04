# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Porte audio d'ÉMISSION : le micro d'un client n'atteint le poste que si
  1. le PTT est confirmé en émission (la porte est ouverte par le PttController), ET
  2. le client est le PROPRIÉTAIRE de l'émission, ET
  3. le son appartient à l'ouverture EN COURS de la porte (son « époque »).
Fermée, elle jette tout et vide le tampon de lecture : aucun reste de son ne part après la
coupure. Le PttController ferme la porte AVANT d'envoyer « PTT off ».

L'époque change à chaque ouverture et à chaque fermeture : un son parti chez Breizh Audio Box pendant une
émission et revenu après la coupure (ou pendant l'émission suivante) porte une époque périmée et est jeté.
Dernier traitement avant le poste : le limiteur final de la station (limiter.py), toujours actif.
"""
from __future__ import annotations

from collections.abc import Callable

from .levels import LevelMeter
from .limiter import PeakLimiter


class TxAudioGate:
    def __init__(self, sink, meter: LevelMeter | None = None, gain_db: float = 0.0,
                 owner_provider: Callable[[], str | None] = lambda: None):
        self.sink, self.meter, self.gain_db = sink, meter or LevelMeter(), gain_db
        self.owner_provider = owner_provider
        self.limiter = PeakLimiter()
        self._open = False
        self.epoch = 0
        self._listeners: list[Callable[[bool, int], None]] = []
        self.passed = self.dropped_closed = self.dropped_not_owner = self.dropped_stale = 0

    @property
    def is_open(self) -> bool:
        return self._open

    def add_listener(self, callback: Callable[[bool, int], None]) -> None:
        """(ouverte, époque) à chaque changement : la route de Breizh oublie alors les blocs en cours."""
        self._listeners.append(callback)

    def set_open(self, open_: bool) -> None:
        """Appelée de façon synchrone par le PttController."""
        if open_ == self._open:
            return
        if not open_:
            self.sink.flush()
            self.meter.reset()
        self.limiter.reset()
        self._open = open_
        self.epoch += 1
        for callback in list(self._listeners):
            callback(open_, self.epoch)

    def admits(self, client_id: str) -> bool:
        """Porte ouverte ET client propriétaire (compte les refus) : rien ne part vers Breizh sinon."""
        if not self._open:
            self.dropped_closed += 1
            return False
        if client_id != self.owner_provider():
            self.dropped_not_owner += 1
            return False
        return True

    def write(self, pcm: bytes, epoch: int, gain_db: float = 0.0) -> bool:
        """Son déjà admis par `admits` sous l'époque `epoch` ; jeté si la porte a changé depuis."""
        if not self._open or epoch != self.epoch:
            self.dropped_stale += 1
            return False
        pcm = self.limiter.process(pcm, self.gain_db + gain_db)
        self.meter.update(pcm)
        self.sink.write(pcm)
        self.passed += 1
        return True

    def push(self, client_id: str, pcm: bytes) -> bool:
        """Route directe : admis puis écrit tout de suite."""
        return self.admits(client_id) and self.write(pcm, self.epoch)
