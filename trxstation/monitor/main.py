"""trx-monitor : `trx-monitor` (TUI Textual) ou `trx-monitor --once` (capture texte, sans Textual)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import config as cfgmod
from ..paths import default_config_path
from .actions import stop_tx
from .model import build_panels, render_plain
from .source import StatusSource


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-monitor", description="Tableau de bord de la station TRX")
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--once", action="store_true", help="affiche une capture de l'état en texte puis quitte")
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except cfgmod.ConfigError as exc:
        print("Configuration invalide :\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    source = StatusSource(cfg.supervisor.status_path, cfg.supervisor.state_dir, cfg.supervisor.stale_after_s)
    if args.once:
        print(render_plain(build_panels(source.poll_once())), end="")
        return 0
    try:
        from .app import run_tui
    except ImportError:
        print("Textual n'est pas installé : pip install -e \".[monitor]\"  (ou utilisez --once)", file=sys.stderr)
        return 3
    return run_tui(source, lambda: stop_tx(cfg))


if __name__ == "__main__":
    raise SystemExit(main())
