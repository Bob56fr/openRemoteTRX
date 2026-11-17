# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Textes MONTRÉS ou DEMANDÉS par `trx-qualif` dans la langue de TRX Console (lot L3, domaine « qualif »).

Seul l'affichage est traduit : les documents produits (fiche.toml, results.json, plan.txt, constats.txt,
fiche-poste.md, rapport-hamlib.md, exploration.json) gardent leur langue, quelle que soit `TRX_LANG`.
Traduction faite À L'EXÉCUTION (la langue peut changer entre deux lancements de la console).
"""
from __future__ import annotations

from ..answers import typed
from ..i18n import DEFAULT, Translator, catalog, tool_translator

DOMAIN = "qualif"


def _t(key: str, **fields) -> str:
    """Texte de `key` dans la langue de l'outil (français si la clé manque)."""
    return tool_translator(DOMAIN)(key, **fields)


def _fr(key: str, **fields) -> str:
    """Même texte, en français : ce qui va dans les DOCUMENTS (résultats, fiche), quelle que soit la langue."""
    return Translator(DEFAULT, DOMAIN)(key, **fields)


def both(key: str, **fields) -> tuple[str, str]:
    """(texte du document en français, texte montré dans la langue de l'outil)."""
    return _fr(key, **fields), _t(key, **fields)


def lang() -> str:
    return tool_translator(DOMAIN).lang


def french() -> bool:
    """Affichage en français : on montre alors le texte d'origine, à l'identique."""
    return lang() == DEFAULT


def has(key: str) -> bool:
    return key in catalog(DEFAULT, DOMAIN)


def typed_yes(answer: str | None) -> bool:
    """Mot de confirmation : celui de la langue choisie OU le mot français OUI (toujours accepté), rien d'autre."""
    return any(typed(answer, word) for word in {_t("word.yes"), "OUI"})


def term(name: str) -> str:
    """Libellé d'un réglage Hamlib (NR, S-mètre…) dans la langue de l'outil ; le nom Hamlib s'il n'en a pas."""
    key = f"label.{name}"
    return _t(key) if has(key) else name
