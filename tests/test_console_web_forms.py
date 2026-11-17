# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Menus en formulaires (étape 235) : questions reconnues, menu joué sans terminal par le worker, commandes et sudo
(mot de passe jamais montré ni gardé ailleurs qu'en mémoire), serveur (un menu à la fois, mot de passe de la
session redonné sans le redemander, oublié à la fermeture)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time

from aiohttp.test_utils import TestClient, TestServer

from trxstation.console_web import worker
from trxstation.console_web.server import TERMINAL_MENUS
from trxstation.console_web.worker import Channel, Inbox, WebRunner, classify

from trxstation.console_web.terminal import IDLE_MARK

from test_console_web import FakeTerminal, login, make


# ---------------------------------------------------------------- questions reconnues

def test_choices_come_from_the_lines_said_just_before_or_from_the_prompt():
    form = classify("Choix (r = retour) : ", [(1, "Titre"), (2, "  1) Démarrer\n  2) Arrêter")], None)
    assert form["kind"] == "choice" and form["choices"] == [["1", "Démarrer"], ["2", "Arrêter"]]
    assert form["hide"] == [2] and form["extra"] == [["r", "retour"]]
    form = classify("\n  1) Réglages\n  2) Créer\nChoix (Entrée = retour) : ", [], None)
    assert form["choices"] == [["1", "Réglages"], ["2", "Créer"]] and form["extra"] == [["", "retour"]]
    form = classify("Nom ? ", [(4, "Titre\n  a) x\n  b) y")], None)
    assert form["rewrite"] == [[4, "Titre"]] and [c[0] for c in form["choices"]] == ["a", "b"]
    form = classify("Adresse du serveur : ", [(5, "Une phrase sans choix.")], None)
    assert form["kind"] == "text" and form["choices"] == []


def test_the_menu_tells_the_nature_of_its_question():
    form = classify("TOT (30 à 120, Entrée = 90) : ", [(1, "  1) x")], {"kind": "int", "low": 30, "high": 120,
                                                                         "current": 90})
    assert form["kind"] == "int" and form["low"] == 30 and form["choices"] == [] and form["extra"] == []
    form = classify("Tape EFFACER (Entrée = non) : ", [], {"kind": "word", "word": "EFFACER"})
    assert form["kind"] == "word" and form["word"] == "EFFACER" and form["extra"] == []


def test_console_helpers_set_the_hint_and_the_terminal_ignores_it(tmp_path):
    from trxstation.console import Console
    seen = []

    def ask(prompt):
        seen.append(con.hint)
        return ""
    con = Console(tmp_path / "station.toml", ask=ask, say=lambda _t: None)
    con._ask_int("TOT", 90, 30, 120)
    con.yes("Sûr ?", False)
    con._ask_new_password("bob")
    con.pause()
    kinds = [h["kind"] for h in seen]
    assert kinds == ["int", "yesno", "password", "pause"] and seen[0]["high"] == 120 and seen[1]["default"] is False


# ---------------------------------------------------------------- worker (vrai processus)

def run_worker(tmp_path, key, answers, timeout=60):
    from trxstation.config import render_toml
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    path = tmp_path / "station.toml"
    path.write_text(render_toml(cfg), encoding="utf-8")
    env = dict(os.environ, APPDATA=str(tmp_path / "appdata"), HOME=str(tmp_path / "home"), PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "trxstation.console_web.worker", "--config", str(path), "--key", key],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    events, pending = [], list(answers)
    deadline = time.monotonic() + timeout
    for line in proc.stdout:
        ev = json.loads(line)
        events.append(ev)
        if ev["type"] == "form":
            proc.stdin.write((json.dumps({"type": "answer", "value": pending.pop(0) if pending else ""}) + "\n").encode())
            proc.stdin.flush()
        if ev["type"] == "done" or time.monotonic() > deadline:
            break
    proc.stdin.close()
    proc.wait(timeout=20)
    return events, proc.stderr.read().decode("utf-8", "replace")


def test_worker_plays_the_language_menu_without_a_terminal(tmp_path):
    events, errors = run_worker(tmp_path, "0", ["2", "3"])
    forms = [e for e in events if e["type"] == "form"]
    assert [f["kind"] for f in forms] == ["choice", "choice"] and len(forms[0]["choices"]) == 4
    assert events[-1] == {"type": "done", "code": 0, "id": events[-1]["id"]}
    assert "Fatal" not in errors and "Traceback" not in errors                      # fin nette (os._exit)
    prefs = next((tmp_path / "appdata").rglob("console.json"), None) or next((tmp_path / "home").rglob("console.json"))
    assert json.loads(prefs.read_text(encoding="utf-8")) == {"lang": "en", "level": "expert"}


def test_worker_plays_a_settings_menu_with_numbers_and_yes_no(tmp_path):
    events, _ = run_worker(tmp_path, "4.2", ["1", "3", "n", "", "", "", ""])
    kinds = [e["kind"] for e in events if e["type"] == "form"]
    assert kinds[:3] == ["choice", "int", "yesno"] and events[-1]["type"] == "done"


# ---------------------------------------------------------------- commandes et sudo

FAKE_SUDO = r'''
import subprocess, sys
line = sys.stdin.readline().rstrip("\n")
if line != "secret":
    sys.exit(1)
args = sys.argv[1:]
if args == ["true"]:
    sys.exit(0)
sys.exit(subprocess.call(args))
'''


class Collect:
    def __init__(self):
        self.messages = []
        self.next_id = 0

    def send(self, message):
        self.messages.append(message)
        return len(self.messages)


def runner_with(tmp_path, passwords):
    fake = tmp_path / "fake_sudo.py"
    fake.write_text(FAKE_SUDO, encoding="utf-8")
    channel = Collect()
    runner = WebRunner(channel)
    runner.sudo, runner.use_sudo = [sys.executable, str(fake)], True
    inbox = Inbox(iter(()), runner)
    for p in passwords:
        inbox.passwords.put(p)
    runner.inbox = inbox
    return runner, channel


def test_a_command_streams_its_output_and_reads_what_the_page_types(tmp_path):
    runner, channel = runner_with(tmp_path, [])
    cmd = [sys.executable, "-c", "name = input('Nom ? '); print('Bonjour ' + name)"]
    threading.Timer(1.0, runner.feed, args=("Bob\n",)).start()
    assert runner.run(cmd) == 0
    out = "".join(m["data"] for m in channel.messages if m["type"] == "out")
    assert "Nom ?" in out and "Bonjour Bob" in out
    assert channel.messages[0]["type"] == "run" and channel.messages[-1] == {"type": "end", "code": 0}


def test_sudo_password_is_checked_asked_again_once_wrong_and_never_shown(tmp_path):
    runner, channel = runner_with(tmp_path, ["faux", "secret"])
    cmd = [sys.executable, "-c", "print('fait en administrateur')"]
    assert runner.run(cmd, admin=True) == 0 and runner.run(cmd, admin=True) == 0
    asked = [m for m in channel.messages if m["type"] == "sudo"]
    assert [m["retry"] for m in asked] == [0, 1]                   # faux, puis bon ; pas redemandé la 2e fois
    assert "secret" not in json.dumps(channel.messages) and "faux" not in json.dumps(channel.messages)
    assert sum("fait en administrateur" in m.get("data", "") for m in channel.messages) == 2


def test_sudo_refused_three_times_or_abandoned_runs_nothing(tmp_path):
    runner, channel = runner_with(tmp_path, ["a", "b", "c"])
    assert runner.run([sys.executable, "-c", "print('jamais')"], admin=True) == 1
    assert [m["type"] for m in channel.messages if m["type"].startswith("sudo")] == ["sudo"] * 3 + ["sudo_bad"]
    assert "jamais" not in json.dumps(channel.messages)
    runner, channel = runner_with(tmp_path, [""])                  # « Annuler » dans la page
    assert runner.run([sys.executable, "-c", "print('jamais')"], admin=True) == 1


# ---------------------------------------------------------------- serveur

class FakeFlow:
    made: list = []

    def __init__(self, key, label, config, on_event):
        self.key, self.label, self.on_event = key, label, on_event
        self.events, self.done, self.answers, self.passwords, self.stopped = [], False, [], [], False
        FakeFlow.made.append(self)

    @property
    def alive(self):
        return not self.done

    def summary(self):
        return {"key": self.key, "label": self.label, "done": self.done, "events": self.events}

    async def start(self):
        pass

    def record(self, ev):
        self.events.append(ev)

    def answer(self, value, label=""):
        self.answers.append(value)
        return True

    def stdin(self, data):
        pass

    def password(self, value):
        self.passwords.append(value)

    def stop(self):
        self.stopped = True
        self.done = True


def test_server_opens_menus_in_forms_one_at_a_time_and_keeps_sudo_for_the_session(tmp_path):
    async def run():
        wc = make(tmp_path)
        wc.flow_factory = FakeFlow
        server = TestServer(wc.app(), host="127.0.0.1", port=wc.port)
        async with TestClient(server) as client:
            origin = await login(wc, client)
            data = await (await client.get("/api/state")).json()
            modes = {it["key"]: it["mode"] for th in data["themes"] for it in th["items"]}
            assert modes["4.2"] == "form" and modes["1.3"] == "terminal" and {"monitor", "edit_config"} == TERMINAL_MENUS
            r = await client.post("/api/open", json={"key": "4.2"}, headers=origin)
            assert r.status == 200 and (await r.json())["mode"] == "form"
            flow = FakeFlow.made[-1]
            assert (await client.post("/api/open", json={"key": "4.3"}, headers=origin)).status == 409
            ws = await client.ws_connect("/ws", headers=origin)        # lance la console du terminal
            wc.on_output("menu" + IDLE_MARK)                              # … qui attend à son menu
            await ws.send_str(json.dumps({"type": "flow_answer", "value": "1", "label": "Réglages"}))
            flow.on_event({"type": "sudo", "retry": 0})                 # première commande d'administration
            await ws.send_str(json.dumps({"type": "flow_password", "value": "secret"}))
            await asyncio.sleep(0.2)
            flow.on_event({"type": "sudo_ok"})
            assert flow.answers == ["1"] and flow.passwords == ["secret"] and wc.sudo_password == "secret"
            assert "secret" not in json.dumps(flow.events)
            flow.done = True
            assert (await client.post("/api/open", json={"key": "4.3"}, headers=origin)).status == 200
            second = FakeFlow.made[-1]
            second.on_event({"type": "sudo", "retry": 0})               # même session : pas redemandé
            assert second.passwords == ["secret"]
            second.on_event({"type": "sudo", "retry": 1})               # changé entre-temps : oublié, redemandé
            assert wc.sudo_password is None
            await ws.send_str(json.dumps({"type": "flow_stop"}))
            await asyncio.sleep(0.2)
            assert second.stopped
            await ws.close()
    asyncio.run(run())


def test_closing_a_network_session_stops_the_menu_and_forgets_the_password(tmp_path):
    wc = make(tmp_path)
    wc.network = True
    wc.session = {"id": "x", "account": "pc", "created": 0.0, "last": 0.0}
    flow = FakeFlow("4.2", "Visiteurs", None, lambda e: None)
    wc.flow, wc.sudo_password = flow, "secret"

    async def run():
        wc.close_session("inactivité")
    asyncio.run(run())
    assert flow.stopped and wc.flow is None and wc.sudo_password is None


def test_the_page_scripts_are_served(tmp_path):
    from trxstation.console_web.server import STATIC, STATIC_FILES
    assert "flow.js" in STATIC_FILES and (STATIC / "flow.js").exists()
    assert '<script src="/static/flow.js">' in (STATIC / "index.html").read_text(encoding="utf-8")


def test_unused_imports_stay_honest():
    assert worker.CHOICE_LINE.match("  1) Démarrer") and not worker.CHOICE_LINE.match("1) collé au bord")
    assert FakeTerminal
