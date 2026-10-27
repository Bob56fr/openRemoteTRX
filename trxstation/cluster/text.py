# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Nettoyage du texte reçu d'internet et contrôle des indicatifs."""

from __future__ import annotations

import re
import unicodedata

MAX_LINE = 512                 # octets par ligne reçue ; au-delà, la ligne est jetée

_BIDI = set("‎‏‪‫‬‭‮⁦⁧⁨⁩")
_CALL_RE = re.compile(r"[A-Z0-9]+(?:/[A-Z0-9]+){0,2}")


def clean_line(raw: bytes) -> str:
    """Décode une ligne (UTF-8 sinon Latin-1) et retire contrôle, direction et espaces de fin."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    kept = []
    for ch in text:
        if ch == "\t":
            kept.append(" ")
        elif ch in _BIDI or unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue
        else:
            kept.append(ch)
    return "".join(kept).rstrip()


def base_call(call: str) -> str:
    """Indicatif sans SSID ni marque de skimmer : « DK8NE-#» -> « DK8NE », « F5ABC-2 » -> « F5ABC »."""
    call = call.upper().strip()
    while True:
        cut = re.sub(r"-(#|\d{1,2})$", "", call)
        if cut == call:
            return call
        call = cut


def is_callsign(call: str) -> bool:
    """Forme plausible d'un indicatif : 3 à 15 caractères A-Z 0-9 /, au moins une lettre et un chiffre."""
    if not isinstance(call, str) or not 3 <= len(call) <= 15 or not _CALL_RE.fullmatch(call):
        return False
    return any(c.isdigit() for c in call) and any(c.isalpha() for c in call)


MAX_OWN_CALL = 20


def own_call_problem(call: object) -> str | None:
    """Phrase si l'indicatif de l'UTILISATEUR ne peut pas être envoyé ; None s'il est acceptable.

    Aucun contrôle de FORME (décision de l'utilisateur, 2026-10-27) : indicatifs étrangers, d'écouteur
    (« F-80123 »), de cibiste (« 14AT123 ») passent. Seules règles : il est envoyé tel quel au serveur,
    donc ni espace ni caractère de contrôle (un retour à la ligne y glisserait une commande), et borné.
    """
    if not isinstance(call, str) or not call.strip():
        return "indicatif vide"
    call = call.strip()
    if len(call) > MAX_OWN_CALL:
        return f"indicatif de plus de {MAX_OWN_CALL} caractères"
    if any(ch.isspace() or not ch.isprintable() for ch in call):
        return "indicatif avec espace ou caractère de contrôle (il serait envoyé tel quel au serveur)"
    return None


def check_own_call(call: object) -> str:
    """Indicatif de l'utilisateur, normalisé (majuscules) ; ValueError s'il est vide ou inenvoyable."""
    problem = own_call_problem(call)
    if problem == "indicatif vide":
        raise ValueError("indicatif vide : le cluster ne peut pas être activé sans votre indicatif")
    if problem:
        raise ValueError(f"{problem} : {str(call)[:40]!r}")
    return call.strip().upper()


def check_password(password: object) -> str:
    """Mot de passe envoyable : aucun caractère de contrôle (sinon il injecterait une commande)."""
    if not isinstance(password, str) or not password:
        raise ValueError("mot de passe vide")
    if any(unicodedata.category(c) == "Cc" for c in password) or len(password) > 128:
        raise ValueError("mot de passe refusé : caractère de contrôle ou plus de 128 caractères")
    return password
