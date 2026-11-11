# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fausse station du protocole Breizh v1 (docs/breizh-cahier-des-charges.md § 5) : pour mettre au point Breizh
Audio Box SANS station ni poste, et pour vérifier une liaison réelle.

    python -m trxstation.devtools.breizh_probe --host 192.168.1.50 --key-file breizh.key --seconds 3

Ouvre une session (HELLO), mesure 5 PING, envoie un son de 1 kHz par blocs de 10 ms au rythme réel, puis BYE.
Applique les mêmes refus que la station : réponse d'une autre adresse, étiquette fausse, rejeu, bloc jamais envoyé
ou déjà répondu. Aucun poste, aucun PTT : ce n'est qu'un client UDP.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import struct
import sys
import time
from collections import Counter
from pathlib import Path

from .. import __version__
from ..breizh import protocol as p
from ..config import BREIZH_DEFAULT_PORT


class ProbeError(Exception):
    def __init__(self, reason: str, text: str):
        self.reason = reason
        super().__init__(text)


def tone_block(index: int, hz: float = 1000.0, level_db: float = -20.0) -> bytes:
    amplitude = 32767 * 10 ** (level_db / 20)
    step = 2 * math.pi * hz / p.RATE
    start = index * p.BLOCK_SAMPLES
    return struct.pack(f"<{p.BLOCK_SAMPLES}h", *(int(amplitude * math.sin(step * (start + i)))
                                                for i in range(p.BLOCK_SAMPLES)))


class BreizhProbe(asyncio.DatagramProtocol):
    def __init__(self, key: bytes, host: str, port: int, station_version: str = __version__) -> None:
        self.key, self.peer, self.station_version = key, (host, port), station_version
        self.transport: asyncio.DatagramTransport | None = None
        self.session = p.new_session()
        self.session_key: bytes | None = None
        self.seq = 0
        self.guard = p.SeqGuard()
        self.rejected: Counter[str] = Counter()
        self.ack: p.HelloAck | None = None
        self._hello_nonce = b""
        self._hello_wait: asyncio.Future | None = None
        self._pings: dict[int, float] = {}
        self._pongs: dict[int, float] = {}
        self.pending: dict[int, float] = {}         # bloc envoyé -> instant d'envoi
        self.answered: set[int] = set()
        self.returns: dict[int, tuple[float, bytes]] = {}    # bloc -> (aller-retour en ms, son traité)
        self.bye_reason = ""

    # -- asyncio
    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if tuple(addr[:2]) != self.peer:
            self.rejected["foreign"] += 1
            return
        try:
            packet = p.decode(data, self.key, self.session_key)
        except p.PacketError as exc:
            self.rejected[exc.reason] += 1
            return
        if packet.session != self.session:
            self.rejected["session"] += 1
            return
        if packet.type == p.Type.HELLO_ACK:
            self._on_ack(packet)
        elif packet.type == p.Type.ERROR:
            self._fail("error", f"Breizh refuse la liaison : {_error_text(packet.payload)}")
        elif not self.guard.accept(packet.seq):
            self.rejected["replay"] += 1
        elif packet.type == p.Type.PONG:
            if packet.ref in self._pings and packet.ref not in self._pongs:
                self._pongs[packet.ref] = (time.perf_counter() - self._pings[packet.ref]) * 1000
            else:
                self.rejected["unsolicited"] += 1
        elif packet.type == p.Type.AUDIO_RET:
            self._on_return(packet)
        elif packet.type == p.Type.BYE:
            self.bye_reason = p.parse_bye(packet.payload)
            self.session_key = None
        else:
            self.rejected["type"] += 1

    def _on_ack(self, packet: p.Packet) -> None:
        if self.session_key is not None or self._hello_wait is None or self._hello_wait.done():
            self.rejected["unsolicited"] += 1
            return
        try:
            ack = p.parse_hello_ack(packet.payload)
        except p.PacketError as exc:
            texts = {"proto": "version de protocole différente", "cat_on": "Breizh n'a pas coupé son CAT",
                     "latency": "traitement annoncé trop long", "nonce": "réponse mal formée", "json": "réponse mal formée"}
            self._fail(exc.reason, f"liaison refusée : {texts.get(exc.reason, exc.reason)}")
            return
        self.ack = ack
        self.guard.accept(packet.seq)
        self.session_key = p.session_key(self.key, self.session, self._hello_nonce, ack.nonce)
        self._hello_wait.set_result(ack)

    def _on_return(self, packet: p.Packet) -> None:
        sent = self.pending.pop(packet.ref, None)
        if sent is None:
            self.rejected["duplicate" if packet.ref in self.answered else "unsolicited"] += 1
            return
        self.answered.add(packet.ref)
        self.returns[packet.ref] = ((time.perf_counter() - sent) * 1000, packet.payload)

    def _fail(self, reason: str, text: str) -> None:
        if self._hello_wait is not None and not self._hello_wait.done():
            self._hello_wait.set_exception(ProbeError(reason, text))

    # -- envoi
    def _send(self, kind: p.Type, *, ref: int = 0, payload: bytes = b"", flags: int = 0) -> None:
        self.seq += 1
        key = self.key if kind in p.PAIRING_TYPES else self.session_key
        self.transport.sendto(p.encode(p.Packet(kind, self.session, self.seq, ref, payload, flags), key), self.peer)

    async def connect(self, timeout: float = 5.0, retry: float = 2.0) -> p.HelloAck:
        """HELLO toutes les `retry` s jusqu'à un HELLO_ACK valable ; ProbeError si refus ou aucune réponse."""
        self._hello_wait = asyncio.get_running_loop().create_future()
        self._hello_nonce = p.new_nonce()
        deadline = time.monotonic() + timeout
        while True:
            self._send(p.Type.HELLO, payload=p.hello_payload(self._hello_nonce, self.station_version))
            try:
                return await asyncio.wait_for(asyncio.shield(self._hello_wait),
                                              max(0.01, min(retry, deadline - time.monotonic())))
            except asyncio.TimeoutError:
                if time.monotonic() >= deadline:
                    raise ProbeError("timeout", "aucune réponse valable de Breizh (adresse, port, pare-feu, "
                                                "clé d'appairage ou mode OpenRemoteTRX à vérifier)") from None

    async def ping(self, count: int = 5, interval: float = 0.2, wait: float = 0.5) -> list[float | None]:
        for _ in range(count):
            self._send(p.Type.PING)
            self._pings[self.seq] = time.perf_counter()
            await asyncio.sleep(interval)
        await asyncio.sleep(wait)
        return [self._pongs.get(seq) for seq in sorted(self._pings)[-count:]]

    async def tone(self, seconds: float = 2.0, hz: float = 1000.0, level_db: float = -20.0,
                   block_timeout_ms: float = 40.0, wait: float = 0.3) -> dict:
        """Envoie le son au rythme réel (2 blocs toutes les 20 ms, comme la passerelle) et fait le bilan."""
        blocks = int(seconds * p.RATE / p.BLOCK_SAMPLES)
        start, sent = time.monotonic(), []
        for index in range(blocks):
            if index % 2 == 0:
                await asyncio.sleep(max(0.0, start + index * 0.01 - time.monotonic()))
            block = tone_block(index, hz, level_db)
            sent.append(block)
            self.pending[index] = time.perf_counter()
            self._send(p.Type.AUDIO, ref=index, payload=block, flags=p.FLAG_START if index == 0 else 0)
        await asyncio.sleep(wait)
        rtts = [rtt for rtt, _ in self.returns.values()]
        return {"sent": blocks, "returned": len(self.returns), "lost": len(self.pending),
                "late": sum(1 for r in rtts if r > block_timeout_ms),
                "rtt_ms_median": round(statistics.median(rtts), 2) if rtts else None,
                "rtt_ms_max": round(max(rtts), 2) if rtts else None,
                "gain_db": _gain_db(sent, self.returns), "rejected": dict(self.rejected)}

    def bye(self, reason: str = "shutdown") -> None:
        if self.session_key is not None:
            self._send(p.Type.BYE, payload=p.bye_payload(reason))
            self.session_key = None


def _error_text(payload: bytes) -> str:
    try:
        code = p.parse_error(payload)
    except p.PacketError:
        return "motif inconnu"
    return {"proto": "version de protocole différente", "format": "format du son refusé",
            "mode_off": "mode OpenRemoteTRX non activé dans Breizh", "busy": "Breizh sert déjà une autre station (si c'est la passerelle de cette station, la liaison est en "
                     "service : c'est normal)"}[code]


def _gain_db(sent: list[bytes], returns: dict[int, tuple[float, bytes]]) -> float | None:
    """Gain moyen du traitement (son revenu / son envoyé), en dB."""
    total_in = total_out = 0.0
    for ref, (_, block) in returns.items():
        total_in += sum(s * s for s in struct.unpack(f"<{p.BLOCK_SAMPLES}h", sent[ref]))
        total_out += sum(s * s for s in struct.unpack(f"<{p.BLOCK_SAMPLES}h", block))
    if not total_in or not total_out:
        return None
    return round(10 * math.log10(total_out / total_in), 2)


async def open_probe(key: bytes, host: str, port: int, **kwargs) -> tuple[asyncio.DatagramTransport, BreizhProbe]:
    loop = asyncio.get_running_loop()
    return await loop.create_datagram_endpoint(lambda: BreizhProbe(key, host, port, **kwargs),
                                               remote_addr=None, local_addr=("0.0.0.0" if ":" not in host else "::", 0))


async def _main(args) -> int:
    key = p.key_from_text(args.key) if args.key else _read_key_file(args.key_file)
    transport, probe = await open_probe(key, args.host, args.port)
    try:
        ack = await probe.connect(args.timeout)
        print(f"Liaison ouverte avec {ack.breizh or 'Breizh'} (traitement annoncé : {ack.latency_ms} ms).")
        rtts = await probe.ping(args.pings)
        got = [r for r in rtts if r is not None]
        print(f"PING : {len(got)}/{len(rtts)} réponses" + (f", aller-retour {min(got):.1f} à {max(got):.1f} ms" if got else ""))
        if args.sans_son:                                     # TRX Console : liaison seule, aucun son envoyé
            return 0 if len(got) == len(rtts) else 1
        report = await probe.tone(args.seconds)
        print(f"Son : {report['returned']}/{report['sent']} blocs revenus, {report['lost']} perdus, "
              f"{report['late']} en retard (> 40 ms), aller-retour médian {report['rtt_ms_median']} ms, "
              f"max {report['rtt_ms_max']} ms, gain du traitement {report['gain_db']} dB")
        if report["rejected"]:
            print(f"Paquets refusés : {report['rejected']}")
        return 0 if report["lost"] == 0 else 1
    except ProbeError as exc:
        print(f"ÉCHEC : {exc}")
        return 2
    finally:
        probe.bye()
        transport.close()


def _read_key_file(path: str) -> bytes:
    from ..breizh.keyfile import read_key
    return read_key(Path(path))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fausse station du protocole Breizh v1 : essai d'une liaison avec Breizh")
    ap.add_argument("--host", required=True, help="adresse IP du PC de Breizh")
    ap.add_argument("--port", type=int, default=BREIZH_DEFAULT_PORT)
    key = ap.add_mutually_exclusive_group(required=True)
    key.add_argument("--key-file", help="fichier breizh.key")
    key.add_argument("--key", help="clé d'appairage en texte (43 caractères)")
    ap.add_argument("--seconds", type=float, default=3.0, help="durée du son de test")
    ap.add_argument("--pings", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--sans-son", action="store_true", help="liaison et PING seulement, aucun son (TRX Console, menu 5.2)")
    args = ap.parse_args(argv)
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
