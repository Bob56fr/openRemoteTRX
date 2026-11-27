# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Pages de secours (étape 405) : station mise en sécurité, console web désactivée, aucun compte."""
from __future__ import annotations

import http.client
import json
import socket
import ssl
from pathlib import Path

from trxstation import config as cfgmod
from trxstation.console import menu_number
from trxstation.fallback_page import (CODES, KINDS, MENUS, FallbackServer, json_body, pick_lang, port_answers,
                                      render, texts)
from trxstation.i18n import LANGS, catalog
from trxstation.setup_wizard import dummy_config
from trxstation.supervisor.fallback import RETRY_S, FallbackPages


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(port: int, method: str = "GET", path: str = "/", lang: str = "fr", tls: bool = False):
    if tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=ctx)
    else:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=b"{}" if method == "POST" else None,
                     headers={"Accept-Language": lang, "Content-Type": "application/json"})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read().decode("utf-8")
    finally:
        conn.close()


def test_every_language_has_the_same_texts_and_every_menu_number_is_the_console_one():
    keys = set(catalog("fr", "fallback"))
    assert keys and all(set(catalog(lang, "fallback")) == keys for lang in LANGS)
    assert MENUS == {name: menu_number(name) for name in MENUS}
    for kind in KINDS:
        for lang in LANGS:
            t = texts(kind, lang)
            assert all(t.values()) and not any("{" in v for v in t.values()), (kind, lang)
    assert "menu 1.4 « Réactiver la station »" in texts("safe_mode", "fr")["what"]
    assert "Menü 4.3" in texts("no_account", "de")["what"]


def test_browser_language_is_followed():
    assert pick_lang(None) == "fr" and pick_lang("de-DE,de;q=0.9,en;q=0.8") == "de"
    assert pick_lang("es") == "es" and pick_lang("it-IT,it") == "en"


def test_the_safe_mode_page_never_shows_the_detailed_cause_and_has_no_script():
    page = render("safe_mode", "fr")
    assert "Station mise en sécurité" in page and CODES["safe_mode"] in page
    assert "<script" not in page and "http://" not in page


def test_server_answers_503_with_the_page_the_json_and_frees_its_port(tmp_path):
    port = free_port()
    server = FallbackServer("safe_mode", "127.0.0.1", port)
    assert server.start()
    try:
        assert not FallbackServer("safe_mode", "127.0.0.1", port).start()     # port pris : refus sans exception
        status, headers, body = request(port, lang="en")
        assert status == 503 and "Station in safety lockout" in body and headers["Retry-After"] == "60"
        assert "default-src 'none'" in headers["Content-Security-Policy"] and headers["Cache-Control"] == "no-store"
        status, _, body = request(port, path="/safe-mode.json")
        assert status == 503 and json.loads(body)["error"] == "safe_mode" and json.loads(body)["code"] == "ORT-8008"
        status, _, body = request(port, method="POST", path="/offer", lang="es")       # page et application
        data = json.loads(body)
        assert status == 503 and data["error"] == "safe_mode" and "bloqueo de seguridad" in data["message"]
        assert request(port, method="HEAD")[0] == 503
    finally:
        server.stop()
    assert not port_answers("127.0.0.1", port)
    again = FallbackServer("console_off", "127.0.0.1", port)                 # port vraiment libéré
    assert again.start()
    again.stop()


def test_server_speaks_tls_with_the_station_certificate(tmp_path):
    from trxstation.setup_wizard import _make_certificate
    cfg = dummy_config()
    _make_certificate(["127.0.0.1"], tmp_path, cfg)
    port = free_port()
    server = FallbackServer("console_off", "127.0.0.1", port, cfg.network.tls_cert, cfg.network.tls_key)
    assert server.start()
    try:
        status, _, body = request(port, tls=True, lang="de")
        assert status == 503 and "Web-Konsole deaktiviert" in body and "Menü 4.6" in body
    finally:
        server.stop()
    assert not FallbackServer("console_off", "127.0.0.1", port, str(tmp_path / "absent.pem")).start()


class FakeServer:
    made: list["FakeServer"] = []
    busy: set[int] = set()

    def __init__(self, kind, host, port, cert="", key=""):
        self.kind, self.host, self.port, self.cert, self.running = kind, host, port, cert, False
        FakeServer.made.append(self)

    def start(self):
        self.running = self.port not in FakeServer.busy
        return self.running

    def stop(self):
        self.running = False


def network_config(tmp_path, *, console=False) -> tuple[cfgmod.Config, Path]:
    cfg = dummy_config()
    cfg.network.gateway_bind = "0.0.0.0"
    cfg.network.tls_cert, cfg.network.tls_key = "cert.pem", "key.pem"
    cfg.remote_console.enabled = console
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return cfg, path


def test_supervisor_serves_the_safe_mode_page_only_during_the_lockout_and_follows_the_console_switch(tmp_path):
    FakeServer.made.clear()
    FakeServer.busy.clear()
    safe: list[str | None] = [None]
    now = [0.0]
    cfg, path = network_config(tmp_path)
    pages = FallbackPages(cfg, path, lambda: safe[0], clock=lambda: now[0], factory=FakeServer)
    pages.sync()
    assert pages.serving() == {"console_off"}                     # console désactivée : page sur 8444
    assert FakeServer.made[0].port == 8444 and FakeServer.made[0].cert == "cert.pem"
    safe[0] = "ORT-8008 passerelle muette"
    pages.sync()
    assert pages.serving() == {"console_off", "safe_mode"}
    page = next(s for s in FakeServer.made if s.kind == "safe_mode")
    assert (page.host, page.port) == ("0.0.0.0", 8443)
    safe[0] = None                                                # menu 1.4 : port rendu tout de suite
    pages.sync()
    assert pages.serving() == {"console_off"} and not page.running
    network_config(tmp_path, console=True)                        # menu 4.6 : console activée, superviseur pas relancé
    import os
    os.utime(path, (1_000_000_000, 1_000_000_000))
    pages.sync()
    assert pages.serving() == set()


def test_a_busy_port_is_retried_later_and_a_local_station_gets_no_console_page(tmp_path):
    FakeServer.made.clear()
    FakeServer.busy = {8444}
    now = [0.0]
    cfg, path = network_config(tmp_path)
    pages = FallbackPages(cfg, path, lambda: None, clock=lambda: now[0], factory=FakeServer)
    pages.sync()
    pages.sync()
    assert pages.serving() == set() and len(FakeServer.made) == 1         # pas un essai par tour
    FakeServer.busy.clear()
    now[0] = RETRY_S + 1
    pages.sync()
    assert pages.serving() == {"console_off"}
    FakeServer.made.clear()
    local = dummy_config()                                         # 127.0.0.1 sans TLS : mise en sécurité seulement
    pages = FallbackPages(local, None, lambda: "x", factory=FakeServer)
    pages.sync()
    assert pages.serving() == {"safe_mode"} and FakeServer.made[0].cert == ""


def test_gateway_without_any_account_serves_the_no_account_page():
    from trxstation.gateway import main as gw
    cfg = dummy_config()
    cfg.clients = []
    cfg.network.gateway_bind, cfg.network.gateway_port = "127.0.0.1", free_port()
    gw._no_account_page(cfg)
    try:
        status, _, body = request(cfg.network.gateway_port)
        assert status == 503 and "Aucun compte sur cette station" in body and "menu 4.3" in body
    finally:
        while gw._FALLBACK:
            gw._FALLBACK.pop().stop()


def test_clear_safe_mode_waits_for_the_port_to_be_released():
    from trxstation.supervisor.main import _wait_fallback_released
    cfg = dummy_config()
    cfg.network.gateway_bind, cfg.network.gateway_port = "127.0.0.1", free_port()
    server = FallbackServer("safe_mode", "127.0.0.1", cfg.network.gateway_port)
    assert server.start()
    import threading
    threading.Timer(0.3, server.stop).start()
    _wait_fallback_released(cfg, timeout_s=3.0)
    assert not port_answers("127.0.0.1", cfg.network.gateway_port)
    assert json_body("no_account", "fr")["code"] == "ORT-9710"
