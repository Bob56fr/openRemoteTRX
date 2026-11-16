# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Requêtes signées au relais pour le monitoring (docs/protocole-monlink.md § 3).

MÊME signature que la présence (`"orx-relay v1\\n" || "POST\\n" || chemin || "\\n" || corps`, en-têtes `X-Orx-Station`
et `X-Orx-Signature`, champs `t` et `n`), mais :
- l'identifiant est celui du monitoring (`orx-monlink id v1`), que le relais vérifie sur les routes `/v1/mon/` ;
- le corps peut atteindre 72 ko (une enveloppe de 64 ko au plus et les champs de la requête).
"""
from __future__ import annotations

from urllib.parse import urlsplit

from ..presence import crypto
from ..presence.codec import Malformed, b64d, b64e, cjson, parse_json
from ..presence.wire import CLOCK_TOLERANCE_S, MAX_COUNTER, RequestRefused, signed_bytes

PREFIX = "/v1/mon/"
MAX_BODY = 72 * 1024
ROUTES = ("register", "invite/put", "invite/take", "pair", "allow", "revoke", "put", "get", "ack")


def base_prefix(relay_url: str) -> str:
    """Chemin du relais dans son site (`https://rf-diy.com/orx-relay/public` -> `/orx-relay/public`), signé lui aussi."""
    return urlsplit(relay_url).path.rstrip("/")


def build_request(identity, route: str, fields: dict, *, t: int, n: int,
                  prefix: str = "") -> tuple[str, bytes, dict[str, str]]:
    """(chemin, corps, en-têtes) d'une requête signée vers `<prefix>/v1/mon/<route>`.

    Le chemin SIGNÉ est le chemin complet de la requête, comme pour la présence : un relais installé dans un
    sous-dossier (`/orx-relay/public`) vérifie la signature sur ce chemin-là (défaut trouvé à l'étape 208 contre le
    relais en ligne : `prefix` absent = `bad_signature`)."""
    if route not in ROUTES:
        raise ValueError(f"route inconnue : {route}")
    if prefix and (not prefix.startswith("/") or prefix.endswith("/")):
        raise ValueError("préfixe : « /dossier » sans « / » final")
    path = prefix + PREFIX + route
    body = cjson({**fields, "t": t, "n": n})
    if len(body) > MAX_BODY:
        raise ValueError("requête trop grande")
    sig = identity.sign(signed_bytes(path, body))
    return path, body, {"Content-Type": "application/json", "X-Orx-Station": identity.station_id,
                        "X-Orx-Signature": b64e(sig)}


def verify_request(ed_pub: bytes, path: str, body: bytes, signature: str, *, now: float, last_n: int) -> dict:
    """Ce que fait le relais (en PHP), dans le même ordre que la présence : taille, signature, horloge, rejeu."""
    if len(body) > MAX_BODY:
        raise RequestRefused("too_large")
    if PREFIX not in path or path.rsplit(PREFIX, 1)[1] not in ROUTES:
        raise RequestRefused("unknown_route")
    try:
        sig = b64d(signature, crypto.SIG_SIZE)
    except Malformed as exc:
        raise RequestRefused("bad_signature") from exc
    if not crypto.ed_verify(ed_pub, sig, signed_bytes(path, body)):
        raise RequestRefused("bad_signature")
    try:
        obj = parse_json(body)
    except Malformed as exc:
        raise RequestRefused("malformed") from exc
    t, n = obj.get("t"), obj.get("n")
    for value in (t, n):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_COUNTER:
            raise RequestRefused("malformed")
    if abs(t - now) > CLOCK_TOLERANCE_S:
        raise RequestRefused("clock")
    if n <= last_n:
        raise RequestRefused("replay")
    return obj
