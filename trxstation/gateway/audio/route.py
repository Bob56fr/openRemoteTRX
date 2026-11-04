# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Route d'émission : micro du propriétaire -> [Breizh Audio Box] -> porte d'émission (docs/breizh-cahier-des-charges.md § 4.2).

- Porte d'ENTRÉE : rien ne part vers Breizh si la porte est fermée ou si le client n'est pas le propriétaire.
- Route fixée à la prise (premier son de l'émission) : « breizh » si la liaison est prête et « Direct » n'est pas
  choisi, sinon « direct ». Pendant l'émission, seul le repli breizh -> direct est possible.
- Chaque trame de 20 ms part en 2 blocs de 10 ms ; les blocs sortent DANS L'ORDRE : traités (volume retour), ou
  « secs » à fallback_gain_db s'ils ne sont pas revenus après block_timeout_ms (le retour tardif est alors refusé).
- Aucun retour valable pendant lost_ms : REPLI, la fin de l'émission part en direct à fallback_gain_db.
- Tout passe par TxAudioGate.write avec l'époque de la prise : après une coupure, plus rien de Breizh n'atteint le poste.
Cette route ne touche jamais au PTT : elle ne fait que choisir le son qu'elle présente à la porte.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable

from ...breizh import protocol as bp
from .gate import TxAudioGate

log = logging.getLogger(__name__)


class TxRoute:
    def __init__(self, gate: TxAudioGate, link, cfg, store, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.gate, self.link, self.cfg, self.store, self.clock = gate, link, cfg, store, clock
        self.route = "direct"
        self._epoch: int | None = None              # époque de la porte à laquelle la route a été fixée
        self._direct_gain = 0.0
        self._first = True
        self._pending: OrderedDict[int, list] = OrderedDict()   # bloc -> [envoyé à, son d'origine, son traité ou None]
        self._unanswered_since: float | None = None
        self._timer: asyncio.TimerHandle | None = None
        self.late = self.fallbacks = 0
        gate.add_listener(self._gate_changed)
        link.on_return = self._on_return

    # ---------------------------------------------------------------- état
    def next_route(self) -> str:
        return "direct" if self.store.settings.bypass or not self.link.ready else "breizh"

    @property
    def emitting(self) -> bool:
        return self.gate.is_open and self._epoch == self.gate.epoch

    def snapshot(self) -> dict:
        """state.breizh (opérateurs) et fichier d'état."""
        emitting = self.emitting
        state = "active" if emitting and self.route == "breizh" else self.link.state
        settings = self.store.settings
        return {"state": state, "route": self.route if emitting else self.next_route(), "bypass": settings.bypass,
                "return_gain_db": settings.return_gain_db, "rtt_ms": self.link.rtt_ms, "late": self.late,
                "lost": self.fallbacks, "peer": self.link.peer_version, "reactivate_in_s": self.link.reactivate_in_s()}

    # ---------------------------------------------------------------- micro
    def push(self, client_id: str, pcm: bytes) -> bool:
        """Remplace TxAudioGate.push pour le micro des clients (webrtc.receive_tx_audio)."""
        gate = self.gate
        if not gate.admits(client_id):
            return False
        epoch = gate.epoch
        if epoch != self._epoch:
            self._begin(epoch)
        if self.route == "direct" or len(pcm) % bp.BLOCK_BYTES:
            return gate.write(pcm, epoch, self._direct_gain)
        now = self.clock()
        for start in range(0, len(pcm), bp.BLOCK_BYTES):
            block = pcm[start:start + bp.BLOCK_BYTES]
            ref = self.link.send_audio(block, bp.FLAG_START if self._first else 0)
            if ref is None:
                self._fall_back("Breizh injoignable au moment d'envoyer le son")
                return gate.write(pcm[start:], epoch, self._direct_gain)
            self._first = False
            self._pending[ref] = [now, block, None]
            if self._unanswered_since is None:
                self._unanswered_since = now
        self._arm()
        return True

    def _begin(self, epoch: int) -> None:
        self._clear()
        self._epoch = epoch
        self.route = self.next_route()
        self._direct_gain, self._first = 0.0, True
        self.late = self.fallbacks = 0

    def _gate_changed(self, open_: bool, epoch: int) -> None:
        if not open_:
            self._clear()                           # coupure : les blocs encore chez Breizh ne sortiront jamais

    def _clear(self) -> None:
        for ref in self._pending:
            self.link.forget(ref)
        self._pending.clear()
        self._unanswered_since = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # ---------------------------------------------------------------- retours
    def _on_return(self, ref: int, block: bytes | None) -> None:
        """Retour authentique de Breizh. `block` None : arrivé après son remplacement (Breizh lent, pas perdu)."""
        self._unanswered_since = None
        entry = self._pending.get(ref)
        if entry is None or block is None:          # trop tard, ou émission coupée entre-temps
            return
        entry[2] = block
        self._flush()

    def _flush(self) -> None:
        self._timer = None
        if not self.emitting:
            self._clear()
            return
        now, timeout = self.clock(), self.cfg.block_timeout_ms / 1000
        gain = self.store.settings.return_gain_db
        while self._pending:
            ref, (sent, dry, processed) = next(iter(self._pending.items()))
            if processed is not None:
                self.gate.write(processed, self._epoch, gain)
            elif now - sent >= timeout:
                self.gate.write(dry, self._epoch, self.cfg.fallback_gain_db)
                self.link.forget(ref)
                self.late += 1
            else:
                break
            del self._pending[ref]
        if self._unanswered_since is not None and now - self._unanswered_since >= self.cfg.lost_ms / 1000:
            self._fall_back(f"Breizh ne répond plus depuis {self.cfg.lost_ms} ms : fin de l'émission en direct, "
                            f"gain {self.cfg.fallback_gain_db:g} dB")
            return
        self._arm()

    def _arm(self) -> None:
        """Un seul réveil : la prochaine échéance (bloc en retard ou Breizh perdu), vérifiée à nouveau au réveil
        (les minuteries de Windows ont ~16 ms de résolution et peuvent sonner un peu tôt)."""
        deadlines = []
        if self._pending:
            deadlines.append(next(iter(self._pending.values()))[0] + self.cfg.block_timeout_ms / 1000)
        if self._unanswered_since is not None:
            deadlines.append(self._unanswered_since + self.cfg.lost_ms / 1000)
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if deadlines:
            delay = max(0.0, min(deadlines) - self.clock()) + 0.002
            self._timer = asyncio.get_running_loop().call_later(delay, self._flush)

    def _fall_back(self, detail: str) -> None:
        """Repli : ce qui attend part sec, dans l'ordre ; la fin de l'émission en direct à gain réduit."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for ref, (_, dry, processed) in list(self._pending.items()):
            if processed is not None:
                self.gate.write(processed, self._epoch, self.store.settings.return_gain_db)
            else:
                self.gate.write(dry, self._epoch, self.cfg.fallback_gain_db)
                self.link.forget(ref)
                self.late += 1
        self._pending.clear()
        self._unanswered_since = None
        self.route = "direct"
        self._direct_gain = self.cfg.fallback_gain_db
        self.fallbacks += 1
        self.link.mark_lost(detail)
