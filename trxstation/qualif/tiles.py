# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Thèmes en tuiles de la valise (lot G2b, docs/qualification-gui-cahier-des-charges.md § 2).

Calculs PURS sur la session : chaque tuile reprend une action EXISTANTE de la valise (touche du menu, essai à la
main « 5.N », essai automatique « 8.N ») ; aucun essai nouveau. `plan` donne l'ordre de « Tout lancer » et de
« Relancer les échecs » ; les préalables (station arrêtée ou en marche, mot CHARGE) sont faits par `run_terrain`
au moment de chaque essai, jamais supposés.
"""
from __future__ import annotations

TODO, OK, PARTIAL, FAILED, ABSENT = "a_faire", "ok", "partiel", "echec", "absent"

NEEDS_STOPPED = ("1", "2", "3", "4", "6", "9", "r", "s", "f")   # station du PC ARRÊTÉE (rigctld de la valise)
NEEDS_LOAD = ("3", "5", "8")                                     # émission : charge fictive CONFIRMÉE (mot CHARGE)


def manual_keys() -> tuple[str, ...]:
    from .terrain import DRILLS
    return tuple(f"5.{n}" for n in range(1, len(DRILLS) + 1))


def auto_keys() -> tuple[str, ...]:
    from .autodrills import AUTO_DRILLS
    return tuple(f"8.{n}" for n in range(1, len(AUTO_DRILLS) + 1))


def themes() -> list[tuple[str, str, tuple[str, ...]]]:
    """(identifiant, branchement : sans / antenne / charge, touches dans l'ordre du déroulé conseillé)."""
    return [("releves", "sans", ("9", "1", "2", "4", "6")),
            ("reception", "antenne", ("r", "s", "f")),
            ("emission", "charge", ("3",)),
            ("auto", "charge", auto_keys()),
            ("main", "charge", manual_keys())]


ORDER_HEAD = ("9", "1", "r", "2", "s", "f", "3")
ORDER_TAIL = ("6",)


def order() -> tuple[str, ...]:
    """Déroulé conseillé (CLAUDE.md, valise) : 9, 1, r, 2, s, f, c, 3, d, 8, 5, a, 6 ; « 4 » est l'autre façon du
    « 3 » (sans émission) : jamais dans « Tout lancer »."""
    return ORDER_HEAD + auto_keys() + manual_keys() + ORDER_TAIL


def needs_stopped(key: str) -> bool:
    return key in NEEDS_STOPPED


def needs_running(key: str) -> bool:
    drill = drill_of(key)
    if drill is not None and drill.kind in ("startup", "auto_startup"):
        return False                             # le démarrage part d'une station arrêtée (l'essai s'en charge)
    return key.startswith(("5.", "8."))


def needs_load(key: str) -> bool:
    return key.split(".")[0] in NEEDS_LOAD


def drill_of(key: str):
    """Essai d'une touche « 5.N » / « 8.N », sinon None."""
    from .autodrills import AUTO_DRILLS
    from .terrain import DRILLS
    head, _, n = key.partition(".")
    drills = DRILLS if head == "5" else AUTO_DRILLS if head == "8" else None
    if drills is None or not n.isdigit() or not 1 <= int(n) <= len(drills):
        return None
    return drills[int(n) - 1]


QUALIF = {"validation_en_cours": OK, "incomplet": PARTIAL, "refuse": FAILED}
DRILL = {"reussi": OK, "echec": FAILED, "declare": PARTIAL, "incomplet": PARTIAL, "non_mesure": PARTIAL}


def item_state(session, key: str) -> tuple[str, str]:
    """(état, détail court) d'une tuile, d'après ce que la session a ENREGISTRÉ."""
    drill = drill_of(key)
    if drill is not None:
        rec = session.drills.get(drill.id)
        if not rec:
            return TODO, ""
        return DRILL.get(rec.get("result", ""), PARTIAL), str(rec.get("reason") or "")
    if key == "9":
        a = session.audio
        if not a:
            return TODO, ""
        if a.get("problems"):
            return FAILED, ", ".join(str(p.get("key", "")) for p in a["problems"])
        cap = a.get("capture") or {}
        return OK, f"{cap.get('name', '')} {cap.get('level_dbfs', '')} dBFS".strip()
    if key in ("1", "6"):
        snap = session.snapshots.get("avant" if key == "1" else "apres")
        return (OK, f"{snap.get('count', '?')} lectures") if snap else (TODO, "")
    if key == "2":
        return (OK, "") if any(r["kind"] == "explore" for r in session.runs) else (TODO, "")
    if key in ("3", "4"):
        runs = [r for r in session.runs if r["kind"] == "qualif" and bool(r.get("emission")) == (key == "3")]
        if not runs:
            return TODO, ""
        verdict = runs[-1].get("verdict")
        return QUALIF.get(verdict or "", PARTIAL), str(verdict or "")
    if key == "r":
        rx = session.reception
        if not rx:
            return TODO, ""
        state = {"ok": OK, "faible": PARTIAL, "sature": PARTIAL}.get(rx.get("verdict"), FAILED)
        freq = rx.get("freq_hz")
        where = f"{freq / 1e6:.3f} MHz {rx.get('mode', '')} " if freq else ""
        return state, f"{where}{rx.get('level_dbfs', '')} dBFS".strip()
    if key == "s":
        sp = session.spectrum
        if not sp:
            return TODO, ""
        v = sp.get("verdict")
        if v == "non_propose":
            return ABSENT, str(sp.get("detail", ""))
        return (OK, f"{sp.get('sweeps', 0)} balayages") if v == "ok" else (FAILED, str(sp.get("detail", v)))
    if key == "f":
        fil = session.filters
        if not fil:
            return TODO, ""
        v = fil.get("verdict")
        if v in ("non_propose", "pas_de_port"):
            return ABSENT, str(fil.get("detail", ""))
        return (OK, f"{fil.get('origine', '')} remis") if v == "ok" else (FAILED, str(fil.get("detail", v)))
    return TODO, ""


def tiles(session, label, running: bool | None = None) -> dict:
    """Tuiles pour la page : thèmes, essais (touche, état, détail, titre si c'est un essai), progression.
    `label(drill)` : titre de l'essai dans la langue de l'outil. `running` (station du PC en marche) : un essai lancé
    SEUL qui exige l'autre état est grisé dans la page (`bloque` : « marche » = à arrêter, « arretee » = à démarrer)
    ; « Tout lancer » et « Lancer le thème » font eux-mêmes ces préalables."""
    out, counted, done = [], 0, 0
    for theme, where, keys in themes():
        items = []
        for key in keys:
            state, detail = item_state(session, key)
            drill = drill_of(key)
            item = {"cle": key, "etat": state, "detail": detail[:160]}
            if running is True and needs_stopped(key):
                item["bloque"] = "marche"
            elif running is False and needs_running(key):
                item["bloque"] = "arretee"
            if drill is not None:
                item["texte"] = label(drill)
                item["essai"] = drill.id
                item["facultatif"] = _optional(key)
                if covered_by(key):
                    item["couvert"] = covered_by(key)
            items.append(item)
            if state != ABSENT and not item.get("facultatif") and key != "4":
                counted += 1
                done += state in (OK, PARTIAL, FAILED)
        out.append({"id": theme, "ou": where, "essais": items})
    return {"themes": out, "faits": done, "total": counted}


def plan(session, what: str) -> list[str]:
    """Touches à enchaîner : « tout » (pas encore faits), « echecs » (échec ou partiel), « theme:<id> » (tout le
    thème, essais facultatifs exceptés)."""
    if what.startswith("theme:"):
        wanted = what[len("theme:"):]
        keys = next((k for t, _, k in themes() if t == wanted), ())
        return [k for k in keys if k != "4" and not _optional(k) and item_state(session, k)[0] != ABSENT]
    pick = {"tout": (TODO,), "echecs": (FAILED, PARTIAL)}.get(what)
    if pick is None:
        return []
    # « echecs » reprend aussi un essai à la main facultatif ou couvert qui a ÉCHOUÉ : il pèse sur le verdict
    return [k for k in order() if (what == "echecs" or not _optional(k)) and item_state(session, k)[0] in pick]


def _optional(key: str) -> bool:
    """Essai à la main hors de « Tout lancer » : facultatif par nature (redémarrage du PC) ou FAIT PAR LA VALISE
    (essai automatique équivalent, `terrain.COVERED_BY`)."""
    from .terrain import COVERED_BY
    drill = drill_of(key)
    return bool(drill is not None and key.startswith("5.") and (drill.optional or drill.id in COVERED_BY))


def covered_by(key: str) -> str | None:
    """Touche « 8.N » de l'essai automatique qui fait la même chose qu'un essai à la main."""
    from .autodrills import AUTO_DRILLS
    from .terrain import COVERED_BY
    drill = drill_of(key)
    auto = COVERED_BY.get(drill.id) if drill is not None and key.startswith("5.") else None
    ids = [d.id for d in AUTO_DRILLS]
    return f"8.{ids.index(auto) + 1}" if auto in ids else None
