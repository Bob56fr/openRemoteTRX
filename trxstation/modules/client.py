"""Bibliothèque côté module : connexion à l'API interne du cœur.

Exemple minimal :

    client = ModuleClient("demo", secret, port=47810)
    client.on_event = lambda name, data: print(name, data)
    await client.run_forever()      # reconnexion automatique

Le module détecte les événements manqués (trou dans seq) et appelle
on_gap() : il doit alors relire l'état avec await client.get_state().
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
from typing import Any, Callable

from . import API_VERSION, DEFAULT_BUS_HOST, DEFAULT_BUS_PORT
from .protocol import MAX_LINE_BYTES, ProtocolError, decode, encode

log = logging.getLogger("trx.module")


class BusRefused(Exception):
    """Le cœur a refusé la connexion (secret, API…) : inutile d'insister."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RequestFailed(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class ModuleClient:
    def __init__(self, module: str, secret: str, *, host: str = DEFAULT_BUS_HOST,
                 port: int = DEFAULT_BUS_PORT, heartbeat_s: float = 2.0,
                 request_timeout_s: float = 5.0) -> None:
        self.module, self.secret = module, secret
        self.host, self.port = host, port
        self.heartbeat_s = heartbeat_s
        self.request_timeout_s = request_timeout_s
        self.on_event: Callable[[str, dict], Any] | None = None
        self.on_gap: Callable[[], Any] | None = None
        self.on_connect: Callable[[], Any] | None = None
        self.metrics: Callable[[], dict] | None = None
        self.last_seq: int | None = None
        self.connected = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._stopping = False

    @classmethod
    def from_env(cls, **kw) -> "ModuleClient":
        """Paramètres passés par le superviseur via l'environnement."""
        return cls(os.environ["TRX_MODULE_NAME"], os.environ["TRX_MODULE_SECRET"],
                   host=os.environ.get("TRX_BUS_HOST", DEFAULT_BUS_HOST),
                   port=int(os.environ.get("TRX_BUS_PORT", DEFAULT_BUS_PORT)), **kw)

    # ------------------------------------------------------------- connexion
    async def connect(self) -> None:
        reader, writer = await asyncio.open_connection(self.host, self.port,
                                                       limit=MAX_LINE_BYTES)
        writer.write(encode({"type": "hello", "module": self.module,
                             "secret": self.secret, "api": API_VERSION}))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), 5.0)
        if not line:
            writer.close()
            raise ConnectionError("connexion fermée par le cœur")
        msg = decode(line)
        if msg["type"] == "error":
            writer.close()
            raise BusRefused(str(msg.get("code")), str(msg.get("message")))
        if msg["type"] != "welcome":
            writer.close()
            raise ConnectionError("réponse inattendue du cœur")
        self.last_seq = int(msg.get("seq", 0))
        self._writer = writer
        self._reader = reader
        self.connected.set()

    async def run_session(self) -> None:
        """Une session : lecture + battements de cœur, jusqu'à la coupure."""
        await self.connect()
        hb = asyncio.ensure_future(self._heartbeat_loop())
        self._events: asyncio.Queue = asyncio.Queue()
        disp = asyncio.ensure_future(self._dispatch_loop())
        # Le rappel de connexion passe par la file : il peut faire des requêtes,
        # dont la réponse sera lue par _read_loop qui tourne déjà.
        self._events.put_nowait({"type": "_connect"})
        try:
            await self._read_loop()
        finally:
            hb.cancel()
            disp.cancel()
            self.connected.clear()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("connexion perdue"))
            self._pending.clear()
            if self._writer:
                self._writer.close()
                self._writer = None

    async def run_forever(self, max_delay_s: float = 30.0) -> None:
        """Reconnexion automatique avec délai croissant."""
        delay = 1.0
        while not self._stopping:
            try:
                await self.run_session()
                delay = 1.0
            except BusRefused:
                raise
            except (ConnectionError, OSError, asyncio.TimeoutError, ProtocolError) as exc:
                log.warning("cœur injoignable (%s), nouvel essai dans %.0f s",
                            exc or type(exc).__name__, delay)
            if self._stopping:
                break
            await asyncio.sleep(delay)
            delay = min(max_delay_s, delay * 2)

    def stop(self) -> None:
        self._stopping = True
        if self._writer:
            self._writer.close()

    # ------------------------------------------------------------- boucles
    async def _read_loop(self) -> None:
        while True:
            line = await self._reader.readline()
            if not line:
                return
            try:
                msg = decode(line)
            except ProtocolError:
                continue
            if msg["type"] == "event":
                # Traité à part : un rappel peut lui-même faire une requête.
                self._events.put_nowait(msg)
            elif msg["type"] == "response":
                fut = self._pending.pop(msg.get("id"), None)
                if fut and not fut.done():
                    if msg.get("ok"):
                        fut.set_result(msg.get("result"))
                    else:
                        fut.set_exception(RequestFailed(str(msg.get("error")),
                                                        str(msg.get("message", ""))))

    async def _dispatch_loop(self) -> None:
        while True:
            msg = await self._events.get()
            if msg.get("type") == "_connect":
                if self.on_connect:
                    try:
                        await _maybe_await(self.on_connect())
                    except Exception:
                        log.exception("rappel de connexion en erreur")
                continue
            seq = int(msg.get("seq", 0))
            gap = self.last_seq is not None and seq > self.last_seq + 1
            self.last_seq = seq
            try:
                if gap and self.on_gap:
                    await _maybe_await(self.on_gap())
                if self.on_event:
                    await _maybe_await(self.on_event(msg.get("name"), msg.get("data") or {}))
            except Exception:
                log.exception("traitement de l'événement %s en erreur", msg.get("name"))

    async def _heartbeat_loop(self) -> None:
        while True:
            metrics = {}
            if self.metrics:
                try:
                    metrics = dict(self.metrics())
                except Exception:
                    log.exception("métriques indisponibles")
            await self._send({"type": "heartbeat", "metrics": metrics})
            await asyncio.sleep(self.heartbeat_s)

    async def _send(self, msg: dict) -> None:
        if self._writer is None:
            raise ConnectionError("non connecté")
        self._writer.write(encode(msg))
        await self._writer.drain()

    # ------------------------------------------------------------- requêtes
    async def request(self, op: str, **args) -> Any:
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send({"type": "request", "id": rid, "op": op, "args": args})
            return await asyncio.wait_for(fut, self.request_timeout_s)
        finally:
            self._pending.pop(rid, None)

    async def get_state(self) -> dict:
        return await self.request("get_state")

    async def command(self, command: str, **params) -> Any:
        return await self.request("command", command=command, params=params)

    async def client_message(self, **message) -> None:
        await self.request("client_message", message=message)

    async def verify_token(self, token: str) -> dict:
        return await self.request("verify_token", token=token)


async def _maybe_await(value):
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value
