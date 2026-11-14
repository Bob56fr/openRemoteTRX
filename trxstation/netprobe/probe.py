# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sonde de qualité réseau de la passerelle (docs/netprobe-cahier-des-charges.md § 4 à § 9).

NetProbeHub : service commun (journal, coupures, diagnostic, profil VPN partagé, alertes, statistiques) ;
ClientProbe : la sonde d'UNE connexion (battement réseau dans les deux sens, indicateurs, état `state.net`).

La sonde MESURE et AFFICHE seulement : elle n'a aucun accès au PttController, à la porte audio ni au CAT, et une
erreur chez elle ne doit jamais gêner la session (chaque entrée est protégée par la session).
Horloges : battements sur l'horloge MONOTONE de la station (ms) ; dates des coupures et du journal sur son horloge
murale ; les dates des résumés du client sont recalées sur celle de la station par l'écart estimé (§ 4.7).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path

from ..errors import codes
from . import calc
from .store import NetStore
from .vpn import VpnWatch
from ..errors.emit import emit_event

log = logging.getLogger(__name__)
WINDOW_MS = 10_000
KEEP_BEATS_MS = 70_000                 # fenêtre de 60 s + 5 s d'écho tardif + marge
KEEP_REPORTS_MS = 900_000              # 15 min de résumés du client (diagnostic après coup)
DIAGNOSE_AFTER_MS = 15_000             # attente des résumés du client avant de conclure (un résumé toutes les 10 s)
CLEAR_REQUEST = "netprobe-clear.json"   # « Tout effacer » demandé par TRX Console (menu 2.4), écrit par sudo
CLEAR_MAX_AGE_S = 10.0
RECONNECT_LINK_MS = 1_800_000          # une reconnexion du même appareil dans les 30 min clôt une coupure « déconnexion »
REPORT_FRESH_MS = 30_000               # signal radio pris en compte dans le niveau s'il date de moins de 30 s
SKEW_WARN_MS = 1_000                   # écart d'horloge client / station signalé dans le journal


def _mono_ms() -> int:
    return int(time.monotonic() * 1000)


def _wall_ms() -> int:
    return int(time.time() * 1000)


class NetProbeHub:
    def __init__(self, cfg, state_dir: str | Path, *, alert=None, tx_counter=None, probes=None,
                 mono_ms=_mono_ms, wall_ms=_wall_ms) -> None:
        """`cfg` : section [netprobe] ; `alert` : (code du catalogue, détail) -> None (Notifier.alert) ; `tx_counter` : () -> (propriétaire de
        l'émission, trous + son jeté du son d'émission), pour reconnaître une fenêtre au son dégradé."""
        self.cfg, self.alert, self.tx_counter = cfg, alert, tx_counter
        self.mono_ms, self.wall_ms = mono_ms, wall_ms
        self.state_dir = Path(state_dir)
        self.store = NetStore(self.state_dir / "netprobe", cfg.log_retention_days, cfg.stats_retention_days, wall_ms)
        self._next_clear_check = 0
        self.vpn = VpnWatch(self.store, cfg.vpn_shared_warn, self._alert_now, wall_ms)
        self.connections: list[ClientProbe] = []
        self.reports: dict[str, deque] = {}        # appareil -> (date station, résumé) des 15 dernières minutes
        self.offsets: dict[str, int] = {}          # appareil -> écart horloge station - horloge client (ms)
        self.last_seen: dict[str, dict] = {}       # appareil -> dernière nouvelle avant une fermeture (coupure « déconnexion »)
        self.outages_by_device: dict[str, list[dict]] = {}
        self.pending: list[dict] = []              # coupures en attente de diagnostic
        self.last_outage: dict | None = None
        self._last_alert = -10**12
        self.probes = probes                       # StationProbes (box, Internet) ou None
        self.probe_facts = probes.facts if probes is not None else (lambda start_ms, end_ms: {})
        self._next_probe_log = mono_ms() + WINDOW_MS

    # ------------------------------------------------------------------ connexions

    def open(self, client_id: str, role: str, device: str, agent: str, source: str, send) -> "ClientProbe":
        journal = role != "listener"                     # visiteur : son propre indicateur, rien d'enregistré
        probe = ClientProbe(self, client_id, role, device, agent, source, send, journal)
        others = [(p.source, p.device, p.agent) for p in self.connections if p.journal]
        self.connections.append(probe)                        # avant l'avertissement : le nouveau venu le reçoit aussi
        if journal and device:
            warning = self.vpn.opened(source, device, agent, others)
            if warning is not None:
                self.broadcast({"type": "net_event", "event": "vpn_shared", "warning": warning})
            seen = self.last_seen.pop(device, None)
            if seen is not None and 0 < self.wall_ms() - seen["end_ms"] <= RECONNECT_LINK_MS:
                self._outage_found({"start_ms": seen["end_ms"], "end_ms": self.wall_ms(), "device": device,
                                    "agent": agent or seen["agent"], "client": client_id, "net_type": seen["net_type"],
                                    "kind": "disconnect", "seen_by": "station"})
        return probe

    def close(self, probe: "ClientProbe") -> None:
        if probe in self.connections:
            self.connections.remove(probe)
        if probe.journal and probe.device:
            self.vpn.closed(probe.source, probe.device, probe.agent)
            last = probe.last_echo_wall or probe.opened_wall
            if probe.outage_start_wall is not None:
                last = probe.outage_start_wall           # déjà sans nouvelles : la coupure a commencé plus tôt
            self.last_seen[probe.device] = {"end_ms": last, "agent": probe.agent, "net_type": probe.net_type}

    def broadcast(self, message: dict) -> None:
        """Vers les OPÉRATEURS connectés (jamais vers un visiteur)."""
        for probe in list(self.connections):
            if probe.journal:
                probe.send(message)

    # ------------------------------------------------------------------ résumés du client

    def add_reports(self, probe: "ClientProbe", reports: list[dict]) -> None:
        if not probe.device:
            return
        offset = self.offsets.get(probe.device, 0)
        queue = self.reports.setdefault(probe.device, deque())
        for report in reports:
            queue.append((report["t"] + offset, report))
            if probe.journal:
                self.store.log({"ts": report["t"] + offset, "src": "client", "kind": "mesure", "device": probe.device,
                                "client": probe.client_id, **{k: v for k, v in report.items() if k != "t"}})
        limit = self.wall_ms() - KEEP_REPORTS_MS
        while queue and queue[0][0] < limit:
            queue.popleft()

    def _facts(self, device: str, start: int, end: int) -> dict:
        rows = [r for t, r in self.reports.get(device, ()) if start - 10_000 <= t <= end + 15_000]
        during = [r for t, r in self.reports.get(device, ()) if start <= t <= end + 10_000]
        facts: dict = {"backlog": bool(rows)}
        if during:
            ok = any(r["health_ok"] for r in during)
            fail = any(r["health_fail"] for r in during)
            facts["health_ok"] = True if ok else (False if fail else None)
        before = [r for t, r in self.reports.get(device, ()) if start - 10_000 <= t <= end]
        cfg = self.cfg
        facts["radio_weak"] = any((r["rsrp_dbm"] is not None and r["rsrp_dbm"] < cfg.rsrp_alert_dbm)
                                  or (r["sinr_db"] is not None and r["sinr_db"] < cfg.sinr_alert_db) for r in before)
        facts["cell_changed"] = any(r["cell_changed"] for r in rows)
        facts["network_switched"] = any(r["net_switched"] for r in rows)
        history = self.outages_by_device.get(device, [])
        facts["regular_pattern"] = calc.regular_pattern(history, end)["regular"]
        facts.update(self.probe_facts(start, end))
        return facts

    # ------------------------------------------------------------------ coupures

    def _outage_found(self, outage: dict) -> None:
        outage["duration_ms"] = max(0, outage["end_ms"] - outage["start_ms"])
        history = self.outages_by_device.setdefault(outage["device"] or outage["client"], [])
        history.append({"start_ms": outage["start_ms"], "duration_ms": outage["duration_ms"]})
        del history[:-20]
        self.pending.append({"due": self.mono_ms() + DIAGNOSE_AFTER_MS, "outage": outage})

    def _diagnose(self, outage: dict) -> None:
        device = outage["device"] or outage["client"]
        facts = self._facts(device, outage["start_ms"], outage["end_ms"])
        outage["diagnosis"] = calc.diagnose(facts)
        outage["basis"] = sorted(k for k, v in facts.items() if v is True)
        if outage["diagnosis"] == "vpn_shared":
            pattern = calc.regular_pattern(self.outages_by_device.get(device, []), outage["end_ms"])
            warning = self.vpn.pattern(device, outage["agent"], pattern["period_ms"] or 0)
            if warning is not None:
                self.broadcast({"type": "net_event", "event": "vpn_shared", "warning": warning})
        self.last_outage = outage
        self.store.add_outage(outage)
        log.info("coupure réseau de %.1f s (%s, %s) : %s", outage["duration_ms"] / 1000, outage["agent"] or outage["client"],
                 outage["kind"], outage["diagnosis"])
        self.broadcast({"type": "net_event", "event": "outage", "outage": public_outage(outage)})
        if self.cfg.alert_outage_s and outage["duration_ms"] >= self.cfg.alert_outage_s * 1000:
            self._alert_now(codes.ORT_4501,
                            f"Coupure de {round(outage['duration_ms'] / 1000)} s ({outage['agent'] or outage['client']}). "
                            f"Tronçon probable : {DIAGNOSIS_TEXT.get(outage['diagnosis'], outage['diagnosis'])}.",
                            cooldown=True)

    def _alert_now(self, code: str, message: str, cooldown: bool = False) -> None:
        if self.alert is None:
            return
        now = self.mono_ms()
        if cooldown:
            if now - self._last_alert < self.cfg.alert_cooldown_s * 1000:
                return
            self._last_alert = now
        try:
            self.alert(code, message)
        except Exception:                              # une alerte ratée ne gêne jamais la station
            emit_event(codes.ORT_8013, logger=log, trace=True, detail=f"{code} (sonde réseau)")

    def loss_alert(self, probe: "ClientProbe", loss_pct: float) -> None:
        self._alert_now(codes.ORT_4001,
                        f"Perte de {loss_pct:g} % des battements sur 60 s ({probe.agent or probe.client_id}).", cooldown=True)

    # ------------------------------------------------------------------ minuterie

    def tick(self) -> None:
        """Toutes les ~250 ms : battements de chaque connexion, diagnostics arrivés à échéance, entretien."""
        for probe in list(self.connections):
            try:
                probe.tick()
            except Exception:
                emit_event(codes.ORT_4509, logger=log, trace=True, erreur=f"sonde de {probe.client_id}")
        now = self.mono_ms()
        due = [p for p in self.pending if p["due"] <= now]
        self.pending = [p for p in self.pending if p["due"] > now]
        for item in due:
            try:
                self._diagnose(item["outage"])
            except Exception:
                emit_event(codes.ORT_4509, logger=log, trace=True, erreur="diagnostic d'une coupure")
        if self.probes is not None and now >= self._next_probe_log:
            self._next_probe_log = now + WINDOW_MS
            try:
                snap = self.probes.snapshot()
                if snap:
                    self.store.log({"ts": self.wall_ms(), "src": "sonde", "kind": "mesure", **snap})
            except Exception:
                emit_event(codes.ORT_4509, logger=log, trace=True, erreur="journal des sondes de la station")
        if now >= self._next_clear_check:
            self._next_clear_check = now + 1000
            self._console_clear()
        self.store.prune()

    def _console_clear(self) -> None:
        """Demande « Tout effacer » de la console : prise une fois, ignorée si elle a plus de 10 s."""
        path = self.state_dir / CLEAR_REQUEST
        if not path.exists():
            return
        try:
            raw = path.read_bytes()
            path.unlink()
            at = float(json.loads(raw)["at"])
        except (OSError, ValueError, KeyError, TypeError):
            emit_event(codes.ORT_4017, logger=log, demande="effacement de l'historique réseau", motif="illisible")
            return
        if abs(self.wall_ms() / 1000 - at) <= CLEAR_MAX_AGE_S:
            self.clear("TRX Console")
        else:
            emit_event(codes.ORT_4017, logger=log, demande="effacement de l'historique réseau", motif="trop ancienne")

    def export(self) -> tuple[str, bytes]:
        """Export anonyme (zip) des 30 derniers jours : (nom de fichier, contenu)."""
        from .. import __version__
        from ..station_id import read_station_id
        from .export import build_export, export_name
        return export_name(self.wall_ms() / 1000), build_export(
            self.store, 30, version=__version__, station_id=read_station_id(self.state_dir) or "",
            settings=asdict(self.cfg))

    async def run(self, stop: asyncio.Event, every_s: float = 0.25) -> None:
        while not stop.is_set():
            self.tick()
            try:
                await asyncio.wait_for(stop.wait(), every_s)
            except asyncio.TimeoutError:
                pass
        self.store.flush()

    # ------------------------------------------------------------------ seuils, statistiques, effacement

    def start_thresholds(self) -> dict:
        c = self.cfg
        return {"rtt_warn": c.rtt_warn_ms, "rtt_alert": c.rtt_alert_ms, "loss_warn": c.loss_warn_pct,
                "loss_alert": c.loss_alert_pct}

    def thresholds_for(self, net_type: str | None) -> dict:
        return self.store.thresholds().get(net_type or "unknown", self.start_thresholds())

    def stats(self, days: int, device: str) -> dict:
        self.store.flush()                             # l'heure en cours est relue par hours() ; rien de perdu
        return self.store.stats(days, device, self.start_thresholds())

    def set_thresholds(self, params: dict) -> dict:
        values = None if params.get("reset") else params
        return self.store.set_thresholds(params["net_type"], values)

    def clear(self, by: str) -> None:
        self.store.clear()
        self.vpn.clear()
        self.reports.clear()
        self.last_seen.clear()
        self.outages_by_device.clear()
        self.pending.clear()
        self.last_outage = None
        for probe in self.connections:
            probe.last_outage = None
        self.store.log({"ts": self.wall_ms(), "src": "passerelle", "kind": "etat", "event": "effacement", "by": by})
        emit_event(codes.ORT_4506, logger=log, par=by)

    def summary(self) -> dict:
        """Champ `net` du fichier d'état (trx-monitor, TRX Console) : vue opérateur."""
        return {"enabled": True,
                "clients": [p.summary() for p in self.connections],
                "probes": self.probes.snapshot() if self.probes is not None else {},
                "vpn": self.vpn.active(),
                "last_outage": public_outage(self.last_outage) if self.last_outage else None}


DIAGNOSIS_TEXT = {
    "app_station": "application ou machine de la station", "lan": "réseau local ou machine de la station",
    "box_internet": "connexion Internet de la box", "webrtc": "WebRTC ou passerelle",
    "phone_radio": "radio du téléphone", "vpn_shared": "profil VPN probablement partagé par un autre appareil",
    "mobile_or_tunnel": "téléphone, réseau mobile ou tunnel", "unknown": "indéterminé",
}


def public_outage(o: dict) -> dict:
    return {k: o.get(k) for k in ("start_ms", "end_ms", "duration_ms", "diagnosis", "basis", "agent", "net_type", "kind")}


class ClientProbe:
    def __init__(self, hub: NetProbeHub, client_id: str, role: str, device: str, agent: str, source: str, send,
                 journal: bool) -> None:
        self.hub, self.client_id, self.role = hub, client_id, role
        self.device, self.agent, self.source, self.send, self.journal = device, agent, source, send, journal
        cfg = hub.cfg
        self.interval_ms = int(cfg.heartbeat_interval_s * 1000)
        self.detector = calc.OutageDetector(cfg.outage_missed_beats, self.interval_ms)
        self.beats: deque[list] = deque()          # [numéro, envoi (mono), écho (mono) ou None]
        self.by_seq: dict[int, list] = {}
        self.seq = 0
        self.opened_mono, self.opened_wall = hub.mono_ms(), hub.wall_ms()
        self.next_ping = self.opened_mono
        self.next_window = self.opened_mono + WINDOW_MS
        self.last_echo_wall: int | None = None
        self.outage_start_wall: int | None = None
        self.last_outage: dict | None = None
        self.last_outage_mono: int | None = None
        self.last_report: dict | None = None
        self.last_report_mono: int | None = None
        self.window_degraded = False
        self._tx_mark = None
        self._loss_alerted = False

    @property
    def net_type(self) -> str:
        return (self.last_report or {}).get("net_type") or "unknown"

    def _wall_of(self, mono: int) -> int:
        return self.hub.wall_ms() - (self.hub.mono_ms() - mono)

    # ------------------------------------------------------------------ battements

    def tick(self) -> None:
        now = self.hub.mono_ms()
        if now >= self.next_ping:
            self.seq += 1
            beat = [self.seq, now, None]
            self.beats.append(beat)
            self.by_seq[self.seq] = beat
            for event in self.detector.ping(self.seq, now):
                self._outage_event(event)
            self.send({"type": "net_ping", "seq": self.seq, "t": now})
            self.next_ping = now + self.interval_ms
        for event in self.detector.tick(now):
            self._outage_event(event)
        while self.beats and now - self.beats[0][1] > KEEP_BEATS_MS:
            old = self.beats.popleft()
            self.by_seq.pop(old[0], None)
        if now >= self.next_window:
            self.next_window = now + WINDOW_MS
            self._window(now)

    def on_ping(self, params: dict) -> None:
        """Battement du client : écho immédiat ; `w` (horloge murale du client) sert à estimer l'écart des horloges."""
        now = self.hub.mono_ms()
        self.send({"type": "net_pong", "seq": params["seq"], "t": params["t"], "tr": now})
        if "w" in params and self.device:
            rtt = self.stats(10_000)["rtt_mean_ms"] or 0
            offset = int(self.hub.wall_ms() - params["w"] - rtt / 2)
            previous = self.hub.offsets.get(self.device)
            self.hub.offsets[self.device] = offset
            if abs(offset) > SKEW_WARN_MS and (previous is None or abs(previous) <= SKEW_WARN_MS) and self.journal:
                self.hub.store.log({"ts": self.hub.wall_ms(), "src": "passerelle", "kind": "etat", "event": "horloge",
                                    "device": self.device, "offset_ms": offset})

    def on_pong(self, params: dict) -> None:
        beat = self.by_seq.get(params["seq"])
        if beat is None or beat[1] != params["t"] or beat[2] is not None:
            return                                   # écho inconnu, falsifié ou en double : ignoré
        now = self.hub.mono_ms()
        beat[2] = now
        self.last_echo_wall = self.hub.wall_ms()
        for event in self.detector.pong(params["seq"], now):
            self._outage_event(event)

    def _outage_event(self, event: dict) -> None:
        if event["type"] == "start":
            self.outage_start_wall = self._wall_of(event["start_ms"])
            return
        start = self.outage_start_wall if self.outage_start_wall is not None else self._wall_of(event["start_ms"])
        self.outage_start_wall = None
        self.last_outage_mono = self.hub.mono_ms()
        outage = {"start_ms": start, "end_ms": self._wall_of(event["end_ms"]), "device": self.device,
                  "agent": self.agent, "client": self.client_id, "net_type": self.net_type, "kind": "in_session",
                  "seen_by": "station"}
        self.last_outage = outage
        if self.journal:
            self.hub._outage_found(outage)

    # ------------------------------------------------------------------ résumés

    def on_report(self, report: dict) -> None:
        self.last_report, self.last_report_mono = report, self.hub.mono_ms()
        if report["degraded"] or (report["concealed_pct"] or 0) > 1:
            self.window_degraded = True
        self.hub.add_reports(self, [report])

    def on_backlog(self, reports: list[dict]) -> None:
        self.hub.add_reports(self, reports)

    def stats(self, window_ms: int) -> dict:
        beats = [calc.Beat(b[0], b[1], b[2]) for b in self.beats]
        return calc.window_stats(beats, self.hub.mono_ms(), window_ms)

    def _window(self, now: int) -> None:
        stats = self.stats(WINDOW_MS)
        degraded = self.window_degraded or self._tx_trouble()
        self.window_degraded = False
        s60 = self.stats(60_000)
        th = self.hub.thresholds_for(self.net_type)
        in_outage = self.detector.start_ms is not None or (
            self.last_outage_mono is not None and now - self.last_outage_mono < 60_000)   # pertes dues à la coupure : déjà alertée
        if s60["loss_pct"] is not None and s60["loss_pct"] >= th["loss_alert"] and s60["expected"] >= 30:
            if not self._loss_alerted and self.journal and not in_outage:
                self._loss_alerted = True
                self.hub.loss_alert(self, s60["loss_pct"])
        elif s60["loss_pct"] is not None and s60["loss_pct"] < th["loss_warn"]:
            self._loss_alerted = False
        if not self.journal or not stats["expected"]:
            return
        wall = self.hub.wall_ms()
        self.hub.store.log({"ts": wall, "src": "passerelle", "kind": "mesure", "device": self.device,
                            "client": self.client_id, "net_type": self.net_type, "degraded": degraded,
                            **{k: v for k, v in stats.items() if k != "received"}})
        self.hub.store.add_window(wall, self.device or self.client_id, self.agent, self.net_type, stats, degraded)

    def _tx_trouble(self) -> bool:
        """Son d'émission de CE client en retard ou jeté par la station pendant la fenêtre."""
        if self.hub.tx_counter is None:
            return False
        try:
            owner, count = self.hub.tx_counter()
        except Exception:
            return False
        mark, self._tx_mark = self._tx_mark, (owner, count)
        return mark is not None and owner == self.client_id and mark[0] == self.client_id and count > mark[1]

    # ------------------------------------------------------------------ état

    def state(self) -> dict:
        """`state.net` de CETTE connexion (indicateur et détail)."""
        now = self.hub.mono_ms()
        s10, s60 = self.stats(10_000), self.stats(60_000)
        th = self.hub.thresholds_for(self.net_type)
        report = self.last_report if self.last_report_mono is not None and now - self.last_report_mono < REPORT_FRESH_MS else None
        cfg = self.hub.cfg
        level = calc.level(now - self.opened_mono, s60["loss_pct"], s60["rtt_p95_ms"], self.detector.start_ms is not None,
                           None if self.last_outage_mono is None else now - self.last_outage_mono,
                           report["rsrp_dbm"] if report else None, report["sinr_db"] if report else None,
                           {**th, "rsrp_warn": cfg.rsrp_warn_dbm, "rsrp_alert": cfg.rsrp_alert_dbm,
                            "sinr_warn": cfg.sinr_warn_db, "sinr_alert": cfg.sinr_alert_db})
        last = self.last_outage
        out = {"level": level, "loss_pct": s60["loss_pct"], "loss_pct_10": s10["loss_pct"], "rtt_ms": s60["rtt_p95_ms"],
               "rtt_mean_ms": s60["rtt_mean_ms"], "jitter_ms": s60["jitter_ms"], "late": s60["late"],
               "out_of_order": s60["out_of_order"], "outage": self.detector.start_ms is not None,
               "outage_s": None if self.detector.start_ms is None else round((now - self.detector.start_ms) / 1000),
               "last_outage": None if last is None else {
                   "ago_s": round((self.hub.wall_ms() - last["end_ms"]) / 1000),
                   "duration_s": round((last["end_ms"] - last["start_ms"]) / 1000),
                   "diagnosis": last.get("diagnosis")},
               "net_type": self.net_type, "thresholds": th}
        if self.journal:
            out["vpn"] = self.hub.vpn.active()
            out["probes"] = self.hub.probes.snapshot() if self.hub.probes is not None else {}
        return out

    def summary(self) -> dict:
        s60 = self.stats(60_000)
        report = self.last_report or {}
        return {"id": self.client_id, "role": self.role, "agent": self.agent, "net_type": self.net_type,
                "level": self.state()["level"], "loss_pct": s60["loss_pct"], "rtt_ms": s60["rtt_p95_ms"],
                "outage": self.detector.start_ms is not None,
                # radio du téléphone (application, lot 6) : dernier résumé reçu ; None pour la page
                "rsrp_dbm": report.get("rsrp_dbm"), "sinr_db": report.get("sinr_db"), "signal_level": report.get("signal_level")}
