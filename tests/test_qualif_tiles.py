# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Tuiles et enchaînements de la valise (lot G2b) : états lus dans la session, ordre de « Tout lancer », préalables
faits au moment de chaque essai (station, mot CHARGE demandé à l'humain), arrêt de l'enchaînement sur un refus."""
from __future__ import annotations

import json
from types import SimpleNamespace

from trxstation.qualif import autodrills, terrain, tiles
from trxstation.qualif.bus import SOURCE_KEYBOARD, WORD, Bus

PROFILE = SimpleNamespace(model=3094, hamlib_version="4.7.2", backend_status="Stable",
                          caps=SimpleNamespace(model_name="IC-7300", manufacturer="Icom"))


def _cfg(tmp_path):
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path)
    return cfg


def _session(tmp_path):
    return terrain.Session.open(tmp_path / "s", model=3094)


def test_tile_states_come_from_what_the_session_recorded(tmp_path):
    s = _session(tmp_path)
    assert all(tiles.item_state(s, k)[0] == tiles.TODO for k in tiles.order())
    s.audio = {"capture": {"name": "2- USB Audio Device", "level_dbfs": -40}, "problems": []}
    s.reception = {"verdict": "faible", "freq_hz": 7_100_000, "mode": "LSB", "level_dbfs": -80}
    s.spectrum = {"verdict": "non_propose", "detail": "Yaesu"}
    s.filters = {"verdict": "echec", "detail": "FIL2 non relu"}
    s.snapshots = {"avant": {"at": "x", "count": 48}}
    s.drills = {"stop_page": {"result": "reussi", "reason": "réception 0.4 s après"},
                "tot": {"result": "echec", "reason": "coupée après 31 s"}, "auto_stop": {"result": "non_mesure"}}
    s.runs = [{"kind": "qualif", "verdict": "validation_en_cours", "emission": True},
              {"kind": "qualif", "verdict": "incomplet", "emission": False}]
    state = {k: tiles.item_state(s, k)[0] for k in tiles.order() + ("4",)}
    assert state["9"] == tiles.OK and state["r"] == tiles.PARTIAL and state["s"] == tiles.ABSENT
    assert state["f"] == tiles.FAILED and state["1"] == tiles.OK and state["3"] == tiles.OK and state["4"] == tiles.PARTIAL
    assert state["5.1"] == tiles.OK and state["5.2"] == tiles.FAILED and state["8.1"] == tiles.PARTIAL
    assert tiles.item_state(s, "1")[1] == "48 lectures" and "7.100 MHz LSB" in tiles.item_state(s, "r")[1]


def test_tiles_count_progress_without_optional_absent_or_the_no_tx_qualification(tmp_path):
    s = _session(tmp_path)
    s.spectrum = {"verdict": "non_propose"}
    data = tiles.tiles(s, lambda d: d.id)
    ids = [t["id"] for t in data["themes"]]
    assert ids == ["releves", "reception", "emission", "auto", "main"]
    manual = next(t for t in data["themes"] if t["id"] == "main")["essais"]
    assert manual[-1]["facultatif"] is True and manual[0]["texte"] == "stop_page"     # reboot : facultatif
    expected = len(tiles.order()) - 1 - 1             # moins « s » (absent) et le reboot (facultatif) ; « 4 » hors de l'ordre
    assert data["faits"] == 0 and data["total"] == expected


def test_plan_follows_the_advised_order_and_skips_what_is_done(tmp_path):
    s = _session(tmp_path)
    order = tiles.plan(s, "tout")
    assert order[:7] == ["9", "1", "r", "2", "s", "f", "3"] and order[-1] == "6"
    assert order.index("8.1") < order.index("5.1") and "4" not in order and "5.10" not in order   # reboot facultatif
    s.audio = {"problems": []}
    s.drills = {"tot": {"result": "echec"}, "stop_page": {"result": "reussi"}}
    assert "9" not in tiles.plan(s, "tout") and "5.1" not in tiles.plan(s, "tout")
    assert tiles.plan(s, "echecs") == ["5.2"]
    assert tiles.plan(s, "theme:reception") == ["r", "s", "f"] and tiles.plan(s, "theme:inconnu") == []
    assert tiles.needs_load("8.3") and tiles.needs_load("3") and not tiles.needs_load("r")
    assert tiles.needs_running("5.2") and tiles.needs_stopped("r") and not tiles.needs_stopped("5.2")
    assert tiles.NEEDS_STOPPED == terrain.NEEDS_STOPPED and tiles.NEEDS_LOAD == terrain.NEEDS_LOAD


def _run(tmp_path, answers, *, running=False, **fakes):
    """La valise avec un client clavier scripté ; renvoie les événements écrits dans evenements.jsonl."""
    bus = Bus()
    it = iter(answers)
    bus.subscribe(lambda e: bus.answer(e["id"], next(it), source=SOURCE_KEYBOARD) if e["type"] == "question" else None)
    state = {"running": running}

    def control(start):
        state["running"] = start
        return 0
    terrain.run_terrain(_cfg(tmp_path), PROFILE, "", tmp_path, session_dir=tmp_path / "s", bus=bus,
                        station=lambda: state["running"], control=control, pause=lambda s: None, **fakes)
    return [json.loads(x) for x in (tmp_path / "s" / "evenements.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_theme_runs_its_tests_and_asks_antenne_to_the_human(tmp_path):
    calls = []
    rx = {"freq_hz": 7_100_000, "mode": "LSB", "level_dbfs": -40.0, "zeros_pct": 0.0, "s_metre_db": -20,
          "verdict": "ok", "problems": []}
    events = _run(tmp_path, ["theme:reception", "ANTENNE", "", "q"],
                  receive=lambda wanted=None: calls.append("r") or rx,
                  scope=lambda: calls.append("s") or {"verdict": "ok", "sweeps": 3},
                  filters=lambda: calls.append("f") or {"verdict": "ok", "origine": "FIL1"})
    assert calls == ["r", "s", "f"]
    assert [e["mot"] for e in events if e["type"] == "question" and e["genre"] == WORD] == ["ANTENNE"]
    assert [e["cle"] for e in events if e["type"] == "enchainement"] == ["r", "s", "f"]
    menu = [e for e in events if e["type"] == "question" and e.get("role") == "menu"]
    assert len(menu) == 2 and any(e["type"] == "tuiles" for e in events)


def test_a_chain_stops_the_station_first_and_asks_charge_before_transmitting(tmp_path):
    calls = []
    events = _run(tmp_path, ["theme:emission", "CHARGE", "q"], running=True, qualify=lambda no_tx: calls.append(no_tx))
    assert calls == [False]
    assert any("terrain.control_done" not in e.get("texte", "") and e["type"] == "ligne" for e in events)
    words = [e["mot"] for e in events if e["type"] == "question" and e["genre"] == WORD]
    assert words == ["CHARGE"]


def test_a_refused_charge_stops_the_chain_and_nothing_transmits(tmp_path):
    calls = []
    events = _run(tmp_path, ["theme:emission", "non", "q"], qualify=lambda no_tx: calls.append(no_tx))
    assert calls == []
    assert any(e["type"] == "avis" and "Enchaînement arrêté" in e["texte"] for e in events)


def test_automatic_tests_ask_the_operator_account_once(tmp_path, monkeypatch):
    asked, played = [], []
    monkeypatch.setattr(autodrills, "operator_factory", lambda cfg, ask, out, **kw: asked.append(1) or (lambda: None))

    async def fake_play(drill, session, **kw):
        played.append(drill.id)
        return {}
    monkeypatch.setattr(autodrills, "play_auto", fake_play)
    (tmp_path / "s").mkdir()
    s = _session(tmp_path)
    s.connection = "charge"
    s.save()
    _run(tmp_path, ["8.1", "8.2", "q"], running=True)
    assert asked == [1] and played == ["auto_stop", "auto_heartbeat"]


def test_the_observer_tells_the_page_each_ptt_change():
    seen = []
    obs = terrain.Observer("127.0.0.1", 1)
    obs.notify = seen.append
    for v in (0, 0, 1, 1, None, 0):
        obs._note(v)
    assert seen == [0, 1, None, 0]


def test_the_suitcase_starts_its_own_station_not_the_installed_task(tmp_path, monkeypatch):
    """Essai du 2026-11-18 : « d » lançait la tâche planifiée « TRX distant », absente sur un PC de qualification
    (et qui démarrerait la station installée, avec SA configuration). Configuration propre = son superviseur."""
    import os
    import subprocess
    import pytest
    if os.name != "nt":
        pytest.skip("démarrage propre à Windows (systemd sous Linux)")
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: launched.append((cmd, kw)))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: launched.append((cmd, kw)) or SimpleNamespace(returncode=0))
    config = tmp_path / "qualif" / "station.toml"
    config.parent.mkdir()
    config.write_text("", encoding="utf-8")
    assert terrain.own_station_config(config) and not terrain.own_station_config(None)
    assert terrain.station_control(config, True) == 0
    cmd, kw = launched[0]
    assert cmd[1:3] == ["-m", "trxstation.supervisor.main"] and str(config.resolve()) in cmd
    assert cmd[-1] == str(config.parent.resolve() / "logs") and (config.parent / "logs").is_dir()
    launched.clear()
    terrain.station_control(config, False)                     # arrêt : --stop avec SA configuration
    assert "--stop" in launched[0][0] and str(config) in launched[0][0]
    launched.clear()
    terrain.station_control(None, True)                        # station installée : sa tâche planifiée
    assert launched[0][0][:2] == ["schtasks", "/Run"]


def test_starting_the_station_waits_for_it_and_tells_the_page(tmp_path):
    """Essai du 2026-11-18 : après « d », la page restait sur « Station du PC : arrêtée » (menu réaffiché 30 ms après
    la commande, station pas encore partie)."""
    events = _run(tmp_path, ["d", "a", "q"])
    seen = [e["station"] for e in events if e["type"] == "statut" and "station" in e]
    assert seen == [False, True, True, False, False]       # menu, « d » attendu, menu, « a » attendu, menu
    assert any("Attente de la station du PC" in e.get("texte", "") for e in events)


# --------------------------------------------------------------------------- essai du 2026-11-18 (compte faux)

def _cfg_with_account(tmp_path, password="motdepasse-valise-1"):
    from trxstation.config import ClientAuth as ClientConfig
    from trxstation.passwords import hash_password
    cfg = _cfg(tmp_path)
    cfg.clients = [ClientConfig(id="valise", password_hash=hash_password(password))]
    return cfg


def test_the_operator_account_is_checked_when_typed(tmp_path):
    """Compte faux (« BOB ») ou mot de passe faux : refusé TOUT DE SUITE et redemandé, jamais gardé."""
    cfg = _cfg_with_account(tmp_path)
    shown = []
    answers = iter(["BOB", "valise", "faux", "valise", "motdepasse-valise-1"])
    made = []
    got = autodrills.operator_factory(cfg, ask=lambda p: next(answers), out=shown.append,
                                      factory=lambda cid, pw: made.append((cid, pw)) or "client",
                                      secret=lambda p: next(answers))
    assert got == "client" and made == [("valise", "motdepasse-valise-1")]
    text = "\n".join(shown)
    assert "« BOB » inconnu" in text and "Mot de passe refusé" in text and "vérifié" in text
    answers = iter(["valise", "x", "valise", "y", "valise", "z"])           # trois échecs : abandon
    assert autodrills.operator_factory(cfg, ask=lambda p: next(answers), out=shown.append,
                                       factory=lambda cid, pw: "client", secret=lambda p: next(answers)) is None
    assert autodrills.operator_factory(_cfg(tmp_path), ask=lambda p: "", out=shown.append) is None   # aucun compte


def test_a_link_error_stops_the_chain_and_forgets_the_account(tmp_path, monkeypatch):
    asked, played = [], []
    monkeypatch.setattr(autodrills, "operator_factory", lambda cfg, ask, out, **kw: asked.append(1) or (lambda: None))

    async def refused(drill, session, **kw):
        played.append(drill.id)
        return {"reason": "erreur : ConnectionRefusedError('offre refusée : HTTP 401 unauthorized')"}
    monkeypatch.setattr(autodrills, "play_auto", refused)
    (tmp_path / "s").mkdir()
    s = _session(tmp_path)
    s.connection = "charge"
    s.save()
    events = _run(tmp_path, ["theme:auto", "8.1", "q"], running=True)
    assert played == ["auto_stop", "auto_stop"] and asked == [1, 1]      # arrêt après A1 ; compte redemandé ensuite
    assert any(e["type"] == "avis" and "n'a pas pu parler à la station" in e["texte"] for e in events)


def test_a_chain_announces_the_hand_played_tests_and_can_skip_them(tmp_path, monkeypatch):
    played = []

    async def fake_drill(drill, session, **kw):
        played.append(drill.id)
        return {}
    monkeypatch.setattr(terrain, "play_drill", fake_drill)
    (tmp_path / "s").mkdir()
    s = _session(tmp_path)
    s.connection = "charge"
    s.save()
    events = _run(tmp_path, ["theme:main", "s", "q"], running=True)
    assert played == []
    asked = [e for e in events if e["type"] == "question" and "page DE LA STATION" in e["texte"]]
    assert len(asked) == 1 and "http://127.0.0.1:" in asked[0]["texte"]
    events = _run(tmp_path, ["theme:main", "", "q"], running=True)
    assert len(played) == len(tiles.manual_keys()) - 1                   # tous sauf le redémarrage du PC (facultatif)


def test_the_password_of_the_qualification_folder_is_used_without_asking(tmp_path):
    """Dossier de qualification : valise.pw à côté de station.toml ; s'il ouvre un compte, rien n'est demandé."""
    cfg = _cfg_with_account(tmp_path)
    pw = tmp_path / "valise.pw"
    pw.write_text("motdepasse-valise-1\n", encoding="utf-8")
    shown, made = [], []
    got = autodrills.operator_factory(cfg, ask=lambda p: 1 / 0, out=shown.append, password_file=pw,
                                      factory=lambda cid, p: made.append((cid, p)) or "client")
    assert got == "client" and made == [("valise", "motdepasse-valise-1")] and "lu dans valise.pw" in shown[-1]
    pw.write_text("autre-chose", encoding="utf-8")                       # fichier faux : on redemande
    answers = iter([""])
    assert autodrills.operator_factory(cfg, ask=lambda p: next(answers), out=shown.append, password_file=pw,
                                       factory=lambda cid, p: "client") is None


def test_cancelling_the_account_skips_the_automatic_tests_and_the_chain_goes_on(tmp_path, monkeypatch):
    """Demande de l'utilisateur (2026-11-19) : « Annuler » sans perdre le reste de l'enchaînement."""
    asked, played = [], []
    monkeypatch.setattr(autodrills, "operator_factory", lambda cfg, ask, out, **kw: asked.append(1) or None)

    async def fake_drill(drill, session, **kw):
        played.append(drill.id)
        return {}
    monkeypatch.setattr(terrain, "play_drill", fake_drill)
    (tmp_path / "s").mkdir()
    s = _session(tmp_path)
    s.connection = "charge"
    s.save()
    s.audio, s.snapshots = {"problems": []}, {"avant": {"count": 1}, "apres": {"count": 1}}
    s.reception, s.spectrum, s.filters = {"verdict": "ok"}, {"verdict": "ok"}, {"verdict": "ok"}
    s.runs = [{"kind": "explore"}, {"kind": "qualif", "verdict": "validation_en_cours", "emission": True}]
    s.save()
    events = _run(tmp_path, ["tout", "", "q"], running=True, explore=lambda: None, qualify=lambda no_tx: None)
    assert asked == [1]                                                  # demandé UNE fois pour tout l'enchaînement
    assert len(played) == len(tiles.manual_keys()) - 1                   # la suite (essais à la main) a continué
    assert sum(e["type"] == "avis" and "Essai automatique passé" in e["texte"] for e in events) == 5
    assert not any(e["type"] == "avis" and "Enchaînement arrêté" in e["texte"] for e in events)
