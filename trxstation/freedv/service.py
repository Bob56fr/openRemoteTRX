# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mode FreeDV de la station, en RÉCEPTION (lot F1 du cahier des charges FreeDV).

L'opérateur passe la station en mode FreeDV (commande `freedv_set`, refusée pendant une émission) : le son du poste
alimente le moteur (rx_engine.py) et TOUS les clients, visiteurs compris, entendent la voix décodée à la place du
son brut. Hors synchro, ils entendent du silence (la synchro RADE tient lieu de squelch) ; la suppression des
tonalités SELCALL ne s'applique pas à cette voix (chaîne propre, § 4 du cahier).

`process(pcm)` est appelé par RxHub pour chaque trame de 20 ms de la carte son (48 kHz, 16 bits) et rend une trame
de même taille : la voix décodée passe par un petit tampon (PREFILL_S) pour être rendue au rythme de la carte son,
alors que freedv-ka9q la livre par paquets d'environ 120 ms.

Le moteur ne tourne QUE pendant le mode FreeDV. Au-delà de ses relances (état « panne »), le mode est quitté tout
seul (le son du poste revient) avec la cause, jusqu'à une nouvelle demande de l'opérateur. Le mode n'est pas gardé
au redémarrage de la passerelle. Ce module n'émet jamais rien.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .rx_engine import Callsign, EndOfOver, RadeRxEngine, RxEngineConfig, SequenceEnd, Status, Voice

log = logging.getLogger(__name__)

RATE = 48000
FRAME_BYTES = RATE // 50 * 2          # 20 ms
PREFILL_S = 0.15                      # voix gardée avant de jouer : freedv-ka9q la livre par paquets de ~120 ms
MAX_BUFFER_S = 1.0                    # au-delà, la voix la plus ancienne est jetée (jamais de retard qui grandit)
CALLS_KEPT, SEQUENCES_KEPT = 10, 10
_SILENCE = bytes(FRAME_BYTES)


class FreedvUnavailable(Exception):
    """Mode FreeDV refusé : `reason` (code du protocole) et `detail` lisible."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason, self.detail = reason, detail


def bundled_dir() -> Path:
    """Décodeurs livrés avec la station : dossier `freedv` à côté de l'environnement Python de la version installée
    (paquet Windows : `…\\TRX distant\\versions\\X.Y.Z\\freedv`, à côté de `venv`). Sous Debian, compiler-freedv.sh
    les met dans /usr/local/lib/trx-freedv avec des liens dans /usr/local/bin (PATH)."""
    return Path(sys.prefix).parent / "freedv"


def resolve_program(path: str, bundled: Path | None = None) -> str | None:
    """Chemin complet du programme : nom seul = cherché dans le PATH, puis dans les décodeurs livrés
    (`bundled_dir()`) ; None s'il est introuvable."""
    if Path(path).name == path:
        found = shutil.which(path)
        if found:
            return found
        folder = bundled if bundled is not None else bundled_dir()
        for name in (path, path + ".exe") if sys.platform == "win32" and not path.lower().endswith(".exe") else (path,):
            if (folder / name).is_file():
                return str(folder / name)
        return None
    p = Path(path)
    return str(p) if p.is_file() else None


class FreedvService:
    def __init__(self, ka9q_path: str, radae_rx_path: str, workdir: Path, *,
                 engine_factory: Callable[..., RadeRxEngine] = RadeRxEngine,
                 engine_options: dict | None = None, clock: Callable[[], float] = time.time) -> None:
        self.ka9q_path, self.radae_rx_path, self.workdir = ka9q_path, radae_rx_path, workdir
        self._factory, self._options, self._clock = engine_factory, engine_options or {}, clock
        self.on = False
        self.engine: RadeRxEngine | None = None
        self.engine_status = Status()
        self.fault: str | None = None              # cause du dernier abandon (panne), affichée jusqu'à la prochaine mise en route
        self.calls: collections.deque[dict] = collections.deque(maxlen=CALLS_KEPT)
        self.sequences: collections.deque[dict] = collections.deque(maxlen=SEQUENCES_KEPT)
        self.eoo = 0
        self._buf = bytearray()
        self._playing = False
        self._listeners: list[Callable[[dict], None]] = []
        self._lock = asyncio.Lock()
        self._fallback: asyncio.Task | None = None

    # ------------------------------------------------------------------ abonnés (sessions des clients)
    def add_listener(self, fn: Callable[[dict], None]) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[dict], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _notify(self, event: dict) -> None:
        for fn in list(self._listeners):
            try:
                fn(event)
            except Exception:
                log.exception("abonné FreeDV en erreur")

    # ------------------------------------------------------------------ mode
    async def set_on(self, on: bool) -> None:
        """Entre dans le mode FreeDV ou en sort. FreedvUnavailable si un décodeur est introuvable."""
        async with self._lock:
            if on == self.on and (not on or self.engine is not None):
                return
            if not on:
                await self._stop_engine()
                log.info("mode FreeDV quitté : son du poste")
                return
            ka9q, radae = resolve_program(self.ka9q_path), resolve_program(self.radae_rx_path)
            missing = [name for name, found in (("freedv-ka9q", ka9q), ("radae_rx", radae)) if found is None]
            if missing:
                raise FreedvUnavailable("freedv_missing", f"décodeur introuvable : {', '.join(missing)} ([freedv] de station.toml)")
            try:
                self.workdir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise FreedvUnavailable("freedv_storage_error", f"dossier de travail {self.workdir} : {exc}") from exc
            self.fault = None
            self._buf.clear()
            self._playing = False
            cfg = RxEngineConfig(ka9q=(ka9q,), radae_rx=(radae,), in_rate=RATE, out_rate=RATE,
                                 workdir=str(self.workdir), **self._options)
            self.engine = self._factory(cfg, self._on_event)
            await self.engine.start()
            self.on = True
            log.info("mode FreeDV : voix décodée vers les clients (%s, %s)", ka9q, radae)

    async def _stop_engine(self) -> None:
        self.on = False
        engine, self.engine = self.engine, None
        self._buf.clear()
        self._playing = False
        if engine is not None:
            await engine.stop()
        self.engine_status = Status()

    async def close(self) -> None:
        if self._fallback is not None:
            self._fallback.cancel()
        async with self._lock:
            await self._stop_engine()

    async def _give_up(self, cause: str | None) -> None:
        async with self._lock:
            if not self.on:
                return
            await self._stop_engine()
            self.fault = cause or "décodeur en panne"
        log.error("FreeDV abandonné après ses relances (%s) : son du poste remis", self.fault)
        self._notify({"kind": "fault", "cause": self.fault})

    # ------------------------------------------------------------------ son (RxHub, boucle asyncio)
    def process(self, pcm: bytes) -> bytes:
        """Trame du poste -> trame rendue aux clients (voix décodée, ou silence hors synchro)."""
        engine = self.engine
        if not self.on or engine is None:
            return pcm
        engine.feed(pcm)
        n = len(pcm)
        if not self._playing:
            if len(self._buf) < int(PREFILL_S * RATE) * 2:
                return _SILENCE if n == FRAME_BYTES else bytes(n)
            self._playing = True
        if len(self._buf) < n:                     # plus de voix : silence, puis nouveau remplissage
            self._playing = False
            return _SILENCE if n == FRAME_BYTES else bytes(n)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _on_event(self, ev) -> None:
        if isinstance(ev, Voice):
            self._buf += ev.pcm
            over = len(self._buf) - int(MAX_BUFFER_S * RATE) * 2
            if over > 0:
                del self._buf[:over + (over & 1)]
        elif isinstance(ev, Status):
            self.engine_status = ev
            if ev.etat == "panne" and self.on and (self._fallback is None or self._fallback.done()):
                self._fallback = asyncio.get_running_loop().create_task(self._give_up(ev.cause))
        elif isinstance(ev, Callsign):
            entry = {"callsign": ev.callsign, "snr_db": ev.snr_db, "t": round(self._clock(), 1)}
            self.calls.appendleft(entry)
            log.info("FreeDV : indicatif %s décodé (SNR %s dB)", ev.callsign, ev.snr_db)
            self._notify({"kind": "callsign", **entry})
        elif isinstance(ev, SequenceEnd):
            entry = {"start": round(ev.start, 1), "duration_s": ev.duration_s, "note": ev.note, "detail": ev.detail,
                     "callsigns": list(ev.callsigns)}
            self.sequences.appendleft(entry)
            self._notify({"kind": "sequence", **entry})
        elif isinstance(ev, EndOfOver):
            self.eoo += 1

    # ------------------------------------------------------------------ état publié
    def snapshot(self) -> dict:
        """state.freedv (clients, visiteurs compris) et hello.freedv."""
        s = self.engine_status
        return {"on": self.on, "engine": s.etat if self.on else "arret", "sync": s.sync if self.on else "search",
                "confirmed": bool(self.on and s.confirmed),
                "snr_db": None if not self.on or s.snr_db is None else round(s.snr_db, 1),
                "foff_hz": None if not self.on or s.foff_hz is None else round(s.foff_hz, 1),
                "restarts": s.restarts, "cause": s.cause if self.on else None, "fault": self.fault,
                "calls": list(self.calls), "sequences": list(self.sequences)}

    def summary(self) -> dict:
        """Fichier d'état (trx-monitor) : l'essentiel, sans les listes."""
        snap = self.snapshot()
        return {k: snap[k] for k in ("on", "engine", "sync", "confirmed", "snr_db", "restarts", "fault")} | {
            "last_call": self.calls[0] if self.calls else None, "drops": self.engine_status.drops, "eoo": self.eoo}
