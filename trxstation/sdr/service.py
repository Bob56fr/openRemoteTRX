# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module « sdr » : processus séparé lancé et surveillé par le superviseur (« sdr » dans [modules] run, [sdr] enabled).

Il lance sdr-core (programme natif, processus enfant), lit ses trames (frames.py) et publie par le bus des modules :
- aux OPÉRATEURS qui affichent la rubrique SDR (scope « sdr_view »), chaque ligne de waterfall :
    {"kind": "sdr_line", "scope": "sdr_view", "c": centre Hz, "s": largeur Hz, "d": cases uint8 en base64, "t": ms}
- aux OPÉRATEURS, l'état (retenu, rejoué à l'ouverture de la rubrique) :
    {"kind": "sdr_state", "retain": "snapshot", "scope": "operators", "state": "starting"|"running"|"error"|"stopped",
     "code": ..., "detail": ..., "serial", "fs", "center", "lna", "gr", "ant", "rate", "bins", "overload", "drops",
     "gaps", "cpu", "restarts", "t"}
Commandes d'un opérateur (droit client_commands, relayées par la passerelle) : « state », « set » (center_hz, lna, gr,
rate, agc, dfreq_hz, mode, dbw, sql). De la passerelle seulement : « audio » (quelqu'un écoute le SDR) ; le son démodulé
part alors en UDP vers 127.0.0.1:[sdr] audio_port (paquets « ORSA », jeton dérivé du secret du module) ; « load »
(niveau de bridage 0 à 5 décidé par la passerelle, load.py). Le module se bride aussi LUI-MÊME au-delà de
[sdr] max_cpu_pct / max_mem_mb (niveaux 1 à 4) ; le niveau appliqué est le plus haut des deux (5 = sdr-core arrêté). Le module n'a AUCUN droit sur le poste et ne redémarre JAMAIS le service du fabricant (commun à la machine).
Réglages choisis depuis la page gardés dans state_dir/sdr/last.json (jamais dans station.toml).

À la main (essai, sans bus) :  python -m trxstation.sdr.service --config station.toml --once
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import logging.handlers
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config as cfgmod
from ..errors import codes
from ..errors.emit import emit_event
from ..paths import default_config_path
from .devices import core_path
from .frames import Audio, FrameError, FrameReader, Line
from .load import LEVEL_TEXT, TOP, Ladder, sample_rate, waterfall_rate

log = logging.getLogger("trx.sdr")

STATE_EVERY_S = 5.0
STATE_MIN_GAP_S = 1.0          # état publié au plus une fois par seconde (surcharges du CAN en rafale)
RETRY_ABSENT_S = 30.0          # SDR absent / pris, service du fabricant injoignable
RETRY_CONFIG_S = 300.0         # sdr-core introuvable ou réglage refusé
BACKOFF_MIN_S, BACKOFF_MAX_S = 2.0, 60.0
STABLE_RUN_S = 600.0           # 10 min de marche : le compteur de relances repart de zéro
LOSS_REPORT_EVERY_S = 600.0
STOP_GRACE_S = 3.0
MAX_RATE = 15                  # le bus limite un module à 20 messages par seconde
SET_LIMITS = {"center_hz": (1_000, 2_000_000_000), "lna": (0, 8), "gr": (20, 59), "rate": (1, MAX_RATE)}
SET_BOOLS = ("agc",)           # AGC matériel de la FI
# Démodulation (lot S1b) : fréquence écoutée, mode, largeur du filtre, squelch (dB au-dessus du bruit, 0 = ouvert)
SET_LIMITS.update({"dfreq_hz": (1_000, 2_000_000_000), "dbw": (100, 15_000), "sql": (0, 40)})
MODES = ("AM", "NFM", "USB", "LSB", "CW")
DEFAULT_DBW = {"AM": 8000, "NFM": 12500, "USB": 2700, "LSB": 2700, "CW": 500}
AUDIO_MAGIC = b"ORSA"          # paquet de son vers la passerelle : magie, jeton (16), numéro (uint32), 960 int16
AUDIO_TOKEN_BYTES = 16


class SetRefused(ValueError):
    pass


@dataclass
class Settings:
    center_hz: int
    lna: int
    gr: int
    rate: int
    agc: bool = True
    dfreq_hz: int = 0          # 0 = le centre
    mode: str = "USB"
    dbw: int = 2700
    sql: int = 0


def clean_settings(args: dict, current: Settings) -> Settings:
    """Nouveaux réglages demandés par un opérateur ; SetRefused (message en français) si l'un est hors limites."""
    if not isinstance(args, dict) or set(args) - set(SET_LIMITS) - set(SET_BOOLS) - {"mode"}:
        raise SetRefused(f"réglages permis : {', '.join([*SET_LIMITS, *SET_BOOLS, 'mode'])}")
    values = asdict(current)
    for name in SET_BOOLS:
        if name in args:
            if not isinstance(args[name], bool):
                raise SetRefused(f"{name} : true ou false")
            values[name] = args[name]
    if "mode" in args:
        if args["mode"] not in MODES:
            raise SetRefused(f"mode : un de {', '.join(MODES)}")
        values["mode"] = args["mode"]
        if "dbw" not in args:
            values["dbw"] = DEFAULT_DBW[args["mode"]]     # largeur habituelle du nouveau mode
    for name, (lo, hi) in SET_LIMITS.items():
        if name not in args:
            continue
        v = args[name]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi or int(v) != v:
            raise SetRefused(f"{name} : entier de {lo} à {hi}")
        values[name] = int(v)
    return Settings(**values)


def listened(sd: cfgmod.Sdr, s: Settings, fs: int | None = None) -> int:
    """Fréquence écoutée : celle choisie si elle tient dans la largeur du SDR (95 %), sinon le centre."""
    half = (fs or sd.sample_rate_hz) * 0.475
    return s.dfreq_hz if s.dfreq_hz and abs(s.dfreq_hz - s.center_hz) <= half else s.center_hz


def audio_token(secret: str) -> bytes:
    """Jeton des paquets de son, dérivé du secret du module (la passerelle le dérive de la même clé)."""
    import hashlib
    import hmac
    return hmac.new(secret.encode("ascii"), b"sdr-audio", hashlib.sha256).digest()[:AUDIO_TOKEN_BYTES]


def low_rate(sd: cfgmod.Sdr) -> int:
    """Échantillonnage le plus bas de ce pilote (niveau 4 du bridage)."""
    return min(cfgmod.sdr_rates(sd.driver))


def core_args(sd: cfgmod.Sdr, s: Settings, level: int = 0) -> list[str]:
    """Arguments de sdr-core ; level = niveau de bridage appliqué (cadence du waterfall, échantillonnage)."""
    fs = sample_rate(sd.sample_rate_hz, level, low_rate(sd))
    return ["--driver", sd.driver, "--dfreq", str(listened(sd, s, fs)), "--mode", s.mode, "--dbw", str(s.dbw),
            "--sql", str(s.sql), "--serial", sd.serial, "--fs", str(fs), "--bw", str(cfgmod.SDR_RATES.get(fs, 0)),
            "--freq", str(s.center_hz), "--lna", str(s.lna), "--gr", str(s.gr), "--ant", sd.antenna,
            "--fft", str(sd.fft_size), "--bins", str(sd.bins), "--rate", str(waterfall_rate(s.rate, level)),
            "--agc", str(int(s.agc))]


def line_message(line: Line, now: float) -> dict:
    return {"kind": "sdr_line", "scope": "sdr_view", "c": round(line.center_hz), "s": round(line.span_hz),
            "d": base64.b64encode(line.values).decode("ascii"), "t": int(now * 1000)}


def proc_rss_mb(pid: int) -> float | None:
    """Mémoire résidente d'un processus en Mo (Linux, /proc) ; None ailleurs."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except (OSError, IndexError, ValueError):
        pass
    return None


def proc_cpu_seconds(pid: int) -> float | None:
    """Temps CPU d'un processus (Linux, /proc) ; None ailleurs."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError, AttributeError):
        return None


class SdrService:
    def __init__(self, sd: cfgmod.Sdr, state_dir: Path, bus=None, *, core: str | None = None,
                 core_prefix: list[str] | None = None, clock=time.time, emit=emit_event,
                 audio_secret: str = "", audio_sink=None) -> None:
        self.sd, self.bus, self.clock, self.emit = sd, bus, clock, emit
        self.core = core if core is not None else core_path(sd.core_path)
        self.core_prefix = list(core_prefix or [])     # essais : [python, -m, trxstation.devtools.fake_sdr_core]
        self.folder = Path(state_dir) / "sdr"
        self.settings = self._load_settings()
        self.proc: asyncio.subprocess.Process | None = None
        self.restarts = 0
        self.state: dict = {"state": "starting", "code": "", "detail": "", "serial": sd.serial,
                            "fs": sd.sample_rate_hz, "driver": sd.driver, "ant": sd.antenna, "bins": sd.bins, "overload": 0, "overloads": 0, "drops": 0,
                            "gaps": 0, "cpu": None, "restarts": 0}
        self._cpu_mark: tuple[float, float] | None = None
        self._self_cpu_mark: tuple[float, float] | None = None
        # bridage (load.py) : niveau décidé par la passerelle, et le sien au-delà de ses plafonds
        self.gw_level, self.gw_reason = 0, ""
        self.ladder = Ladder(top=TOP - 1, clock=self.clock)       # le module ne se suspend jamais lui-même
        self._applied = 0                      # niveau dont sdr-core a été lancé ou réglé
        self._reload = False                   # sdr-core arrêté exprès (échantillonnage changé) : pas une panne
        self._wake = asyncio.Event()
        self._last_loss = (0, 0)
        self._loss_reported_at = -1e9
        self._stopping = False
        # son démodulé vers la passerelle : demandé par elle (action « audio ») quand un opérateur écoute
        self.audio_on = False
        self._audio_seq = 0
        self._audio_token = audio_token(audio_secret) if audio_secret else b""
        self._audio_sink = audio_sink          # essais : fonction(paquet) ; sinon UDP vers 127.0.0.1:audio_port
        self._udp = None

    # ------------------------------------------------------------- réglages gardés
    def _load_settings(self) -> Settings:
        base = Settings(self.sd.center_hz, self.sd.lna_state, self.sd.gain_reduction_db, min(self.sd.lines_per_s, MAX_RATE),
                        self.sd.agc)
        try:
            data = json.loads((self.folder / "last.json").read_text(encoding="utf-8"))
            kept = {k: v for k, v in data.items() if (k in SET_LIMITS or k in SET_BOOLS or k == "mode")
                    and not (k == "dfreq_hz" and not v)}          # 0 = le centre
            return clean_settings(kept, base)
        except (OSError, ValueError, TypeError, AttributeError):
            return base

    def _save_settings(self) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / "last.json.tmp"
            tmp.write_text(json.dumps(asdict(self.settings)), encoding="utf-8")
            os.replace(tmp, self.folder / "last.json")
        except OSError as exc:
            log.warning("réglages SDR non gardés : %s", exc)

    # ------------------------------------------------------------- état publié
    def snapshot(self) -> dict:
        s = self.settings
        fs = sample_rate(self.sd.sample_rate_hz, self._applied, low_rate(self.sd))
        return {**self.state, "center": s.center_hz, "lna": s.lna, "gr": s.gr, "rate": s.rate, "agc": s.agc,
                "dfreq": listened(self.sd, s, fs), "mode": s.mode, "dbw": s.dbw, "sql": s.sql, "audio": self.demodulating,
                "restarts": self.restarts, "t": int(self.clock()), "fs": fs,
                "rate_eff": waterfall_rate(s.rate, self._applied), "load": self._applied,
                "load_gw": self.gw_level, "load_self": self.ladder.level, "load_reason": self.load_reason(),
                "max_cpu_pct": self.sd.max_cpu_pct, "max_mem_mb": self.sd.max_mem_mb}

    async def publish_state(self) -> None:
        await self._send({"kind": "sdr_state", "retain": "snapshot", "scope": "operators", **self.snapshot()})

    async def _send(self, message: dict) -> None:
        if self.bus is None or not self.bus.connected.is_set():
            return
        try:
            await self.bus.client_message(**message)
        except Exception as exc:          # cœur occupé, débit dépassé : la ligne suivante suivra
            log.debug("message SDR non publié : %s", exc)

    def _set_state(self, state: str, code: str = "", detail: str = "") -> None:
        self.state.update(state=state, code=code, detail=detail)

    # ------------------------------------------------------------- commandes des opérateurs
    async def on_call(self, data: dict) -> dict:
        from ..modules.client import CallRefused
        action = data.get("action")
        if action == "state":
            return self.snapshot()
        if action == "load":                   # de la PASSERELLE seulement : niveau de bridage (load.py)
            args = data.get("args") or {}
            level = args.get("level")
            if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= TOP:
                raise CallRefused("sdr_invalid", f"load : niveau de 0 à {TOP}")
            self.gw_level, self.gw_reason = level, str(args.get("reason") or "")[:160]
            await self._apply_load()
            return {"load": self.level}
        if action == "audio":                  # de la PASSERELLE seulement (un client ne peut pas l'envoyer)
            on = bool((data.get("args") or {}).get("on"))
            if on != self.audio_on:
                self.audio_on = on
                await self._write_core([f"audio {int(self.demodulating)}"])
                await self.publish_state()
            return {"audio": self.audio_on}
        if action == "set":
            try:
                new = clean_settings(data.get("args") or {}, self.settings)
            except SetRefused as exc:
                raise CallRefused("sdr_invalid", str(exc)) from None
            if ("dfreq_hz" in (data.get("args") or {})
                    and listened(self.sd, new, sample_rate(self.sd.sample_rate_hz, self._applied, low_rate(self.sd))) != new.dfreq_hz):
                raise CallRefused("sdr_invalid", "fréquence écoutée hors de la largeur du SDR : déplacer le centre")
            old, self.settings = self.settings, new
            await self._command_core(old, new)
            self._save_settings()
            await self.publish_state()
            return self.snapshot()
        raise CallRefused("sdr_invalid", "action inconnue (state, set)")

    # ------------------------------------------------------------- bridage
    @property
    def level(self) -> int:
        return max(self.gw_level, self.ladder.level)

    @property
    def demodulating(self) -> bool:
        """sdr-core démodule : quelqu'un écoute et aucun bridage (dès le niveau 1, plus de son du SDR)."""
        return self.audio_on and self._applied == 0

    def load_reason(self) -> str:
        if not self.level:
            return ""
        if self.gw_level >= self.ladder.level:
            return "station chargée : " + (self.gw_reason or "décision de la passerelle")
        return "module au-delà de ses plafonds : " + (self.ladder.reason or "?")

    async def _apply_load(self) -> None:
        """Applique le niveau courant : cadence du waterfall, échantillonnage (relance de sdr-core), suspension."""
        old, new = self._applied, self.level
        if old == new:
            await self.publish_state()
            return
        self._applied = new
        log.info("bridage du module : niveau %d (%s)%s", new, LEVEL_TEXT[new],
                 f", {self.load_reason()}" if new else "")
        fs_changed = sample_rate(self.sd.sample_rate_hz, old, low_rate(self.sd)) != sample_rate(self.sd.sample_rate_hz, new, low_rate(self.sd))
        if new >= TOP or old >= TOP or fs_changed:
            if self.proc is not None and self.proc.returncode is None:
                self._reload = True
                await self._write_core(["quit"])        # la boucle de lecture voit la fin et relance (ou suspend)
            self._wake.set()
        else:
            lines = []
            if waterfall_rate(self.settings.rate, old) != waterfall_rate(self.settings.rate, new):
                lines.append(f"rate {waterfall_rate(self.settings.rate, new)}")
            if self.audio_on and (old == 0) != (new == 0):
                lines.append(f"audio {int(self.demodulating)}")
            await self._write_core(lines)
        await self.publish_state()

    def _self_measure(self) -> bool:
        """Processeur et mémoire du module (sdr-core + module) ; échelle propre au-delà des plafonds. Vrai si le
        niveau propre change."""
        core_cpu = self.state.get("cpu")
        mine = self._self_cpu()
        cpu = None if core_cpu is None and mine is None else round((core_cpu or 0) + (mine or 0), 1)
        mems = [m for m in (proc_rss_mb(os.getpid()), proc_rss_mb(self.proc.pid) if self.proc else None) if m is not None]
        mem = round(sum(mems), 1) if mems else None
        self.state["cpu_total"], self.state["mem_mb"] = cpu, mem
        over = ""
        if cpu is not None and cpu > self.sd.max_cpu_pct:
            over = f"processeur à {cpu:.0f} % (plafond {self.sd.max_cpu_pct} %)"
        elif mem is not None and mem > self.sd.max_mem_mb:
            over = f"mémoire à {mem:.0f} Mo (plafond {self.sd.max_mem_mb} Mo)"
        green = ((cpu is None or cpu <= 0.7 * self.sd.max_cpu_pct) and (mem is None or mem <= 0.9 * self.sd.max_mem_mb))
        before = self.ladder.level
        changed = self.ladder.step(over, green)
        if changed and self.ladder.level > before:
            self.emit(codes.ORT_6008, logger=log, niveau=self.ladder.level, effet=LEVEL_TEXT[self.ladder.level],
                      cause=self.ladder.reason)
        return changed

    def _self_cpu(self) -> float | None:
        cpu, now = proc_cpu_seconds(os.getpid()), time.monotonic()
        if cpu is None:
            return None
        mark, self._self_cpu_mark = self._self_cpu_mark, (cpu, now)
        if mark is None or now <= mark[1]:
            return None
        return round(100.0 * (cpu - mark[0]) / (now - mark[1]), 1)

    async def _command_core(self, old: Settings, new: Settings) -> None:
        lines = []
        if new.center_hz != old.center_hz:
            lines.append(f"freq {new.center_hz}")
        if (new.lna, new.gr) != (old.lna, old.gr):
            lines.append(f"gain {new.lna} {new.gr}")
        if waterfall_rate(new.rate, self._applied) != waterfall_rate(old.rate, self._applied):
            lines.append(f"rate {waterfall_rate(new.rate, self._applied)}")
        if new.agc != old.agc:
            lines.append(f"agc {int(new.agc)}")
        fs = sample_rate(self.sd.sample_rate_hz, self._applied, low_rate(self.sd))
        if (listened(self.sd, new, fs), new.mode, new.dbw) != (listened(self.sd, old, fs), old.mode, old.dbw):
            lines.append(f"demod {listened(self.sd, new, fs)} {new.mode} {new.dbw}")
        if new.sql != old.sql:
            lines.append(f"sql {new.sql}")
        await self._write_core(lines)

    async def _write_core(self, lines: list[str]) -> None:
        proc = self.proc
        if not lines or proc is None or proc.stdin is None or proc.returncode is not None:
            return                         # pris en compte au prochain lancement
        try:
            proc.stdin.write(("\n".join(lines) + "\n").encode("ascii"))
            await proc.stdin.drain()
        except (ConnectionError, OSError) as exc:
            log.warning("réglage non transmis à sdr-core : %s", exc)

    # ------------------------------------------------------------- cœur natif
    async def run_core_once(self) -> tuple[int | None, dict | None]:
        """Lance sdr-core et lit ses trames jusqu'à son arrêt : (code de sortie, dernière erreur annoncée)."""
        self._set_state("starting")
        await self.publish_state()
        self._applied = self.level
        self.proc = await asyncio.create_subprocess_exec(
            *(self.core_prefix or [self.core]), *core_args(self.sd, self.settings, self._applied), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        err_task = asyncio.ensure_future(self._drain_stderr(self.proc))     # un tube jamais lu bloque l'enfant
        reader, error = FrameReader(), None
        last_state, dirty = 0.0, False
        try:
            while True:
                chunk = await self.proc.stdout.read(65536)
                if not chunk:
                    break
                try:
                    frames = reader.feed(chunk)
                except FrameError as exc:
                    log.warning("flux de sdr-core illisible (%s) : relance", exc)
                    self.proc.kill()
                    break
                for frame in frames:
                    if isinstance(frame, Line):
                        await self._send(line_message(frame, self.clock()))
                        continue
                    if isinstance(frame, Audio):
                        self._send_audio(frame.pcm)
                        continue
                    kind = frame.get("t")
                    if kind == "started":
                        self._set_state("running")
                        if self.demodulating:
                            await self._write_core(["audio 1"])     # cœur relancé pendant une écoute
                        log.info("SDR %s ouvert (API %s)", frame.get("serial"), frame.get("api"))
                        await self.publish_state()
                    elif kind == "status":
                        self._on_status(frame)
                        if self._self_measure():
                            await self._apply_load()
                    elif kind == "event" and frame.get("name") == "overload":
                        on = int(bool(frame.get("on")))
                        if on and not self.state["overload"]:
                            self.state["overloads"] = self.state.get("overloads", 0) + 1
                        dirty = dirty or on != self.state["overload"]
                        self.state["overload"] = on
                    elif kind == "event" and frame.get("name") == "squelch":
                        self.state["sql_open"] = int(bool(frame.get("open")))
                        dirty = True
                    elif kind == "error":
                        error = frame
                # une surcharge du CAN peut basculer des dizaines de fois par seconde : état publié au plus 1 fois/s
                now = self.clock()
                if now - last_state >= STATE_EVERY_S or (dirty and now - last_state >= STATE_MIN_GAP_S):
                    last_state, dirty = now, False
                    await self.publish_state()
        finally:
            if self.proc.returncode is None:
                await self._stop_core()
            rc = await self.proc.wait()
            err_task.cancel()
            self.proc = None
        return rc, error

    def _on_status(self, st: dict) -> None:
        for key in ("overload", "drops", "gaps", "sql_open"):
            if isinstance(st.get(key), int):
                self.state[key] = st[key]
        for key in ("chan_db", "noise_db"):                    # puissance du canal écouté et bruit estimé (dBFS)
            v = st.get(key)
            self.state[key] = v if isinstance(v, (int, float)) and v > -190 else None
        gr_now, gain = st.get("gr_now"), st.get("gain_db")      # gain réellement appliqué (AGC de la FI)
        self.state["gr_now"] = gr_now if isinstance(gr_now, int) and gr_now >= 0 else None
        self.state["gain_db"] = gain if isinstance(gain, (int, float)) and gain else None
        self.state["cpu"] = self._core_cpu()
        loss = (self.state["drops"], self.state["gaps"])
        now = self.clock()
        if loss != self._last_loss and loss > self._last_loss and now - self._loss_reported_at >= LOSS_REPORT_EVERY_S:
            self._loss_reported_at = now
            self.emit(codes.ORT_6005, logger=log, perdus=loss[0], trous=loss[1])
        self._last_loss = loss

    def _send_audio(self, pcm: bytes) -> None:
        """20 ms de son vers la passerelle (UDP local) ; perdu sans dommage si elle ne l'attend pas."""
        if not self.demodulating or not self._audio_token:
            return
        self._audio_seq = (self._audio_seq + 1) & 0xFFFFFFFF
        packet = AUDIO_MAGIC + self._audio_token + self._audio_seq.to_bytes(4, "little") + pcm
        if self._audio_sink is not None:
            self._audio_sink(packet)
            return
        try:
            if self._udp is None:
                import socket
                self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._udp.setblocking(False)
            self._udp.sendto(packet, ("127.0.0.1", self.sd.audio_port))
        except OSError:
            pass                               # passerelle arrêtée ou tampon plein : le paquet suivant suivra

    def _core_cpu(self) -> float | None:
        if self.proc is None:
            return None
        cpu, now = proc_cpu_seconds(self.proc.pid), time.monotonic()
        if cpu is None:
            return None
        mark, self._cpu_mark = self._cpu_mark, (cpu, now)
        if mark is None or now <= mark[1]:
            return None
        return round(100.0 * (cpu - mark[0]) / (now - mark[1]), 1)

    async def _drain_stderr(self, proc) -> None:
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            log.info("sdr-core : %s", line.decode("utf-8", "replace").rstrip())

    async def _stop_core(self) -> None:
        proc = self.proc
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.stdin.write(b"quit\n")
            await proc.stdin.drain()
            proc.stdin.close()
            await asyncio.wait_for(proc.wait(), STOP_GRACE_S)
        except (asyncio.TimeoutError, ConnectionError, OSError):
            proc.kill()

    async def _after_exit(self, rc: int | None, error: dict | None, ran_s: float) -> float:
        """Journalise la cause d'un arrêt de sdr-core et renvoie le délai avant le prochain essai."""
        code = (error or {}).get("code", "")
        detail = str((error or {}).get("detail", ""))[:200]
        if code in ("absent", "busy", "duplicate") or rc == 3:
            self._set_state("error", code or "absent", detail)
            self.emit(codes.ORT_6001, logger=log, serial=self.sd.serial,
                      detail={"busy": "déjà pris par une autre application",
                              "duplicate": "numéro de série en double (deux clés RTL-SDR identiques)"}.get(
                                  code, "absent de la liste du fabricant"))
            delay = RETRY_ABSENT_S
        elif code == "service" or rc == 4:
            self._set_state("error", "service", detail)
            self.emit(codes.ORT_6002, logger=log, detail=detail or "API du fabricant absente")
            delay = RETRY_ABSENT_S
        elif rc == 2:
            self._set_state("error", "config", "réglage refusé par sdr-core")
            self.emit(codes.ORT_6003, logger=log, chemin=self.core, detail="réglage refusé (voir [sdr] de station.toml)")
            delay = RETRY_CONFIG_S
        else:
            if ran_s >= STABLE_RUN_S:
                self.restarts = 0
            self.restarts += 1
            self._set_state("error", code or "exit", detail or f"code de sortie {rc}")
            self.emit(codes.ORT_6004, logger=log, detail=detail or f"code de sortie {rc}", relances=self.restarts)
            delay = min(BACKOFF_MAX_S, BACKOFF_MIN_S * 2 ** (self.restarts - 1))
        await self.publish_state()
        return delay

    # ------------------------------------------------------------- boucle principale
    async def run(self) -> None:
        tasks = []
        if self.bus is not None:
            self.bus.on_call = self.on_call
            self.bus.on_connect = self.publish_state
            tasks.append(asyncio.ensure_future(self._bus_forever()))
        try:
            while not self._stopping:
                if not self.core_prefix and (not self.core or not Path(self.core).is_file()):
                    self._set_state("error", "core_missing", "sdr-core introuvable")
                    self.emit(codes.ORT_6003, logger=log, chemin=self.core or self.sd.core_path or "sdr-core",
                              detail="programme absent (installer l'API du fabricant puis relancer l'installation)")
                    await self.publish_state()
                    await asyncio.sleep(RETRY_CONFIG_S)
                    self.core = core_path(self.sd.core_path)
                    continue
                if self.level >= TOP:                     # suspendu par la passerelle : sdr-core arrêté
                    self._applied = self.level
                    self._set_state("suspended", "load", self.load_reason())
                    await self.publish_state()
                    self._wake.clear()
                    while self.level >= TOP and not self._stopping:
                        try:
                            await asyncio.wait_for(self._wake.wait(), 5.0)
                        except asyncio.TimeoutError:
                            pass
                        self._wake.clear()
                    continue
                started = time.monotonic()
                self._reload = False
                try:
                    rc, error = await self.run_core_once()
                except OSError as exc:
                    rc, error = None, {"code": "exit", "detail": f"lancement impossible : {exc}"}
                if self._stopping:
                    break
                if self._reload:                          # arrêt voulu (bridage) : relance immédiate, pas une panne
                    self._reload = False
                    continue
                await asyncio.sleep(await self._after_exit(rc, error, time.monotonic() - started))
        finally:
            self._stopping = True
            await self._stop_core()
            for t in tasks:
                t.cancel()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()

    async def _bus_forever(self) -> None:
        try:
            await self.bus.run_forever()
        except Exception as exc:
            log.warning("API interne indisponible : %s", exc)


def setup_logging(folder: Path) -> None:
    fmt = logging.Formatter("%(asctime)s sdr %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(folder / "sdr.log", maxBytes=1_000_000, backupCount=2,
                                                       encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError as exc:
        log.warning("journal %s impossible : %s", folder / "sdr.log", exc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.sdr.service", description="Module SDR")
    ap.add_argument("--config", type=Path, default=Path(os.environ.get("TRX_CONFIG_PATH") or default_config_path()))
    ap.add_argument("--once", action="store_true", help="essai : 10 s de sdr-core puis l'état")
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration illisible ({args.config}) : {exc}", file=sys.stderr)
        return 2
    if not cfg.sdr.serial:
        print("[sdr] serial est vide : le SDR doit être désigné par son numéro (trx-sdr --list)", file=sys.stderr)
        return 2
    state_dir = Path(cfg.supervisor.state_dir)
    if args.once:
        svc = SdrService(cfg.sdr, state_dir)

        async def once() -> None:
            task = asyncio.ensure_future(svc.run())
            await asyncio.sleep(10)
            svc.stop()
            await asyncio.gather(task, return_exceptions=True)
        asyncio.run(once())
        print(json.dumps(svc.snapshot(), ensure_ascii=False, indent=1))
        return 0
    setup_logging(state_dir / "sdr")
    bus = None
    if os.environ.get("TRX_MODULE_SECRET"):
        from ..modules.client import ModuleClient
        bus = ModuleClient.from_env()
    log.info("démarrage : SDR %s, %d Hz", cfg.sdr.serial, cfg.sdr.sample_rate_hz)
    try:
        asyncio.run(SdrService(cfg.sdr, state_dir, bus, audio_secret=os.environ.get("TRX_MODULE_SECRET", "")).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
