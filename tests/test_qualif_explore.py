# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Exploration d'un poste jamais essayé (`trx-qualif --explorer`) et incohérences de dump_caps.

Références RÉELLES : `rigctl -m 3094 -u` de l'IC-7300MK2 avec Hamlib 4.7.2 et 5.0.0~git (relevés sur la station
minix-bzh le 2026-11-13). L'exploration ne doit JAMAIS commander le PTT ni changer le mode, n'écrit que sa liste
fermée, s'arrête net si le poste émet, et rétablit la fréquence d'origine.
"""
import asyncio
import json
import re
from pathlib import Path

import pytest

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.cat import RigctldClient
from trxstation.qualif import coherence, explore
from trxstation.qualif import main as qmain
from trxstation.qualif.coherence import ATTENTION, BLOQUANT, analyse_caps
from trxstation.qualif.explore import EXPLORE_WRITE_FUNCS, EXPLORE_WRITE_LEVELS, Exploration
from trxstation.qualif.explore_report import write_report
from trxstation.qualif.plan import build_plan
from trxstation.qualif.profile import parse_profile
from trxstation.qualif.trace import TraceProxy
from trxstation.setup_wizard import dummy_config

DATA = Path(__file__).parent / "data"
REAL_472 = (DATA / "dump_caps_ic7300mk2_hamlib472.txt").read_text(encoding="utf-8")
REAL_50 = (DATA / "dump_caps_ic7300mk2_hamlib50.txt").read_text(encoding="utf-8")
# Réglages dont l'écriture peut provoquer une émission, gêner la station ou surprendre l'opérateur : jamais écrits.
DANGEROUS = {"VOX", "VOXGAIN", "VOXDELAY", "ANTIVOX", "TUNER", "SEND_MORSE", "SEND_VOICE_MEM", "SBKIN", "FBKIN",
             "TRANSCEIVE", "MICGAIN", "RFPOWER", "AF", "LOCK", "SCOPE", "MON"}


def ids(findings):
    return {f.id for f in findings}


# --------------------------------------------------------------------------- dump_caps réel

def test_real_dumps_give_ranges_ptt_type_and_parameters():
    p472, p50 = parse_profile(REAL_472, 3094), parse_profile(REAL_50, 3094)
    assert p472.ptt_declared == "None" and p50.ptt_declared == "Rig capable"     # change selon la version de Hamlib
    for p in (p472, p50):
        assert [(r.low_hz, r.high_hz) for r in p.rx_ranges] == [(30_000, 74_800_000)]
        assert len(p.tx_ranges) == 24 and p.tx_ranges[0].low_hz == 1_810_000 and p.tx_ranges[0].high_w == 100.0
        assert p.tx_ranges[-1].modes == ("AM", "AM-D") and p.tx_ranges[-1].high_w == 12.5
        assert "PKTUSB" not in p.tx_ranges[0].modes                                # déclaration TX incomplète
        assert p.get_params[:3] == ("ANN", "BACKLIGHT", "BEEP") and "KEYERTYPE" in p.set_params
        assert p.async_data is True and p.backend_warnings == 0 and "Transceiver" in p.rig_type
        assert p.get_level_ranges["STRENGTH"].high == 60 and p.get_level_ranges["SWR"].high == 5
        json.dumps(p.to_dict())                                                    # sérialisable pour le rapport


def test_known_inconsistencies_of_the_ic7300mk2_are_found_without_touching_the_rig():
    found = analyse_caps(parse_profile(REAL_472, 3094))
    assert {"backend_status", "ptt_type_none", "list_vs_range_PREAMP", "list_vs_range_ATT", "agc_range_empty",
            "ranges_empty", "tx_ranges_data_modes", "vfo_unreadable", "async_data"} <= ids(found)
    assert not any(f.severity == BLOQUANT for f in found)
    assert all(f.title_en for f in found if f.source == coherence.HAMLIB and f.severity == ATTENTION)
    assert "ptt_type_none" not in ids(analyse_caps(parse_profile(REAL_50, 3094)))


def test_a_rig_without_ptt_readback_is_blocking():
    text = REAL_50.replace("Can get PTT:\tY", "Can get PTT:\tN")
    found = [f for f in analyse_caps(parse_profile(text, 3094)) if f.severity == BLOQUANT]
    assert [f.id for f in found] == ["cannot_get_ptt"]


def test_plan_labels_a_level_that_shares_its_name_with_a_function():
    labels = [i.label for i in build_plan(parse_profile(REAL_50, 3094)).items]
    assert len(labels) == len(set(labels))                                         # plus de doublon NR / NB
    assert "Lecture : réducteur de bruit (NR), niveau" in labels


# --------------------------------------------------------------------------- sécurité de la liste fermée

def test_the_closed_write_list_never_contains_anything_that_can_transmit():
    assert not (set(EXPLORE_WRITE_FUNCS) | set(EXPLORE_WRITE_LEVELS)) & DANGEROUS
    assert not any(n.startswith(("SPECTRUM", "SEND_")) for n in EXPLORE_WRITE_FUNCS + EXPLORE_WRITE_LEVELS)


def test_the_explorer_code_has_no_ptt_command():
    """Analyse du CODE (pas des commentaires) : aucun appel write_ptt / set_ptt, aucune chaîne qui commence par « T »."""
    import ast
    tree = ast.parse(Path(explore.__file__).read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"write_ptt", "set_ptt", "set_ptt_raw"}
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in strings if re.match(r"\\?(T\b|set_ptt)", s)]            # ni « T 1 », ni « \set_ptt »


# --------------------------------------------------------------------------- exploration sur le faux poste

def explore_run(scenario, *, profile_text=REAL_50, setup=None, **kwargs):
    async def wrapper():
        fake = FakeRigctld()
        fake.freq, fake.mode, fake.passband = 7_074_000, "PKTUSB", 3000
        for name in ("TONE", "TSQL"):
            fake.funcs[name] = 0
        fake.levels.update({"PBT_IN": 0.5, "CWPITCH": 600.0, "KEYSPD": 20.0})
        fake.writable_levels |= {"PBT_IN", "CWPITCH", "KEYSPD"}
        if setup:
            setup(fake)
        await fake.start()
        client = RigctldClient("127.0.0.1", fake.port, timeout=1.0)
        await client.connect()
        out = []
        params = dict(burst=40, settle_s=0.3, reconnects=2)
        params.update(kwargs)
        ex = Exploration(client, parse_profile(profile_text, 3094), out=out.append, **params)
        try:
            await asyncio.wait_for(scenario(ex, fake, out), 60)
        finally:
            await client.close()
            await fake.stop()
    asyncio.run(wrapper())


def sent(fake, letter):
    return [c.lstrip("+") for c in fake.commands if c.lstrip("+").split(" ")[0] == letter]


def test_exploration_reads_everything_writes_only_its_list_and_restores_the_rig():
    async def scenario(ex, fake, out):
        result = await ex.run()
        assert result.stopped == "" and result.restored is True
        assert fake.ptt_set_calls == 0 and sent(fake, "M") == []                    # ni PTT ni mode, jamais
        assert (fake.freq, fake.mode, fake.passband) == (7_074_000, "PKTUSB", 3000)
        written = {c.split()[1] for c in sent(fake, "U") + sent(fake, "L")}
        assert written and written <= set(EXPLORE_WRITE_FUNCS) | set(EXPLORE_WRITE_LEVELS)
        assert fake.funcs["TONE"] == 0 and fake.levels["CWPITCH"] == 600 and abs(fake.levels["PBT_IN"] - 0.5) < 1e-6
        probes = {p.id: p for p in result.probes}
        assert probes["write_func_TONE"].ok and probes["write_level_CWPITCH"].ok and probes["write_level_PBT_IN"].ok
        assert probes["read_func_SEND_MORSE"].ok is None                            # fonction d'action : pas lue
        assert probes["coverage_bas"].ok and probes["coverage_haut"].ok
        assert probes["burst"].ok and probes["reconnect"].ok and probes["sync_after_error"].ok
        assert sent(fake, "F")[-1] == "F 7074000"                                   # fréquence d'origine en dernier
        assert {"reads_refused", "coverage_wider_75800000"} <= ids(result.findings)   # le faux poste accepte tout
    explore_run(scenario)


def test_a_rig_already_transmitting_stops_everything_before_any_write():
    async def scenario(ex, fake, out):
        result = await ex.run()
        assert "émission" in result.stopped and result.restored is None
        assert sent(fake, "F") == sent(fake, "U") == sent(fake, "L") == [] and fake.ptt_set_calls == 0
        assert fake.ptt == 1                                                        # l'exploration ne coupe pas : elle ne touche à rien
        assert any(f.id == "stopped_tx" and f.severity == BLOQUANT for f in result.findings)
    explore_run(scenario, setup=lambda fake: setattr(fake, "ptt", 1))


def test_a_local_transmission_during_the_exploration_stops_it_without_restoring():
    def setup(fake):
        original = fake._reply

        def reply(line):
            if len(fake.commands) > 60:          # l'opérateur prend le micro du poste en cours de route
                fake.ptt = 1
            return original(line)
        fake._reply = reply

    async def scenario(ex, fake, out):
        result = await ex.run()
        assert result.stopped and fake.ptt_set_calls == 0
        keyed_at = next(i for i, c in enumerate(fake.commands) if i > 60)
        after = [c.lstrip("+").split(" ")[0] for c in fake.commands[keyed_at:]]
        assert not set(after) & {"F", "U", "L", "M"}                                 # plus rien d'écrit une fois en émission
    explore_run(scenario, setup=setup)


def test_unreadable_ptt_stops_the_exploration():
    async def scenario(ex, fake, out):
        result = await ex.run()
        assert "illisible" in result.stopped and sent(fake, "F") == []
    explore_run(scenario, setup=lambda fake: fake.errors.update({"t": -5}))


def test_read_only_mode_changes_nothing():
    async def scenario(ex, fake, out):
        result = await ex.run()
        assert result.stopped == ""
        assert sent(fake, "U") == sent(fake, "L") == sent(fake, "M") == []
        assert all(c == "F 7074000" for c in sent(fake, "F"))                       # seulement la remise en état
    explore_run(scenario, writes=False)


def test_an_out_of_range_frequency_accepted_silently_is_reported():
    def setup(fake):
        original = fake._reply

        def reply(line):
            parts = line.lstrip("+").split()
            if parts[:1] == ["F"] and int(parts[1]) > 74_800_000:
                return "set_freq:\nRPRT 0\n"                                    # « OK » mais rien n'est appliqué
            return original(line)
        fake._reply = reply

    async def scenario(ex, fake, out):
        result = await ex.run()
        assert "coverage_silent_75800000" in ids(result.findings)
        assert fake.freq == 7_074_000
    explore_run(scenario, setup=setup)


def test_settings_that_the_rig_rounds_or_ignores_are_told_apart():
    def setup(fake):
        original = fake._reply

        def reply(line):
            parts = line.lstrip("+").split()
            if parts[:2] == ["L", "PBT_IN"]:
                return original(f"+L PBT_IN {round(float(parts[2]) * 11) / 11}")   # pas réel : 1/11
            if parts[:2] == ["U", "TSQL"]:
                return "set_func: TSQL\nRPRT 0\n"                                    # accepté, ignoré
            return original(line)
        fake._reply = reply

    async def scenario(ex, fake, out):
        result = await ex.run()
        probes = {p.id: p for p in result.probes}
        assert probes["write_level_PBT_IN"].ok and "arrondi" in probes["write_level_PBT_IN"].detail
        assert probes["write_func_TSQL"].ok is False
        assert {"writes_rounded", "writes_not_followed"} <= ids(result.findings)
    explore_run(scenario, setup=setup)


def test_replies_from_the_rigctld_cache_are_reported_and_a_slow_rig_is_not():
    async def fast(ex, fake, out):
        result = await ex.run()
        cache = next(f for f in result.findings if f.id == "rigctld_cache")
        assert "PTT" in cache.title and cache.severity == ATTENTION

    async def slow(ex, fake, out):
        fake.delay_s = 0.003
        result = await ex.run()
        assert "rigctld_cache" not in ids(result.findings)
    explore_run(fast, reconnects=0)
    explore_run(slow, burst=20, reconnects=0)


# --------------------------------------------------------------------------- rapport

def test_report_files_and_hamlib_draft_in_english(tmp_path):
    async def scenario(ex, fake, out):
        result = await ex.run()
        profile = ex.profile
        directory = write_report(tmp_path / "explore", profile, result, dump_text=REAL_50, journal=out, firmware="1.10")
        names = {p.name for p in directory.iterdir()}
        assert {"exploration.json", "constats.txt", "fiche-poste.md", "rapport-hamlib.md", "dump_caps.txt", "journal.txt"} <= names
        data = json.loads((directory / "exploration.json").read_text(encoding="utf-8"))
        assert data["poste"]["firmware"] == "1.10" and data["etat_retabli"] is True and data["sondes"]
        sheet = (directory / "fiche-poste.md").read_text(encoding="utf-8")
        assert "BROUILLON" in sheet and "ÉMISSION" in sheet and "| `rafale f` |" in sheet
        hamlib = (directory / "rapport-hamlib.md").read_text(encoding="utf-8")
        assert hamlib.startswith("# Icom IC-7300MK2 (model 3094)") and "Nothing was transmitted" in hamlib
        everything = "".join(p.read_text(encoding="utf-8") for p in directory.iterdir() if p.suffix in (".md", ".json", ".txt"))
        assert "/dev/" not in everything and not re.search(r"\bCOM\d", everything)          # ni port série ni port COM
    explore_run(scenario)


# --------------------------------------------------------------------------- ligne de commande

def test_plan_for_a_model_without_station_toml(monkeypatch, capsys):
    monkeypatch.setattr(qmain, "_run_dump_caps", lambda model, hamlib_dir: REAL_50)
    assert qmain.main(["--plan", "--modele", "3094"]) == qmain.EXIT_OK
    text = capsys.readouterr().out
    assert "Cahier de test" in text and "Incohérences de dump_caps" in text and "Préamplis" in text


@pytest.mark.parametrize("argv", [["--modele", "3094"], ["--explorer", "--sans-emission"], ["--explorer", "--filtres"],
                                  ["--lecture-seule"], ["--plan", "--modele", "0"]])
def test_inconsistent_options_are_refused(argv, monkeypatch):
    monkeypatch.setattr(qmain, "_run_dump_caps", lambda model, hamlib_dir: REAL_50)
    assert qmain.main(argv) == qmain.EXIT_CONFIG


def test_a_rigctld_already_answering_is_refused_unless_no_spawn():
    async def scenario():
        fake = FakeRigctld()
        await fake.start()
        cfg = dummy_config()
        cfg.network.rigctld_port = fake.port
        try:
            with pytest.raises(qmain.RigctldUnavailable, match="station tourne"):
                async with qmain.rigctld_session(cfg, spawn=True, out=lambda s: None):
                    pass
            async with qmain.rigctld_session(cfg, spawn=False, out=lambda s: None) as (host, port):
                assert port == fake.port
        finally:
            await fake.stop()
    asyncio.run(scenario())


def test_full_explorer_command_against_the_fake_rig(tmp_path, monkeypatch):
    async def scenario():
        fake = FakeRigctld()
        await fake.start()
        cfg = dummy_config()
        cfg.network.rigctld_port = fake.port
        answers = iter(["OUI", ""])
        out = []
        try:
            code = await qmain.run_explore(cfg, parse_profile(REAL_50, 3094), REAL_50, tmp_path, spawn=False,
                                           ask=lambda prompt: next(answers), out=out.append, burst=20, settle_s=0.3)
        finally:
            await fake.stop()
        assert code == qmain.EXIT_OK and fake.ptt_set_calls == 0
        directory = next(tmp_path.glob("explore-3094-*"))
        assert "CONSTATS" in "\n".join(out) and (directory / "cat_trace.log").exists()
    asyncio.run(scenario())


def test_explorer_is_cancelled_without_oui(tmp_path):
    async def scenario():
        cfg = dummy_config()
        code = await qmain.run_explore(cfg, parse_profile(REAL_50, 3094), REAL_50, tmp_path, spawn=False,
                                       ask=lambda prompt: "non", out=lambda s: None)
        assert code == qmain.EXIT_INCOMPLETE and not any(tmp_path.iterdir())
    asyncio.run(scenario())


def test_trace_proxy_is_still_used_by_the_explorer():
    assert "TraceProxy" in Path(qmain.__file__).read_text(encoding="utf-8") and TraceProxy
