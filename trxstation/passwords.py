# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mots de passe des clients : hachage scrypt (bibliothèque standard), jamais stockés en clair.

Format stocké : scrypt$N$r$p$<sel base64>$<empreinte base64>. La vérification coûte ~100 ms par essai,
ce qui limite aussi la vitesse d'une attaque par devinette. Elle doit s'exécuter HORS de la boucle
asyncio (voir api/server.py) pour ne jamais retarder les surveillances de sécurité de l'émission.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_BYTES, KEY_BYTES = 2 ** 15, 8, 1, 16, 32
MAXMEM = 128 * 1024 * 1024
MIN_LENGTH = 12


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=MAXMEM, dklen=KEY_BYTES)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")          # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def parse_hash(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    """None si le format est invalide ou si les paramètres sont hors des bornes raisonnables."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        n, r, p = int(n), int(r), int(p)
        salt, digest = base64.b64decode(salt, validate=True), base64.b64decode(digest, validate=True)
    except (ValueError, AttributeError):
        return None
    if scheme != "scrypt" or not (2 ** 10 <= n <= 2 ** 20 and n & (n - 1) == 0 and 1 <= r <= 32 and 1 <= p <= 16):
        return None
    if len(salt) < 8 or len(digest) < 16 or 128 * n * r > MAXMEM:
        return None
    return n, r, p, salt, digest


def is_valid_hash(stored: str) -> bool:
    return parse_hash(stored) is not None


def verify_password(password: str, stored: str) -> bool:
    parsed = parse_hash(stored)
    if parsed is None or not isinstance(password, str):
        return False
    n, r, p, salt, digest = parsed
    return hmac.compare_digest(_derive(password, salt, n, r, p), digest)


def password_problem(password: str, login: str = "") -> str | None:
    """None si le mot de passe est acceptable, sinon la raison du refus (en français)."""
    if len(password) < MIN_LENGTH:
        return f"{MIN_LENGTH} caractères au minimum (une phrase de passe longue est préférable)"
    if len(set(password)) < 5:
        return "trop répétitif (au moins 5 caractères différents)"
    if login and login.lower() in password.lower():
        return "ne doit pas contenir l'identifiant"
    if password.strip() != password:
        return "ne doit pas commencer ni finir par une espace"
    return None


def generate_password() -> str:
    """Mot de passe aléatoire fort (≈ 128 bits), saisissable et copiable sans ambiguïté."""
    return secrets.token_urlsafe(16)
