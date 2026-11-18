# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Son de la passerelle vers le module « diffusion » : paquets UDP en 127.0.0.1 (l'inverse du son du SDR, étape 190).

Paquet : « ORDA », jeton (16 octets, dérivé du secret du module : un autre programme local ne peut rien injecter),
numéro (uint32 little-endian), 960 échantillons int16 (20 ms, mono, 48 kHz). Infos du poste (étape 248) : « ORDI », même jeton,
puis un objet JSON (S-mètre, squelch, filtre, voyants : diffusion/rigview.py), toutes les 200 ms pendant la diffusion. Calculs purs : la passerelle et le
module importent ce fichier ; lui n'importe ni l'un ni l'autre.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import struct

MAGIC = b"ORDA"
INFO_MAGIC = b"ORDI"
MAX_INFO_BYTES = 1200
TOKEN_BYTES = 16
BLOCK = 960
PCM_BYTES = 2 * BLOCK
PACKET_BYTES = 4 + TOKEN_BYTES + 4 + PCM_BYTES
SILENCE = bytes(PCM_BYTES)


def audio_token(module_secret: str | bytes) -> bytes:
    """Jeton des paquets, dérivé du secret du module (modules/keys.py : texte) ; la passerelle et le module le
    dérivent chacun de la même clé de la station."""
    key = module_secret.encode() if isinstance(module_secret, str) else module_secret
    return hmac.new(key, b"diffusion-audio", hashlib.sha256).digest()[:TOKEN_BYTES]


def pack(token: bytes, seq: int, pcm: bytes) -> bytes:
    if len(token) != TOKEN_BYTES or len(pcm) != PCM_BYTES:
        raise ValueError("jeton ou bloc de son de mauvaise taille")
    return MAGIC + token + struct.pack("<I", seq & 0xFFFFFFFF) + pcm


def unpack(token: bytes, packet: bytes) -> tuple[int, bytes] | None:
    """(numéro, PCM) d'un paquet valide ; None pour tout le reste (taille, marque, jeton)."""
    if len(packet) != PACKET_BYTES or packet[:4] != MAGIC:
        return None
    if not hmac.compare_digest(packet[4:4 + TOKEN_BYTES], token):
        return None
    seq = struct.unpack_from("<I", packet, 4 + TOKEN_BYTES)[0]
    return seq, packet[4 + TOKEN_BYTES + 4:]


def pack_info(token: bytes, info: dict) -> bytes:
    data = json.dumps(info, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(token) != TOKEN_BYTES or len(data) > MAX_INFO_BYTES:
        raise ValueError("jeton ou infos de mauvaise taille")
    return INFO_MAGIC + token + data


def unpack_info(token: bytes, packet: bytes) -> dict | None:
    """Objet d'un paquet d'infos valide ; None pour tout le reste (marque, jeton, JSON, taille)."""
    if packet[:4] != INFO_MAGIC or len(packet) > 4 + TOKEN_BYTES + MAX_INFO_BYTES:
        return None
    if not hmac.compare_digest(packet[4:4 + TOKEN_BYTES], token):
        return None
    try:
        obj = json.loads(packet[4 + TOKEN_BYTES:].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None
