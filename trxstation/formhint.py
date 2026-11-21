# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Questions d'un outil lancé par la console web (étape 236, lot W3b).

Un outil (trx-setup…) lancé par un menu ouvert dans la PAGE (openRemoteTRX Console en formulaires) tourne comme une commande :
sa sortie part dans la page, l'entrée vient de la page. Avant chaque question, il écrit une ligne marquée qui en dit la
nature (choix, oui / non, nombre et bornes, mot de passe…) ; le worker de la console web la remplace par un formulaire
et renvoie la réponse sur l'entrée de l'outil, comme une frappe. Au terminal (variable absente), rien n'est écrit :
l'outil reste identique.
"""
from __future__ import annotations

import json
import os
import sys

MARK = "\x1eTRXFORM "            # début de ligne : jamais produit par un texte ordinaire
ENV = "TRX_CONSOLE_FORMS"


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


def emit(kind: str, prompt: str, echo: str, **fields) -> None:
    """Annonce la question suivante. `echo` : texte exact que l'outil va écrire juste après comme invite (la page le
    remplace par le formulaire). Champs selon `kind` : choices [[valeur, libellé]], default, low / high / current,
    word, generate."""
    if not enabled():
        return
    fields.update(kind=kind, prompt=prompt, echo=echo)
    sys.stdout.write(MARK + json.dumps(fields, ensure_ascii=False) + "\n")
    sys.stdout.flush()
