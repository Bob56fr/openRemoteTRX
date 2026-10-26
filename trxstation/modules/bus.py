"""Serveur de l'API interne, côté cœur TRX (intégré à la passerelle).

Règle d'or : le cœur n'attend jamais un module.
- publish() est synchrone et ne bloque jamais : chaque module a sa file
  bornée ; si elle déborde, les plus anciens événements sont jetés et le
  module voit un trou dans les numéros (seq) qui l'invite à relire l'état.
- Un module trop lent à lire est déconnecté, sans effet sur le cœur.
- Les commandes passent par les mêmes règles que celles du client :
  refusées pendant le PTT, journalisées avec leur origine.
"""

from __future__ import annotations

import asyncio
import hmac
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import API_VERSION, DEFAULT_BUS_HOST
from .manifest import Manifest, api_compatible
from .protocol import MAX_LINE_BYTES, ProtocolError, decode, encode
from .tokens import TokenAuthority, TokenError

log = logging.getLogger("trx.bus")

# Commandes refusées tant que le PTT est actif (décision du projet).
PTT_BLOCKED_COMMANDS = frozenset({"qsy"})

class CommandRefused(Exception):
    """Levée par le gestionnaire de commandes du cœur : refus avec un code stable."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


StateProvider = Callable[[], dict]
CommandHandler = Callable[[str, dict, str], Any]       # (commande, args, module)
ClientSink = Callable[[str, dict], None]               # (module, message)
HealthSink = Callable[[str, dict], None]               # (module, métriques)


class _TokenBucket:
    def __init__(self, rate: float, burst: float, clock=time.monotonic) -> None:
        self.rate, self.burst, self._clock = rate, burst, clock
        self.tokens, self.t = burst, clock()

    def take(self) -> bool:
        now = self._clock()
        self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


@dataclass
class ModuleSession:
    manifest: Manifest
    writer: asyncio.StreamWriter
    queue: asyncio.Queue
    bucket: _TokenBucket
    dropped: int = 0
    last_heartbeat: float = field(default_factory=time.monotonic)
    metrics: dict = field(default_factory=dict)
    tasks: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.manifest.name


class BusServer:
    def __init__(self, manifests: dict[str, Manifest], secrets: dict[str, str], *,
                 state_provider: StateProvider,
                 command_handler: CommandHandler | None = None,
                 client_sink: ClientSink | None = None,
                 health_sink: HealthSink | None = None,
                 tokens: TokenAuthority | None = None,
                 host: str = DEFAULT_BUS_HOST, port: int = 0,
                 queue_size: int = 256, write_timeout_s: float = 2.0,
                 hello_timeout_s: float = 3.0,
                 client_rate: float = 20.0, client_burst: float = 40.0,
                 command_timeout_s: float = 5.0) -> None:
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("l'API interne n'écoute que sur la machine locale")
        self.manifests = dict(manifests)
        self.secrets = dict(secrets)
        self.state_provider = state_provider
        self.command_handler = command_handler
        self.client_sink = client_sink
        self.health_sink = health_sink
        self.tokens = tokens
        self.host, self.port = host, port
        self.queue_size = queue_size
        self.write_timeout_s = write_timeout_s
        self.hello_timeout_s = hello_timeout_s
        self.client_rate, self.client_burst = client_rate, client_burst
        self.command_timeout_s = command_timeout_s
        self.seq = 0
        self.sessions: dict[str, ModuleSession] = {}
        self._server: asyncio.base_events.Server | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ cycle de vie
    async def start(self) -> int:
        self._loop = asyncio.get_running_loop()
        self._server = await asyncio.start_server(
            self._handle, self.host, self.port, limit=MAX_LINE_BYTES)
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("API interne à l'écoute sur %s:%s", self.host, self.port)
        return self.port

    async def stop(self) -> None:
        for sess in list(self.sessions.values()):
            self._close_session(sess, "arrêt du cœur")
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # ------------------------------------------------------------- diffusion
    def publish(self, name: str, data: dict | None = None) -> int:
        """Diffuse un événement aux modules abonnés. Ne bloque jamais.

        À appeler depuis la boucle asyncio du cœur ; depuis un autre thread,
        utiliser publish_threadsafe().
        """
        self.seq += 1
        msg = {"type": "event", "seq": self.seq, "ts": time.time(),
               "name": name, "data": data or {}}
        for sess in list(self.sessions.values()):
            if name in sess.manifest.rights.events:
                self._enqueue(sess, msg)
        return self.seq

    def publish_threadsafe(self, name: str, data: dict | None = None) -> None:
        if self._loop is None:
            raise RuntimeError("bus non démarré")
        self._loop.call_soon_threadsafe(self.publish, name, data)

    def send_to(self, module: str, name: str, data: dict | None = None) -> bool:
        """Envoie un événement à un seul module (ex. consigne « degrade »)."""
        sess = self.sessions.get(module)
        if sess is None or name not in sess.manifest.rights.events:
            return False
        self.seq += 1
        self._enqueue(sess, {"type": "event", "seq": self.seq, "ts": time.time(),
                             "name": name, "data": data or {}})
        return True

    def _enqueue(self, sess: ModuleSession, msg: dict) -> None:
        q = sess.queue
        while True:
            try:
                q.put_nowait(msg)
                return
            except asyncio.QueueFull:
                try:
                    q.get_nowait()          # jette le plus ancien
                    sess.dropped += 1
                except asyncio.QueueEmpty:
                    pass

    # ------------------------------------------------------------- état
    def module_status(self) -> dict[str, dict]:
        now = time.monotonic()
        return {name: {"connected": True,
                       "heartbeat_age_s": round(now - s.last_heartbeat, 3),
                       "dropped": s.dropped, "metrics": dict(s.metrics)}
                for name, s in self.sessions.items()}

    # ------------------------------------------------------------- connexions
    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        sess: ModuleSession | None = None
        try:
            sess = await self._handshake(reader, writer)
            if sess is None:
                return
            sess.tasks.append(asyncio.ensure_future(self._writer_loop(sess)))
            await self._reader_loop(sess, reader)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:                        # un module ne fait jamais tomber le cœur
            log.exception("erreur sur une connexion module")
        finally:
            if sess is not None:
                self._close_session(sess, "déconnexion")
            else:
                writer.close()

    async def _send_now(self, writer: asyncio.StreamWriter, msg: dict) -> None:
        writer.write(encode(msg))
        await asyncio.wait_for(writer.drain(), self.write_timeout_s)

    async def _handshake(self, reader, writer) -> ModuleSession | None:
        async def refuse(code: str, message: str) -> None:
            log.warning("module refusé : %s", message)
            try:
                await self._send_now(writer, {"type": "error", "code": code,
                                              "message": message})
            finally:
                writer.close()

        try:
            line = await asyncio.wait_for(reader.readline(), self.hello_timeout_s)
            msg = decode(line)
        except (asyncio.TimeoutError, ProtocolError, ValueError):
            await refuse("hello", "présentation absente ou illisible")
            return None
        name = msg.get("module")
        if msg.get("type") != "hello" or not isinstance(name, str):
            await refuse("hello", "présentation attendue")
            return None
        manifest = self.manifests.get(name)
        expected = self.secrets.get(name)
        given = msg.get("secret")
        if manifest is None or expected is None or not isinstance(given, str) \
                or not hmac.compare_digest(given, expected):
            await refuse("auth", f"module {name!r} inconnu ou secret invalide")
            return None
        api = str(msg.get("api", ""))
        if not api_compatible(api) or not api_compatible(manifest.api):
            await refuse("api", f"{name} : API {api} incompatible avec {API_VERSION}")
            return None
        old = self.sessions.get(name)
        if old is not None:
            self._close_session(old, "remplacé par une nouvelle connexion")
        sess = ModuleSession(manifest=manifest, writer=writer,
                             queue=asyncio.Queue(self.queue_size),
                             bucket=_TokenBucket(self.client_rate, self.client_burst))
        await self._send_now(writer, {"type": "welcome", "api": API_VERSION,
                                      "seq": self.seq})
        self.sessions[name] = sess
        log.info("module %s %s connecté", name, manifest.version)
        return sess

    async def _writer_loop(self, sess: ModuleSession) -> None:
        try:
            while True:
                msg = await sess.queue.get()
                await self._send_now(sess.writer, msg)
        except asyncio.TimeoutError:
            log.warning("module %s trop lent à lire : déconnecté", sess.name)
            self._close_session(sess, "trop lent")
        except (ConnectionError, asyncio.CancelledError):
            pass

    async def _reader_loop(self, sess: ModuleSession, reader) -> None:
        while True:
            line = await reader.readline()
            if not line:
                return
            try:
                msg = decode(line)
            except ProtocolError:
                log.warning("module %s : ligne illisible ignorée", sess.name)
                continue
            mtype = msg["type"]
            if mtype == "heartbeat":
                sess.last_heartbeat = time.monotonic()
                metrics = msg.get("metrics")
                sess.metrics = metrics if isinstance(metrics, dict) else {}
                if self.health_sink:
                    self._safe_call(self.health_sink, sess.name, sess.metrics)
            elif mtype == "request":
                resp = await self._handle_request(sess, msg)
                self._enqueue(sess, resp)

    def _safe_call(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("rappel du cœur en erreur")

    # ------------------------------------------------------------- requêtes
    async def _handle_request(self, sess: ModuleSession, msg: dict) -> dict:
        rid = msg.get("id")
        op = msg.get("op")
        args = msg.get("args") if isinstance(msg.get("args"), dict) else {}

        def ok(result=None) -> dict:
            return {"type": "response", "id": rid, "ok": True, "result": result}

        def err(code: str, message: str) -> dict:
            return {"type": "response", "id": rid, "ok": False,
                    "error": code, "message": message}

        rights = sess.manifest.rights
        try:
            if op == "get_state":
                return ok(dict(self.state_provider()))

            if op == "command":
                cmd = args.get("command")
                if cmd not in rights.commands:
                    return err("forbidden", f"commande {cmd!r} non autorisée pour {sess.name}")
                if cmd in PTT_BLOCKED_COMMANDS and self.state_provider().get("ptt"):
                    log.info("commande %s de %s refusée : PTT actif", cmd, sess.name)
                    return err("ptt_active", "refusé pendant l'émission")
                if self.command_handler is None:
                    return err("unavailable", "aucune commande disponible")
                log.info("commande %s demandée par le module %s", cmd, sess.name)
                try:
                    result = self.command_handler(cmd, dict(args.get("params") or {}), sess.name)
                    if inspect.isawaitable(result):
                        result = await asyncio.wait_for(result, self.command_timeout_s)
                except CommandRefused as exc:
                    return err(exc.code, str(exc))
                except asyncio.TimeoutError:
                    return err("timeout", "le cœur n'a pas répondu à temps")
                return ok(result)

            if op == "client_message":
                if not rights.client_messages:
                    return err("forbidden", "messages vers le client non autorisés")
                if not sess.bucket.take():
                    return err("rate_limited", "trop de messages, réessayer plus tard")
                if self.client_sink is not None:
                    self.client_sink(sess.name, dict(args.get("message") or {}))
                return ok()

            if op == "verify_token":
                if not rights.verify_tokens or self.tokens is None:
                    return err("forbidden", "vérification de jeton non autorisée")
                try:
                    claims = self.tokens.verify(str(args.get("token", "")))
                except TokenError as exc:
                    return err(f"token_{exc.code}", str(exc))
                return ok({"sid": claims.sid, "user": claims.user, "exp": claims.exp})

            return err("unknown_op", f"opération inconnue {op!r}")
        except Exception as exc:
            log.exception("requête %s de %s en erreur", op, sess.name)
            return err("internal", str(exc))

    def _close_session(self, sess: ModuleSession, reason: str) -> None:
        if self.sessions.get(sess.name) is sess:
            del self.sessions[sess.name]
            log.info("module %s : %s", sess.name, reason)
        for t in sess.tasks:
            t.cancel()
        try:
            sess.writer.close()
        except Exception:
            pass
