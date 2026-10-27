"""Protocole de commandes (JSON) : validation stricte de tout ce qui vient d'un client.

Client -> passerelle : {"cmd": <nom>, "id": <entier optionnel : numéro de la REQUÊTE, repris dans la réponse>, ...paramètres}
(l'identifiant d'une mémoire s'appelle « memory_id » : « id » est toujours le numéro de requête)
Passerelle -> client : {"type": "hello"|"state"|"result"|"error", ...}
Spectre HF : `hello.spectrum` = {source, level_max, max_fps} ou null ; `state.spectrum` = {state, code, message} ;
balayages en BINAIRE sur un second canal « spectrum » ouvert par le client (non ordonné, maxRetransmits 0),
format dans trxstation/spectrum/frame.py ; la passerelle n'y lit rien. Les balayages ne partent QUE pendant que
le client affiche la vue HF : `spectrum_watch {on: true}` à l'ouverture, `{on: false}` à la fermeture (défaut : rien).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from ...layout.catalog import MAX_PROFILE_BYTES
from ..cat.client import INT_LEVELS, POWER_STEPS, WRITABLE_FUNCS
from ..memories import ID_RE, validate_fields

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 2048
# Seule exception à la limite : l'enregistrement d'un profil de mise en page, reconnu à son début
# (le client envoie toujours « cmd » en premier) AVANT toute analyse JSON.
MAX_LAYOUT_MESSAGE_BYTES = MAX_PROFILE_BYTES + 1024
LAYOUT_SAVE_PREFIX = '{"cmd":"layout_save"'
MODE_RE = re.compile(r"^[A-Za-z0-9\-]{1,16}$")
COMMANDS = ("toggle", "stop", "heartbeat", "set_frequency", "set_mode", "get_state",
            "set_squelch", "set_function", "set_level", "memory_save", "memory_delete", "memory_recall",
            "layout_get", "layout_save", "layout_reset", "spectrum_set", "spectrum_watch", "beeps_set")
SPECTRUM_SETTINGS = ("mode", "span", "ref", "speed")   # valeurs vérifiées par la liste fermée de spectrum/civ.py


class ProtocolError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Command:
    name: str
    id: int | None = None
    params: dict = field(default_factory=dict)


def _int(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ProtocolError("invalid_params", f"{name} doit être un entier entre {low} et {high}")
    return value


def _memory_id(value) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ProtocolError("invalid_params", "identifiant de mémoire invalide")
    return value


def parse_command(raw: str | bytes) -> Command:
    if len(raw) > MAX_MESSAGE_BYTES:
        head = raw[:len(LAYOUT_SAVE_PREFIX)]
        head = head.decode("utf-8", "replace") if isinstance(head, bytes) else head
        if len(raw) > MAX_LAYOUT_MESSAGE_BYTES or head != LAYOUT_SAVE_PREFIX:
            raise ProtocolError("too_large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError("bad_json") from None
    if not isinstance(data, dict):
        raise ProtocolError("bad_message", "un objet JSON est attendu")
    name = data.get("cmd")
    if name not in COMMANDS:
        raise ProtocolError("unknown_command", str(name)[:40])
    ident = data.get("id")
    if ident is not None:
        ident = _int(ident, "id", 0, 2**31 - 1)
    params: dict = {}
    if name == "set_frequency":
        params["hz"] = _int(data.get("hz"), "hz", 1, 10_000_000_000)
    elif name == "set_mode":
        mode = data.get("mode")
        if not isinstance(mode, str) or not MODE_RE.fullmatch(mode):
            raise ProtocolError("invalid_params", "mode invalide")
        params["mode"] = mode
        params["passband"] = _int(data.get("passband", 0), "passband", 0, 20_000)
    elif name == "set_squelch":
        value = data.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ProtocolError("invalid_params", "value doit être un nombre entre 0 et 1")
        params["value"] = float(value)
    elif name == "set_function":
        if data.get("name") not in WRITABLE_FUNCS:
            raise ProtocolError("invalid_params", "name doit être l'une des fonctions : " + ", ".join(WRITABLE_FUNCS))
        if not isinstance(data.get("on"), bool):
            raise ProtocolError("invalid_params", "on doit valoir true ou false")
        params["name"], params["on"] = data["name"], data["on"]
    elif name == "set_level":
        level, value = data.get("name"), data.get("value")
        if level == "RFPOWER":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or round(float(value), 3) not in POWER_STEPS:
                raise ProtocolError("invalid_params", "value doit être l'une des puissances : " + ", ".join(str(round(p * 100)) for p in POWER_STEPS) + " % (0.05 à 1)")
            params["name"], params["value"] = level, float(value)
        elif level in INT_LEVELS:
            low, high = INT_LEVELS[level]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ProtocolError("invalid_params", f"value doit être un entier entre {low} et {high}")
            params["name"], params["value"] = level, value
        else:
            raise ProtocolError("invalid_params", "name doit être l'un des niveaux : RFPOWER, " + ", ".join(INT_LEVELS))
    elif name == "memory_save":
        try:
            params["name"], params["hz"], params["mode"], params["favorite"] = validate_fields(
                data.get("name"), data.get("hz"), data.get("mode"), data.get("favorite", False))
        except ValueError as exc:
            raise ProtocolError("invalid_params", str(exc)) from None
        params["memory_id"] = None if data.get("memory_id") is None else _memory_id(data.get("memory_id"))
    elif name in ("memory_delete", "memory_recall"):
        params["memory_id"] = _memory_id(data.get("memory_id"))
    elif name == "spectrum_set":
        setting, value = data.get("name"), data.get("value")
        if setting not in SPECTRUM_SETTINGS:
            raise ProtocolError("invalid_params", "name doit être l'un des réglages : " + ", ".join(SPECTRUM_SETTINGS))
        if setting in ("mode", "speed"):
            if not isinstance(value, str) or len(value) > 16:
                raise ProtocolError("invalid_params", "value doit être un nom de réglage")
        elif setting == "span":
            value = _int(value, "value", 1, 1_000_000)
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 100:
            raise ProtocolError("invalid_params", "value doit être un niveau en dB")
        else:
            value = float(value)
        params["name"], params["value"] = setting, value
    elif name == "beeps_set":
        from ..audio.beeps import validate_changes
        changes = {k: v for k, v in data.items() if k not in ("cmd", "id")}
        try:
            params.update(validate_changes(changes))     # liste FERMÉE de réglages et de valeurs
        except ValueError as exc:
            raise ProtocolError("invalid_params", str(exc)) from exc
    elif name == "spectrum_watch":
        if not isinstance(data.get("on"), bool):
            raise ProtocolError("invalid_params", "on doit valoir true ou false")
        params["on"] = data["on"]
    elif name == "layout_save":
        profile = data.get("profile")
        if not isinstance(profile, dict):
            raise ProtocolError("invalid_params", "profile doit être un objet (profil de mise en page)")
        params["profile"] = profile                         # validé en détail par la session (capacités du poste)
    return Command(name, ident, params)
