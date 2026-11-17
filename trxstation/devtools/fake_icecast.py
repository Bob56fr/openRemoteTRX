# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Faux serveur de diffusion pour les tests et les essais sans VPS (docs/protocole-diffusion.md).

- Source : comme Icecast 2.4 (raw TCP, sans TLS) : `PUT /<station>-<acces>`, `Authorization: Basic source:<mot>`,
  « HTTP/1.0 200 OK » puis lecture du flux brut ; 401 mauvais mot de passe, 403 montage occupé, 400 si la requête
  annonce du chunked ou une longueur (refusés par le protocole).
- Métadonnées : `POST /api/v1/<station>/<meta|auditeur>` signés (aiohttp), comme le service orx-meta.

Essai : python -m trxstation.devtools.fake_icecast --station bob56fr --source-password X --meta-key HEX
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass, field

from aiohttp import web

from ..diffusion import protocol as p

MOUNT = re.compile(r"^/([a-z0-9-]{2,32})-(prive|public)$")


@dataclass
class FakeIcecast:
    station: str = "bob56fr"
    source_password: str = "MotSource42"
    meta_key: bytes = bytes(32)
    listeners: dict[str, int] = field(default_factory=lambda: {"prive": 0, "public": 0})
    received: dict[str, bytearray] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)        # première ligne de chaque requête source
    statuses: list[int] = field(default_factory=list)
    metas: list[dict] = field(default_factory=list)
    listener_updates: list[dict] = field(default_factory=list)
    refuse_meta: int | None = None                             # forcer une erreur HTTP des métadonnées
    _writers: dict[str, asyncio.StreamWriter] = field(default_factory=dict)
    _last_ts: int = 0

    # ---------------------------------------------------------------- source (Icecast)
    async def _source(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        mount = None
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            lines = head.decode("latin-1").split("\r\n")
            self.requests.append(lines[0])
            headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if l)}
            method, path, _ = (lines[0].split(" ") + ["", "", ""])[:3]
            m = MOUNT.match(path)
            if method != "PUT" or not m or m.group(1) != self.station:
                return await self._reply(writer, 404, "Not Found")
            if "transfer-encoding" in headers or "content-length" in headers:
                return await self._reply(writer, 400, "Bad Request")       # Icecast 2.4 : flux corrompu
            want = "Basic " + base64.b64encode(f"source:{self.source_password}".encode()).decode()
            if headers.get("authorization") != want:
                return await self._reply(writer, 401, "Authentication Required")
            if path in self._writers:
                return await self._reply(writer, 403, "Forbidden")         # « Mountpoint in use »
            mount = path
            self._writers[mount] = writer
            self.received.setdefault(mount, bytearray())
            await self._reply(writer, 200, "OK", close=False)
            while data := await reader.read(65536):
                self.received[mount] += data
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, asyncio.LimitOverrunError, OSError):
            pass
        finally:
            if mount and self._writers.get(mount) is writer:
                del self._writers[mount]
            writer.close()

    async def _reply(self, writer: asyncio.StreamWriter, status: int, text: str, close: bool = True) -> None:
        self.statuses.append(status)
        writer.write(f"HTTP/1.0 {status} {text}\r\n\r\n".encode())
        await writer.drain()
        if close:
            writer.close()

    def live(self) -> list[str]:
        return sorted(self._writers)

    async def drop(self, mount: str | None = None) -> None:
        """Coupe une source (arrêt du serveur, panne réseau) : la station doit se reconnecter seule."""
        for m in [mount] if mount else list(self._writers):
            w = self._writers.pop(m, None)
            if w:
                w.close()

    # ---------------------------------------------------------------- métadonnées (orx-meta)
    async def _api(self, request: web.Request) -> web.Response:
        st, action = request.match_info["station"], request.match_info["action"]
        body = await request.read()
        if st != self.station:
            return web.json_response({"erreur": "station inconnue"}, status=404)
        sig = request.headers.get(p.SIGNATURE_HEADER, "")
        if sig != p.sign(self.meta_key, "POST", request.path, body):
            return web.json_response({"erreur": "signature invalide"}, status=401)
        d = json.loads(body)
        if d.get("ts_ms", 0) <= self._last_ts or abs(d["ts_ms"] - time.time() * 1000) > p.CLOCK_WINDOW_MS:
            return web.json_response({"erreur": "ts_ms"}, status=409)
        self._last_ts = d["ts_ms"]
        if self.refuse_meta:
            return web.json_response({"erreur": "refus d'essai"}, status=self.refuse_meta)
        if action == "meta":
            self.metas.append(d)
            return web.json_response({"ok": True, "auditeurs": dict(self.listeners)})
        if action == "auditeur":
            self.listener_updates.append(d)
            return web.json_response({"ok": True})
        return web.json_response({"erreur": "introuvable"}, status=404)

    # ---------------------------------------------------------------- démarrage
    async def start(self, host: str = "127.0.0.1") -> tuple[int, int]:
        """Lance les deux serveurs sur des ports libres ; renvoie (port des sources, port HTTP des métadonnées)."""
        self._server = await asyncio.start_server(self._source, host, 0)
        app = web.Application()
        app.router.add_post("/api/v1/{station}/{action}", self._api)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, 0)
        await site.start()
        self.source_port = self._server.sockets[0].getsockname()[1]
        self.http_port = site._server.sockets[0].getsockname()[1]     # type: ignore[union-attr]
        return self.source_port, self.http_port

    async def stop(self) -> None:
        await self.drop()
        self._server.close()
        await self._server.wait_closed()
        await self._runner.cleanup()


async def _main(args: argparse.Namespace) -> None:
    fake = FakeIcecast(args.station, args.source_password, bytes.fromhex(args.meta_key))
    src, http = await fake.start()
    print(f"faux serveur de diffusion : sources sur 127.0.0.1:{src} (sans TLS), métadonnées http://127.0.0.1:{http}")
    while True:
        await asyncio.sleep(5)
        print(f"en direct : {fake.live() or 'rien'} ; reçu : "
              f"{ {m: len(b) for m, b in fake.received.items()} } ; métadonnées : {len(fake.metas)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Faux serveur de diffusion (Icecast + métadonnées)")
    ap.add_argument("--station", default="bob56fr")
    ap.add_argument("--source-password", default="MotSource42")
    ap.add_argument("--meta-key", default="00" * 32)
    try:
        asyncio.run(_main(ap.parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
