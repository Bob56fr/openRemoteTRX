"""Point d'entrée du superviseur : `python -m trxstation.supervisor.main` (unit systemd Type=notify)."""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .. import config as cfgmod
from ..paths import default_config_path
from ..ports import port_present
from ..procutil import acquire_instance_lock
from ..modules.supervisor_glue import build_launcher, make_tick, start_modules
from ..status import read_status
from .actions import SystemActions
from .backends import choose_backend
from .core import Supervisor
from .rigctl import RigctlProbe
from .sdnotify import sd_notify
from .state import StateStore

log = logging.getLogger("trx-supervisor")
MAX_CONSECUTIVE_FAILURES = 5
TX_POLL_S = 0.25


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
            log.exception("erreur dans la boucle de supervision (%d/%d)", failures, MAX_CONSECUTIVE_FAILURES)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                return 1                      # systemd (Restart=always) nous relance proprement
        notify("WATCHDOG=1")
        sleep(TX_POLL_S if sup.tx_active else poll_interval_s)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-supervisor", description="Superviseur autonome de la station TRX")
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--clear-safe-mode", action="store_true", help="sort du mode sûr (action de l'opérateur)")
    ap.add_argument("--status", action="store_true", help="affiche le mode sûr et l'historique des redémarrages")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = cfgmod.load(args.config)
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    store = StateStore(cfg.supervisor.state_dir)
    if args.clear_safe_mode:
        store.clear_safe_mode()
        print("Mode sûr désactivé. La passerelle peut être relancée : systemctl start", cfg.supervisor.gateway_unit)
        return 0
    if args.status:
        print("mode sûr :", store.safe_mode() or "non")
        print("redémarrages enregistrés :", store.reboot_times())
        return 0

    lock = acquire_instance_lock(cfg.supervisor.instance_lock_port)
    if lock is None:
        print("Un superviseur est déjà en cours d'exécution (port de verrouillage "
              f"{cfg.supervisor.instance_lock_port} occupé).", file=sys.stderr)
        return 4
    status_path = cfg.supervisor.status_path
    probe = RigctlProbe(cfg.network.rigctld_host, cfg.network.rigctld_port)
    backend = choose_backend(cfg, args.config, store)
    sup = Supervisor(cfg, read_status=lambda: read_status(status_path), probe_rig=probe.read,
                     actions=SystemActions(cfg, backend), store=store, port_exists=port_present)
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
    launcher = None
    try:
        launcher = build_launcher(cfg, alert=sup.actions.notifier.send)   # [modules] run vide : None
        start_modules(launcher)
    except Exception:
        log.exception("modules non lancés : la station fonctionne sans eux")
        launcher = None
    try:
        return run_forever(sup, cfg.supervisor.poll_interval_s, stop=lambda: stopping,
                           tick=make_tick(backend.maintain, launcher))
    finally:
        if launcher is not None:
            try:
                launcher.stop_all()
            except Exception:
                log.exception("arrêt des modules incomplet")
        backend.stop_all()                                    # no-op sous systemd


if __name__ == "__main__":
    raise SystemExit(main())
