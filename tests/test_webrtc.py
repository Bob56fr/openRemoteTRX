"""Bout en bout WebRTC : faux poste + passerelle complète + faux client dans un seul processus.

Ces tests ne font RIEN si aiortc / aiohttp / av ne sont pas installés (`pip install -e ".[audio]"`) :
ils n'ont pas pu être exécutés dans l'environnement où ce code a été écrit. Sur ta machine, ils
valident le transport réel (RX, TX derrière la porte du PTT, propriétaire, coupure, jeton).
"""
import asyncio
import contextlib
import io

import pytest

from trxstation.gateway.audio.devices import ClickDetectSink, ClickSource, RecordingSink, ToneSource
from trxstation.gateway.audio.pcm import rms_dbfs


def _available():
    try:
        import aiohttp, aiortc, av  # noqa: F401
        return True
    except ImportError:
        return False


async def until(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("condition jamais atteinte")
        await asyncio.sleep(0.02)


def test_webrtc_end_to_end():
    if not _available():
        return
    from trxstation.devtools.fake_client import FakeClient, ToneTrack
    from trxstation.devtools.loopback import PASSWORDS, Loopback

    async def scenario():
        sink = RecordingSink()
        async with Loopback(source=ToneSource(440.0, -10), sink=sink) as lb:
            bad = FakeClient(lb.url, "phone", "mauvais mot de passe")
            with pytest.raises(ConnectionRefusedError):                     # mot de passe refusé : aucune connexion
                await bad.connect()
            await bad.close()

            phone = FakeClient(lb.url, "phone", PASSWORDS["phone"], track=ToneTrack(1000.0, -10.0, active=True))
            await phone.connect()
            assert phone.hello["client_id"] == "phone" and phone.state is not None
            await until(lambda: phone.rx_frames >= 20, 10)                  # le son du poste arrive au client
            assert lb.pipeline.stats()["listeners"] >= 1 and len(phone.rx_loud_times) > 0

            await asyncio.sleep(0.5)
            assert sink.frames == []                                        # RX : le micro du client n'atteint pas le poste

            result = await phone.command("toggle")
            assert result["ok"] and result["ptt"]["state"] == "TX" and lb.fake.ptt == 1
            phone.start_heartbeat()
            await until(lambda: len(sink.frames) >= 20, 10)                 # TX : le micro passe la porte
            assert max(rms_dbfs(f) for f in sink.frames[-10:]) > -25

            car = FakeClient(lb.url, "car", PASSWORDS["car"], track=ToneTrack(2000.0, -10.0, active=True))
            await car.connect()
            await until(lambda: lb.pipeline.gate.dropped_not_owner > 0, 10)  # un autre client ne peut pas émettre
            assert (await car.command("toggle"))["ok"]                      # ... mais peut couper
            await until(lambda: lb.ctrl.snapshot().state == "RX" and lb.fake.ptt == 0, 5)
            count = len(sink.frames)
            await asyncio.sleep(0.4)
            assert len(sink.frames) == count                                # porte refermée : plus rien ne part

            assert (await phone.command("toggle"))["ok"] and lb.fake.ptt == 1
            await phone.close()                                             # le propriétaire disparaît
            await until(lambda: lb.ctrl.snapshot().state == "RX" and lb.fake.ptt == 0, 8)
            await car.close()
    asyncio.run(asyncio.wait_for(scenario(), 90))


def test_latency_tool_runs_and_reports_both_directions():
    if not _available():
        return
    from trxstation.devtools.latency import run

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        asyncio.run(asyncio.wait_for(run(6.0), 60))
    text = out.getvalue()
    assert "RX (poste -> client)" in text and "TX (client -> poste)" in text


def test_web_client_page_is_served_with_strict_headers():
    if not _available():
        return
    import aiohttp
    from trxstation.devtools.loopback import Loopback

    async def scenario():
        async with Loopback() as lb:
            async with aiohttp.ClientSession() as http:
                async with http.get(lb.url + "/") as r:
                    page = await r.text()
                    assert r.status == 200 and "text/html" in r.headers["Content-Type"] and "client.js" in page and "ui.js" in page and "waterfall.js" in page
                    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
                    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["Cache-Control"] == "no-store"
                for path, kind in (("/client.js", "javascript"), ("/ui.js", "javascript"), ("/waterfall.js", "javascript"), ("/splash.webp", "image"), ("/client.css", "css")):
                    async with http.get(lb.url + path) as r:
                        assert r.status == 200 and kind in r.headers["Content-Type"]
                async with http.get(lb.url + "/health") as r:
                    assert r.status == 200 and await r.json() == {"ok": True}
                async with http.get(lb.url + "/config") as r:
                    config = await r.json()
                    assert r.status == 200 and config["protocol"] == 1 and "ice_servers" in config and "rig_audio" in config
                async with http.post(lb.url + "/offer", data="pas du json") as r:
                    assert r.status == 400
                async with http.post(lb.url + "/offer", json={"client_id": "phone", "password": "faux", "sdp": "x", "type": "offer"}) as r:
                    assert r.status == 401
    asyncio.run(asyncio.wait_for(scenario(), 30))
