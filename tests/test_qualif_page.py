# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Page de la valise (lot G2a) : accès (jeton, cookie, Host, Origin), questions par la page, mots de sécurité
SEULEMENT par la fenêtre d'intervention, STOP (T 0 d'abord, puis l'enchaînement interrompu, retour au menu)."""
from __future__ import annotations

import asyncio
import json
import re
import socket
import threading
import time
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from trxstation.qualif import terrain
from trxstation.qualif.bus import (SOURCE_KEYBOARD, SOURCE_WINDOW, WORD, Bus, QuestionStopped)
from trxstation.qualif.page import server as page_server
from trxstation.qualif.page.server import COOKIE, STATIC, STATIC_FILES, ValisePage, load_texts


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def scenario(body, *, stop_tx=lambda: (True, "ok"), interrupt=lambda: None):
    async def run():
        bus = Bus(interrupt=interrupt)
        page = ValisePage(bus, stop_tx=stop_tx, lang="fr", port=free_port())
        page.loop = asyncio.get_running_loop()
        async with TestClient(TestServer(page.app(), host="127.0.0.1", port=page.port)) as client:
            await body(bus, page, client)
    asyncio.run(run())


async def login(page, client):
    r = await client.get(f"/?t={page.token}", allow_redirects=False)
    assert r.status == 302 and COOKIE in r.cookies
    return {"Origin": f"http://127.0.0.1:{page.port}"}


def ask_in_thread(bus, *args, **kw):
    box: dict = {}

    def go():
        try:
            box["answer"] = bus.question(*args, **kw)
        except BaseException as exc:          # noqa: BLE001
            box["error"] = exc
    th = threading.Thread(target=go, daemon=True)
    th.start()
    return th, box


async def until(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("délai dépassé")


async def receive(ws, kind, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        msg = await ws.receive_json(timeout=timeout)
        if msg.get("type") == kind:
            return msg
    raise AssertionError(f"pas de message {kind}")


def test_one_time_token_then_cookie_host_origin_and_closed_static_list():
    async def body(bus, page, client):
        token = page.token
        assert (await client.get("/")).status == 403                         # sans cookie
        origin = await login(page, client)
        r = await client.get("/")
        assert r.status == 200 and 'lang="fr"' in await r.text()
        assert "script-src 'self'" in r.headers["Content-Security-Policy"] and page.token is None
        import aiohttp
        async with aiohttp.ClientSession() as other:
            assert (await other.get(client.make_url(f"/?t={token}"), allow_redirects=False)).status == 403
            assert (await other.get(client.make_url("/"))).status == 403
        assert (await client.get("/", headers={"Host": "evil.example:80"})).status == 403     # rebinding
        assert (await client.post("/api/stop")).status == 403                                  # sans Origin
        assert (await client.post("/api/stop", headers={"Origin": "http://evil.example"})).status == 403
        assert (await client.get("/ws")).status == 403
        assert (await client.get("/static/server.py")).status == 404
        assert (await client.get("/static/../server.py")).status in (403, 404)
        assert (await client.get("/static/valise.js")).status == 200 and origin
    scenario(body)


def test_the_page_answers_a_menu_choice_and_sees_the_journal():
    async def body(bus, page, client):
        origin = await login(page, client)
        bus.out("ligne avant la page")
        th, box = ask_in_thread(bus, "Choix : ", "choix", choices=[{"cle": "9"}, {"cle": "q"}])
        await until(lambda: page.open)
        async with client.ws_connect("/ws", headers=origin) as ws:
            init = await receive(ws, "init")
            assert init["textes"]["menu.9"] and [q["genre"] for q in init["ouvertes"]] == ["choix"]
            assert any(e.get("texte") == "ligne avant la page" for e in init["evenements"])
            await ws.send_json({"type": "reponse", "id": init["ouvertes"][0]["id"], "text": "9"})
            await until(lambda: "answer" in box)
        assert box["answer"] == "9"
    scenario(body)


def test_a_safety_word_only_comes_from_the_intervention_window_typed_at_the_keyboard():
    """Cahier § 3 : la route ordinaire de la page, un collage ou une saisie simulée ne donnent JAMAIS le mot."""
    async def body(bus, page, client):
        origin = await login(page, client)
        th, box = ask_in_thread(bus, "Tape CHARGE : ", WORD, word="CHARGE", context="Branche la charge fictive.")
        await until(lambda: page.open)
        async with client.ws_connect("/ws", headers=origin) as ws:
            init = await receive(ws, "init")
            q = init["ouvertes"][0]
            assert q["famille"] == "CHARGE" and q["contexte"] == "Branche la charge fictive."
            await ws.send_json({"type": "reponse", "id": q["id"], "text": "CHARGE"})
            assert (await receive(ws, "erreur"))["cle"] == "err.word_window"
            await ws.send_json({"type": "mot", "id": q["id"], "text": "CHARGE", "trusted": False})
            assert (await receive(ws, "erreur"))["cle"] == "err.not_typed"
            await ws.send_json({"type": "mot", "id": q["id"], "text": "CHARGE"})
            assert (await receive(ws, "erreur"))["cle"] == "err.not_typed"
            assert th.is_alive() and bus.open_questions()            # la question attend toujours un humain
            await ws.send_json({"type": "mot", "id": q["id"], "text": "CHARGE", "trusted": True})
            await until(lambda: "answer" in box)
        assert box["answer"] == "CHARGE"
        answered = [e for e in page.history if e["type"] == "reponse"]
        assert [e["source"] for e in answered] == [SOURCE_WINDOW]
    scenario(body)


def test_the_window_route_refuses_an_ordinary_question():
    async def body(bus, page, client):
        origin = await login(page, client)
        th, box = ask_in_thread(bus, "Fréquence : ", "texte")
        await until(lambda: page.open)
        async with client.ws_connect("/ws", headers=origin) as ws:
            q = (await receive(ws, "init"))["ouvertes"][0]
            await ws.send_json({"type": "mot", "id": q["id"], "text": "7.1", "trusted": True})
            assert (await receive(ws, "erreur"))["cle"] == "err.not_word"
            await ws.send_json({"type": "reponse", "id": q["id"], "text": "7.1"})
            await until(lambda: "answer" in box)
        assert box["answer"] == "7.1"
    scenario(body)


def test_a_page_closed_during_a_question_finds_it_again():
    async def body(bus, page, client):
        origin = await login(page, client)
        th, box = ask_in_thread(bus, "Tape EMETTRE : ", WORD, word="EMETTRE")
        await until(lambda: page.open)
        async with client.ws_connect("/ws", headers=origin) as ws:
            assert len((await receive(ws, "init"))["ouvertes"]) == 1
        assert th.is_alive()                                           # page fermée : la valise attend
        async with client.ws_connect("/ws", headers=origin) as ws:
            q = (await receive(ws, "init"))["ouvertes"][0]
            assert q["mot"] == "EMETTRE"
            await ws.send_json({"type": "mot", "id": q["id"], "text": "", "trusted": True})   # « Passer cet essai »
            await until(lambda: "answer" in box)
        assert box["answer"] == ""
    scenario(body)


def test_stop_cuts_the_transmission_first_then_interrupts_and_releases_the_questions():
    order = []

    async def body(bus, page, client):
        origin = await login(page, client)
        th, box = ask_in_thread(bus, "Entrée quand c'est fini : ", "fait")
        await until(lambda: page.open)
        r = await client.post("/api/stop", headers=origin)
        assert (await r.json()) == {"ok": True, "message": "coupé"}
        await until(lambda: "error" in box)
        assert isinstance(box["error"], QuestionStopped)
        assert any(e["type"] == "stop" for e in page.history) and any(e["type"] == "annule" for e in page.history)
        assert bus.consume_stop() and not bus.consume_stop()
    scenario(body, stop_tx=lambda: order.append("T 0") or (True, "coupé"),
             interrupt=lambda: order.append("interruption"))
    assert order == ["T 0", "interruption"]


def test_texts_fr_and_en_have_the_same_keys_and_every_menu_entry():
    fr, en = load_texts("fr"), load_texts("en")
    assert fr.keys() == en.keys()
    for key in terrain.MENU_KEYS:
        assert f"menu.{key}" in fr
    for name in ("tous", "retour"):
        assert f"choice.{name}" in fr
    js = (STATIC / "valise.js").read_text(encoding="utf-8")
    used = {k for k in re.findall(r'\bt\("([a-z_.]+)"', js) if not k.endswith(".")}
    assert used <= fr.keys(), used - fr.keys()
    from trxstation.qualif import tiles
    dynamic = {f"theme.{t}" for t, _, _ in tiles.themes()} | {f"where.{w}" for _, w, _ in tiles.themes()}
    dynamic |= {f"state.{s}" for s in ("ok", "partiel", "echec", "encours", "a_faire", "absent")}
    dynamic |= {f"meter.{m}" for m in ("freq", "po", "swr", "alc", "s")}
    dynamic |= {f"why.{w}" for w in ("CHARGE", "ANTENNE", "EMETTRE")}
    dynamic |= {f"connection.{c}" for c in ("antenne", "charge", "inconnu")} | {"choice.tous", "choice.retour"}
    dynamic |= {"blocked.marche", "blocked.arretee"}
    assert dynamic <= fr.keys(), dynamic - fr.keys()
    source = open(page_server.__file__, encoding="utf-8").read()
    assert set(re.findall(r'"(err\.[a-z_]+)"', source)) <= fr.keys()


def test_the_page_has_no_inline_script_and_serves_only_its_files():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son[a-z]+=", html)
    for name in STATIC_FILES:
        assert (STATIC / name).exists() and f"/static/{name}" in html


# --------------------------------------------------------------------------- la valise et son STOP

def _cfg(tmp_path):
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path)
    return cfg


PROFILE = SimpleNamespace(model=3094, hamlib_version="4.7.2", backend_status="Stable",
                          caps=SimpleNamespace(model_name="IC-7300", manufacturer="Icom"))


def test_a_stop_during_a_qualification_comes_back_to_the_menu(tmp_path):
    """STOP = Ctrl+C simulé dans le fil principal : la qualification (asyncio.run) est annulée, la valise le dit et
    revient au menu ; un vrai Ctrl+C, lui, arrête toujours la valise."""
    bus = Bus()                                                  # interruption RÉELLE du fil principal
    answers = iter(["c", "CHARGE", "3", "q"])
    cancelled = []

    def client(event):
        if event["type"] == "question":
            bus.answer(event["id"], next(answers), source=SOURCE_KEYBOARD)
    bus.subscribe(client)
    shown = []
    bus.subscribe(lambda e: shown.append(e.get("texte", "")) if e["type"] == "ligne" else None)

    async def long_qualification():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(True)                               # les « finally » des essais coupent l'émission
            raise
    threading.Timer(0.4, bus.request_stop).start()
    code = terrain.run_terrain(_cfg(tmp_path), PROFILE, "", tmp_path, session_dir=tmp_path / "s", bus=bus,
                               station=lambda: False, qualify=lambda no_tx: asyncio.run(long_qualification()))
    assert code == 0 and cancelled == [True]
    assert any("STOP demandé depuis la page" in line for line in shown)
    events = [json.loads(line) for line in (tmp_path / "s" / "evenements.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["type"] for e in events].count("stop") == 1


def test_run_with_page_answers_only_in_the_page(monkeypatch):
    """Mode page : le terminal affiche (questions marquées « [page] »), il ne répond à rien."""
    shown = []

    def run(bus):
        th, box = ask_in_thread(bus, "Choix : ", "choix", choices=[{"cle": "q"}])
        time.sleep(0.2)
        assert th.is_alive()                                     # personne au terminal ne répond
        q = bus.open_questions()[0]
        bus.answer(q.id, "q", source="page")
        th.join(2)
        return 0 if box.get("answer") == "q" else 1
    code = page_server.run_with_page(run, stop_tx=lambda: (True, ""), lang="en", announce=shown.append,
                                     open_browser=False, port=free_port())
    assert code == 0
    assert any("[page] Choix :" in s for s in shown) and any("Suitcase page: http://127.0.0.1:" in s for s in shown)


def test_the_menu_greys_what_the_suitcase_will_refuse_and_says_why(tmp_path):
    """Essai réel du 2026-11-18 : après « r » (ANTENNE), le choix 3 était refusé sans que la page le montre."""
    session = terrain.Session.open(tmp_path / "s", model=1)
    session.connection = "antenne"
    rows = {c["cle"]: c for c in terrain.menu_choices(session, set(), tmp_path / "s")}
    assert rows["3"]["bloque"] == rows["5"]["bloque"] == rows["8"]["bloque"] == "charge" and "bloque" not in rows["c"]
    rows = {c["cle"]: c for c in terrain.menu_choices(session, set(), tmp_path / "s", running=True)}
    assert rows["3"]["bloque"] == "station" and rows["8"]["bloque"] == "charge" and "bloque" not in rows["a"]
    session.connection = "charge"
    assert "bloque" not in {c["cle"]: c for c in terrain.menu_choices(session, set(), tmp_path / "s")}["3"]
    bus = Bus()
    answers = iter(["3", "q"])
    bus.subscribe(lambda e: bus.answer(e["id"], next(answers), source=SOURCE_KEYBOARD) if e["type"] == "question" else None)
    seen = []
    bus.subscribe(lambda e: seen.append(e) if e["type"] == "avis" else None)
    terrain.run_terrain(_cfg(tmp_path), PROFILE, "", tmp_path, session_dir=tmp_path / "s", bus=bus,
                        station=lambda: False, qualify=lambda no_tx: None)
    assert [e["texte"] for e in seen] == ["Émission refusée : confirme d'abord que le poste est sur la CHARGE FICTIVE (choix c)."]


def test_an_interrupted_transmission_still_gets_its_mode_back():
    """Essai réel du 2026-11-18 (IC-7300MK2) : STOP pendant l'audio d'émission = poste laissé en PKTUSB : le
    contrôleur se croyait encore en émission. Désormais : coupure (force_rx), puis le mode d'origine remis."""
    from trxstation.devtools.hwtest import HwTest

    class Ctrl:
        def __init__(self):
            self.state, self.calls = "TX", []

        def snapshot(self):
            return SimpleNamespace(state=self.state)

        async def force_rx(self, reason, by=None):
            self.calls.append("force_rx")
            self.state = "RX"

        async def set_mode(self, mode):
            self.calls.append(f"set_mode {mode}")
            hw.link.state.mode = mode
    said = []
    hw = HwTest.__new__(HwTest)
    hw.ctrl, hw.say, hw._mode_to_restore = Ctrl(), said.append, "USB"
    hw.link = SimpleNamespace(state=SimpleNamespace(mode="PKTUSB"))
    asyncio.run(hw._restore_mode())
    assert hw.ctrl.calls == ["force_rx", "set_mode USB"] and any("USB" in s for s in said)


def test_every_hand_played_test_has_its_card_in_both_languages():
    """Demande de l'utilisateur (2026-11-19) : « Nous testons maintenant… pour… », étapes, résultat attendu."""
    fr, en = load_texts("fr"), load_texts("en")
    for drill in terrain.DRILLS:
        for lang in (fr, en):
            assert lang[f"drill.{drill.id}.but"] and lang[f"drill.{drill.id}.expected"]
            assert isinstance(lang[f"drill.{drill.id}.steps"], list) and lang[f"drill.{drill.id}.steps"]
            if drill.kind in terrain.NEEDS_MARK:                     # un repère = un gros bouton qui le dit
                assert lang[f"drill.{drill.id}.mark"]


def test_the_station_stop_button_only_stops_and_needs_the_session():
    stopped = []

    async def body(bus, page, client):
        page.stop_station = lambda: stopped.append(1) or 0
        assert (await client.post("/api/station_stop")).status == 403
        origin = await login(page, client)
        r = await client.post("/api/station_stop", headers=origin)
        assert (await r.json()) == {"ok": True} and stopped == [1]
    scenario(body)


def test_hand_played_questions_tell_the_page_which_test_and_step(tmp_path):
    bus = Bus()
    seen = []

    def client(event):
        if event["type"] == "question":
            seen.append(event)
            bus.answer(event["id"], "", source=SOURCE_KEYBOARD)
    bus.subscribe(client)

    class Unreadable(terrain.Observer):
        async def read_once(self):
            return None
    original = terrain.Observer
    terrain.Observer = Unreadable
    try:
        session = terrain.Session.open(tmp_path / "s", model=1)
        asyncio.run(terrain.play_drill(terrain.DRILLS[0], session, host="127.0.0.1", port=1, tot_s=20,
                                       state_dir=tmp_path, ask=bus.ask, out=bus.out))
    finally:
        terrain.Observer = original
    assert seen[0]["role"] == "essai:stop_page:stop:debut" and seen[0]["genre"] == "choix"


def test_open_report_shows_only_the_last_report_built(tmp_path, monkeypatch):
    import subprocess
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: opened.append(cmd))
    zip_path = tmp_path / "terrain.zip"
    zip_path.write_bytes(b"PK")

    async def body(bus, page, client):
        origin = await login(page, client)
        assert (await (await client.post("/api/open_report", headers=origin)).json()) == {"ok": False}
        bus.publish("rapport", chemin=str(zip_path))
        await until(lambda: page.report)
        assert (await (await client.post("/api/open_report", headers=origin)).json()) == {"ok": True}
        assert str(zip_path) in " ".join(opened[0])
    scenario(body)
