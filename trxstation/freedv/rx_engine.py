# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Moteur de RÉCEPTION RADE V1 (lot F1) : deux processus enfants, sans aucune voie d'émission.

  son du poste (int16) ─┬─> freedv-ka9q -i IN -o OUT ──> voix décodée (int16) + indicatif (stderr)
                        └─> ToRadaeIQ (8 kHz complexe) ──> radae_rx -v 1 ──> état, SNR, décalage (stderr)

freedv-ka9q n'écrit ni l'état de synchro ni le SNR, d'où le second processus (rade_c, ~4 % d'un cœur).
freedv-ka9q est lancé SANS -c / -l / -f : il ne se connecte jamais à FreeDV Reporter (lot F6, une
seule connexion par station, faite par la passerelle).

Pannes traitées (tests dans tests/test_freedv_rx_engine.py) :
  - un programme s'arrête ou ne se lance pas      -> les deux sont arrêtés puis relancés ;
  - radae_rx se tait alors qu'on l'alimente        -> gel, relance ;
  - une entrée ne se vide plus (write_timeout_s)   -> gel, relance ;
  - plus de max_restarts relances en restart_window_s -> état « panne » (plus aucune relance ;
    feed() ne fait plus rien, sans exception) jusqu'à reset() ;
  - file d'entrée pleine (enfant trop lent)        -> les morceaux les plus anciens sont jetés et comptés.
Après toute panne, l'état repart de « search » : jamais de synchro ni de voix héritées.

feed() s'appelle depuis la boucle asyncio ; feed_threadsafe() depuis un fil (carte son) : UN SEUL
réveil en attente à la fois (piège de l'étape 44 : jamais un call_soon_threadsafe par morceau).
"""
from __future__ import annotations

import asyncio
import collections
import math
import struct
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from .parse import DemodState, parse_ka9q_line, parse_radae_line
from .quality import Sequence, SyncFilter
from .resample import ToRadaeIQ


@dataclass(frozen=True)
class RxEngineConfig:
    ka9q: tuple[str, ...]            # commande : (chemin de freedv-ka9q,) ; les tests y mettent un faux
    radae_rx: tuple[str, ...]        # commande : (chemin de radae_rx,)
    in_rate: int = 48000
    out_rate: int = 48000
    radae_args: tuple[str, ...] = ("-v", "1")
    workdir: str | None = None       # dossier courant des décodeurs : radae_rx y écrit eoo_rx.f32
    freeze_s: float = 3.0            # radae_rx muet alors qu'il est alimenté
    startup_grace_s: float = 5.0     # chargement des modèles au lancement
    write_timeout_s: float = 2.0
    backoff_s: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)
    max_restarts: int = 5
    restart_window_s: float = 600.0
    queue_max_s: float = 1.0
    min_sync_s: float = 2.0
    sync_hold_s: float = 1.0
    voice_dbfs: float = -55.0
    sequence_end_s: float = 2.0
    gate_voice: bool = False         # True : voix transmise seulement en synchro confirmée
    status_every_s: float = 0.5


@dataclass(frozen=True)
class Status:
    etat: str = "arret"              # arret, demarrage, ecoute, relance, panne
    sync: str = "search"
    confirmed: bool = False
    snr_db: float | None = None
    foff_hz: float | None = None
    restarts: int = 0
    drops: int = 0
    cause: str | None = None


@dataclass(frozen=True)
class Voice:
    pcm: bytes


@dataclass(frozen=True)
class Callsign:
    callsign: str
    snr_db: int | None


@dataclass(frozen=True)
class EndOfOver:
    pass


@dataclass(frozen=True)
class SequenceEnd:
    start: float
    duration_s: float
    note: int
    detail: str
    callsigns: tuple[str, ...]


Event = Status | Voice | Callsign | EndOfOver | SequenceEnd


def _dbfs(pcm: bytes) -> float:
    n = len(pcm) // 2
    if not n:
        return -120.0
    s = sum(v * v for v in struct.unpack(f"<{n}h", pcm[: 2 * n]))
    return 10 * math.log10(s / n / 32768.0 ** 2 + 1e-12)


class _Fault(Exception):
    pass


class RadeRxEngine:
    def __init__(self, cfg: RxEngineConfig, listener: Callable[[Event], None],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg, self._emit_cb, self._clock = cfg, listener, clock
        self._status = Status()
        self._queue: collections.deque[bytes] = collections.deque()
        self._queued_bytes = 0
        self._drops = 0
        self._qmax = int(cfg.queue_max_s * cfg.in_rate) * 2
        self._qlock = threading.Lock()
        self._wake: asyncio.Event | None = None
        self._wake_pending = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._restart_times: collections.deque[float] = collections.deque()
        self._filter = SyncFilter(cfg.min_sync_s, cfg.sync_hold_s)
        self._seq: Sequence | None = None
        self._last_voice = 0.0
        self._last_feed = -1e9
        self._last_radae = 0.0
        self._last_status_emit = -1e9
        self._last_calls: dict[str, float] = {}
        self._pending_text: tuple[str, float] | None = None
        self.procs: list[asyncio.subprocess.Process] = []   # lisible par les tests

    # ------------------------------------------------------------------ interface
    @property
    def status(self) -> Status:
        return self._status

    async def start(self) -> None:
        if self._task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._set(etat="demarrage", cause=None)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        assert self._stopping is not None and self._wake is not None
        self._stopping.set()
        self._wake.set()
        try:
            await self._task
        finally:
            self._task = None
            self._set(etat="arret", sync="search", confirmed=False, snr_db=None, foff_hz=None)

    async def reset(self) -> None:
        """Sortie de l'état « panne » (action de l'opérateur) : compteur de relances remis à zéro."""
        await self.stop()
        self._restart_times.clear()
        self._set(restarts=0, cause=None)
        await self.start()

    def feed(self, pcm: bytes) -> None:
        self._enqueue(pcm)
        if self._wake is not None:
            self._wake.set()

    def feed_threadsafe(self, pcm: bytes) -> None:
        self._enqueue(pcm)
        loop = self._loop
        if loop is None or self._wake is None:
            return
        with self._qlock:
            if self._wake_pending:
                return
            self._wake_pending = True
        try:
            loop.call_soon_threadsafe(self._wake_from_thread)
        except RuntimeError:            # boucle fermée
            pass

    # ------------------------------------------------------------------ interne
    def _wake_from_thread(self) -> None:
        with self._qlock:
            self._wake_pending = False
        if self._wake is not None:
            self._wake.set()

    def _enqueue(self, pcm: bytes) -> None:
        if self._status.etat not in ("ecoute", "demarrage") or not pcm:
            return
        dropped = 0
        with self._qlock:
            self._queue.append(pcm)
            self._queued_bytes += len(pcm)
            while self._queued_bytes > self._qmax and len(self._queue) > 1:
                self._queued_bytes -= len(self._queue.popleft())
                dropped += 1
            self._drops += dropped
            self._last_feed = self._clock()

    def _take_all(self) -> list[bytes]:
        with self._qlock:
            out = list(self._queue)
            self._queue.clear()
            self._queued_bytes = 0
        return out

    def _emit(self, ev: Event) -> None:
        try:
            self._emit_cb(ev)
        except Exception:               # un abonné fautif ne doit jamais arrêter le moteur
            pass

    def _set(self, force: bool = True, **kw) -> None:
        kw.setdefault("drops", self._drops)
        new = replace(self._status, **kw)
        if new != self._status:
            self._status = new
            if force:
                self._last_status_emit = self._clock()
                self._emit(new)

    def _reset_demod(self) -> None:
        self._filter.reset()
        self._close_sequence()
        self._pending_text = None
        self._set(sync="search", confirmed=False, snr_db=None, foff_hz=None)

    def _close_sequence(self) -> None:
        seq, self._seq = self._seq, None
        if seq is None or seq.voice_s < 0.5:
            return
        note, detail = seq.note()
        self._emit(SequenceEnd(seq.start, round(seq.voice_s, 1), note, detail, tuple(seq.callsigns)))

    async def _run(self) -> None:
        assert self._stopping is not None
        while not self._stopping.is_set():
            self._set(etat="demarrage", cause=None)
            cause = await self._session()
            self._reset_demod()
            if self._stopping.is_set():
                break
            now = self._clock()
            self._restart_times.append(now)
            while self._restart_times and now - self._restart_times[0] > self.cfg.restart_window_s:
                self._restart_times.popleft()
            n = len(self._restart_times)
            if n > self.cfg.max_restarts:
                self._set(etat="panne", cause=cause, restarts=self._status.restarts + 1)
                self._take_all()
                return
            self._set(etat="relance", cause=cause, restarts=self._status.restarts + 1)
            delay = self.cfg.backoff_s[min(n - 1, len(self.cfg.backoff_s) - 1)]
            try:
                await asyncio.wait_for(self._stopping.wait(), delay)
            except asyncio.TimeoutError:
                pass

    async def _spawn(self, *args: str, read_stdout: bool = True) -> asyncio.subprocess.Process:
        # Une sortie non lue remplit le tuyau et bloque le programme : radae_rx écrit ses paramètres de
        # parole (~14 ko/s) sur stdout, qui part donc vers DEVNULL (essai réel du 2026-11-11).
        try:
            return await asyncio.create_subprocess_exec(
                *args, cwd=self.cfg.workdir, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE if read_stdout else asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE)
        except OSError as e:
            raise _Fault(f"lancement impossible de {Path(args[0]).name} : {e.strerror or e}") from None

    async def _session(self) -> str | None:
        """Une vie des deux processus ; rend la cause de la fin (None si arrêt demandé)."""
        assert self._stopping is not None and self._wake is not None
        cfg = self.cfg
        fault: asyncio.Future[str] = asyncio.get_running_loop().create_future()

        def fail(cause: str) -> None:
            if not fault.done():
                fault.set_result(cause)

        tasks: list[asyncio.Task] = []
        self.procs = []
        try:
            ka9q = await self._spawn(*cfg.ka9q, "-i", str(cfg.in_rate), "-o", str(cfg.out_rate))
            self.procs.append(ka9q)
            radae = await self._spawn(*cfg.radae_rx, *cfg.radae_args, read_stdout=False)
            self.procs.append(radae)
        except _Fault as e:
            await self._kill_all()
            return str(e)
        self._take_all()                      # pas de son d'avant la (re)prise
        iq = ToRadaeIQ(cfg.in_rate)
        t0 = self._clock()
        self._last_radae = t0
        self._set(etat="ecoute")

        # Une file et une tâche d'écriture PAR décodeur : freedv-ka9q, cadencé en temps réel, lit par
        # à-coups (surtout au lancement) et ne doit jamais affamer radae_rx (essai réel du 2026-11-11).
        names = {"ka9q": "freedv-ka9q", "radae": "radae_rx"}
        align = {"ka9q": 2, "radae": 8}                       # int16 ; complexe float32
        limit = {"ka9q": self._qmax, "radae": int(cfg.queue_max_s * 8000) * 8}
        bufs = {k: bytearray() for k in names}
        ready = {k: asyncio.Event() for k in names}

        def push(k: str, data: bytes) -> None:
            b = bufs[k]
            b += data
            over = len(b) - limit[k]
            if over > 0:
                over += -over % align[k]
                del b[:over]
                with self._qlock:
                    self._drops += 1
            ready[k].set()

        async def dispatcher() -> None:
            assert self._wake is not None
            while True:
                await self._wake.wait()
                self._wake.clear()
                chunks = self._take_all()
                if chunks:
                    pcm = b"".join(chunks)
                    push("ka9q", pcm)
                    push("radae", iq.process(pcm))

        async def child_writer(k: str, stdin: asyncio.StreamWriter) -> None:
            while True:
                await ready[k].wait()
                ready[k].clear()
                data = bytes(bufs[k])
                bufs[k].clear()
                if not data:
                    continue
                timeout = cfg.write_timeout_s if self._clock() - t0 > cfg.startup_grace_s else \
                    max(cfg.write_timeout_s, cfg.startup_grace_s)
                try:
                    stdin.write(data)
                    await asyncio.wait_for(stdin.drain(), timeout)
                except asyncio.TimeoutError:
                    fail(f"gel de {names[k]} (entrée bloquée)")
                    return
                except (BrokenPipeError, ConnectionResetError, OSError):
                    await asyncio.sleep(0.5)            # laisser waiter() donner le code de sortie
                    fail(f"{names[k]} ne lit plus son entrée")
                    return

        async def voice_reader() -> None:
            block = cfg.out_rate // 50 * 2          # 20 ms
            while True:
                pcm = await ka9q.stdout.read(block)
                if not pcm:
                    return
                now = self._clock()
                if _dbfs(pcm) > cfg.voice_dbfs:
                    self._last_voice = now
                    if self._seq is None:
                        self._seq = Sequence(start=time.time())
                if self._seq is not None:
                    self._seq.voice_s += len(pcm) / 2 / cfg.out_rate
                if not cfg.gate_voice or self._filter.confirmed:
                    self._emit(Voice(pcm))

        async def ka9q_err() -> None:
            try:
                await _ka9q_err()
            except (ValueError, asyncio.LimitOverrunError, UnicodeError) as e:
                fail(f"lecture impossible de freedv-ka9q : {e}")

        async def _ka9q_err() -> None:
            async for raw in ka9q.stderr:
                r = parse_ka9q_line(raw.decode(errors="replace"))
                if r is None:
                    continue
                cs, snr = r
                now = self._clock()
                if snr is None:
                    self._pending_text = (cs, now)      # attendre la ligne « Reporting » (SNR)
                else:
                    self._pending_text = None
                    self._callsign(cs, snr, now)

        async def radae_err() -> None:
            try:
                await _radae_err()
            except (ValueError, asyncio.LimitOverrunError, UnicodeError) as e:
                fail(f"lecture impossible de radae_rx : {e}")

        async def _radae_err() -> None:
            async for raw in radae.stderr:
                now = self._clock()
                self._last_radae = now
                r = parse_radae_line(raw.decode(errors="replace"))
                if r == "eoo":
                    self._emit(EndOfOver())
                elif isinstance(r, DemodState):
                    self._demod(r, now)

        async def waiter(p: asyncio.subprocess.Process, name: str) -> None:
            code = await p.wait()
            fail(f"{name} s'est arrêté (code {code})")

        async def watchdog() -> None:
            while True:
                await asyncio.sleep(0.25)
                now = self._clock()
                fed = now - self._last_feed < 1.0
                if fed and now - t0 > cfg.startup_grace_s and now - self._last_radae > cfg.freeze_s:
                    fail("radae_rx gelé (plus aucune ligne d'état)")
                    return
                if self._pending_text and now - self._pending_text[1] > 1.0:
                    cs, _ = self._pending_text
                    self._pending_text = None
                    self._callsign(cs, None, now)
                if self._seq is not None and now - self._last_voice > cfg.sequence_end_s:
                    self._close_sequence()

        for coro in (dispatcher(), child_writer("ka9q", ka9q.stdin), child_writer("radae", radae.stdin), voice_reader(), ka9q_err(), radae_err(), waiter(ka9q, "freedv-ka9q"),
                     waiter(radae, "radae_rx"), watchdog()):
            tasks.append(asyncio.create_task(coro))
        stop_wait = asyncio.create_task(self._stopping.wait())
        try:
            await asyncio.wait({fault, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop_wait.cancel()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._kill_all()
        return None if self._stopping.is_set() else (fault.result() if fault.done() else "inconnue")

    def _callsign(self, cs: str, snr: int | None, now: float) -> None:
        last = self._last_calls.get(cs)
        self._last_calls[cs] = now
        if last is not None and now - last < 10.0:
            return
        if self._seq is not None and cs not in self._seq.callsigns:
            self._seq.callsigns.append(cs)
        self._emit(Callsign(cs, snr))

    def _demod(self, d: DemodState, now: float) -> None:
        confirmed = self._filter.update(d.state, now)
        if self._seq is not None:
            self._seq.sample(now, d.state == "sync", d.snr_db)
        changed = d.state != self._status.sync or confirmed != self._status.confirmed
        due = now - self._last_status_emit >= self.cfg.status_every_s
        snr = d.snr_db if d.state == "sync" else None
        foff = d.foff_hz if d.state == "sync" else None
        if changed or due:
            self._set(sync=d.state, confirmed=confirmed, snr_db=snr, foff_hz=foff)
        else:
            self._set(force=False, sync=d.state, confirmed=confirmed, snr_db=snr, foff_hz=foff)

    async def _kill_all(self) -> None:
        for p in self.procs:
            if p.returncode is None:
                try:
                    p.kill()
                except ProcessLookupError:
                    pass
        for p in self.procs:
            try:
                await asyncio.wait_for(p.wait(), 5.0)
            except asyncio.TimeoutError:
                pass
            # asyncio n'a pas de fermeture publique des tuyaux d'un processus : sans elle, Windows
            # (Proactor) signale des tuyaux ouverts quand la boucle se ferme.
            tr = getattr(p, "_transport", None)
            if tr is not None:
                tr.close()
