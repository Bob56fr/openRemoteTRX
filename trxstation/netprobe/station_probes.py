# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sondes de la station vers la box et vers Internet (docs/netprobe-cahier-des-charges.md § 5, EF4).

Une sonde par seconde vers chaque cible : ping ICMP sans privilège (Linux : socket « ping » SOCK_DGRAM permise par
net.ipv4.ping_group_range ; Windows : IcmpSendEcho), sinon connexion TCP toutes les 5 s (port 80 de la box, 443 de
la cible Internet ; une connexion REFUSÉE prouve que la machine répond). Elles disent, après une coupure, si le
réseau local ou la connexion Internet de la box ont lâché aussi (diagnostic § 7, règles 2 et 3).

Décision technique (étape 138) : elles tournent dans la passerelle, en tâche asyncio sans rien de bloquant (ICMP de
Windows dans un fil), et non dans un module : les modules ne démarrent que si `[modules]` est en service. Toute erreur
reste ici. Elles n'envoient que ces paquets et n'ont accès à rien d'autre.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
import struct
import sys
import time
from collections import deque

from . import calc

log = logging.getLogger(__name__)
ICMP_EVERY_MS = 1_000
TCP_EVERY_MS = 5_000
TIMEOUT_S = 1.0
TCP_PORTS = {"lan": 80, "internet": 443}
KEEP_MS = 900_000                       # 15 min d'historique pour le diagnostic après coup
DOWN_RATIO = 0.5                        # sonde « tombée » pendant une coupure : la moitié des essais au moins ratés


def default_gateway() -> str:
    """Passerelle par défaut IPv4 de la machine, ou "" si introuvable (jamais d'exception)."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/net/route", encoding="ascii") as handle:
                for line in handle.readlines()[1:]:
                    parts = line.split()
                    if len(parts) > 3 and parts[1] == "00000000" and int(parts[3], 16) & 2:
                        return socket.inet_ntoa(struct.pack("<L", int(parts[2], 16)))
        elif os.name == "nt":
            import ctypes

            class Row(ctypes.Structure):
                _fields_ = [(name, ctypes.c_uint32) for name in (
                    "dest", "mask", "policy", "next_hop", "if_index", "type", "proto", "age", "next_hop_as",
                    "metric1", "metric2", "metric3", "metric4", "metric5")]
            # routes par défaut (0.0.0.0/0) ayant une vraie passerelle, la plus petite métrique d'abord ; une route
            # par défaut sans passerelle (VPN point à point) est sautée : c'est la box qu'on veut sonder
            api = ctypes.windll.iphlpapi
            api.GetIpForwardTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.c_int]
            size = ctypes.c_ulong(0)
            api.GetIpForwardTable(None, ctypes.byref(size), 0)
            buffer = ctypes.create_string_buffer(size.value)
            if api.GetIpForwardTable(buffer, ctypes.byref(size), 1) == 0:
                count = struct.unpack_from("<L", buffer, 0)[0]
                rows = [Row.from_buffer_copy(buffer, 4 + i * ctypes.sizeof(Row)) for i in range(count)]
                best = sorted((r for r in rows if r.dest == 0 and r.mask == 0 and r.next_hop), key=lambda r: r.metric1)
                if best:
                    return socket.inet_ntoa(struct.pack("<L", best[0].next_hop))
    except Exception as exc:                       # fichier absent, API indisponible : pas de sonde de la box
        log.info("passerelle par défaut introuvable : %s", exc)
    return ""


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


async def icmp_linux(address: str, seq: int, timeout: float = TIMEOUT_S) -> bool:
    """Ping sans privilège ; PermissionError si le système ne le permet pas (alors : TCP)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
    try:
        sock.setblocking(False)
        header = struct.pack("!BBHHH", 8, 0, 0, 0, seq & 0xFFFF)
        payload = b"openremotetrx"
        packet = struct.pack("!BBHHH", 8, 0, _checksum(header + payload), 0, seq & 0xFFFF) + payload
        loop = asyncio.get_running_loop()
        await loop.sock_sendto(sock, packet, (address, 0))
        deadline = loop.time() + timeout
        while True:
            left = deadline - loop.time()
            if left <= 0:
                return False
            try:
                reply = await asyncio.wait_for(loop.sock_recv(sock, 512), left)
            except asyncio.TimeoutError:
                return False
            if len(reply) >= 8 and reply[0] == 0 and struct.unpack("!H", reply[6:8])[0] == seq & 0xFFFF:
                return True
    finally:
        sock.close()


def _icmp_windows_blocking(address: str, timeout: float) -> bool:
    import ctypes
    from ctypes import wintypes
    icmp = ctypes.windll.iphlpapi
    icmp.IcmpCreateFile.restype = wintypes.HANDLE
    icmp.IcmpSendEcho.argtypes = [wintypes.HANDLE, ctypes.c_uint32, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    icmp.IcmpSendEcho.restype = wintypes.DWORD
    icmp.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
    handle = icmp.IcmpCreateFile()
    if not handle or handle == wintypes.HANDLE(-1).value:
        raise PermissionError("IcmpCreateFile refusé")
    try:
        payload = b"openremotetrx"
        reply = ctypes.create_string_buffer(64 + len(payload))
        dest = struct.unpack("<L", socket.inet_aton(address))[0]
        count = icmp.IcmpSendEcho(handle, dest, payload, len(payload), None, reply, len(reply), int(timeout * 1000))
        return count > 0 and struct.unpack("<L", reply.raw[4:8])[0] == 0      # IP_SUCCESS
    finally:
        icmp.IcmpCloseHandle(handle)


async def icmp_windows(address: str, seq: int, timeout: float = TIMEOUT_S) -> bool:
    return await asyncio.to_thread(_icmp_windows_blocking, address, timeout)


async def tcp_probe(address: str, port: int, timeout: float = 2.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(address, port), timeout)
    except ConnectionRefusedError:
        return True                                # la machine a répondu (refus) : elle est joignable
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


class Target:
    def __init__(self, name: str, address: str) -> None:
        self.name, self.address = name, address
        self.method = ""                           # icmp, tcp ; "" = pas encore choisie
        self.seq = 0
        self.beats: deque[list] = deque()          # [numéro, envoi (mono), réponse (mono) ou None]
        self.history: deque[tuple[int, bool]] = deque()   # (heure murale, réussi) pour le diagnostic


class StationProbes:
    def __init__(self, lan_target: str, internet_target: str, *, mono_ms=None, wall_ms=None,
                 icmp=None, tcp=None, gateway=default_gateway) -> None:
        self.mono_ms = mono_ms or (lambda: int(time.monotonic() * 1000))
        self.wall_ms = wall_ms or (lambda: int(time.time() * 1000))
        self._icmp = icmp or (icmp_windows if os.name == "nt" else icmp_linux)
        self._tcp = tcp or tcp_probe
        self._gateway = gateway
        self.wanted = {"lan": lan_target, "internet": internet_target}
        self.targets: dict[str, Target] = {}

    def _resolve(self) -> None:
        for name, wanted in self.wanted.items():
            address = self._gateway() if wanted == "auto" else wanted
            try:
                if address and ipaddress.ip_address(address).version == 4:
                    self.targets[name] = Target(name, address)
                    continue
            except ValueError:
                pass
            if wanted:
                log.warning("sonde %s : pas d'adresse IPv4 utilisable (%s) : sonde abandonnée", name, wanted)

    async def _probe(self, target: Target) -> None:
        target.seq += 1
        beat = [target.seq, self.mono_ms(), None]
        target.beats.append(beat)
        ok = False
        try:
            if target.method != "tcp":
                try:
                    ok = await self._icmp(target.address, target.seq)
                    if not target.method:
                        target.method = "icmp"
                        log.info("sonde %s (%s) : ping ICMP", target.name, target.address)
                except (PermissionError, OSError) as exc:
                    target.method = "tcp"
                    log.info("sonde %s (%s) : ICMP impossible (%s), connexion TCP toutes les 5 s",
                             target.name, target.address, exc)
            if target.method == "tcp":
                ok = await self._tcp(target.address, TCP_PORTS[target.name])
        except Exception:                          # une sonde ne fait jamais tomber la passerelle
            log.exception("sonde %s", target.name)
            ok = False
        now = self.mono_ms()
        if ok and now - beat[1] <= TIMEOUT_S * 1000 * (3 if target.method == "tcp" else 1.5):
            beat[2] = now
        wall = self.wall_ms()
        target.history.append((wall, beat[2] is not None))
        while target.history and wall - target.history[0][0] > KEEP_MS:
            target.history.popleft()
        while target.beats and now - target.beats[0][1] > 70_000:
            target.beats.popleft()

    async def run(self, stop: asyncio.Event) -> None:
        await asyncio.to_thread(self._resolve)
        if not self.targets:
            return
        pending: set[asyncio.Task] = set()
        next_at = {name: 0 for name in self.targets}
        while not stop.is_set():
            now = self.mono_ms()
            for name, target in self.targets.items():
                if now >= next_at[name]:
                    next_at[name] = now + (TCP_EVERY_MS if target.method == "tcp" else ICMP_EVERY_MS)
                    task = asyncio.create_task(self._probe(target))
                    pending.add(task)
                    task.add_done_callback(pending.discard)
            try:
                await asyncio.wait_for(stop.wait(), 0.25)
            except asyncio.TimeoutError:
                pass
        for task in list(pending):
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def snapshot(self) -> dict:
        """État des sondes pour state.net (opérateurs) et le fichier d'état."""
        out = {}
        for name, target in self.targets.items():
            beats = [calc.Beat(b[0], b[1], b[2]) for b in target.beats]
            s = calc.window_stats(beats, self.mono_ms(), 60_000)
            last = target.history[-1][1] if target.history else None
            out[name] = {"address": target.address, "method": target.method or None, "ok": last,
                         "loss_pct": s["loss_pct"], "rtt_ms": s["rtt_p95_ms"]}
        return out

    def facts(self, start_ms: int, end_ms: int) -> dict:
        """lan_probe_down / internet_probe_down pendant [début, fin] d'une coupure (au moins 2 essais, la moitié ratés)."""
        out = {}
        for name, key in (("lan", "lan_probe_down"), ("internet", "internet_probe_down")):
            target = self.targets.get(name)
            if target is None:
                continue
            tries = [ok for t, ok in target.history if start_ms <= t <= end_ms]
            if len(tries) >= 2:
                out[key] = tries.count(False) >= DOWN_RATIO * len(tries)
        return out
