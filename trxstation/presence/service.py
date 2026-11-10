# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module « presence » : processus séparé lancé et surveillé par le superviseur (`[modules] run = ["presence"]`).

Il ne parle JAMAIS au poste : son manifeste ne lui donne aucune commande (ni PTT ni QSY). Il lit seulement la
fréquence, le mode et l'émission sur le bus, et échange des états chiffrés avec le relais (`[presence] relay_url`).

- configuration : `[presence]` de station.toml (chemin dans TRX_CONFIG_PATH, donné par le superviseur) ;
- clés de la station : `[presence] key_file`, ou `state_dir/presence/presence.key` créé au premier démarrage ;
- groupes, clés de groupe, partage : `state_dir/presence/presence.json` (0600) ; résumé : `status.json` ;
- journal : `state_dir/presence/presence.log`, 5 fichiers de 1 Mo, jamais de clé.

À la main (essai) :  python -m trxstation.presence.service --config station.toml
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

from .. import __version__
from .. import config as cfgmod
from ..paths import default_config_path
from .engine import Engine
from .identity import Identity, load_key_file, save_key_file
from .relay import HttpRelay
from .store import Store

log = logging.getLogger("trx.presence")
ERROR_DELAY_S = 120.0


def presence_dir(cfg: cfgmod.Config) -> Path:
    return Path(cfg.supervisor.state_dir) / "presence"


def load_or_create_identity(path: Path) -> Identity:
    if path.exists():
        return load_key_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = Identity.generate()
    save_key_file(path, identity)
    log.info("clés de la station créées : %s (identifiant %s)", path, identity.station_id)
    return identity


class PresenceService:
    def __init__(self, cfg: cfgmod.Config, config_path: Path, bus_client=None, *, relay_factory=None,
                 clock=time.time) -> None:
        self.cfg, self.config_path, self.bus = cfg, Path(config_path), bus_client
        self.folder = presence_dir(cfg)
        self.relay_factory = relay_factory      # essais : FakeRelay.transport ; sinon HttpRelay
        self.relay = None
        self.clock = clock
        self.engine: Engine | None = None
        self.store: Store | None = None

    def setup(self) -> Engine:
        identity = load_or_create_identity(cfgmod.presence_key_path(self.cfg, self.config_path))
        self.store = Store(self.folder)
        if self.relay_factory is not None:
            self.relay = self.relay_factory(identity)
        else:
            self.relay = HttpRelay(self.cfg.presence.relay_url, identity, version=__version__)
        self.engine = Engine(self.store, identity, self.relay, relay_url=self.cfg.presence.relay_url,
                             version=__version__, clock=self.clock)
        if self.bus is not None:
            self.bus.on_event = self.on_event
            self.bus.on_connect = self.on_connect
            self.bus.on_gap = self.on_connect
            self.bus.metrics = lambda: {"groups": len(self.store.groups), "problem": self.engine.problem or ""}
        return self.engine

    # ------------------------------------------------------------- bus (lecture seule)
    async def on_connect(self) -> None:
        state = await self.bus.get_state()
        self.engine.set_rig(state.get("freq"), state.get("mode"))
        self.engine.on_ptt(state.get("ptt"))

    def on_event(self, name: str, data: dict) -> None:
        if self.engine is None:
            return
        if name == "freq_mode":
            self.engine.on_rig(data.get("freq"), data.get("mode"))
        elif name == "ptt":
            self.engine.on_ptt(data.get("active"))

    # ------------------------------------------------------------- boucle
    async def run(self) -> None:
        tasks = []
        if not self.cfg.presence.enabled:
            Store(self.folder).write_status({"enabled": False, "updated": int(self.clock())})
            log.info("[presence] désactivé : le module attend sans rien envoyer")
            if self.bus is not None:
                tasks.append(asyncio.ensure_future(self._bus_forever()))
            await asyncio.gather(*tasks) if tasks else asyncio.Event().wait()
            return
        engine = self.setup()
        log.info("démarrage : relais %s, station %s", self.cfg.presence.relay_url, engine.me)
        if self.bus is not None:
            tasks.append(asyncio.ensure_future(self._bus_forever()))
        tasks.append(asyncio.ensure_future(self._loop()))
        await asyncio.gather(*tasks)

    async def _loop(self) -> None:
        while True:
            delay = await self.step()
            await asyncio.sleep(delay)

    async def step(self) -> float:
        """Un cycle, protégé : une erreur inattendue est journalisée, jamais fatale."""
        try:
            delay = await self.engine.cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("cycle de présence en erreur")
            self.engine.problem = "internal"
            delay = ERROR_DELAY_S
        self.store.write_status({"enabled": True, "updated": int(self.clock()), **self.engine.status_summary()})
        return delay

    async def _bus_forever(self) -> None:
        try:
            await self.bus.run_forever()
        except Exception as exc:              # sans bus, le module continue (statut « inconnu » de la station)
            log.warning("API interne indisponible : %s", exc)


def setup_logging(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s presence %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        handler = logging.handlers.RotatingFileHandler(folder / "presence.log", maxBytes=1_000_000, backupCount=4,
                                                       encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError as exc:
        log.warning("journal %s impossible : %s", folder / "presence.log", exc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.presence.service", description="Module de présence")
    ap.add_argument("--config", type=Path, default=Path(os.environ.get("TRX_CONFIG_PATH") or default_config_path()))
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration illisible ({args.config}) : {exc}", file=sys.stderr)
        return 2
    setup_logging(presence_dir(cfg))
    bus = None
    if os.environ.get("TRX_MODULE_SECRET"):
        from ..modules.client import ModuleClient       # client du bus : les droits sont ceux du manifeste
        bus = ModuleClient.from_env()
    try:
        asyncio.run(PresenceService(cfg, args.config, bus_client=bus).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
