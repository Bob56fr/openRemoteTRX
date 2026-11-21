# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Textes de la station pour les CLIENTS, refabriqués dans la langue de chacun (lot T5 de
docs/application-traduction-cahier-des-charges.md, § 3.3).

`Text` est une chaîne dont la VALEUR est le texte français (journal, fichiers d'état, openRemoteTRX Console, alertes ntfy et
clients français : rien ne change pour eux) ; elle garde la clé du tronc commun (`trxstation/i18n/client.<langue>.json`,
clés `station.*`) et ses champs `{nom}`. La passerelle la refabrique pour chaque client au moment de l'envoi
(`gateway/api/texts.py`, `localize`). Un champ peut être lui-même un `Text` (traduit aussi) ; un détail technique
(message d'exception, nom de port) reste une chaîne ordinaire, jamais traduite.

Attention : une concaténation (`Text + "…"`, f-string) rend une chaîne ORDINAIRE (le texte français seul) : pour un
texte destiné aux clients, passer par une clé et ses champs.
"""
from __future__ import annotations

from . import DEFAULT, catalog


def render(lang: str, key: str, fields: dict) -> str | None:
    """Texte d'une clé du tronc commun dans `lang` (repli : français), champs remplis ; None si la clé n'existe nulle
    part ou si ses champs ne correspondent pas."""
    text = catalog(lang, "client").get(key)
    if text is None:
        text = catalog(DEFAULT, "client").get(key)
    if text is None:
        return None
    try:
        return text.format(**fields)
    except (KeyError, IndexError, ValueError):
        return None


class Text(str):
    """Texte français (la valeur) + clé du tronc commun et champs, pour le refabriquer dans une autre langue."""

    key: str
    fields: dict

    def __new__(cls, key: str, /, _fr: str | None = None, **fields: object) -> "Text":
        if _fr is None:
            _fr = render(DEFAULT, key, {k: str(v) for k, v in fields.items()})
            if _fr is None:
                raise KeyError(f"clé {key} absente du tronc commun français (ou champs faux)")
        obj = super().__new__(cls, _fr)
        obj.key, obj.fields = key, dict(fields)
        return obj

    def __reduce__(self):                        # copie, deepcopy, pickle : la clé et les champs suivent
        return (_rebuild, (str(self), self.key, self.fields))

    def render(self, lang: str) -> str:
        """Le texte dans `lang` (chaîne ordinaire) ; français = la valeur, exactement."""
        if lang == DEFAULT:
            return str(self)
        fields = {k: v.render(lang) if isinstance(v, Text) else str(v) for k, v in self.fields.items()}
        text = render(lang, self.key, fields)
        return str(self) if text is None else text


def _rebuild(fr: str, key: str, fields: dict) -> Text:
    return Text(key, _fr=fr, **fields)
