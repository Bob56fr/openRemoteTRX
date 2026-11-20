# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lecture complète d'une grande réponse HTTP (défaut du 2026-11-19 : boîte du monitoring de 177 ko coupée)."""
from __future__ import annotations

import asyncio
import json

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web  # noqa: E402

from trxstation.httpread import read_capped  # noqa: E402
from trxstation.monlink.identity import Identity  # noqa: E402
from trxstation.monlink.relay import HttpRelay, RelayUnavailable  # noqa: E402

BIG = {"msgs": [{"id": i, "msg": {"b": "x" * 4000}} for i in range(45)], "more": False}   # ≈ 180 ko


async def _serve(payload: bytes):
    async def handler(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "application/json"})
        await resp.prepare(request)
        for i in range(0, len(payload), 8192):           # par morceaux, comme le relais derrière TLS
            await resp.write(payload[i:i + 8192])
            await asyncio.sleep(0.002)
        await resp.write_eof()
        return resp

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def test_a_large_chunked_reply_is_read_entirely() -> None:
    payload = json.dumps(BIG).encode()

    async def run():
        runner, url = await _serve(payload)
        try:
            async with aiohttp.ClientSession() as s, s.get(url + "/") as resp:
                return await read_capped(resp.content, 1024 * 1024)
        finally:
            await runner.cleanup()

    assert asyncio.run(run()) == payload


def test_a_reply_over_the_cap_is_reported_too_large() -> None:
    payload = b"a" * 50_000

    async def run():
        runner, url = await _serve(payload)
        try:
            async with aiohttp.ClientSession() as s, s.get(url + "/") as resp:
                return await read_capped(resp.content, 20_000)
        finally:
            await runner.cleanup()

    assert len(asyncio.run(run())) > 20_000


def test_the_monitoring_relay_reads_a_large_mailbox() -> None:
    payload = json.dumps(BIG).encode()

    async def run():
        runner, url = await _serve(payload)
        relay = HttpRelay(url + "/orx-relay/public", Identity.generate())
        try:
            return await relay.call("get", {"after": 0})
        finally:
            await relay.close()
            await runner.cleanup()

    try:
        reply = asyncio.run(run())
    except RelayUnavailable as exc:                       # avant la correction : « réponse illisible (HTTP 200) »
        pytest.fail(str(exc))
    assert len(reply["msgs"]) == 45
