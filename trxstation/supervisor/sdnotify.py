"""Protocole sd_notify (systemd) sans dépendance : READY=1 et WATCHDOG=1."""
from __future__ import annotations

import os
import socket


def sd_notify(state: str) -> bool:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address or not hasattr(socket, "AF_UNIX"):
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(state.encode())
        return True
    except OSError:
        return False
