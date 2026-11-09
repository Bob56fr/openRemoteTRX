# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Indicateur près de l'horloge (Windows) : logique pure, portage de debian/gnome-extension/status.js.

Entrée : les fichiers publiés par la station (lecture seule). Sortie : voyant, texte court, lignes du menu.
L'indicateur ne commande JAMAIS la station : il lit seulement. Les deux versions (JavaScript pour GNOME, Python ici) sont
vérifiées contre les MÊMES exemples (tests/protocol/indicator_vectors.json) : arrondis et formats de nombres à la manière
de JavaScript (Math.round, toFixed, String(nombre)).
"""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

STALE_S = 5          # fichier d'état plus vieux : passerelle muette (elle écrit 4 fois par seconde)

MODE_LABELS = {"PKTUSB": "USB-D", "PKTLSB": "LSB-D", "PKTFM": "FM-D", "PKTAM": "AM-D", "FM-D": "FM-D", "AM-D": "AM-D"}
CUT_REASONS = {
    "tot": "durée maximale d'émission atteinte", "heartbeat": "perte du signal de vie du client", "toggle": "demande d'un client",
    "stop": "bouton STOP", "client_disconnected": "déconnexion du client émetteur", "frequency_changed": "fréquence modifiée sur le poste",
    "mode_changed": "mode modifié sur le poste pendant l'émission", "rig_reported_rx": "le poste est repassé en réception",
    "cat_down": "liaison avec le poste perdue", "rig_silent": "poste muet", "rig_overheat": "poste trop chaud",
    "ptt_write_failed": "échec de l'ordre d'émission", "rig_did_not_key": "le poste n'a pas émis", "shutdown": "arrêt de la station",
    "startup": "démarrage de la station", "spectrum_port_keyed": "port du spectre mal réglé",
}
LOCAL_REASONS = {"tx": "émission au micro du poste", "frequency": "fréquence changée sur le poste", "mode": "mode changé sur le poste"}
SPECTRUM = {"ok": "reçu", "waiting": "en attente de la réception", "starting": "démarrage", "error": "en panne"}
CLUSTER = {"green": "toutes les sources connectées", "orange": "sources en partie connectées", "red": "aucune source connectée"}
RANK = {"ok": 0, "info": 0, "warn": 1, "bad": 2}

# Où agir (renvois aux outils de la station) : TRX Console sous Debian, menu Démarrer sous Windows.
DEBIAN_HINTS = {"start": "TRX Console, menu 5 pour la démarrer", "safe": "TRX Console, menu 9", "update": "TRX Console, menu 10"}
WINDOWS_HINTS = {"start": "menu Démarrer > TRX distant > 3 - Démarrer la station",
                 "safe": "voir le diagnostic : menu Démarrer > TRX distant > 2", "update": "installer le nouveau paquet"}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _finite(v) -> bool:
    """Number.isFinite : un vrai nombre fini (ni texte, ni booléen)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)                       # Math.round : les demis vers +∞


def _to_fixed(x: float, decimals: int) -> str:
    """Number.prototype.toFixed : valeur binaire exacte, demis loin de zéro."""
    q = Decimal(x).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return f"{q:.{decimals}f}"


def _js_number(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


def _js_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return _js_number(v)
    if isinstance(v, dict):
        return "[object Object]"
    if isinstance(v, list):
        return ",".join(_js_str(x) for x in v)
    return str(v)


def text(value, maxlen: int = 80) -> str:
    """Texte venant d'un fichier : ramené à une ligne courte, sans caractère de contrôle."""
    return _CONTROL.sub(" ", _js_str(value)).strip()[:maxlen]


def mode_label(mode) -> str:
    return MODE_LABELS.get(mode) or (mode if isinstance(mode, str) else "?")


def clock(seconds) -> str:
    n = seconds if _finite(seconds) else 0
    s = max(0, _js_round(n))
    return f"{s // 60}:{s % 60:02d}"


def mhz(hz, decimals: int) -> str:
    return _to_fixed(hz / 1e6, decimals) if _finite(hz) and hz > 0 else "?"


def _width(hz) -> str:
    if not _finite(hz) or hz <= 0:
        return ""
    if hz >= 1000:
        return _to_fixed(hz / 1000, 0 if hz % 1000 == 0 else 1) + " kHz"
    return _js_number(hz) + " Hz"


def _num(v, default: float = 0.0) -> float:
    if _finite(v):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return math.nan
    return default if v is None else math.nan


def summarize(data, hints: dict[str, str] = DEBIAN_HINTS) -> dict:
    """data : { status, nowS, safeMode, cluster, update, stationId, version } (comme status.js).
    Renvoie { level: off | ok | tx | warn | safe | stale, label, lines: [{ key, text, level }] }."""
    lines: list[dict] = []

    def add(key: str, value, level: str = "info") -> None:
        lines.append({"key": key, "text": text(value, 120), "level": level or "info"})

    data = data if isinstance(data, dict) else {}
    status = data.get("status") if isinstance(data.get("status"), dict) else None
    now = _num(data.get("nowS"), 0.0)
    now = now if not math.isnan(now) else 0.0
    safe = text(data.get("safeMode"), 100) if data.get("safeMode") else ""
    level, label = "ok", "TRX"

    if safe:
        level, label = "safe", "MODE SÛR"
        add("Station", f"MODE SÛR : {safe} ({hints['safe']})", "bad")
    age = now - _num(status.get("written_at"), math.nan) if status else math.inf
    if not status:
        if not safe:
            level, label = "off", "TRX arrêtée"
        add("Station", f"arrêtée ({hints['start']})", "bad" if safe else "info")
    elif not age < STALE_S:
        if not safe:
            level, label = ("off", "TRX arrêtée") if age > 120 else ("stale", "TRX ?")
        add("Station", "arrêtée" if age > 120 else f"ne répond plus depuis {'NaN' if math.isnan(age) else _js_round(age)} s",
            "info" if age > 120 else "warn")
    fresh = bool(status) and age < STALE_S
    if fresh:
        ptt = status.get("ptt") if isinstance(status.get("ptt"), dict) else {}
        rig = status.get("rig") if isinstance(status.get("rig"), dict) else {}
        levels = rig.get("levels") if isinstance(rig.get("levels"), dict) else {}
        clients = [text(c, 32) for c in status["clients"]] if isinstance(status.get("clients"), list) else []
        if not safe:
            add("Station", "en marche", "ok")
        state = ptt.get("state")
        transmitting = bool(state) and state != "RX"
        if state == "TX":
            left = ptt.get("tot_remaining_s") if _finite(ptt.get("tot_remaining_s")) else None
            add("Émission", "ÉMISSION par " + (text(ptt.get("owner"), 32) or "?")
                + ("" if left is None else ", coupure automatique dans " + clock(left)), "bad")
            if not safe:
                level, label = "tx", "TX " + ("" if left is None else clock(left))
        elif transmitting:
            add("Émission", "prise d'émission en cours" if state == "KEYING" else "coupure en cours", "warn")
            if not safe:
                level, label = "tx", "TX"
        else:
            add("Émission", "réception", "ok")
        if rig.get("connected"):
            freq = re.sub(r"(\d)(\d{3})$", r"\1.\2", mhz(rig.get("frequency_hz"), 6))
            width = _width(rig.get("passband_hz"))
            add("Fréquence", f"{freq} MHz {mode_label(rig.get('mode'))}" + (f", filtre {width}" if width else ""), "info")
            if not transmitting and not safe:
                label = f"{mhz(rig.get('frequency_hz'), 3)} {mode_label(rig.get('mode'))}"
        else:
            err = rig.get("last_error")
            add("Poste", "liaison perdue" + (f" ({text(err, 60)})" if err else "") + " : poste éteint ou débranché ?", "bad")
        add("Clients web", ", ".join(clients) if clients else "aucun", "ok" if clients else "info")
        if _finite(ptt.get("local_remaining_s")):
            add("Sur place", LOCAL_REASONS.get(ptt.get("local_reason"), "action sur le poste") + " : PTT à distance bloqué "
                + ("pendant l'émission locale" if ptt.get("local_tx") else "encore " + clock(ptt["local_remaining_s"])), "warn")
        if ptt.get("fault"):
            add("Défaut", text(ptt["fault"], 60) + " : intervention sur la station requise", "bad")
        if ptt.get("last_cut_reason"):
            add("Dernière coupure", CUT_REASONS.get(ptt["last_cut_reason"]) or text(ptt["last_cut_reason"], 40), "info")
        temp = ptt.get("temp_c")
        temp_r = _js_round(temp) if _finite(temp) else 0
        if ptt.get("temp_alert") == "hot":
            add("Température", f"POSTE TROP CHAUD ({temp_r} °C) : émission coupée", "bad")
        elif ptt.get("temp_alert") == "warn":
            add("Température", f"poste chaud ({temp_r} °C)", "warn")
        elif _finite(temp):
            add("Température", f"{temp_r} °C", "info")
        vd = levels.get("VD_METER")
        if _finite(vd):
            add("Alimentation", _to_fixed(vd, 1) + " V", "warn" if vd < 12 else "info")
        sp = status.get("spectrum") if isinstance(status.get("spectrum"), dict) else {}
        sp_state = sp.get("state")
        if sp_state and sp_state != "off":
            add("Spectre HF", (SPECTRUM.get(sp_state) or text(sp_state, 20))
                + (f" ({_js_number(sp['fps'])} /s)" if sp_state == "ok" and _finite(sp.get("fps")) else "")
                + (" : " + text(sp["message"], 80) if sp_state == "error" and sp.get("message") else ""),
                "warn" if sp_state == "error" else "info")
    cluster = data.get("cluster")
    if isinstance(cluster, dict) and cluster.get("enabled") is not False and cluster.get("health") in CLUSTER:
        health = cluster["health"]
        add("Cluster DX", CLUSTER[health], "ok" if health == "green" else "warn" if health == "orange" else "bad")
    update = data.get("update")
    release = update.get("release") if isinstance(update, dict) else None
    if isinstance(release, dict) and release.get("version"):
        add("Mise à jour", f"version {text(release['version'], 20)} disponible ({hints['update']})", "warn")
    if data.get("version"):
        add("Version", text(data["version"], 20), "info")
    if data.get("stationId"):
        add("Identifiant", text(data["stationId"], 40), "info")

    # Une anomalie colore le voyant en orange, sauf émission ou mode sûr (prioritaires).
    worst = max((RANK.get(line["level"], 0) for line in lines), default=0)
    if level == "ok" and worst >= 1:
        level = "warn"
    return {"level": level, "label": text(label, 24), "lines": lines}
