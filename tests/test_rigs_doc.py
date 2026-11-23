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
    for change in (lambda r: r["fonctions"].update(zzz_inconnue={"etat": "valide"}),
                   lambda r: r["fonctions"]["agc"].update(etat="ok"),
                   lambda r: r["fonctions"].pop("agc")):
        rig = _rig()
        change(rig)
        with pytest.raises(doc.DocError):
            doc.check([rig])


def test_a_rig_cannot_be_validated_while_transmit_safety_is_not() -> None:
    rig = _rig()
    rig["poste"]["statut"] = "valide"
    rig["fonctions"]["operateur_local"] = {"etat": "non_teste"}
    with pytest.raises(doc.DocError, match="sécurité non validée"):
        doc.check([rig])


def test_the_comparison_shows_only_validated_and_partial_and_never_a_refused_rig() -> None:
    rig = _rig()
    other = _rig()
    other["id"], other["poste"]["modele"], other["poste"]["statut"] = "x-refuse", "REFUSÉ-1", "refuse"
    page = doc.render([rig, other])
    comparison = page.split("Comparaison des postes", 1)[1].split("Fiche de chaque poste", 1)[0]
    assert "REFUSÉ-1" not in comparison and "IC-7300MK2" in comparison
    assert "REFUSÉ-1" in page                                # sa fiche reste visible plus bas


def test_every_state_is_spelled_out_with_its_footnote_and_the_cause_of_an_unavailable_feature() -> None:
    """Demande de l'utilisateur (2026-11-19) : plus de tiret ; « non testé (1) », « non disponible (2) (cause) »,
    « ne fonctionne pas » en clair, notes de bas de page."""
    rig = _rig()
    rig["fonctions"]["agc"] = {"etat": "echec", "note": "refusé", "note_en": "refused"}
    rig["fonctions"]["squelch"] = {"etat": "non_teste"}
    rig["fonctions"]["anf"] = {"etat": "non_declare", "cause": "poste"}
    page = doc.render([rig])
    comparison = page.split("Comparaison des postes", 1)[1].split("Fiche de chaque poste", 1)[0]
    assert "<td>—</td>" not in page and "ne fonctionne pas" in comparison
    assert 'href="#note1">(1)</a></sup>' in comparison and 'href="#note2">(2)</a></sup>' in comparison
    assert "le poste" in comparison and 'id=note1' in page and 'id=note2' in page
    assert page.count("(2) Non disponible") == 2             # sous la comparaison et en bas de page


def test_an_unavailable_feature_needs_its_cause() -> None:
    rig = _rig()
    rig["fonctions"]["anf"] = {"etat": "non_declare"}
    with pytest.raises(doc.DocError, match="cause"):
        doc.check([rig])
    rig["fonctions"]["anf"] = {"etat": "non_declare", "cause": "lune"}
    with pytest.raises(doc.DocError, match="cause"):
        doc.check([rig])


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
    assert {p["poste"]["hamlib_model"] for p in data["postes"]} >= {3094, 3085}


def test_public_data_holds_no_address_host_or_serial() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in doc.DATA.glob("*.toml"))
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)          # aucune adresse IP
    assert "minix" not in text.lower() and "13003336" not in text and "43003441" not in text   # ni machine, ni n° de série


def test_every_partial_or_failed_feature_has_a_numbered_clickable_note() -> None:
    """Demande de l'utilisateur (2026-11-19) : renvoi numéroté (à partir de 3) vers une note qui dit ce qui ne marche pas,
    dans la fiche et dans la comparaison."""
    rig = _rig()
    rig["fonctions"]["agc"] = {"etat": "partiel", "note": "écriture refusée", "note_en": "write refused"}
    page = doc.render([rig])
    marks = doc.number_partials([rig])
    number = marks[("icom-ic7300mk2", "agc")]
    assert number >= 3 and f'href="#p-icom-ic7300mk2-agc">({number})</a></sup>' in page
    assert page.count('href="#p-icom-ic7300mk2-agc"') == 2              # fiche et comparaison
    assert f'<p id="p-icom-ic7300mk2-agc"><small>({number})' in page and "écriture refusée" in page
    assert len(set(marks.values())) == len(marks)                         # numéros uniques


def test_rating_counts_what_trx_remote_uses_and_the_rig_offers() -> None:
    """Note sur 5 (validée par l'utilisateur, 2026-11-19) : absences dues au POSTE hors du calcul, limites de Hamlib / TRX
    distant comptées ½, sécurité d'émission d'abord, défauts aléatoires = 3 étoiles au plus, provisoire si non testé."""
    rig = _rig()
    r = doc.rating(rig)
    assert r["stars"] == 5.0 and not r["provisional"] and len(r["absent"]) == 2 and r["valid"] == r["counted"]
    rig["fonctions"]["agc"] = {"etat": "non_declare", "cause": "poste"}           # absent du poste : rien ne change
    assert doc.rating(rig)["stars"] == 5.0
    rig["fonctions"]["agc"] = {"etat": "non_declare", "cause": "hamlib"}          # limite de Hamlib : ½
    rig["fonctions"]["nr"] = {"etat": "echec", "note": "x", "note_en": "x"}
    r = doc.rating(rig)
    assert r["stars"] == round((r["counted"] - 1.5) / r["counted"] * 10) / 2 and r["limits"]
    rig["fonctions"]["nb"] = {"etat": "non_teste"}
    assert doc.rating(rig)["provisional"]
    rig["poste"]["stabilite"] = "defauts"
    assert doc.rating(rig)["stars"] == 3.0
    rig["poste"]["stabilite"] = "ok"
    rig["fonctions"]["tot"] = {"etat": "non_teste"}                                # sécurité incomplète : pas de note
    assert doc.rating(rig)["stars"] is None
    del rig["poste"]["stabilite"]
    rig["fonctions"]["tot"] = {"etat": "valide"}
    assert doc.rating(rig)["stars"] is None                                       # stabilité pas évaluée


def test_stars_are_shown_and_stability_is_checked() -> None:
    rig = _rig()
    page = doc.render([rig])
    assert "★★★★★" in page and "5/5" in page and "Absent du poste" in page
    rig["poste"]["stabilite"] = "defauts"
    with pytest.raises(doc.DocError, match="stabilite_note"):
        doc.check([rig])
    rig["poste"]["stabilite"] = "peut-etre"
    with pytest.raises(doc.DocError, match="stabilite"):
        doc.check([rig])
    assert doc._stars(4.5) == "★★★★½" and doc._stars(3.0) == "★★★☆☆"



def test_comparison_names_link_to_their_sheet_and_show_the_rating() -> None:
    rig = _rig()
    other = _rig()
    other["id"], other["poste"]["modele"] = "x-sans-note", "SANS-NOTE"
    other["fonctions"]["tot"] = {"etat": "non_teste"}
    comparison = doc.render([rig, other]).split("Comparaison des postes", 1)[1].split("Fiche de chaque poste", 1)[0]
    assert '<a href="#icom-ic7300mk2">Icom IC-7300MK2</a><br><span class="etoiles">★★★★★</span> 5/5' in comparison
    assert '<a href="#x-sans-note">' in comparison and "note attendue" in comparison


def test_usb_list_is_consistent_and_lists_every_tried_rig() -> None:
    usb = doc.load_usb()
    assert len(usb["usb"]) >= 20
    doc.check_usb(usb, doc.load_rigs())


def test_usb_list_refuses_a_duplicate_hamlib_number_and_an_unknown_sheet() -> None:
    rigs = doc.load_rigs()
    usb = doc.load_usb()
    bad = copy.deepcopy(usb)
    bad["usb"].append(dict(bad["usb"][0]))
    with pytest.raises(doc.DocError, match="en double"):
        doc.check_usb(bad, rigs)
    bad = copy.deepcopy(usb)
    bad["usb"][0]["fiche"] = "inconnu"
    with pytest.raises(doc.DocError, match="fiche inconnue"):
        doc.check_usb(bad, rigs)
    bad = copy.deepcopy(usb)
    bad["usb"] = [e for e in bad["usb"] if e.get("fiche") != "icom-ic7300mk2"]
    with pytest.raises(doc.DocError, match="absent"):
        doc.check_usb(bad, rigs)


def test_page_shows_the_usb_list_with_tried_rigs_linked() -> None:
    page = doc.render(doc.load_rigs())
    section = page.split('id="usb"', 1)[1]
    assert "IC-7610" in section and "TS-890S" in section and "FT-891" in section
    assert 'href="#icom-ic7300mk2"' in section
    assert "non essayé" in section and "not tried" in section


# --- Préqualifications par l'Autotest (étape 374)

def _reports() -> list[dict]:
    return copy.deepcopy(doc.load_autotest())


def test_prequalifications_are_consistent_and_never_change_a_sheet_or_a_rating() -> None:
    reports = _reports()
    assert reports and all(r["rapport"]["empreinte_trace"] for r in reports)
    doc.check_autotest(reports)
    rigs = doc.load_rigs()
    assert {r["poste"]["hamlib_model"] for r in rigs}.isdisjoint({3070}), "l'IC-7100 n'a pas de fiche (préqualifié)"
    page = doc.render(rigs, reports=reports)
    assert 'id="autotest"' in page and 'id="at-icom-ic-7100-20261123-1507"' in page
    assert "n’est PAS une qualification" in page and "is NOT a qualification" in page
    # l'IC-7100 de la liste USB renvoie vers sa préqualification, jamais vers une fiche
    assert 'href="#at-icom-ic-7100-20261123-1507"' in page
    assert "IC-7100" not in "".join(doc._table2(rigs))


def test_prequalification_steps_are_those_of_the_autotest_page() -> None:
    runner = (ROOT / "autotest" / "web" / "runner.js").read_text(encoding="utf-8")
    steps = re.findall(r'\["(R\d+|E\d|RS)", "([^"]+)"\]', runner.split("const STEPS")[1].split("];")[0])
    assert steps == [(c, fr) for c, fr, _ in doc.AUTOTEST_STEPS]


def test_a_prequalification_needs_english_texts_known_codes_and_a_unique_trace() -> None:
    for change in (lambda r: r["essais"][0].update(texte_en=""),
                   lambda r: r["rapport"].update(resume_en=""),
                   lambda r: r["essais"][0].update(code="Z9"),
                   lambda r: r["essais"][0].update(statut="absent"),
                   lambda r: r["essais"][0].update(note="seulement en français"),
                   lambda r: r["rapport"].update(source="inconnue"),
                   lambda r: r["rapport"].pop("empreinte_trace")):
        reports = _reports()
        change(reports[0])
        with pytest.raises(doc.DocError):
            doc.check_autotest(reports)
    twice = _reports() + _reports()
    twice[1]["id"] = "copie"
    with pytest.raises(doc.DocError, match="double"):
        doc.check_autotest(twice)


def test_tests_not_done_are_shown_as_not_done_yet() -> None:
    page = "".join(doc._autotest_section(_reports()))
    row = re.search(r"<tr><td>E2 · .*?</tr>", page)
    assert row and "pas encore fait" in row.group(0)


def test_import_keeps_only_public_fields_and_checks_the_trace(tmp_path: Path) -> None:
    import import_autotest as imp
    trace = [{"t": 5, "d": "tx", "h": "f", "r": 0, "v": ["7074000"], "ms": 21}, {"t": 9, "d": "tx", "h": "l ALC", "r": 0, "v": ["0.0333334"], "ms": 0}]
    report = {"schema": imp.SCHEMA, "outil": {"version": "0.10.5", "mode": "B"}, "date": "2026-11-23T15:07:58.240Z",
              "systeme": "Windows", "poste": {"marque": "Hamlib", "modele_reconnu": "IC-7100", "hamlib_model": 3070,
                                              "hamlib": {"nom": "Icom IC-7100", "version": "4.7.2"}},
              "carte_son": {"entree": "Microphone (2- USB Audio CODEC )"}, "port": "COM9",
              "essais": [{"code": "R1", "statut": "ok", "texte": "Le poste répond."}],
              "trace": trace, "empreinte_trace": imp.trace_digest(trace)}
    name, text = imp.convert(report)
    assert name == "icom-ic-7100-20261123-1507.toml"
    assert "COM9" not in text and "CODEC" not in text and "7074000" not in text
    assert 'texte_en = ""' in text and 'resume_en = ""' in text           # à écrire à la main
    report["empreinte_trace"] = "0" * 64
    with pytest.raises(ValueError, match="empreinte"):
        imp.convert(report)
