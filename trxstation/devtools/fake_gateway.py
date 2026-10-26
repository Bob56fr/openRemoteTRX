"""Faux processus passerelle (vraies couches CAT, sécurité PTT et publication d'état).

Sert à tester le superviseur avec de vrais processus : on peut le suspendre (SIGSTOP)
pendant une émission, comme un gel de la passerelle.
    python -m trxstation.devtools.fake_gateway --rigctld-port 4532 --status /tmp/s.json --key
"""
from __future__ import annotations

import argparse
import asyncio

from ..gateway.cat import CatLink
from ..gateway.safety import PttController, PttLimits
from ..gateway.status import StatusPublisher
from ..setup_wizard import dummy_config
from .loop_noise import install_quiet_reset_handler


async def _run(args: argparse.Namespace) -> None:
    install_quiet_reset_handler(asyncio.get_running_loop())
    cfg = dummy_config()
    link = CatLink("127.0.0.1", args.rigctld_port, poll_fast_s=0.1, slow_every=2)
    ctrl = PttController(link, cfg, limits=PttLimits(tot_s=args.tot, warn_before_s=min(10.0, args.tot / 2),
                                                     heartbeat_timeout_s=2.0, rekey_cooldown_s=0.0))
    publisher = StatusPublisher(args.status, link, ctrl, interval_s=0.2)
    background = [asyncio.create_task(link.run()), asyncio.create_task(publisher.run())]  # références gardées
    await ctrl.start()
    ctrl.connect_client("phone")
    while link.state.connected is False or ctrl.starting:
        await asyncio.sleep(0.05)
    if args.key:
        await ctrl.toggle("phone")
    while all(not t.done() for t in background):   # le « client » bat régulièrement le heartbeat
        ctrl.heartbeat("phone")
        await asyncio.sleep(0.1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rigctld-port", type=int, required=True)
    ap.add_argument("--status", required=True)
    ap.add_argument("--tot", type=float, default=90.0)
    ap.add_argument("--key", action="store_true", help="prend l'émission au démarrage")
    args = ap.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
