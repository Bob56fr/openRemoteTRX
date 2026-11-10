# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Primitives de la présence de groupe.

- Signatures : Ed25519 (le relais les vérifie avec `sodium_crypto_sign_verify_detached`).
- Chiffrement : XChaCha20-Poly1305 IETF, construit comme libsodium (`sodium_crypto_aead_xchacha20poly1305_ietf_*`) :
  sous-clé HChaCha20(clé, nonce[0:16]), puis ChaCha20-Poly1305 IETF avec le nonce 00000000 || nonce[16:24].
  `cryptography` ne le fournit pas : HChaCha20 est écrit ici et vérifié sur les vecteurs de
  draft-irtf-cfrg-xchacha (tests/test_presence_calc.py).
- Sceau d'une clé pour un membre : X25519 éphémère, HKDF-SHA256, XChaCha20-Poly1305.

Seules les stations chiffrent et déchiffrent ; le relais ne fait que vérifier des signatures et la preuve de travail.
"""
from __future__ import annotations

import os
import struct

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_SIZE = 32
NONCE_SIZE = 24
TAG_SIZE = 16
SIG_SIZE = 64
SEAL_OVERHEAD = 32 + NONCE_SIZE + TAG_SIZE       # clé éphémère + nonce + étiquette
SEAL_INFO = b"orx-presence seal v1"

_M = 0xFFFFFFFF


class DecryptError(ValueError):
    """Déchiffrement refusé (clé fausse, donnée altérée)."""


# ------------------------------------------------------------------ HChaCha20 / XChaCha20-Poly1305
def _rotl(v: int, c: int) -> int:
    return ((v << c) & _M) | (v >> (32 - c))


def _quarter(s: list[int], a: int, b: int, c: int, d: int) -> None:
    s[a] = (s[a] + s[b]) & _M; s[d] = _rotl(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & _M; s[b] = _rotl(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & _M; s[d] = _rotl(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & _M; s[b] = _rotl(s[b] ^ s[c], 7)


def hchacha20(key: bytes, nonce16: bytes) -> bytes:
    if len(key) != KEY_SIZE or len(nonce16) != 16:
        raise ValueError("HChaCha20 : clé de 32 octets et nonce de 16 octets")
    s = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574, *struct.unpack("<8L", key), *struct.unpack("<4L", nonce16)]
    for _ in range(10):
        _quarter(s, 0, 4, 8, 12); _quarter(s, 1, 5, 9, 13); _quarter(s, 2, 6, 10, 14); _quarter(s, 3, 7, 11, 15)
        _quarter(s, 0, 5, 10, 15); _quarter(s, 1, 6, 11, 12); _quarter(s, 2, 7, 8, 13); _quarter(s, 3, 4, 9, 14)
    return struct.pack("<8L", *s[0:4], *s[12:16])


def _xchacha(key: bytes, nonce: bytes) -> tuple[ChaCha20Poly1305, bytes]:
    if len(nonce) != NONCE_SIZE:
        raise ValueError("XChaCha20 : nonce de 24 octets")
    return ChaCha20Poly1305(hchacha20(key, nonce[:16])), b"\0\0\0\0" + nonce[16:]


def xchacha_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Chiffré suivi de l'étiquette de 16 octets (comme libsodium)."""
    aead, n12 = _xchacha(key, nonce)
    return aead.encrypt(n12, plaintext, aad)


def xchacha_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    aead, n12 = _xchacha(key, nonce)
    try:
        return aead.decrypt(n12, ciphertext, aad)
    except InvalidTag as exc:
        raise DecryptError("étiquette fausse") from exc


def random_nonce() -> bytes:
    return os.urandom(NONCE_SIZE)


def random_key() -> bytes:
    return os.urandom(KEY_SIZE)


# ------------------------------------------------------------------ Ed25519
def ed_public(seed: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()


def ed_sign(seed: bytes, data: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(seed).sign(data)


def ed_verify(public: bytes, signature: bytes, data: bytes) -> bool:
    if len(public) != 32 or len(signature) != SIG_SIZE:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, data)
    except (InvalidSignature, ValueError):
        return False
    return True


# ------------------------------------------------------------------ X25519 et sceau
def x_public(seed: bytes) -> bytes:
    return X25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()


def _seal_key(shared: bytes, eph_pub: bytes, recipient_pub: bytes) -> bytes:
    if shared == bytes(32):
        raise DecryptError("point X25519 de petit ordre")
    return HKDF(hashes.SHA256(), KEY_SIZE, salt=eph_pub + recipient_pub, info=SEAL_INFO).derive(shared)


def seal(plaintext: bytes, recipient_pub: bytes, aad: bytes, *, eph_seed: bytes | None = None,
         nonce: bytes | None = None) -> bytes:
    """Clé éphémère (32) || nonce (24) || chiffré + étiquette. `eph_seed`, `nonce` : vecteurs d'essai seulement."""
    eph = X25519PrivateKey.from_private_bytes(eph_seed) if eph_seed else X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes_raw()
    try:
        shared = eph.exchange(X25519PublicKey.from_public_bytes(recipient_pub))
    except ValueError as exc:
        raise DecryptError("clé publique X25519 refusée") from exc
    nonce = nonce or random_nonce()
    return eph_pub + nonce + xchacha_encrypt(_seal_key(shared, eph_pub, recipient_pub), nonce, plaintext, aad)


def unseal(box: bytes, recipient_seed: bytes, aad: bytes) -> bytes:
    if len(box) < SEAL_OVERHEAD:
        raise DecryptError("sceau trop court")
    me = X25519PrivateKey.from_private_bytes(recipient_seed)
    eph_pub, nonce, body = box[:32], box[32:32 + NONCE_SIZE], box[32 + NONCE_SIZE:]
    try:
        shared = me.exchange(X25519PublicKey.from_public_bytes(eph_pub))
    except ValueError as exc:
        raise DecryptError("clé éphémère refusée") from exc
    my_pub = me.public_key().public_bytes_raw()
    return xchacha_decrypt(_seal_key(shared, eph_pub, my_pub), nonce, body, aad)
