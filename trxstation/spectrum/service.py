# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Service du spectre HF dans la passerelle : lecture du second port CI-V d'un Icom ([spectrum] source = "civ_port").

Jetable par construction : toute anomalie ferme le port B et la station continue en MODE NORMAL (un seul port,
sans waterfall HF) ; l'état et le message destiné à l'utilisateur sont publiés (fichier d'état, clients, journal).
Le CAT et le PTT ne passent jamais par ici.

Règles :
  - le port B ne s'ouvre (ou ne se rouvre) qu'en RÉCEPTION CONFIRMÉE : passerelle en RX, liaison CAT active,
    PTT relu à 0 ;
  - juste après l'ouverture, le PTT est relu par le port CAT pendant PTT_SETTLE_S : s'il passe à 1, le port est
    refermé AUSSITÔT puis on regarde pendant CLOSE_SETTLE_S si l'émission tombe : oui = c'est ce port qui la tenait
    (réglage « USB SEND » / « USB Keying » sur une ligne DTR ou RTS de ce port ; sous Linux, l'ouverture lève DTR et
    RTS), coupure et spectre désactivé jusqu'au redémarrage ; non = émission venue d'ailleurs (micro du poste...),
    coupure par prudence et nouvel essai plus tard (`ptt_busy`) ; illisible = port refermé ;
  - à chaque ouverture, `probe.check` revérifie l'adresse CI-V, le spectre et la fréquence (même poste) ;
  - en marche : plus de balayage pendant SILENT_S, ou poste qui ne répond plus à son adresse (vérifiée toutes les
    IDENT_EVERY_S) = retour au mode normal ; nouvel essai toutes les RETRY_S, toujours en réception confirmée ;
  - pendant une émission (de la station ou au micro du poste), le poste ne balaie plus : PAUSE, pas une panne ;
  - à l'arrêt, les deux réglages du spectre du poste sont remis comme au départ ;
  - réglages du spectre (mode, largeur, référence, vitesse) demandés par la page : liste fermée (civ.encode_setting),
    exécutés par le fil entre deux lectures, SEULEMENT en réception confirmée, puis RELUS sur le poste ; ils sont
    aussi relus à l'ouverture et toutes les IDENT_EVERY_S (un changement fait sur le poste apparaît dans la page) ;
  - préréglage de filtre FIL1/2/3 (« filter ») : même chemin, plus le verrou des réglages du contrôleur PTT
    (`ctrl.rig_setting`, jamais pendant une prise d'émission) ; le mode et le mode données relus sont réécrits tels
    quels, seul le filtre change ; relu toutes les FILTER_EVERY_S. Poste qui ne répond pas à « 26 00 » : `filter`
    reste None et la page garde son ancien bouton.
La lecture série (bloquante) tourne dans un fil à part : elle ne retarde jamais la boucle asyncio de la passerelle.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable

from ..config import Spectrum, parse_civ_address
from .civ import (FILTERS, LEVEL_MAX, OK, SCOPE_MODE, SCOPE_REF, SCOPE_SPAN, SCOPE_SPEED, Sweep, decode_mode_filter,
                  decode_setting, encode_mode_filter, encode_setting)
from .probe import FALLBACK, SCOPE_DISPLAY, SCOPE_OUTPUT, CheckFailed, CivPort, check, open_serial

log = logging.getLogger("trx-gateway.spectrum")

PERMANENT = ("ptt_on_open", "no_pyserial")
SETTING_SUBS = {"mode": SCOPE_MODE, "span": SCOPE_SPAN, "ref": SCOPE_REF, "speed": SCOPE_SPEED}
# Motifs de refus d'un réglage (traduits par la page : REASONS de client.js).
SETTING_REASONS = ("bad_setting", "spectrum_unavailable", "spectrum_busy", "spectrum_timeout", "spectrum_refused", "tx_active")


class SpectrumService:
    RETRY_S = 60.0
    SILENT_S = 5.0
    IDENT_EVERY_S = 30.0
    PTT_SETTLE_S = 1.5
    CLOSE_SETTLE_S = 1.5
    READY_POLL_S = 0.5
    MIN_RETRY_S = 5.0          # relance demandée par un client (ouverture de la vue HF) : pas plus souvent
    FILTER_EVERY_S = 1.0       # relecture du préréglage de filtre (changé sur le poste : la page suit)

    def __init__(self, cfg: Spectrum, link, ctrl, *, opener: Callable = open_serial,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg, self.link, self.ctrl, self.opener, self.clock = cfg, link, ctrl, opener, clock
        self.active = bool(cfg.enabled) and cfg.source == "civ_port"
        self.address = parse_civ_address(cfg.civ_address) if self.active else None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()             # relance anticipée (retry_now)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._state = {"state": "waiting" if self.active else "off", "code": "", "message": ""}
        self.latest: Sweep | None = None
        self.sweeps = 0
        self._fps_window: list[float] = []
        self._listeners: list[Callable[[Sweep], None]] = []
        self._requests: queue.Queue = queue.Queue(maxsize=8)
        self._settings: dict = {}
        self._pending: Sweep | None = None         # balayage en attente de diffusion dans la boucle (le plus récent)
        self._failing: set[int] = set()            # écouteurs déjà signalés en erreur

    def retry_now(self) -> None:
        """Un client ouvre la vue HF : si le spectre est en panne passagère, nouvel essai sans attendre RETRY_S
        (au plus tôt MIN_RETRY_S après l'échec précédent ; jamais après une panne définitive). Ne lève jamais."""
        self._wake.set()

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
                if id(callback) not in self._failing:  # une fois par écouteur : pas un journal (et une boucle) noyés
                    self._failing.add(id(callback))
                    log.exception("diffusion du spectre en erreur (signalé une seule fois pour cet écouteur)")

    def _dispatch_latest(self) -> None:
        with self._lock:
            sweep, self._pending = self._pending, None
        if sweep is not None:
            self._dispatch(sweep)

    # ------------------------------------------------------------------ état publié

    def snapshot(self) -> dict:
        """Pour les clients : état, code, message et réglages relus du poste (change rarement)."""
        with self._lock:
            return dict(self._state, settings=dict(self._settings))

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
                log.error("spectre HF : %s", message)          # le message contient déjà « Mode normal… »
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
            # Un seul envoi en attente dans la boucle : si elle prend du retard (petit PC chargé), on garde le DERNIER
            # balayage au lieu d'empiler des milliers d'appels (la boucle de la passerelle ne doit jamais être noyée).
            if not self._listeners or self._loop is None:
                return
            scheduled = self._pending is not None
            self._pending = sweep
        if not scheduled:
            try:
                self._loop.call_soon_threadsafe(self._dispatch_latest)
            except RuntimeError:                      # boucle fermée (arrêt en cours)
                with self._lock:
                    self._pending = None

    # ------------------------------------------------------------------ réglages du spectre (demandés par la page)

    async def set_setting(self, name: str, value, timeout: float = 3.0) -> tuple[bool, str]:
        """(réussi, motif) ; jamais d'exception. Exécuté par le fil du port B, puis relu sur le poste."""
        if name == "filter":
            return await self._set_filter(value, timeout)
        sub = SETTING_SUBS.get(name)
        try:
            if sub is None:
                raise ValueError(name)
            encode_setting(sub, value)
        except ValueError:
            return False, "bad_setting"
        if self.snapshot()["state"] != "ok" or self._loop is None:
            return False, "spectrum_unavailable"
        if self.ctrl.snapshot().state != "RX":
            return False, "tx_active"
        future = self._loop.create_future()
        try:
            self._requests.put_nowait((name, value, future))
        except queue.Full:
            return False, "spectrum_busy"
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return False, "spectrum_timeout"

    async def _set_filter(self, value, timeout: float) -> tuple[bool, str]:
        from ..gateway.safety import Refused
        if isinstance(value, bool) or value not in FILTERS:
            return False, "bad_setting"
        if self.snapshot()["state"] != "ok" or self._loop is None or self.snapshot()["settings"].get("filter") is None:
            return False, "spectrum_unavailable"
        try:
            async with self.ctrl.rig_setting():          # même verrou que fréquence et mode : jamais pendant une prise
                future = self._loop.create_future()
                try:
                    self._requests.put_nowait(("filter", value, future))
                except queue.Full:
                    return False, "spectrum_busy"
                try:
                    return await asyncio.wait_for(future, timeout)
                except asyncio.TimeoutError:
                    return False, "spectrum_timeout"
        except Refused:
            return False, "tx_active"

    def _resolve(self, future, result: tuple[bool, str]) -> None:
        def done() -> None:
            if not future.done():
                future.set_result(result)
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(done)
            except RuntimeError:                      # boucle fermée
                pass

    def _drain_requests(self, reason: str) -> None:
        while True:
            try:
                _, _, future = self._requests.get_nowait()
            except queue.Empty:
                return
            self._resolve(future, (False, reason))

    def _read_settings(self, port: CivPort) -> None:
        values = {}
        for name, sub in SETTING_SUBS.items():
            reply = port.request(0x27, sub, b"\x00", timeout=0.6)
            values[name] = decode_setting(sub, reply.payload) if reply is not None else None
        current = self._mode_filter(port)
        values["filter"] = current[2] if current else None
        with self._lock:
            self._settings = values

    @staticmethod
    def _mode_filter(port: CivPort) -> tuple[int, int, int] | None:
        reply = port.request(0x26, 0x00, timeout=0.6)
        return decode_mode_filter(reply.payload) if reply is not None else None

    def _read_filter(self, port: CivPort) -> None:
        with self._lock:
            known = self._settings.get("filter") is not None
        if not known:
            return                                     # poste sans « 26 00 » : retenté seulement avec les autres réglages
        current = self._mode_filter(port)
        with self._lock:
            if self._settings:
                self._settings["filter"] = current[2] if current else None

    def _change_filter(self, port: CivPort, value: int) -> tuple[bool, str]:
        current = self._mode_filter(port)
        if current is None:
            return False, "spectrum_refused"
        mode, data, filt = current
        if filt != value:
            reply = port.request(0x26, 0x00, encode_mode_filter(mode, data, value))
            if reply is None or reply.payload[:1] != bytes([OK]):
                self._read_filter(port)
                return False, "spectrum_refused"
        after = self._mode_filter(port)
        with self._lock:
            if self._settings:
                self._settings["filter"] = after[2] if after else None
        return ((True, "") if after == (mode, data, value) else (False, "spectrum_refused"))

    def _serve_requests(self, port: CivPort) -> None:
        while True:
            try:
                name, value, future = self._requests.get_nowait()
            except queue.Empty:
                return
            if not self._rx_confirmed():                 # double garde : jamais pendant l'émission
                self._resolve(future, (False, "tx_active"))
                continue
            if name == "filter":
                self._resolve(future, self._change_filter(port, value))
                continue
            sub = SETTING_SUBS[name]
            reply = port.request(0x27, sub, encode_setting(sub, value))
            accepted = reply is not None and reply.payload[:1] == bytes([OK])
            self._read_settings(port)
            now = self._settings.get(name)
            same = now == value if not isinstance(value, float) else isinstance(now, float) and abs(now - value) < 0.01
            self._resolve(future, (True, "") if accepted and same else (False, "spectrum_refused"))

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
        self._wake.set()                            # sort aussi de l'attente du prochain essai
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

    def _keyed_by_port_b(self) -> bool:
        """Port B déjà refermé : l'émission tombe-t-elle ? Oui = c'est lui qui la tenait (ligne DTR/RTS retombée)."""
        end = self.clock() + self.CLOSE_SETTLE_S
        while self.clock() < end:
            if self.link.state.ptt is False:
                return True
            if self._wait(0.1):
                break
        return False

    def _transmitting(self) -> bool:
        return self.link.state.ptt is True or self.ctrl.snapshot().state != "RX"

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
            self._wake.clear()
            try:
                self._session()
            except CheckFailed as exc:
                self._fail(exc)
                if exc.code in PERMANENT:
                    return
            first = min(self.MIN_RETRY_S, self.RETRY_S)
            if self._wait(first):
                return
            self._wake.wait(max(0.0, self.RETRY_S - first))   # réveillé plus tôt par retry_now
            self._wake.clear()
            if self._stop.is_set():
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
                    ser.close()                     # d'abord fermer le port qui tient peut-être le PTT
                    guilty = self._keyed_by_port_b()
                    self._cut()                     # dans les deux cas : en cas de doute, pas d'émission
                    if not guilty:
                        raise CheckFailed("ptt_busy") from exc   # pas ce port : pas de désactivation définitive
                raise
            if self._stop.is_set():
                return
            before = check(port, lambda: self.link.state.frequency_hz)
            self._read_settings(port)
            for sub in (SCOPE_DISPLAY, SCOPE_OUTPUT):
                if before[sub] != 1:
                    if not port.set_setting(sub, 1):
                        raise CheckFailed("no_scope")
                    changed.append((sub, before[sub]))
            self._stream(port)
        except OSError as exc:
            raise CheckFailed("port_lost", str(exc)) from exc
        finally:
            self._drain_requests("spectrum_unavailable")
            with self._lock:
                self._settings = {}
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
        next_filter = started + self.FILTER_EVERY_S
        quiet_from = started
        while not self._stop.is_set():
            port.poll()
            now = self.clock()
            transmitting = self._transmitting()
            if transmitting:
                quiet_from = now                       # le poste ne balaie plus en émission : pause, pas une panne
            last = max(port.last_sweep_at or started, quiet_from)
            if now - last > self.SILENT_S:
                raise CheckFailed("silent", f"{self.SILENT_S:g}")
            if port.sweeps and self._state["state"] != "ok":
                self._set("ok")
            self._serve_requests(port)
            if now >= next_filter and not transmitting:
                next_filter = now + self.FILTER_EVERY_S
                self._read_filter(port)
            if now >= next_ident and not transmitting:
                next_ident = now + self.IDENT_EVERY_S
                found = port.identify()
                if found != self.address:
                    raise CheckFailed("no_answer")
                self._read_settings(port)                  # réglage changé sur le poste : la page le voit
