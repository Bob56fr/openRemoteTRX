# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Jetons de session courts, signés HMAC-SHA256.

La passerelle délivre un jeton au client après le login. Un module qui reçoit
une connexion directe du client (le service vidéo) le fait vérifier par le
cœur via l'API interne : il ne connaît jamais le mot de passe ni la clé.

Format : base64url(json des revendications) "." base64url(signature)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass


class TokenError(Exception):
    """Jeton refusé. `code` vaut malformed, signature, expired ou revoked."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class SessionClaims:
    sid: str          # identifiant de session
    user: str         # utilisateur (login)
    exp: float        # expiration, secondes epoch


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


class TokenAuthority:
    """Émet, vérifie et révoque les jetons de session (côté passerelle)."""

    def __init__(self, key: bytes | None = None, ttl_s: float = 3600.0,
                 clock=time.time) -> None:
        self._key = key if key is not None else secrets.token_bytes(32)
        if len(self._key) < 16:
            raise ValueError("clé de signature trop courte (16 octets minimum)")
        self.ttl_s = float(ttl_s)
        self._clock = clock
        self._revoked: dict[str, float] = {}   # sid -> expiration

    def _sign(self, body: str) -> str:
        mac = hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest()
        return _b64e(mac)

    def issue(self, user: str, sid: str | None = None,
              ttl_s: float | None = None) -> str:
        claims = {
            "sid": sid or secrets.token_urlsafe(12),
            "user": user,
            "exp": self._clock() + (self.ttl_s if ttl_s is None else ttl_s),
        }
        body = _b64e(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
        return f"{body}.{self._sign(body)}"

    def verify(self, token: str) -> SessionClaims:
        if not isinstance(token, str) or token.count(".") != 1:
            raise TokenError("malformed", "jeton mal formé")
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, self._sign(body)):
            raise TokenError("signature", "signature invalide")
        try:
            data = json.loads(_b64d(body))
            claims = SessionClaims(sid=str(data["sid"]), user=str(data["user"]),
                                   exp=float(data["exp"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise TokenError("malformed", "contenu illisible") from exc
        now = self._clock()
        if claims.exp <= now:
            raise TokenError("expired", "jeton expiré")
        self._purge(now)
        if claims.sid in self._revoked:
            raise TokenError("revoked", "session fermée")
        return claims

    def revoke(self, sid: str, exp: float | None = None) -> None:
        """Révoque une session (déconnexion). Gardée jusqu'à son expiration."""
        self._revoked[sid] = exp if exp is not None else self._clock() + self.ttl_s

    def _purge(self, now: float) -> None:
        for sid in [s for s, e in self._revoked.items() if e <= now]:
            del self._revoked[sid]
