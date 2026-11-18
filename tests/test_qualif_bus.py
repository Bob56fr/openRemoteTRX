# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Bus d'événements de la valise (lot G1) : questions typées, mots de sécurité réservés à un humain au clavier,
historique `evenements.jsonl`, terminal = simple client."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from trxstation.qualif import bus as qbus
from trxstation.qualif import terrain
from trxstation.qualif.bus import (DONE, SOURCE_KEYBOARD, SOURCE_PILOT, TEXT, WORD, YES_NO, Bus, KeyboardClient,
                                   RefusedAnswer, ask_typed, ask_word)


def _journal(folder):
    return [json.loads(line) for line in (folder / qbus.JOURNAL).read_text(encoding="utf-8").splitlines()]


def _wait_question(bus, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if bus.open_questions():
            return bus.open_questions()[0]
        time.sleep(0.005)
    raise AssertionError("aucune question posée")


def test_the_keyboard_client_answers_and_shows_lines_like_the_terminal(tmp_path):
    shown, prompts = [], []
    bus = Bus()
    KeyboardClient(bus, ask=lambda p: prompts.append(p) or "bonjour", out=shown.append)
    bus.attach(tmp_path)
    bus.out("ligne 1")
    assert bus.ask("Question ? ") == "bonjour"
    assert shown == ["ligne 1"] and prompts == ["Question ? "]
    types = [e["type"] for e in _journal(tmp_path)]
    assert types == ["ligne", "question", "reponse"]
    assert _journal(tmp_path)[2]["source"] == SOURCE_KEYBOARD


def test_questions_are_typed(tmp_path):
    bus = Bus()
    KeyboardClient(bus, ask=lambda p: "x", out=lambda s: None)
    bus.attach(tmp_path)
    for kind in (TEXT, YES_NO, DONE):
        bus.question("?", kind)
    bus.question("Tape CHARGE : ", WORD, word="CHARGE")
    asked = [e for e in _journal(tmp_path) if e["type"] == "question"]
    assert [e["genre"] for e in asked] == [TEXT, YES_NO, DONE, WORD] and asked[-1]["mot"] == "CHARGE"
    with pytest.raises(ValueError):
        bus.question("?", "inconnu")
    with pytest.raises(ValueError):
        bus.question("?", WORD)                          # un mot de sécurité dit toujours le mot demandé


@pytest.mark.parametrize("word", sorted(qbus.SAFETY_WORDS))
def test_a_safety_word_is_refused_unless_typed_by_a_human_at_the_keyboard(tmp_path, word):
    """Règle du cahier § 3 : ni Claude ni l'API ne peuvent fournir CHARGE, ANTENNE ou EMETTRE."""
    bus = Bus()
    bus.attach(tmp_path)
    got = {}
    worker = threading.Thread(target=lambda: got.setdefault("a", bus.question("Tape : ", WORD, word=word)))
    worker.start()
    q = _wait_question(bus)
    for source in (SOURCE_PILOT, "page", "claude", ""):
        with pytest.raises(RefusedAnswer):
            bus.answer(q.id, word, source=source)
    assert worker.is_alive() and bus.open_questions()       # la question reste ouverte : seul un humain y répond
    bus.answer(q.id, word, source=SOURCE_KEYBOARD)
    worker.join(2)
    assert got["a"] == word
    events = _journal(tmp_path)
    assert sum(e["type"] == "refus" for e in events) == 4
    assert [e["source"] for e in events if e["type"] == "reponse"] == [SOURCE_KEYBOARD]


def test_a_plain_question_can_be_answered_by_the_pilot(tmp_path):
    bus = Bus()
    got = {}
    worker = threading.Thread(target=lambda: got.setdefault("a", bus.question("Fréquence ? ", TEXT)))
    worker.start()
    bus.answer(_wait_question(bus).id, "7.1", source=SOURCE_PILOT)
    worker.join(2)
    assert got["a"] == "7.1"
    with pytest.raises(KeyError):
        bus.answer(999, "x", source=SOURCE_KEYBOARD)


def test_events_before_the_session_folder_are_kept():
    bus = Bus()
    KeyboardClient(bus, ask=lambda p: "o", out=lambda s: None)
    bus.ask("Reprendre ? ")
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        bus.attach(Path(d))
        bus.out("après")
        assert [e["n"] for e in _journal(Path(d))] == [1, 2, 3]


def test_without_a_bus_the_helpers_are_plain_input():
    """trx-hwtest lancé seul : `ask` = input, rien ne change."""
    seen = []
    assert ask_word(lambda p: seen.append(p) or "EMETTRE", "Tape EMETTRE : ", "EMETTRE") == "EMETTRE"
    assert ask_typed(lambda p: "o", "?", YES_NO) == "o" and seen == ["Tape EMETTRE : "]


def test_the_ctrl_c_of_the_keyboard_reaches_the_suitcase():
    bus = Bus()

    def interrupt(prompt):
        raise KeyboardInterrupt
    KeyboardClient(bus, ask=interrupt, out=lambda s: None)
    with pytest.raises(KeyboardInterrupt):
        bus.ask("?")
    assert bus.open_questions() == []


# --------------------------------------------------------------------------- la valise passe par le bus

def _cfg(tmp_path):
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path)
    return cfg


PROFILE = SimpleNamespace(model=3094, hamlib_version="4.7.2", backend_status="Stable",
                          caps=SimpleNamespace(model_name="IC-7300", manufacturer="Icom"))


def test_the_suitcase_declares_charge_and_antenne_as_safety_words(tmp_path):
    rx = {"freq_hz": 7_100_000, "mode": "LSB", "level_dbfs": -40.0, "zeros_pct": 0.0, "s_metre_db": -20,
          "verdict": "ok", "problems": []}
    answers = iter(["c", "CHARGE", "r", "ANTENNE", "", "q"])
    terrain.run_terrain(_cfg(tmp_path), PROFILE, "", tmp_path, session_dir=tmp_path / "s",
                        ask=lambda p: next(answers), out=lambda s: None, station=lambda: False,
                        receive=lambda wanted=None: rx)
    words = [e["mot"] for e in _journal(tmp_path / "s") if e["type"] == "question" and e["genre"] == WORD]
    assert words == ["CHARGE", "ANTENNE"]
    assert any(e["type"] == "ligne" for e in _journal(tmp_path / "s"))


def test_the_antenna_part_needs_the_word_antenne(tmp_path):
    """Avant le lot G1 : « Antenne branchée ? (O/n) » validé par Entrée ; désormais le mot ANTENNE."""
    calls, shown = [], []
    answers = iter(["c", "CHARGE", "r", "", "r", "o", "q"])
    terrain.run_terrain(_cfg(tmp_path), PROFILE, "", tmp_path, session_dir=tmp_path / "s",
                        ask=lambda p: next(answers), out=shown.append, station=lambda: False,
                        receive=lambda wanted=None: calls.append(wanted) or {})
    assert calls == [] and shown.count("Non confirmé : réception sur antenne non lancée.") == 2
    assert json.loads((tmp_path / "s" / "session.json").read_text(encoding="utf-8"))["connection"] == "charge"


def test_a_pilot_cannot_confirm_the_dummy_load(tmp_path):
    """Un client non humain (futur pilote) qui répondrait « CHARGE » est refusé ; l'essai n'est pas permis."""
    bus = Bus()
    answers = iter(["c", "CHARGE", "q"])

    def pilot(event):
        if event["type"] != "question":
            return
        text = next(answers)
        try:
            bus.answer(event["id"], text, source=SOURCE_PILOT)
        except RefusedAnswer:
            bus.answer(event["id"], "", source=SOURCE_KEYBOARD)    # l'humain ne tape rien : refus de l'essai
    bus.subscribe(pilot)
    calls = []
    terrain.run_terrain(_cfg(tmp_path), PROFILE, "", tmp_path, session_dir=tmp_path / "s", bus=bus,
                        station=lambda: False, qualify=lambda no_tx: calls.append(no_tx))
    session = json.loads((tmp_path / "s" / "session.json").read_text(encoding="utf-8"))
    assert calls == [] and session["connection"] == ""
    assert any(e["type"] == "refus" for e in _journal(tmp_path / "s"))


def test_the_suitcase_gives_its_ask_to_the_qualification_and_the_exploration(tmp_path, monkeypatch):
    from trxstation.qualif import main as qmain
    seen = {}

    async def fake_qualif(cfg, profile, dump, folder, *, ask, out, **kw):
        seen["qualif"] = qbus.bus_of(ask) is not None and qbus.bus_of(out) is not None
        return 0

    async def fake_explore(cfg, profile, dump, folder, *, ask, out, **kw):
        seen["explore"] = qbus.bus_of(ask) is not None
        return 0
    monkeypatch.setattr(qmain, "run_qualif", fake_qualif)
    monkeypatch.setattr(qmain, "run_explore", fake_explore)
    answers = iter(["2", "c", "CHARGE", "3", "q"])
    terrain.run_terrain(_cfg(tmp_path), PROFILE, "", tmp_path, session_dir=tmp_path / "s",
                        ask=lambda p: next(answers), out=lambda s: None, station=lambda: False)
    assert seen == {"qualif": True, "explore": True}


def test_the_emission_word_of_hwtest_and_autodrills_is_a_safety_word(tmp_path):
    from trxstation.devtools.hwtest import HwTest
    from trxstation.qualif import autodrills
    bus = Bus()
    KeyboardClient(bus, ask=lambda p: "EMETTRE", out=lambda s: None)
    bus.attach(tmp_path)
    import asyncio
    hw = HwTest.__new__(HwTest)
    hw.ask, hw.out, hw.ctrl = bus.ask, bus.out, None
    assert asyncio.run(hw.confirm_emission("essai")) is True
    drill = autodrills.AUTO_DRILLS[0]
    session = terrain.Session.open(tmp_path / "s", model=1)
    cfg = _cfg(tmp_path)

    class Unreadable(terrain.Observer):
        async def read_once(self):
            return None
    import trxstation.qualif.autodrills as ad
    original = ad.Observer
    ad.Observer = Unreadable
    try:
        asyncio.run(autodrills.play_auto(drill, session, client_factory=lambda: None, host="127.0.0.1", port=1,
                                         cfg=cfg, state_dir=tmp_path, ask=bus.ask, out=bus.out))
    finally:
        ad.Observer = original
    words = [e["mot"] for e in _journal(tmp_path) if e["type"] == "question" and e["genre"] == WORD]
    assert len(words) == 2 and words[1] == "EMETTRE"
