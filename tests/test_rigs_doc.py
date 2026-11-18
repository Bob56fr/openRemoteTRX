# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Page publique des postes (scripts/build_rigs_doc.py) : à jour, fiches cohérentes, comparaison sans échec ni
non-proposé, contenu échappé, bilingue, aucune donnée personnelle."""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_rigs_doc as doc  # noqa: E402


def test_page_and_data_are_up_to_date_with_the_rig_sheets() -> None:
    stale = doc.stale_pages()
    assert not stale, ("page des postes périmée (relancer python scripts/build_rigs_doc.py) : "
                       + ", ".join(str(p.relative_to(ROOT)) for p in stale))


def test_every_published_sheet_is_consistent() -> None:
    rigs = doc.load_rigs()
    assert rigs and any(r["id"] == "icom-ic7300mk2" for r in rigs)
    doc.check(rigs)


def _rig() -> dict:
    return copy.deepcopy(next(r for r in doc.load_rigs() if r["id"] == "icom-ic7300mk2"))


def test_a_partial_or_failed_feature_needs_its_note_in_both_languages() -> None:
    rig = _rig()
    rig["fonctions"]["agc"] = {"etat": "echec", "note": "refusé"}
    with pytest.raises(doc.DocError, match="agc"):
        doc.check([rig])


def test_unknown_features_states_or_missing_features_are_refused() -> None:
    for change in (lambda r: r["fonctions"].update(vox={"etat": "valide"}),
                   lambda r: r["fonctions"]["agc"].update(etat="ok"),
                   lambda r: r["fonctions"].pop("agc")):
        rig = _rig()
        change(rig)
        with pytest.raises(doc.DocError):
            doc.check([rig])


def test_a_rig_cannot_be_validated_while_transmit_safety_is_not() -> None:
    rig = _rig()
    rig["poste"]["statut"] = "valide"
    with pytest.raises(doc.DocError, match="sécurité non validée"):
        doc.check([rig])                                     # opérateur sur place et démarrage pas encore essayés


def test_the_comparison_shows_only_validated_and_partial_and_never_a_refused_rig() -> None:
    rig = _rig()
    other = _rig()
    other["id"], other["poste"]["modele"], other["poste"]["statut"] = "x-refuse", "REFUSÉ-1", "refuse"
    page = doc.render([rig, other])
    comparison = page.split("Comparaison des postes", 1)[1].split("Fiche de chaque poste", 1)[0]
    assert "REFUSÉ-1" not in comparison and "IC-7300MK2" in comparison
    assert "ne fonctionne pas" not in comparison and "non proposé par Hamlib</span></td>" not in comparison
    assert "REFUSÉ-1" in page                                # sa fiche reste visible plus bas


def test_page_is_escaped_and_bilingual() -> None:
    rig = _rig()
    rig["fonctions"]["agc"] = {"etat": "partiel", "note": "<script>x</script>", "note_en": "a & b"}
    page = doc.render([rig])
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page and "a &amp; b" in page
    assert 'class="fr-t"' in page and 'class="en-t"' in page and "Rig comparison" in page


def test_data_json_lists_themes_features_and_rigs() -> None:
    data = json.loads(doc.data_json(doc.load_rigs()))
    assert data["format"] == 1 and [t["id"] for t in data["themes"]][0] == "securite"
    assert {f["id"] for f in data["fonctions"]} == {f[0] for f in doc.FEATURES}
    assert data["postes"][0]["poste"]["hamlib_model"] == 3094


def test_public_data_holds_no_address_host_or_serial() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in doc.DATA.glob("*.toml"))
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)          # aucune adresse IP
    assert "minix" not in text.lower() and "13003336" not in text        # ni nom de machine, ni numéro de série
