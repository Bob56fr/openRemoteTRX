# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Connexion source à Icecast (asyncio) : `PUT` en flux brut, en TLS, sans mandataire (docs/protocole-diffusion.md § 2).

La réponse d'Icecast (« HTTP/1.0 200 OK ») se lit sur la prise elle-même ; ensuite Icecast ne dit plus rien : toute
donnée ou fin de connexion de sa part = source coupée.
"""
from __future__ import annotations

import asyncio
import ssl

from . import protocol as p

CONNECT_TIMEOUT_S = 10.0
REPLY_TIMEOUT_S = 10.0


class SourceRefused(Exception):
    """Icecast a refusé la source : `status` = 401 (mot de passe), 403 (montage occupé)… ; None = pas de réponse."""

    def __init__(self, status: int | None, detail: str = "") -> None:
        super().__init__(f"source refusée ({status if status is not None else 'pas de réponse'}) {detail}".strip())
        self.status = status


class SourceConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self.closed = asyncio.Event()
        self._watch = asyncio.ensure_future(self._watch_peer())

    async def _watch_peer(self) -> None:
        try:
            while await self._reader.read(1024):
                pass                         # Icecast n'envoie rien après « 200 OK » : on ignore
        except (OSError, asyncio.IncompleteReadError, ssl.SSLError):
            pass
        self.closed.set()

    async def send(self, data: bytes) -> None:
        if self.closed.is_set():
            raise ConnectionError("source coupée par le serveur")
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        """Fermeture SANS « close_notify » TLS : Icecast 2.4.4, quand il fait lui-même le TLS, tourne en boucle à
        100 % d'un cœur sur un close_notify et garde le montage occupé (essai du 2026-11-17). Une fin TCP nette lui
        suffit (« End of Stream ») ; rien n'est perdu : la source n'a plus rien à dire."""
        self.closed.set()
        self._watch.cancel()
        try:
            self._writer.transport.abort()
        except (OSError, AttributeError):
            pass


def client_ssl_context() -> ssl.SSLContext:
    """Certificat du serveur VÉRIFIÉ (autorités du système) : jamais de TLS sans vérification."""
    return ssl.create_default_context()


async def open_source(host: str, port: int, request: bytes, ssl_ctx: ssl.SSLContext | None) -> SourceConnection:
    """Ouvre la connexion, envoie les en-têtes, attend « 200 OK » ; lève SourceRefused sinon."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_ctx, server_hostname=host if ssl_ctx else None),
            CONNECT_TIMEOUT_S)
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as exc:
        raise SourceRefused(None, f"connexion impossible : {exc.__class__.__name__}") from None
    try:
        writer.write(request)
        await writer.drain()
        line = await asyncio.wait_for(reader.readuntil(b"\r\n"), REPLY_TIMEOUT_S)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
            ssl.SSLError):
        writer.close()
        raise SourceRefused(None) from None
    status = p.source_reply_status(line)
    if status != 200:
        writer.close()
        raise SourceRefused(status)
    return SourceConnection(reader, writer)
