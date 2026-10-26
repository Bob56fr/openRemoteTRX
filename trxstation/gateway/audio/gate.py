"""Porte audio d'ÉMISSION : le micro d'un client n'atteint le poste que si
  1. le PTT est confirmé en émission (la porte est ouverte par le PttController), ET
  2. le client est le PROPRIÉTAIRE de l'émission.
Fermée, elle jette tout et vide le tampon de lecture : aucun reste de son ne part après la
coupure. Le PttController ferme la porte AVANT d'envoyer « PTT off ».
"""
from __future__ import annotations

from collections.abc import Callable

from .levels import LevelMeter
from .pcm import apply_gain


class TxAudioGate:
    def __init__(self, sink, meter: LevelMeter | None = None, gain_db: float = 0.0,
                 owner_provider: Callable[[], str | None] = lambda: None):
        self.sink, self.meter, self.gain_db = sink, meter or LevelMeter(), gain_db
        self.owner_provider = owner_provider
        self._open = False
        self.passed = self.dropped_closed = self.dropped_not_owner = 0

    @property
    def is_open(self) -> bool:
        return self._open

    def set_open(self, open_: bool) -> None:
        """Appelée de façon synchrone par le PttController."""
        if self._open and not open_:
            self.sink.flush()
            self.meter.reset()
        self._open = open_

    def push(self, client_id: str, pcm: bytes) -> bool:
        if not self._open:
            self.dropped_closed += 1
            return False
        if client_id != self.owner_provider():
            self.dropped_not_owner += 1
            return False
        pcm = apply_gain(pcm, self.gain_db)
        self.meter.update(pcm)
        self.sink.write(pcm)
        self.passed += 1
        return True
