# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sonde rigctld indépendante (sockets bloquants, une connexion par requête).

Ce client n'a rien en commun avec celui de la passerelle : si l'un a un défaut, l'autre
reste capable de couper l'émission. Il ne sait faire qu'une chose d'actif : « T 0 ».
"""
from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

RETRY_PAUSE_S = 0.05     # avant le second essai d'une connexion refusée ou coupée


class RigctlError(Exception):
    pass


class _Closed(ConnectionError):
    """Connexion fermée par rigctld avant la réponse : rigctld injoignable, pas « PTT illisible »."""


@dataclass
class RigProbe:
    ok: bool                       # rigctld joignable et a répondu
    ptt: bool | None = None        # None = inconnu (non relisible)
    frequency_hz: int | None = None
    error: str = ""


class RigctlProbe:
    def __init__(self, host: str = "127.0.0.1", port: int = 4532, timeout: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep):
        self.host, self.port, self.timeout, self.sleep = host, port, timeout, sleep

    def _query(self, command: str) -> dict[str, str]:
        """Une requête ; une connexion refusée ou coupée (rigctld en referme parfois une, étape 103) est
        réessayée UNE fois. Jamais un délai dépassé (rigctld bloqué : la boucle ne doit pas s'allonger)."""
        try:
            return self._query_once(command)
        except ConnectionError:              # refusée, coupée (reset) ou fermée sans réponse
            self.sleep(RETRY_PAUSE_S)
            return self._query_once(command)

    def _query_once(self, command: str) -> dict[str, str]:
        with socket.create_connection((self.host, self.port), self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(f"+{command}\n".encode())
            buf = b""
            values: dict[str, str] = {}
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    raise _Closed("connexion fermée")
                buf += chunk
                lines = buf.decode(errors="replace").splitlines()
                if lines and lines[-1].startswith("RPRT"):
                    break
                if len(buf) > 65536:
                    raise RigctlError("réponse trop longue")
            for line in lines:
                if line.startswith("RPRT"):
                    code = int(line.split()[1])
                    if code != 0:
                        raise RigctlError(f"RPRT {code}")
                elif ": " in line:
                    key, value = line.split(": ", 1)
                    values[key.strip()] = value.strip()
            return values

    def read(self) -> RigProbe:
        try:
            try:
                ptt: bool | None = int(self._query("t").get("PTT", "")) != 0
            except RigctlError:
                ptt = None            # rigctld répond mais le PTT n'est pas lisible
            try:
                freq: int | None = int(float(self._query("f").get("Frequency", "")))
            except (RigctlError, ValueError):
                freq = None
            return RigProbe(True, ptt, freq)
        except (OSError, RigctlError, ValueError) as exc:
            return RigProbe(False, error=repr(exc))

    def force_rx(self) -> bool:
        """Envoie « T 0 » puis relit : True si le poste est bien repassé en réception."""
        try:
            self._query("T 0")
            return self.read().ptt is not True
        except (OSError, RigctlError, ValueError):
            return False
