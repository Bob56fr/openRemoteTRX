# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Valise de qualification v0 (`trx-qualif --terrain`) : observateur en LECTURE SEULE, mesures des essais, verdict,
rapport zip et empreintes, textes dans les quatre langues."""
from __future__ import annotations

import asyncio
import json
import time
import zipfile
from pathlib import Path

import pytest

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.i18n import FOLDER, LANGS
from trxstation.qualif import terrain
from trxstation.qualif.terrain import DRILLS, Drill, Observer, ObserverError, Session, analyse, judge


# --------------------------------------------------------------------------- observateur

def test_the_observer_only_sends_the_ptt_read():
    obs = Observer("127.0.0.1", 1)
    for command in ("T 1", "T 0", "F 7074000", "w FA;", "t\nT 1"):
        with pytest.raises(ObserverError):
            asyncio.run(obs._send(command))


def test_the_observer_refuses_a_rigctld_that_is_not_local():
    with pytest.raises(ObserverError):
        Observer("192.168.1.19", 4532)


def test_the_observer_sees_the_ptt_changes_and_never_writes():
    async def go():
        fake = FakeRigctld()
        await fake.start()
        sent = []
        obs = Observer("127.0.0.1", fake.port, period=0.02)
        original = obs._send

        async def spy(command):
            sent.append(command)
            return await original(command)
        obs._send = spy
        stop = asyncio.Event()
        task = asyncio.create_task(obs.run(stop))
        await asyncio.sleep(0.15)
        fake.ptt = 1
        await asyncio.sleep(0.15)
        fake.ptt = 0
        await asyncio.sleep(0.15)
        stop.set()
        await task
        await fake.stop()
        return obs, sent
    obs, sent = asyncio.run(go())
    assert set(sent) == {"t"}
    assert [v for _, v in obs.events] == [0, 1, 0]


def test_the_observer_survives_a_missing_rigctld():
    async def go():
        obs = Observer("127.0.0.1", 1, period=0.01, timeout=0.2)
        stop = asyncio.Event()
        task = asyncio.create_task(obs.run(stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task
        return obs
    obs = asyncio.run(go())
    assert obs.failures >= 1 and [v for _, v in obs.events] == [None]


# --------------------------------------------------------------------------- mesures

def test_delay_from_the_mark_and_duration():
    m = analyse([(10.0, 0), (11.0, 1), (15.3, 0)], start=10.0, end=20.0, mark=15.0)
    assert m["tx_seen"] and m["tx_duration_s"] == pytest.approx(4.3) and m["delay_from_mark_s"] == pytest.approx(0.3)


def test_a_drill_that_ends_in_transmission_always_fails():
    m = analyse([(10.0, 0), (11.0, 1)], start=10.0, end=20.0, mark=12.0)
    assert m["still_tx_at_end"]
    for d in DRILLS:
        assert judge(d, m, tot_s=90)[0] == "echec"


def test_stop_is_judged_against_its_bound():
    drill = Drill("x", "stop", bound_s=1.0)
    ok = analyse([(10.0, 0), (11.0, 1), (12.5, 0)], start=10.0, end=20.0, mark=12.0)
    late = analyse([(10.0, 0), (11.0, 1), (14.0, 0)], start=10.0, end=20.0, mark=12.0)
    assert judge(drill, ok, tot_s=90)[0] == "reussi"
    assert judge(drill, late, tot_s=90)[0] == "echec"
    nothing = analyse([(10.0, 0)], start=10.0, end=20.0, mark=12.0)
    assert judge(drill, nothing, tot_s=90)[0] == "non_mesure"


def test_tot_is_judged_on_the_duration():
    drill = next(d for d in DRILLS if d.kind == "tot")
    assert judge(drill, analyse([(0, 0), (1, 1), (91.0, 0)], 0, 100, None), tot_s=90)[0] == "reussi"
    assert judge(drill, analyse([(0, 0), (1, 1), (120.0, 0)], 0, 130, None), tot_s=90)[0] == "echec"


def test_any_transmission_fails_the_refusal_and_startup_drills():
    for kind in ("refusal", "startup"):
        d = Drill("x", kind)
        assert judge(d, analyse([(0, None), (1, 0), (2, 1), (3, 0)], 0, 10, None), tot_s=90)[0] == "echec"
        assert judge(d, analyse([(0, None), (1, 0)], 0, 10, None), tot_s=90)[0] == "reussi"


def test_already_transmitting_at_start_counts_as_transmission():
    m = analyse([(5.0, 1), (12.0, 0)], start=10.0, end=20.0, mark=11.5)
    assert m["tx_seen"] and m["tx_start"] == 10.0 and m["delay_from_mark_s"] == pytest.approx(0.5)


def test_the_declaration_never_turns_a_measured_failure_into_a_success():
    assert terrain.final_result("echec", True) == "echec"
    assert terrain.final_result("reussi", False) == "echec"
    assert terrain.final_result("reussi", None) == "incomplet"
    assert terrain.final_result("non_mesure", True) == "declare"


# --------------------------------------------------------------------------- un essai joué, rapport

def _session(tmp_path: Path) -> Session:
    return Session.open(tmp_path / "terrain-3094-x", model=3094, model_name="IC-7300", manufacturer="Icom",
                        hamlib_version="4.7.2", backend_status="Stable")


def test_a_drill_is_played_measured_and_saved(tmp_path):
    session = _session(tmp_path)
    state = tmp_path / "state"
    state.mkdir()

    async def go():
        fake = FakeRigctld()
        await fake.start()
        answers = iter(["", "", "", "o", "rien à signaler"])

        def ask(prompt):
            value = next(answers)
            if "EXACT" in prompt:
                time.sleep(0.15)      # l'observateur voit l'émission en cours
                fake.ptt = 0          # STOP : le poste revient en réception au repère
            return value
        fake.ptt = 1
        try:
            return await terrain.play_drill(DRILLS[0], session, host="127.0.0.1", port=fake.port, tot_s=90,
                                            state_dir=state, ask=ask, out=lambda s: None, period=0.02)
        finally:
            await fake.stop()
    record = asyncio.run(go())
    assert record["measured"] == "reussi" and record["result"] == "reussi"
    saved = json.loads((session.folder / "essais" / "stop_page.json").read_text(encoding="utf-8"))
    assert saved["observer"]["changes"][0][1] == 1
    assert Session.open(session.folder, model=0).drills["stop_page"]["result"] == "reussi"


def test_journal_lines_are_kept_in_the_window_and_masked(tmp_path):
    (tmp_path / "journal-passerelle.jsonl").write_text(
        '{"ts": "2026-11-18T10:00:01.000Z", "message": "client 192.168.1.42 connecté"}\n'
        '{"ts": "2026-11-18T11:00:00.000Z", "message": "hors fenêtre"}\n', encoding="utf-8")
    start = terrain._parse_ts("2026-11-18T10:00:00Z")
    lines = terrain.journal_lines(tmp_path, start, start + 60, terrain._redactor())
    assert len(lines) == 1 and "192.168.1.42" not in lines[0]["message"]


def test_verdict_is_refuse_on_a_failed_drill_and_incomplete_when_drills_are_missing(tmp_path):
    session = _session(tmp_path)
    assert terrain.verdict(session)[0] == "incomplet"
    session.runs = [{"kind": "qualif", "folder": "qualif-x", "verdict": "validation_en_cours"}]
    for d in DRILLS:
        if not d.optional:
            session.drills[d.id] = {"result": "reussi"}
    assert terrain.verdict(session) == ("validation_en_cours", [])
    session.drills["tot"] = {"result": "echec"}
    assert terrain.verdict(session)[0] == "refuse"


def test_the_report_zip_has_its_files_and_valid_fingerprints(tmp_path):
    session = _session(tmp_path)
    q = session.folder / "qualif-3094-1"
    q.mkdir()
    (q / "results.json").write_text('{"verdict": {"statut": "validation_en_cours", "raisons": []}}', encoding="utf-8")
    target = terrain.build_report(session, settings={"hamlib_model": 3094}, out_dir=tmp_path)
    names = zipfile.ZipFile(target).namelist()
    root = session.folder.name
    for f in ("qualification.json", "rapport.html", "LISEZMOI-CLAUDE.md", "empreintes.sha256", "qualif-3094-1/results.json"):
        assert f"{root}/{f}" in names
    assert terrain.check_report(target) == []
    data = json.loads(zipfile.ZipFile(target).read(f"{root}/qualification.json"))
    assert data["format"] == 1 and data["signature"] is None and data["runs"][0]["verdict"] == "validation_en_cours"
    # zip retouché : l'empreinte le voit
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(target) as src, zipfile.ZipFile(bad, "w") as dst:
        for n in src.namelist():
            dst.writestr(n, b"x" if n.endswith("rapport.html") else src.read(n))
    assert terrain.check_report(bad) == ["rapport.html"]


def _menu(tmp_path, answers, *, running=False, snapshots=None):
    from types import SimpleNamespace
    from trxstation.setup_wizard import dummy_config
    calls = []
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path)
    profile = SimpleNamespace(model=3094, hamlib_version="4.7.2", backend_status="Stable",
                              caps=SimpleNamespace(model_name="IC-7300", manufacturer="Icom"))
    it = iter(answers)
    shown = []
    snaps = iter(snapshots or [])
    code = terrain.run_terrain(cfg, profile, "", tmp_path, session_dir=tmp_path / "s", ask=lambda p: next(it),
                               out=shown.append, explore=lambda: calls.append("explore"),
                               qualify=lambda no_tx: calls.append(("qualif", no_tx)), station=lambda: running,
                               control=lambda start: calls.append(("station", start)) or 0,
                               snapshot=lambda: next(snaps))
    return code, calls, "\n".join(map(str, shown))


def test_the_menu_runs_the_existing_tools_and_quits(tmp_path):
    code, calls, _ = _menu(tmp_path, ["2", "c", "CHARGE", "3", "4", "a", "d", "q"])
    assert code == 0
    assert calls == ["explore", ("qualif", False), ("qualif", True), ("station", False), ("station", True)]
    assert (tmp_path / "s" / "photos" / "avant").is_dir() and (tmp_path / "s" / "photos" / "apres").is_dir()


def test_the_tools_that_start_their_own_rigctld_are_refused_while_the_station_runs(tmp_path):
    code, calls, shown = _menu(tmp_path, ["1", "2", "3", "4", "6", "q"], running=True)
    assert calls == [] and shown.count("arrête-la d'abord") == 5


def test_before_and_after_snapshots_list_what_to_restore_by_hand(tmp_path):
    before = {"f": "Frequency=7074000", "l AF": "0.5", "u NB": "1", "t": "0"}
    after = {"f": "Frequency=7074000", "l AF": "0.3", "u NB": "1", "t": "0"}
    code, _, shown = _menu(tmp_path, ["1", "6", "7", "q"], snapshots=[before, after])
    assert "À REMETTRE À LA MAIN" in shown and "l AF" in shown
    data = json.loads((tmp_path / "s" / "qualification.json").read_text(encoding="utf-8"))
    assert data["remise_en_etat"] == {"compare": True, "differences": [{"lecture": "l AF", "avant": "0.5", "apres": "0.3"}]}
    assert set(data["releves"]) == {"avant", "apres"}


def test_a_report_without_snapshots_says_the_restoration_was_not_checked(tmp_path):
    _menu(tmp_path, ["7", "q"])
    data = json.loads((tmp_path / "s" / "qualification.json").read_text(encoding="utf-8"))
    assert data["remise_en_etat"]["compare"] is False
    assert "NON vérifiée" in (tmp_path / "s" / "rapport.html").read_text(encoding="utf-8")


def test_a_failed_snapshot_is_said_and_never_fatal(tmp_path):
    def boom():
        raise OSError("rigctld absent")
    from types import SimpleNamespace
    session = _session(tmp_path)
    shown = []
    terrain.take_snapshot(session, "avant", boom, out=shown.append)
    assert "rigctld absent" in shown[-1] and "avant" not in session.snapshots


def test_the_snapshot_never_sends_a_write():
    class Spy:
        sent = []

        async def _command(self, line):
            self.sent.append(line)
            return {"#1": "0"}
    rig = terrain.ReadOnlyRig(Spy())
    for line in ("F 7074000", "M USB 0", "T 1", "U NB 1", "L AF 0.5", "P BACKLIGHT 1", "w FA;", "f\nT 1"):
        with pytest.raises(ObserverError):
            asyncio.run(rig.read(line))
    assert Spy.sent == []


def test_the_snapshot_reads_settings_but_not_meters_on_a_fake_rig():
    from types import SimpleNamespace
    from trxstation.gateway.cat.client import RigctldClient
    profile = SimpleNamespace(get_functions=("NB", "SEND_MORSE"), get_levels=("AF", "STRENGTH"),
                              get_params=("BEEP", "TIME"))

    async def go():
        fake = FakeRigctld()
        await fake.start()
        client = RigctldClient("127.0.0.1", fake.port, timeout=1.0)
        await client.connect()
        try:
            state = {}
            assert await terrain.read_state(terrain.ReadOnlyRig(client), terrain.state_lines(profile), state) is None
            return state
        finally:
            await client.close()
            await fake.stop()
    state = asyncio.run(go())
    assert "f" in state and "u NB" in state and "l AF" in state
    assert "l STRENGTH" not in state and "u SEND_MORSE" not in state and "p TIME" not in state   # mesures, horloge


def test_a_read_that_crashes_rigctld_is_noted_and_never_compared(tmp_path):
    from trxstation.gateway.cat.client import CatConnectionError

    class Crashy:
        async def _command(self, line):
            if line == "p KEYERTYPE":          # vu sur l'IC-7300MK2, Hamlib 4.7.2 sous Windows
                raise CatConnectionError("liaison rigctld perdue")
            return {"#1": "1"}
    state = {}
    lines = ["f", "p KEYERTYPE", "p AFIF"]
    assert asyncio.run(terrain.read_state(terrain.ReadOnlyRig(Crashy()), lines, state)) == "p KEYERTYPE"
    assert state == {"f": "1", "p KEYERTYPE": terrain.CRASHED}           # la suite sera lue après la relance
    session = _session(tmp_path)
    shown = []
    terrain.take_snapshot(session, "avant", lambda: dict(state), out=shown.append)
    assert session.crashers == ["p KEYERTYPE"] and any("KEYERTYPE" in line for line in shown)
    after = {"f": "1", "p KEYERTYPE": terrain.SKIPPED}
    assert terrain.differences(state, after) == []


def test_the_snapshot_restarts_rigctld_after_a_crash_and_reads_the_rest(monkeypatch):
    import contextlib
    from types import SimpleNamespace
    from trxstation.gateway.cat import client as catclient
    from trxstation.qualif import main as qmain
    sessions = []

    @contextlib.asynccontextmanager
    async def fake_session(cfg, *, spawn, out=print):
        assert spawn is True                        # toujours son propre rigctld (station arrêtée)
        sessions.append(1)
        yield "127.0.0.1", 1

    class Client:
        def __init__(self, *a, **k):
            pass

        async def connect(self):
            pass

        async def close(self):
            pass

        async def _command(self, line):
            if line == "p KEYERTYPE":
                raise catclient.CatConnectionError("tombé")
            return {"#1": "0"}
    monkeypatch.setattr(qmain, "rigctld_session", fake_session)
    monkeypatch.setattr(catclient, "RigctldClient", Client)
    monkeypatch.setattr(terrain, "RESTART_PAUSE_S", 0)
    profile = SimpleNamespace(get_functions=(), get_levels=(), get_params=("KEYERTYPE", "AFIF"))
    state = asyncio.run(terrain.snapshot_session(None, profile, out=lambda s: None))
    assert len(sessions) == 2 and state["p KEYERTYPE"] == terrain.CRASHED and state["p AFIF"] == "0"
    sessions.clear()
    state = asyncio.run(terrain.snapshot_session(None, profile, out=lambda s: None, skip=("p KEYERTYPE",)))
    assert len(sessions) == 1 and state["p KEYERTYPE"] == terrain.SKIPPED


# --------------------------------------------------------------------------- textes

def test_every_drill_text_exists_in_the_four_languages():
    keys = {f"terrain.drill.{d.id}.{p}" for d in DRILLS for p in ("title", "how", "expected")}
    keys |= {f"terrain.result.{r}" for r in ("reussi", "echec", "non_mesure", "declare", "incomplet")}
    for lang in LANGS:
        cat = json.loads((FOLDER / f"qualif.{lang}.json").read_text(encoding="utf-8"))
        assert keys <= set(cat), (lang, sorted(keys - set(cat)))


def test_terrain_refuses_the_other_modes(capsys):
    from trxstation.qualif import main as qmain
    assert qmain.main(["--terrain", "--explorer"]) == qmain.EXIT_CONFIG


def test_what_the_kit_prints_fits_a_windows_console(tmp_path):
    """Sortie redirigée sous Windows (console web, journal) = page de code 1252 : un « ✓ » y faisait PLANTER la valise
    sur le vrai poste (étape 254)."""
    for lang in LANGS:
        cat = json.loads((FOLDER / f"qualif.{lang}.json").read_text(encoding="utf-8"))
        for key, text in cat.items():
            if key.startswith("terrain.") or key == "explore.rigctld_crash":
                text.encode("cp1252")
    _, _, shown = _menu(tmp_path, ["7", "q"])
    shown.encode("cp1252")


def test_a_refused_q1_qualification_refuses_the_rig(tmp_path):
    """Format RÉEL de results.json (vu sur l'IC-7300MK2, étape 256) : `verdict` = {statut, raisons}."""
    session = _session(tmp_path)
    q = session.folder / "qualif-3094-2"
    q.mkdir()
    (q / "results.json").write_text('{"verdict": {"statut": "refuse", "raisons": ["socle en échec"]}}',
                                    encoding="utf-8")
    terrain.note_runs(session)
    assert session.runs[-1]["verdict"] == "refuse"
    assert terrain.verdict(session) == ("refuse", ["qualification Q1 : refus"])


# --------------------------------------------------------------------------- carte son du poste (étape 258)

class FakeSd:
    """Bibliothèque audio factice : deux cartes du poste (nom Windows numéroté), niveau reçu réglable."""

    def __init__(self, *, signal=0.01, fail_play=False):
        import numpy as np
        self.np, self.signal, self.fail_play, self.played = np, signal, fail_play, []

    def query_hostapis(self):
        return [{"name": "Windows WASAPI"}]

    def query_devices(self):
        return [{"name": "Microphone (2- USB Audio Device)", "max_input_channels": 1, "max_output_channels": 0,
                 "hostapi": 0},
                {"name": "Haut-parleurs (2- USB Audio Device)", "max_input_channels": 0, "max_output_channels": 2,
                 "hostapi": 0}]

    def rec(self, frames, samplerate, channels, dtype, device):
        return (self.np.ones((frames, 1)) * self.signal * 32767).astype("int16")

    def play(self, data, samplerate, device):
        if self.fail_play:
            raise RuntimeError("Error starting stream")
        self.played.append(float(abs(data).max()))

    def wait(self):
        pass


def _audio_cfg(capture="Microphone (2- USB Audio Device)", playback="Haut-parleurs (2- USB Audio Device)"):
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.audio.capture_device, cfg.audio.playback_device = capture, playback
    return cfg


def test_the_rig_sound_card_check_passes_and_writes_only_silence():
    sd = FakeSd()
    result = terrain.audio_check(_audio_cfg(), sd=sd, seconds=0.1, windows=True)
    assert result["problems"] == [] and result["capture"]["level_dbfs"] == pytest.approx(-40.0, abs=0.5)
    assert sd.played == [0.0]                                    # jamais un son vers le poste
    assert {a["key"] for a in result["advice"]} == {"windows_numbered", "windows_volume"}


def test_an_empty_sound_card_name_is_a_problem_not_a_silent_success():
    result = terrain.audio_check(_audio_cfg(capture="", playback=""), sd=FakeSd(), seconds=0.1, windows=False)
    assert [p["key"] for p in result["problems"]] == ["no_capture", "no_playback"] and result["advice"] == []


def test_digital_silence_missing_card_and_refused_output_are_problems():
    keys = lambda r: [p["key"] for p in r["problems"]]       # noqa: E731
    assert keys(terrain.audio_check(_audio_cfg(), sd=FakeSd(signal=0), seconds=0.1)) == ["digital_silence"]
    assert keys(terrain.audio_check(_audio_cfg(capture="Autre carte"), sd=FakeSd(), seconds=0.1)) == ["not_found"]
    assert keys(terrain.audio_check(_audio_cfg(), sd=FakeSd(fail_play=True), seconds=0.1)) == ["open_failed"]


def test_the_check_is_shown_saved_and_reported(tmp_path):
    ok = {"capture": {"name": "m", "level_dbfs": -40.0, "zeros_pct": 1.0}, "playback": {"name": "h", "opened": True},
          "problems": [], "advice": []}
    from trxstation.setup_wizard import dummy_config
    from types import SimpleNamespace
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path)
    profile = SimpleNamespace(model=3094, hamlib_version="4.7.2", backend_status="Stable",
                              caps=SimpleNamespace(model_name="IC-7300", manufacturer="Icom"))
    answers, shown = iter(["9", "7", "q"]), []
    terrain.run_terrain(cfg, profile, "", tmp_path, session_dir=tmp_path / "s", ask=lambda p: next(answers),
                        out=shown.append, station=lambda: False, sound=lambda: ok)
    assert any("Carte son du poste : OK" in str(line) for line in shown)
    data = json.loads((tmp_path / "s" / "qualification.json").read_text(encoding="utf-8"))
    assert data["carte_son"]["capture"]["level_dbfs"] == -40.0
    assert "9 [x]" in "\n".join(map(str, shown))


def test_the_sound_check_is_refused_while_the_station_runs(tmp_path):
    _, _, shown = _menu(tmp_path, ["9", "q"], running=True)
    assert "arrête-la d'abord" in shown


# --------------------------------------------------------------------------- leçons du passage B de l'IC-705 (étape 261)

def test_a_drill_is_not_started_when_the_ptt_cannot_be_read(tmp_path):
    """Station d'essai arrêtée : l'essai n'est ni joué ni enregistré (vu : « stop_page » joué sans station)."""
    session = _session(tmp_path)
    shown, asked = [], []
    record = asyncio.run(terrain.play_drill(DRILLS[0], session, host="127.0.0.1", port=1, tot_s=90, state_dir=tmp_path,
                                            ask=lambda p: asked.append(p) or "", out=shown.append, period=0.01))
    assert record == {} and "stop_page" not in session.drills
    assert any("ILLISIBLE" in s for s in shown) and not any("EXACT" in p for p in asked)


def test_relaunching_the_kit_offers_to_resume_today_s_session(tmp_path):
    first = _menu(tmp_path, ["q"])                            # crée tmp_path/s via session_dir : pas une session du jour
    today = tmp_path / "out"
    folder = terrain._resume_or_new(today, 3085, ask=lambda p: "", out=lambda s: None)
    Session.open(folder, model=3085)
    again = terrain._resume_or_new(today, 3085, ask=lambda p: "", out=lambda s: None)
    assert again == folder                                    # Entrée = reprendre
    assert terrain._resume_or_new(today, 3085, ask=lambda p: "n", out=lambda s: None).name.startswith("terrain-3085-")



# --------------------------------------------------------------------------- parties antenne / charge, T3 (étape 263)

def test_no_transmitting_part_without_the_dummy_load_confirmed(tmp_path):
    code, calls, shown = _menu(tmp_path, ["3", "8", "5", "c", "charge?", "3", "q"])
    assert calls == [] and shown.count("CHARGE FICTIVE (choix c)") == 4     # 3 refus, puis mot faux, puis refus


def test_the_antenna_part_locks_transmissions_again_until_charge(tmp_path):
    rx = {"freq_hz": 7_100_000, "mode": "LSB", "level_dbfs": -40.0, "zeros_pct": 0.0, "s_metre_db": -20,
          "verdict": "ok", "problems": []}
    from trxstation.setup_wizard import dummy_config
    from types import SimpleNamespace
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path)
    profile = SimpleNamespace(model=3094, hamlib_version="4.7.2", backend_status="Stable",
                              caps=SimpleNamespace(model_name="IC-7300", manufacturer="Icom"))
    calls, shown = [], []
    answers = iter(["c", "CHARGE", "r", "", "3", "c", "CHARGE", "3", "7", "q"])
    terrain.run_terrain(cfg, profile, "", tmp_path, session_dir=tmp_path / "s", ask=lambda p: next(answers),
                        out=shown.append, station=lambda: False, qualify=lambda no_tx: calls.append(no_tx),
                        receive=lambda: rx, explore=lambda: None)
    assert calls == [False]                                   # une seule qualification : après le second « CHARGE »
    text = "\n".join(map(str, shown))
    assert "ACTION DEMANDÉE : branche l'ANTENNE" in text and "7.100 MHz LSB" in text and ": OK." in text
    data = json.loads((tmp_path / "s" / "qualification.json").read_text(encoding="utf-8"))
    assert data["reception_antenne"]["verdict"] == "ok"


@pytest.mark.parametrize("level,zeros,verdict", [(-40, 0, "ok"), (-80, 2, "faible"), (-3, 0, "sature"),
                                                 (-120, 100, "silence"), (None, None, "silence")])
def test_reception_on_the_antenna_is_judged(level, zeros, verdict):
    assert terrain.judge_reception(level, zeros) == verdict


def test_spectrum_check_reads_the_scope_tool_summary(tmp_path):
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.rig.model, cfg.rig.port = 3085, "COM11"

    def fake_run(cmd):
        out = Path(cmd[cmd.index("--sortie") + 1])
        out.mkdir(parents=True)
        (out / "resume.txt").write_text("Port COM11, 115200 bauds, adresse du poste A4h\n"
                                        "Durée 8.0 s ; trames du spectre 40 ; balayages complets 12 (1.5/s)", encoding="utf-8")
        assert "civ_scope" in " ".join(cmd) and "COM11" in cmd
        return SimpleNamespace(stdout="")
    from types import SimpleNamespace
    result = terrain.spectrum_check(cfg, tmp_path, run=fake_run)
    assert result["verdict"] == "ok" and result["sweeps"] == 12 and result["which"] == "port CAT"
    cfg.rig.model = 1042                                      # Yaesu : rien d'envoyé
    assert terrain.spectrum_check(cfg, tmp_path, run=lambda c: 1 / 0)["verdict"] == "non_propose"
