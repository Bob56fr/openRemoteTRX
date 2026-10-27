# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sources de spots : reconnexion à délai croissant, bascule entre clusters, RBN à part.

- Les clusters (type « telnet ») forment UN groupe : une seule connexion à la
  fois, dans l'ordre de priorité ; 3 échecs de suite = source suivante.
- Chaque source RBN a sa propre connexion (activable séparément).
- Délais : 10 s, 30 s, 1 min, 2 min, puis 5 min au plus.
- Indicatif ou mot de passe refusé : la source est mise « en échec » et n'est
  PLUS réessayée jusqu'au redémarrage (insister mène au bannissement).
- Une connexion est « réussie » si elle a reçu un spot ou tenu 60 s : le
  compteur d'échecs et le délai repartent alors de zéro.
- Source « web » (clusterdx.org) : une page relevée toutes les 60 s au plus,
  mêmes délais en cas d'échec ; seuls les spots de numéro nouveau passent.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable

from . import clusterdx, telnet

DELAYS_S = (10.0, 30.0, 60.0, 120.0, 300.0)
FAILS_BEFORE_SWITCH = 3
GOOD_SESSION_S = 60.0

# états publiés par source
DISABLED, CONNECTING, CONNECTED, RECONNECTING, FAILED = (
    "disabled", "connecting", "connected", "reconnecting", "failed")


@dataclass(frozen=True)
class Source:
    name: str
    kind: str                      # « telnet » (cluster), « rbn » ou « web » (clusterdx.org, cibistes)
    host: str = ""
    port: int = 0
    priority: int = 1
    enabled: bool = True
    call: str = ""                 # vide = indicatif de la station
    password: str | None = None
    url: str = ""                  # source « web »

    @property
    def spot_kind(self) -> str:
        return {"rbn": "rbn", "web": "cb"}.get(self.kind, "cluster")

    @property
    def address(self) -> str:
        return self.url if self.kind == "web" else f"{self.host}:{self.port}"


@dataclass
class SourceState:
    state: str = DISABLED
    last_code: str | None = None
    last_message: str = ""
    cluster_type: str | None = None
    connects: int = 0
    retry_in_s: float | None = None


@dataclass
class StreamStats:
    """Un flux = le groupe des clusters, ou une source RBN. Une perte est « rattrapée » quand
    une source du même flux s'identifie de nouveau (la bascule compte)."""
    losses: int = 0
    recovered: int = 0
    recover_s: list[float] = field(default_factory=list)
    lost_at: float | None = None

    @property
    def unrecovered(self) -> int:
        return self.losses - self.recovered


Session = Callable[..., Awaitable[telnet.SessionResult]]
Fetch = Callable[[str], tuple[str, datetime]]          # (page, heure du serveur), appelée dans un fil


class Feed:
    def __init__(self, sources: list[Source], call: str, on_line: Callable[[Source, str], None], *,
                 on_web: Callable[[Source, list[clusterdx.WebSpot], int], None] | None = None,
                 on_state: Callable[[Source, SourceState], None] | None = None,
                 session: Session = telnet.run_session, fetch: Fetch = clusterdx.fetch,
                 sleep=asyncio.sleep, clock: Callable[[], float] = time.monotonic,
                 session_kw: dict | None = None, poll_s: float = clusterdx.POLL_S) -> None:
        self.call = call
        self.on_line, self.on_web, self.on_state = on_line, on_web, on_state
        self._fetch, self._poll_s = fetch, max(poll_s, clusterdx.POLL_S)
        self._session, self._sleep, self._clock = session, sleep, clock
        self._session_kw = session_kw or {}
        self.sources = sorted(sources, key=lambda s: s.priority)
        self.states = {s.name: SourceState() for s in self.sources}
        self.streams: dict[str, StreamStats] = {}
        self.stop_event = asyncio.Event()
        self.active_cluster: str | None = None

    def _set(self, src: Source, state: str, **kw) -> None:
        st = self.states[src.name]
        st.state = state
        for k, v in kw.items():
            setattr(st, k, v)
        if self.on_state is not None:
            try:
                self.on_state(src, st)
            except Exception:                    # un affichage ne doit jamais arrêter le flux
                pass

    async def _wait(self, delay: float) -> None:
        if self.stop_event.is_set():
            return
        tasks = {asyncio.ensure_future(self.stop_event.wait()), asyncio.ensure_future(self._sleep(delay))}
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()

    async def _one(self, src: Source, stream: StreamStats) -> telnet.SessionResult:
        st = self.states[src.name]
        self._set(src, CONNECTING, retry_in_s=None)

        def login(cluster_type: str | None) -> None:
            st.connects += 1
            if stream.lost_at is not None:
                stream.recovered += 1
                stream.recover_s.append(self._clock() - stream.lost_at)
                stream.lost_at = None
            self._set(src, CONNECTED, cluster_type=cluster_type)

        res = await self._session(src.host, src.port, src.call or self.call, password=src.password,
                                  on_line=lambda line: self.on_line(src, line), on_login=login,
                                  stop=self.stop_event, **self._session_kw)
        st.last_code, st.last_message = res.code, res.message
        if res.logged_in and res.code != telnet.STOPPED:
            stream.losses += 1
            stream.lost_at = self._clock()
        return res

    async def _run_group(self, stream_name: str, group: list[Source]) -> None:
        """Clusters : un seul connecté à la fois, bascule après 3 échecs ; `group` déjà trié."""
        stream = self.streams.setdefault(stream_name, StreamStats())
        live = list(group)
        idx = fails = step = 0
        while live and not self.stop_event.is_set():
            src = live[idx % len(live)]
            if src.kind == "telnet":
                self.active_cluster = src.name
            res = await self._one(src, stream)
            if self.stop_event.is_set():
                break
            if res.fatal:
                self._set(src, FAILED)
                live.remove(src)
                fails = step = 0
                continue
            good = res.logged_in and (res.spots > 0 or res.duration_s >= GOOD_SESSION_S)
            if good:
                fails = step = 0
            else:
                fails += 1
            if fails >= FAILS_BEFORE_SWITCH and len(live) > 1:
                self._set(src, FAILED)
                idx, fails, step = (idx + 1) % len(live), 0, 0
            delay = DELAYS_S[min(step, len(DELAYS_S) - 1)]
            step += 1
            self._set(live[idx % len(live)] if live else src, RECONNECTING, retry_in_s=delay)
            await self._wait(delay)
        if stream_name == "clusters":
            self.active_cluster = None

    async def _run_web(self, src: Source) -> None:
        """Relevé périodique d'une page : `on_web` reçoit les spots de numéro nouveau."""
        stream = self.streams.setdefault(src.name, StreamStats())
        last_id = -1
        step = 0
        ok = False
        self._set(src, CONNECTING)
        while not self.stop_event.is_set():
            try:
                page, server_now = await asyncio.to_thread(self._fetch, src.url)
                spots, bad = clusterdx.parse_page(page, server_now)
            except Exception as exc:                  # réseau, HTTP, format : jamais fatal pour la station
                if ok:
                    stream.losses += 1
                    stream.lost_at = self._clock()
                ok = False
                st = self.states[src.name]
                st.last_code = "format" if isinstance(exc, clusterdx.FormatError) else telnet.UNREACHABLE
                st.last_message = str(exc)[:160] or type(exc).__name__
                delay = DELAYS_S[min(step, len(DELAYS_S) - 1)]
                step += 1
                self._set(src, RECONNECTING, retry_in_s=delay)
                await self._wait(delay)
                continue
            if not ok:
                ok, step = True, 0
                self.states[src.name].connects += 1
                if stream.lost_at is not None:
                    stream.recovered += 1
                    stream.recover_s.append(self._clock() - stream.lost_at)
                    stream.lost_at = None
                self._set(src, CONNECTED, retry_in_s=None, cluster_type="web")
            fresh = sorted((s for s in spots if s.id > last_id), key=lambda s: s.id)
            if spots:
                last_id = max(last_id, max(s.id for s in spots))
            if (fresh or bad) and self.on_web is not None:
                self.on_web(src, fresh, bad)
            await self._wait(self._poll_s)

    async def run(self) -> None:
        clusters = [s for s in self.sources if s.enabled and s.kind == "telnet"]
        tasks = []
        if clusters:
            tasks.append(self._run_group("clusters", clusters))
        tasks += [self._run_group(s.name, [s]) for s in self.sources if s.enabled and s.kind == "rbn"]
        tasks += [self._run_web(s) for s in self.sources if s.enabled and s.kind == "web"]
        await asyncio.gather(*tasks)

    def stop(self) -> None:
        self.stop_event.set()
