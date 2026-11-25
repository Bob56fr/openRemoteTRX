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

PRÉSENCE PROUVÉE (décision de l'utilisateur, 2026-11-16, étape 206) : une émission locale est jugée « opérateur présent »
si une action sur le poste a été vue dans les PRESENCE_S avant sa prise ou pendant elle : fréquence ou mode (dont la
sortie du mode DATA pour parler au micro), ou un réglage de la face avant (volume AF, préampli, ATT, AGC, squelch,
puissance, NR, NB, fonctions, RIT / XIT, split, VFO). Le superviseur la tolère alors jusqu'à `local_tx_max_s` au lieu de
`tot_abs_s`. Un réglage de la face avant ne sert QU'À cette preuve : il ne bloque pas le PTT à distance (comportement de
l'étape 34 inchangé). Un réglage relu dans les PANEL_EXPECT_S après une écriture de la station (`CatLink.writes`), ou
après un changement de fréquence ou de mode de la station (réglages mémorisés par bande du poste), n'est pas une preuve.

DÉLAIS DU POSTE (étape 393, signalement de l'utilisateur du 2026-11-25 : « prise en main sur place » à tort sur le Yaesu
FTDX10) : l'attente d'une commande de la station se compte depuis la FIN de la commande (`expect` rappelé après elle),
avec la marge de la fiche technique du poste (`rigspec`, plus encore coupleur en service) ; si la fiche le dit
(`linked_changes`), une commande de fréquence attend aussi un changement de mode (mémoire par bande) et inversement.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from ...rigspec import Timing

HOLD_S = 120.0          # durée de l'état après la dernière action locale
EXPECT_S = 3.0          # après une commande de la station, un changement du même genre lui est attribué (+ fiche du poste)
SETTLE_S = 2.0          # après une émission de la station, le poste relu peut traîner : on n'en déduit rien
PRESENCE_S = 120.0      # action sur le poste vue au plus tant avant la prise d'une émission locale : opérateur présent
PANEL_EXPECT_S = 60.0   # réglage écrit par la station : sa relecture peut venir tard (lectures facultatives à tour de rôle)
PANEL_LEVELS = ("AF", "PREAMP", "ATT", "AGC", "SQL", "RFPOWER", "NR", "NB")   # réglages, jamais les mesures (_METER...)


def panel_of(functions: dict | None, levels: dict | None, offsets: dict | None, split: bool | None,
             vfo: str | None) -> dict:
    """Réglages de la face avant relus du poste, à plat (« f:NR », « l:AF », « o:RIT », « split », « vfo »)."""
    panel: dict = {f"f:{k}": v for k, v in (functions or {}).items()}
    panel.update({f"l:{k}": v for k, v in (levels or {}).items() if k in PANEL_LEVELS})
    panel.update({f"o:{k}": v for k, v in (offsets or {}).items()})
    if split is not None:
        panel["split"] = split
    if vfo is not None:
        panel["vfo"] = vfo
    return panel


class LocalPresence:
    def __init__(self, hold_s: float = HOLD_S, clock: Callable[[], float] = time.monotonic, timing: Timing | None = None):
        self.hold_s, self.clock = hold_s, clock
        self.timing = timing or Timing()       # délais du poste (fiche technique, trxstation/rigspec)
        self._until = 0.0
        self.reason = ""                       # "tx" | "frequency" | "mode"
        self._local_tx = False                 # émission locale en cours
        self._freq: int | None = None
        self._mode: str | None = None
        self._expect = {"frequency": -1e18, "mode": -1e18}
        self._busy_until = -1e18               # station en émission ou juste après : aucune déduction
        self._panel: dict = {}
        self._action_at = -1e18                # dernière action sur le poste (fréquence, mode, face avant)
        self._tx_start = 0.0                   # prise de l'émission locale en cours

    # ---- ce que la station commande elle-même
    def station_busy(self) -> None:
        """La passerelle change d'état d'émission : les relectures des SETTLE_S suivantes ne disent rien de l'opérateur."""
        self._busy_until = self.clock() + SETTLE_S

    def expect_window_s(self) -> float:
        """Durée pendant laquelle un changement relu est attribué à la station : base + marge du poste (+ coupleur)."""
        tuner = self.timing.tuner_delay_s if self._panel.get("f:TUNER") is True else 0.0
        return EXPECT_S + self.timing.read_delay_s + tuner

    def expect(self, kind: str) -> None:
        """La station va changer (ou vient de changer) la fréquence ou le mode : les changements de ce genre relus dans
        la fenêtre sont les siens. À rappeler APRÈS la commande (poste lent : la fenêtre part de la fin). Fiche du poste
        `linked_changes` : la fréquence et le mode sont attendus ensemble (mémoire par bande)."""
        until = self.clock() + self.expect_window_s()
        for k in (("frequency", "mode") if self.timing.linked_changes else (kind,)):
            self._expect[k] = max(self._expect[k], until)

    # ---- ce que la station relit du poste
    def observe(self, connected: bool, ptt: bool | None, frequency_hz: int | None, mode: str | None,
                gateway_state: str, panel: dict | None = None, writes: dict | None = None) -> bool:
        """Nouvel état relu. Renvoie True si une action locale vient d'être repérée, ou si la présence de l'opérateur
        vient d'être prouvée pendant une émission locale (pour publier l'état).
        `panel` : panel_of(...) ; `writes` : CatLink.writes (même horloge que `clock`)."""
        now = self.clock()
        if not connected:
            self._freq = self._mode = None     # pas de comparaison à travers une coupure de liaison
            self._panel = {}
            self._local_tx = False
            return False
        was_present = self.present
        if gateway_state != "RX":
            self._busy_until = now + SETTLE_S
        idle = now >= self._busy_until
        found = False
        if ptt is True and gateway_state == "RX" and idle:
            if not self._local_tx:
                found = True
                self._tx_start = now
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
        if panel is not None:
            if idle and self._panel_changed_by_hand(panel, writes or {}, now):
                self._action_at = now
            self._panel = dict(panel)
        return found or self.present != was_present

    def _panel_changed_by_hand(self, panel: dict, writes: dict, now: float) -> bool:
        tuned = writes.get("*", -1e18)
        for key, value in panel.items():
            if key not in self._panel or self._panel[key] == value:
                continue                       # première lecture de ce réglage : rien à comparer
            if now - max(tuned, writes.get(key, -1e18)) < PANEL_EXPECT_S:
                continue                       # écrit par la station (ou réglage par bande après son QSY)
            return True
        return False

    def _mark(self, reason: str, now: float) -> None:
        self.reason = reason
        self._until = now + self.hold_s
        if reason != "tx":                     # l'émission elle-même ne prouve pas que quelqu'un est là
            self._action_at = now

    # ---- état
    @property
    def transmitting(self) -> bool:
        return self._local_tx

    @property
    def present(self) -> bool:
        """Émission locale EN COURS avec un opérateur présent (action sur le poste dans les PRESENCE_S avant la prise,
        ou pendant l'émission). Faux hors émission locale."""
        return self._local_tx and self._action_at >= self._tx_start - PRESENCE_S

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
