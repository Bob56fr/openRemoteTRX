# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Faux cluster DX (telnet) pour les essais sans internet.

    python -m trxstation.devtools.fake_cluster --port 7300

Invite « login: », mot de passe facultatif, indicatifs refusés, spots tirés
d'une liste à intervalle régulier, coupure après N spots. Il enregistre tout
ce que le client envoie (`received`) : les tests vérifient ainsi que le
client n'envoie que son indicatif (et son mot de passe).
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import time

SAMPLE_SPOTS = (
    "DX de F5XYZ:     14025.0  K1ABC        CW 599 tnx                     {t}Z JN18",
    "DX de DK8NE-#:   7018.0   OH2BH        CW    18 dB  25 WPM  CQ        {t}Z",
    "DX de G4ABC:     14205.0  VK2XYZ       59 strong LP                   {t}Z IO91",
    "DX de KM3T-#:    14074.0  JA1XXX       FT8   -12 dB  CQ               {t}Z",
    "DX de EA5WU:     21074.5  ZS6AAA       FT8 -08                        {t}Z",
    "DX de W3LPL:     3525.0   UA9ABC       CW                             {t}Z MD",
)


class FakeCluster:
    def __init__(self, *, banner: str = "Welcome to the FAKE DXSpider node", prompt: str = "login: ",
                 password: str | None = None, refuse_calls: tuple[str, ...] = (),
                 spots: tuple[str, ...] = SAMPLE_SPOTS, interval: float = 0.05,
                 close_after: int | None = None, telnet_negotiation: bool = False) -> None:
        self.banner, self.prompt, self.password = banner, prompt, password
        self.refuse_calls = {c.upper() for c in refuse_calls}
        self.spots, self.interval, self.close_after = spots, interval, close_after
        self.telnet_negotiation = telnet_negotiation
        self.received: list[str] = []
        self.connections = 0
        self.server: asyncio.base_events.Server | None = None
        self.port = 0
        self._tasks: set[asyncio.Task] = set()

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        self.server = await asyncio.start_server(self._handle, host, port)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            for task in list(self._tasks):
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            await self.server.wait_closed()

    async def _readline(self, reader: asyncio.StreamReader) -> str:
        raw = await asyncio.wait_for(reader.readline(), 30)
        if not raw:
            raise asyncio.IncompleteReadError(b"", None)
        line = raw.decode("utf-8", "replace").strip()
        self.received.append(line)
        return line

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            if self.telnet_negotiation:
                writer.write(bytes([255, 251, 1, 255, 253, 24]))      # WILL ECHO, DO TTYPE
            writer.write(f"{self.banner}\r\n{self.prompt}".encode())
            await writer.drain()
            call = (await self._readline(reader)).upper()
            if call in self.refuse_calls:
                writer.write(b"Sorry, invalid callsign\r\n")
                await writer.drain()
                return
            if self.password is not None:
                writer.write(b"password: ")
                await writer.drain()
                if await self._readline(reader) != self.password:
                    writer.write(b"Sorry, password incorrect\r\n")
                    await writer.drain()
                    return
            writer.write(f"Hello {call}, this is FAKE-1\r\n{call} de FAKE-1 >\r\n".encode())
            await writer.drain()
            sent = 0
            for spot in itertools.cycle(self.spots):
                if self.close_after is not None and sent >= self.close_after:
                    break
                writer.write((spot.format(t=time.strftime("%H%M", time.gmtime())) + "\a\r\n").encode())
                await writer.drain()
                sent += 1
                await asyncio.sleep(self.interval)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            self._tasks.discard(task)
            writer.close()


async def _main(port: int, interval: float) -> None:
    fake = FakeCluster(interval=interval)
    await fake.start("127.0.0.1", port)
    print(f"Faux cluster sur 127.0.0.1:{fake.port} (Ctrl+C pour arrêter)")
    await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Faux cluster DX telnet (127.0.0.1)")
    ap.add_argument("--port", type=int, default=7300)
    ap.add_argument("--intervalle", type=float, default=2.0, help="secondes entre deux spots")
    args = ap.parse_args(argv)
    try:
        asyncio.run(_main(args.port, args.intervalle))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
