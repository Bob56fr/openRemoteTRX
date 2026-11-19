# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""API de pilotage de la valise (lot G3) : jeton propre, aucun navigateur, actions du menu seulement au menu, questions
à l'humain, STOP ; et la règle du cahier : l'API ne peut JAMAIS fournir un mot de sécurité (CHARGE, ANTENNE,
EMETTRE) ni répondre à une question de la valise à la place de l'humain."""
from __future__ import annotations

import asyncio
import json
import threading

from aiohttp.test_utils import TestClient, TestServer

from trxstation.qualif.bus import (CHOICE, SECRET, SOURCE_PILOT, SOURCE_WINDOW, WORD, YES_NO, Bus, RefusedAnswer)
from trxstation.qualif.page.server import PILOT_HEADER, ValisePage, pilot_key_allowed
from trxstation.qualif.pilot import Pilot, describe, run_pilot

from test_qualif_page import ask_in_thread, free_port, until

MENU = [{"cle": k} for k in ("9", "1", "r", "3", "5", "8", "d", "a", "7", "q")]


def scenario(body, *, stop_tx=lambda: (True, "ok"), interrupt=lambda: None, tmp_path=None):
    async def run():
        bus = Bus(interrupt=interrupt)
        page = ValisePage(bus, stop_tx=stop_tx, lang="fr", port=free_port(),
                          pilot_file=(tmp_path / "pilote.json") if tmp_path else None)
        page.loop = asyncio.get_running_loop()
        async with TestClient(TestServer(page.app(), host="127.0.0.1", port=page.port)) as client:
            await body(bus, page, client, {PILOT_HEADER: page.pilot_token})
    asyncio.run(run())


def test_the_pilot_needs_its_token_and_never_a_browser():
    async def body(bus, page, client, auth):
        assert (await client.get("/pilote/etat")).status == 403                          # sans jeton
        assert (await client.get("/pilote/etat", headers={PILOT_HEADER: "faux"})).status == 403
        browser = {**auth, "Origin": f"http://127.0.0.1:{page.port}"}
        assert (await client.get("/pilote/etat", headers=browser)).status == 403          # une page web : jamais
        assert (await client.post("/pilote/stop", headers=browser)).status == 403
        r = await client.get("/pilote/etat", headers=auth)
        assert r.status == 200 and (await r.json())["menu"] is False
        # le cookie de la page ne donne pas le pilotage
        await client.get(f"/?t={page.token}", allow_redirects=False)
        assert (await client.get("/pilote/etat")).status == 403
    scenario(body)


def test_the_pilot_launches_a_menu_action_only_when_the_suitcase_waits_at_the_menu():
    async def body(bus, page, client, auth):
        r = await client.post("/pilote/lancer", json={"cle": "r"}, headers=auth)
        assert (await r.json())["ok"] is False                                           # pas encore au menu
        th, box = ask_in_thread(bus, "Choix : ", CHOICE, choices=MENU, role="menu")
        await until(lambda: page._menu() is not None)
        for refused in ("q", "5", "8", "zz", "theme:inconnu", "", 12):
            r = await client.post("/pilote/lancer", json={"cle": refused}, headers=auth)
            assert (await r.json())["ok"] is False, refused
        assert th.is_alive()
        r = await client.post("/pilote/lancer", json={"cle": "8.1"}, headers=auth)
        assert (await r.json())["ok"] is True
        th.join(2)
        assert box["answer"] == "8.1"
        sent = [e for e in page.history if e["type"] == "reponse"]
        assert sent[-1]["source"] == SOURCE_PILOT
        assert any(e["type"] == "pilote" and e.get("cle") == "8.1" for e in page.history)   # petit bip de la page
    scenario(body)


def test_the_api_never_supplies_a_safety_word_nor_answers_for_the_human():
    """Règle du cahier (§ 3) : CHARGE / ANTENNE / EMETTRE ne viennent QUE de la fenêtre, tapés par un humain."""
    async def body(bus, page, client, auth):
        th, box = ask_in_thread(bus, "Tapez EMETTRE : ", WORD, word="EMETTRE", family="EMETTRE")
        await until(lambda: bus.open_questions())
        qid = bus.open_questions()[0].id
        # aucune route du pilote ne répond à une question de la valise
        for path in ("/pilote/repondre", "/pilote/reponse", "/pilote/mot"):
            r = await client.post(path, json={"id": qid, "texte": "EMETTRE"}, headers=auth)
            assert r.status in (404, 405)
        # « lancer » ne répond qu'au MENU : jamais à un mot de sécurité
        r = await client.post("/pilote/lancer", json={"cle": "EMETTRE"}, headers=auth)
        assert (await r.json())["ok"] is False
        # et le bus refuse de toute façon un mot venant du pilote
        try:
            bus.answer(qid, "EMETTRE", source=SOURCE_PILOT)
            raise AssertionError("mot de sécurité accepté du pilote")
        except RefusedAnswer:
            pass
        state = await (await client.get("/pilote/etat", headers=auth)).json()
        assert state["attente_operateur"][0]["mot"] == "EMETTRE" and th.is_alive()
        bus.answer(qid, "EMETTRE", source=SOURCE_WINDOW)                                  # l'humain, au clavier
        th.join(2)
        assert box["answer"] == "EMETTRE"
    scenario(body)


def test_the_pilot_asks_the_human_and_reads_the_answer_but_never_a_word_or_a_secret():
    async def body(bus, page, client, auth):
        for kind in (WORD, SECRET, CHOICE, "inconnu"):
            r = await client.post("/pilote/demander", json={"genre": kind, "texte": "x"}, headers=auth)
            assert (await r.json())["ok"] is False, kind
        r = await client.post("/pilote/demander", json={"genre": YES_NO, "texte": "Antenne branchée ?"}, headers=auth)
        n = (await r.json())["demande"]
        await until(lambda: any(str(q.get("role")) == f"pilote:{n}" for q in page.open.values()))
        q = next(q for q in page.open.values() if str(q.get("role")) == f"pilote:{n}")
        state = await (await client.get("/pilote/etat", headers=auth)).json()
        assert state["questions_du_pilote"] == [q["id"]] and state["attente_operateur"] == []
        assert (await (await client.get(f"/pilote/reponse?demande={n}", headers=auth)).json())["etat"] == "attente"
        assert page.handle({"type": "reponse", "id": q["id"], "text": "o"}) is None     # l'humain répond dans la page
        await until(lambda: page.pilot_asks[n]["etat"] == "repondu")
        reply = await (await client.get(f"/pilote/reponse?demande={n}", headers=auth)).json()
        assert reply == {"ok": True, "etat": "repondu", "texte": "o"}
    scenario(body)


def test_the_pilot_stop_cuts_first_like_the_page_button():
    calls = []

    def stop_tx():
        calls.append("T 0")
        return True, "ok"

    def interrupt():
        calls.append("interruption")

    async def body(bus, page, client, auth):
        r = await client.post("/pilote/stop", headers=auth)
        assert (await r.json())["ok"] is True
        assert calls == ["T 0", "interruption"]
    scenario(body, stop_tx=stop_tx, interrupt=interrupt)


def test_the_pilot_file_is_private_and_removed(tmp_path):
    async def body(bus, page, client, auth):
        page.write_pilot_file()
        data = json.loads((tmp_path / "pilote.json").read_text(encoding="utf-8"))
        assert data["port"] == page.port and data["jeton"] == page.pilot_token
        page.remove_pilot_file()
        assert not (tmp_path / "pilote.json").exists()
    scenario(body, tmp_path=tmp_path)


def test_menu_keys_allowed_to_the_pilot():
    menu = {"choix": MENU}
    for key in ("9", "r", "3", "7", "d", "a", "5.6", "8.3", "tout", "echecs", "theme:auto"):
        assert pilot_key_allowed(key, menu), key
    for key in ("q", "5", "8", "5.99", "theme:x", "x", None, "a" * 50):
        assert not pilot_key_allowed(key, menu), key


def test_the_command_line_client_end_to_end(tmp_path):
    """`trx-qualif --pilote` contre une vraie page dans son fil : état, lancer, attendre le retour au menu."""
    bus = Bus(interrupt=lambda: None)
    page = ValisePage(bus, stop_tx=lambda: (True, "ok"), lang="fr", port=free_port(),
                      pilot_file=tmp_path / "pilote.json")
    page.start()
    page.write_pilot_file()
    done = threading.Event()

    def valise():                     # une valise minimale : menu, une ligne de journal, de nouveau le menu
        first = bus.question("Choix : ", CHOICE, choices=MENU, role="menu")
        bus.out(f"essai {first} joué")
        bus.question("Choix : ", CHOICE, choices=MENU, role="menu")
        done.set()
    th = threading.Thread(target=valise, daemon=True)
    th.start()
    try:
        lines: list[str] = []
        pilot = Pilot.from_folder(tmp_path)
        for _ in range(100):
            if pilot.state()["menu"]:
                break
        assert run_pilot(["etat"], tmp_path, out=lines.append) == 0 and "MENU" in lines[-1]
        assert run_pilot(["lancer", "q"], tmp_path, out=lines.append) == 1
        lines.clear()
        assert run_pilot(["lancer", "r", "10"], tmp_path, out=lines.append) == 0      # lancé puis suivi
        assert "essai r joué" in lines and lines[-1] == "== retour au menu"
        assert "Poste" in describe(pilot.state())
    finally:
        for q in bus.open_questions():
            bus.answer(q.id, "q", source="clavier")
        page.close()
    assert run_pilot(["etat"], tmp_path / "ailleurs", out=lines.append) == 1     # aucune valise ici


def test_the_pilot_words_reach_the_pilot_untouched_even_with_dashes():
    """« demander --fait TEXTE » : argparse prenait « --fait » pour une option inconnue de trx-qualif (FTDX10,
    2026-11-19). Les mots de --pilote vont jusqu'à --output / --config."""
    from trxstation.qualif.main import _split_pilot
    rest, words = _split_pilot(["--pilote", "demander", "--fait", "Règle la carte son", "--output", "valise"])
    assert words == ["demander", "--fait", "Règle la carte son"] and rest == ["--output", "valise"]
    rest, words = _split_pilot(["--output=valise", "--pilote", "demander", "--oui-non", "Antenne ?"])
    assert words == ["demander", "--oui-non", "Antenne ?"] and rest == ["--output=valise"]
    assert _split_pilot(["--terrain", "--page"]) == (["--terrain", "--page"], None)
