# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""trx-qualif en quatre langues (lot L3) : catalogues `trxstation/i18n/qualif.<langue>.json` complets et cohérents,
affichage dans la langue d'openRemoteTRX Console (`TRX_LANG`), français affiché inchangé, confirmations sûres, et DOCUMENTS
produits (rapport, fiche, cahier, constats, brouillons) identiques quelle que soit la langue."""
from __future__ import annotations

import ast
import asyncio
import json
import re
import string
from pathlib import Path

import pytest

from trxstation.answers import yes_no
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.i18n import FOLDER, LANGS
from trxstation.qualif import coherence, plan, texts
from trxstation.qualif import main as qmain
from trxstation.qualif.coherence import SEVERITIES, analyse_caps, render_findings
from trxstation.qualif.explore_report import write_report
from trxstation.qualif.profile import parse_profile
from trxstation.qualif.results import INCOMPLETE, IN_VALIDATION, REFUSE
from trxstation.setup_wizard import dummy_config

from test_qualif_explore import REAL_472, REAL_50, explore_run
from test_qualif_runner import run as qualif_run

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "trxstation" / "qualif").glob("*.py"))


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((FOLDER / f"qualif.{lang}.json").read_text(encoding="utf-8"))


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


# --------------------------------------------------------------------------- catalogues

def test_the_four_catalogs_have_the_same_keys_and_the_same_fields():
    fr = _catalog("fr")
    for lang in LANGS:
        raw = (FOLDER / f"qualif.{lang}.json").read_text(encoding="utf-8")
        assert raw.endswith("}\n") and "\\u00" not in raw, f"qualif.{lang}.json : UTF-8 lisible et fin de ligne finale"
        other = _catalog(lang)
        assert set(other) == set(fr), f"qualif.{lang}.json : clés différentes {set(other) ^ set(fr)}"
        for key, text in fr.items():
            assert _fields(other[key]) == _fields(text), f"qualif.{lang}.json, {key} : variables différentes"
            assert other[key].strip(), f"qualif.{lang}.json, {key} : texte vide"


def test_markers_coloured_by_the_web_page_are_kept():
    for lang in LANGS:
        cat = _catalog(lang)
        for key in ("phase1.title", "phase2.title", "phase3.title", "phase3.no_tx_title"):
            assert re.fullmatch(r"\n=== .+ ===", cat[key]), (lang, key)
        assert "->" in cat["write.level_detail"]


def _constant_keys(tree: ast.AST) -> set[str]:
    """Clés passées en constante à _t / _fr / both / has / tr (et celles d'une expression conditionnelle)."""
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_t", "_fr", "both", "has", "tr") \
                and node.args:
            arg = node.args[0]
            candidates = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
            keys |= {c.value for c in candidates if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if isinstance(node, ast.keyword) and node.arg == "key" and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and node.value.value:
            keys |= {f"finding.{node.value.value}.title"}
    return keys


def _dynamic_keys() -> set[str]:
    """Clés construites à l'exécution (nom de test, libellé Hamlib, gravité, constat dont la clé est calculée)."""
    keys = {f"check.{i}" for i, _ in plan.SOCLE_ITEMS + plan.FIXED_ITEMS}
    keys |= {"check.decl_freq", "check.decl_audio_rx", "check.decl_skipped", "phase2.on", "phase2.off"}
    keys |= {f"label.{n}" for n in plan.LABELS} | {f"plan.no_auto.{n}" for n in plan.NO_AUTO_WRITE}
    keys |= {f"plan.category.{c}" for c in (plan.SOCLE, plan.FIXE, plan.GENERE)}
    keys |= {f"summary.category.{c}" for c in (plan.SOCLE, plan.FIXE, plan.GENERE, plan.DECLARATIF)}
    keys |= {f"verdict.{s}" for s in (REFUSE, INCOMPLETE, IN_VALIDATION)} | {f"findings.{s}" for s in SEVERITIES}
    keys |= {f"stop.{k}" for k in ("ptt_unreadable", "transmitting", "snapshot", "burst_tx")}
    keys |= {f"term.{k}" for k in ("frequency", "mode", "ptt")}
    findings = [f"cannot_{k}" for k in ("set_frequency", "get_frequency", "set_mode", "get_mode", "get_ptt")]
    findings += ["list_vs_range_PREAMP", "list_vs_range_ATT", "func_write_only", "level_write_only"]
    findings += [f"coverage_edge_{e}{r}" for e in ("low", "high") for r in ("", "_read")]
    return keys | {f"finding.{f}.title" for f in findings}


def test_every_key_used_by_trx_qualif_exists_in_french():
    fr = _catalog("fr")
    used = set().union(*(_constant_keys(ast.parse(p.read_text(encoding="utf-8"))) for p in SOURCES)) | _dynamic_keys()
    missing = sorted(k for k in used if k not in fr)
    assert not missing, f"clés absentes de qualif.fr.json : {missing}"


def test_hamlib_labels_and_preflight_in_french_are_the_original_texts():
    fr = _catalog("fr")
    assert {k: fr[f"label.{k}"] for k in plan.LABELS} == plan.LABELS
    assert fr["explore.preflight"] == qmain.EXPLORE_PREFLIGHT
    assert {f"check.{i}": lbl for i, lbl in plan.SOCLE_ITEMS + plan.FIXED_ITEMS} == \
           {k: v for k, v in fr.items() if k[6:] in dict(plan.SOCLE_ITEMS + plan.FIXED_ITEMS) and k.startswith("check.")}


# --------------------------------------------------------------------------- confirmations

@pytest.mark.parametrize("lang", LANGS)
def test_only_the_word_of_the_language_or_oui_confirms(lang, monkeypatch):
    """Sécurité : une traduction ne change jamais la logique d'une confirmation (mot en entier, rien par défaut)."""
    monkeypatch.setenv("TRX_LANG", lang)
    word = _catalog(lang)["word.yes"]
    assert texts.typed_yes(word) and texts.typed_yes(word.lower()) and texts.typed_yes("OUI") and texts.typed_yes("oui")
    for answer in ("", "o", "y", "j", "s", "non", "no", "N", "1", f"{word}!"):
        assert not texts.typed_yes(answer), (lang, answer)


@pytest.mark.parametrize("lang", LANGS)
def test_yes_no_letters_shown_in_each_language_are_accepted(lang):
    cat = _catalog(lang)
    assert yes_no(cat["word.yes"]) is True
    for key, default_is_yes in (("yesno.default_yes", True), ("yesno.default_no", False)):
        yes, no = cat[key].split("/")
        assert yes_no(yes) is True and yes_no(no) is False, (lang, key)
        assert (yes.isupper() if default_is_yes else no.isupper()), (lang, key)      # majuscule = réponse par défaut


def test_the_explorer_refuses_anything_else_than_the_confirmation_word(tmp_path, monkeypatch):
    monkeypatch.setenv("TRX_LANG", "en")
    for answer in ("y", "yes please", ""):
        prompts = []
        code = asyncio.run(qmain.run_explore(dummy_config(), parse_profile(REAL_50, 3094), REAL_50, tmp_path, spawn=False,
                                             ask=lambda p: prompts.append(p) or answer, out=lambda s: None))
        assert code == qmain.EXIT_INCOMPLETE and prompts == ["Type YES to start: "]
    assert not any(tmp_path.iterdir())


# --------------------------------------------------------------------------- affichage

def _explore_findings():
    found = []

    async def scenario(ex, fake, out):
        found.extend((await ex.run()).findings)
    explore_run(scenario, profile_text=REAL_472)
    return found


def test_french_display_is_exactly_the_original_text():
    profile = parse_profile(REAL_472, 3094)
    assert plan.render_plan_shown(plan.build_plan(profile), profile) == plan.render_plan(plan.build_plan(profile), profile)
    findings = analyse_caps(profile) + _explore_findings()
    for broken in (REAL_50.replace("Can get PTT:\tY", "Can get PTT:\tN").replace("Can set Frequency:\tY", "Can set Frequency:\tN"),):
        findings += analyse_caps(parse_profile(broken, 3094))
    assert all(f.key for f in findings), [f.id for f in findings if not f.key]
    for f in findings:
        assert f.shown() == (f.title, f.detail), f.id
    assert render_findings(findings, shown=True) == render_findings(findings)
    assert render_findings([], shown=True) == render_findings([])


def test_the_plan_is_shown_in_english(monkeypatch, capsys):
    monkeypatch.setenv("TRX_LANG", "en")
    monkeypatch.setattr(qmain, "_run_dump_caps", lambda model, hamlib_dir: REAL_50)
    assert qmain.main(["--plan", "--modele", "3094"]) == qmain.EXIT_OK
    text = capsys.readouterr().out
    assert text.startswith("Test plan: Icom IC-7300MK2 (Hamlib model 3094")
    assert "Mandatory core (one failure rejects the rig)" in text and "  - Read: noise reduction (NR), level" in text
    assert "dump_caps inconsistencies (no command sent to the rig):" in text and "To check:" in text
    assert "Preamps: the list (" in text and "\"Has async data support: Y\"" in text
    assert "Cahier de test" not in text and "Lecture :" not in text and "finding." not in text


def test_the_exploration_speaks_english_and_its_documents_stay_in_french(tmp_path, monkeypatch):
    def explore(lang: str) -> tuple[Path, list[str], list[str]]:
        monkeypatch.setenv("TRX_LANG", lang)
        out, prompts = [], []
        answers = iter([_catalog(lang)["word.yes"], ""])

        async def scenario():
            fake = FakeRigctld()
            await fake.start()
            cfg = dummy_config()
            cfg.network.rigctld_port = fake.port
            try:
                code = await qmain.run_explore(cfg, parse_profile(REAL_50, 3094), REAL_50, tmp_path / lang, spawn=False,
                                               ask=lambda p: prompts.append(p) or next(answers), out=out.append,
                                               burst=20, settle_s=0.3)
            finally:
                await fake.stop()
            assert code == qmain.EXIT_OK and fake.ptt_set_calls == 0
        asyncio.run(scenario())
        return next((tmp_path / lang).glob("explore-3094-*")), out, prompts

    fr_dir, fr_out, _ = explore("fr")
    en_dir, en_out, en_prompts = explore("en")
    shown = "\n".join(en_out)
    assert en_prompts == ["Type YES to start: ", "Firmware version shown by the rig (Enter if unknown): "]
    assert "RECEIVE-ONLY exploration of a rig (expert)" in shown and "  Reading everything Hamlib declares…" in shown
    assert "EXPLORATION FINDINGS" in shown and "\nReport: " in shown and "CONSTATS" not in shown
    assert "CONSTATS DE L'EXPLORATION" in "\n".join(fr_out)

    def masked(path: Path) -> str:
        return re.sub(r"\d+(\.\d+)?", "#", path.read_text(encoding="utf-8"))     # dates et temps de réponse
    for name in ("exploration.json", "constats.txt", "fiche-poste.md", "rapport-hamlib.md"):
        assert masked(en_dir / name) == masked(fr_dir / name), name
    assert "Aucun constat" in masked(en_dir / "constats.txt") or "À vérifier :" in masked(en_dir / "constats.txt")


HWTEST_IDS = {"cat", "audio_rx"}       # résultats de trx-hwtest : leur détail suit la langue de trx-hwtest


def test_the_qualification_speaks_english_and_its_report_stays_in_french(tmp_path, monkeypatch):
    reports, outputs = {}, {}
    answers = {"YES": "YES", "Firmware": "1.10", "display show": "y", " now ": "y", "can you hear": "y"}
    for lang in ("fr", "en"):
        monkeypatch.setenv("TRX_LANG", lang)

        async def scenario(q, fake, proxy, prompts, lang=lang):
            fake.freq, fake.mode, fake.passband = 7_074_000, "USB", 2400
            await q.run()
            reports[lang] = q.write_report(tmp_path / f"report-{lang}")
            outputs[lang] = q.journal + q.summary()
            assert 1 not in fake.ptt_commands and fake.ptt == 0          # jamais en émission (retour RX seulement)
        (tmp_path / lang).mkdir()
        qualif_run(tmp_path / lang, scenario, answers=answers, no_tx=True)
    shown = "\n".join(outputs["en"])
    assert "\n=== Phase 1: automatic tests (receive only, no transmission) ===" in shown
    assert "\n=== Phase 3: transmission NOT done (--sans-emission) ===" in shown
    assert "QUALIFICATION SUMMARY" in shown and "\nProposed verdict: INCOMPLETE" in shown
    assert "  - core not tested — PTT on then off, with read-back" in shown and "Frequency: write and read back" in shown
    assert "Phase 1 :" not in shown and "BILAN" not in shown
    french = "\n".join(outputs["fr"])
    # Sans émission : jamais les 6 points de l'émission (« antenne débranchée ») à confirmer (FTDX10, 2026-11-19)
    assert "QUALIFICATION WITHOUT TRANSMISSION" in shown and "No PTT command is sent" in shown
    assert "QUALIFICATION SANS ÉMISSION" in french and "DÉBRANCHÉE" not in french and "6 points" not in french
    assert "BILAN DE QUALIFICATION" in french and "\nVerdict proposé : INCOMPLET" in french

    def masked(text: str) -> str:
        return re.sub(r"\d+(\.\d+)?", "#", text)
    for name in ("plan.txt", "fiche.toml"):
        assert masked((reports["en"] / name).read_text(encoding="utf-8")) == \
               masked((reports["fr"] / name).read_text(encoding="utf-8")), name
    data = {}
    for lang in ("fr", "en"):
        report = json.loads((reports[lang] / "results.json").read_text(encoding="utf-8"))
        report.pop("date")
        report["tests"] = [t for t in report["tests"] if t["id"] not in HWTEST_IDS]
        text = json.dumps(report, ensure_ascii=False, sort_keys=True)
        data[lang] = masked(text.replace(json.dumps(str(tmp_path / lang))[1:-1], "DOSSIER"))
    assert data["en"] == data["fr"]
    assert "Fréquence : écriture et relecture" in data["en"] and "non fait : qualification sans émission" in data["en"]


def test_a_finding_written_to_a_document_never_carries_its_display_fields():
    finding = analyse_caps(parse_profile(REAL_472, 3094))[0]
    assert set(finding.to_dict()) == {"id", "severity", "source", "title", "detail", "title_en", "detail_en"}
    assert finding == coherence.Finding(finding.id, finding.severity, finding.source, finding.title, finding.detail,
                                        finding.title_en, finding.detail_en)
