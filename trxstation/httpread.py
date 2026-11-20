# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lecture COMPLÈTE et plafonnée du corps d'une réponse aiohttp.

`resp.content.read(n)` d'aiohttp ne renvoie que ce qui est DÉJÀ arrivé (au plus n octets), pas tout le corps :
une réponse de quelques centaines d'octets arrive d'un coup, une de 177 ko (boîte aux lettres du monitoring,
2026-11-19) était coupée au premier morceau, d'où « réponse illisible (HTTP 200) ». Lire ici jusqu'à la fin.
"""
from __future__ import annotations


async def read_capped(stream, limit: int) -> bytes:
    """Corps entier si sa taille ne dépasse pas `limit` ; sinon `limit + 1` octets au moins (trop grand)."""
    parts: list[bytes] = []
    size = 0
    while size <= limit:
        chunk = await stream.read(limit + 1 - size)
        if not chunk:
            break
        parts.append(chunk)
        size += len(chunk)
    return b"".join(parts)
