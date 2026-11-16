# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module « monlink » : processus séparé lancé et surveillé par le superviseur (`[modules] run = ["monlink"]`).

Monitoring inter-stations, mode R (docs/cdc-monitoring.md § 17) : aider un opérateur en difficulté, ou être aidé.
Il ne parle JAMAIS au poste : son manifeste ne lui donne ni événement, ni commande, ni message vers les pages ; il lit
des fichiers d'état (passerelle, superviseur, journaux JSON) et échange des enveloppes chiffrées avec le relais.

- configuration : `[monitor_link]` de station.toml (chemin dans TRX_CONFIG_PATH, donné par le superviseur) ;
- clés : `[monitor_link] key_file`, ou `state_dir/monlink/monlink.key` créé au premier démarrage (À PART de la présence) ;
- liaisons : `state_dir/monlink/monlink.json` (0600) ; résumé : `status.json` (0644) ; reçu : `received.db` ;
- journal : `state_dir/monlink/monlink.log`, 5 fichiers de 1 Mo, jamais de clé ;
- TRX Console (menu 5.5, lot R3b) : demande `state_dir/monlink-request.json` déposée par la console, réponse dans
  `state_dir/monlink/console-reply.json`, effacée après 60 s (même mécanisme que la présence).

À la main (essai) :  python -m trxstation.monlink.service --config station.toml
"""
from __future__ import annotations

import argparse
import asyncio
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
from ..presence.store import write_json
from .engine import ActionRefused, Engine
from .identity import Identity, load_key_file, save_key_file
from .relay import HttpRelay, RelayRefused, RelayUnavailable
from .store import Store

log = logging.getLogger("trx.monlink")
ERROR_DELAY_S = 120.0
CONSOLE_REQUEST = "monlink-request.json"       # dans state_dir (déposé par TRX Console, au besoin par sudo)
CONSOLE_REPLY = "console-reply.json"           # dans state_dir/monlink
CONSOLE_MAX_AGE_S = 120.0
CONSOLE_REPLY_KEEP_S = 60.0
TICK_S = 1.0
# Actions de l'opérateur (TRX Console) -> (méthode du moteur, arguments acceptés)
ACTIONS = {"view": ("view", ()), "pseudo": ("set_pseudo", ("pseudo",)), "invite": ("invite", ()),
           "join": ("join", ("code",)), "confirm": ("confirm", ("peer", "profile")),
           "profile": ("set_profile", ("peer", "profile")), "pause": ("pause", ("peer", "paused")),
           "end": ("end", ("peer", "purge")), "request_assist": ("request_assist", ("peer", "duration_s")),
           "answer": ("answer", ("peer", "accept")), "received": ("received", ("peer", "limit")),
           "request_report": ("request_report", ("peer",)), "send_report": ("send_report", ("peer",)),
           "last_report": ("last_report", ("peer",)), "report_part": ("report_part", ("peer", "part"))}


def monlink_dir(cfg: cfgmod.Config) -> Path:
    return Path(cfg.supervisor.state_dir) / "monlink"


def load_or_create_identity(path: Path) -> Identity:
    if path.exists():
        return load_key_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = Identity.generate()
    save_key_file(path, identity)
    log.info("clés du monitoring créées : %s (identifiant %s)", path, identity.station_id)
    return identity


class MonlinkService:
    def __init__(self, cfg: cfgmod.Config, config_path: Path, bus_client=None, *, relay_factory=None,
                 clock=time.time, monitor=None) -> None:
        self.cfg, self.config_path, self.bus = cfg, Path(config_path), bus_client
        self.folder = monlink_dir(cfg)
        self.relay_factory = relay_factory        # essais : FakeMonRelay.transport ; sinon HttpRelay
        self.clock = clock
        self.monitor = monitor
        self.engine: Engine | None = None
        self.store: Store | None = None
        self.lock = asyncio.Lock()                # un cycle et une action de l'opérateur ne s'entremêlent jamais
        self._reply_at: float | None = None

    def setup(self) -> Engine:
        identity = load_or_create_identity(cfgmod.monlink_key_path(self.cfg, self.config_path))
        self.store = Store(self.folder)
        relay = (self.relay_factory(identity) if self.relay_factory is not None
                 else HttpRelay(self.cfg.monitor_link.relay_url, identity, version=__version__))
        if self.monitor is None:
            from ..hostinfo import HostMonitor
            self.monitor = HostMonitor(self.cfg.supervisor.state_dir)
        notifier = None
        if self.cfg.supervisor.notify_url:
            from ..supervisor.notify import Notifier               # le ntfy de la station (alertes de celui qui aide)
            notifier = Notifier(self.cfg.supervisor.notify_url, lang=self.cfg.supervisor.notify_lang)
        self.engine = Engine(self.store, identity, relay, status_path=self.cfg.supervisor.status_path,
                             state_dir=self.cfg.supervisor.state_dir, clock=self.clock, monitor=self.monitor,
                             notifier=notifier, make_report=self.make_report)
        if self.bus is not None:
            self.bus.metrics = lambda: {"links": len(self.store.links), "problem": self.engine.problem or ""}
            self.bus.on_call = self.on_call               # commande « monitoring » d'un opérateur de la page
        return self.engine

    def make_report(self) -> bytes:
        """Rapport du menu 2.3 (`report.make_report`, déjà sans mot de passe), fabriqué dans un dossier temporaire
        avec les droits du compte du module ; masqué ensuite par le moteur avant tout envoi."""
        import shutil
        import tempfile
        from ..report import make_report
        folder = Path(tempfile.mkdtemp(prefix="trx-monlink-rapport-"))
        try:
            return make_report(destination=folder, config_path=self.config_path).read_bytes()
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def write_status(self) -> None:
        self.store.write_status({"enabled": True, "updated": int(self.clock()), **self.engine.view()})

    # ------------------------------------------------------------- actions de l'opérateur
    async def act(self, action: str, args: dict) -> object:
        spec = ACTIONS.get(action)
        if spec is None:
            raise ActionRefused("unknown_action", f"action inconnue : {action}")
        method, allowed = spec
        extra = set(args) - set(allowed)
        if extra:
            raise ActionRefused("malformed", f"arguments inattendus : {', '.join(sorted(extra))}")
        async with self.lock:
            try:
                result = getattr(self.engine, method)(**args)
                if asyncio.iscoroutine(result):
                    result = await result
            except RelayUnavailable as exc:
                raise ActionRefused("relay", f"relais injoignable : {exc}") from exc
            except RelayRefused as exc:
                raise ActionRefused("relay_" + exc.reason, f"refus du relais : {exc.reason}") from exc
            except TypeError as exc:              # argument manquant
                raise ActionRefused("malformed", "arguments incomplets") from exc
        self.write_status()
        return result

    async def on_call(self, data: dict):
        """Commande « monitoring » d'un OPÉRATEUR de la page (lot R5), relayée par le cœur : mêmes actions que le menu
        5.5 ; un refus revient à la page avec son motif."""
        from ..modules.client import CallRefused          # client du bus : seulement pour traduire le refus
        args = data.get("args") or {}
        if not isinstance(args, dict):
            raise CallRefused("malformed", "arguments mal formés")
        try:
            return await self.act(str(data.get("action")), args)
        except ActionRefused as exc:
            raise CallRefused(exc.reason, str(exc)) from None

    async def check_console(self) -> None:
        """Demande de TRX Console : lue puis effacée, réponse dans console-reply.json (effacée après 60 s)."""
        reply_path = self.folder / CONSOLE_REPLY
        now = self.clock()
        if self._reply_at is not None and now - self._reply_at > CONSOLE_REPLY_KEEP_S:
            try:
                reply_path.unlink()
            except OSError:
                pass
            self._reply_at = None
        path = Path(self.cfg.supervisor.state_dir) / CONSOLE_REQUEST
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return
        except OSError as exc:
            log.info("demande de la console illisible : %s", exc)
            return
        try:
            path.unlink()
        except OSError as exc:
            log.info("demande de la console non effacée : %s", exc)
        try:
            req = json.loads(raw.decode("utf-8"))
            ident, action, args, at = req["id"], req["action"], req.get("args") or {}, float(req["at"])
            if not isinstance(ident, str) or not isinstance(action, str) or not isinstance(args, dict):
                raise ValueError("champs")
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            log.info("demande de la console mal formée : ignorée")
            return
        if abs(now - at) > CONSOLE_MAX_AGE_S:
            log.info("demande de la console trop ancienne : ignorée")
            return
        try:
            reply = {"id": ident, "ok": True, "result": await self.act(action, args)}
        except ActionRefused as exc:
            reply = {"id": ident, "ok": False, "error": exc.reason, "message": str(exc)}
        except Exception as exc:
            emit_event(codes.ORT_7040, logger=log, trace=True, relais="module monlink", detail=type(exc).__name__)
            reply = {"id": ident, "ok": False, "error": "internal", "message": "erreur du module"}
        try:
            write_json(reply_path, reply, private=False)        # lisible par le compte de la console
            self._reply_at = now
        except OSError as exc:
            log.info("réponse à la console non écrite : %s", exc)

    # ------------------------------------------------------------- boucle
    async def run(self) -> None:
        tasks = []
        if self.bus is not None:
            tasks.append(asyncio.ensure_future(self._bus_forever()))
        if not self.cfg.monitor_link.enabled:
            Store(self.folder).write_status({"enabled": False, "updated": int(self.clock())})
            log.info("[monitor_link] désactivé : le module attend sans rien envoyer ni relever")
            await (asyncio.gather(*tasks) if tasks else asyncio.Event().wait())
            return
        try:
            engine = self.setup()
        except (ValueError, OSError) as exc:      # fichier de clés abîmé : ni plantage en boucle, ni nouvelle identité
            key_path = cfgmod.monlink_key_path(self.cfg, self.config_path)       # créée en silence
            emit_event(codes.ORT_7041, logger=log, fichier=str(key_path), detail=str(exc)[:200])
            Store(self.folder).write_status({"enabled": True, "updated": int(self.clock()),
                                             "problem": f"fichier de clés illisible ({key_path.name})"})
            await (asyncio.gather(*tasks) if tasks else asyncio.Event().wait())
            return
        log.info("démarrage : relais %s, station %s", self.cfg.monitor_link.relay_url, engine.me)
        tasks.append(asyncio.ensure_future(self._loop()))
        await asyncio.gather(*tasks)

    async def _loop(self) -> None:
        due = 0.0
        while True:
            if self.clock() >= due:
                due = self.clock() + await self.step()
            try:
                await self.check_console()
            except Exception:
                emit_event(codes.ORT_7040, logger=log, trace=True, relais="module monlink", detail="console")
            await asyncio.sleep(TICK_S)

    async def step(self) -> float:
        """Un cycle, protégé : une erreur inattendue est journalisée, jamais fatale."""
        try:
            async with self.lock:
                delay = await self.engine.cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            emit_event(codes.ORT_7040, logger=log, trace=True, relais="module monlink", detail=type(exc).__name__)
            self.engine.problem = "internal"
            delay = ERROR_DELAY_S
        self.write_status()
        return delay

    async def _bus_forever(self) -> None:
        try:
            await self.bus.run_forever()
        except Exception as exc:              # sans bus, le module continue (il n'en a pas besoin pour travailler)
            log.info("API interne indisponible : %s", exc)


def setup_logging(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s monlink %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        handler = logging.handlers.RotatingFileHandler(folder / "monlink.log", maxBytes=1_000_000, backupCount=4,
                                                       encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError as exc:
        log.info("journal %s impossible : %s", folder / "monlink.log", exc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.monlink.service", description="Module de monitoring")
    ap.add_argument("--config", type=Path, default=Path(os.environ.get("TRX_CONFIG_PATH") or default_config_path()))
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration illisible ({args.config}) : {exc}", file=sys.stderr)
        return 2
    setup_logging(monlink_dir(cfg))
    bus = None
    if os.environ.get("TRX_MODULE_SECRET"):
        from ..modules.client import ModuleClient       # client du bus : les droits sont ceux du manifeste (aucun)
        bus = ModuleClient.from_env()
    try:
        asyncio.run(MonlinkService(cfg, args.config, bus_client=bus).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
