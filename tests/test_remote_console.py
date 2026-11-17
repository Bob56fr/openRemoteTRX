# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console sur le réseau (étape 233) : [remote_console] et `admin` des comptes, connexion d'un opérateur
ADMINISTRATEUR seulement, une session à la fois, fermée après le délai sans action, blocage après 5 échecs, adresses
publiques refusées, alerte à chaque connexion, lien de la page pour les administrateurs seulement, menu 4.6, service."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from test_api import connect, run, station
from test_console_tools import make, write_config

from trxstation import config as cfgmod
from trxstation.config import Access, ClientAuth
from trxstation.console import MENU_THEMES, menu_number
from trxstation.console_web.server import COOKIE, WebConsole, private_source
from trxstation.console_web.terminal import Terminal
from trxstation.gateway.api.access import AccessControl
from trxstation.passwords import hash_password
from trxstation.setup_wizard import dummy_config

ROOT = Path(__file__).parents[1]
HASH = hash_password("bon mot de passe 42")


class FakeTerminal(Terminal):
    made: list[FakeTerminal] = []

    def __init__(self, cmd, env, on_output, on_exit, **kw):
        super().__init__(cmd, env, on_output, on_exit)
        FakeTerminal.made.append(self)

    def start(self, loop):
        self.alive = True

    def write(self, data):
        pass

    def resize(self, rows, cols):
        pass

    def close(self):
        self.alive = False


def station_toml(tmp_path, *, enabled=True):
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    cfg.clients = [ClientAuth("pc", password_hash=HASH, admin=True), ClientAuth("s25", password_hash=HASH),
                   ClientAuth("club", password_hash=HASH, role="listener")]
    cfg.remote_console.enabled = enabled
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return path


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def scenario(tmp_path, body, **kw):
    alerts: list[tuple] = []
    clock = Clock()

    async def go():
        from trxstation.console import Console
        wc = WebConsole(station_toml(tmp_path, **kw), port=8444, network=True, idle_s=1800, clock=clock,
                        terminal_factory=FakeTerminal,
                        console_factory=lambda p: Console(p, ask=lambda _q: "", say=lambda _t: None, installed="0.178.0"),
                        notify=lambda code, **ctx: alerts.append((code, ctx)))
        server = TestServer(wc.app(), host="127.0.0.1", port=0)
        async with TestClient(server) as client:
            wc.port = server.port
            await body(wc, client, alerts, clock)
    asyncio.run(go())


def origin(wc):
    return {"Origin": f"https://127.0.0.1:{wc.port}"}


async def login(wc, client, account="pc", password="bon mot de passe 42"):
    r = await client.post("/api/login", json={"id": account, "password": password}, headers=origin(wc))
    cookie = r.cookies.get(COOKIE)
    return r, ({"Cookie": f"{COOKIE}={cookie.value}", **origin(wc)} if cookie else origin(wc))


def test_setting_and_admin_flag_are_checked_and_old_shortcut_keys_are_taken_over():
    cfg, problems = cfgmod.build({"rig": {"model": 1}, "remote_console": {"enabled": True}})
    assert any("aucun compte opérateur administrateur" in p for p in problems)
    _, problems = cfgmod.build({"rig": {"model": 1}, "clients": [{"id": "club", "password_hash": HASH, "role": "listener",
                                                                   "admin": True}]})
    assert any("visiteur ne peut pas être administrateur" in p for p in problems)
    _, problems = cfgmod.build({"rig": {"model": 1}, "remote_console": {"port": 8443}})
    assert any("déjà pris" in p for p in problems)
    cfg, problems = cfgmod.build({"rig": {"model": 1}, "remote_console": {"enabled": True, "ssh_user": "bob", "ssh_port": 22,
                                                                          "web_port": 8765}})
    assert not problems and cfg.remote_console.account == "bob" and cfg.remote_console.enabled is False   # 0.176-0.177
    cfg = dummy_config()
    cfg.clients = [ClientAuth("pc", password_hash=HASH, admin=True)]
    cfg.remote_console.enabled = True
    text = cfgmod.render_toml(cfg)
    assert "admin = true" in text and cfgmod.from_dict(__import__("tomllib").loads(text)).clients[0].admin is True


def test_only_private_addresses_reach_the_console():
    for ok in ("192.168.1.20", "10.8.0.2", "172.16.4.1", "100.101.102.103", "127.0.0.1", "::1", "fd00::5", "fe80::1",
               "::ffff:192.168.1.9"):
        assert private_source(ok), ok
    for bad in ("8.8.8.8", "2a01:e0a::1", "::ffff:8.8.8.8", "", None, "nimporte"):
        assert not private_source(bad), bad


def test_admin_operator_logs_in_and_gets_an_alert(tmp_path):
    async def body(wc, client, alerts, clock):
        assert "Connexion à TRX Console" in await (await client.get("/")).text() or (await client.get("/")).status == 200
        page = await (await client.get("/")).text()
        assert "login.js" in page                                        # pas de session : page de connexion
        r, headers = await login(wc, client)
        assert r.status == 200 and wc.session["account"] == "pc"
        assert "app.js" in await (await client.get("/", headers=headers)).text()
        state = await (await client.get("/api/state", headers=headers)).json()
        assert state["network"] is True
        assert alerts == [("ORT-4022", {"compte": "pc", "source": "127.0.0.1"})]
        set_cookie = r.headers["Set-Cookie"]
        assert "HttpOnly" in set_cookie and "Secure" in set_cookie and "SameSite=Strict" in set_cookie
    scenario(tmp_path, body)


def test_non_admin_operator_visitor_and_wrong_password_are_refused(tmp_path):
    async def body(wc, client, alerts, clock):
        for account, password in (("s25", "bon mot de passe 42"), ("club", "bon mot de passe 42"),
                                  ("pc", "mauvais"), ("inconnu", "x")):
            r, _ = await login(wc, client, account, password)
            assert r.status == 401 and wc.session is None, account
        r = await client.post("/api/login", json={"id": "pc", "password": "bon mot de passe 42"})   # sans Origin
        assert r.status == 403
        assert (await client.get("/api/state")).status == 403
        assert alerts == []
    scenario(tmp_path, body)


def test_five_failures_block_the_address_for_15_minutes(tmp_path):
    async def body(wc, client, alerts, clock):
        for _ in range(5):
            assert (await login(wc, client, "pc", "faux"))[0].status == 401
        r, _ = await login(wc, client)                                   # même le bon mot de passe : bloqué
        assert r.status == 429 and (await r.json())["blocked_min"] == 15
        assert [a[0] for a in alerts] == ["ORT-4023"]
        clock.now += 15 * 60 + 1
        assert (await login(wc, client))[0].status == 200
    scenario(tmp_path, body)


def test_session_closes_after_idle_time_and_a_new_login_replaces_the_old_one(tmp_path):
    async def body(wc, client, alerts, clock):
        r, first = await login(wc, client)
        wc.ensure_terminal()
        terminal = FakeTerminal.made[-1]
        clock.now += 1700
        wc.touch()                                                       # une action : la session reste ouverte
        clock.now += 1700
        assert (await client.get("/api/state", headers=first)).status == 200
        _, second = await login(wc, client)                              # une autre connexion : l'ancienne est fermée
        assert terminal.alive is False                                   # avec son terminal (sudo jamais hérité)
        assert (await client.get("/api/state", headers=first)).status == 403
        clock.now += 1801
        assert (await client.get("/api/state", headers=second)).status == 403      # 30 min sans action
        task = asyncio.create_task(wc.watchdog(period_s=0.01))
        await asyncio.sleep(0.05)
        wc.stop.set()
        await task
        assert wc.session is None
    scenario(tmp_path, body)


def test_console_disabled_in_station_toml_refuses_every_login(tmp_path):
    async def body(wc, client, alerts, clock):
        assert (await login(wc, client))[0].status == 401
    scenario(tmp_path, body, enabled=False)


def test_logout_closes_the_session(tmp_path):
    async def body(wc, client, alerts, clock):
        _, headers = await login(wc, client)
        assert (await client.post("/api/logout", headers=headers)).status == 200
        assert wc.session is None and (await client.get("/api/state", headers=headers)).status == 403
    scenario(tmp_path, body)


def test_hello_offers_the_link_to_administrators_only():
    async def scenario_(fake):
        async with station(fake) as st:
            st.ctrl.config.remote_console = cfgmod.RemoteConsole(enabled=True, port=8444)
            st.ctrl.config.clients = [ClientAuth("pc", password_hash="x", admin=True), ClientAuth("s25", password_hash="x"),
                                      ClientAuth("club1", password_hash="y", role="listener")]
            access = AccessControl(st.ctrl.config.clients, Access(max_listeners=1))
            access.switch.open = True
            for account in ("pc", "s25"):
                access.admit(account)
            pc, s25 = await connect(st, "pc", access=access), await connect(st, "s25", access=access)
            assert pc.of_type("hello")[0]["remote_console"] == {"port": 8444} and "remote_console" in pc.of_type("hello")[0]["features"]
            assert s25.of_type("hello")[0]["remote_console"] is None
            access.admit("club1")
            visitor = await connect(st, "club1", role="listener", access=access)
            assert visitor.of_type("hello")[0]["remote_console"] is None
    run(scenario_)


def test_network_option_of_the_console(tmp_path, monkeypatch):
    import trxstation.console as module
    import trxstation.console_web.server as server
    started = []
    monkeypatch.setattr(server, "run_network", lambda config: started.append(config.name) or 0)
    assert module.main(["--config", str(tmp_path / "station.toml"), "--reseau"]) == 0
    assert started == ["station.toml"]


def test_service_refuses_to_start_without_certificate(tmp_path):
    from trxstation.console_web.server import run_network
    path = station_toml(tmp_path)
    assert run_network(path) == 2                                        # dummy_config : pas de tls_cert


def test_menu_4_6_is_last_of_the_access_theme():
    assert dict((n, m) for n, _k, m in MENU_THEMES)["4"][-1] == "remote_console"
    assert menu_number("remote_console") == "4.6"


def test_menu_marks_administrators_and_starts_the_service(tmp_path):
    path = write_config(tmp_path)
    cfg = cfgmod.load(path)
    cfg.clients = [ClientAuth("pc", password_hash=HASH), ClientAuth("s25", password_hash=HASH)]
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    import trxstation.console as module
    windows = module.IS_WINDOWS
    answers = ["o", "9", "", "1"] + ([] if windows else ["bob"]) + ["o", "n"]   # n : pas de redémarrage
    con, fake, out = make(tmp_path, answers=answers)
    con.remote_console()
    cfg = cfgmod.load(path)
    assert cfg.remote_console.enabled is True and [c.admin for c in cfg.clients] == [True, False]
    text = "\n".join(out)
    assert "Réponse refusée" in text and "au moins un compte administrateur" in text and ":8444/" in text
    if not windows:
        assert cfg.remote_console.account == "bob"
        assert ["systemctl", "restart", "trx-console-web@bob"] in [c[-3:] for c in fake.admin_commands()]


def test_systemd_unit_runs_the_console_under_the_chosen_account_never_root():
    unit = (ROOT / "systemd" / "trx-console-web@.service").read_text(encoding="utf-8")
    assert "User=%i" in unit and "--reseau" in unit and "SupplementaryGroups=trx" in unit
    assert "RestartPreventExitStatus=2" in unit
    install = (ROOT / "debian" / "install.sh").read_text(encoding="utf-8")
    assert "trx-console-web@.service" in install and "--on-active=30" in install   # jamais relancée en pleine installation


def test_windows_supervisor_starts_the_console_when_enabled():
    from trxstation.supervisor.backends import ManagedBackend
    cfg = dummy_config()
    assert "console_web" not in ManagedBackend(cfg).children
    cfg.remote_console.enabled = True
    backend = ManagedBackend(cfg, config_path="station.toml")
    assert backend._command("console_web")[-3:] == ["--reseau", "--config", "station.toml"]
