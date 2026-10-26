"""Format des messages de l'API interne.

Une ligne = un message JSON (UTF-8), terminé par « \n ».

Module -> cœur
  {"type":"hello","module":"demo","secret":"…","api":"1.0"}
  {"type":"request","id":1,"op":"get_state"|"command"|"client_message"|"verify_token","args":{…}}
  {"type":"heartbeat","metrics":{…}}

Cœur -> module
  {"type":"welcome","api":"1.0","seq":42}
  {"type":"event","seq":43,"ts":1730000000.0,"name":"ptt","data":{"active":true}}
  {"type":"response","id":1,"ok":true,"result":…}
  {"type":"response","id":1,"ok":false,"error":"ptt_active","message":"…"}
  {"type":"error","code":"auth","message":"…"}   (puis fermeture)
"""

from __future__ import annotations

import json

MAX_LINE_BYTES = 64 * 1024


class ProtocolError(ValueError):
    pass


def encode(msg: dict) -> bytes:
    raw = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) >= MAX_LINE_BYTES:
        raise ProtocolError("message trop long")
    return raw + b"\n"


def decode(line: bytes) -> dict:
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("ligne illisible") from exc
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        raise ProtocolError("message sans type")
    return msg
