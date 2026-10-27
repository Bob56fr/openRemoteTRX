"""Service du spectre HF dans la passerelle : lecture du second port CI-V d'un Icom ([spectrum] source = "civ_port").

Jetable par construction : toute anomalie ferme le port B et la station continue en MODE NORMAL (un seul port,
sans waterfall HF) ; l'état et le message destiné à l'utilisateur sont publiés (fichier d'état, clients, journal).
Le CAT et le PTT ne passent jamais par ici.

Règles :
  - le port B ne s'ouvre (ou ne se rouvre) qu'en RÉCEPTION CONFIRMÉE : passerelle en RX, liaison CAT active,
    PTT relu à 0 ;
  - juste après l'ouverture, le PTT est relu par le port CAT pendant PTT_SETTLE_S : s'il passe à 1, le port est
    refermé, la coupure est demandée et le spectre est désactivé jusqu'au redémarrage (réglage « USB SEND » sur
    ce port) ; illisible = port refermé ;
  - à chaque ouverture, `probe.check` revérifie l'adresse CI-V, le spectre et la fréquence (même poste) ;
  - en marche : plus de balayage pendant SILENT_S, ou poste qui ne répond plus à son adresse (vérifiée toutes les
    IDENT_EVERY_S) = retour au mode normal ; nouvel essai toutes les RETRY_S, toujours en réception confirmée ;
  - à l'arrêt, les deux réglages du spectre du poste sont remis comme au départ.
La lecture série (bloquante) tourne dans un fil à part : elle ne retarde jamais la boucle asyncio de la passerelle.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable

from ..config import Spectrum, parse_civ_address
from .civ import LEVEL_MAX, Sweep
from .probe import FALLBACK, SCOPE_DISPLAY, SCOPE_OUTPUT, CheckFailed, CivPort, check, open_serial

log = logging.getLogger("trx-gateway.spectrum")

PERMANENT = ("ptt_on_open", "no_pyserial")


class SpectrumService:
    RETRY_S = 60.0
    SILENT_S = 5.0
    IDENT_EVERY_S = 30.0
    PTT_SETTLE_S = 1.5
    READY_POLL_S = 0.5

    def __init__(self, cfg: Spectrum, link, ctrl, *, opener: Callable = open_serial,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg, self.link, self.ctrl, self.opener, self.clock = cfg, link, ctrl, opener, clock
        self.active = bool(cfg.enabled) and cfg.source == "civ_port"
        self.address = parse_civ_address(cfg.civ_address) if self.active else None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._state = {"state": "waiting" if self.active else "off", "code": "", "message": ""}
        self.latest: Sweep | None = None
        self.sweeps = 0
        self._fps_window: list[float] = []
        self._listeners: list[Callable[[Sweep], None]] = []

    def add_listener(self, callback: Callable[[Sweep], None]) -> None:
        """Appelé dans la boucle asyncio de la passerelle à chaque balayage (jamais dans le fil de lecture)."""
        self._listeners.append(callback)

    def capability(self) -> dict | None:
        """Annoncé dans « hello » : None si le spectre n'est pas configuré."""
        if not self.active:
            return None
        return {"source": "civ_port", "level_max": LEVEL_MAX, "max_fps": self.cfg.max_fps}

    def _dispatch(self, sweep: Sweep) -> None:
        for callback in list(self._listeners):
            try:
                callback(sweep)
            except Exception:                         # noqa: BLE001 - un client fautif ne touche ni les autres ni la lecture
                log.exception("diffusion du spectre en erreur")

    # ------------------------------------------------------------------ état publié

    def snapshot(self) -> dict:
        """Pour les clients : état, code et message seulement (change rarement)."""
        with self._lock:
            return dict(self._state)

    def stats(self) -> dict:
        """Pour le fichier d'état : snapshot + compteurs."""
        with self._lock:
            out = dict(self._state, port=self.cfg.port if self.active else "", sweeps=self.sweeps)
            now = self.clock()
            recent = [t for t in self._fps_window if now - t <= 5.0]
            out["fps"] = round(len(recent) / 5.0, 1)
            if self.latest is not None:
                out.update(points=len(self.latest.points), f1_hz=self.latest.f1_hz, f2_hz=self.latest.f2_hz)
            return out

    def _set(self, state: str, code: str = "", message: str = "") -> None:
        with self._lock:
            changed = (self._state["state"], self._state["code"]) != (state, code)
            self._state = {"state": state, "code": code, "message": message}
        if changed:
            if state == "error":
                log.error("spectre HF : %s %s", message, FALLBACK)
            elif state == "ok":
                log.info("spectre HF reçu sur %s", self.cfg.port)

    def _fail(self, exc: CheckFailed) -> None:
        self._set("error", exc.code, f"{exc.message(self.cfg.port, self.address)} {FALLBACK}")

    def _on_sweep(self, sweep: Sweep) -> None:
        with self._lock:
            self.latest = sweep
            self.sweeps += 1
            now = self.clock()
            self._fps_window = [t for t in self._fps_window if now - t <= 5.0] + [now]
        if self._listeners and self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._dispatch, sweep)
            except RuntimeError:                      # boucle fermée (arrêt en cours)
                pass

    # ------------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        if not self.active or self._thread is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._worker, name="trx-spectre", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        """Ne lève jamais : remet les réglages du poste et ferme le port B (au plus quelques secondes)."""
        self._stop.set()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 5.0)

    # ------------------------------------------------------------------ fil de lecture

    def _rx_confirmed(self) -> bool:
        rig = self.link.state
        return self.ctrl.snapshot().state == "RX" and rig.connected and rig.ptt is False and rig.frequency_hz is not None

    def _wait(self, seconds: float) -> bool:
        """Attente interruptible ; True si l'arrêt est demandé."""
        return self._stop.wait(seconds)

    def _cut(self) -> None:
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self.ctrl.force_rx("spectrum_port_keyed", by="spectre"), self._loop)

    def _ptt_after_open(self) -> None:
        """Relit le PTT par le port CAT après l'ouverture du port B : actif = CheckFailed permanent."""
        end = self.clock() + self.PTT_SETTLE_S
        while self.clock() < end:
            if self.link.state.ptt is True:
                raise CheckFailed("ptt_on_open")
            if self._wait(0.1):
                return
        if self.link.state.ptt is not False:
            raise CheckFailed("ptt_unknown")

    def _worker(self) -> None:
        try:
            self._run()
        except Exception as exc:                    # jamais d'arrêt de la passerelle à cause du spectre
            log.exception("spectre HF : erreur interne")
            self._fail(CheckFailed("internal", type(exc).__name__))

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._rx_confirmed():
                if self._state["state"] != "error":
                    self._set("waiting")
                if self._wait(self.READY_POLL_S):
                    return
                continue
            self._set("starting")
            try:
                self._session()
            except CheckFailed as exc:
                self._fail(exc)
                if exc.code in PERMANENT:
                    return
            if self._wait(self.RETRY_S):
                return

    def _session(self) -> None:
        """Une ouverture du port B : vérification, mise en marche du spectre, lecture jusqu'à l'arrêt ou une anomalie."""
        try:
            ser = self.opener(self.cfg.port, self.cfg.baud)
        except ImportError as exc:
            raise CheckFailed("no_pyserial") from exc
        except (OSError, ValueError) as exc:
            raise CheckFailed("open_failed", str(exc)) from exc
        changed: list[tuple[int, int]] = []
        port = CivPort(ser, self.address, on_sweep=self._on_sweep, clock=self.clock)
        try:
            try:
                self._ptt_after_open()
            except CheckFailed as exc:
                if exc.code == "ptt_on_open":
                    ser.close()                     # d'abord fermer le port qui tient le PTT, puis couper
                    self._cut()
                raise
            if self._stop.is_set():
                return
            before = check(port, lambda: self.link.state.frequency_hz)
            for sub in (SCOPE_DISPLAY, SCOPE_OUTPUT):
                if before[sub] != 1:
                    if not port.set_setting(sub, 1):
                        raise CheckFailed("no_scope")
                    changed.append((sub, before[sub]))
            self._stream(port)
        except OSError as exc:
            raise CheckFailed("port_lost", str(exc)) from exc
        finally:
            for sub, value in reversed(changed):    # remis comme au départ, chacun indépendamment
                try:
                    port.set_setting(sub, value)
                except Exception:                    # noqa: BLE001 - port perdu : rien à remettre
                    pass
            try:
                ser.close()
            except Exception:                        # noqa: BLE001
                pass

    def _stream(self, port: CivPort) -> None:
        started = self.clock()
        next_ident = started + self.IDENT_EVERY_S
        while not self._stop.is_set():
            port.poll()
            now = self.clock()
            last = port.last_sweep_at or started
            if now - last > self.SILENT_S:
                raise CheckFailed("silent", f"{self.SILENT_S:g}")
            if port.sweeps and self._state["state"] != "ok":
                self._set("ok")
            if now >= next_ident:
                next_ident = now + self.IDENT_EVERY_S
                found = port.identify()
                if found != self.address:
                    raise CheckFailed("no_answer")
