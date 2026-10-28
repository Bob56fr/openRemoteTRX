# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mots tapés en réponse aux questions des outils (OUI, EMETTRE...) : casse et accents ignorés.

« oui », « Oui », « OUI » valent OUI ; « émettre », « Emettre », « EMETTRE » valent EMETTRE. Le mot reste exigé en
entier : une confirmation d'émission n'est jamais devinée.
"""
from __future__ import annotations

import unicodedata


def normalize(text: str | None) -> str:
    """Majuscules, sans accents, sans espaces autour."""
    decomposed = unicodedata.normalize("NFKD", (text or "").strip())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def typed(answer: str | None, word: str) -> bool:
    """La réponse est-elle exactement ce mot (casse et accents ignorés) ?"""
    return normalize(answer) == normalize(word)


YES_WORDS = ("O", "OUI", "Y", "YES")
NO_WORDS = ("N", "NON", "NO")


def yes_no(answer: str | None) -> bool | None:
    """o/oui/y/yes => True, n/non/no => False, autre chose (ou vide) => None."""
    word = normalize(answer)
    if word in YES_WORDS:
        return True
    if word in NO_WORDS:
        return False
    return None
