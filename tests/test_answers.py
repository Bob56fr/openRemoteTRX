# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mots tapés en réponse aux questions des outils : casse et accents ignorés, mot exigé en entier."""
from trxstation.answers import normalize, typed, yes_no


def test_case_and_accents_are_ignored():
    for answer in ("OUI", "oui", "Oui", " oUi \n"):
        assert typed(answer, "OUI")
    for answer in ("EMETTRE", "emettre", "Emettre", "émettre", "ÉMETTRE", "Émettre"):
        assert typed(answer, "EMETTRE")
    assert normalize("Téléchargé") == "TELECHARGE"


def test_the_whole_word_is_required():
    for answer in ("", None, "o", "ou", "OUI!", "non", "emet", "emettre maintenant"):
        assert not typed(answer, "OUI")
        assert not typed(answer, "EMETTRE")


def test_yes_no():
    assert [yes_no(a) for a in ("o", "OUI", "Oui", "y", "Yes")] == [True] * 5
    assert [yes_no(a) for a in ("n", "NON", "Non", "no")] == [False] * 4
    assert [yes_no(a) for a in ("", None, "peut-être", "ouii")] == [None] * 4
