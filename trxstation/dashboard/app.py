# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Boucle principale : lit la station et le PC, tient l'historique, sert la page."""
from __future__ import annotations

import asyncio
import contextlib
import socket
import logging
import time

from aiohttp import web

from ..errors import codes
from ..errors.emit import emit_event
from . import __version__, demo, server, view
from .settings import Settings
from .history import DAY_S, History
from .hostmetrics import HostMonitor
from .netcheck import InternetWatch
from .station import JournalTail, StationReader, heat_history

log = logging.getLogger(__name__)
READ_EVERY_S = 1.0
SAMPLE_EVERY_S = 60.0
SERVICES_EVERY_S = 10.0
JOURNAL_EVERY_S = 5.0
SAVE_EVERY_S = 300.0
ADDRESSES_EVERY_S = 60.0


class AddressesChanged(Exception):
    """Adresses automatiques changées (étape 386) : le service quitte pour être relancé par systemd au bon endroit."""


class Dashboard:
    def __init__(self, cfg: Settings, demo_mode: bool = False):
        self.cfg, self.demo = cfg, demo_mode
        self.history = History(None if demo_mode else cfg.history_path)
        self.host = HostMonitor()
        self.internet = InternetWatch(cfg.internet_targets, cfg.internet_every_s)
        self.reader = None if demo_mode else StationReader(cfg.status_path, cfg.state_dir, cfg.station_toml,
                                                           rig_name=cfg.rig_name, rig_max_w=cfg.rig_max_w)
        self.journal = None if demo_mode else JournalTail(cfg.state_dir)
        self.state: dict = {}
        self._host_now: dict = {}
        self._minute: list[dict] = []        # relevés du PC de la minute en cours
        self._flags: dict[str, bool] = {}    # états qui déclenchent une alerte « maison » au changement
        self.view_cfg = {"station_name": socket.gethostname(), "accounts": [], "version": __version__}

    # ------------------------------------------------------------------ démarrage

    def prime(self) -> None:
        if self.demo:
            demo.fill_history(self.history)
            return
        self.history.load()
        since = time.time() - DAY_S
        if not self.history.samples:                 # premier démarrage : 24 h de chauffe du superviseur
            for s in heat_history(self.cfg.state_dir, since):
                self.history.samples.append({"t": s["t"], "cpu": s["cpu"], "mem": None, "temp": s["temp"], "net": None})
        for a in self.journal.initial(since):
            self.history.add_alert(a["key"], a["level"], a["text"], a["t"])

    # ------------------------------------------------------------------ boucles

    async def loop_read(self) -> None:
        last_host = 0.0
        while True:
            now = time.monotonic()
            if now - last_host >= 2.0:
                self._host_now = demo.host() if self.demo else self.host.read()
                self._minute.append(self._host_now)
                last_host = now
            raw = demo.vitals() if self.demo else self.reader.read()
            v = view.merge(view.vitals_template(), raw)
            v["host"] = view.merge(v["host"], self._host_now)
            v["internet"] = view.merge(v["internet"], self.internet.last or {})
            if self.demo:
                v["internet"] = {"up": True, "ms": 18.0}
            self._watch(v)
            aw, ac = self.history.alert_counts()
            info = {"internet_pct": self.history.internet_pct(), "alerts_warn": aw, "alerts_crit": ac}
            try:
                self.view_cfg["accounts"] = demo.ACCOUNTS if self.demo else self.reader.accounts
                self.state = view.build_state(v, info, self.view_cfg)
            except Exception:                              # un état inattendu ne doit pas arrêter l'affichage
                emit_event(codes.ORT_6569, logger=log, trace=True, etape="mise en forme de l'état")
            await asyncio.sleep(READ_EVERY_S)

    def _watch(self, v: dict) -> None:
        """Alertes vues par le tableau lui-même (en plus des journaux de la station), au changement d'état."""
        checks = {
            "station_muette": (not v["station"]["ok"], "crit", "Station muette : plus d'état de la passerelle"),
            "mise_en_securite": (v["safe"]["active"], "crit", "Mise en sécurité de la station"),
            "cat_perdue": (v["rig"]["connected"] is False, "crit", "Liaison CAT perdue"),
            "internet": (v["internet"]["up"] is False, "warn", "Internet injoignable"),
        }
        for key, (active, level, text) in checks.items():
            if active and not self._flags.get(key) and not self.demo:
                self.history.add_alert(f"tableau|{key}|{int(time.time())}", level, text)
            self._flags[key] = active

    async def loop_sample(self) -> None:
        while True:
            await asyncio.sleep(SAMPLE_EVERY_S)
            if self.demo:
                continue
            rows, self._minute = self._minute, []
            avg = lambda k: (sum(r[k] for r in rows if r.get(k) is not None) / n
                             if (n := sum(1 for r in rows if r.get(k) is not None)) else None)
            net = self.internet.last["up"] if self.internet.last else None
            self.history.add_sample(avg("cpu"), avg("mem"), max((r["temp"] for r in rows if r.get("temp") is not None),
                                                                default=None), net)

    async def loop_services(self) -> None:
        while True:
            if self.reader:
                try:
                    await self.reader.refresh_services()
                except Exception:
                    emit_event(codes.ORT_6569, logger=log, trace=True, etape="lecture de l'état des services")
            await asyncio.sleep(SERVICES_EVERY_S)

    async def loop_journal(self) -> None:
        while True:
            await asyncio.sleep(JOURNAL_EVERY_S)
            if self.journal:
                for a in self.journal.new():
                    self.history.add_alert(a["key"], a["level"], a["text"], a["t"])

    async def loop_addresses(self) -> None:
        """Adresses automatiques : une adresse arrivée après le démarrage ou changée = sortie pour relance."""
        while True:
            await asyncio.sleep(ADDRESSES_EVERY_S)
            try:
                now = self.cfg.reresolve()
            except Exception:
                continue
            if sorted(now) != sorted(self.cfg.listen):
                log.info("adresses du tableau de bord changées (%s -> %s) : relance du service",
                         ", ".join(self.cfg.listen), ", ".join(now))
                self.save()
                raise AddressesChanged(", ".join(now))

    async def loop_save(self) -> None:
        while True:
            await asyncio.sleep(SAVE_EVERY_S)
            self.save()

    def save(self) -> None:
        try:
            self.history.save()
        except OSError as exc:
            emit_event(codes.ORT_6570, logger=log, erreur=str(exc))

    # ------------------------------------------------------------------ service

    async def run(self) -> None:
        self.prime()
        hosts = server.allowed_hosts(self.cfg.listen, self.cfg.port, self.cfg.hosts)
        app = server.make_app(lambda: self.state, lambda: view.history_view(self.history.view()),
                              hosts=hosts)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        ctx = server.ssl_context(self.cfg.tls_cert, self.cfg.tls_key)
        for addr in self.cfg.listen:
            # TLS sur les adresses du réseau seulement : le certificat de la station ne couvre pas 127.0.0.1,
            # et l'écran local n'a pas besoin de chiffrement
            site_ctx = None if server.is_loopback(addr) else ctx
            await web.TCPSite(runner, addr, self.cfg.port, ssl_context=site_ctx).start()
            log.info("page servie sur %s://%s:%d/", "https" if site_ctx else "http",
                     f"[{addr}]" if ":" in addr else addr, self.cfg.port)
        tasks = [asyncio.create_task(c) for c in (self.loop_read(), self.loop_sample(), self.loop_services(),
                                                   self.loop_journal(), self.loop_save(),
                                                   *(() if self.demo else (self.internet.run(),)),
                                                   *((self.loop_addresses(),) if self.cfg.reresolve else ()))]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            with contextlib.suppress(Exception):
                await runner.cleanup()
            if not self.demo:
                self.save()
