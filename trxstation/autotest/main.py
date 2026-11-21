# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""openRemoteTRX-Autotest, mode B (lot PQ5) : `python -m trxstation.autotest`.

Lance la page de préqualification sur 127.0.0.1, ouvre le navigateur, et pilote le poste par SON rigctld (lancé à
la connexion, arrêté à la fin). Refuse de démarrer si la station openRemoteTRX tourne : deux programmes qui pilotent
le même poste se gênent. Ctrl+C = arrêt (« T 0 » d'abord)."""
from __future__ import annotations

import argparse
import asyncio
import sys
import webbrowser

from aiohttp import web

from ..config import Supervisor
from ..procutil import station_running
from .server import DEFAULT_PORT, AutotestServer


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="trx-autotest", description="openRemoteTRX-Autotest (mode B, Hamlib)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port local de la page (127.0.0.1)")
    parser.add_argument("--hamlib-dir", default="", help="dossier de Hamlib si rigctld n'est pas dans le PATH")
    parser.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    return parser.parse_args(argv)


async def serve(args: argparse.Namespace) -> None:
    server = AutotestServer(port=args.port, hamlib_dir=args.hamlib_dir)
    runner = web.AppRunner(server.app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    print(f"openRemoteTRX-Autotest : {server.url()}", flush=True)
    print("Poste sur CHARGE FICTIVE pour les émissions. Ctrl+C pour arrêter.", flush=True)
    if not args.sans_navigateur:
        webbrowser.open(server.url())
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()               # « T 0 » puis rigctld arrêté (AutotestServer._cleanup)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if station_running(Supervisor().instance_lock_port):
        print("La station openRemoteTRX est en marche : arrêtez-la d'abord (openRemoteTRX Console, menu 1.2).\n"
              "The openRemoteTRX station is running: stop it first (openRemoteTRX Console, menu 1.2).")
        return 2
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"Port {args.port} indisponible : {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
