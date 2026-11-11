# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Actions de l'opérateur sur la présence de groupe (commande client `friends`, TRX Console menu 5.3).

Chaque argument est vérifié ici (le cœur ne contrôle que la forme : action connue, objet de 1 500 octets au plus).
Aucune action ne touche au poste : `qsy_mark` / `qsy_back` ne font que retenir puis rendre la fréquence et le mode
d'avant un QSY ; c'est le CLIENT qui envoie ensuite `set_mode` puis `set_frequency`, avec les règles habituelles.
"""
from __future__ import annotations

import json

from .codec import group_id_ok, station_id_ok
from .engine import ActionRefused, Engine

MUTATING = {"pseudo", "texts", "shack_for", "shack_cancel", "shack_rules", "create", "invite", "join", "leave",
            "delete", "exclude", "role", "share", "rename"}
MAX_VIEW_BYTES = 48 * 1024          # sous la limite d'un message du canal de données (64 ko)


def _str(args: dict, key: str, limit: int = 200) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not 0 < len(value) <= limit:
        raise ActionRefused("args", f"{key} : texte attendu")
    return value


def _int(args: dict, key: str, low: int, high: int, default: int | None = None) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ActionRefused("args", f"{key} : entier de {low} à {high} attendu")
    return value


def _group(args: dict) -> str:
    g = args.get("g")
    if not group_id_ok(g):
        raise ActionRefused("args", "g : identifiant de groupe attendu")
    return g


def _member(args: dict) -> str:
    m = args.get("member")
    if not station_id_ok(m):
        raise ActionRefused("args", "member : identifiant de station attendu")
    return m


def _bool(args: dict, key: str) -> bool:
    value = args.get(key, False)
    if not isinstance(value, bool):
        raise ActionRefused("args", f"{key} : true ou false")
    return value


def view(engine: Engine, g: str | None = None) -> dict:
    """Vue des groupes ; tronquée (membres retirés, `truncated`) si elle dépasse MAX_VIEW_BYTES : le client demande
    alors chaque groupe à part (`view` avec `g`)."""
    out = engine.view()
    if g is not None:
        out["groups"] = [x for x in out["groups"] if x["g"] == g]
        if not out["groups"]:
            raise ActionRefused("unknown_group", "groupe inconnu")
    if len(json.dumps(out, ensure_ascii=False)) > MAX_VIEW_BYTES:
        out["truncated"] = True
        for grp in out["groups"]:
            grp["count"] = len(grp["members"])
            grp["members"] = [m for m in grp["members"] if m["code"] != "O"][:10]
    return out


async def handle(engine: Engine, action: str, args: dict) -> dict:
    if not isinstance(args, dict):
        raise ActionRefused("args", "args : objet attendu")
    if action == "view":
        return view(engine, _group(args) if "g" in args else None)
    if action == "stats":
        g = _group(args)
        return {"g": g, "stats": engine.admin_stats(g)}
    if action == "pseudo":
        await engine.set_pseudo(_str(args, "pseudo", 40))
        return {"pseudo": engine.pseudo}
    if action == "texts":
        texts = args.get("texts")
        if not isinstance(texts, list):
            raise ActionRefused("args", "texts : liste de textes")
        engine.set_texts(texts)
        return {"texts": engine.store.data["texts"]}
    if action == "shack_for":
        engine.shack_for(_int(args, "minutes", 1, 1440) * 60)
        return {}
    if action == "shack_cancel":
        engine.shack_cancel()
        return {}
    if action == "shack_rules":
        rules = args.get("rules")
        if not isinstance(rules, list) or len(rules) > 7:
            raise ActionRefused("args", "rules : 7 plages au plus")
        until = args.get("suspended_until")
        if until is not None:
            until = _int(args, "suspended_until", 0, 2**40)
        engine.set_shack_rules(rules, until)
        return {}
    if action == "create":
        return {"g": await engine.create_group(_str(args, "name", 60))}
    if action == "invite":
        days = _int(args, "days", 1, 30, default=7)
        return {"url": engine.invitation(_group(args), ttl_s=days * 86400), "days": days}
    if action == "join":
        name = args.get("name", "")
        if not isinstance(name, str):
            raise ActionRefused("args", "name : texte")
        return {"g": await engine.join(_str(args, "url", 1000), name)}
    if action == "leave":
        await engine.leave(_group(args))
        return {}
    if action == "delete":
        await engine.delete_group(_group(args))
        return {}
    if action == "exclude":
        await engine.exclude(_group(args), _member(args))
        return {}
    if action == "role":
        role = args.get("role")
        if role not in ("a", "c", "m"):
            raise ActionRefused("args", "role : a, c ou m")
        await engine.set_role(_group(args), _member(args), role)
        return {}
    if action == "share":
        level = args.get("level")
        text = args.get("text")
        if text is not None and not isinstance(text, str):
            raise ActionRefused("args", "text : texte")
        engine.set_share(_group(args), level=level, text=text, invisible=_bool(args, "invisible"),
                         hide_absence=_bool(args, "hide_absence"))
        return {}
    if action == "rename":
        engine.rename(_group(args), _str(args, "name", 60))
        return {}
    if action == "qsy_mark":
        return {"back": engine.mark_qsy()}
    if action == "qsy_back":                         # rendu UNE fois : le client y retourne, puis on oublie
        back = engine.qsy_back
        engine.qsy_done()
        return {"back": back}
    raise ActionRefused("unknown_action", f"action inconnue : {action}")
