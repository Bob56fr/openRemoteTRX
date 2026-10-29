# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module Cluster DX : processus séparé lancé et surveillé par le superviseur (`[modules] run = ["cluster"]`).

Il ne parle JAMAIS au poste : aucun droit sur le bus (ni PTT ni QSY), seulement
des messages d'état vers les pages. Une panne ici n'atteint ni rigctld ni l'audio.

- configuration : `[cluster]` de station.toml (chemin dans TRX_CONFIG_PATH, donné par le superviseur) ;
- mots de passe : secrets.toml à côté, droits vérifiés au démarrage (corrigés si possible) ;
- état : `<state_dir>/cluster/status.json` toutes les 5 s (lu par le diagnostic et le rapport) ;
- journal : `<state_dir>/cluster/cluster.log`, 5 fichiers de 1 Mo, jamais de secret ;
- cty.dat : `<state_dir>/cluster/cty.dat`, mis à jour chaque semaine.

À la main (essai) :  python -m trxstation.cluster.service --config station.toml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import sys
import tempfile
import time
from pathlib import Path

from .. import config as cfgmod
from .. import secretstore
from ..paths import default_config_path
from ..status import replace_atomic
from . import cty as ctymod
from .cache import SpotCache, SpotFilter
from .engine import Engine
from .feed import CONNECTED, FAILED, Feed, Source
from .publish import SpotPublisher

log = logging.getLogger("trx.cluster")

STATUS_EVERY_S = 5.0
PUBLISH_EVERY_S = 1.0               # spots vers les pages : changements regroupés (marqueur < 2 s après réception)
EXPIRE_EVERY_S = 30.0
CTY_CHECK_EVERY_S = 6 * 3600.0
STALE_SPOT_S = 15 * 60.0
GREEN, ORANGE, RED, OFF = "green", "orange", "red", "off"
HEALTH_TEXT = {GREEN: "toutes les sources connectées", ORANGE: "sources en partie connectées",
               RED: "aucune source connectée", OFF: "désactivé"}
# État des flux pour les pages (« le cluster reçoit-il quelque chose ? ») : toutes les PAGE_STATUS_EVERY écritures
# de status.json (5 s chacune), et à chaque changement de pastille. Un flux connecté mais sans spot depuis
# QUIET_AFTER_S n'est pas en panne : il est « calme » (bande fermée, filtres) ; le délai dépend de sa vitesse habituelle.
PAGE_STATUS_EVERY = 3
QUIET_AFTER_S = {"rbn": 5 * 60.0, "telnet": 30 * 60.0, "web": 2 * 3600.0}
MAX_PAGE_SOURCES = 12


def cluster_dir(cfg: cfgmod.Config) -> Path:
    return Path(cfg.supervisor.state_dir) / "cluster"


def status_path(cfg: cfgmod.Config) -> Path:
    return cluster_dir(cfg) / "status.json"


def build_sources(c: cfgmod.Cluster, secrets: dict[str, str]) -> tuple[list[Source], list[str]]:
    """Sources actives de la configuration ; (sources, problèmes lisibles, jamais de valeur secrète)."""
    out, problems = [], []
    for s in c.source:
        if not s.enabled:
            continue
        password = None
        if s.secret:
            password = secrets.get(s.secret)
            if password is None:
                problems.append(f"{s.name} : mot de passe « {s.secret} » absent de secrets.toml (connexion sans)")
        out.append(Source(s.name, s.type, s.host, s.port, s.priority, True, s.call, password, s.url))
    return out, problems


def build_cache(c: cfgmod.Cluster, table: ctymod.Cty) -> SpotCache:
    flt = SpotFilter(bands=frozenset(c.bands), modes=frozenset(c.modes), continents=frozenset(c.continents),
                     blacklist=frozenset(c.blacklist))
    return SpotCache(table, flt, ttl_s={"cluster": c.ttl_min * 60.0, "cb": c.ttl_min * 60.0,
                                        "rbn": c.rbn_ttl_min * 60.0})


def health(feed: Feed | None, engine: Engine | None) -> str:
    if feed is None:
        return OFF
    states = [feed.states[s.name].state for s in feed.sources if s.enabled]
    # clusters : une seule connexion à la fois ; le groupe est « connecté » si l'un l'est
    groups: dict[str, bool] = {}
    for s in feed.sources:
        if s.enabled:
            key = "clusters" if s.kind == "telnet" else s.name
            groups[key] = groups.get(key, False) or feed.states[s.name].state == CONNECTED
    if not states or not any(groups.values()):
        return RED
    if not all(groups.values()):
        return ORANGE
    age = engine.last_spot_age() if engine is not None else None
    return ORANGE if age is None or age > STALE_SPOT_S else GREEN


def snapshot(feed: Feed | None, engine: Engine | None, *, enabled: bool, seq: int,
             cty_problem: str | None, cty_entities: int, problems: list[str]) -> dict:
    sources = {}
    if feed is not None:
        for s in feed.sources:
            st = feed.states[s.name]
            sources[s.name] = {"type": s.kind, "address": s.address, "state": st.state, "code": st.last_code,
                               "message": st.last_message[:200], "cluster_type": st.cluster_type,
                               "connects": st.connects, "retry_in_s": st.retry_in_s}
    return {"version": 1, "seq": seq, "time": time.time(), "pid": os.getpid(), "enabled": enabled,
            "health": health(feed, engine), "sources": sources,
            "streams": {} if feed is None else {k: {"losses": v.losses, "recovered": v.recovered}
                                                 for k, v in feed.streams.items()},
            "counters": {} if engine is None else engine.counters(),
            "cty": {"entities": cty_entities, "problem": cty_problem}, "problems": problems[:20]}


def page_summary(feed: Feed | None, engine: Engine | None) -> dict:
    """Résumé COURT pour les pages : pastille et, par flux, verdict, spots des 10 dernières minutes, âge du dernier."""
    sources = []
    if feed is not None:
        active = [s for s in feed.sources if s.enabled]
        cluster_up = any(s.kind == "telnet" and feed.states[s.name].state == CONNECTED for s in active)
        for s in active[:MAX_PAGE_SOURCES]:
            st = feed.states[s.name]
            stats = engine.source_stats(s.name) if engine is not None else {"last_10min": 0, "last_spot_age_s": None}
            age = stats["last_spot_age_s"]
            if st.state == CONNECTED:
                verdict = "ok" if age is not None and age <= QUIET_AFTER_S.get(s.kind, 30 * 60.0) else "calme"
            elif s.kind == "telnet" and cluster_up:
                verdict = "reserve"                     # clusters : un seul connecté à la fois, les autres en secours
            elif st.state == FAILED:
                verdict = "echec"
            else:
                verdict = "attente"
            sources.append({"name": s.name[:40], "type": s.kind, "verdict": verdict, "last_10min": stats["last_10min"],
                            "last_spot_age_s": age, "retry_in_s": st.retry_in_s, "code": (st.last_code or "")[:40]})
    # Spots actifs par bande (ceux du cache : filtres de l'utilisateur appliqués, expirés retirés) : pastilles des boutons.
    bands: dict[str, int] = {}
    spots = getattr(engine.cache, "spots", None) if engine is not None else None
    if callable(spots):
        for spot in spots():
            if spot.band:
                bands[spot.band] = bands.get(spot.band, 0) + 1
    return {"kind": "cluster_status", "health": health(feed, engine), "sources": sources, "bands": bands}


def write_status(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".status-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        if os.name == "posix":
            os.chmod(tmp, 0o644)                  # lu par le diagnostic (compte de bureau)
        replace_atomic(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def setup_logging(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s cluster %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        handler = logging.handlers.RotatingFileHandler(folder / "cluster.log", maxBytes=1_000_000, backupCount=4,
                                                       encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError as exc:
        log.warning("journal %s impossible : %s", folder / "cluster.log", exc)


def load_secrets(config_path: Path) -> tuple[dict[str, str], list[str]]:
    path = secretstore.path_for(config_path)
    problems: list[str] = []
    if not path.exists():
        return {}, problems
    issue = secretstore.permission_problem(path)
    if issue:
        try:
            secretstore.fix_permissions(path)
            log.warning("secrets.toml : %s ; corrigé en 0600", issue)
        except OSError:
            problems.append(f"secrets.toml : {issue} (correction impossible : sudo chmod 600 {path})")
    try:
        return secretstore.load(path), problems
    except secretstore.SecretsError as exc:
        return {}, problems + [str(exc)]


class ClusterService:
    def __init__(self, cfg: cfgmod.Config, config_path: Path, *, bus_client=None) -> None:
        self.cfg, self.config_path, self.bus = cfg, config_path, bus_client
        self.dir = cluster_dir(cfg)
        self.status_file = status_path(cfg)
        self.cty_path = self.dir / "cty.dat"
        self.feed: Feed | None = None
        self.engine: Engine | None = None
        self.problems: list[str] = []
        self.cty_problem: str | None = None
        self.cty_entities = 0
        self.seq = 0
        self._last_health: str | None = None
        self.publisher: SpotPublisher | None = None
        if bus_client is not None:
            bus_client.on_event = self._on_event
            bus_client.on_connect = bus_client.on_gap = self._resync

    async def _on_event(self, name: str, data: dict) -> None:
        if name == "freq_mode" and self.publisher is not None:
            self.publisher.set_frequency(data.get("freq"))

    async def _resync(self) -> None:
        """(Re)connexion au cœur ou événement perdu : relire la fréquence, renvoyer un instantané."""
        try:
            state = await self.bus.get_state()
        except Exception as exc:
            log.debug("état du poste illisible : %s", exc)
            return
        if self.publisher is not None:
            self.publisher.set_frequency(state.get("freq"))
            self.publisher._need_snapshot = True
        self._last_health = None                  # la pastille sera renvoyée

    async def _publish_loop(self) -> None:
        while True:
            await asyncio.sleep(PUBLISH_EVERY_S)
            if self.publisher is None or self.bus is None:
                continue
            now = time.monotonic()
            for message in (self.publisher.tick(now), self.publisher.recent(now)):
                if message is None:
                    continue
                try:
                    await self.bus.client_message(**message)
                except Exception as exc:          # message perdu : l'instantané suivant remettra la page d'aplomb
                    self.publisher._need_snapshot = True
                    self.publisher._recent_dirty = True
                    log.debug("spots non transmis : %s", exc)

    def _status(self) -> None:
        self.seq += 1
        data = snapshot(self.feed, self.engine, enabled=self.cfg.cluster.enabled, seq=self.seq,
                        cty_problem=self.cty_problem, cty_entities=self.cty_entities, problems=self.problems)
        try:
            write_status(self.status_file, data)
        except OSError as exc:
            log.warning("état %s non écrit : %s", self.status_file, exc)
        changed = data["health"] != self._last_health
        if changed:
            self._last_health = data["health"]
            log.info("état : %s", HEALTH_TEXT[data["health"]])
            asyncio.ensure_future(self._tell_clients(data["health"]))
        if changed or self.seq % PAGE_STATUS_EVERY == 0:
            asyncio.ensure_future(self._tell_status())

    async def _tell_status(self) -> None:
        """État des flux pour les pages (message facultatif : une page absente ne gêne rien)."""
        if self.bus is None:
            return
        try:
            await self.bus.client_message(**page_summary(self.feed, self.engine))
        except Exception as exc:
            log.debug("état des flux non transmis : %s", exc)

    async def _tell_clients(self, state: str) -> None:
        if self.bus is None:
            return
        try:
            await self.bus.client_message(kind="module_state", module="cluster", health=state,
                                          text=f"Cluster DX : {HEALTH_TEXT[state]}")
        except Exception as exc:                  # message facultatif : la page peut être absente
            log.debug("message aux pages refusé : %s", exc)

    async def _update_cty(self) -> None:
        try:
            table = await asyncio.to_thread(ctymod.download, self.cty_path)
        except Exception as exc:
            log.warning("mise à jour de cty.dat impossible : %s", exc)
            return
        if self.engine is not None:
            self.engine.cache.cty = table
        self.cty_entities, self.cty_problem = len(table), None
        log.info("cty.dat mis à jour (%d entités)", len(table))

    async def _housekeeping(self) -> None:
        last_expire = last_cty = time.monotonic()
        while True:
            now = time.monotonic()
            if self.engine is not None and now - last_expire >= EXPIRE_EVERY_S:
                self.engine.cache.expire(now)
                last_expire = now
            if self.cfg.cluster.cty_update and now - last_cty >= CTY_CHECK_EVERY_S:
                last_cty = now
                if ctymod.is_stale(self.cty_path):
                    await self._update_cty()
            self._status()
            await asyncio.sleep(STATUS_EVERY_S)

    async def run(self) -> None:
        c = self.cfg.cluster
        tasks = [asyncio.ensure_future(self._housekeeping())]
        if self.bus is not None:
            tasks.append(asyncio.ensure_future(self._bus_forever()))
        if not c.enabled:
            log.info("[cluster] désactivé : le module attend sans rien faire")
            await asyncio.gather(*tasks)
            return
        secrets, self.problems = load_secrets(self.config_path)
        sources, more = build_sources(c, secrets)
        self.problems += more
        for p in self.problems:
            log.warning("%s", p)
        table, self.cty_problem = ctymod.load_or_empty(self.cty_path)
        self.cty_entities = len(table)
        self.engine = Engine(build_cache(c, table))
        self.publisher = SpotPublisher(self.engine.cache)
        self.engine.on_spot = self.publisher.on_spot
        if self.bus is not None:
            tasks.append(asyncio.ensure_future(self._publish_loop()))
        self.feed = Feed(sources, c.call, self.engine.handle_line, on_web=self.engine.handle_web,
                         on_state=lambda s, st: log.info("%s (%s) : %s %s", s.name, s.address, st.state,
                                                          st.last_message if st.state != CONNECTED else ""))
        if c.cty_update and ctymod.is_stale(self.cty_path):
            tasks.append(asyncio.ensure_future(self._update_cty()))
        log.info("démarrage : %d source(s), indicatif %s", len(sources), c.call or "(aucun)")
        tasks.append(asyncio.ensure_future(self.feed.run()))
        await asyncio.gather(*tasks)

    async def _bus_forever(self) -> None:
        try:
            await self.bus.run_forever()
        except Exception as exc:                  # sans bus, le module continue (état dans status.json)
            log.warning("API interne indisponible : %s", exc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.cluster.service", description="Module Cluster DX")
    ap.add_argument("--config", type=Path, default=Path(os.environ.get("TRX_CONFIG_PATH") or default_config_path()))
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration illisible ({args.config}) : {exc}", file=sys.stderr)
        return 2
    setup_logging(cluster_dir(cfg))
    bus = None
    if os.environ.get("TRX_MODULE_SECRET"):
        from ..modules.client import ModuleClient
        bus = ModuleClient.from_env()
    try:
        asyncio.run(ClusterService(cfg, args.config, bus_client=bus).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
