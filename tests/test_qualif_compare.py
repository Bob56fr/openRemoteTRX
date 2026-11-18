# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Comparaison de deux qualifications du même poste (`trx-qualif --comparer`) : aucun écart entre un rapport et
lui-même (dossier ou zip), chaque écart trouvé avec sa gravité et sa cause, documents écrits."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trxstation.qualif import compare as cmp
from trxstation.qualif import main as qmain
from trxstation.qualif import terrain
from trxstation.qualif.terrain import Session


def _report(tmp_path: Path, name: str, *, model=3094, heartbeat="2.1", audio_ok=True, auto_delay=0.16,
            manual="reussi", constats=("backend_status",), start_af="0.5", latency=1.8) -> Path:
    s = Session.open(tmp_path / name, model=model, model_name="IC-7300MK2", manufacturer="Icom",
                     hamlib_version="4.7.2", backend_status="Beta")
    q = s.folder / "qualif-3094-20261118-150000"
    q.mkdir()
    tests = [{"id": "audio_rx", "label": "Audio RX", "category": "socle", "ok": audio_ok, "detail": "", "data": {}},
             {"id": "drill_heartbeat", "label": "Panne : perte du heartbeat", "category": "fixe", "ok": True,
              "detail": f"coupée en {heartbeat} s par « heartbeat »", "data": {}},
             {"id": "latency", "label": "Temps de réponse CAT", "category": "fixe", "ok": True, "detail": "",
              "data": {"latence_cat_ms": latency}}]
    (q / "results.json").write_text(json.dumps({"verdict": {"statut": "validation_en_cours"}, "tests": tests}),
                                    encoding="utf-8")
    e = s.folder / "explore-3094-20261118-140000"
    e.mkdir()
    (e / "exploration.json").write_text(json.dumps({"constats": [{"id": c, "title": c} for c in constats]}),
                                        encoding="utf-8")
    (s.folder / "essais").mkdir()
    for did, record in (("auto_stop", {"result": "reussi", "measures": {"delai_s": auto_delay}}),
                        ("stop_page", {"result": manual, "measures": {"delay_from_mark_s": 0.4}})):
        (s.folder / "essais" / f"{did}.json").write_text(json.dumps({"id": did, **record}), encoding="utf-8")
        s.drills[did] = {"result": record["result"]}
    (s.folder / "reglages").mkdir()
    (s.folder / "reglages" / "releve-avant.json").write_text(json.dumps({"f": "28500000", "l AF": start_af}),
                                                             encoding="utf-8")
    s.save()
    return terrain.build_report(s, settings={"hamlib_model": model}, out_dir=tmp_path)


def _gaps(tmp_path, **changes):
    a = cmp.load_report(_report(tmp_path / "a", "terrain-a"))
    b = cmp.load_report(_report(tmp_path / "b", "terrain-b", **changes))
    return cmp.compare(a, b)


def test_a_report_compared_with_itself_has_no_gap_folder_or_zip(tmp_path):
    zipped = _report(tmp_path, "terrain-a")
    assert cmp.compare(cmp.load_report(zipped), cmp.load_report(tmp_path / "terrain-a")) == []


def test_two_different_rigs_are_an_important_gap(tmp_path):
    gaps = _gaps(tmp_path, model=3085)
    assert any(g.item == "modèle Hamlib" and g.gravity == cmp.IMPORTANT for g in gaps)


@pytest.mark.parametrize("changes,item,gravity,cause", [
    ({"audio_ok": False}, "Audio RX", cmp.IMPORTANT, "poste"),
    ({"heartbeat": "3.4"}, "Panne : perte du heartbeat", cmp.CHECK, "poste"),
    ({"manual": "echec"}, "stop_page", cmp.IMPORTANT, "opérateur"),
    ({"auto_delay": 1.4}, "auto_stop : delai_s", cmp.CHECK, "poste"),
    ({"constats": ("backend_status", "rigctld_crash_p_KEYERTYPE")}, "rigctld_crash_p_KEYERTYPE", cmp.CHECK, "poste"),
    ({"start_af": "0.3"}, "l AF", cmp.CHECK, "opérateur"),
    ({"latency": 9.0}, "temps de réponse CAT (ms)", cmp.INFO, "environnement"),
])
def test_each_kind_of_gap_is_found_with_its_gravity_and_cause(tmp_path, changes, item, gravity, cause):
    gaps = _gaps(tmp_path, **changes)
    found = [g for g in gaps if g.item == item]
    assert found and found[0].gravity == gravity and found[0].cause == cause, gaps


def test_small_differences_within_tolerance_are_not_gaps(tmp_path):
    assert _gaps(tmp_path, heartbeat="2.3", auto_delay=0.4, latency=2.5) == []


def test_the_command_writes_both_documents(tmp_path, capsys):
    a = _report(tmp_path / "a", "terrain-a")
    b = _report(tmp_path / "b", "terrain-b", manual="echec")
    assert qmain.main(["--comparer", str(a), str(b), "--output", str(tmp_path / "out")]) == qmain.EXIT_OK
    folder = next((tmp_path / "out").glob("comparaison-*"))
    data = json.loads((folder / "ecarts.json").read_text(encoding="utf-8"))
    assert data["format"] == 1 and any(g["item"] == "stop_page" for g in data["ecarts"])
    assert "| IMPORTANT | essais | stop_page |" in (folder / "ecarts.md").read_text(encoding="utf-8")
    assert qmain.main(["--comparer", str(tmp_path / "absent.zip"), str(a)]) == qmain.EXIT_CONFIG


def test_the_last_qualification_WITH_transmission_is_compared(tmp_path):
    """Une qualification sans émission faite APRÈS ne masque pas celle avec émission (vu sur l'IC-705)."""
    z = _report(tmp_path, "terrain-a")
    folder = tmp_path / "terrain-a"
    later = folder / "qualif-3094-20261118-170000"
    later.mkdir()
    (later / "results.json").write_text(json.dumps({"verdict": {"statut": "incomplet"}, "tests": [
        {"id": "ptt_cycle", "ok": None, "detail": "non fait : --sans-emission", "category": "socle"}]}), encoding="utf-8")
    (folder / "qualif-3094-20261118-150000" / "results.json").write_text(json.dumps(
        {"verdict": {"statut": "validation_en_cours"}, "tests": [{"id": "ptt_cycle", "ok": True, "detail": ""}]}),
        encoding="utf-8")
    report = cmp.load_report(folder)
    assert report["q1_folder"] == "qualif-3094-20261118-150000"


def test_a_test_done_on_one_side_only_is_not_an_important_gap(tmp_path):
    """IC-705 : le débranchement USB fait par le qualifieur seul (A = non fait) apparaissait « important »."""
    gaps = _gaps(tmp_path, audio_ok=None)
    found = [g for g in gaps if g.item == "Audio RX"]
    assert found and found[0].gravity == cmp.CHECK and found[0].cause == "opérateur"
