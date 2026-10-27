# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mesure de latence audio en boucle locale : `python -m trxstation.devtools.latency [--seconds 12]`.

  RX : salve générée côté « poste » -> arrivée dans le faux client (capture, Opus, WebRTC).
  TX : salve générée par le faux client -> arrivée au puits du « poste » (porte d'émission).
Résolution de l'ordre d'une trame (20 ms). Sur une vraie liaison, ajoute la latence réseau
et celle de la carte son. Nécessite aiortc et aiohttp.
"""
from __future__ import annotations

import argparse
import asyncio

from ..gateway.audio.devices import ClickDetectSink, ClickSource
from ..asyncio_noise import install_quiet_handler
from .fake_client import ClickTrack, FakeClient
from .latency_math import describe, latencies
from .loopback import PASSWORDS, Loopback


async def run(seconds: float) -> None:
    install_quiet_handler(asyncio.get_running_loop())
    source, sink, track = ClickSource(1.0), ClickDetectSink(), ClickTrack(1.0)
    async with Loopback(source=source, sink=sink) as lb:
        client = FakeClient(lb.url, "phone", PASSWORDS["phone"], track=track)
        await client.connect()
        await asyncio.sleep(seconds / 2)
        print(describe("RX (poste -> client)", latencies(source.click_times, client.rx_loud_times)))
        result = await client.command("toggle")
        if not result.get("ok"):
            print("prise d'émission refusée :", result)
            await client.close()
            return
        client.start_heartbeat()
        await asyncio.sleep(seconds / 2)
        print(describe("TX (client -> poste)", latencies(track.click_times, sink.click_times)))
        await client.command("toggle")
        await client.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=12.0)
    asyncio.run(run(ap.parse_args().seconds))


if __name__ == "__main__":
    main()
