# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Calculs purs de l'écran partagé (docs/protocole-ecran.md § 2 et § 3) : aucun réseau, aucun terminal.

Code dicté : 10 caractères (alphabet de Crockford, 50 bits), MÊME forme que le code du monitoring (`monlink.invite`),
mais autre sel : scrypt(code, "orx-screen v1", N = 2^15, r = 8, p = 1) donne 80 octets :
- 0-15 : ADRESSE de la session sur le relais (32 caractères hexadécimaux) ;
- 16-47 : CLÉ des images (XChaCha20-Poly1305) ;
- 48-79 : JETON D'ÉCRITURE (le relais n'en garde que l'empreinte SHA-256 : seul l'opérateur écrit).

Image = zlib( genre (1 octet) ‖ colonnes (2) ‖ lignes (2) ‖ octets du terminal ), chiffrée avec, en données
associées, le domaine, l'adresse et le numéro d'image (le relais ne peut ni lire, ni changer l'ordre, ni rejouer).
"""
from __future__ import annotations

import hashlib
import re
import struct
import zlib
from dataclasses import dataclass

from ..monlink.invite import InviteRefused, display_code, new_code, normalize_code
from ..presence import crypto
from ..presence.codec import Malformed, b64d, b64e

__all__ = ["InviteRefused", "display_code", "new_code", "normalize_code", "ScreenKeys", "derive", "Frame",
           "FrameRefused", "seal_frame", "open_frame", "Tape", "KIND_OUTPUT", "KIND_KEYFRAME", "MAX_DATA"]

SCRYPT_SALT = b"orx-screen v1"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
FRAME_DOMAIN = b"orx-screen frame v1\0"
KIND_OUTPUT = 1           # octets à ajouter à l'écran
KIND_KEYFRAME = 2         # l'aidant efface son écran puis applique ces octets (écran complet)
MAX_DATA = 32 * 1024      # octets du terminal par image (avant compression)
MAX_BOX = 65536           # image chiffrée en base64url (relais : ScreenApi::MAX_FRAME)
_HEAD = struct.Struct(">BHH")


class FrameRefused(ValueError):
    """Image illisible : malformed, decrypt."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ScreenKeys:
    address: str              # 32 hex, seule chose que le relais voit
    key: bytes                # 32 octets, jamais envoyés
    write: bytes              # 32 octets, envoyés par l'opérateur seulement (jamais par l'aidant)

    @property
    def write_token(self) -> str:
        return b64e(self.write)

    @property
    def write_hash(self) -> str:
        return hashlib.sha256(self.write).hexdigest()

    def __repr__(self) -> str:
        return f"ScreenKeys({self.address})"


def derive(code: str) -> ScreenKeys:
    """Clés tirées du code tapé (casse libre, tirets et espaces ignorés) ; `InviteRefused("malformed")` sinon."""
    out = hashlib.scrypt(normalize_code(code).encode("ascii"), salt=SCRYPT_SALT, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                         maxmem=SCRYPT_MAXMEM, dklen=80)
    return ScreenKeys(out[:16].hex(), out[16:48], out[48:80])


@dataclass(frozen=True)
class Frame:
    kind: int
    cols: int
    rows: int
    data: bytes


def _aad(address: str, seq: int) -> bytes:
    return FRAME_DOMAIN + address.encode("ascii") + seq.to_bytes(8, "big")


def seal_frame(keys: ScreenKeys, seq: int, kind: int, cols: int, rows: int, data: bytes, *,
               nonce: bytes | None = None) -> str:
    if kind not in (KIND_OUTPUT, KIND_KEYFRAME) or not 1 <= seq < 2**53 or len(data) > MAX_DATA:
        raise ValueError("image invalide")
    plain = zlib.compress(_HEAD.pack(kind, max(0, min(cols, 65535)), max(0, min(rows, 65535))) + data, 6)
    nonce = nonce or crypto.random_nonce()
    box = b64e(nonce + crypto.xchacha_encrypt(keys.key, nonce, plain, _aad(keys.address, seq)))
    if len(box) > MAX_BOX:                       # impossible avec MAX_DATA (zlib ne grossit que de quelques octets)
        raise ValueError("image trop grande")
    return box


def open_frame(keys: ScreenKeys, seq: int, box_text: object) -> Frame:
    try:
        box = b64d(box_text)
        if len(box) < crypto.NONCE_SIZE + crypto.TAG_SIZE:
            raise Malformed("taille")
    except Malformed as exc:
        raise FrameRefused("malformed") from exc
    try:
        plain = crypto.xchacha_decrypt(keys.key, box[:crypto.NONCE_SIZE], box[crypto.NONCE_SIZE:],
                                       _aad(keys.address, seq))
    except crypto.DecryptError as exc:
        raise FrameRefused("decrypt") from exc
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(plain, _HEAD.size + MAX_DATA + 1)
        if inflater.unconsumed_tail or len(raw) < _HEAD.size or len(raw) > _HEAD.size + MAX_DATA:
            raise ValueError("taille")
    except (zlib.error, ValueError) as exc:
        raise FrameRefused("malformed") from exc
    kind, cols, rows = _HEAD.unpack_from(raw)
    if kind not in (KIND_OUTPUT, KIND_KEYFRAME):
        raise FrameRefused("malformed")
    return Frame(kind, cols, rows, raw[_HEAD.size:])


# ------------------------------------------------------------------ bande de l'écran (image complète à la demande)
_ALT_RE = re.compile(rb"\x1b\[\?(?:1049|1047|47)([hl])")
_CLEAR_RE = re.compile(rb"\x1b\[2J|\x1bc|\x1b\[\?(?:1049|1047|47)h")
RESET = b"\x1b[0m\x1b[?25h\x1b[H\x1b[2J"


class Tape:
    """Ce qu'il faut renvoyer pour reconstruire l'écran chez un aidant qui arrive (ou qui a perdu des images) :
    les octets écrits depuis le dernier effacement complet, 64 ko au plus, et l'état de l'écran secondaire (les
    applications plein écran comme l'écran plein de la console l'ouvrent une seule fois, au départ)."""

    def __init__(self, keep: int = 64 * 1024) -> None:
        self.keep = keep
        self.buf = bytearray()
        self.alt = False
        self._carry = b""

    def feed(self, data: bytes) -> None:
        scan = self._carry + data                     # une séquence coupée entre deux lectures
        for match in _ALT_RE.finditer(scan):
            self.alt = match.group(1) == b"h"
        self._carry = scan[-8:]
        start = len(self.buf)
        self.buf += data
        last = None
        for match in _CLEAR_RE.finditer(self.buf, max(0, start - 8)):
            last = match.start()
        if last is not None:
            del self.buf[:last]
        if len(self.buf) > self.keep:
            del self.buf[:len(self.buf) - self.keep]
            cut = self.buf.find(b"\n", 0, 4096)        # recommencer sur une ligne entière, pas au milieu d'une séquence
            if cut >= 0:
                del self.buf[:cut + 1]

    def keyframe(self) -> bytes:
        return (b"\x1b[?1049h" if self.alt else b"\x1b[?1049l") + RESET + bytes(self.buf)
