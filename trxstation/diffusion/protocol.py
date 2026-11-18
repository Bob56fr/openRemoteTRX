# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Protocole de diffusion station <-> serveur, calculs purs (docs/protocole-diffusion.md).

- Son : protocole source d'Icecast, `PUT` en FLUX BRUT (sans chunked, comme libshout) en TLS sur le port des
  sources ; Icecast 2.4 ne comprend pas le chunked (essai du 2026-11-17).
- Métadonnées et mot de passe des auditeurs : `POST /api/v1/<station>/<action>` en HTTPS, signés
  `X-Orx-Signature` = HMAC-SHA256(meta_key, MÉTHODE \\n chemin \\n corps).
Tout ce que renvoie le serveur est une donnée non fiable (nombre d'auditeurs), jamais une commande.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Any

VERSION = 1
SIGNATURE_HEADER = "X-Orx-Signature"
ACCESS = ("prive", "public")
DEFAULT_ACCESS = "prive"                 # cahier § 1.5
CODECS = {"opus": "audio/ogg", "mp3": "audio/mpeg"}
MAX_BODY = 4096
CLOCK_WINDOW_MS = 120_000               # écart toléré par le serveur
META_MIN_INTERVAL_S = 1.0               # la station : au plus une fois par seconde (cahier § 7)
META_REFRESH_S = 30.0                   # et au moins toutes les 30 s pendant une diffusion (nombre d'auditeurs)
DEFAULT_HOURS = 1                       # cahier § 1.3 et § 5
MAX_HOURS = 24
BACKOFF_S = (2, 4, 8, 16, 32, 60)       # reconnexion de la source (cahier § 4)
LISTENER_PASSWORD_LEN = 12
MAX_LISTENERS_SANE = 10_000             # au-delà : réponse du serveur ignorée (donnée non fiable)

STATION_NAME = re.compile(r"^[a-z0-9-]{2,32}$")
LISTENER_USER = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
LISTENER_PASSWORD = re.compile(r"^[A-Za-z0-9]{8,64}$")
# Mot de passe généré : à dicter et à taper sur un téléphone, sans caractères ambigus (0 O 1 l I).
PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Métadonnées permises (cahier § 7), mêmes règles que le serveur. JAMAIS : adresse IP, nom de machine, locator
# précis, numéro de série. Ordre = ordre de la liste proposée à l'opérateur.
META_FIELDS: dict[str, tuple[Any, ...]] = {
    "pseudo": (str, 32),
    "indicatif": (str, 16),
    "frequence_hz": (int, 0, 300_000_000_000),
    "mode": (str, 12),
    "bande": (str, 12),
    "tx": (bool,),
    "s_metre": (str, 8),
    "filtre": (str, 8),                 # largeur du filtre, ex. « 2.4k »
    "voyants": (list,),                 # [[texte, allumé], …] : P.AMP, ATT, RIT, ΔTX, SPLIT, NOTCH, NB, NR (§ 3.1)
    "s": (list,),                       # S-mètre des dernières secondes : [[âge ms, dB / S9, squelch ouvert], …]
    "message": (str, 140),
}
# Champs que l'opérateur coche ; « s » suit « s_metre » (jamais coché seul).
CHOICE_FIELDS = tuple(k for k in META_FIELDS if k != "s")
# Décision de l'utilisateur du 2026-11-18 (étape 248, à la place de « pseudo seul » du cahier § 1.6) : TOUT par
# défaut, comme le POC ; l'opérateur décoche au lancement. Un champ sans valeur (indicatif, message) n'est pas envoyé.
DEFAULT_META_CHOICE = CHOICE_FIELDS
MAX_VOYANTS, MAX_VOYANT_TEXT = 10, 12
MAX_S_POINTS, MAX_S_AGE_MS = 40, 10_000
# Raison d'un silence VOULU, toujours envoyée (aucune donnée personnelle), pour l'expliquer aux auditeurs (§ 3.1) :
# réception hors des bandes autorisées, opérateur en émission sans sa voix diffusée, plus de son du poste.
SILENCE_REASONS = ("hors_bandes", "emission", "pas_de_son")


class DiffusionRefused(ValueError):
    """Valeur refusée avant tout envoi (la station ne transmet jamais une donnée que le serveur refuserait)."""


# ------------------------------------------------------------------ noms et adresses
def check_station(name: str) -> str:
    if not isinstance(name, str) or not STATION_NAME.match(name):
        raise DiffusionRefused("nom de station : 2 à 32 caractères a-z, 0-9, -")
    return name


def check_access(access: str) -> str:
    if access not in ACCESS:
        raise DiffusionRefused("accès : prive ou public")
    return access


def mount(station: str, access: str) -> str:
    return f"/{check_station(station)}-{check_access(access)}"


def listen_page(server: str, station: str) -> str:
    """Adresse à transmettre aux auditeurs (page du serveur : lecteur, métadonnées, connexion)."""
    return f"https://{server}/ecoute/{check_station(station)}"


def stream_url(server: str, station: str, access: str) -> str:
    """Adresse directe du flux (VLC, applications de radio)."""
    return f"https://{server}{mount(station, access)}"


def api_path(station: str, action: str) -> str:
    if action not in ("meta", "auditeur"):
        raise DiffusionRefused("action : meta ou auditeur")
    return f"/api/v1/{check_station(station)}/{action}"


# ------------------------------------------------------------------ son : requête source d'Icecast
def source_request(host: str, port: int, station: str, access: str, password: str, codec: str = "opus",
                   name: str = "") -> bytes:
    """En-têtes du `PUT` de la source ; le flux brut suit la ligne vide, sans fin (ni chunked ni longueur)."""
    if codec not in CODECS:
        raise DiffusionRefused("codec : opus ou mp3")
    if not password or any(c in password for c in "\r\n"):
        raise DiffusionRefused("mot de passe source vide ou invalide")
    name = "".join(c for c in name if c.isprintable())[:64]
    cred = base64.b64encode(f"source:{password}".encode()).decode()
    lines = [
        f"PUT {mount(station, access)} HTTP/1.1",
        f"Host: {host}:{int(port)}",
        f"Authorization: Basic {cred}",
        f"Content-Type: {CODECS[codec]}",
        "Ice-Public: 0",                         # jamais dans un annuaire (cahier § 6)
        f"Ice-Name: {name}" if name else "Ice-Name: openRemoteTRX",
        "User-Agent: openRemoteTRX",
    ]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")


def source_reply_status(data: bytes) -> int | None:
    """Code de la première ligne d'Icecast (« HTTP/1.0 200 OK ») ; None si illisible."""
    line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace").split()
    if len(line) >= 2 and line[0].startswith("HTTP/") and line[1].isdigit():
        return int(line[1])
    return None


def backoff(attempt: int) -> int:
    """Attente avant le nouvel essai n° `attempt` (1, 2…) : 2, 4, 8… 60 s."""
    return BACKOFF_S[min(max(attempt, 1), len(BACKOFF_S)) - 1]


# ------------------------------------------------------------------ requêtes signées
def sign(key: bytes, method: str, path: str, body: bytes) -> str:
    return hmac.new(key, method.encode() + b"\n" + path.encode() + b"\n" + body, hashlib.sha256).hexdigest()


def check_meta(meta: Any) -> dict[str, Any]:
    if not isinstance(meta, dict):
        raise DiffusionRefused("métadonnées : objet attendu")
    clean: dict[str, Any] = {}
    for key, value in meta.items():
        rule = META_FIELDS.get(key)
        if rule is None:
            raise DiffusionRefused(f"métadonnée inconnue : {key}")
        if value is None:
            continue
        kind = rule[0]
        if kind is list:
            _check_list(key, value)
        elif kind is bool:
            if not isinstance(value, bool):
                raise DiffusionRefused(f"{key} : booléen attendu")
        elif kind is int:
            if isinstance(value, bool) or not isinstance(value, int) or not rule[1] <= value <= rule[2]:
                raise DiffusionRefused(f"{key} : entier de {rule[1]} à {rule[2]} attendu")
        else:
            if not isinstance(value, str) or len(value) > rule[1]:
                raise DiffusionRefused(f"{key} : texte de {rule[1]} caractères au plus")
            if any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 for c in value):
                raise DiffusionRefused(f"{key} : caractère de contrôle")
        clean[key] = value
    return clean


def _check_list(key: str, value: Any) -> None:
    if not isinstance(value, list):
        raise DiffusionRefused(f"{key} : liste attendue")
    if key == "voyants":
        if len(value) > MAX_VOYANTS:
            raise DiffusionRefused(f"voyants : {MAX_VOYANTS} au plus")
        for item in value:
            if (not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str)
                    or not 0 < len(item[0]) <= MAX_VOYANT_TEXT or not isinstance(item[1], bool)
                    or any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 for c in item[0])):
                raise DiffusionRefused(f"voyants : [texte de {MAX_VOYANT_TEXT} caractères au plus, booléen] attendu")
    else:                                    # « s »
        if len(value) > MAX_S_POINTS:
            raise DiffusionRefused(f"s : {MAX_S_POINTS} points au plus")
        for item in value:
            ok = (isinstance(item, list) and len(item) == 3
                  and isinstance(item[0], int) and not isinstance(item[0], bool) and 0 <= item[0] <= MAX_S_AGE_MS
                  and isinstance(item[1], (int, float)) and not isinstance(item[1], bool) and -80 <= item[1] <= 100
                  and (item[2] is None or isinstance(item[2], bool)))
            if not ok:
                raise DiffusionRefused(f"s : [âge de 0 à {MAX_S_AGE_MS} ms, dB de -80 à 100, booléen ou null] attendu")


def pick_meta(choice: tuple[str, ...] | list[str], values: dict[str, Any]) -> dict[str, Any]:
    """Seulement les champs choisis par l'opérateur (inconnus ignorés), valeurs absentes omises, puis vérifiées."""
    keys = [k for k in choice if k in CHOICE_FIELDS] + (["s"] if "s_metre" in choice else [])
    return check_meta({k: values[k] for k in keys if values.get(k) is not None})


def _body(obj: dict[str, Any]) -> bytes:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_BODY:
        raise DiffusionRefused("corps trop grand")
    return data


def meta_body(station: str, ts_ms: int, access: str, meta: dict[str, Any], silence: str | None = None) -> bytes:
    """`silence` : raison d'un silence voulu (SILENCE_REASONS), champ absent quand le son passe."""
    obj = {"v": VERSION, "station": check_station(station), "ts_ms": int(ts_ms), "acces": check_access(access),
           "meta": check_meta(meta)}
    if silence is not None:
        if silence not in SILENCE_REASONS:
            raise DiffusionRefused("silence : " + ", ".join(SILENCE_REASONS))
        obj["silence"] = silence
    return _body(obj)


def listener_body(station: str, ts_ms: int, user: str, password: str) -> bytes:
    if not isinstance(user, str) or not LISTENER_USER.match(user):
        raise DiffusionRefused("identifiant des auditeurs : 1 à 32 caractères A-Z a-z 0-9 . _ -")
    if not isinstance(password, str) or not LISTENER_PASSWORD.match(password):
        raise DiffusionRefused("mot de passe des auditeurs : 8 à 64 lettres ou chiffres")
    return _body({"v": VERSION, "station": check_station(station), "ts_ms": int(ts_ms),
                  "user": user, "password": password})


def signed_headers(key: bytes, path: str, body: bytes) -> dict[str, str]:
    return {"Content-Type": "application/json", SIGNATURE_HEADER: sign(key, "POST", path, body)}


def next_ts_ms(now_ms: int, last_ms: int) -> int:
    """`ts_ms` strictement croissant (le serveur refuse un ts_ms déjà vu : 409), même si l'horloge recule."""
    return max(int(now_ms), last_ms + 1)


def parse_meta_reply(obj: Any) -> dict[str, int] | None:
    """Nombre d'auditeurs renvoyé par le serveur, vérifié (donnée non fiable) ; None si absent ou incohérent."""
    if not isinstance(obj, dict) or obj.get("ok") is not True:
        return None
    counts = obj.get("auditeurs")
    if not isinstance(counts, dict):
        return None
    out = {}
    for access in ACCESS:
        n = counts.get(access)
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= MAX_LISTENERS_SANE:
            return None
        out[access] = n
    return out


# ------------------------------------------------------------------ durée et mot de passe
def check_hours(hours: int | None) -> int | None:
    """Durée choisie au lancement : 1 à 24 h, ou None = sans limite (cahier § 5)."""
    if hours is None:
        return None
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= MAX_HOURS:
        raise DiffusionRefused(f"durée : 1 à {MAX_HOURS} heures, ou sans limite")
    return hours


def end_time(start: float, hours: int | None) -> float | None:
    hours = check_hours(hours)
    return None if hours is None else start + hours * 3600


def new_listener_password(rand: secrets.SystemRandom | None = None) -> str:
    r = rand or secrets.SystemRandom()
    return "".join(r.choice(PASSWORD_ALPHABET) for _ in range(LISTENER_PASSWORD_LEN))


def masked(secret: str) -> str:
    """Un secret n'est jamais affiché en entier (cahier § 3)."""
    return "…" if len(secret) < 8 else secret[:2] + "…" + secret[-2:]
