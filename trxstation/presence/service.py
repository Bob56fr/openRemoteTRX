# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module « presence » : processus séparé lancé et surveillé par le superviseur (`[modules] run = ["presence"]`).

Il ne parle JAMAIS au poste : son manifeste ne lui donne aucune commande (ni PTT ni QSY). Il lit seulement la
fréquence, le mode et l'émission sur le bus, et échange des états chiffrés avec le relais (`[presence] relay_url`).

- configuration : `[presence]` de station.toml (chemin dans TRX_CONFIG_PATH, donné par le superviseur) ;
- clés de la station : `[presence] key_file`, ou `state_dir/presence/presence.key` créé au premier démarrage ;
- groupes, clés de groupe, partage : `state_dir/presence/presence.json` (0600) ; résumé : `status.json` ;
- journal : `state_dir/presence/presence.log`, 5 fichiers de 1 Mo, jamais de clé ;
- commandes des opérateurs (`friends` de la page et de l'application, relayées par le cœur : droit client_commands)
  et de TRX Console (menu 5.3 : `state_dir/presence-request.json` déposé par la console, réponse dans
  `state_dir/presence/console-reply.json`, effacée après 60 s) ; avis `friends_changed` aux SEULS opérateurs.

À la main (essai) :  python -m trxstation.presence.service --config station.toml
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

from .. import __version__
from .. import config as cfgmod
from ..errors import codes
from ..errors.emit import emit_event
from ..paths import default_config_path
from . import actions
from .engine import ActionRefused, Engine
from .identity import Identity, load_key_file, save_key_file
from .relay import HttpRelay
from .store import Store

log = logging.getLogger("trx.presence")
ERROR_DELAY_S = 120.0
CONSOLE_REQUEST = "presence-request.json"      # dans state_dir (déposé par TRX Console, au besoin par sudo)
CONSOLE_REPLY = "console-reply.json"           # dans state_dir/presence
CONSOLE_MAX_AGE_S = 120.0
CONSOLE_REPLY_KEEP_S = 60.0
TICK_S = 1.0


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
        self.lock = asyncio.Lock()               # un cycle et une action de l'opérateur ne s'entremêlent jamais
        self._view_digest = ""
        self._reply_at: float | None = None

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
            self.bus.on_call = self.on_call
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
        elif name == "operator_activity":
            self.engine.on_activity()

    # ------------------------------------------------------------- commandes des opérateurs et de la console
    async def act(self, action: str, args: dict) -> dict:
        """Une action de l'opérateur (ActionRefused sinon) ; les pages sont prévenues si la vue a changé."""
        async with self.lock:
            result = await actions.handle(self.engine, action, args)
        if action in actions.MUTATING:
            self.store.write_status({"enabled": True, "updated": int(self.clock()), **self.engine.status_summary()})
        await self.notify_if_changed()
        return result

    async def on_call(self, data: dict):
        from ..modules.client import CallRefused          # client du bus : seulement pour traduire le refus
        try:
            return await self.act(str(data.get("action")), data.get("args") or {})
        except ActionRefused as exc:
            raise CallRefused(exc.reason, str(exc)) from None

    async def notify_if_changed(self) -> None:
        """Avis court `friends_changed` aux OPÉRATEURS (jamais aux visiteurs) quand la vue a changé ; le client
        redemande la vue (`friends` view) : un message reste petit, quel que soit le nombre de membres."""
        if self.bus is None or not self.bus.connected.is_set():
            return
        digest = hashlib.sha256(json.dumps(self.engine.view(), sort_keys=True, default=str).encode()).hexdigest()
        if digest == self._view_digest:
            return
        self._view_digest = digest
        try:
            await self.bus.client_message(kind="friends_changed", scope="operators")
        except Exception as exc:                  # le bus peut refuser (débit) ou être tombé : la vue reste lisible
            log.info("avis aux pages non transmis : %s", exc)

    def _state_dir(self) -> Path:
        return Path(self.cfg.supervisor.state_dir)

    async def check_console(self) -> None:
        """Demande de TRX Console (menu 5.3) : lue puis effacée, réponse dans console-reply.json (effacée après 60 s)."""
        from .store import write_json
        reply_path = self.folder / CONSOLE_REPLY
        now = self.clock()
        if self._reply_at is not None and now - self._reply_at > CONSOLE_REPLY_KEEP_S:
            try:
                reply_path.unlink()
            except OSError:
                pass
            self._reply_at = None
        path = self._state_dir() / CONSOLE_REQUEST
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return
        except OSError as exc:
            log.warning("demande de la console illisible : %s", exc)
            return
        try:
            path.unlink()
        except OSError as exc:
            log.warning("demande de la console non effacée : %s", exc)
        try:
            req = json.loads(raw.decode("utf-8"))
            ident, action, args, at = req["id"], req["action"], req.get("args") or {}, float(req["at"])
            if not isinstance(ident, str) or not isinstance(action, str) or not isinstance(args, dict):
                raise ValueError("champs")
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            log.warning("demande de la console mal formée : ignorée")
            return
        if abs(now - at) > CONSOLE_MAX_AGE_S:
            log.warning("demande de la console trop ancienne : ignorée")
            return
        try:
            reply = {"id": ident, "ok": True, "result": await self.act(action, args)}
        except ActionRefused as exc:
            reply = {"id": ident, "ok": False, "error": exc.reason, "message": str(exc)}
        except Exception:
            log.exception("demande de la console en erreur")
            reply = {"id": ident, "ok": False, "error": "internal", "message": "erreur du module"}
        try:
            write_json(reply_path, reply, private=False)       # lisible par le compte de la console
            self._reply_at = now
        except OSError as exc:
            log.warning("réponse à la console non écrite : %s", exc)

    # ------------------------------------------------------------- boucle
    async def run(self) -> None:
        tasks = []
        if not self.cfg.presence.enabled:
            Store(self.folder).write_status({"enabled": False, "updated": int(self.clock())})
            log.info("[presence] désactivé : le module attend sans rien envoyer")
            if self.bus is not None:
                tasks.append(asyncio.ensure_future(self._bus_forever()))
            await (asyncio.gather(*tasks) if tasks else asyncio.Event().wait())
            return
        try:
            engine = self.setup()
        except (ValueError, OSError) as exc:      # fichier de clés abîmé ou illisible : ni plantage en boucle, ni
            key_path = cfgmod.presence_key_path(self.cfg, self.config_path)   # nouvelle identité créée en silence
            emit_event(codes.ORT_6920, logger=log, fichier=str(key_path), detail=str(exc))
            Store(self.folder).write_status({"enabled": True, "updated": int(self.clock()),
                                             "problem": f"fichier de clés illisible ({key_path.name})"})
            if self.bus is not None:
                tasks.append(asyncio.ensure_future(self._bus_forever()))
            await (asyncio.gather(*tasks) if tasks else asyncio.Event().wait())
            return
        log.info("démarrage : relais %s, station %s", self.cfg.presence.relay_url, engine.me)
        if self.bus is not None:
            tasks.append(asyncio.ensure_future(self._bus_forever()))
        tasks.append(asyncio.ensure_future(self._loop()))
        await asyncio.gather(*tasks)

    async def _loop(self) -> None:
        due = 0.0
        while True:
            if self.clock() >= due:
                due = self.clock() + await self.step()
                await self.notify_if_changed()
            try:
                await self.check_console()
            except Exception:
                log.exception("demande de la console en erreur")
            await asyncio.sleep(TICK_S)

    async def step(self) -> float:
        """Un cycle, protégé : une erreur inattendue est journalisée, jamais fatale."""
        try:
            async with self.lock:
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
