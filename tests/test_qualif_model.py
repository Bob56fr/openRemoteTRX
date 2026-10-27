# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Qualification (lot Q1) : profil Hamlib, cahier de test généré, fiche TRX, catalogue et verdict."""
import pytest

from trxstation.devtools.sample_caps import SAMPLE_DUMP_CAPS
from trxstation.qualif.plan import FIXE, GENERE, SOCLE, SOCLE_ITEMS, build_plan, render_plan
from trxstation.qualif.profile import parse_profile, version_tuple
from trxstation.qualif.results import (INCOMPLETE, IN_VALIDATION, REFUSE, Check, collect_measures, compute_verdict,
                                       draft_sheet)
from trxstation.qualif.sheet import (RigSheet, SheetError, load_catalog, load_sheet, render_sheet, sheet_from_dict,
                                     validate_sheet)


def profile():
    return parse_profile(SAMPLE_DUMP_CAPS, 3094)


# --------------------------------------------------------------------------- profil

def test_profile_reads_read_and_write_lists_with_ranges():
    p = profile()
    assert p.name == "Icom IC-7300MK2" and p.backend_status == "Stable" and p.hamlib_version == "4.6.2"
    assert "STRENGTH" in p.get_levels and "STRENGTH" not in p.set_levels
    assert "SQL" in p.set_levels and p.level_ranges["SQL"].high == 1.0
    assert p.level_ranges["PREAMP"].step == 10 and p.level_ranges["AGC"].high == 6
    assert "TUNER" in p.set_functions and "AIP" in p.get_functions
    assert p.preamps == (10, 20) and p.attenuators == (20,) and p.agc_levels == (1, 2, 3)
    assert p.can["get PTT"] is True and p.can["get VFO"] is False and p.can["set Split VFO"] is True   # E = émulé
    assert p.modes[:4] == ("AM", "CW", "USB", "LSB") and p.caps.filters["USB"] == [3000, 2400, 1800]


def test_unknown_format_gives_an_empty_profile_not_guesses():
    p = parse_profile("rien d'exploitable", 1)
    assert p.modes == () and p.get_functions == () and p.backend_status == "" and p.hamlib_version == ""


def test_version_tuple():
    assert version_tuple("4.6.2") == (4, 6, 2) and version_tuple("") == () and version_tuple("4.5") < (4, 6)


# --------------------------------------------------------------------------- plan

def test_plan_has_the_fixed_socle_for_every_rig():
    plan = build_plan(parse_profile("", 1))
    assert [i.id for i in plan.of(SOCLE)] == [i for i, _ in SOCLE_ITEMS]
    assert plan.of(GENERE) == [] and plan.by_id("cat_loss_rx").category == SOCLE


def test_plan_generates_tests_only_for_declared_functions_used_by_trx_remote():
    plan = build_plan(profile())
    ids = {i.id for i in plan.items}
    assert {"read_level_STRENGTH", "read_func_NB", "write_func_NR", "write_level_SQL", "write_level_RFPOWER",
            "mode_PKTUSB"} <= ids
    assert "write_level_ATT" in ids                             # ATT est écrit par TRX Remote depuis la 0.40.0 (bouton ATT)
    assert plan.by_id("write_func_TUNER").action == "manual"   # jamais automatique : peut lancer un accord
    assert {"MON", "VOX", "SCOPE", "AF", "MICGAIN"} <= set(plan.unused)
    assert "NR" not in plan.unused and "STRENGTH" not in plan.unused
    assert plan.by_id("mode_USB").note and not plan.by_id("mode_RTTY").note


def test_plan_text_lists_categories_and_unused():
    text = render_plan(build_plan(profile()), profile())
    assert "Socle obligatoire" in text and "non testé automatiquement" in text and "non exploité" in text


# --------------------------------------------------------------------------- fiche

def good_sheet(**changes):
    data = dict(nom="IC-7300MK2", hamlib_model=3094, hamlib_min="4.6", statut="validation_en_cours",
                firmware=["1.10"], fonctions={"freq": True, "mode": True, "ptt": True, "audio_rx": True, "nr": False},
                avertissements={"nr": "sans effet"}, mesures={"latence_cat_ms": 45.0})
    data.update(changes)
    return RigSheet(**data)


def test_sheet_round_trip(tmp_path):
    path = tmp_path / "ic7300.toml"
    path.write_text(render_sheet(good_sheet(), ["brouillon"]), encoding="utf-8")
    sheet = load_sheet(path)
    assert sheet.available("freq") and not sheet.available("nr") and sheet.firmware == ["1.10"]
    assert sheet.mesures["latence_cat_ms"] == 45.0 and sheet.avertissements["nr"] == "sans effet"


def test_usable_status_without_the_full_socle_is_refused():
    problems = validate_sheet(good_sheet(fonctions={"freq": True, "mode": True, "ptt": False, "audio_rx": True}))
    assert any("socle" in p and "ptt" in p for p in problems)
    assert validate_sheet(good_sheet(statut="refuse", fonctions={"ptt": False})) == []
    with pytest.raises(SheetError):
        render_sheet(good_sheet(fonctions={"freq": True}))


def test_sheet_rejects_unknown_fields_and_bad_values():
    assert any("inconnue" in p for p in validate_sheet(good_sheet(fonctions={**good_sheet().fonctions, "laser": True})))
    assert any("hamlib_min" in p for p in validate_sheet(good_sheet(hamlib_min="récente")))
    assert any("plus ancienne" in p for p in validate_sheet(good_sheet(hamlib_teste="4.5")))
    with pytest.raises(SheetError):
        sheet_from_dict({"rig": {"nom": "x", "hamlib_model": 1, "hamlib_min": "4.6", "statut": "refuse",
                                 "fiche_version": 1, "couleur": "rouge"}})
    with pytest.raises(SheetError):
        sheet_from_dict({"fonctions": {}})


def test_unusable_sheet_offers_nothing():
    sheet = good_sheet(statut="refuse")
    assert not sheet.available("freq")


def test_catalog_lookup_and_rejected_files(tmp_path):
    (tmp_path / "a.toml").write_text(render_sheet(good_sheet()), encoding="utf-8")
    (tmp_path / "b.toml").write_text(render_sheet(good_sheet(firmware=["1.20"], fiche_version=2)), encoding="utf-8")
    (tmp_path / "casse.toml").write_text("[rig]\nnom = \n", encoding="utf-8")
    catalog = load_catalog(tmp_path)
    assert "casse.toml" in catalog.problems and len(catalog.sheets[3094]) == 2
    sheet, warnings = catalog.lookup(3094, firmware="1.10", hamlib="4.6.2")
    assert sheet.firmware == ["1.10"] and not any("firmware" in w for w in warnings)
    sheet, warnings = catalog.lookup(3094, firmware="2.00", hamlib="4.5")
    assert sheet.fiche_version == 2
    assert any("firmware 2.00 non qualifié" in w for w in warnings) and any("Hamlib 4.5" in w for w in warnings)
    assert any("en validation" in w for w in warnings)
    assert catalog.lookup(1234) == (None, ["poste absent du catalogue : non qualifié"])


# --------------------------------------------------------------------------- verdict

def socle(ok=True, **overrides):
    checks = [Check(i, lbl, SOCLE, overrides.get(i, ok), "détail") for i, lbl in SOCLE_ITEMS]
    return checks


def test_verdict_is_computed_from_raw_results():
    assert compute_verdict(socle()).status == IN_VALIDATION
    assert compute_verdict(socle(ptt_cycle=False)).status == REFUSE
    assert compute_verdict(socle(cat_loss_rx=None)).status == INCOMPLETE
    assert compute_verdict(socle()[:-1]).status == INCOMPLETE
    retried = socle(freq_rw=False) + [Check("freq_rw", "Fréquence", SOCLE, True)]   # le dernier essai compte
    assert compute_verdict(retried).status == IN_VALIDATION


def test_draft_sheet_marks_unproven_features_unavailable():
    p = profile()
    checks = socle() + [Check("audio_tx", "Audio TX", FIXE, True), Check("read_level_STRENGTH", "S", GENERE, True),
                        Check("write_func_NR", "NR", GENERE, False, "relu 0"),
                        Check("latency", "Latence", FIXE, True, "", {"latence_cat_ms": 40.0, "latence_cat_p95_ms": 60.0,
                                                                     "polling_max_hz": 16.7}),
                        Check("ptt_cycle", "PTT", SOCLE, True, "2 cycles, prise max 120 ms, coupure max 80 ms")]
    sheet, verdict = draft_sheet(checks, p, firmware="1.10")
    assert verdict.status == IN_VALIDATION and sheet.statut == "validation_en_cours"
    assert sheet.fonctions["smetre"] and sheet.fonctions["audio_tx"]
    assert sheet.fonctions["nr"] is False and "relu 0" in sheet.avertissements["nr"]
    assert sheet.fonctions["nb"] is False and "non testé" in sheet.avertissements["nb"]
    assert sheet.fonctions["tuner"] is False and sheet.fonctions["scope"] is False
    assert sheet.mesures["ptt_prise_ms"] == 120 and sheet.mesures["latence_cat_ms"] == 40.0
    assert sheet.hamlib_min == "4.6.2" and sheet.firmware == ["1.10"] and sheet.validation["rapports_qualif"] == 1
    render_sheet(sheet)                                         # le brouillon est une fiche valide


def test_draft_of_a_failed_or_incomplete_rig_is_never_usable():
    for checks in (socle(mode_rw=False), socle(audio_rx=None)):
        sheet, _ = draft_sheet(checks, profile())
        assert sheet.statut == "refuse" and not sheet.usable


def test_measures_ignore_failed_checks():
    assert collect_measures([Check("latency", "", FIXE, False, "", {"latence_cat_ms": 1})]) == {}
