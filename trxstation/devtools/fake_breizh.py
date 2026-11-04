# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Faux Breizh Audio Box : serveur du protocole Breizh v1 (docs/breizh-cahier-des-charges.md § 5), pour les tests.

Usage manuel (passerelle, ou breizh_probe.py, sur la même machine) :
    python -m trxstation.devtools.fake_breizh --key-file C:\\ProgramData\\trx-remote\\breizh.key --mode gain --gain-db -6

Modes de panne (§ 9) : echo, gain, slow (délai fixe), jitter, freeze (cesse de répondre après --freeze-after-s),
drop (perd 1 bloc sur --drop-every), forge (étiquettes fausses), replay (renvoie aussi les anciens AUDIO_RET),
spontaneous (AUDIO_RET jamais demandés), cat_on (annonce son CAT actif), proto2 (autre version), mode_off (refuse).
Comme le vrai Breizh : un paquet invalide est jeté SANS réponse ; une seule station (--station) si elle est donnée.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import struct
import time
from collections import deque
from pathlib import Path

from ..breizh import protocol as p
from ..config import BREIZH_DEFAULT_PORT

MODES = ("echo", "gain", "slow", "jitter", "freeze", "drop", "forge", "replay", "spontaneous", "cat_on", "proto2",
         "mode_off")


def apply_gain(block: bytes, gain_db: float) -> bytes:
    gain = 10 ** (gain_db / 20)
    samples = struct.unpack(f"<{p.BLOCK_SAMPLES}h", block)
    return struct.pack(f"<{p.BLOCK_SAMPLES}h", *(max(-32768, min(32767, int(s * gain))) for s in samples))


class FakeBreizh(asyncio.DatagramProtocol):
    def __init__(self, key: bytes, *, mode: str = "echo", gain_db: float = 0.0, delay_ms: float = 0.0,
                 jitter_ms: float = 20.0, freeze_after_s: float = 1.0, drop_every: int = 5, station: str | None = None,
                 latency_ms: int = 5, version: str = "faux Breizh 1") -> None:
        if mode not in MODES:
            raise ValueError(f"mode inconnu : {mode}")
        self.key, self.mode, self.gain_db = key, mode, gain_db
        self.delay_ms, self.jitter_ms, self.freeze_after_s, self.drop_every = delay_ms, jitter_ms, freeze_after_s, drop_every
        self.station, self.latency_ms, self.version = station, latency_ms, version
        self.transport: asyncio.DatagramTransport | None = None
        self.session: int | None = None
        self.session_key: bytes | None = None
        self.peer: tuple | None = None
        self.guard = p.SeqGuard()
        self.seq = 0
        self.session_started = 0.0
        self.sent_rets: deque[bytes] = deque(maxlen=20)
        self.stats = {"hello": 0, "audio": 0, "returned": 0, "ping": 0, "rejected": 0, "replayed": 0, "foreign": 0}

    # -- asyncio
    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if self.station is not None and addr[0] != self.station:
            self.stats["foreign"] += 1
            return
        try:
            packet = p.decode(data, self.key, self.session_key)
        except p.PacketError:
            self.stats["rejected"] += 1
            return
        if packet.type == p.Type.HELLO:
            self._hello(packet, addr)
            return
        if packet.session != self.session or addr != self.peer:
            self.stats["rejected"] += 1
            return
        if not self.guard.accept(packet.seq):
            self.stats["replayed"] += 1
            return
        if packet.type == p.Type.PING:
            self.stats["ping"] += 1
            self._send(p.Type.PONG, ref=packet.seq)
        elif packet.type == p.Type.AUDIO:
            self._audio(packet)
        elif packet.type == p.Type.BYE:
            self.session = self.session_key = self.peer = None

    # -- messages
    def _hello(self, packet: p.Packet, addr) -> None:
        self.stats["hello"] += 1
        try:
            hello = p.parse_hello(packet.payload)
        except p.PacketError as exc:
            code = "proto" if exc.reason == "proto" else "format"
            self._send_raw(p.Packet(p.Type.ERROR, packet.session, 1, 0, p.error_payload(code)), self.key, addr)
            return
        if self.mode == "mode_off":
            self._send_raw(p.Packet(p.Type.ERROR, packet.session, 1, 0, p.error_payload("mode_off")), self.key, addr)
            return
        nonce = p.new_nonce()
        self.session, self.peer, self.seq = packet.session, addr, 0
        self.session_key = p.session_key(self.key, packet.session, hello.nonce, nonce)
        self.guard = p.SeqGuard()
        self.guard.accept(packet.seq)
        self.session_started = time.monotonic()
        payload = p.hello_ack_payload(nonce, self.version, cat_off=self.mode != "cat_on", latency_ms=self.latency_ms,
                                      proto=2 if self.mode == "proto2" else p.PROTO)
        self.seq += 1
        self._send_raw(p.Packet(p.Type.HELLO_ACK, packet.session, self.seq, 0, payload), self.key, addr)

    def _audio(self, packet: p.Packet) -> None:
        self.stats["audio"] += 1
        if self.mode == "freeze" and time.monotonic() - self.session_started > self.freeze_after_s:
            return
        if self.mode == "drop" and self.stats["audio"] % self.drop_every == 0:
            return
        block = apply_gain(packet.payload, self.gain_db) if self.gain_db else packet.payload
        delay = self.delay_ms if self.mode == "slow" else random.uniform(0, self.jitter_ms) if self.mode == "jitter" else 0
        if delay:
            asyncio.get_running_loop().call_later(delay / 1000, self._return, packet.ref, block)
        else:
            self._return(packet.ref, block)

    def _return(self, ref: int, block: bytes) -> None:
        if self.session_key is None:
            return
        if self.mode == "replay":
            for old in list(self.sent_rets):
                self.transport.sendto(old, self.peer)
        data = self._send(p.Type.AUDIO_RET, ref=ref, payload=block)
        self.sent_rets.append(data)
        self.stats["returned"] += 1
        if self.mode == "spontaneous":
            self._send(p.Type.AUDIO_RET, ref=(ref + 1000) & p.U32, payload=block)

    # -- envoi
    def _send(self, kind: p.Type, *, ref: int = 0, payload: bytes = b"") -> bytes:
        self.seq += 1
        return self._send_raw(p.Packet(kind, self.session, self.seq, ref, payload), self.session_key, self.peer)

    def _send_raw(self, packet: p.Packet, key: bytes, addr) -> bytes:
        data = p.encode(packet, key)
        if self.mode == "forge" and packet.type in (p.Type.AUDIO_RET, p.Type.PONG):
            data = data[:-1] + bytes([data[-1] ^ 0xFF])
        if self.transport is not None:
            self.transport.sendto(data, addr)
        return data

    def bye(self, reason: str = "shutdown") -> None:
        if self.session_key is not None:
            self._send(p.Type.BYE, payload=p.bye_payload(reason))
        self.session = self.session_key = self.peer = None


async def serve(key: bytes, host: str = "127.0.0.1", port: int = BREIZH_DEFAULT_PORT,
                **options) -> tuple[asyncio.DatagramTransport, FakeBreizh]:
    loop = asyncio.get_running_loop()
    return await loop.create_datagram_endpoint(lambda: FakeBreizh(key, **options), local_addr=(host, port))


def _read_key(args) -> bytes:
    if args.key:
        return p.key_from_text(args.key)
    from ..breizh.keyfile import read_key
    return read_key(Path(args.key_file))


async def _main(args) -> None:
    transport, fake = await serve(_read_key(args), args.listen, args.port, mode=args.mode, gain_db=args.gain_db,
                                  delay_ms=args.delay_ms, jitter_ms=args.jitter_ms, freeze_after_s=args.freeze_after_s,
                                  drop_every=args.drop_every, station=args.station)
    print(f"Faux Breizh en écoute sur {args.listen}:{args.port} (mode {args.mode}) ; Ctrl+C pour arrêter.")
    try:
        while True:
            await asyncio.sleep(5)
            print(fake.stats)
    finally:
        fake.bye()
        transport.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Faux Breizh Audio Box (protocole Breizh v1) pour les essais")
    ap.add_argument("--listen", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=BREIZH_DEFAULT_PORT)
    key = ap.add_mutually_exclusive_group(required=True)
    key.add_argument("--key-file", help="fichier breizh.key de la station")
    key.add_argument("--key", help="clé d'appairage en texte (43 caractères)")
    ap.add_argument("--mode", choices=MODES, default="echo")
    ap.add_argument("--gain-db", type=float, default=0.0)
    ap.add_argument("--delay-ms", type=float, default=60.0, help="mode slow")
    ap.add_argument("--jitter-ms", type=float, default=20.0, help="mode jitter")
    ap.add_argument("--freeze-after-s", type=float, default=5.0, help="mode freeze")
    ap.add_argument("--drop-every", type=int, default=5, help="mode drop")
    ap.add_argument("--station", help="seule adresse de station acceptée")
    args = ap.parse_args(argv)
    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
