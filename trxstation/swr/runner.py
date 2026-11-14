# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Moteur de la mesure de TOS dans la passerelle (docs/tos-cahier-des-charges.md § 6, § 6 bis, § 7).

SÉCURITÉ (règles d'émission, priorité absolue) :
- chaque point est une prise d'émission NORMALE du client qui a lancé la mesure (`PttController.key_without_audio` :
  mêmes refus que toggle, battements, TOT, bandes si `enforce_bands`, mode permis), porte audio FERMÉE ;
- le compteur de coupures du contrôleur (`epoch`) est relu à chaque étape : toute coupure qui n'est pas la nôtre
  (STOP de n'importe quel client, TOT, battement perdu, déconnexion, poste utilisé sur place, défaut...) ARRÊTE la
  mesure, jamais de point suivant, jamais de reprise ;
- quoi qu'il arrive (fin, annulation, coupure, erreur), RX confirmé d'abord, puis remise en état RELUE (puissance, mode,
  fréquence, coupleur), puis réservation libérée ;
- ce module ne fait que des prises normales et des coupures : il n'a aucun moyen d'émettre autrement.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections.abc import Callable

from ..gateway.cat import RigError
from ..gateway.safety import Refused
from . import plan as planmod
from .store import SwrStore
from ..errors import codes
from ..errors.emit import emit_event

log = logging.getLogger(__name__)

FM_MODES = ("FM", "PKTFM", "FM-D")      # ordre de préférence ; le premier permis par tx_modes et annoncé par le poste
STABLE_READS, STABLE_SPREAD, SETTLE_MARGIN_S, SETTLE_MIN_S = 3, 0.05, 0.2, 0.3
READ_PERIOD_S = 0.05
COOLDOWN_WAIT_S = 3.0                   # anti-rebond du PTT entre deux points (rekey_cooldown_s) : attente au plus
REDUCED_POWER = 0.5                     # puissance lue sous la moitié de la demande : « puissance réduite par le poste »


class SwrAbort(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason, self.detail = reason, detail


class SwrRunner:
    def __init__(self, ctrl, cfg, store: SwrStore, *, clock: Callable[[], float] = time.monotonic, sleep=asyncio.sleep):
        self.ctrl, self.cfg, self.store = ctrl, cfg, store
        self.clock, self.sleep = clock, sleep
        self.task: asyncio.Task | None = None
        self.owner: str | None = None
        self._progress: dict = {}

    def status(self) -> dict:
        """Pour le fichier d'état de la passerelle (trx-monitor) : mesure en cours, client, étape, point."""
        if not self.busy:
            return {"running": False}
        p = self._progress
        return {"running": True, "owner": self.owner, "state": p.get("state", "preparing"),
                "done": sum(1 for x in p.get("points", []) if x.get("swr") is not None), "total": p.get("total", 0)}

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    # ------------------------------------------------------------------ préparation (n'émet rien)

    def fm_mode(self) -> str | None:
        caps = self.ctrl.link.capabilities
        modes = set(caps.modes) if caps is not None and caps.complete else set(FM_MODES)
        allowed = self.cfg.rig.tx_modes
        return next((m for m in FM_MODES if m in modes and (not allowed or m in allowed)), None)

    def make_plan(self, low_hz: int, high_hz: int, points: int, power_pct: float | None = None) -> dict:
        """Plan affiché avant le lancement (commande swr_plan) : points, pas, hors bande, avertissement, puissance, durée."""
        s = self.cfg.swr
        plan = planmod.plan(low_hz, high_hz, points, s.max_points)
        enforce = self.cfg.safety.enforce_bands
        pts = [{"hz": f, "status": "out_of_band" if enforce and not self.cfg.tx_allowed(f) else "pending"} for f in plan["freqs"]]
        if all(p["status"] == "out_of_band" for p in pts):
            raise planmod.PlanError("swr_out_of_band", "aucun point dans les bandes autorisées de la station")
        pct = min(float(power_pct if power_pct is not None else 15), float(s.max_power_pct))
        model = self.cfg.rig.model
        settle = self.store.settle_s(model)
        per_point = (settle or s.point_tx_max_s) + 1.6          # émission + anti-rebond + QSY
        measured = sum(p["status"] == "pending" for p in pts)
        return {"low_hz": plan["low_hz"], "high_hz": plan["high_hz"], "step_hz": plan["step_hz"], "points": pts,
                "amateur_only": plan["amateur_only"], "fm_mode": self.fm_mode(), "power_pct": pct,
                "power_w": round(self.cfg.rig.max_power_w * pct / 100, 1) if self.cfg.rig.max_power_w else None,
                "max_power_pct": s.max_power_pct, "settle_s": settle, "calibration_needed": settle is None,
                "estimated_s": round(measured * per_point + (0 if settle else s.point_tx_max_s + 1.5), 1)}

    # ------------------------------------------------------------------ commandes

    async def start(self, client_id: str, low_hz: int, high_hz: int, points: int, power_pct: float,
                    send: Callable[[dict], None]) -> dict:
        """Lance la mesure en tâche de fond ; renvoie le plan. Refus (Refused) si impossible ; rien n'est touché."""
        if self.busy:
            raise Refused("swr_busy", f"mesure de TOS déjà en cours ({self.owner})")
        if not self.cfg.swr.enabled:
            raise Refused("swr_unavailable")
        try:
            plan = self.make_plan(low_hz, high_hz, points, power_pct)
        except planmod.PlanError as exc:
            raise Refused(exc.code, str(exc)) from exc
        if plan["fm_mode"] is None:
            raise Refused("swr_no_fm_mode", "aucun mode FM permis (tx_modes) : ajouter FM-D, par exemple")
        snap = self.ctrl.snapshot()
        if snap.state != "RX":
            raise Refused("tx_active", "mesure possible seulement en réception")
        if self.ctrl.reserved_by is not None:
            raise Refused("swr_busy")
        self.store.save_choices(client_id, plan["power_pct"], points)
        self.owner = client_id
        self.ctrl.reserve(client_id)
        self.task = asyncio.get_running_loop().create_task(self._run(client_id, plan, send))
        return plan

    async def cancel(self, client_id: str) -> None:
        """Annuler : coupure immédiate (toujours permise) ; la mesure la voit, s'arrête et remet le poste en état."""
        if self.busy:
            await self.ctrl.force_rx("swr_cancel", by=client_id)

    # ------------------------------------------------------------------ déroulé

    def _check(self, epoch: int) -> None:
        if self.ctrl.epoch != epoch:
            raise SwrAbort("cut", self.ctrl.last_cut_request or "coupure")

    async def _key(self, client_id: str, epoch: int) -> int:
        """Prise d'émission normale (porte audio fermée) ; attend l'anti-rebond du PTT entre deux points. `epoch` = celui
        que la mesure connaît : s'il a changé (coupure entre-temps), c'est une coupure, jamais une prise. Renvoie l'epoch."""
        deadline, before = self.clock() + COOLDOWN_WAIT_S, epoch
        while True:
            self._check(before)
            try:
                await self.ctrl.key_without_audio(client_id)
                return self.ctrl.epoch
            except Refused as exc:
                if self.ctrl.epoch != before or exc.reason == "cancelled":        # coupé pendant la prise : coupure
                    raise SwrAbort("cut", self.ctrl.last_cut_request or "coupure") from exc
                if exc.reason == "cooldown" and self.clock() < deadline:
                    await self.sleep(0.1)
                    continue
                raise SwrAbort(exc.reason, str(exc)) from exc

    async def _unkey(self, client_id: str) -> int:
        await self.ctrl.force_rx("swr_point", by=client_id)
        return self.ctrl.epoch

    async def _read(self, name: str) -> float | None:
        try:
            return float(await self.ctrl.link.client.get_level(name))
        except Exception:                                   # une lecture manquée n'arrête pas la mesure
            return None

    async def _read_rig(self) -> dict:
        client = self.ctrl.link.client
        try:
            freq = await client.get_frequency()
            mode, passband = await client.get_mode()
        except Exception as exc:
            raise SwrAbort("swr_unreadable", f"état du poste illisible : {exc}") from exc
        power = await self._read("RFPOWER")
        try:
            tuner = bool(await client.get_func("TUNER"))
        except RigError:
            tuner = None                                    # poste sans coupleur lisible : rien à couper ni à remettre
        except Exception as exc:
            raise SwrAbort("swr_unreadable", f"coupleur illisible : {exc}") from exc
        return {"frequency_hz": freq, "mode": mode, "passband_hz": passband, "rfpower": power, "tuner": tuner}

    async def _sample(self, seconds: float, epoch: int) -> tuple[list[float], list[float]]:
        """Lectures du TOS et de la puissance sur la seconde moitié de l'émission du point."""
        start = self.clock()
        swr, power = [], []
        while True:
            self._check(epoch)
            elapsed = self.clock() - start
            if elapsed >= seconds and swr:
                break
            if elapsed >= seconds + 1.0:                    # rien de lisible : on n'insiste pas
                break
            if elapsed >= seconds / 2:
                value = await self._read("SWR")
                if value is not None and value > 0:
                    swr.append(value)
                p = await self._read("RFPOWER_METER")
                if p is not None:
                    power.append(p)
            await self.sleep(READ_PERIOD_S)
        return swr, power

    async def _calibrate(self, client_id: str, hz: int) -> float:
        """§ 6 bis : temps de lecture fiable du TOS sur ce poste (une seule prise d'émission)."""
        epoch = self.ctrl.epoch
        await self.ctrl.set_frequency(hz)
        epoch = await self._key(client_id, epoch)
        start, reads, settle = self.clock(), [], None
        limit = float(self.cfg.swr.point_tx_max_s)
        try:
            while self.clock() - start < limit:
                self._check(epoch)
                value, power = await self._read("SWR"), await self._read("RFPOWER_METER")
                if value is not None and value > 0 and power:
                    reads.append((self.clock() - start, value))
                    last = [v for _, v in reads[-STABLE_READS:]]
                    if len(last) == STABLE_READS and max(last) - min(last) <= STABLE_SPREAD:
                        settle = reads[-STABLE_READS][0] + SETTLE_MARGIN_S
                        break
                await self.sleep(READ_PERIOD_S)
        finally:
            if self.ctrl.epoch == epoch:
                await self._unkey(client_id)
        if settle is None:
            emit_event(codes.ORT_5509, logger=log, secondes=round(limit, 1))
            return limit
        return round(min(limit, max(SETTLE_MIN_S, settle)), 2)

    async def _run(self, client_id: str, plan: dict, send: Callable[[dict], None]) -> None:
        ctrl, cfg = self.ctrl, self.cfg
        points = [dict(p, swr=None, power_w=None) for p in plan["points"]]
        rf = plan["power_pct"] / 100
        caps = ctrl.link.capabilities
        if caps is not None and caps.level_ranges.get("RFPOWER"):
            rf = max(rf, float(caps.level_ranges["RFPOWER"][0]))       # minimum du poste (IC-7300 : 5 %)
        saved, reason, detail, warning = None, "done", "", ""

        def progress(state: str, index: int | None = None, **extra) -> None:
            message = {"type": "swr", "state": state, "index": index, "total": len(points), "points": points, **extra}
            self._progress = message
            send(message)

        try:
            progress("preparing")
            epoch = ctrl.epoch
            saved = await self._read_rig()
            self._check(epoch)
            if saved["tuner"]:
                await ctrl.set_function("TUNER", False)
            await ctrl.set_mode(plan["fm_mode"], 0)
            await ctrl.set_power_exact(round(rf, 3))
            mode, _ = await ctrl.link.client.get_mode()
            power = await self._read("RFPOWER")
            if mode != plan["fm_mode"] or power is None or abs(power - rf) > 0.03:
                raise SwrAbort("swr_unreadable", f"réglages non relus (mode {mode}, puissance {power})")
            self._check(epoch)
            settle = self.store.settle_s(cfg.rig.model)
            if settle is None:
                progress("calibrating")
                first = next(p["hz"] for p in points if p["status"] == "pending")
                settle = await self._calibrate(client_id, first)
                if settle >= cfg.swr.point_tx_max_s:
                    warning = "swr_unstable"
                self.store.save_settle(cfg.rig.model, settle)
                epoch = ctrl.epoch
            for i, p in enumerate(points):
                if p["status"] == "out_of_band":
                    continue
                self._check(epoch)
                await ctrl.set_frequency(p["hz"])
                epoch = await self._key(client_id, epoch)
                swr, power = await self._sample(settle, epoch)
                epoch = await self._unkey(client_id)
                if swr:
                    p["swr"] = round(statistics.median(swr), 2)
                    p["status"] = "measured"
                else:
                    p["status"] = "unread"
                if power:
                    frac = statistics.median(power)
                    if cfg.rig.max_power_w:
                        p["power_w"] = round(frac * cfg.rig.max_power_w, 1)
                    if frac < rf * REDUCED_POWER:
                        p["status"] = "reduced"
                progress("measuring", i)
        except SwrAbort as exc:
            reason, detail = exc.reason, exc.detail
        except Refused as exc:                              # réglage refusé (émission en cours, poste sur place...)
            reason, detail = exc.reason, str(exc)
        except asyncio.CancelledError:
            reason = "cancelled"
            raise
        except Exception as exc:
            emit_event(codes.ORT_5508, logger=log, trace=True, detail=str(exc))
            reason, detail = "swr_failed", str(exc)
        finally:
            await self._finish(client_id, plan, points, saved, reason, detail, warning, progress)

    async def _finish(self, client_id, plan, points, saved, reason, detail, warning, progress) -> None:
        ctrl = self.ctrl
        restored, differences = {}, []
        try:
            if ctrl.snapshot().state != "RX":
                await ctrl.force_rx("swr_end", by=client_id)
            for _ in range(100):                            # RX confirmé, coupure terminée, avant toute remise en état
                if ctrl.rx_settled:
                    break
                await self.sleep(0.05)
            if saved is not None and ctrl.rx_settled:
                progress("restoring")
                restored, differences = await self._restore(saved)
        except Exception as exc:
            emit_event(codes.ORT_5512, logger=log, trace=True, ecarts=f"remise en état impossible : {exc}")
            differences.append(f"remise en état impossible : {exc}")
        finally:
            ctrl.release_reservation(client_id)
            self.owner = None
        measured = [p for p in points if p.get("swr") is not None]
        best = min(measured, key=lambda p: p["swr"]) if measured else None
        result = {"low_hz": plan["low_hz"], "high_hz": plan["high_hz"], "step_hz": plan["step_hz"],
                  "fm_mode": plan["fm_mode"], "power_pct": plan["power_pct"], "power_w": plan["power_w"],
                  "points": points, "best": best, "reason": reason, "detail": detail, "warning": warning,
                  "saved": saved, "restored": restored, "differences": differences, "at": time.time()}
        if measured:
            self.store.save_last(result)
        state = "done" if reason == "done" else "cancelled" if reason in ("cut",) and detail == "swr_cancel" else \
            "cut" if reason == "cut" else "failed"
        if state == "done":
            log.info("mesure de TOS terminée : %d points mesurés", len(measured))
        elif state in ("cancelled", "cut"):
            emit_event(codes.ORT_5506, logger=log, raison=f"{reason} {detail}".strip(), points=len(measured))
        else:
            emit_event(codes.ORT_5508, logger=log, detail=f"{reason} {detail}".strip(), points=len(measured))
        progress(state, None, result=result)

    async def _restore(self, saved: dict) -> tuple[dict, list[str]]:
        """Remise en état (en RX seulement), chaque valeur relue ; renvoie (état relu, écarts lisibles)."""
        ctrl, client, diffs = self.ctrl, self.ctrl.link.client, []

        async def attempt(label: str, coro) -> None:
            try:
                await coro
            except Exception as exc:
                diffs.append(f"{label} : non remis ({exc})")

        if saved.get("rfpower") is not None:
            await attempt("puissance", ctrl.set_power_exact(round(saved["rfpower"], 3)))
        await attempt("mode", ctrl.set_mode(saved["mode"], saved["passband_hz"] or 0))
        await attempt("fréquence", ctrl.set_frequency(saved["frequency_hz"]))
        if saved.get("tuner"):
            await attempt("coupleur", ctrl.set_function("TUNER", True))
        now = await self._read_rig()
        if now["frequency_hz"] != saved["frequency_hz"]:
            diffs.append(f"fréquence : {now['frequency_hz']} Hz au lieu de {saved['frequency_hz']} Hz")
        if now["mode"] != saved["mode"]:
            diffs.append(f"mode : {now['mode']} au lieu de {saved['mode']}")
        if saved.get("rfpower") is not None and (now["rfpower"] is None or abs(now["rfpower"] - saved["rfpower"]) > 0.03):
            diffs.append(f"puissance : {now['rfpower']} au lieu de {saved['rfpower']}")
        if saved.get("tuner") is not None and now["tuner"] != saved["tuner"]:
            diffs.append("coupleur : " + ("non remis en service, à rallumer à la main" if saved["tuner"] else "resté en service"))
        return now, diffs
