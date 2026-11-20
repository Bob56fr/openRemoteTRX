# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Textes envoyés aux clients dans LEUR langue (lot T1 de docs/application-traduction-cahier-des-charges.md ; décision
de l'utilisateur du 2026-11-20 : la station envoie ses textes directement dans la langue de l'application ou de la
page).

Le client annonce sa langue dans `POST /offer` (`lang`, facultatif) ; une langue inconnue ou absente vaut le français
(clients plus anciens : rien ne change pour eux). Les CODES (`reason`, `event`, `ort`) ne changent jamais : seuls les
textes pour l'humain (`detail`, `message`) suivent la langue. Textes : tronc commun `trxstation/i18n/client.<langue>.json`
(le même que lisent la page et l'application) et catalogue d'erreurs (`rig_notice`).
"""
from __future__ import annotations

from ...errors.emit import LANGS as ERROR_LANGS
from ...i18n import DEFAULT, LANGS, catalog


def clean_lang(value: object) -> str:
    """Langue annoncée par un client, validée (liste fermée), sinon le français."""
    return value if isinstance(value, str) and value in LANGS else DEFAULT


def client_text(lang: str, key: str, **fields: object) -> str | None:
    """Texte d'une clé du tronc commun dans la langue du client (repli : français), champs `{nom}` remplis ; None si la
    clé n'existe nulle part."""
    text = catalog(lang, "client").get(key)
    if text is None:
        text = catalog(DEFAULT, "client").get(key)
    if text is None:
        return None
    if fields:
        try:
            return text.format(**fields)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def errors_lang(lang: str) -> str:
    """Langue des textes du catalogue d'erreurs (`render`) pour ce client : la sienne si le catalogue l'a, sinon
    l'anglais pour une langue étrangère (allemand et espagnol arrivent au lot T8), le français pour un client français."""
    if lang in ERROR_LANGS:
        return lang
    return "en" if lang != DEFAULT and "en" in ERROR_LANGS else DEFAULT
