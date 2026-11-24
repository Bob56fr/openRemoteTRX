# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mise en forme : « signes vitaux » normalisés (voir `vitals_template`) -> état prêt à afficher pour la page.

Fonctions pures, sans entrée/sortie : testées seules (tests/test_view.py). Tous les textes sont rédigés ici ;
la page ne fait que les placer.
"""
from __future__ import annotations

import copy

# seuils orange / rouge, mêmes valeurs que la station (trxstation/hostinfo.py LIMITS)
LIMITS = {"cpu": (75.0, 90.0), "mem": (80.0, 90.0), "disk": (85.0, 95.0), "temp": (75.0, 85.0)}
TEMP_RANGE = (30, 95)
# bandes radioamateur (Hz) pour nommer la bande de la fréquence affichée
BANDS = [(1_810_000, 2_000_000, "160 m"), (3_500_000, 3_800_000, "80 m"), (5_351_500, 5_366_500, "60 m"),
         (7_000_000, 7_200_000, "40 m"), (10_100_000, 10_150_000, "30 m"), (14_000_000, 14_350_000, "20 m"),
         (18_068_000, 18_168_000, "17 m"), (21_000_000, 21_450_000, "15 m"), (24_890_000, 24_990_000, "12 m"),
         (26_965_000, 27_405_000, "CB"), (26_100_000, 28_000_000, "11 m"), (28_000_000, 29_700_000, "10 m"), (50_000_000, 54_000_000, "6 m"),
         (70_000_000, 70_500_000, "4 m"), (144_000_000, 146_000_000, "2 m"), (430_000_000, 440_000_000, "70 cm")]


def vitals_template() -> dict:
    """Forme des signes vitaux attendus par `build_state` (None = inconnu)."""
    return {
        "station": {"ok": False, "age_s": None, "version": None},
        "safe": {"active": False, "reason": None},
        "rig": {"model": None, "connected": None, "lost_s": None, "power": None, "tx_allowed": None,
                "freq_hz": None, "mode": None, "passband_hz": None, "strength_db": None,
                "vfo": None, "vfo_a_hz": None, "vfo_b_hz": None, "split": None,
                "rit_hz": None, "xit_hz": None,
                # None = fonction absente de ce poste ; valeurs déjà rédigées (nr_level "8", preamp "P1", agc "LENTE")
                "tuner": None, "nb": None, "nr": None, "nr_level": None, "notch": None,   # notch : "auto" / "manual" / False
                "att_db": None, "preamp": None, "agc": None, "comp": None, "comp_level": None,
                "vox": None, "squelch": None, "monitor": None,
                "power_set_w": None, "temp_c": None, "vd_v": None,
                "po_w": None, "swr": None, "alc_pct": None,
                "last_freq_hz": None, "last_mode": None},
        "ptt": {"tx": False, "elapsed_s": None, "tot_s": None, "warn_s": None, "owner": None,
                "local": False, "heartbeat_s": None},
        "operators": [],              # [{"id": "tablette", "name": "BOB", "tx": False}] : comptes opérateurs connectés
        "visitors": 0,
        "services": [],               # [{"name": "Passerelle", "level": "ok", "text": "OK"}]
        "sdr": None,                  # {"present", "model", "state", "freq_hz", "mode", "rate", "load_pct", "seen_ago_s"}
        "host": {"cpu": None, "mem": None, "disk": None, "temp": None, "uptime_s": None, "os": None},
        "internet": {"up": None, "ms": None},
    }


def merge(base: dict, data: dict) -> dict:
    """Recouvre le modèle par les valeurs lues (clés inconnues ignorées)."""
    out = copy.deepcopy(base)
    for k, v in (data or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
        elif k in out:
            out[k] = v
    return out


# ---------------------------------------------------------------------- formats

def fmt_freq(hz: float | None) -> str | None:
    if hz is None:
        return None
    s = f"{int(round(hz)):,}".replace(",", ".")
    return s if hz >= 1_000_000 else "0." + s.rjust(7, "0")


def band_of(hz: float | None) -> str | None:
    if hz is None:
        return None
    return next((name for lo, hi, name in BANDS if lo <= hz <= hi), None)


def fmt_num(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


def fmt_uptime(sec: float | None) -> str | None:
    if sec is None:
        return None
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    return f"{d} j {h:02d} h" if d else f"{h} h {rem // 60:02d} min"


def fmt_ago(sec: float | None) -> str:
    if sec is None:
        return "—"
    if sec < 10:
        return f"{fmt_num(sec)} s"
    if sec < 120:
        return f"{int(sec)} s"
    if sec < 7200:
        return f"{int(sec // 60)} min"
    return f"{int(sec // 3600)} h"


def smeter(db: float | None) -> dict | None:
    """STRENGTH de Hamlib (dB par rapport à S9, 6 dB par point S) -> texte et part de la barre (S0 à S9+60)."""
    if db is None:
        return None
    if db <= 0:
        text = f"S{max(0, min(9, round(9 + db / 6)))}"
    else:
        text = f"S9+{int(round(db / 10) * 10)}" if db >= 5 else "S9"
    return {"text": text, "frac": round(max(0.0, min(1.0, (db + 54) / 114)), 3)}


def level_of(key: str, v: float | None) -> str:
    if v is None:
        return "ok"
    warn, crit = LIMITS[key]
    return "crit" if v >= crit else "warn" if v >= warn else "ok"


# ---------------------------------------------------------------------- morceaux

def functions(r: dict, tx: bool, known: bool) -> list[dict]:
    """Pastilles des fonctions : `on` vrai = libellé allumé ; valeur seulement quand elle dit quelque chose."""
    if not known:                              # poste injoignable : tout est gris, rien n'est affirmé
        names = ["VFO A", "VFO B", "Split", "Tuner", "RIT", "XIT", "NB", "NR", "Notch", "ATT", "Préamp", "AGC",
                 "Comp.", "VOX", "SQL", "Monit."]
        return [{"label": n, "on": False, "wide": n.startswith("VFO")} for n in names]
    vfo = (r["vfo"] or "A").upper()
    out = []
    for name in ("A", "B"):
        active = vfo == name
        hz = r["vfo_a_hz"] if name == "A" else r["vfo_b_hz"]
        if hz is None and active:
            hz = r["freq_hz"]
        label = f"VFO {name}" + ((" · TX" if tx else " · actif") if active else "")
        out.append({"label": label, "on": active, "tx": active and tx, "value": fmt_freq(hz), "wide": True})

    def flag(label, on, value=None, is_tx=False):
        if on is None:                         # fonction que ce poste ne déclare pas : pastille absente
            return
        out.append({"label": label, "on": bool(on), "value": value if on else None, "tx": bool(on) and is_tx})

    flag("Split", r["split"])
    flag("Tuner", r["tuner"])
    flag("RIT", r["rit_hz"] if r["rit_hz"] is None else bool(r["rit_hz"]), f"{r['rit_hz']:+d}" if r["rit_hz"] else None)
    flag("XIT", r["xit_hz"] if r["xit_hz"] is None else bool(r["xit_hz"]), f"{r['xit_hz']:+d}" if r["xit_hz"] else None)
    flag("NB", r["nb"])
    flag("NR", r["nr"], r["nr_level"])
    flag("Notch", r["notch"], {"auto": "AN", "manual": "MN"}.get(r["notch"]) if isinstance(r["notch"], str) else None)
    flag("ATT", r["att_db"] if r["att_db"] is None else bool(r["att_db"]), f"{r['att_db']:g} dB" if r["att_db"] else None)
    flag("Préamp", r["preamp"] if r["preamp"] is None else bool(r["preamp"]), r["preamp"] or None)
    flag("AGC", r["agc"] if r["agc"] is None else r["agc"] != "OFF", r["agc"] if r["agc"] != "OFF" else None)
    flag("Comp.", r["comp"], r["comp_level"], is_tx=tx)
    flag("VOX", r["vox"])
    flag("SQL", r["squelch"])
    flag("Monit.", r["monitor"])
    return out


def tiles(v: dict, mode: str) -> list[dict]:
    r, p = v["rig"], v["ptt"]
    w = lambda x: None if x is None else f"{x:.0f} W"
    ops = len(v["operators"])
    operators = {"label": "Opérateurs", "value": str(ops), "small": f"+{v['visitors']} visit." if v["visitors"] else None}
    temp = {"label": "Température poste", "value": "—" if r["temp_c"] is None else f"{r['temp_c']:.0f} °C"}
    if mode == "tx":
        return [
            {"label": "Puissance émise", "value": w(r["po_w"]) or "—",
             "small": f"/ {r['power_set_w']:.0f}" if r["power_set_w"] is not None else None},
            {"label": "ROS", "value": "—" if r["swr"] is None else fmt_num(r["swr"]),
             "level": "warn" if (r["swr"] or 0) >= 2 else None},
            {"label": "ALC", "value": "—" if r["alc_pct"] is None else f"{r['alc_pct']:.0f} %"},
            {"label": "Signal de vie", "kind": "text",
             "value": "Poste local" if p["local"] else "—" if p["heartbeat_s"] is None
             else ("OK · " if p["heartbeat_s"] < 1.5 else "Retard · ") + fmt_ago(p["heartbeat_s"]),
             "level": "warn" if (p["heartbeat_s"] or 0) >= 1.5 else None},
        ]
    if mode in ("rx", "off"):
        return [
            {"label": "Puissance réglée", "value": w(r["power_set_w"]) or "—"},
            {"label": "Tension poste", "value": "—" if r["vd_v"] is None else f"{fmt_num(r['vd_v'])} V"},
            temp, operators,
        ]
    return [                                   # mise en sécurité, poste ou station injoignable
        {"label": "Émission", "kind": "text", "value": "Bloquée", "level": "crit"},
        operators,
        {"label": "Alim. poste", "kind": "text", "value": {"on": "Allumé", "off": "Éteint"}.get(r["power"], "Inconnue"),
         "level": None if r["power"] in ("on", "off") else "warn"},
        temp,
    ]


def terminals(v: dict, accounts: list[dict]) -> list[dict]:
    """Comptes opérateurs de station.toml ([[clients]] hors visiteurs, un par appareil), dans l'ordre du fichier :
    pastille allumée si l'appareil est connecté, orange s'il émet. Libellé = identifiant du compte ; le pseudo, s'il
    existe, en petit (« émet » à sa place pendant l'émission). Un opérateur connecté inconnu de la liste est ajouté."""
    ops = [o for o in v["operators"] if o.get("id") or o.get("name")]
    out, used = [], set()
    for acc in accounts:
        account = str(acc.get("id") or "").strip()
        if not account:
            continue
        match = [o for o in ops if (o.get("id") or o.get("name")) == account]
        used.update(id(o) for o in match)
        state = "off" if not match else "tx" if any(o.get("tx") for o in match) else "on"
        pseudo = str(acc.get("pseudo") or "").strip() or None
        out.append({"name": account, "state": state, "note": "émet" if state == "tx" else pseudo})
    for o in ops:
        if id(o) not in used:
            state = "tx" if o.get("tx") else "on"
            out.append({"name": o.get("id") or o.get("name"), "state": state, "note": "émet" if state == "tx" else None})
    return out


def sdr_view(s: dict | None) -> dict | None:
    if s is None:
        return None
    model = s.get("model") or "SDR"
    if not s.get("present"):
        return {"title": f"{model} · absent", "level": "warn",
                "cells": [["État", "Débranché ?"], ["Écoute", "—"], ["Débit", "—"],
                          ["Vu il y a", fmt_ago(s.get("seen_ago_s")) if s.get("seen_ago_s") is not None else "—"]]}
    states = {"running": ("En marche", "ok"), "idle": ("En veille", "ok"), "waking": ("Réveil", "ok"),
              "error": ("En panne", "crit"), "stopped": ("Arrêté", "off")}
    text, level = states.get(s.get("state"), (s.get("state") or "—", "ok"))
    listen = fmt_freq(s.get("freq_hz"))
    listen = (listen[:-4] if listen else "—") + (f" {s['mode']}" if s.get("mode") and listen else "")
    return {"title": f"{model} · présent", "level": level,
            "cells": [["État", text], ["Écoute", listen], ["Débit", s.get("rate") or "—"],
                      ["Charge", "—" if s.get("load_pct") is None else f"{s['load_pct']:.0f} %"]]}


# ---------------------------------------------------------------------- ensemble

def build_state(v: dict, history_info: dict, cfg: dict) -> dict:
    """`history_info` : {"internet_pct", "alerts_warn", "alerts_crit"} ; `cfg` : {"station_name", "accounts", "version"}
    (accounts : [{"id", "pseudo"}] des comptes opérateurs de station.toml)."""
    st, r, p, safe = v["station"], v["rig"], v["ptt"], v["safe"]
    known = st["ok"] and r["connected"] is True and not safe["active"]
    if not st["ok"]:
        mode, mode_text = "nolink", "STATION MUETTE"
    elif safe["active"]:
        mode, mode_text = "safe", "MISE EN SÉCURITÉ"
    elif p["tx"]:
        mode, mode_text = "tx", "ÉMISSION"
    elif r["power"] == "off":
        mode, mode_text = "off", "POSTE ÉTEINT"
    else:
        mode, mode_text = "rx", "RÉCEPTION"

    banner = None
    if not st["ok"]:
        banner = {"level": "crit", "title": "Station muette.",
                  "text": "Aucun état de la passerelle reçu" + (f" depuis {fmt_ago(st['age_s'])}." if st["age_s"] else ".")
                  + " Le superviseur reste seul juge de l'émission."}
    elif safe["active"]:
        banner = {"level": "crit", "title": "Réception seule.",
                  "text": (safe["reason"] or "La station est en mode sûr.") + " Intervention sur place requise."}
    elif r["connected"] is False:
        banner = {"level": "warn", "title": "Liaison CAT perdue.",
                  "text": f"Poste injoignable depuis {fmt_ago(r['lost_s'])}." if r["lost_s"] else "Poste injoignable."}

    # ligne d'état du poste
    model = r["model"] or "Poste"
    if not st["ok"]:
        status, rlevel = f"{model} · état inconnu", "off"
    elif r["connected"] is False:
        status, rlevel = f"{model} · CAT perdue" + (f" depuis {fmt_ago(r['lost_s'])}" if r["lost_s"] else ""), "crit"
    else:
        parts = [model, "CAT OK"]
        if mode == "tx":
            parts.append("fréquence et mode verrouillés")
        else:
            parts.append({"on": "allumé", "off": "éteint"}.get(r["power"], "alimentation inconnue"))
            if r["tx_allowed"] is not None:
                parts.append("émission autorisée" if r["tx_allowed"] else "réception seule")
        status, rlevel = " · ".join(parts), "ok" if r["power"] != "off" else "warn"

    freq_hz = r["freq_hz"] if known else None
    if known:
        if mode == "tx":
            who = "opérateur sur place" if p["local"] else (p["owner"] or "opérateur distant")
            detail = f"émet : {who}"
        else:
            bits = []
            if r["passband_hz"]:
                bits.append(f"filtre {fmt_num(r['passband_hz'] / 1000)} kHz")
            if band_of(freq_hz):
                bits.append(band_of(freq_hz))
            detail = " · ".join(bits)
    else:
        last = fmt_freq(r["last_freq_hz"] or r["freq_hz"])
        detail = f"dernière lecture {last} {r['last_mode'] or r['mode'] or ''}".strip() if last else ""

    tx = None
    if mode == "tx" and p["elapsed_s"] is not None and p["tot_s"]:
        tx = {"elapsed_s": p["elapsed_s"], "tot_s": p["tot_s"], "warn_s": p["warn_s"]}

    h = v["host"]
    cur = {}
    for key, unit in (("cpu", "%"), ("mem", "%"), ("temp", "°C")):
        val = h[key]
        cur[key] = {"text": "—" if val is None else f"{val:.0f} {unit}", "level": level_of(key, val)}
    ipct = history_info.get("internet_pct")
    cur["internet"] = {"text": "—" if ipct is None else f"{ipct:.0f} %",
                       "level": "crit" if v["internet"]["up"] is False else "ok"}
    aw, ac = history_info.get("alerts_warn", 0), history_info.get("alerts_crit", 0)
    cur["alerts"] = {"text": str(aw + ac), "level": "crit" if ac else "warn" if aw else "ok"}
    # pastille de l'en-tête PC : état ACTUEL seulement (les alertes des 24 h ont leur propre ligne)
    pc_level = max((cur[k]["level"] for k in ("cpu", "mem", "temp", "internet")), key=["ok", "warn", "crit"].index)
    title = " · ".join(x for x in (h["os"], f"en marche {fmt_uptime(h['uptime_s'])}" if h["uptime_s"] else None) if x)

    age = st["age_s"]
    foot_left = (f"État station reçu il y a {fmt_ago(age)}" if st["ok"]
                 else f"Aucun état station depuis {fmt_ago(age)}" if age is not None else "Aucun état station reçu")
    right = [f"openRemoteTRX v{st['version']}" if st["version"] else None, f"tableau v{cfg.get('version', '?')}"]
    if v["internet"]["ms"] is not None:
        right.insert(0, f"Internet {v['internet']['ms']:.0f} ms")

    return {
        "v": 1, "station_name": cfg.get("station_name") or "", "mode": mode, "mode_text": mode_text, "banner": banner,
        "tx": tx, "stale": not st["ok"],
        "rig": {"status_text": status, "level": rlevel, "freq_text": fmt_freq(freq_hz),
                "mode": r["mode"] if known else None, "detail_text": detail,
                "smeter": smeter(r["strength_db"]) if known and mode != "tx" else None,
                "functions": functions(r, mode == "tx", known), "tiles": tiles(v, mode)},
        "terminals": terminals(v, cfg.get("accounts") or []),
        "pc": {"title": title, "level": pc_level, **cur, "services": v["services"]},
        "sdr": sdr_view(v["sdr"]),
        "foot_left": foot_left, "foot_right": " · ".join(x for x in right if x),
    }


def history_view(h: dict) -> dict:
    return {**h, "thresholds": {k: LIMITS[k][0] for k in ("cpu", "mem", "temp")}, "temp_range": list(TEMP_RANGE)}
