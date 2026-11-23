# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Point d'entrée du superviseur : `python -m trxstation.supervisor.main` (unit systemd Type=notify)."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .. import config as cfgmod
from ..errors import codes
from ..errors.emit import emit_event
from ..heatlog import FILE_NAME as HEAT_FILE, HeatLog
from ..logsetup import LOG_DIR_ENV, add_json_journal, setup_logging
from ..paths import default_config_path
from ..ports import port_present
from ..procutil import acquire_instance_lock
from ..modules.supervisor_glue import build_launcher, make_tick, start_modules
from ..status import read_status
from .actions import SystemActions
from .backends import GuardUnavailable, choose_backend
from .core import Supervisor, default_read_host
from .rigctl import RigctlProbe
from .runmark import RunMark
from .sdnotify import sd_notify
from .state import StateStore

log = logging.getLogger("trx-supervisor")
MAX_CONSECUTIVE_FAILURES = 5
TX_POLL_S = 0.25
STOP_REQUEST = "stop_request"      # fichier déposé par `--stop` (Windows : station sans fenêtre, pas de Ctrl+C)
STOP_WAIT_S = 30.0


def stop_request_path(cfg) -> Path:
    return Path(cfg.supervisor.state_dir) / STOP_REQUEST


def request_stop(cfg, *, wait_s: float = STOP_WAIT_S, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> int:
    """Demande l'arrêt au superviseur en marche et attend qu'il ait fini (passerelle d'abord : retour RX)."""
    probe = acquire_instance_lock(cfg.supervisor.instance_lock_port)
    if probe is not None:
        probe.close()
        print("La station est déjà arrêtée.")
        return 0
    path = stop_request_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("arrêt demandé\n", encoding="utf-8")
    deadline = clock() + wait_s
    while clock() < deadline:
        sleep(0.5)
        probe = acquire_instance_lock(cfg.supervisor.instance_lock_port)
        if probe is not None:
            probe.close()
            print("Station arrêtée (le poste est en réception).")
            return 0
    print(f"La station ne s'est pas arrêtée en {wait_s:.0f} s : regarde ses journaux.", file=sys.stderr)
    return 5


def run_forever(sup: Supervisor, poll_interval_s: float, *, stop: Callable[[], bool] = lambda: False,
                sleep: Callable[[float], None] = time.sleep, notify: Callable[[str], object] = sd_notify,
                tick: Callable[[], None] = lambda: None) -> int:
    notify("READY=1")
    failures = 0
    while not stop():
        try:
            tick()                    # mode géré : relance les processus arrêtés
            sup.step()
            failures = 0
        except Exception:
            failures += 1
            emit_event(codes.ORT_8014, logger=log, trace=True, n=failures, max=MAX_CONSECUTIVE_FAILURES)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                return 1                      # systemd (Restart=always) nous relance proprement
        notify("WATCHDOG=1")
        sleep(TX_POLL_S if sup.tx_active else poll_interval_s)
    return 0


def _with_mark(tick: Callable[[], None], runmark: RunMark) -> Callable[[], None]:
    """Passage de supervision, puis le dernier signe de vie du témoin de marche (une écriture par minute)."""
    def run() -> None:
        tick()
        runmark.refresh()
    return run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-supervisor", description="Superviseur autonome de la station TRX")
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--clear-safe-mode", action="store_true", help="réactive la station après une mise en sécurité (action de l'opérateur)")
    ap.add_argument("--status", action="store_true", help="affiche la mise en sécurité et l'historique des redémarrages")
    ap.add_argument("--stop", action="store_true", help="arrête proprement le superviseur en marche (et la station)")
    ap.add_argument("--log-dir", type=Path, help="journaux dans ce dossier (aussi pour la passerelle et rigctld)")
    args = ap.parse_args(argv)
    if args.log_dir is not None:
        os.environ[LOG_DIR_ENV] = str(args.log_dir)        # transmis aux processus lancés par le superviseur
    setup_logging("superviseur")
    try:
        cfg = cfgmod.load(args.config)
    except FileNotFoundError:
        # PC sans station installée (ex. PC de la valise, essai du 2026-11-19) : plus de trace Python
        if args.stop:
            print(f"Aucune station installée sur ce PC ({args.config} absent) : rien à arrêter.")
            return 0
        print(f"Configuration absente : {args.config} (installer la station, ou donner --config).", file=sys.stderr)
        return 2
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    store = StateStore(cfg.supervisor.state_dir)
    if args.clear_safe_mode:
        store.clear_safe_mode()
        print("Station réactivée (mise en sécurité levée). La passerelle peut être relancée : systemctl start", cfg.supervisor.gateway_unit)
        return 0
    if args.status:
        print("mise en sécurité :", store.safe_mode() or "non")
        print("redémarrages enregistrés :", store.reboot_times())
        return 0
    if args.stop:
        return request_stop(cfg)

    lock = acquire_instance_lock(cfg.supervisor.instance_lock_port)
    if lock is None:
        print("Un superviseur est déjà en cours d'exécution (port de verrouillage "
              f"{cfg.supervisor.instance_lock_port} occupé).", file=sys.stderr)
        return 4
    add_json_journal("superviseur", cfg.supervisor.state_dir)
    runmark = RunMark(cfg.supervisor.state_dir)
    unclean = runmark.start()                                 # arrêt précédent non propre ? (étape 355)
    stop_file = stop_request_path(cfg)
    stop_file.unlink(missing_ok=True)                         # demande d'arrêt d'une session précédente : oubliée
    status_path = cfg.supervisor.status_path
    probe = RigctlProbe(cfg.network.rigctld_host, cfg.network.rigctld_port)
    backend = choose_backend(cfg, args.config, store)
    host_paths = tuple(dict.fromkeys([cfg.supervisor.state_dir, os.path.abspath(os.sep)]))   # dossier d'état, racine
    heat = HeatLog(Path(cfg.supervisor.state_dir) / HEAT_FILE)     # historique de chauffe (Linux seulement)
    heat = heat if heat.available else None
    sup = Supervisor(cfg, read_status=lambda: read_status(status_path), probe_rig=probe.read,
                     actions=SystemActions(cfg, backend), store=store, port_exists=port_present,
                     read_host=lambda: default_read_host(host_paths), heat=heat)
    if unclean is not None:
        sup.actions.notifier.alert(codes.ORT_8030 if unclean.machine else codes.ORT_8031,
                                   dernier_signe=time.strftime("%Y-%m-%d %H:%M", time.localtime(unclean.last_seen)))
    stopping = False

    def _stop(*_: object) -> None:
        nonlocal stopping
        stopping = True
    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):           # SIGBREAK : Windows
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop)
    try:
        backend.start()
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 3
    except GuardUnavailable as exc:
        # Fail-safe (cahier du Microsoft Store § 4.1) : sans garde de fin, aucune station ; rien n'a été lancé.
        sup.actions.notifier.alert(codes.ORT_8026, raison=str(exc))
        return 5
    launcher = None
    try:
        launcher = build_launcher(cfg, alert=sup.actions.notifier.alert, config_path=args.config)   # [modules] run vide : None
        start_modules(launcher)
    except Exception:
        emit_event(codes.ORT_8024, logger=log, trace=True, action="lancement", erreur="voir la trace")
        launcher = None
    try:
        return run_forever(sup, cfg.supervisor.poll_interval_s, stop=lambda: stopping or stop_file.exists(),
                           tick=_with_mark(make_tick(backend.maintain, launcher), runmark))
    finally:
        if launcher is not None:
            try:
                launcher.stop_all()
            except Exception:
                emit_event(codes.ORT_8024, logger=log, trace=True, action="arrêt", erreur="voir la trace")
        backend.stop_all(force_rx=sup.actions.force_rx)       # no-op sous systemd ; « T 0 » avant d'arrêter rigctld
        stop_file.unlink(missing_ok=True)
        runmark.clean_stop()                                  # arrêt propre : témoin retiré


if __name__ == "__main__":
    raise SystemExit(main())
