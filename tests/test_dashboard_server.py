# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Accès : libre en local comme sur le réseau (pas de clé, décision du 2026-11-24), Host vérifié, fichiers en liste
fermée ; règles de [dashboard] dans station.toml ; ligne de l'en-tête d'openRemoteTRX Console."""
import asyncio
import tomllib

import pytest
from aiohttp.test_utils import TestClient, TestServer

from trxstation import config
from trxstation.dashboard import server, settings


def run(coro):
    return asyncio.run(coro)


async def client_for(remote: str):
    app = server.make_app(lambda: {"ok": 1}, lambda: {"n": 0},
                          hosts=server.allowed_hosts(["127.0.0.1", "100.64.0.5"], 8450, []))

    @__import__("aiohttp").web.middleware
    async def fake_remote(request, handler):           # simule l'adresse du client
        return await handler(request.clone(remote=remote))

    app.middlewares.insert(0, fake_remote)
    c = TestClient(TestServer(app))
    await c.start_server()
    return c


async def get(remote, path, host="127.0.0.1:8450"):
    c = await client_for(remote)
    try:
        r = await c.get(path, headers={"Host": host}, allow_redirects=False)
        return r.status, r.headers, await r.text()
    finally:
        await c.close()


def test_local_is_free():
    status, headers, _ = run(get("127.0.0.1", "/api/state"))
    assert status == 200 and "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_network_is_free_without_key():
    status, headers, body = run(get("100.64.0.9", "/api/state", host="100.64.0.5:8450"))
    assert status == 200 and '"ok"' in body and "Set-Cookie" not in headers
    assert run(get("100.64.0.9", "/", host="100.64.0.5:8450"))[0] == 200
    assert run(get("100.64.0.9", "/api/state", host="evil.example"))[0] == 421


def test_host_checked():
    assert run(get("127.0.0.1", "/api/state", host="evil.example:8450"))[0] == 421


def test_closed_file_list():
    assert run(get("127.0.0.1", "/app.js"))[0] == 200
    assert run(get("127.0.0.1", "/../server.py"))[0] in (403, 404)
    assert run(get("127.0.0.1", "/server.py"))[0] == 404


def test_station_config_dashboard_rules():
    """[dashboard] de station.toml : 0.0.0.0 refusé, adresse réseau seulement avec HTTPS (ou VPN déclaré), port libre."""
    c = config.Config()
    assert config._dashboard_problems(c) == []
    c.dashboard.listen = ["127.0.0.1", "192.168.1.19"]
    assert any("HTTPS" in m for m in config._dashboard_problems(c))
    c.network.tls_cert, c.network.tls_key = "cert.pem", "key.pem"
    assert config._dashboard_problems(c) == []
    c.dashboard.listen = ["0.0.0.0"]
    assert config._dashboard_problems(c)
    c.dashboard.listen = ["127.0.0.1"]
    c.dashboard.port = c.network.gateway_port
    assert config._dashboard_problems(c)
    c.dashboard.port = 8450
    c.dashboard.rig_name = "x" * 41
    assert config._dashboard_problems(c)


def test_render_and_reload_dashboard_section():
    """Plus de liste de terminaux écrite à la main : ce sont les comptes de [[clients]]."""
    c = config.Config()
    c.dashboard.rig_name = "IC-7300MK2"
    d = tomllib.loads(config.render_toml(c))
    assert d["dashboard"]["rig_name"] == "IC-7300MK2" and d["dashboard"]["port"] == 8450
    assert "terminals" not in d["dashboard"] and not hasattr(c.dashboard, "terminals")
    _, problems = config.build({**d, "dashboard": {**d["dashboard"], "terminals": ["S25"]}})
    assert problems                                       # réglage inconnu refusé, comme partout


def test_settings_from_station(tmp_path):
    c = config.Config()
    c.supervisor.state_dir = str(tmp_path)
    c.rig.max_power_w = 100
    s = settings.from_station(c, tmp_path / "station.toml")
    assert s.history_path == tmp_path / "dashboard" / "history.json" and s.listen == ["127.0.0.1"]
    assert not hasattr(s, "access_key") and not (tmp_path / "dashboard" / "access.key").exists()
    c.dashboard.listen = ["0.0.0.0"]
    with pytest.raises(settings.SettingsError):
        settings.check(settings.from_station(c, tmp_path / "station.toml"))


def test_automatic_addresses_follow_the_control_page():
    """Étape 386 : [dashboard] listen vide = automatique, comme la page de pilotage ; jamais une adresse d'Internet."""
    c = config.Config()
    found = lambda: ["192.168.1.19", "100.64.0.7", "8.8.8.8", "169.254.3.4"]
    assert c.dashboard.listen == [] and settings.is_auto(c)
    assert settings.listen_addresses(c, found) == ["127.0.0.1"]                 # page sur la machine seule
    c.network.gateway_bind = "0.0.0.0"
    assert settings.listen_addresses(c, found) == ["127.0.0.1"]                 # sans HTTPS : rien sur le réseau
    c.network.tls_cert, c.network.tls_key = "cert.pem", "key.pem"
    assert settings.listen_addresses(c, found) == ["127.0.0.1", "192.168.1.19", "100.64.0.7"]
    c.network.gateway_bind = "100.64.0.7"                                      # page sur l'adresse du VPN seulement
    assert settings.listen_addresses(c, found) == ["127.0.0.1", "100.64.0.7"]
    c.network.gateway_bind = "0.0.0.0"
    assert settings.listen_addresses(c, lambda: 1 / 0) == ["127.0.0.1"]         # adresses introuvables
    c.dashboard.listen = ["127.0.0.1"]                                          # rempli : pris tel quel
    assert settings.listen_addresses(c, found) == ["127.0.0.1"] and not settings.is_auto(c)


def test_automatic_settings_reresolve_and_the_service_restarts_on_change(tmp_path):
    from trxstation.dashboard import app as dapp
    c = config.Config()
    c.supervisor.state_dir = str(tmp_path)
    c.network.gateway_bind, c.network.tls_cert, c.network.tls_key = "0.0.0.0", "cert.pem", "key.pem"
    addrs = ["192.168.1.19"]
    s = settings.from_station(c, tmp_path / "station.toml", lambda: list(addrs))
    assert s.listen == ["127.0.0.1", "192.168.1.19"] and s.reresolve and s.hosts   # nom de la machine accepté
    c.dashboard.listen = ["127.0.0.1"]
    assert settings.from_station(c, tmp_path / "station.toml").reresolve is None  # liste écrite : jamais relue
    d = dapp.Dashboard.__new__(dapp.Dashboard)
    d.cfg, d.save = s, lambda: None
    addrs.append("100.64.0.7")                                                  # le VPN monte après le démarrage

    async def go():
        dapp.ADDRESSES_EVERY_S, old = 0.0, dapp.ADDRESSES_EVERY_S
        try:
            await d.loop_addresses()
        finally:
            dapp.ADDRESSES_EVERY_S = old
    c.dashboard.listen = []
    with pytest.raises(dapp.AddressesChanged):
        asyncio.run(go())


def test_console_header_line():
    """Ligne « Tableau de bord Web » de l'en-tête d'openRemoteTRX Console (sous « Application Web »)."""
    from trxstation.console import dashboard_line
    assert dashboard_line(False, ["127.0.0.1", "192.168.1.19"], 8450, True) is None
    assert dashboard_line(True, ["127.0.0.1", "192.168.1.19"], 8450, True) == \
        "  Tableau de bord Web : https://192.168.1.19:8450"
    assert dashboard_line(True, ["127.0.0.1"], 8450, True) == \
        "  Tableau de bord Web : http://127.0.0.1:8450 (cette machine seulement)"
    assert dashboard_line(True, ["127.0.0.1", "fd00::5"], 8450, False).endswith("http://[fd00::5]:8450")
