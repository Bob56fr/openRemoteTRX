# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Charge des visiteurs sur la passerelle (docs/visiteurs-cahier-des-charges.md § 10) :
`python -m trxstation.devtools.listener_load [--listeners 5] [--seconds 10]`.

La passerelle complète (faux poste, audio, WebRTC) tourne dans CE processus ; l'opérateur et les visiteurs sont des
faux clients dans un AUTRE processus, pour que leur décodage ne compte pas. Mesures : temps processeur de la
passerelle (en % d'un cœur) avec l'opérateur seul, puis avec N visiteurs, et le pire retard de sa boucle asyncio.
Sert à décider si l'encodage Opus partagé (écarté au § 12) devient nécessaire. Nécessite aiortc et aiohttp.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

from ..asyncio_noise import install_quiet_handler
from ..config import Access


async def _loop_lag(stop: asyncio.Event, out: list[float]) -> None:
    """Pire retard d'un réveil de 20 ms (la boucle qui surveille aussi l'émission)."""
    worst = 0.0
    while not stop.is_set():
        start = time.perf_counter()
        await asyncio.sleep(0.02)
        worst = max(worst, time.perf_counter() - start - 0.02)
    out.append(worst)


async def _measure(seconds: float) -> tuple[float, float]:
    stop, lag = asyncio.Event(), []
    task = asyncio.ensure_future(_loop_lag(stop, lag))
    cpu, wall = time.process_time(), time.perf_counter()
    await asyncio.sleep(seconds)
    cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
    stop.set()
    await task
    return 100.0 * cpu / wall, 1000.0 * lag[0]


async def gateway(listeners: int, seconds: float) -> None:
    from .loopback import Loopback
    install_quiet_handler(asyncio.get_running_loop())
    async with Loopback(access=Access(max_listeners=max(1, listeners), listeners_need_operator=False),
                        listeners=listeners) as lb:
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "trxstation.devtools.listener_load", "--clients", lb.url, "--listeners", str(listeners),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        try:
            assert (await child.stdout.readline()).strip() == b"operator", "opérateur non connecté"
            await asyncio.sleep(2)
            alone = await _measure(seconds)
            child.stdin.write(b"go\n")
            await child.stdin.drain()
            assert (await child.stdout.readline()).strip() == b"listeners", "visiteurs non connectés"
            await asyncio.sleep(2)
            loaded = await _measure(seconds)
            print(f"Opérateur seul           : processeur {alone[0]:5.1f} % d'un cœur, pire retard de la boucle {alone[1]:5.1f} ms")
            print(f"+ {listeners} visiteur(s)           : processeur {loaded[0]:5.1f} % d'un cœur, pire retard de la boucle {loaded[1]:5.1f} ms")
            if listeners:
                print(f"Coût d'un visiteur        : {(loaded[0] - alone[0]) / listeners:5.1f} % d'un cœur "
                      f"(peers connectés : {len(lb.manager.listener_ids())})")
        finally:
            if child.returncode is None:
                child.kill()
            await child.wait()


async def clients(url: str, listeners: int) -> None:
    from .fake_client import FakeClient
    from .loopback import PASSWORDS, listener_password
    install_quiet_handler(asyncio.get_running_loop())
    operator = FakeClient(url, "phone", PASSWORDS["phone"])
    await operator.connect()
    print("operator", flush=True)
    await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
    visitors = []
    for i in range(1, listeners + 1):
        visitor = FakeClient(url, f"club{i}", listener_password(i))
        await visitor.connect()
        visitors.append(visitor)
    print("listeners", flush=True)
    await asyncio.sleep(3600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="listener_load", description="Charge des visiteurs sur la passerelle")
    ap.add_argument("--listeners", type=int, default=5)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--clients", metavar="URL", help=argparse.SUPPRESS)   # processus des faux clients
    args = ap.parse_args(argv)
    if args.clients:
        asyncio.run(clients(args.clients, args.listeners))
    else:
        asyncio.run(gateway(args.listeners, args.seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
