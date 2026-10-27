# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""« Poste utilisé sur place » : quelqu'un se sert du poste lui-même (micro, bouton d'accord, touches de mode).

Repéré d'après ce que la station relit du poste, sans rien commander :
  * émission alors que la passerelle est en réception (micro du poste, pédale, VOX...) ;
  * fréquence ou mode changés sans commande de la station.
La station ne sait pas QUI a agi (micro, pédale, autre logiciel CAT) : c'est une déduction.

Effet (décision de l'utilisateur) : le PTT à distance est refusé (`local_active`) tant que dure l'état, c'est-à-dire
pendant l'émission locale puis HOLD_S après la dernière action locale. L'accord et le mode à distance restent
permis. Un client peut « reprendre la main » plus tôt (`release`), jamais pendant une émission locale.
Rien ici ne commande le poste : ce module ne fait que refuser.
"""
from __future__ import annotations

import time
from collections.abc import Callable

HOLD_S = 120.0          # durée de l'état après la dernière action locale
EXPECT_S = 3.0          # après une commande de la station, un changement du même genre lui est attribué
SETTLE_S = 2.0          # après une émission de la station, le poste relu peut traîner : on n'en déduit rien


class LocalPresence:
    def __init__(self, hold_s: float = HOLD_S, clock: Callable[[], float] = time.monotonic):
        self.hold_s, self.clock = hold_s, clock
        self._until = 0.0
        self.reason = ""                       # "tx" | "frequency" | "mode"
        self._local_tx = False                 # émission locale en cours
        self._freq: int | None = None
        self._mode: str | None = None
        self._expect = {"frequency": -1e18, "mode": -1e18}
        self._busy_until = -1e18               # station en émission ou juste après : aucune déduction

    # ---- ce que la station commande elle-même
    def station_busy(self) -> None:
        """La passerelle change d'état d'émission : les relectures des SETTLE_S suivantes ne disent rien de l'opérateur."""
        self._busy_until = self.clock() + SETTLE_S

    def expect(self, kind: str) -> None:
        """La station va changer la fréquence ou le mode : le prochain changement de ce genre est le sien."""
        self._expect[kind] = self.clock() + EXPECT_S

    # ---- ce que la station relit du poste
    def observe(self, connected: bool, ptt: bool | None, frequency_hz: int | None, mode: str | None,
                gateway_state: str) -> bool:
        """Nouvel état relu. Renvoie True si une action locale vient d'être repérée (pour publier l'état)."""
        now = self.clock()
        if not connected:
            self._freq = self._mode = None     # pas de comparaison à travers une coupure de liaison
            self._local_tx = False
            return False
        if gateway_state != "RX":
            self._busy_until = now + SETTLE_S
        idle = now >= self._busy_until
        found = False
        if ptt is True and gateway_state == "RX" and idle:
            if not self._local_tx:
                found = True
            self._local_tx = True
            self._mark("tx", now)
        elif ptt is False and self._local_tx:
            self._local_tx = False
            self._mark("tx", now)              # l'attente repart de la FIN de l'émission locale
            found = True
        if frequency_hz is not None:
            if (self._freq is not None and frequency_hz != self._freq and idle
                    and now > self._expect["frequency"]):
                self._mark("frequency", now)
                found = True
            self._freq = frequency_hz
        if mode:
            if self._mode is not None and mode != self._mode and idle and now > self._expect["mode"]:
                self._mark("mode", now)
                found = True
            self._mode = mode
        return found

    def _mark(self, reason: str, now: float) -> None:
        self.reason = reason
        self._until = now + self.hold_s

    # ---- état
    @property
    def transmitting(self) -> bool:
        return self._local_tx

    def active(self) -> bool:
        return self._local_tx or self.clock() < self._until

    def remaining(self) -> float | None:
        """Secondes avant que le PTT à distance soit de nouveau permis ; None si l'état n'est pas actif."""
        if self._local_tx:
            return self.hold_s
        left = self._until - self.clock()
        return left if left > 0 else None

    def release(self) -> bool:
        """« Reprendre la main » depuis un client. Refusé (False) pendant une émission locale."""
        if self._local_tx:
            return False
        self._until = 0.0
        self.reason = ""
        return True
