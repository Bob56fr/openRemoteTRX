# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Profil d'envoi d'une liaison et mode assistance (cahier § 5, § 10, § 17.6).

C'est l'opérateur de la station SURVEILLÉE qui choisit ; rien ne part sans profil validé. Fréquence et mode du poste
sont masqués par défaut (à autoriser liaison par liaison). Le mode assistance est DEMANDÉ par la station qui aide et
ACCEPTÉ par l'opérateur, pour une durée bornée ; à l'échéance, retour seul au profil de la liaison.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

SEVERITIES = ("info", "avertissement", "erreur", "critique")       # comme `gravite` du catalogue d'erreurs
PERIOD_MIN_S, PERIOD_MAX_S = 60, 900
ASSIST_PERIOD_S = 30
ASSIST_LOGS_S = 120
ASSIST_MIN_S, ASSIST_MAX_S, ASSIST_DEFAULT_S = 15 * 60, 24 * 3600, 2 * 3600
ASSIST_REQUESTS_PER_DAY = 3
RIG_SECRET_FIELDS = ("freq", "mode", "tx_freq", "vfo", "filter", "width")   # masqués sauf `freq_mode`


class ProfileRefused(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    system: bool = True               # charge, mémoire, disque, température (hostinfo)
    rig: bool = True                  # liaison CAT, émission oui/non, compteurs de refus et de coupures
    freq_mode: bool = False           # fréquence, mode, filtre : seulement si l'opérateur l'autorise
    events_min: str = "avertissement"
    period_s: int = 300               # battement, système, poste

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, obj: object) -> "Profile":
        if not isinstance(obj, dict) or set(obj) - set(cls.__dataclass_fields__):
            raise ProfileRefused("profil illisible")
        p = replace(cls(), **obj)
        for name in ("system", "rig", "freq_mode"):
            if not isinstance(getattr(p, name), bool):
                raise ProfileRefused(f"{name} : oui ou non attendu")
        if p.events_min not in SEVERITIES:
            raise ProfileRefused("gravité minimale inconnue")
        if isinstance(p.period_s, bool) or not isinstance(p.period_s, int) \
                or not PERIOD_MIN_S <= p.period_s <= PERIOD_MAX_S:
            raise ProfileRefused(f"rythme : {PERIOD_MIN_S} à {PERIOD_MAX_S} s")
        return p


PRESETS = {
    "essentiel": Profile(rig=False, events_min="erreur"),
    "diagnostic": Profile(),                       # le défaut du § 17.6
}


@dataclass(frozen=True)
class Effective:
    """Ce que le module applique à l'instant : rythmes et filtres."""
    period_s: int
    events_min: str
    logs_every_s: int | None          # None : pas de journaux
    system: bool
    rig: bool
    freq_mode: bool
    assistance: bool


def effective(profile: Profile, assist_until: float | None, now: float) -> Effective:
    if assist_until is not None and now < assist_until:
        return Effective(ASSIST_PERIOD_S, "info", ASSIST_LOGS_S, True, True, profile.freq_mode, True)
    return Effective(profile.period_s, profile.events_min, None, profile.system, profile.rig, profile.freq_mode, False)


def assist_until(accepted_at: float, duration_s: int) -> float:
    if isinstance(duration_s, bool) or not isinstance(duration_s, int) \
            or not ASSIST_MIN_S <= duration_s <= ASSIST_MAX_S:
        raise ProfileRefused("durée de l'assistance : 15 min à 24 h")
    return accepted_at + duration_s


def severity_passes(severity: str, minimum: str) -> bool:
    """Gravité inconnue : envoyée (mieux vaut trop que rien pour un dépannage), au niveau « erreur »."""
    rank = SEVERITIES.index(severity) if severity in SEVERITIES else SEVERITIES.index("erreur")
    return rank >= SEVERITIES.index(minimum)


def filter_rig(rig: dict, eff: Effective) -> dict | None:
    """État du poste à envoyer, ou None si la catégorie est coupée ; fréquence et mode retirés sauf autorisation."""
    if not eff.rig:
        return None
    if eff.freq_mode:
        return dict(rig)
    return {k: v for k, v in rig.items() if k not in RIG_SECRET_FIELDS}
