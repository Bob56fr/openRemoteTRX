# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Point d'entrée de la passerelle : `python -m trxstation.gateway.main` (commande `trx-gateway`).

Assemble : liaison CAT, couche de sécurité PTT, audio (réception diffusée, émission derrière la
porte du PTT), fichier d'état et API WebRTC. Sans client autorisé ([[clients]]) ou sans aiortc,
il n'y a pas d'API : le poste reste en réception, ce qui est le comportement sûr.

Arrêt propre sur SIGTERM / SIGINT (et SIGBREAK sous Windows) : l'émission est coupée avant de
quitter. En mode géré, `--parent-pid` fait quitter la passerelle (après coupure) si le
superviseur disparaît.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import ssl
import sys
from pathlib import Path

from .. import __version__
from .. import config as cfgmod
from ..asyncio_noise import install_quiet_handler
from ..audio_devices import real_device_names
from ..config import Config, exposure_problem
from ..layout import LayoutStore
from ..modules.gateway_bridge import ModuleBridge
from ..paths import default_config_path
from ..procutil import pid_alive
from ..spectrum.service import SpectrumService
from .audio import AudioConfigError, AudioPipeline
from .audio.beeps import BeepStore, TailPlayer
from .bugreports import ReportStore
from .cat import CatLink, load_capabilities
from .memories import MemoryStore
from .safety import PttController
from .status import StatusPublisher

log = logging.getLogger("trx-gateway")


async def _watch_parent(pid: int, stop: asyncio.Event, every_s: float = 1.0) -> None:
    while not stop.is_set():
        if not pid_alive(pid):
            log.error("le superviseur (pid %d) a disparu : arrêt de la passerelle", pid)
            stop.set()
            return
        await asyncio.sleep(every_s)


async def run(cfg: Config, *, stop: asyncio.Event | None = None, parent_pid: int | None = None) -> None:
    stop = stop or asyncio.Event()
    try:
        capabilities = await load_capabilities(cfg.rig.model, cfg.tools.hamlib_dir)
    except Exception as exc:                       # Hamlib absent ou format inattendu : l'interface s'adapte
        log.warning("capacités du poste indisponibles (%s) : jeu minimal", exc)
        capabilities = None
    pipeline = AudioPipeline(cfg.audio)            # AudioConfigError : périphérique introuvable, on s'arrête franchement
    try:
        await pipeline.start()                     # AVANT la liaison CAT et la sécurité PTT : un échec ne laisse rien derrière
    except BaseException:
        await pipeline.stop()
        raise
    link = CatLink(cfg.network.rigctld_host, cfg.network.rigctld_port, capabilities=capabilities)
    beeps = BeepStore(Path(cfg.supervisor.state_dir) / "beeps.json")   # roger bip, bip de liaison perdue (téléphone)
    tail = TailPlayer(pipeline.sink, beeps, gain_db=cfg.audio.tx_gain_db)
    ctrl = PttController(link, cfg, audio_gate=pipeline.gate.set_open, tail=tail)
    pipeline.gate.owner_provider = lambda: ctrl.snapshot().owner     # seul le propriétaire de l'émission est entendu
    spectrum = SpectrumService(cfg.spectrum, link, ctrl)   # [spectrum] source = "civ_port" ; sinon inactif
    publisher = StatusPublisher(cfg.supervisor.status_path, link, ctrl, pipeline=pipeline, spectrum=spectrum)
    tasks = [asyncio.create_task(link.run()), asyncio.create_task(publisher.run())]
    if parent_pid is not None:
        tasks.append(asyncio.create_task(_watch_parent(parent_pid, stop)))
    manager = runner = None
    bridge = ModuleBridge(cfg, ctrl, link, clients=lambda: _client_sessions(manager))
    try:
        await ctrl.start()
        await spectrum.start()                     # n'ouvre le second port qu'en réception confirmée
        manager, runner = await _start_api(cfg, ctrl, link, pipeline, capabilities, spectrum)
        if manager is not None:
            manager.on_hf_view = bridge.on_hf_view     # vue HF ouverte : spots du cluster rejoués à ce client
        await bridge.start()                       # [modules] run vide : rien ; toute erreur : la station continue
        log.info("passerelle démarrée (RX), état publié dans %s", cfg.supervisor.status_path)
        await stop.wait()
    finally:
        log.info("arrêt : coupure de l'émission")
        await bridge.stop()
        await spectrum.stop()                      # réglages du spectre remis, second port fermé
        if runner is not None:
            await runner.cleanup()                 # plus de nouvelle connexion
        if manager is not None:
            await manager.close_all()              # déconnecte les clients : coupe l'émission du propriétaire
        await ctrl.close()
        await pipeline.stop()
        publisher.stop()
        link.stop()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def bind_hint(host: str) -> str:
    """Conseil lisible quand l'adresse d'écoute ne peut pas être ouverte."""
    if host in ("0.0.0.0", "::") or cfgmod.is_loopback(host):
        return "Le port est sans doute déjà pris (autre passerelle encore active ?) : change [network] gateway_port ou arrête l'autre programme."
    return (f"Cette machine n'a peut-être plus l'adresse {host} (réseau ou box changés) : relance l'assistant, "
            "étape Accès (écoute sur toutes les adresses), ou corrige [network] gateway_bind.")


def _client_sessions(manager) -> list:
    """Sessions client ouvertes (relais des messages des modules)."""
    if manager is None:
        return []
    return [peer.session for peer in list(manager.peers.values()) if peer.session is not None]


async def _start_api(cfg: Config, ctrl, link, pipeline, capabilities, spectrum=None):
    """Démarre l'API WebRTC si des clients sont autorisés, si aiortc/aiohttp sont installés et si l'exposition est sûre."""
    if not cfg.clients:
        log.warning("aucun client autorisé ([[clients]]) : pas d'API, le poste reste en réception seule")
        return None, None
    problem = exposure_problem(cfg)
    if problem:
        log.error("API NON DÉMARRÉE (réception seule) : %s", problem)    # on ne quitte pas : le superviseur redémarrerait la station
        return None, None
    try:
        from .api.auth import ClientRegistry
        from .api.server import make_app, start_server
        from .api.tls import make_ssl_context
        from .api.webrtc import PeerManager
    except ImportError as exc:
        log.error("API WebRTC indisponible (%s) : pip install -e \".[audio]\" ; réception seule", exc)
        return None, None
    ssl_context = None
    if cfg.network.tls_cert and cfg.network.tls_key:
        try:
            ssl_context = make_ssl_context(cfg.network.tls_cert, cfg.network.tls_key)
        except (OSError, ssl.SSLError) as exc:
            log.error("API NON DÉMARRÉE (réception seule) : certificat TLS inutilisable (%s)", exc)
            return None, None
    memories = MemoryStore(Path(cfg.supervisor.state_dir) / "memories.json")
    layouts = LayoutStore(Path(cfg.supervisor.state_dir) / "layouts")     # profils de mise en page (designer)
    reports = ReportStore(Path(cfg.supervisor.state_dir) / "reports", version=__version__)   # « Signaler un problème »
    manager = PeerManager(ctrl, link, pipeline, capabilities, ice_servers=cfg.network.ice_servers, memories=memories,
                          layouts=layouts, spectrum=spectrum, reports=reports)
    app = make_app(ClientRegistry(cfg.clients), manager, web_client=cfg.network.web_client,
                   trusted_proxies=cfg.network.trusted_proxies, ice_servers=cfg.network.ice_servers,
                   rig_audio=real_device_names(cfg.audio.capture_device, cfg.audio.playback_device))
    try:
        runner = await start_server(app, cfg.network.gateway_bind, cfg.network.gateway_port, ssl_context)
    except OSError as exc:                         # on ne quitte pas : le superviseur relancerait la passerelle en boucle
        log.error("API NON DÉMARRÉE (réception seule) : écoute impossible sur %s:%s (%s). %s",
                  cfg.network.gateway_bind, cfg.network.gateway_port, exc, bind_hint(cfg.network.gateway_bind))
        return None, None
    log.info("API WebRTC%s en écoute en %s sur %s:%s", " et page web" if cfg.network.web_client else "",
             "HTTPS" if ssl_context else "HTTP", cfg.network.gateway_bind, cfg.network.gateway_port)
    return manager, runner


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-gateway", description="Passerelle de la station TRX")
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--parent-pid", type=int, default=None, help="mode géré : quitter si ce processus disparaît")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = cfgmod.load(args.config)
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        install_quiet_handler(loop)
        stop = asyncio.Event()
        for name in ("SIGTERM", "SIGINT", "SIGBREAK"):     # SIGBREAK : CTRL_BREAK_EVENT sous Windows
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), lambda *_: loop.call_soon_threadsafe(stop.set))
        await run(cfg, stop=stop, parent_pid=args.parent_pid)

    try:
        asyncio.run(_main())
    except AudioConfigError as exc:
        print(f"Audio : {exc}", file=sys.stderr)
        return 5
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
