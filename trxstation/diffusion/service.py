# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module « diffusion » : processus séparé lancé par le superviseur (`[modules] run = ["diffusion"]`).

Diffusion en direct du son du TRX vers un serveur Icecast (docs/diffusion-cahier-des-charges.md, lot D1b ;
protocole : docs/protocole-diffusion.md). AUCUN droit sur le poste : il ne lit que le son (paquets UDP de la
passerelle, `audio.py`) et l'état publié (événements `freq_mode` et `ptt`, pour les métadonnées) ; il ne peut ni
changer de fréquence ni émettre. Une panne ici n'a aucun effet sur la réception, l'émission ou les sécurités.

- ordres de la PASSERELLE (bus, `call`) : `status`, `start`, `stop` ; la passerelle demande `status` toutes les 2 s
  et n'envoie le son que pendant une diffusion active ; elle arrête la diffusion si la station est surchargée ;
- fermée par défaut, JAMAIS reprise seule : ni au démarrage du module, ni quand la passerelle revient (relance par
  le superviseur, mode sûr) : la diffusion ne survit pas à ce qui l'a autorisée (cahier § 3) ;
- secrets : `diffusion.key` (0600, keyfile.py) ; état : `state_dir/diffusion/status.json` (0644, sans secret) ;
- journal : `state_dir/diffusion/diffusion.log`, 5 fichiers de 1 Mo.

À la main (essai) :  python -m trxstation.diffusion.service --config station.toml
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .. import config as cfgmod
from ..errors import codes
from ..errors.emit import emit_event
from ..online import LinkHealth, read_json
from . import audio as au, keyfile, protocol as p
from .encoder import Encoder
from .meta import MetaClient
from .source import SourceRefused, client_ssl_context, open_source

log = logging.getLogger("trx.diffusion")

FRAME_S = au.BLOCK / 48000            # 20 ms
AUDIO_QUEUE = 50                      # 1 s au plus en attente
NO_AUDIO_ALERT_S = 5.0                # plus de son de la passerelle : alerte (silence envoyé)
NO_AUDIO_SILENCE_S = 2.0              # plus de son de la passerelle : raison « pas_de_son » dite aux auditeurs
S_KEEP_S = 6.0                        # S-mètre gardé (couvre des envois perdus) ; envoyé : S_SEND_S dernières secondes
S_SEND_S = 4.0
FATAL_STATUSES = (401, 404)           # mot de passe ou station refusés : pas de nouvel essai
# openRemoteTRX Console (menu 5.6) : demande déposée dans state_dir, réponse dans state_dir/diffusion (même mécanisme que la
# présence et le monitoring). La réponse peut porter le mot de passe des AUDITEURS (« reveal ») : effacée vite.
CONSOLE_REQUEST = "diffusion-request.json"
CONSOLE_REPLY = "console-reply.json"
CONSOLE_MAX_AGE_S = 120.0
CONSOLE_REPLY_KEEP_S = 15.0
TICK_S = 1.0


class ActionRefused(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def default_config_path() -> Path:
    from ..paths import default_config_path as d     # même règle que les autres outils
    return d()


def fmt_duration(seconds: float) -> str:
    m = int(max(seconds, 0) // 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, service: "DiffusionService") -> None:
        self.service = service

    def datagram_received(self, data: bytes, addr) -> None:
        if addr[0] == "127.0.0.1":
            self.service.on_packet(data)


class DiffusionService:
    def __init__(self, cfg: cfgmod.Config, config_path: Path, bus_client=None, *,
                 clock: Callable[[], float] = time.time, ssl_context=None, api_base: str | None = None) -> None:
        self.cfg, self.config_path, self.bus, self.clock = cfg, Path(config_path), bus_client, clock
        self.df = cfg.diffusion
        self.folder = Path(cfg.supervisor.state_dir) / "diffusion"
        self.key_path = cfgmod.diffusion_key_path(cfg, config_path)
        self.ssl_context = ssl_context if ssl_context is not None else (client_ssl_context() if self.df.tls else None)
        scheme = "https" if self.df.tls else "http"
        port = "" if (self.df.tls and self.df.api_port == 443) else f":{self.df.api_port}"
        self.api_base = api_base or f"{scheme}://{self.df.server}{port}"
        self.token = b""
        self.audio: asyncio.Queue[bytes] = asyncio.Queue(maxsize=AUDIO_QUEUE)
        self.values: dict[str, Any] = {}       # métadonnées connues (pseudo… au lancement, fréquence par le bus)
        self.problem = ""
        self._task: asyncio.Task | None = None
        self._session: dict[str, Any] | None = None   # diffusion en cours
        self.last_stop: dict[str, Any] | None = None
        # services en ligne (étape 351) : liaison au serveur et dernier lancement, gardés d'un démarrage à l'autre
        self.server_health = LinkHealth("ORT-6104")
        previous = read_json(self.folder / "status.json") or {}
        self.last_start: dict[str, Any] | None = previous.get("last_start") if isinstance(previous.get("last_start"), dict) else None
        if self.last_stop is None and isinstance(previous.get("last_stop"), dict):
            self.last_stop = previous["last_stop"]
        self._bus_seen = False
        self._reply_at: float | None = None
        self._meta_dirty = False
        self._last_audio = 0.0
        self._s_hist: list[tuple[float, float, bool | None]] = []   # (instant monotone, dB / S9, squelch)

    # ------------------------------------------------------------- état
    @property
    def active(self) -> bool:
        return self._session is not None

    def status(self) -> dict[str, Any]:
        s = self._session
        out: dict[str, Any] = {"enabled": bool(self.df.enabled), "active": s is not None, "updated": int(self.clock()),
                               "codec": self.df.codec, "problem": self.problem or None, "last_stop": self.last_stop,
                               "last_start": self.last_start, "server": self.server_health.to_dict()}
        if self.df.server and self.df.station:
            out["listen_page"] = p.listen_page(self.df.server, self.df.station)
        out["accepted"] = self.accepted()
        out["outside_bands"] = bool(self.df.outside_bands)        # appliqué par la passerelle (silence hors bandes)
        if s is not None:
            out.update({k: s[k] for k in ("access", "voice", "started", "ends", "phase", "listeners", "operator",
                                          "meta_choice")})
            out["silence"] = s.get("silence")                   # raison d'un silence voulu, dite aux auditeurs
            out["remaining_s"] = None if s["ends"] is None else max(0, int(s["ends"] - self.clock()))
            out["stream_url"] = p.stream_url(self.df.server, self.df.station, s["access"])
            if s["access"] == "prive":
                out["listener_user"] = s["listener_user"]          # le mot de passe : jamais ici
        return out

    def write_status(self) -> None:
        from ..presence.store import write_json          # écriture atomique (0644 : rien de secret)
        try:
            write_json(self.folder / "status.json", self.status(), private=False)
        except OSError as exc:
            log.info("état %s non écrit : %s", self.folder / "status.json", exc)

    # ------------------------------------------------------------- bus
    def setup(self) -> None:
        if self.bus is not None:
            self.bus.on_call = self.on_call
            self.bus.on_event = self.on_event
            self.bus.on_connect = self.on_connect
            self.bus.on_gap = lambda: asyncio.ensure_future(self.load_state())
            self.bus.metrics = lambda: {"active": self.active}

    async def on_connect(self) -> None:
        """La passerelle (re)vient : si c'est un RETOUR (relance, mode sûr), la diffusion en cours s'arrête."""
        if self._bus_seen and self.active:
            await self.stop("gateway_restart")
        self._bus_seen = True
        asyncio.ensure_future(self.load_state())      # tâche à part : la lecture du bus ne doit pas attendre

    async def load_state(self) -> None:
        """Fréquence, mode et émission ACTUELS (les événements ne viennent qu'au changement : sans cette lecture, un
        module relancé ne connaissait pas la fréquence tant que le poste n'avait pas bougé)."""
        try:
            st = await self.bus.get_state()
        except Exception:                              # bus coupé : on aura les prochains événements
            return
        if isinstance(st, dict):
            await self.on_event("freq_mode", {"freq": st.get("freq"), "mode": st.get("mode")})
            if isinstance(st.get("ptt"), bool):
                await self.on_event("ptt", {"active": st["ptt"]})

    async def on_event(self, name: str, data: dict) -> None:
        if name == "freq_mode" and isinstance(data, dict):
            freq = data.get("freq")
            if isinstance(freq, int) and not isinstance(freq, bool) and freq > 0:
                from ..cluster.bandplan import band_of         # table simple des bandes (aucun accès au poste)
                self.values["frequence_hz"] = freq
                self.values["bande"] = band_of(freq / 1000)
            mode = data.get("mode")
            self.values["mode"] = mode[:12] if isinstance(mode, str) and mode else None
            self._meta_dirty = True
        elif name == "ptt" and isinstance(data, dict):
            self.values["tx"] = bool(data.get("active"))
            self._meta_dirty = True

    def on_info(self, info: dict, now: float | None = None) -> None:
        """Infos du poste de la passerelle (diffusion/rigview.snapshot) ; chaque valeur revérifiée, le reste ignoré."""
        from .rigview import s_text
        now = time.monotonic() if now is None else now
        self._rig_off = info.get("off") is True            # poste éteint (allumage à distance) : raison du silence
        w = info.get("w")
        self.values["filtre"] = w if isinstance(w, str) and 0 < len(w) <= 8 else None
        v = info.get("v")
        try:
            self.values["voyants"] = p.check_meta({"voyants": v})["voyants"] if isinstance(v, list) else None
        except p.DiffusionRefused:
            self.values["voyants"] = None
        s, q = info.get("s"), info.get("q")
        if isinstance(s, (int, float)) and not isinstance(s, bool) and -80 <= s <= 100:
            self._s_hist.append((now, round(float(s), 1), q if isinstance(q, bool) else None))
            self.values["s_metre"] = s_text(s)
        self._s_hist = [h for h in self._s_hist if now - h[0] <= S_KEEP_S]

    def s_points(self, now: float | None = None) -> list[list] | None:
        """S-mètre des S_SEND_S dernières secondes, le plus récent d'abord : [[âge ms, dB, squelch], …]."""
        now = time.monotonic() if now is None else now
        pts = [[int(round(1000 * (now - t))), db, q] for t, db, q in reversed(self._s_hist) if now - t <= S_SEND_S]
        return pts[:p.MAX_S_POINTS] or None

    def silence_reason(self) -> str | None:
        """Pourquoi les auditeurs n'entendent rien (protocol.SILENCE_REASONS), None si le son passe. Même règle que la
        passerelle (diffusion_out : silence hors [[bands]] sauf outside_bands, voix de l'opérateur non cochée) ;
        fréquence encore inconnue : rien d'affirmé."""
        s = self._session
        if s is None:
            return None
        if getattr(self, "_rig_off", False):
            return "poste_eteint"                        # poste éteint (fonction « power ») ; serveur à jour (2026-11-19)
        if s.get("phase") == "en_direct" and time.monotonic() - self._last_audio > NO_AUDIO_SILENCE_S:
            return "pas_de_son"
        if self.values.get("tx") and not s.get("voice"):
            return "emission"
        freq = self.values.get("frequence_hz")
        if not self.df.outside_bands and isinstance(freq, int) and not self.cfg.tx_allowed(freq):
            return "hors_bandes"
        return None

    async def on_call(self, data: dict):
        from ..modules.client import CallRefused          # client du bus : seulement pour traduire le refus
        args = data.get("args") or {}
        if not isinstance(args, dict):
            raise CallRefused("malformed", "arguments mal formés")
        try:
            return await self.act(str(data.get("action")), args)
        except ActionRefused as exc:
            raise CallRefused(exc.reason, str(exc)) from None

    async def act(self, action: str, args: dict) -> dict:
        if action == "status":
            return self.status()
        if action == "start":
            return await self.start(args)
        if action == "listener":
            return self.set_listener(args)
        if action == "reveal":
            return self.reveal()
        if action == "stop":
            cause = args.get("cause", "operator")
            if cause not in ("operator", "overload", "disabled", "station_stop"):
                cause = "operator"
            if self.active:
                await self.stop(cause, by=str(args.get("operator") or "")[:32])
            return self.status()
        raise ActionRefused("unknown_action", f"action inconnue : {action}")

    # ------------------------------------------------------------- avertissement et auditeurs
    def accepted(self) -> bool:
        """L'avertissement du cahier § 1.1 (responsabilité de l'opérateur) a-t-il été confirmé une fois ?"""
        return (self.folder / "accepted.json").exists()

    def _accept(self, operator: str) -> None:
        from ..presence.store import write_json
        write_json(self.folder / "accepted.json", {"by": operator, "at": int(self.clock())}, private=False)

    def _secrets(self) -> keyfile.Secrets:
        try:
            return keyfile.read(self.key_path)
        except (keyfile.KeyFileError, OSError) as exc:
            emit_event(codes.ORT_6105, logger=log, fichier=str(self.key_path), detail=str(exc)[:200])
            raise ActionRefused("no_secrets", f"secrets du serveur absents ou illisibles ({exc}) : openRemoteTRX Console, "
                                              "menu 5.6, choix 6") from None

    def set_listener(self, args: dict) -> dict:
        """Identifiant et mot de passe des auditeurs du montage privé : choisis par l'opérateur ou générés ; FIXES
        ensuite (cahier § 1.9). Pris par le serveur au prochain lancement privé (ou tout de suite si une diffusion
        privée est en cours). Seule réponse qui contient le mot de passe, avec `reveal`."""
        sec = self._secrets()
        user = args.get("user", sec.listener_user)
        password = p.new_listener_password() if args.get("generate") is True else args.get("password")
        if not isinstance(user, str) or not p.LISTENER_USER.match(user):
            raise ActionRefused("malformed", "identifiant des auditeurs : 1 à 32 caractères A-Z a-z 0-9 . _ -")
        if not isinstance(password, str) or not p.LISTENER_PASSWORD.match(password):
            raise ActionRefused("malformed", "mot de passe des auditeurs : 8 à 64 lettres ou chiffres")
        sec = keyfile.Secrets(sec.source_password, sec.meta_key, user, password)
        keyfile.save(self.key_path, sec)
        s = self._session
        if s is not None:
            s["secrets"], s["listener_user"] = sec, user
            if s["access"] == "prive":
                s["resend_listener"] = True
        self.write_status()
        return {"listener_user": user, "listener_password": password}

    def reveal(self) -> dict:
        sec = self._secrets()
        return {"listener_user": sec.listener_user, "listener_password": sec.listener_password or None}

    # ------------------------------------------------------------- lancement et arrêt
    async def start(self, args: dict) -> dict:
        if not self.df.enabled:
            raise ActionRefused("disabled", "diffusion hors service ([diffusion] enabled = false)")
        if self.problem:
            raise ActionRefused("unavailable", self.problem)
        if self.active:
            raise ActionRefused("busy", "une diffusion est déjà en cours")
        if not self.accepted():
            if args.get("confirm") is not True:
                raise ActionRefused("confirm_required", "avertissement à confirmer avant la première diffusion")
            self._accept(str(args.get("operator") or "opérateur")[:32])
        access = args.get("access", p.DEFAULT_ACCESS)
        hours = args.get("hours", p.DEFAULT_HOURS)
        voice = args.get("voice", False)
        choice = args.get("meta", list(p.DEFAULT_META_CHOICE))
        try:
            p.check_access(access)
            p.check_hours(hours)
            if not isinstance(voice, bool):
                raise p.DiffusionRefused("voice : true ou false")
            if not isinstance(choice, list) or any(c not in p.CHOICE_FIELDS for c in choice):
                raise p.DiffusionRefused("meta : liste de champs permis")
            fixed = p.check_meta({k: args.get(k) for k in ("pseudo", "indicatif", "message")})
        except p.DiffusionRefused as exc:
            raise ActionRefused("malformed", str(exc)) from None
        secrets = self._secrets()
        if access == "prive" and not secrets.listener_password:
            secrets = keyfile.Secrets(secrets.source_password, secrets.meta_key, secrets.listener_user,
                                      p.new_listener_password())
            keyfile.save(self.key_path, secrets)           # fixe ensuite, jusqu'à ce que l'opérateur le change
        now = self.clock()
        operator = str(args.get("operator") or "opérateur")[:32]
        self.values.update(fixed)
        self.last_start = {"at": int(now), "operator": operator}
        self._session = {"access": access, "voice": voice, "started": int(now),
                         "ends": None if hours is None else int(p.end_time(now, hours)),
                         "phase": "connexion", "listeners": None, "operator": operator, "meta_choice": choice,
                         "listener_user": secrets.listener_user, "secrets": secrets}
        self._drain_audio()
        self._meta_dirty = True
        emit_event(codes.ORT_6101, logger=log, operateur=operator, acces=access,
                   duree="sans limite" if hours is None else f"{hours} h", voix="oui" if voice else "non")
        self._task = asyncio.ensure_future(self._run_session(self._session))
        self.write_status()
        return self.status()

    async def stop(self, cause: str, by: str = "") -> None:
        s, self._session = self._session, None
        task, self._task = self._task, None
        if s is None:
            return
        self.last_stop = {"cause": cause, "at": int(self.clock())}   # aussitôt : jamais « arrêtée » sans cause
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        texts = {"operator": f"arrêt par {by}" if by else "arrêt par un opérateur", "duration": "fin de la durée",
                 "overload": "station surchargée", "gateway_restart": "passerelle relancée", "auth": "source refusée",
                 "disabled": "fonction mise hors service", "station_stop": "arrêt de la station"}
        emit_event(codes.ORT_6102, logger=log, cause=texts.get(cause, cause),
                   duree=fmt_duration(self.clock() - s["started"]))
        self.write_status()

    def _drain_audio(self) -> None:
        while not self.audio.empty():
            self.audio.get_nowait()

    # ------------------------------------------------------------- son reçu de la passerelle
    def on_packet(self, data: bytes) -> None:
        if not self.active or not self.token:
            return
        if data[:4] == au.INFO_MAGIC:
            info = au.unpack_info(self.token, data)
            if info is not None:
                self.on_info(info)
            return
        got = au.unpack(self.token, data)
        if got is None:
            return
        if self.audio.full():
            self.audio.get_nowait()                    # retard borné : la plus ancienne trame part
        self.audio.put_nowait(got[1])

    async def open_audio(self) -> bool:
        from ..modules.keys import key_path, load_or_create_key, module_secret
        try:
            secret = module_secret(load_or_create_key(key_path(self.cfg.supervisor.state_dir)), "diffusion")
            self.token = au.audio_token(secret)
            loop = asyncio.get_running_loop()
            self._udp, _ = await loop.create_datagram_endpoint(lambda: _UdpProtocol(self),
                                                               local_addr=("127.0.0.1", self.df.audio_port))
        except OSError as exc:
            emit_event(codes.ORT_6106, logger=log, chemin=f"127.0.0.1:{self.df.audio_port}", detail=str(exc)[:200])
            self.problem = f"port du son 127.0.0.1:{self.df.audio_port} indisponible"
            return False
        return True

    # ------------------------------------------------------------- une diffusion
    async def _run_session(self, s: dict) -> None:
        secrets: keyfile.Secrets = s["secrets"]
        meta = MetaClient(self.api_base, self.df.station, secrets.meta_key_bytes, clock=self.clock,
                          health=self.server_health)
        meta_task = asyncio.ensure_future(self._meta_loop(s, meta))
        attempt = 0
        try:
            while self._session is s:
                request = p.source_request(self.df.server, self.df.source_port, self.df.station, s["access"],
                                           secrets.source_password, self.df.codec, str(self.values.get("pseudo") or ""))
                start = time.monotonic()
                try:
                    conn = await open_source(self.df.server, self.df.source_port, request, self.ssl_context)
                except SourceRefused as exc:
                    if exc.status is None:                                 # pas de réponse du serveur
                        self.server_health.fail()
                    else:                                                  # le serveur a répondu (refus)
                        self.server_health.ok(time.monotonic() - start)
                    if exc.status in FATAL_STATUSES:
                        emit_event(codes.ORT_6103, logger=log, serveur=self.df.server, statut=exc.status)
                        asyncio.ensure_future(self.stop("auth"))
                        return
                    attempt += 1
                    await self._retry(s, str(exc), attempt)
                    continue
                self.server_health.ok(time.monotonic() - start)
                attempt = 0
                s["phase"] = "en_direct"
                self.write_status()
                try:
                    reason = await self._stream(s, conn)
                finally:
                    await conn.close()                 # arrêt compris : le montage est libéré tout de suite
                if reason == "end":
                    asyncio.ensure_future(self.stop("duration"))
                    return
                if self._session is s:
                    attempt += 1
                    await self._retry(s, reason, attempt)
        finally:
            meta_task.cancel()
            await meta.close()

    async def _retry(self, s: dict, detail: str, attempt: int) -> None:
        delay = p.backoff(attempt)
        s["phase"] = "nouvel_essai"
        self.write_status()
        emit_event(codes.ORT_6104, logger=log, serveur=self.df.server, detail=detail[:120], delai=delay)
        await asyncio.sleep(delay)

    async def _stream(self, s: dict, conn) -> str:
        """Envoie le son tant que la connexion tient ; renvoie la raison de la fin (« end » = durée écoulée)."""
        encoder = Encoder(self.df.codec)                  # flux neuf (en-têtes Ogg) à chaque connexion
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        sent = 0                                          # blocs envoyés depuis t0 : le débit suit l'horloge
        self._last_audio = time.monotonic()
        alerted = False
        try:
            while True:
                if s["ends"] is not None and self.clock() >= s["ends"]:
                    return "end"
                if conn.closed.is_set():
                    return "connexion fermée par le serveur"
                try:
                    pcm = await asyncio.wait_for(self.audio.get(), FRAME_S * 2)
                    self._last_audio = time.monotonic()
                    alerted = False
                except asyncio.TimeoutError:
                    behind = int((loop.time() - t0) / FRAME_S) - sent
                    if behind <= 0:
                        continue
                    pcm = au.SILENCE * min(behind, 10)    # pas de son de la passerelle : silence (Icecast coupe
                    if not alerted and time.monotonic() - self._last_audio > NO_AUDIO_ALERT_S:   # une source muette)
                        alerted = True
                        emit_event(codes.ORT_6108, logger=log, secondes=int(NO_AUDIO_ALERT_S))
                sent += len(pcm) // au.PCM_BYTES
                data = encoder.push(pcm)
                if data:
                    try:
                        await conn.send(data)
                    except (OSError, ConnectionError) as exc:
                        return f"envoi coupé ({exc.__class__.__name__})"
        finally:
            try:
                encoder.close()
            except Exception:                              # un encodeur abandonné ne doit rien bloquer
                pass

    async def _meta_loop(self, s: dict, meta: MetaClient) -> None:
        """Métadonnées : au lancement, à chaque changement (au plus 1 par seconde), au moins toutes les 30 s."""
        refused = False
        s["resend_listener"] = s["access"] == "prive"
        last = -p.META_REFRESH_S
        while self._session is s:
            if s.get("resend_listener"):               # au lancement privé, et quand l'opérateur change le mot
                s["resend_listener"] = False
                sec: keyfile.Secrets = s["secrets"]
                status = await meta.send_listener(sec.listener_user, sec.listener_password)
                if status != 200:
                    refused = True
                    emit_event(codes.ORT_6107, logger=log, serveur=self.df.server, statut=status or "sans réponse")
            silence = self.silence_reason()
            if silence != s.get("silence"):            # dit aux auditeurs dès que possible (au plus 1 par seconde)
                s["silence"] = silence
                self._meta_dirty = True
                self.write_status()
            now = time.monotonic()                     # cadence : horloge monotone (l'heure murale peut sauter)
            if "s_metre" in s["meta_choice"] and self._s_hist:   # S-mètre animé : un envoi par seconde
                self._meta_dirty = True
            if (self._meta_dirty and now - last >= p.META_MIN_INTERVAL_S) or now - last >= p.META_REFRESH_S:
                self._meta_dirty = False
                last = now
                self.values["s"] = self.s_points()
                try:
                    chosen = p.pick_meta(s["meta_choice"], self.values)
                except p.DiffusionRefused:            # une valeur inattendue : jamais d'arrêt, le pseudo seul
                    chosen = p.pick_meta(["pseudo"], self.values)
                status, counts = await meta.send_meta(s["access"], chosen, s.get("silence"))
                if status == 200:
                    refused = False
                    if counts is not None and counts.get(s["access"]) != s["listeners"]:
                        s["listeners"] = counts.get(s["access"])
                        self.write_status()
                elif not refused:
                    refused = True
                    emit_event(codes.ORT_6107, logger=log, serveur=self.df.server, statut=status or "sans réponse")
            await asyncio.sleep(0.25)

    # ------------------------------------------------------------- boucle
    async def run(self) -> None:
        self.setup()
        tasks = []
        if self.bus is not None:
            tasks.append(asyncio.ensure_future(self._bus_forever()))
        if self.df.enabled:
            await self.open_audio()
            log.info("prêt : serveur %s, station %s, codec %s", self.df.server, self.df.station, self.df.codec)
        else:
            log.info("[diffusion] hors service : le module attend sans rien envoyer")
        self.write_status()
        ticks = 0
        while True:
            await asyncio.sleep(TICK_S)
            try:
                await self.check_console()
            except Exception:
                emit_event(codes.ORT_6110, logger=log, trace=True, contexte="demande d'openRemoteTRX Console")
            ticks += 1
            if ticks % 10 == 0:
                self.write_status()                    # « updated » : trx-monitor voit un module vivant

    async def check_console(self) -> None:
        """Demande d'openRemoteTRX Console : lue puis effacée ; réponse dans state_dir/diffusion/console-reply.json (0644 : le
        compte de la console la lit), effacée après 15 s. Mêmes actions que la page, opérateur « openRemoteTRX Console »."""
        import json
        from ..presence.store import write_json
        reply_path = self.folder / CONSOLE_REPLY
        now = self.clock()
        if self._reply_at is not None and now - self._reply_at > CONSOLE_REPLY_KEEP_S:
            try:
                reply_path.unlink()
            except OSError:
                pass
            self._reply_at = None
        path = Path(self.cfg.supervisor.state_dir) / CONSOLE_REQUEST
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return
        except OSError as exc:
            log.info("demande de la console illisible : %s", exc)
            return
        try:
            path.unlink()
        except OSError as exc:
            log.info("demande de la console non effacée : %s", exc)
        try:
            req = json.loads(raw.decode("utf-8"))
            ident, action, args, at = req["id"], req["action"], req.get("args") or {}, float(req["at"])
            if not isinstance(ident, str) or not isinstance(action, str) or not isinstance(args, dict):
                raise ValueError("champs")
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            log.info("demande de la console mal formée : ignorée")
            return
        if abs(now - at) > CONSOLE_MAX_AGE_S:
            log.info("demande de la console trop ancienne : ignorée")
            return
        if action == "stop":
            args = {"operator": "openRemoteTRX Console"}                 # jamais une cause choisie par la demande
        elif action == "start":
            args = {**args, "operator": "openRemoteTRX Console"}
        try:
            reply = {"id": ident, "ok": True, "result": await self.act(action, args)}
        except ActionRefused as exc:
            reply = {"id": ident, "ok": False, "error": exc.reason, "message": str(exc)}
        except Exception:
            emit_event(codes.ORT_6110, logger=log, trace=True, contexte=f"action « {action[:20]} » d'openRemoteTRX Console")
            reply = {"id": ident, "ok": False, "error": "internal", "message": "erreur du module"}
        try:
            write_json(reply_path, reply, private=False)
            self._reply_at = now
        except OSError as exc:
            log.info("réponse à la console non écrite : %s", exc)

    async def _bus_forever(self) -> None:
        try:
            await self.bus.run_forever()
        except Exception as exc:                       # sans bus, aucun ordre : rien ne sera diffusé
            log.info("API interne indisponible : %s", exc)


def setup_logging(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s diffusion %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        handler = logging.handlers.RotatingFileHandler(folder / "diffusion.log", maxBytes=1_000_000, backupCount=4,
                                                       encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError as exc:
        log.info("journal %s impossible : %s", folder / "diffusion.log", exc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.diffusion.service", description="Module de diffusion")
    ap.add_argument("--config", type=Path, default=Path(os.environ.get("TRX_CONFIG_PATH") or default_config_path()))
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except (cfgmod.ConfigError, OSError) as exc:
        print(f"Configuration illisible ({args.config}) : {exc}", file=sys.stderr)
        return 2
    setup_logging(Path(cfg.supervisor.state_dir) / "diffusion")
    bus = None
    if os.environ.get("TRX_MODULE_SECRET"):
        from ..modules.client import ModuleClient       # droits du manifeste : son et état seulement
        bus = ModuleClient.from_env()
    try:
        asyncio.run(DiffusionService(cfg, args.config, bus_client=bus).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
