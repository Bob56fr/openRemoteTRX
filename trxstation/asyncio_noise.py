"""Réduit le bruit asyncio sans masquer les vrais problèmes.

Ignore uniquement deux cas connus et sans gravité :
  * ConnectionResetError / BrokenPipeError sous Windows (Proactor) quand un correspondant se
    déconnecte brutalement ;
  * InvalidStateError levée par aiortc dans RTCPeerConnection.close() quand la connexion est
    fermée deux fois en même temps (elle est bien fermée dans les deux cas).
Toute autre exception reste signalée normalement.
"""
from __future__ import annotations

import asyncio
import os
import traceback


def is_aiortc_close_race(exc: object) -> bool:
    if not isinstance(exc, asyncio.InvalidStateError):
        return False
    frames = traceback.extract_tb(exc.__traceback__)
    return bool(frames) and os.path.basename(frames[-1].filename) == "rtcpeerconnection.py" \
        and frames[-1].name == "close"


def install_quiet_handler(loop: asyncio.AbstractEventLoop):
    previous = loop.get_exception_handler()

    def handler(lp: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)) or is_aiortc_close_race(exc):
            return
        if previous is not None:
            previous(lp, context)
        else:
            lp.default_exception_handler(context)

    loop.set_exception_handler(handler)
    return handler
