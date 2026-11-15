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
rate, agc). Le module n'a AUCUN droit sur le poste et ne redémarre JAMAIS le service du fabricant (commun à la machine).
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
from .frames import FrameError, FrameReader, Line

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
SET_BOOLS = ("agc",)           # AGC matériel de la FI


class SetRefused(ValueError):
    pass


@dataclass
class Settings:
    center_hz: int
    lna: int
    gr: int
    rate: int
    agc: bool = True


def clean_settings(args: dict, current: Settings) -> Settings:
    """Nouveaux réglages demandés par un opérateur ; SetRefused (message en français) si l'un est hors limites."""
    if not isinstance(args, dict) or set(args) - set(SET_LIMITS) - set(SET_BOOLS):
        raise SetRefused(f"réglages permis : {', '.join([*SET_LIMITS, *SET_BOOLS])}")
    values = asdict(current)
    for name in SET_BOOLS:
        if name in args:
            if not isinstance(args[name], bool):
                raise SetRefused(f"{name} : true ou false")
            values[name] = args[name]
    for name, (lo, hi) in SET_LIMITS.items():
        if name not in args:
            continue
        v = args[name]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi or int(v) != v:
            raise SetRefused(f"{name} : entier de {lo} à {hi}")
        values[name] = int(v)
    return Settings(**values)


def core_args(sd: cfgmod.Sdr, s: Settings) -> list[str]:
    return ["--serial", sd.serial, "--fs", str(sd.sample_rate_hz), "--bw", str(cfgmod.SDR_RATES[sd.sample_rate_hz]),
            "--freq", str(s.center_hz), "--lna", str(s.lna), "--gr", str(s.gr), "--ant", sd.antenna,
            "--fft", str(sd.fft_size), "--bins", str(sd.bins), "--rate", str(s.rate), "--agc", str(int(s.agc))]


def line_message(line: Line, now: float) -> dict:
    return {"kind": "sdr_line", "scope": "sdr_view", "c": round(line.center_hz), "s": round(line.span_hz),
            "d": base64.b64encode(line.values).decode("ascii"), "t": int(now * 1000)}


def proc_cpu_seconds(pid: int) -> float | None:
    """Temps CPU d'un processus (Linux, /proc) ; None ailleurs."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError, AttributeError):
        return None


class SdrService:
    def __init__(self, sd: cfgmod.Sdr, state_dir: Path, bus=None, *, core: str | None = None,
                 core_prefix: list[str] | None = None, clock=time.time, emit=emit_event) -> None:
        self.sd, self.bus, self.clock, self.emit = sd, bus, clock, emit
        self.core = core if core is not None else core_path(sd.core_path)
        self.core_prefix = list(core_prefix or [])     # essais : [python, -m, trxstation.devtools.fake_sdr_core]
        self.folder = Path(state_dir) / "sdr"
        self.settings = self._load_settings()
        self.proc: asyncio.subprocess.Process | None = None
        self.restarts = 0
        self.state: dict = {"state": "starting", "code": "", "detail": "", "serial": sd.serial,
                            "fs": sd.sample_rate_hz, "ant": sd.antenna, "bins": sd.bins, "overload": 0, "overloads": 0, "drops": 0,
                            "gaps": 0, "cpu": None, "restarts": 0}
        self._cpu_mark: tuple[float, float] | None = None
        self._last_loss = (0, 0)
        self._loss_reported_at = -1e9
        self._stopping = False

    # ------------------------------------------------------------- réglages gardés
    def _load_settings(self) -> Settings:
        base = Settings(self.sd.center_hz, self.sd.lna_state, self.sd.gain_reduction_db, min(self.sd.lines_per_s, MAX_RATE),
                        self.sd.agc)
        try:
            data = json.loads((self.folder / "last.json").read_text(encoding="utf-8"))
            return clean_settings({k: v for k, v in data.items() if k in SET_LIMITS or k in SET_BOOLS}, base)
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
        return {**self.state, "center": s.center_hz, "lna": s.lna, "gr": s.gr, "rate": s.rate, "agc": s.agc,
                "restarts": self.restarts, "t": int(self.clock())}

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
        if action == "set":
            try:
                new = clean_settings(data.get("args") or {}, self.settings)
            except SetRefused as exc:
                raise CallRefused("sdr_invalid", str(exc)) from None
            old, self.settings = self.settings, new
            await self._command_core(old, new)
            self._save_settings()
            await self.publish_state()
            return self.snapshot()
        raise CallRefused("sdr_invalid", "action inconnue (state, set)")

    async def _command_core(self, old: Settings, new: Settings) -> None:
        lines = []
        if new.center_hz != old.center_hz:
            lines.append(f"freq {new.center_hz}")
        if (new.lna, new.gr) != (old.lna, old.gr):
            lines.append(f"gain {new.lna} {new.gr}")
        if new.rate != old.rate:
            lines.append(f"rate {new.rate}")
        if new.agc != old.agc:
            lines.append(f"agc {int(new.agc)}")
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
        self.proc = await asyncio.create_subprocess_exec(
            *(self.core_prefix or [self.core]), *core_args(self.sd, self.settings), stdin=asyncio.subprocess.PIPE,
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
                    kind = frame.get("t")
                    if kind == "started":
                        self._set_state("running")
                        log.info("SDR %s ouvert (API %s)", frame.get("serial"), frame.get("api"))
                        await self.publish_state()
                    elif kind == "status":
                        self._on_status(frame)
                    elif kind == "event" and frame.get("name") == "overload":
                        on = int(bool(frame.get("on")))
                        if on and not self.state["overload"]:
                            self.state["overloads"] = self.state.get("overloads", 0) + 1
                        dirty = dirty or on != self.state["overload"]
                        self.state["overload"] = on
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
        for key in ("overload", "drops", "gaps"):
            if isinstance(st.get(key), int):
                self.state[key] = st[key]
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
        if code in ("absent", "busy") or rc == 3:
            self._set_state("error", code or "absent", detail)
            self.emit(codes.ORT_6001, logger=log, serial=self.sd.serial,
                      detail="déjà pris par une autre application" if code == "busy" else "absent de la liste du fabricant")
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
                started = time.monotonic()
                try:
                    rc, error = await self.run_core_once()
                except OSError as exc:
                    rc, error = None, {"code": "exit", "detail": f"lancement impossible : {exc}"}
                if self._stopping:
                    break
                await asyncio.sleep(await self._after_exit(rc, error, time.monotonic() - started))
        finally:
            self._stopping = True
            await self._stop_core()
            for t in tasks:
                t.cancel()

    def stop(self) -> None:
        self._stopping = True
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
        asyncio.run(SdrService(cfg.sdr, state_dir, bus).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
