# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Masquage obligatoire avant tout envoi (cahier § 6) : un seul filtre pour tous les messages et toutes les lignes.

Appliqué dans la station surveillée, AVANT chiffrement et mise en file ; aucun profil ne le désactive. Deux niveaux :
1. règles PAR CHAMP (nom de la clé d'un objet JSON) : secrets -> `***`, identifiants de personnes -> alias stable par
   liaison (`user-1`, `visiteur-2`), numéros de série -> 3 premiers caractères ;
2. règles sur le TEXTE (toute chaîne, champs ordinaires compris) : adresses de messagerie, secrets écrits `clé=valeur`,
   URL réduites au domaine, adresses MAC tronquées, IPv4 / IPv6 (privées -> `LAN`, publiques -> hachage court propre à
   la liaison), dossiers personnels (`<user>`), numéros de série dans `/dev/serial/by-id`, UUID, mots connus de la station
   (nom de machine, comptes, sujet ntfy) donnés par l'appelant.
Les boucles locales (127.0.0.1, ::1) restent : utiles au dépannage (rigctld), sans rien révéler.
Fréquence et mode ne sont pas traités ici : c'est le profil (profiles.filter_rig).
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any

MASK = "***"
MAX_DEPTH = 32

_SECRET_KEY = re.compile(r"(?:^|[_\-.])(?:pass|password|passwd|pwd|passphrase|secret|secrets|token|tokens|key|keys|"
                         r"cle|psk|auth|authorization|cookie|session|private|signature|sig|hmac|seed|credential|"
                         r"credentials|otp|pin)(?:$|[_\-.])", re.I)
_PERSON_KEYS = {"owner": "user", "user": "user", "username": "user", "account": "user", "login": "user",
                "operator": "user", "by": "user", "client": "user", "clients": "user", "email": "user",
                "pseudo": "visiteur", "listener": "visiteur", "listeners": "visiteur", "visitor": "visiteur",
                "visitors": "visiteur"}
_SERIAL_KEY = re.compile(r"(?:^|_)(?:serial|serials|serial_number|sn|imei|uuid|station_id)(?:$|_)", re.I)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_INLINE_SECRET = re.compile(r"(?i)(?<![A-Za-z0-9])([A-Za-z0-9_.-]*?(?:password|passwd|pwd|passphrase|secret|token|"
                            r"api[_-]?key|key|psk|auth))"
                            r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&\"']+)")
_BEARER = re.compile(r"(?i)\b(authorization\s*:\s*(?:(?:bearer|basic|token)\s+)?|bearer\s+|basic\s+)"
                     r"[A-Za-z0-9._~+/=-]{6,}")
_URL = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{1,15})://(?:[^\s/@\"'<>]*@)?([A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])"
                  r"(?::\d{1,5})?(?:[/?#][^\s\"'<>]*)?")
_MAC = re.compile(r"(?<![0-9A-Fa-f:-])((?:[0-9A-Fa-f]{2}[:-]){2}[0-9A-Fa-f]{2})(?:[:-][0-9A-Fa-f]{2}){3}"
                  r"(?![0-9A-Fa-f:-])")
_IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.]|\.\d)")
_IPV6 = re.compile(r"(?<![\w:.])((?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4})(?:%[\w.-]+)?(?![\w:])")
_WIN_HOME = re.compile(r"(?i)\b([A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+)([^\\/\s\"'<>:]+)")
_UNIX_HOME = re.compile(r"(/(?:home|Users)/)([^/\s\"'<>:]+)")
_BY_ID = re.compile(r"(/dev/serial/by-(?:id|path)/[^\s\"']*)")
_BY_ID_SERIAL = re.compile(r"(?<=_)([0-9A-Za-z]{3})[0-9A-Za-z]{3,}(?=-if\d|-port|$)")   # dernier mot avant -if00
_UUID = re.compile(r"(?<![0-9a-fA-F-])([0-9a-fA-F]{3})[0-9a-fA-F]{5}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{12}(?![0-9a-fA-F-])")


class Redactor:
    """Un par liaison : les alias (`user-1`…) et les hachages d'IP publiques sont stables DANS la liaison seulement."""

    def __init__(self, link_salt: bytes, *, known: dict[str, str] | None = None) -> None:
        if len(link_salt) < 16:
            raise ValueError("sel de liaison de 16 octets au moins")
        self._salt = link_salt
        self._aliases: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}
        # Mots connus de la station (nom de machine, comptes, sujet ntfy…) -> remplacement ; les plus longs d'abord.
        pairs = [(w, r) for w, r in (known or {}).items() if isinstance(w, str) and len(w) >= 3]
        self._known = sorted(pairs, key=lambda p: -len(p[0]))

    # -------------------------------------------------------------- champs
    def alias(self, kind: str, value: object) -> str:
        key = (kind, str(value))
        if key not in self._aliases:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            self._aliases[key] = f"{kind}-{self._counts[kind]}"
        return self._aliases[key]

    def obj(self, value: Any, _depth: int = 0) -> Any:
        if _depth > MAX_DEPTH:
            return MASK
        if isinstance(value, dict):
            return {str(k): self._field(str(k), v, _depth + 1) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.obj(v, _depth + 1) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def _field(self, key: str, value: Any, depth: int) -> Any:
        if _SECRET_KEY.search(key):
            return value if value is None or isinstance(value, bool) else MASK
        person = _PERSON_KEYS.get(key.lower())
        if person is not None:
            return self._person(person, value, depth)
        if _SERIAL_KEY.search(key):
            return self._serial(value)
        return self.obj(value, depth)

    def _person(self, kind: str, value: Any, depth: int) -> Any:
        if value is None or isinstance(value, (bool, int, float)) or value == "":
            return value
        if isinstance(value, (list, tuple)):
            return [self._person(kind, v, depth + 1) for v in value]
        if isinstance(value, dict):
            return self.obj(value, depth)
        return self.alias(kind, value)

    @staticmethod
    def _serial(value: Any) -> Any:
        if isinstance(value, str) and len(value) > 3:
            return value[:3] + "…"
        if isinstance(value, (list, tuple)):
            return [Redactor._serial(v) for v in value]
        return value

    # -------------------------------------------------------------- texte
    def text(self, s: str) -> str:
        for word, repl in self._known:
            s = s.replace(word, repl)
        s = _URL.sub(self._url, s)                 # d'abord : `https://compte:secret@hôte` n'est pas une adresse mail
        s = _EMAIL.sub("<email>", s)
        s = _BEARER.sub(lambda m: m.group(1) + MASK, s)
        s = _INLINE_SECRET.sub(lambda m: m.group(1) + m.group(2) + MASK, s)
        s = _BY_ID.sub(lambda m: _BY_ID_SERIAL.sub(lambda h: h.group(1) + "…", m.group(1)), s)
        s = _UUID.sub(lambda m: m.group(1) + "…", s)
        s = _MAC.sub(lambda m: m.group(1) + ":xx:xx:xx", s)
        s = _IPV4.sub(self._ipv4, s)
        s = _IPV6.sub(self._ipv6, s)
        s = _WIN_HOME.sub(lambda m: m.group(1) + "<user>", s)
        s = _UNIX_HOME.sub(lambda m: m.group(1) + "<user>", s)
        return s

    def _url(self, m: re.Match) -> str:
        host = m.group(2)
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return f"{m.group(1)}://{host}"
        return f"{m.group(1)}://{self._ip(ip)}"

    def _ip(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
        if ip.is_loopback or ip.is_unspecified:
            return str(ip)
        if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "LAN"
        return "ip-" + hashlib.sha256(self._salt + b"ip\0" + ip.packed).hexdigest()[:6]

    def _ipv4(self, m: re.Match) -> str:
        try:
            return self._ip(ipaddress.IPv4Address(m.group(1)))
        except ValueError:
            return m.group(0)                  # 999.1.2.3 : pas une adresse

    def _ipv6(self, m: re.Match) -> str:
        candidate = m.group(1)
        if candidate.count(":") < 2:
            return m.group(0)
        try:
            ip = ipaddress.IPv6Address(candidate)
        except ValueError:
            return m.group(0)                  # 12:34:56 (heure) : pas une adresse
        return self._ip(ip)
