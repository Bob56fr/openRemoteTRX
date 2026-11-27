# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Pages de secours tenues par le superviseur (étape 405, `trxstation/fallback_page.py`).

- Port de la page de pilotage : servi SEULEMENT pendant une mise en sécurité (passerelle arrêtée par le superviseur).
  Jamais pendant un redémarrage de la passerelle : elle ne doit jamais trouver son port pris.
- Port de la console web : servi tant que [remote_console] est désactivée (station.toml relue à chaque changement :
  le menu 4.6 ne redémarre pas le superviseur).

Le port est LIBÉRÉ dès que la page n'a plus lieu d'être : `sync()` est appelée à chaque tour du superviseur AVANT
la relance des processus (Windows), et par un fil toutes les 0,25 s (systemd, menu 1.4 : `--clear-safe-mode`
attend en plus que le port soit libre). Un port déjà pris par autre chose : réessayé au plus toutes les 30 s.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable

from .. import config as cfgmod
from ..fallback_page import FallbackServer, is_local

RETRY_S = 30.0
WATCH_S = 0.25


class FallbackPages:
    def __init__(self, cfg: cfgmod.Config, config_path: str | Path | None, safe_mode: Callable[[], str | None], *,
                 clock: Callable[[], float] = time.monotonic, factory=FallbackServer):
        self.cfg, self.config_path, self._safe_mode = cfg, Path(config_path) if config_path else None, safe_mode
        self._clock, self._factory = clock, factory
        self._lock = threading.Lock()
        self._servers: dict[str, FallbackServer] = {}
        self._next_try: dict[str, float] = {}
        self._mtime: float | None = None
        self._console_enabled = cfg.remote_console.enabled is True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ ce qui doit être servi

    def _refresh_config(self) -> None:
        """Relit [remote_console] enabled quand station.toml change (fichier illisible : réglage précédent gardé)."""
        if self.config_path is None:
            return
        try:
            mtime = os.stat(self.config_path).st_mtime
        except OSError:
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        try:
            cfg, _ = cfgmod.load_unchecked(self.config_path)
        except (cfgmod.ConfigError, OSError):
            return
        self._console_enabled = cfg.remote_console.enabled is True

    def wanted(self) -> dict[str, tuple[str, int]]:
        """{genre: (adresse, port)} des pages à servir maintenant."""
        n = self.cfg.network
        tls = bool(n.tls_cert and n.tls_key)
        out: dict[str, tuple[str, int]] = {}
        try:
            safe = self._safe_mode() is not None
        except Exception:
            safe = False
        # page de pilotage : même exposition que la passerelle (TLS, ou machine seule)
        if safe and (tls or is_local(n.gateway_bind)):
            out["safe_mode"] = (n.gateway_bind, n.gateway_port)
        # console web désactivée : seulement sur le réseau et en TLS (comme la vraie console)
        if not self._console_enabled and tls and not is_local(n.gateway_bind):
            out["console_off"] = (n.gateway_bind, self.cfg.remote_console.port)
        return out

    # ------------------------------------------------------------------ ouverture et libération

    def sync(self) -> None:
        """Libère d'abord ce qui n'a plus lieu d'être, puis ouvre ce qui manque. Jamais d'exception."""
        with self._lock:
            try:
                self._refresh_config()
                want = self.wanted()
                for kind in [k for k in self._servers if k not in want]:
                    self._servers.pop(kind).stop()
                    self._next_try.pop(kind, None)
                now = self._clock()
                n = self.cfg.network
                for kind, (host, port) in want.items():
                    if kind in self._servers or now < self._next_try.get(kind, 0.0):
                        continue
                    tls = bool(n.tls_cert and n.tls_key)
                    server = self._factory(kind, host, port, n.tls_cert if tls else "", n.tls_key if tls else "")
                    if server.start():
                        self._servers[kind] = server
                    else:
                        self._next_try[kind] = now + RETRY_S
            except Exception:                                   # une page de secours ne gêne jamais la surveillance
                pass

    def serving(self) -> set[str]:
        return set(self._servers)

    def start(self) -> None:
        self.sync()
        self._thread = threading.Thread(target=self._watch, name="fallback-pages", daemon=True)
        self._thread.start()

    def _watch(self) -> None:
        while not self._stop.wait(WATCH_S):
            self.sync()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._lock:
            for server in self._servers.values():
                server.stop()
            self._servers.clear()
