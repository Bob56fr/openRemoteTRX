# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Modèle d'affichage de trx-monitor : tout ce qui se calcule sans écran, donc testable.

Le moniteur est un LECTEUR. Il ne commande jamais le poste, sauf l'unique action « STOP TX »
(voir actions.py), qui ne peut que couper.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from ..status import GatewayStatus

ACTIVE_STATES = ("KEYING", "TX", "UNKEYING")

PTT_LABELS = {
    "RX": ("RÉCEPTION", "ok"),
    "KEYING": ("PRISE D'ÉMISSION", "bad"),
    "TX": ("ÉMISSION", "bad"),
    "UNKEYING": ("COUPURE EN COURS", "bad"),
}

CUT_REASONS = {
    "tot": "TOT dépassé",
    "heartbeat": "perte du heartbeat du client",
    "toggle": "demande d'un client",
    "client_disconnected": "déconnexion du client émetteur",
    "frequency_changed": "fréquence modifiée sur le poste",
    "rig_reported_rx": "le poste est repassé en réception",
    "cat_down": "liaison CAT perdue",
    "rig_silent": "poste muet",
    "rig_overheat": "poste trop chaud",
    "ptt_write_failed": "échec de l'ordre PTT",
    "rig_did_not_key": "le poste n'a pas émis",
    "shutdown": "arrêt de la passerelle",
    "startup": "démarrage de la passerelle",
}


@dataclass(frozen=True)
class Row:
    label: str
    text: str
    level: str = "info"        # ok | warn | bad | info | dim


@dataclass(frozen=True)
class Panel:
    key: str                   # radio | connexion | sante | materiel
    title: str
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class SystemInfo:
    temp_c: float | None = None
    load1: float | None = None
    mem_available_mb: float | None = None
    uptime_s: float | None = None


@dataclass(frozen=True)
class Snapshot:
    status: GatewayStatus | None
    gateway_fresh: bool
    stale_s: float | None
    safe_mode: str | None
    system: SystemInfo = SystemInfo()


# --------------------------------------------------------------------------- formats

def format_frequency(hz: int | None) -> str:
    return "--" if hz is None else f"{hz:,}".replace(",", " ") + " Hz"


def s_meter_text(db: int | None) -> str:
    """Hamlib STRENGTH : dB relatifs à S9 (S9 = 0 ; chaque point S = 6 dB)."""
    if db is None:
        return "--"
    if db >= 0:
        return "S9" if db == 0 else f"S9+{db} dB"
    return f"S{max(0, round(9 + db / 6))}"


def s_meter_bar(db: int | None, width: int = 20) -> str:
    if db is None:
        return "░" * width
    fraction = min(1.0, max(0.0, (db + 54) / 114))      # S0 (-54 dB) à S9+60
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return (f"{days} j " if days else "") + f"{hours} h {minutes:02d} min"


# --------------------------------------------------------------------------- panneaux

def _radio_panel(snap: Snapshot) -> Panel:
    status = snap.status
    if status is None:
        return Panel("radio", "Radio", (Row("Poste", "aucune donnée de la passerelle", "bad"),))
    ptt, rig = status.ptt, status.rig
    state = str(ptt.get("state", "?"))
    label, level = PTT_LABELS.get(state, (state, "warn"))
    if not snap.gateway_fresh:                      # donnée périmée : ne jamais l'afficher comme vivante
        label += " ?"
        level = "bad" if state in ACTIVE_STATES else "warn"
    rows = [Row("PTT", label, level)]
    swr = status.swr if isinstance(getattr(status, "swr", None), dict) else {}
    if swr.get("running"):                          # mesure de TOS : des émissions courtes vont se succéder
        steps = {"preparing": "préparation", "calibrating": "étalonnage", "measuring": "mesure", "restoring": "remise en état"}
        rows.append(Row("Mesure de TOS", f"{steps.get(swr.get('state'), swr.get('state'))} {swr.get('done', 0)}/{swr.get('total', 0)}"
                        f" ({swr.get('owner') or '?'}) : STOP TX l'arrête", "warn"))
    if state == "TX" and ptt.get("tot_remaining_s") is not None:
        rows.append(Row("TOT", f"{ptt['tot_remaining_s']:.0f} s restantes",
                        "warn" if ptt.get("tot_warning") else "info"))
    dim = "info" if snap.gateway_fresh else "dim"
    rows += [
        Row("Fréquence", format_frequency(rig.get("frequency_hz")), dim),
        Row("Mode", str(rig.get("mode") or "--"), dim),
        Row("Filtre", "--" if rig.get("passband_hz") is None else f"{rig['passband_hz']} Hz", dim),
        Row("S-mètre", f"{s_meter_text(rig.get('strength_db'))}  {s_meter_bar(rig.get('strength_db'))}", dim),
    ]
    return Panel("radio", "Radio", tuple(rows))


def _connexion_panel(snap: Snapshot) -> Panel:
    status = snap.status
    if status is None:
        return Panel("connexion", "Connexion", (Row("Clients", "--", "dim"),))
    clients = ", ".join(status.clients) if status.clients else "aucun"
    owner = status.ptt.get("owner")
    reason = str(status.ptt.get("last_cut_reason") or "")
    rows = [
        Row("Clients", clients, "info" if status.clients else "dim"),
        Row("Émetteur", str(owner) if owner else "—", "bad" if owner else "dim"),
        Row("Dernière coupure", CUT_REASONS.get(reason, reason) if reason else "—", "info" if reason else "dim"),
    ]
    return Panel("connexion", "Connexion", tuple(rows + _visitor_rows(status.presence)))


def _visitor_rows(presence: dict) -> list[Row]:
    """Visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md) : lecture seule, aucune action ici."""
    if not isinstance(presence, dict) or not presence:
        return []
    most = presence.get("max_listeners") or 0
    count = presence.get("listeners") or 0
    rows = [Row("Visiteurs", f"{count} / {most}" if most else "écoute fermée", "info" if count else "dim")]
    suspended = presence.get("suspended")
    if isinstance(suspended, dict):
        rows.append(Row("Écoute suspendue", str(suspended.get("reason", "surcharge"))
                        + (" (réouverture à la main)" if suspended.get("locked") else ""), "warn"))
    grace = presence.get("grace_remaining_s")
    if isinstance(grace, (int, float)):
        rows.append(Row("Opérateur absent", f"visiteurs déconnectés dans {grace:.0f} s", "warn"))
    for c in presence.get("connections", []) or []:
        if isinstance(c, dict):
            since = int(c.get("since_s") or 0)
            role = "Visiteur" if c.get("role") == "listener" else "Opérateur"
            rows.append(Row(role, f"{c.get('pseudo', '?')} ({c.get('id', '?')}, {c.get('source', '?')}, "
                                  f"{since // 3600:02d}:{since % 3600 // 60:02d})", "info"))
    return rows


def _sante_panel(snap: Snapshot) -> Panel:
    status = snap.status
    rows: list[Row] = []
    if status is None:
        rows.append(Row("Passerelle", "ABSENTE (aucun fichier d'état)", "bad"))
    elif not snap.gateway_fresh:
        age = "?" if snap.stale_s is None else f"{snap.stale_s:.0f}"
        rows.append(Row("Passerelle", f"FIGÉE depuis {age} s (pid {status.pid})", "bad"))
    else:
        rows.append(Row("Passerelle", f"active (pid {status.pid})", "ok"))
    if status is not None:
        connected = bool(status.rig.get("connected"))
        rows.append(Row("rigctld", "joint" if connected else "INJOIGNABLE", "ok" if connected else "bad"))
        if status.rig.get("last_error"):
            rows.append(Row("Dernière erreur", str(status.rig["last_error"])[:70], "warn"))
        fault = status.ptt.get("fault")
        rows.append(Row("Défaut PTT",
                        f"{fault} : retour RX impossible, intervention requise" if fault else "aucun",
                        "bad" if fault else "ok"))
    rows.append(Row("Mode sûr", f"ACTIF : {snap.safe_mode}" if snap.safe_mode else "non",
                    "bad" if snap.safe_mode else "ok"))
    return Panel("sante", "Santé", tuple(rows))


def _materiel_panel(snap: Snapshot) -> Panel:
    s = snap.system
    temp_level = "dim" if s.temp_c is None else "bad" if s.temp_c >= 80 else "warn" if s.temp_c >= 70 else "ok"
    return Panel("materiel", "Matériel", (
        Row("Température", "--" if s.temp_c is None else f"{s.temp_c:.0f} °C", temp_level),
        Row("Charge (1 min)", "--" if s.load1 is None else f"{s.load1:.2f}", "info"),
        Row("Mémoire libre", "--" if s.mem_available_mb is None else f"{s.mem_available_mb:.0f} Mo", "info"),
        Row("Disponibilité", format_duration(s.uptime_s), "info"),
    ))


def _db_bar(db: float | None, width: int = 16) -> str:
    """Barre de niveau de -60 dBFS (vide) à 0 dBFS (pleine)."""
    if db is None:
        return "░" * width
    filled = round(min(1.0, max(0.0, (db + 60) / 60)) * width)
    return "█" * filled + "░" * (width - filled)


def _spectrum_rows(snap: Snapshot) -> tuple[Row, ...]:
    """Spectre HF (second port CI-V) : rien s'il n'est pas configuré."""
    sp = {} if snap.status is None else getattr(snap.status, "spectrum", {}) or {}
    state = sp.get("state", "off")
    if state == "off":
        return ()
    if state == "ok":
        return (Row("Spectre HF", f"reçu sur {sp.get('port', '?')} ({sp.get('fps', '?')}/s)", "ok"),)
    if state == "error":
        return (Row("Spectre HF", "PROBLÈME DE CONFIGURATION : " + str(sp.get("message", ""))[:160], "bad"),)
    return (Row("Spectre HF", "en attente" if state == "waiting" else "vérification du port", "dim"),)


def _audio_panel(snap: Snapshot) -> Panel:
    status = snap.status
    audio = {} if status is None else status.audio
    if not audio:
        return Panel("audio", "Audio", (Row("Audio", "pas de donnée (audio inactif)", "dim"), *_spectrum_rows(snap)))
    rx, tx = audio.get("rx_db"), audio.get("tx_db")
    gate = bool(audio.get("gate_open"))
    dim = "info" if snap.gateway_fresh else "dim"
    return Panel("audio", "Audio", (
        Row("Réception", f"{rx:>4} dBFS  {_db_bar(rx)}" if rx is not None else "--", dim),
        Row("Émission", f"{tx:>4} dBFS  {_db_bar(tx)}" if tx is not None else "--", "bad" if gate else dim),
        Row("Porte micro", "OUVERTE (émission)" if gate else "fermée", "bad" if gate else "ok"),
        Row("Auditeurs", str(audio.get("listeners", 0)), "info"),
        Row("Trames", f"capturées {audio.get('rx_frames', 0)} · micro passées au poste {audio.get('tx_frames', 0)}", "dim"),
        Row("Pertes", f"RX {audio.get('rx_dropped', 0)}, TX hors propriétaire {audio.get('tx_dropped_not_owner', 0)}",
            "warn" if audio.get("rx_dropped", 0) or audio.get("tx_dropped_not_owner", 0) else "dim"),
        *_breizh_rows(snap),
        *_selcall_rows(snap),
        *_spectrum_rows(snap),
    ))


SELCALL_LABELS = {"disabled": ("désactivé", "dim"), "standby": ("veille", "info"), "open": ("OUVERT (appel reçu)", "warn")}


def _selcall_rows(snap: Snapshot) -> tuple[Row, ...]:
    """SELCALL ([selcall] enabled) : état et code armé, envoi en cours, dernier appel (code, Δ, S/B), trames décodées
    et rejetées (docs/selcall-cahier-des-charges.md § 11). Affichage local : le code y figure."""
    sc = getattr(snap.status, "selcall", None) if snap.status is not None else None
    if not isinstance(sc, dict) or not sc:
        return ()
    label, level = SELCALL_LABELS.get(sc.get("state"), (str(sc.get("state")), "warn"))
    text = label + (f" · code {sc['code']}" if sc.get("code") and sc.get("state") != "disabled" else "")
    if sc.get("sending"):
        text += f" · ENVOI {sc['sending']}"
        level = "bad"
    rows = [Row("SELCALL", text, level if snap.gateway_fresh else "dim")]
    call, details = sc.get("last_call"), []
    if isinstance(call, dict) and call.get("code"):
        details.append(f"dernier appel {call['code']}")
        if isinstance(call.get("delta_hz"), (int, float)):
            details.append(f"Δ {call['delta_hz']:+.0f} Hz")
        if isinstance(call.get("snr_db"), (int, float)):
            details.append(f"S/B {call['snr_db']:.0f} dB")
        if isinstance(call.get("at"), (int, float)):
            details.append(time.strftime("%H:%M:%S", time.localtime(call["at"])))
    details.append(f"trames {sc.get('frames_valid', 0)} · rejetées {sc.get('frames_rejected', 0)}")
    rows.append(Row("Appels", " · ".join(details), "dim"))
    return tuple(rows)


BREIZH_LABELS = {"connecting": ("recherche…", "warn"), "ready": ("prêt", "ok"), "active": ("ÉMISSION par Breizh", "ok"),
                 "fallback": ("REPLI : émission en direct", "bad"), "refused": ("liaison refusée", "bad")}


def _breizh_rows(snap: Snapshot) -> tuple[Row, ...]:
    """Breizh Audio Box ([breizh] enabled) : état, route de la prochaine émission, aller-retour, blocs remplacés."""
    breizh = getattr(snap.status, "breizh", None) if snap.status is not None else None
    if not isinstance(breizh, dict) or not breizh:
        return ()
    label, level = BREIZH_LABELS.get(breizh.get("state"), (str(breizh.get("state")), "warn"))
    details = [f"route {breizh.get('route')}" + (" (« Direct » choisi)" if breizh.get("bypass") else "")]
    if breizh.get("rtt_ms") is not None:
        details.append(f"aller-retour {breizh['rtt_ms']} ms")
    if breizh.get("late"):
        details.append(f"{breizh['late']} bloc(s) en retard")
    if breizh.get("reactivate_in_s") is not None:
        details.append(f"retour dans {breizh['reactivate_in_s']} s")
    return (Row("Breizh", f"{label} · {' · '.join(details)}", level if snap.gateway_fresh else "dim"),)


NET_LEVELS = {"green": ("BONNE", "ok"), "orange": ("MOYENNE", "warn"), "red": ("FAIBLE", "bad"), "gray": ("mesure…", "dim")}
NET_TYPES = {"lan": "réseau local", "wifi": "Wi-Fi", "4g": "4G", "5g": "5G", "mobile": "mobile", "unknown": "réseau ?"}
NET_DIAGNOSES = {
    "app_station": "application ou machine de la station", "lan": "réseau local ou machine de la station",
    "box_internet": "connexion Internet de la box", "webrtc": "WebRTC ou passerelle", "phone_radio": "radio du téléphone",
    "vpn_shared": "profil VPN probablement partagé", "mobile_or_tunnel": "téléphone, réseau mobile ou tunnel",
    "unknown": "indéterminé",
}


def _short(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s" if s < 3600 else f"{s // 3600} h {s % 3600 // 60:02d}"


def _value(v, unit: str) -> str:
    return "—" if v is None else f"{v:g} {unit}"


def _reseau_panel(snap: Snapshot, detail: bool = False) -> Panel:
    """Sonde de qualité réseau (docs/netprobe-cahier-des-charges.md § 9.4) : une ligne par client, les sondes de la
    station, la dernière coupure, les avertissements de profil VPN partagé. `detail` (touche n) : tout le détail."""
    net = getattr(snap.status, "net", None) if snap.status is not None else None
    if not isinstance(net, dict) or not net:
        return Panel("reseau", "Réseau", (Row("Sonde", "absente (station plus ancienne ou [netprobe] enabled = false)", "dim"),))
    dim = not snap.gateway_fresh
    rows: list[Row] = []
    for c in net.get("clients") or []:
        if not isinstance(c, dict):
            continue
        label, level = NET_LEVELS.get(c.get("level"), ("?", "warn"))
        if c.get("outage"):
            label, level = "COUPURE", "bad"
        who = str(c.get("id", "?")) + (" (visiteur)" if c.get("role") == "listener" else "")
        text = f"{label} · {NET_TYPES.get(c.get('net_type'), c.get('net_type') or '?')} · perte {_value(c.get('loss_pct'), '%')}" \
               f" · {_value(c.get('rtt_ms'), 'ms')}" + (f" · {c['agent']}" if c.get("agent") else "")
        if c.get("rsrp_dbm") is not None or c.get("signal_level") is not None:      # radio du téléphone (application)
            text += " · radio " + " ".join(x for x in (f"{c['rsrp_dbm']} dBm" if c.get("rsrp_dbm") is not None else "",
                                                       f"{c['signal_level']}/4" if c.get("signal_level") is not None else "") if x)
        rows.append(Row(who, text, "dim" if dim else level))
    if not rows:
        rows.append(Row("Clients", "aucun connecté", "dim"))
    for name, title in (("lan", "Box"), ("internet", "Internet")):
        p = (net.get("probes") or {}).get(name)
        if not isinstance(p, dict):
            continue
        ok = p.get("ok")
        state = "NE RÉPOND PAS" if ok is False else "répond" if ok else "—"
        text = f"{state} · {'TCP' if p.get('method') == 'tcp' else 'ping'} · {_value(p.get('rtt_ms'), 'ms')}"
        if detail:
            text += f" · perte {_value(p.get('loss_pct'), '%')} · {p.get('address', '?')}"
        rows.append(Row(title, text, "dim" if dim else ("bad" if ok is False else "ok" if ok else "dim")))
    last = net.get("last_outage")
    if isinstance(last, dict) and last.get("end_ms"):
        when = time.strftime("%H:%M:%S", time.localtime(last["end_ms"] / 1000))
        text = f"{_short((last.get('duration_ms') or 0) / 1000)}, fin à {when} — " \
               f"{NET_DIAGNOSES.get(last.get('diagnosis'), 'diagnostic en cours')}" + (f" ({last['agent']})" if last.get("agent") else "")
        if detail and last.get("basis"):
            text += " ; d'après : " + ", ".join(str(b) for b in last["basis"])
        rows.append(Row("Dernière coupure", text, "warn"))
    for w in net.get("vpn") or []:
        if isinstance(w, dict):
            agents = " / ".join(str(a) for a in w.get("agents") or [])
            rows.append(Row("PROFIL VPN", f"probablement partagé : {agents} ({w.get('address', '?')})"
                            + (" — un profil par appareil" if detail else ""), "bad"))
    if not detail:
        rows.append(Row("Détail", "touche n", "dim"))
    return Panel("reseau", "Réseau" + (" (détail)" if detail else ""), tuple(rows))


def build_panels(snap: Snapshot, net_detail: bool = False) -> list[Panel]:
    return [_radio_panel(snap), _audio_panel(snap), _connexion_panel(snap), _sante_panel(snap), _materiel_panel(snap),
            _reseau_panel(snap, net_detail)]


def render_plain(panels: list[Panel]) -> str:
    out = []
    for panel in panels:
        out.append(f"== {panel.title} ==")
        width = max(len(r.label) for r in panel.rows)
        out += [f"  {r.label.ljust(width)} : {r.text}" for r in panel.rows]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- journal

class EventLog:
    """Déduit des événements lisibles en comparant deux instantanés successifs."""

    def __init__(self, now_text: Callable[[], str] = lambda: time.strftime("%H:%M:%S"), limit: int = 200):
        self.now_text = now_text
        self.lines: deque[str] = deque(maxlen=limit)
        self._prev: dict | None = None

    @staticmethod
    def _facts(snap: Snapshot) -> dict:
        st = snap.status
        return {
            "fresh": snap.gateway_fresh, "present": st is not None,
            "state": None if st is None else st.ptt.get("state"),
            "owner": None if st is None else st.ptt.get("owner"),
            "clients": () if st is None else tuple(st.clients),
            "cut": "" if st is None else str(st.ptt.get("last_cut_reason") or ""),
            "fault": "" if st is None else str(st.ptt.get("fault") or ""),
            "rig": None if st is None else bool(st.rig.get("connected")),
            "safe": snap.safe_mode,
            "net_outage": None if st is None else ((getattr(st, "net", None) or {}).get("last_outage") or {}).get("end_ms"),
            "net_last": None if st is None else (getattr(st, "net", None) or {}).get("last_outage"),
            "vpn": () if st is None else tuple(sorted(str(w.get("address")) for w in (getattr(st, "net", None) or {}).get("vpn") or []
                                                      if isinstance(w, dict))),
        }

    def observe(self, snap: Snapshot) -> list[str]:
        now, new = self._facts(snap), []
        prev, self._prev = self._prev, now
        if prev is None:
            new.append("trx-monitor démarré")
        else:
            if now["fresh"] != prev["fresh"]:
                new.append("passerelle active" if now["fresh"] else "PASSERELLE FIGÉE OU ABSENTE")
            if now["state"] != prev["state"] and now["state"] is not None:
                owner = f" (client {now['owner']})" if now["owner"] else ""
                new.append(f"PTT {prev['state'] or '?'} → {now['state']}{owner}")
            if now["cut"] and now["cut"] != prev["cut"]:
                new.append(f"coupure : {CUT_REASONS.get(now['cut'], now['cut'])}")
            for client in sorted(set(now["clients"]) - set(prev["clients"])):
                new.append(f"client connecté : {client}")
            for client in sorted(set(prev["clients"]) - set(now["clients"])):
                new.append(f"client déconnecté : {client}")
            if now["rig"] != prev["rig"] and now["rig"] is not None:
                new.append("rigctld joint" if now["rig"] else "RIGCTLD INJOIGNABLE")
            if now["fault"] != prev["fault"]:
                new.append(f"DÉFAUT PTT : {now['fault']}" if now["fault"] else "défaut PTT effacé")
            if now["safe"] != prev["safe"]:
                new.append(f"MODE SÛR ACTIVÉ : {now['safe']}" if now["safe"] else "mode sûr désactivé")
            if now["net_outage"] and now["net_outage"] != prev["net_outage"]:
                o = now["net_last"] or {}
                new.append(f"coupure réseau de {_short((o.get('duration_ms') or 0) / 1000)}"
                           + (f" ({o['agent']})" if o.get("agent") else "")
                           + f" : {NET_DIAGNOSES.get(o.get('diagnosis'), 'indéterminé')}")
            for address in sorted(set(now["vpn"]) - set(prev["vpn"])):
                new.append(f"PROFIL VPN PROBABLEMENT PARTAGÉ ({address}) : un profil par appareil")
        stamped = [f"{self.now_text()}  {text}" for text in new]
        self.lines.extend(stamped)
        return stamped
