# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Textes envoyés aux clients dans LEUR langue (lot T1 de docs/application-traduction-cahier-des-charges.md ; décision
de l'utilisateur du 2026-11-20 : la station envoie ses textes directement dans la langue de l'application ou de la
page).

Le client annonce sa langue dans `POST /offer` (`lang`, facultatif) ; une langue inconnue ou absente vaut le français
(clients plus anciens : rien ne change pour eux). Les CODES (`reason`, `event`, `ort`) ne changent jamais : seuls les
textes pour l'humain (`detail`, `message`) suivent la langue. Textes : tronc commun `trxstation/i18n/client.<langue>.json`
(le même que lisent la page et l'application) et catalogue d'erreurs (`rig_notice`).

Lot T5 : les textes des autres messages (allumage du poste, Breizh, FreeDV, surcharge) sont des `Text`
(`i18n/text.py`, clés `station.*`) refabriqués ici pour chaque client au moment de l'envoi (`localize`, appelé par
`ControlSession.send`) ; un MODULE envoie le code de son texte et ses variables (`_texts`), jamais le texte seul.
"""
from __future__ import annotations

from ...errors.emit import LANGS as ERROR_LANGS
from ...i18n import DEFAULT, LANGS, catalog
from ...i18n.text import Text, render


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


MODULE_TEXTS = "_texts"         # champ des messages de MODULE : {champ: {"key": "station.…", "fields": {…}}}
MODULE_PREFIX = "station."      # un module ne fait dire à la station que ses propres textes (jamais refus.*, coupure.*)


def localize(lang: str, value: object) -> object:
    """Message pour CE client (lot T5) : chaque `Text` (i18n/text.py) refabriqué dans sa langue ; dans un message de
    module, `_texts` (le CODE du texte et ses variables, envoyés par le module sur le bus) refabrique le champ nommé
    et disparaît toujours (même pour un client français, qui garde le texte français du module). Champ sans clé
    connue, ou dont les variables ne correspondent pas : texte français d'origine. Copie : l'original ne change pas."""
    if isinstance(value, Text):
        return value.render(lang)
    if isinstance(value, dict):
        out = {k: localize(lang, v) for k, v in value.items() if k != MODULE_TEXTS}
        specs = value.get(MODULE_TEXTS)
        if lang != DEFAULT and isinstance(specs, dict):
            for name, spec in specs.items():
                if name not in out or not isinstance(spec, dict):
                    continue
                key, fields = spec.get("key"), spec.get("fields", {})
                if not (isinstance(key, str) and key.startswith(MODULE_PREFIX) and isinstance(fields, dict)):
                    continue
                text = render(lang, key, {str(k): str(v) for k, v in fields.items()
                                          if isinstance(v, (str, int, float)) and not isinstance(v, bool)})
                if text is not None:
                    out[name] = text
        return out
    if isinstance(value, (list, tuple)):
        return [localize(lang, v) for v in value]
    return value


def needs_localize(lang: str, message: dict) -> bool:
    """Français : les `Text` partent tels quels (leur valeur est le français) ; seul un message de module peut porter
    `_texts`, à retirer."""
    return lang != DEFAULT or message.get("type") == "module"


def errors_lang(lang: str) -> str:
    """Langue des textes du catalogue d'erreurs (`render`) pour ce client : la sienne si le catalogue l'a, sinon
    l'anglais pour une langue étrangère (allemand et espagnol arrivent au lot T8), le français pour un client français."""
    if lang in ERROR_LANGS:
        return lang
    return "en" if lang != DEFAULT and "en" in ERROR_LANGS else DEFAULT
