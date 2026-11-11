# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module « freedv_activity » : processus séparé lancé et surveillé par le superviseur
(`[modules] run = ["freedv_activity"]`, désactivé par défaut).

Il lit FreeDV Reporter en OBSERVATEUR (reporter.py : rien n'est envoyé sur la station) et publie toutes les
PUBLISH_EVERY_S secondes, à TOUS les clients (visiteurs compris), le message de module :

    {"kind": "freedv_activity", "retain": "snapshot", "status": "ok"|"connexion"|"erreur", "message": "...",
     "total": <stations connectées au service>, "locator": true|false, "t": <heure Unix>,
     "freqs": [{"f": Hz, "note": 0..., "tx": [{"c", "km", "on", "min", "m"}], "rx": [{"c", "km", "snr", "m"}]}]}

Il ne parle JAMAIS au poste (aucun droit dans son manifeste) : le QSY vers une fréquence de la liste est une
commande habituelle du client (fréquence, et USB si le poste n'est ni en USB ni en PKTUSB).

- configuration : `[freedv] locator` de station.toml (distances et note ; vide = sans distance) ;
- journal : `state_dir/freedv_activity/activity.log`, 3 fichiers de 1 Mo.

À la main (essai, sans bus) :  python -m trxstation.freedv.activity_service --config station.toml --once
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

from .. import __version__
from .. import config as cfgmod
from ..paths import default_config_path
from .activity import ReporterState
from .reporter import ReporterClient

log = logging.getLogger("trx.freedv.activity")
PUBLISH_EVERY_S = 10.0
FIRST_PUBLISH_S = 3.0


def build_message(client: ReporterClient, state: ReporterState, lock: threading.Lock, locator: str, now: float) -> dict:
    with lock:
        freqs = state.snapshot(now, locator) if client.status == "ok" else []
        return {"kind": "freedv_activity", "retain": "snapshot", "status": client.status, "message": client.message,
                "total": len(state.stations), "locator": bool(locator), "t": int(now), "freqs": freqs}


class ActivityService:
    def __init__(self, locator: str, bus_client=None, *, reporter: ReporterClient | None = None,
                 clock=time.time) -> None:
        self.locator, self.bus, self.clock = locator, bus_client, clock
        self.lock = threading.Lock()
        self.state = ReporterState()
        self.reporter = reporter or ReporterClient(self.state, self.lock, user_agent=f"openRemoteTRX/{__version__}")
        if reporter is not None:
            self.state, self.lock = reporter.state, reporter.lock
        self.stop = threading.Event()

    def message(self) -> dict:
        return build_message(self.reporter, self.state, self.lock, self.locator, self.clock())

    async def publish(self) -> None:
        if self.bus is None or not self.bus.connected.is_set():
            return
        try:
            await self.bus.client_message(**self.message())
        except Exception as exc:          # cœur occupé ou redémarré : la prochaine publication suivra
            log.warning("liste non publiée : %s", exc)

    async def run(self) -> None:
        thread = threading.Thread(target=self.reporter.run, args=(self.stop,), name="freedv-reporter", daemon=True)
        thread.start()
        tasks = []
        if self.bus is not None:
            tasks.append(asyncio.ensure_future(self._bus_forever()))
        try:
            await asyncio.sleep(FIRST_PUBLISH_S)
            while True:
                await self.publish()
                await asyncio.sleep(PUBLISH_EVERY_S)
        finally:
            self.stop.set()
            for t in tasks:
                t.cancel()

    async def _bus_forever(self) -> None:
        try:
            await self.bus.run_forever()
        except Exception as exc:
            log.warning("API interne indisponible : %s", exc)


def setup_logging(folder: Path) -> None:
    fmt = logging.Formatter("%(asctime)s freedv_activity %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(folder / "activity.log", maxBytes=1_000_000, backupCount=2,
                                                       encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError as exc:
        log.warning("journal %s impossible : %s", folder / "activity.log", exc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.freedv.activity_service", description="Activité FreeDV")
    ap.add_argument("--config", type=Path, default=Path(os.environ.get("TRX_CONFIG_PATH") or default_config_path()))
    ap.add_argument("--once", action="store_true", help="essai : lit FreeDV Reporter 20 s puis affiche la liste")
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration illisible ({args.config}) : {exc}", file=sys.stderr)
        return 2
    locator = cfg.freedv.locator.strip().upper()
    if args.once:
        svc = ActivityService(locator)
        threading.Thread(target=svc.reporter.run, args=(svc.stop,), daemon=True).start()
        time.sleep(20)
        svc.stop.set()
        print(json.dumps(svc.message(), ensure_ascii=False, indent=1))
        return 0
    setup_logging(Path(cfg.supervisor.state_dir) / "freedv_activity")
    bus = None
    if os.environ.get("TRX_MODULE_SECRET"):
        from ..modules.client import ModuleClient
        bus = ModuleClient.from_env()
    log.info("démarrage : FreeDV Reporter en observateur, locator %s", locator or "absent (sans distances)")
    try:
        asyncio.run(ActivityService(locator, bus).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
