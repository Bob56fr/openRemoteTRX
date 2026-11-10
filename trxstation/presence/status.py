# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Statut de l'opérateur (cahier § 9.1), calcul pur, horloge et fuseau fournis par l'appelant.

Priorités : En QSO (Q) > En RX (R) > Au shack (S) > Absent (A). « Hors ligne » (O) est décidé par celui qui LIT
(état trop vieux, absent ou « invisible » H), jamais publié.

- En QSO : émission (de la station ou au micro du poste), puis 10 min après la dernière émission.
- En RX : changement de fréquence ou de mode, commande d'un client opérateur, client opérateur connecté ; 5 min
  après la dernière activité. L'écoute d'un visiteur n'est PAS une activité (c'est à l'appelant de ne pas l'envoyer).
- Au shack : déclaration ponctuelle (« pour 2 h ») ou plages récurrentes (jours, HH:MM-HH:MM, minuit franchi
  permis), suspendables jusqu'à une date.
- `since` : début du statut en cours, au plus juste (fin exacte de la temporisation précédente).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo

QSO_HOLD_S = 600
RX_HOLD_S = 300
OFFLINE_AFTER_S = 240
ORDER = {"Q": 0, "R": 1, "S": 2, "A": 3, "O": 4}
_HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


@dataclass(frozen=True)
class ShackRule:
    """Plage récurrente : `days` 0 = lundi … 6 = dimanche (jour du DÉBUT de la plage)."""
    days: frozenset[int]
    start: str
    end: str

    def __post_init__(self) -> None:
        if not self.days or not self.days <= set(range(7)):
            raise ValueError("jours de 0 (lundi) à 6 (dimanche)")
        if not _HHMM.fullmatch(self.start) or not _HHMM.fullmatch(self.end) or self.start == self.end:
            raise ValueError("plage HH:MM-HH:MM attendue (début différent de la fin)")

    def windows(self, now: float, tz: tzinfo) -> list[tuple[float, float]]:
        """Plages qui commencent entre 8 jours avant et le jour de `now` (heure locale de `tz`)."""
        day = datetime.fromtimestamp(now, tz).date()
        sh, sm = map(int, self.start.split(":"))
        eh, em = map(int, self.end.split(":"))
        out = []
        for back in range(8, -1, -1):
            d = day - timedelta(days=back)
            if d.weekday() not in self.days:
                continue
            start = datetime(d.year, d.month, d.day, sh, sm, tzinfo=tz)
            end_day = d + timedelta(days=1) if (eh, em) <= (sh, sm) else d
            end = datetime(end_day.year, end_day.month, end_day.day, eh, em, tzinfo=tz)
            out.append((start.timestamp(), end.timestamp()))
        return out


@dataclass(frozen=True)
class Status:
    code: str                    # Q, R, S, A
    since: float
    last_tx: float | None        # fin de la dernière émission (maintenant si elle dure)
    shack_until: float | None    # fin de la plage « Au shack » en cours


@dataclass
class StatusTracker:
    started: float
    tz: tzinfo
    rules: list[ShackRule] = field(default_factory=list)
    suspended_until: float | None = None       # plages récurrentes suspendues (vacances)
    once: tuple[float, float] | None = None     # « Au shack » ponctuel
    tx_active: bool = False
    qso_start: float | None = None
    last_tx_end: float | None = None
    rx_start: float | None = None
    last_activity: float | None = None

    # -------------------------------------------------------------- événements
    def tx(self, active: bool, t: float) -> None:
        if active and not self.tx_active:
            if self.last_tx_end is None or t > self.last_tx_end + QSO_HOLD_S:
                self.qso_start = t
            self.tx_active = True
        elif not active and self.tx_active:
            self.tx_active = False
            self.last_tx_end = t

    def activity(self, t: float) -> None:
        if self.last_activity is None or t > self.last_activity + RX_HOLD_S:
            self.rx_start = t
        self.last_activity = max(t, self.last_activity or t)

    def shack_for(self, t: float, seconds: float) -> None:
        self.once = (t, t + seconds)

    def shack_cancel(self) -> None:
        self.once = None

    # -------------------------------------------------------------- calcul
    def _windows(self, now: float) -> list[tuple[float, float]]:
        out = [self.once] if self.once else []
        for rule in self.rules:
            for start, end in rule.windows(now, self.tz):
                if self.suspended_until is not None and start < self.suspended_until:
                    continue
                out.append((start, end))
        return out

    def status(self, now: float) -> Status:
        last_tx = now if self.tx_active else self.last_tx_end
        qso_end = None if self.tx_active or self.last_tx_end is None else self.last_tx_end + QSO_HOLD_S
        if self.tx_active or (qso_end is not None and now < qso_end):
            return Status("Q", self.qso_start if self.qso_start is not None else now, last_tx, None)
        ended = [x for x in (qso_end,) if x is not None]
        rx_end = None if self.last_activity is None else self.last_activity + RX_HOLD_S
        if rx_end is not None and now < rx_end:
            return Status("R", max([self.rx_start or now, *ended]), last_tx, None)
        if rx_end is not None:
            ended.append(rx_end)
        windows = self._windows(now)
        current = [w for w in windows if w[0] <= now < w[1]]
        if current:
            start = min(w[0] for w in current)
            until = max(w[1] for w in current)
            return Status("S", max([start, *ended]), last_tx, until)
        ended += [w[1] for w in windows if w[1] <= now]
        return Status("A", max([self.started, *ended]), last_tx, None)


# ------------------------------------------------------------------ lecture et affichage
def display_code(published: str | None, age_s: float | None) -> str:
    """Statut affiché : O si rien, état trop vieux (> 4 min) ou membre invisible (H)."""
    if published is None or age_s is None or age_s > OFFLINE_AFTER_S or published not in ORDER or published == "O":
        return "O"
    return published


def sort_key(code: str, pseudo: str) -> tuple[int, str]:
    """Actifs en haut, absents puis hors ligne en bas ; pseudo sans tenir compte de la casse."""
    return ORDER.get(code, ORDER["O"]), pseudo.casefold()


def format_age(seconds: float) -> str:
    """Âge arrondi par défaut : « 3 min » (1 min au moins), « 2 h », « 4 j »."""
    s = max(0, int(seconds))
    if s < 3600:
        return f"{max(1, s // 60)} min"
    if s < 86400:
        return f"{s // 3600} h"
    return f"{s // 86400} j"
