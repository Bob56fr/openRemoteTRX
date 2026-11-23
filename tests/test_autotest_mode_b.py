# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""openRemoteTRX-Autotest, MODE B (lot PQ5, trxstation/autotest/) : liste fermée des commandes rigctld, protections de
la page servie (jeton, Host, Origin, fichiers), garde d'émission du programme (durée maximale, page muette, arrêt),
rigctld qui tombe. Faux rigctld de devtools ; essai avec le poste factice de Hamlib (modèle 1) si Hamlib est là."""
from __future__ import annotations

import asyncio
import socket

import pytest
from aiohttp.test_utils import TestClient, TestServer

from trxstation.autotest import rig as rg
from trxstation.autotest import server as sv
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.hamlib import find_tool


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_closed_list_of_rigctld_commands() -> None:
    ok = {"f": "f", "m": "m", "t": "t", "l STRENGTH": "l STRENGTH", "u NB": "u NB", "u VOX": "u VOX",
          "F 7074000": "F 7074000", "M PKTUSB 0": "M PKTUSB 0", "T 1": "T 1", "T 0": "T 0", "U NR 1": "U NR 1",
          "L RFPOWER 0.1": "L RFPOWER 0.1", "L ATT 20": "L ATT 20", "L NR 0.4": "L NR 0.4", "G XCHG": "G XCHG"}
    for line, norm in ok.items():
        assert rg.check_command(line) == norm, line
    for line in ("U VOX 1", "U TUNER 1", "U XIT 1", "S 1 VFOB", "I 7100000", "M USB 2400", "M usb 0", "T 2",
                 "L RFPOWER 1.5", "L ATT 2.5", "L VOXGAIN 0.5", "W \\0xFE 1", "\\set_powerstat 0", "F 5", "F 7e6",
                 "G TUNE", "l STRENGTH x", "", "f;T 1", "L RFPOWER nan", None, "x" * 80):
        assert rg.check_command(line) is None, line


def test_reply_of_the_extended_protocol() -> None:
    assert rg.parse_reply("get_freq:\nFrequency: 7074000\nRPRT 0\n") == (0, ["7074000"])
    assert rg.parse_reply("get_mode:\nMode: USB\nPassband: 2400\nRPRT 0\n") == (0, ["USB", "2400"])
    assert rg.parse_reply("set_level: RFPOWER 0.1\nRPRT 0\n") == (0, [])
    assert rg.parse_reply("RPRT -11\n") == (-11, [])


def test_rig_settings_are_checked() -> None:
    assert rg.RigSettings(3094, "COM8", 115200).problems() == []
    assert rg.RigSettings(1).problems() == []                                     # poste factice : aucun port
    assert rg.RigSettings(3094, "").problems() == ["port"]
    assert rg.RigSettings(3094, "COM8 -C x").problems() == ["port"]
    assert rg.RigSettings(3094, "/dev/ttyUSB0", 1234).problems() == ["vitesse"]
    args = rg.RigSettings(3094, "COM8", 19200).args("rigctld", 4600)
    assert args[:7] == ["rigctld", "-m", "3094", "-T", "127.0.0.1", "-t", "4600"] and args[-2:] == ["-C", "cache_timeout=0"]


def test_page_of_mode_b_allows_only_its_own_api() -> None:
    html = (sv.default_web_dir() / "index.html").read_text(encoding="utf-8")
    page = sv.page_for_mode_b(html)
    assert "connect-src 'self'" in page and "connect-src 'none'" not in page and sv.MODE_META in page
    assert "connect-src 'none'" in html                                          # la page publiée (mode A) reste fermée


class FakeLinkedRigctld(rg.Rigctld):
    """Rigctld branché sur le faux rigctld (aucun processus lancé)."""
    fake_port = 0

    async def start(self) -> None:
        self.tcp_port = self.fake_port
        self._reader, self._writer = await asyncio.open_connection("127.0.0.1", self.tcp_port)

    def alive(self) -> bool:
        return True

    async def stop(self) -> None:
        self._close_link()


def scenario(body):
    async def run():
        fake = FakeRigctld()
        port = await fake.start(0)
        FakeLinkedRigctld.fake_port = port
        now = [100.0]
        server = sv.AutotestServer(port=free_port(), rigctld_factory=lambda s: FakeLinkedRigctld(s),
                                   clock=lambda: now[0])
        try:
            async with TestClient(TestServer(server.app(), host="127.0.0.1", port=server.port)) as client:
                await body(server, client, fake, now)
        finally:
            await fake.stop()
    asyncio.run(run())


async def login(server, client) -> dict:
    r = await client.get(f"/?t={server.token}", allow_redirects=False)
    assert r.status == 302 and sv.COOKIE in r.cookies
    return {"Origin": f"http://127.0.0.1:{server.port}"}


def test_token_cookie_host_origin_and_closed_list_of_files() -> None:
    async def body(server, client, fake, now):
        assert (await client.get("/")).status == 403                              # sans session
        assert (await client.get("/app.js")).status == 403
        token = server.token
        h = await login(server, client)
        assert (await client.get(f"/?t={token}", allow_redirects=False)).status == 403       # jeton à usage unique
        r = await client.get("/")
        page = await r.text()
        assert r.status == 200 and sv.MODE_META in page and "connect-src 'self'" in r.headers["Content-Security-Policy"]
        assert (await client.get("/hamlib.js")).status == 200
        for bad in ("/station.toml", "/..%2Fserve.py", "/index.html"):
            assert (await client.get(bad)).status == 404, bad
        assert (await client.post("/api/cmd", json={"c": "f"})).status == 403    # POST sans Origin
        assert (await client.post("/api/cmd", json={"c": "f"}, headers={"Origin": "http://evil.example"})).status == 403
        assert (await client.get("/", headers={"Host": "evil.example"})).status == 403       # DNS rebinding
        assert (await client.post("/api/cmd", json={"c": "f"}, headers=h)).status == 409     # pas encore connecté
    scenario(body)


def test_connect_then_only_the_closed_list_reaches_rigctld() -> None:
    async def body(server, client, fake, now):
        h = await login(server, client)
        bad = await client.post("/api/connect", json={"modele": 3094, "port": "COM8 ; rm"}, headers=h)
        assert bad.status == 400
        r = await (await client.post("/api/connect", json={"modele": 1, "port": ""}, headers=h)).json()
        assert r["ok"] is True
        got = await (await client.post("/api/cmd", json={"c": "f"}, headers=h)).json()
        assert got["rprt"] == 0 and got["valeurs"] == [str(fake.freq)]
        before = list(fake.commands)
        for line in ("U VOX 1", "M USB 2400", "S 1 VFOB", "\\set_powerstat 0"):
            assert (await client.post("/api/cmd", json={"c": line}, headers=h)).status == 400, line
        assert fake.commands == before                                           # rien n'est arrivé au poste
        await client.post("/api/cmd", json={"c": "L RFPOWER 0.1"}, headers=h)
        assert fake.levels["RFPOWER"] == pytest.approx(0.1)
    scenario(body)


def test_transmit_guard_of_the_program_cuts_a_long_or_orphan_transmission() -> None:
    async def body(server, client, fake, now):
        h = await login(server, client)
        await client.post("/api/connect", json={"modele": 1}, headers=h)
        # Page muette pendant une émission : « T 0 » après SILENCE_S.
        await client.post("/api/cmd", json={"c": "T 1"}, headers=h)
        assert fake.ptt == 1 and server.tx_since is not None
        now[0] += sv.SILENCE_S - 0.5
        assert await server.check_tx() is None and fake.ptt == 1
        now[0] += 1.0
        assert await server.check_tx() == "page_muette" and fake.ptt == 0 and server.tx_since is None
        # Page qui parle sans cesse mais émission trop longue : « T 0 » après MAX_TX_S.
        await client.post("/api/cmd", json={"c": "T 1"}, headers=h)
        for _ in range(int(sv.MAX_TX_S) + 2):
            now[0] += 1.0
            await client.post("/api/cmd", json={"c": "l RFPOWER_METER"}, headers=h)
            if await server.check_tx():
                break
        assert fake.ptt == 0 and [c["raison"] for c in server.cuts] == ["page_muette", "duree_max"]
        assert all(c["rx"] for c in server.cuts)
        # STOP de la page : « T 0 » par une connexion à part.
        await client.post("/api/cmd", json={"c": "T 1"}, headers=h)
        stop = await (await client.post("/api/ptt_off", headers=h)).json()
        assert stop["rx"] is True and fake.ptt == 0
        # détail rendu pour la trace du rapport (étape 374) : l'ordre puis la relecture du PTT
        assert [(s["h"], s["rprt"]) for s in stop["trace"]] == [("T 0", 0), ("t", 0)]
        assert stop["trace"][1]["valeurs"] == ["0"] and server.tx_since is None
        # Déconnexion pendant une émission : « T 0 » d'abord.
        await client.post("/api/cmd", json={"c": "T 1"}, headers=h)
        await client.post("/api/disconnect", headers=h)
        assert fake.ptt == 0 and server.rig is None
    scenario(body)


def test_program_stop_sends_t0_first() -> None:
    async def run():
        fake = FakeRigctld()
        FakeLinkedRigctld.fake_port = await fake.start(0)
        server = sv.AutotestServer(port=free_port(), rigctld_factory=lambda s: FakeLinkedRigctld(s))
        async with TestClient(TestServer(server.app(), host="127.0.0.1", port=server.port)) as client:
            h = await login(server, client)
            await client.post("/api/connect", json={"modele": 1}, headers=h)
            await client.post("/api/cmd", json={"c": "T 1"}, headers=h)
            assert fake.ptt == 1
        assert fake.ptt == 0                                                      # arrêt du programme : réception
        await fake.stop()
    asyncio.run(run())


def test_timeout_and_lost_rigctld_give_an_error_not_a_crash() -> None:
    async def run():
        fake = FakeRigctld()
        port = await fake.start(0)
        link = FakeLinkedRigctld(rg.RigSettings(1), timeout_s=0.3)
        FakeLinkedRigctld.fake_port = port
        await link.start()
        fake.slow = {"l STRENGTH": 1.0}
        assert (await link.query("l STRENGTH"))["erreur"] == "delai"
        fake.slow = {}
        await asyncio.sleep(1.0)
        assert (await link.query("f"))["rprt"] == 0                               # liaison rouverte
        fake.drop_connections()                                                   # rigctld referme la connexion
        await asyncio.sleep(0.1)
        first = await link.query("f")
        assert first.get("rprt") == 0 or first["erreur"] == "liaison"
        assert (await link.query("f"))["rprt"] == 0
        await link.stop()
        await fake.stop()
    asyncio.run(run())


@pytest.mark.skipif(find_tool("rigctld") is None, reason="Hamlib absent")
def test_real_rigctld_with_the_dummy_rig() -> None:
    """Le vrai rigctld (poste factice, modèle 1) : lancé sur un port libre, lu, émission coupée par la connexion à
    part, arrêté."""
    async def run():
        link = rg.Rigctld(rg.RigSettings(1))
        await link.start()
        try:
            assert (await link.query("f"))["rprt"] == 0
            assert (await link.query("T 1"))["rprt"] == 0
            assert await link.ptt_off() is True
            assert (await link.query("T 1"))["rprt"] == 0
            detail = await link.ptt_off_detail()
            assert detail["rx"] is True and [s["h"] for s in detail["trace"]] == ["T 0", "t"]
            assert (await link.query("t"))["valeurs"] == ["0"]
        finally:
            await link.stop()
        assert not link.alive()
    asyncio.run(run())
