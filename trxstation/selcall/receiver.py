# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""SELCALL, réception (cahier des charges § 5 et § 6) : machine d'états persistante et traitement de l'audio reçu.

États : DÉSACTIVÉ (audio normal), VEILLE (armé : silence vers les clients, décodeur actif), OUVERT (appel reçu : audio
retardé et tonalités filtrées). OUVERT est verrouillé jusqu'à une action de l'utilisateur (aucune temporisation) ; la
déconnexion d'un client ne change rien ; au redémarrage, VEILLE ou OUVERT reprend en VEILLE avec le même code.

`SelcallReceiver.process(pcm)` s'insère entre la carte son du poste et les clients (RxHub) : trames de 20 ms en
48 kHz 16 bits. Il retarde l'audio (500 ms par défaut), décode une copie ramenée à 8 kHz et atténue les tonalités
SELCALL AVANT qu'elles ne soient audibles (pré-détecteur : ton stable dans la zone du pilote depuis 150 ms). Pendant une
émission (de ce client ou locale), le décodeur est suspendu. Ce module n'émet jamais rien.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import protocol as p
from .decoder import RATE as DEC_RATE
from .decoder import Frame, SelcallDecoder

log = logging.getLogger(__name__)

DISABLED, STANDBY, OPEN = "disabled", "standby", "open"
STATES = (DISABLED, STANDBY, OPEN)
IN_RATE = 48000
DECIMATE = IN_RATE // DEC_RATE                      # 6
FADE_S = 0.02                                       # fondu de l'atténuation
HOLD_AFTER_S = 0.05                                 # atténuation maintenue après la fin de trame
CHIME = ((880.0, 0.12), (1320.0, 0.16))             # carillon doux : deux notes, environ 300 ms
CHIME_DBFS = -26.0


@dataclass
class SelcallStatus:
    state: str = DISABLED
    code: str = ""
    history: tuple[str, ...] = ()
    filter_mode: str = "attenuate"
    attenuation_db: int = 20
    last_call: dict | None = None                   # dernier appel reçu (code, Δ, SNR, heure)
    send_on_tx_end: bool = False                    # trame émise en fin d'émission, à la place du roger bip
    sending: str = ""                               # appel manuel en cours : « 1/3 », « 2/3 »… (jamais enregistré)
    tx_level_dbfs: float = -6.0                     # niveau de la trame émise (curseur, réglage automatique)
    calibration: str = ""                           # résultat du dernier réglage automatique (jamais enregistré)

    def to_dict(self) -> dict:
        return {"state": self.state, "code": self.code, "history": list(self.history), "filter_mode": self.filter_mode,
                "attenuation_db": self.attenuation_db, "last_call": self.last_call, "send_on_tx_end": self.send_on_tx_end,
                "sending": self.sending, "tx_level_dbfs": self.tx_level_dbfs, "calibration": self.calibration}


class SelcallStore:
    """État courant et historique des codes (`state_dir/selcall.json`), écrits de façon atomique.
    Fichier absent ou illisible : DÉSACTIVÉ. Au chargement, OUVERT redevient VEILLE (sûr par défaut)."""

    def __init__(self, path: str | Path | None, *, history_size: int = 10, filter_mode: str = "attenuate",
                 attenuation_db: int = 20, send_on_tx_end: bool = False, tx_level_dbfs: float = -6.0) -> None:
        self.path = Path(path) if path is not None else None
        self.history_size = history_size
        self._lock = threading.Lock()
        self._listeners: list[Callable[[SelcallStatus], None]] = []
        self.status = SelcallStatus(filter_mode=filter_mode, attenuation_db=attenuation_db, send_on_tx_end=send_on_tx_end,
                                    tx_level_dbfs=tx_level_dbfs)
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            history = tuple(c for c in data.get("history", []) if _valid(c))[: self.history_size]
            code = data.get("code", "") if _valid(data.get("code", "")) else ""
            state = data.get("state") if data.get("state") in STATES else DISABLED
            if state != DISABLED and not code:
                state = DISABLED
            if state == OPEN:
                state = STANDBY                                     # redémarrage : jamais ouvert d'office
            mode = data.get("filter_mode") if data.get("filter_mode") in ("mute", "attenuate", "chime") else self.status.filter_mode
            att = data.get("attenuation_db")
            att = att if isinstance(att, int) and not isinstance(att, bool) and 6 <= att <= 60 else self.status.attenuation_db
            tail = data.get("send_on_tx_end")
            tail = tail if isinstance(tail, bool) else self.status.send_on_tx_end
            level = data.get("tx_level_dbfs")
            level = float(level) if _level_ok(level) else self.status.tx_level_dbfs
            self.status = SelcallStatus(state=state, code=code, history=history, filter_mode=mode, attenuation_db=att,
                                        send_on_tx_end=tail, tx_level_dbfs=level)
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("état SELCALL illisible (%s) : fonction désactivée", exc)

    def add_listener(self, callback: Callable[[SelcallStatus], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[SelcallStatus], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _set(self, status: SelcallStatus) -> SelcallStatus:
        with self._lock:
            self.status = status
            self._save()
        for callback in list(self._listeners):
            try:
                callback(status)
            except Exception:
                log.exception("écouteur SELCALL en erreur")
        return status

    def _save(self) -> None:
        if self.path is None:
            return
        data = self.status.to_dict()
        data.pop("sending", None)                                   # passagers : jamais enregistrés
        data.pop("calibration", None)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".selcall-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as exc:                                      # jamais d'arrêt de la passerelle pour un fichier
            log.warning("état SELCALL non enregistré : %s", exc)

    # ---- actions de l'utilisateur (lot 4 : commandes des clients)

    def activate(self, code: str) -> SelcallStatus:
        code = p.validate_code(code)
        history = (code,) + tuple(c for c in self.status.history if c != code)
        log.info("SELCALL armé sur %s", code)
        return self._set(_replace(self.status, state=STANDBY, code=code, history=history[: self.history_size]))

    def rearm(self) -> SelcallStatus:
        if self.status.state == DISABLED:
            return self.status
        log.info("SELCALL réarmé (%s)", self.status.code)
        return self._set(_replace(self.status, state=STANDBY))

    def deactivate(self) -> SelcallStatus:
        log.info("SELCALL désactivé")
        return self._set(_replace(self.status, state=DISABLED))

    def set_calibration(self, text: str) -> None:
        """Résultat du réglage automatique, annoncé aux clients (jamais enregistré)."""
        self.status = _replace(self.status, calibration=text)
        for callback in list(self._listeners):
            try:
                callback(self.status)
            except Exception:
                log.exception("écouteur SELCALL en erreur")

    def set_sending(self, text: str) -> None:
        """Progression d'un appel manuel (« 2/3 », « » à la fin) : annoncée aux clients, jamais enregistrée."""
        self.status = _replace(self.status, sending=text)
        for callback in list(self._listeners):
            try:
                callback(self.status)
            except Exception:
                log.exception("écouteur SELCALL en erreur")

    def tail_code(self) -> str | None:
        """Code à émettre en fin d'émission (à la place du roger bip), ou None."""
        s = self.status
        return s.code if s.send_on_tx_end and s.state != DISABLED and s.code else None

    def set_options(self, *, filter_mode: str | None = None, attenuation_db: int | None = None,
                    send_on_tx_end: bool | None = None, tx_level_dbfs: float | None = None) -> SelcallStatus:
        s = self.status
        if tx_level_dbfs is not None:
            if not _level_ok(tx_level_dbfs):
                raise ValueError("niveau de la trame : -30 à -1 dBFS")
            s = _replace(s, tx_level_dbfs=round(float(tx_level_dbfs) * 2) / 2)
        if send_on_tx_end is not None:
            if not isinstance(send_on_tx_end, bool):
                raise ValueError("send_on_tx_end : true ou false")
            s = _replace(s, send_on_tx_end=send_on_tx_end)
        if filter_mode is not None:
            if filter_mode not in ("mute", "attenuate", "chime"):
                raise ValueError("mode de filtrage : mute, attenuate ou chime")
            s = _replace(s, filter_mode=filter_mode)
        if attenuation_db is not None:
            if not isinstance(attenuation_db, int) or isinstance(attenuation_db, bool) or not 6 <= attenuation_db <= 60:
                raise ValueError("atténuation : 6 à 60 dB")
            s = _replace(s, attenuation_db=attenuation_db)
        return self._set(s)

    def call_received(self, frame: Frame, wall: float) -> bool:
        """Trame valide reçue : ouvre si c'est le code armé et qu'on est en VEILLE. Vrai si le squelch s'ouvre."""
        last = {"code": frame.code, "delta_hz": frame.delta_hz, "snr_db": frame.snr_db, "at": round(wall, 3)}
        s = self.status
        if s.state == STANDBY and frame.code == s.code:
            log.warning("SELCALL : appel %s reçu (Δ %+.1f Hz, SNR %.1f dB) : audio ouvert", frame.code, frame.delta_hz, frame.snr_db)
            self._set(_replace(s, state=OPEN, last_call=last))
            return True
        return False


def _level_ok(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and -30 <= value <= -1


def _valid(code) -> bool:
    try:
        p.validate_code(code)
        return True
    except p.CodeError:
        return False


def _replace(s: SelcallStatus, **changes) -> SelcallStatus:
    data = {**s.__dict__, **changes}
    return SelcallStatus(**data)


def _lowpass(taps: int = 97, cutoff_hz: float = 3400.0) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff_hz / IN_RATE * n) * np.hamming(taps)
    return h / h.sum()


class SelcallReceiver:
    """Traitement de l'audio reçu selon l'état du store. Appelé trame par trame (fil de la boucle asyncio)."""

    def __init__(self, store: SelcallStore, *, delay_ms: int = 500, transmitting: Callable[[], bool] = lambda: False,
                 on_frame: Callable[[Frame, bool], None] | None = None, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.delay = int(IN_RATE * delay_ms / 1000)
        self.transmitting = transmitting
        self.on_frame = on_frame
        self.clock = clock
        self._fir = _lowpass()
        self._restart()
        self.frames_rejected = 0

    def _restart(self) -> None:
        self.decoder = SelcallDecoder()
        self._hist = np.zeros(len(self._fir) - 1)          # fin du morceau précédent (filtre anti-repliement)
        self._phase = 0                                     # décalage de la décimation
        self._line = np.zeros(self.delay, dtype=np.float64)   # ligne à retard (silence au départ)
        self._in = 0                                        # échantillons 48 kHz reçus depuis le départ
        self._intervals: list[list[float]] = []             # [début, fin] des atténuations (secondes, temps d'entrée)
        self._chimes: list[tuple[float, np.ndarray]] = []
        self._was_tx = False
        self._active = False

    # ------------------------------------------------------------------

    def process(self, pcm: bytes) -> bytes:
        state = self.store.status.state
        if state == DISABLED:
            if self._active:
                self._restart()                             # au prochain armement : ligne à retard repartie de zéro
            return pcm
        self._active = True
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
        t0 = self._in / IN_RATE
        self._in += len(x)
        self._decode(x, t0)
        # ligne à retard : sort ce qui est entré il y a `delay` échantillons
        line = np.concatenate([self._line, x])
        out, self._line = line[: len(x)], line[len(x):]
        out_t0 = t0 - self.delay / IN_RATE
        state = self.store.status.state                     # peut avoir changé avec cette trame (ouverture)
        if state != OPEN:
            return bytes(len(pcm))                          # VEILLE : la piste reste établie, elle porte du silence
        out = self._filter(out, out_t0)
        return (np.clip(out, -1, 1) * 32767).astype("<i2").tobytes()

    # ---- décodage

    def _decode(self, x: np.ndarray, t0: float) -> None:
        tx = bool(self.transmitting())
        if tx and not self._was_tx:
            self.decoder.reset()                            # émission : décodeur suspendu
        self._was_tx = tx
        full = np.concatenate([self._hist, x])
        filtered = np.convolve(full, self._fir, mode="valid")
        self._hist = full[-(len(self._fir) - 1):]
        dec = filtered[self._phase::DECIMATE]
        self._phase = (self._phase - len(filtered)) % DECIMATE
        if tx:
            dec = np.zeros_like(dec)                        # le temps du décodeur avance, sans rien décoder
        for frame in self.decoder.feed(dec):
            self._on_frame(frame)
        now = t0 + len(x) / IN_RATE
        start = self.decoder.busy_since if self.decoder.busy else self.decoder.tone_since()
        active = self._intervals[-1] if self._intervals and self._intervals[-1][1] == float("inf") else None
        if start is not None and active is None:
            self._intervals.append([start, float("inf")])   # pré-détecteur : on atténue depuis le début du ton
        elif start is None and active is not None and not self.decoder.busy:
            active[1] = now                                 # pilote non confirmé : retour en fondu

    def _on_frame(self, frame: Frame) -> None:
        if self._intervals and self._intervals[-1][1] == float("inf"):
            self._intervals[-1][1] = frame.end_s + HOLD_AFTER_S
        else:
            self._intervals.append([frame.start_s, frame.end_s + HOLD_AFTER_S])
        opened = False
        if frame.valid:
            log.info("SELCALL : trame %s (Δ %+.1f Hz, SNR %.1f dB)", frame.code, frame.delta_hz, frame.snr_db)
            opened = self.store.call_received(frame, self.clock())
        else:
            self.frames_rejected += 1
            log.info("SELCALL : trame rejetée (%s)", frame.reason)
        if self.store.status.filter_mode == "chime":
            self._chimes.append((frame.end_s + HOLD_AFTER_S, _chime()))
        if self.on_frame is not None:
            try:
                self.on_frame(frame, opened)
            except Exception:
                log.exception("écouteur des trames SELCALL en erreur")

    # ---- filtrage

    def _filter(self, out: np.ndarray, t0: float) -> np.ndarray:
        t = t0 + np.arange(len(out)) / IN_RATE
        s = self.store.status
        floor = 0.0 if s.filter_mode in ("mute", "chime") else 10 ** (-s.attenuation_db / 20)
        gain = np.ones(len(out))
        for start, end in self._intervals:
            w = np.clip((t - (start - FADE_S)) / FADE_S, 0, 1) * np.clip(((end + FADE_S) - t) / FADE_S, 0, 1)
            gain = np.minimum(gain, 1 - w * (1 - floor))
        out = out * gain
        for start, wave in self._chimes:
            i0 = int(round((start - t0) * IN_RATE))
            a, b = max(0, i0), min(len(out), i0 + len(wave))
            if a < b:
                out[a:b] += wave[a - i0:b - i0]
        horizon = t0 - 1.0
        self._intervals = [iv for iv in self._intervals if iv[1] + FADE_S > horizon]
        self._chimes = [(s0, w) for s0, w in self._chimes if s0 + len(w) / IN_RATE > t0]
        return out


def _chime() -> np.ndarray:
    parts = []
    amp = 10 ** (CHIME_DBFS / 20)
    for hz, dur in CHIME:
        n = int(dur * IN_RATE)
        env = np.sin(np.pi * np.arange(n) / n) ** 2                # doux, sans clic
        parts.append(amp * env * np.sin(2 * np.pi * hz * np.arange(n) / IN_RATE))
    return np.concatenate(parts)
