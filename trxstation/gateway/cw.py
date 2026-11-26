# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Manipulation CW, mode A (laboratoire, branche exp/cw ; docs/exp-cw/cahier-des-charges.md § 3, § 4, § 5).

SÉCURITÉ (exception du cahier § 3, valable dans la branche seulement, essais sur charge fictive) :
- « Armer CW » = prise d'émission NORMALE du client (`PttController.key_without_audio` : mêmes refus que toggle,
  verrou mono-client, battements 500 ms / 2 s, TOT, opérateur sur place, bandes) ; la porte du MICRO reste fermée ;
- avant la prise : mode du poste = `[cw] data_mode` (jamais changé par la station), porteuse (fréquence d'émission
  + tonalité en USB, - en LSB) ET fréquence affichée dans les bandes ; après la prise : ce que le PttController a
  relu doit être ce qui a été vérifié, sinon coupure ;
- seule la TONALITÉ recréée ici part vers le poste, au rythme réel, jamais plus de LEAD_S d'avance (passerelle
  gelée = plus rien d'écrit, le tampon de la carte se vide en moins de 0,2 s) ;
- bail du rejeu dépassé, appui trop long, désarmement, inactivité : fermeture adoucie puis « T 0 » ;
- STOP, TOT, battement perdu, déconnexion, toute coupure du PttController : tampon jeté (tonalité coupée net), le
  PttController envoie « T 0 » ; le module se désarme sans jamais reprendre l'émission ;
- ce module ne peut QUE prendre une émission normale ou couper : aucun autre chemin vers le PTT.
V1 (`ptt_variant = "hold"`, défaut) : PTT tenu pendant tout l'armement.
V2 (`"hang"`, cahier § 5.4) : après `hang_ms` de silence, PTT relâché (« T 0 », motif `cw_hang`), la CW reste armée et
le rendu n'écrit plus RIEN vers le poste ; au front de fermeture suivant, émission reprise par le MÊME chemin que
l'armement (mode, porteuse, bandes revérifiés, `key_without_audio` avec tous ses refus, anti-rebond `cooldown` attendu
au plus RETAKE_MAX_S) ; refus = désarmement (`cw_retake_refused`). Toute coupure venue d'ailleurs pendant la pause
(STOP, autre client, déconnexion) désarme pour de bon : jamais de reprise après elle.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from ..cw.player import CwParams, CwPlayer
from ..cw.protocol import parse_packet
from ..cw.tone import to_pcm16
from .audio.pcm import FRAME_S, FRAME_SAMPLES
from .safety import Refused

log = logging.getLogger(__name__)

LEAD_S = 0.06                    # avance d'écriture sur la lecture de la carte (comme les bips de fin)
STALL_S = 0.25                   # rendu en retard de plus que cela : passerelle gênée, CW désarmée
STATE_EVERY_S = 0.2              # cw_state envoyé au propriétaire pendant l'armement
MAX_PACKETS_PER_S = 120          # canal cw : au-delà, paquets ignorés (le client en envoie 50)
RETAKE_MAX_S = 3.0               # V2 : reprise de l'émission refusée pour anti-rebond attendue au plus ce temps
STATS_MAX_BYTES = 2_000_000      # mesures du POC (§ 12) : fichier tourné au-delà


def carrier_sign(mode: str) -> int:
    """+1 : porteuse au-dessus de la fréquence affichée (USB et modes données USB) ; -1 en LSB."""
    return -1 if "LSB" in mode.upper() else 1


class CwKeyer:
    def __init__(self, ctrl, sink, cfg, *, state_dir: str | Path | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep=asyncio.sleep) -> None:
        self.ctrl, self.sink, self.cfg = ctrl, sink, cfg
        self.clock, self.sleep = clock, sleep
        self.stats_path = Path(state_dir) / "cw" / "sequences.jsonl" if state_dir else None
        self.owner: str | None = None
        self.player: CwPlayer | None = None
        self.info: dict = {}
        self._send: Callable[[dict], None] = lambda message: None
        self._epoch = -1
        self._t0 = 0.0
        self._task: asyncio.Task | None = None
        self._closing = ""                       # motif d'une fermeture adoucie en cours (puis « T 0 »)
        self._last_activity = 0.0
        self._arrivals: deque[float] = deque()
        self.ignored_packets = 0
        self._phase = "tx"                       # "tx" (PTT tenu) ; V2 : "hang" (PTT relâché), "retake" (reprise en cours)
        self._retake_task: asyncio.Task | None = None
        self._release_task: asyncio.Task | None = None
        self.retakes = 0
        ctrl.add_listener(self._on_ptt)

    # ------------------------------------------------------------------ état
    @property
    def enabled(self) -> bool:
        return bool(self.cfg.cw.enabled)

    @property
    def armed(self) -> bool:
        return self.owner is not None

    def status(self) -> dict:
        p = self.player
        if not self.armed or p is None:
            return {"state": "idle"}
        state = "hang" if self._phase != "tx" else "playing" if p.active else "armed"
        return {"state": state, "seq": p.seq, "buffer_ms": round(p.buffer_ms),
                "late": p.late, "lease_cuts": p.lease_cuts, "carrier_hz": self.info.get("carrier_hz")}

    def _state_message(self, state: str | None = None, reason: str = "") -> dict:
        msg = {"type": "cw_state", **self.status()}
        if state is not None:
            msg["state"] = state
        if reason:
            msg["reason"] = reason
        return msg

    # ------------------------------------------------------------------ armement
    async def arm(self, client_id: str, params: dict, send: Callable[[dict], None]) -> dict:
        """Prise d'émission normale de `client_id`, puis rendu de la tonalité. Refused si impossible (rien n'émet)."""
        c = self.cfg.cw
        if not c.enabled:
            raise Refused("cw_unavailable")
        if params.get("mode", "A") not in c.modes:
            raise Refused("cw_unavailable", f"mode {params.get('mode')} non proposé par la station")
        if self.armed:
            raise Refused("cw_busy", f"manipulation CW déjà armée ({self.owner})")
        if self.ctrl.snapshot().state != "RX":
            raise Refused("tx_active", "armement possible seulement en réception")
        tone = float(params.get("tone_hz", c.tone_hz))
        delay = float(params.get("delay_ms", c.delay_ms))
        if not c.delay_min_ms <= delay <= c.delay_max_ms:
            raise Refused("invalid", f"delay_ms entre {c.delay_min_ms:g} et {c.delay_max_ms:g}")
        carrier = await self._take(client_id, tone, align=bool(params.get("align")))
        self.player = CwPlayer(CwParams(tone_hz=tone, edge_ms=c.edge_ms, delay_ms=delay, adaptive=c.adaptive,
                                        delay_min_ms=c.delay_min_ms, delay_max_ms=c.delay_max_ms,
                                        lease_grace_ms=c.lease_grace_ms, max_keydown_ms=c.max_keydown_ms,
                                        seq_gap_ms=c.seq_gap_ms))
        self.owner, self._send, self._epoch = client_id, send, self.ctrl.epoch
        self._closing = ""
        self._phase, self.retakes = "tx", 0
        self._t0 = self._last_activity = self.clock()
        self.info = {"carrier_hz": carrier, "tone_hz": tone, "delay_ms": delay, "mode": c.data_mode,
                     "wpm": params.get("wpm"), "interface": params.get("interface", ""), "net": params.get("net", "")}
        self._task = asyncio.get_running_loop().create_task(self._feed())
        log.info("CW armée par %s : porteuse %.4f MHz, rejeu %.0f ms", client_id, carrier / 1e6, delay)
        send(self._state_message("armed"))
        return dict(self.info)

    async def _take(self, client_id: str, tone: float, *, align: bool = False) -> int:
        """Vérifications (mode, porteuse et fréquence affichée dans les bandes) puis prise d'émission NORMALE ; même
        chemin à l'armement et à chaque reprise V2. Rend la porteuse ; Refused si impossible (rien n'émet)."""
        c = self.cfg.cw
        client = self.ctrl.link.client
        try:
            mode, _ = await client.get_mode()
        except Exception as exc:                 # noqa: BLE001 : illisible = pas d'émission
            raise Refused("cat_error", f"mode illisible : {exc}") from exc
        if mode != c.data_mode:
            raise Refused("cw_mode", f"poste en {mode} : {c.data_mode} attendu (la station ne change jamais le mode)")
        sign = carrier_sign(mode)
        if align:                                # caler la porteuse : QSY AVANT la prise seulement (refusé hors RX)
            freq, _, _ = await self.ctrl.read_transmit_plan()
            await self.ctrl.set_frequency(int(round(freq - sign * tone)))
        freq, tx, plan = await self.ctrl.read_transmit_plan()
        carrier = int(round(tx + sign * tone))
        if self.cfg.safety.enforce_bands:
            if not self.cfg.bands:
                raise Refused("tx_disabled", "aucune bande autorisée dans station.toml")
            for hz, what in ((carrier, "porteuse CW"), (tx, "fréquence affichée")):
                if not self.cfg.tx_allowed(hz):
                    raise Refused("out_of_band", f"{hz / 1e6:.4f} MHz ({what})")
        await self.ctrl.key_without_audio(client_id)      # mêmes refus que toggle ; porte du micro fermée
        got_freq, got_mode, got_plan = self.ctrl.tx_reading
        if got_freq != freq or got_plan != plan or (got_mode is not None and got_mode != c.data_mode):
            await self.ctrl.force_rx("cw_carrier_changed", by=client_id)
            raise Refused("cw_carrier_changed", "fréquence ou mode changés pendant l'armement")
        return carrier

    async def disarm(self, client_id: str, reason: str = "cw_disarm") -> None:
        """Désarmement demandé par le propriétaire (ou toggle) : fermeture adoucie puis « T 0 »."""
        if self.armed and client_id == self.owner:
            self._begin_close(reason)
            task = self._task
            if task is not None:
                await asyncio.wait({task}, timeout=1.0)
            if self.armed:                       # rendu bloqué : on coupe quand même
                await self._cut(reason)

    def forget(self, client_id: str) -> None:
        """Connexion fermée : la coupure vient du PttController (déconnexion du propriétaire)."""
        if client_id == self.owner:
            self._stop_now("client_disconnected")

    # ------------------------------------------------------------------ canal cw
    def receive(self, client_id: str, raw: str | bytes) -> None:
        """Paquet du canal `cw` ; ignoré s'il ne vient pas du propriétaire armé, mal formé ou trop fréquent."""
        if not self.armed or client_id != self.owner or self.player is None or self._closing:
            self.ignored_packets += 1
            return
        now = self.clock()
        self._arrivals.append(now)
        while self._arrivals and now - self._arrivals[0] > 1.0:
            self._arrivals.popleft()
        if len(self._arrivals) > MAX_PACKETS_PER_S or len(raw) > 4096:
            self.ignored_packets += 1
            return
        try:
            pkt = parse_packet(json.loads(raw))
        except (ValueError, UnicodeDecodeError):
            self.ignored_packets += 1
            return
        if pkt.edges:
            self._last_activity = now
        self.player.receive(pkt, now - self._t0)

    # ------------------------------------------------------------------ rendu
    def _still_ours(self) -> bool:
        snap = self.ctrl.snapshot()
        return snap.state == "TX" and snap.owner == self.owner and self.ctrl.epoch == self._epoch

    async def _feed(self) -> None:
        player = self.player
        assert player is not None
        frame = 0
        last_state = self.clock()
        try:
            while self.armed and player is self.player:
                due = self._t0 + frame * FRAME_S - LEAD_S
                wait = due - self.clock()
                if wait > 0:
                    await self.sleep(wait)
                if not self.armed or player is not self.player:
                    return
                if self._phase == "tx":
                    if not self._still_ours():
                        self._stop_now(self.ctrl.last_cut_request or "cut")
                        return
                elif self.ctrl.epoch > self._epoch:
                    # V2, PTT relâché : coupure venue d'ailleurs (STOP, autre client...) = désarmée, jamais reprise
                    self._stop_now(self.ctrl.last_cut_request or "cut")
                    return
                if self.clock() - due > STALL_S:
                    self._begin_close("cw_stalled")
                    await self._cut("cw_stalled")
                    return
                pcm = to_pcm16(player.render(FRAME_SAMPLES))
                if self._phase == "tx":
                    self.sink.write(pcm)                 # PTT relâché (V2) : rien n'est écrit vers le poste
                frame += 1
                for event in player.drain_events():
                    self._event(event)
                if self.cfg.cw.ptt_variant == "hang" and not self._closing:
                    if self._phase == "tx" and player.silent and player.idle_ms >= self.cfg.cw.hang_ms:
                        self._begin_hang()
                    elif self._phase == "hang" and player.wants_key and self._retake_task is None:
                        self._retake_task = asyncio.get_running_loop().create_task(self._retake())
                now = self.clock()
                if not self._closing and not player.active and now - self._last_activity > self.cfg.cw.idle_disarm_s:
                    self._begin_close("cw_idle")
                if self._closing and player.silent:
                    # la carte joue ce qui est écrit (avance + réserve) avant « T 0 »
                    await self.sleep(LEAD_S + FRAME_S + getattr(self.sink, "PREFILL_S", 0.0))
                    await self._cut(self._closing)
                    return
                if now - last_state >= STATE_EVERY_S:
                    last_state = now
                    self._send(self._state_message())
        except asyncio.CancelledError:
            raise
        except Exception:                        # noqa: BLE001 : jamais une émission sans rendu
            log.info("CW : erreur du rendu, désarmement", exc_info=True)
            self._stop_now("cw_failed")
            await self.ctrl.force_rx("cw_failed", by="manipulation CW")

    def _event(self, event: dict) -> None:
        if event["type"] == "cw_fault":
            self._send({"type": "cw_fault", "seq": event["seq"], "reason": event["reason"]})
            if event["reason"] in ("lease_expired", "keydown_too_long", "seq_overlap"):
                self._begin_close("cw_" + event["reason"])
        elif event["type"] == "seq_end":
            p = self.player
            stats = {"type": "cw_stats", "seq": event["seq"], "jitter_p95_ms": round(event["jitter_p95_ms"], 1),
                     "late": event["late"], "lease_cuts": p.lease_cuts if p else 0,
                     "max_timing_err_ms": round(p.max_timing_err_ms if p else 0.0, 3),
                     "delay_ms": event["delay_ms"], "end": event["reason"]}
            self._send(stats)
            self._record(event)

    def _record(self, event: dict) -> None:
        """Mesures du POC (§ 12) : une ligne par séquence ; aucun son, aucun texte manipulé."""
        if self.stats_path is None:
            return
        line = {"at": round(time.time(), 1), **{k: self.info.get(k) for k in ("mode", "interface", "wpm", "net")},
                **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in event.items() if k != "type"}}
        try:
            self.stats_path.parent.mkdir(parents=True, exist_ok=True)
            if self.stats_path.exists() and self.stats_path.stat().st_size > STATS_MAX_BYTES:
                self.stats_path.replace(self.stats_path.with_suffix(".jsonl.1"))
            with self.stats_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            log.info("CW : mesures non enregistrées (%s)", self.stats_path)

    # ------------------------------------------------------------------ fins
    def _begin_close(self, reason: str) -> None:
        if not self._closing and self.player is not None:
            self._closing = reason
            self.player.stop(reason)
            for event in self.player.drain_events():
                self._event(event)

    async def _cut(self, reason: str) -> None:
        owner, phase = self.owner, self._phase
        self._stop_now(reason)
        if phase == "tx":
            await self.ctrl.force_rx(reason, by=owner or "manipulation CW")
        elif self._release_task is not None:
            await asyncio.wait({self._release_task}, timeout=2.0)   # relâché V2 encore en cours : il se termine

    # ------------------------------------------------------------------ V2 (« hang »)
    def _begin_hang(self) -> None:
        """Silence de `hang_ms` : PTT relâché par la passerelle, CW toujours armée, plus rien n'est écrit."""
        assert self.player is not None
        self._phase = "hang"
        self.player.hold()
        self._epoch = self.ctrl.epoch + 1        # force_rx l'augmente d'exactement 1 : au-delà, coupure venue d'ailleurs
        self._release_task = asyncio.get_running_loop().create_task(
            self.ctrl.force_rx("cw_hang", by=self.owner or "manipulation CW"))
        self._send(self._state_message())

    async def _retake(self) -> None:
        """Front de fermeture pendant la pause V2 : émission reprise par le chemin de l'armement, sinon désarmée."""
        owner, player = self.owner, self.player
        try:
            if self._release_task is not None:
                await asyncio.wait({self._release_task}, timeout=2.0)
            deadline = self.clock() + RETAKE_MAX_S
            self._phase = "retake"
            while True:
                if self.owner != owner or self.player is not player or self._closing or self.ctrl.epoch > self._epoch:
                    return                       # désarmée ou coupée entre-temps : la boucle du rendu a conclu
                try:
                    carrier = await self._take(owner, float(self.info.get("tone_hz", self.cfg.cw.tone_hz)))
                    break
                except Refused as exc:
                    if exc.reason == "cooldown" and self.clock() < deadline:
                        await self.sleep(0.05)   # anti-rebond du PttController (jamais baissé pour la CW)
                        continue
                    log.info("CW : émission non reprise après la pause (%s)", exc)
                    self._send({"type": "cw_fault", "seq": player.seq if player else None, "reason": "retake_refused",
                                "detail": exc.reason})
                    self._stop_now("cw_retake_refused")
                    return
            if self.owner != owner or self.player is not player or self.ctrl.epoch > self._epoch:
                await self.ctrl.force_rx("cw_disarm", by=owner)       # désarmée pendant la prise : on recoupe
                return
            self.retakes += 1
            self.info["carrier_hz"] = carrier
            self._phase = "tx"
            player.resume()
            self._send(self._state_message())
        finally:
            if self.player is player:
                self._retake_task = None

    def _stop_now(self, reason: str) -> None:
        """Tonalité coupée net (tampon jeté), module désarmé ; n'émet JAMAIS rien."""
        if not self.armed:
            return
        try:
            self.sink.flush()
        finally:
            send, owner = self._send, self.owner
            self.owner, self.player = None, None
            self._phase = "tx"
            for task in (self._task, self._retake_task):
                if task is not None and task is not asyncio.current_task() and not task.done():
                    task.cancel()
            self._task = self._retake_task = None
            log.info("CW désarmée (%s, %s)", owner, reason)
            send({"type": "cw_state", "state": "idle", "reason": reason})

    def _on_ptt(self, snap) -> None:
        """Écouteur synchrone du PttController : toute coupure (STOP, TOT, battement...) arrête le rendu AVANT « T 0 ».
        Pendant la pause V2 (PTT relâché ou reprise en cours), la boucle du rendu juge sur `epoch`."""
        if self.armed and self._phase == "tx" and (snap.state != "TX" or snap.owner != self.owner or self.ctrl.epoch != self._epoch):
            self._stop_now(self.ctrl.last_cut_request or snap.event or "cut")
