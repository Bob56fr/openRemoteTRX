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
    return Panel("connexion", "Connexion", (
        Row("Clients", clients, "info" if status.clients else "dim"),
        Row("Émetteur", str(owner) if owner else "—", "bad" if owner else "dim"),
        Row("Dernière coupure", CUT_REASONS.get(reason, reason) if reason else "—", "info" if reason else "dim"),
    ))


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
        *_spectrum_rows(snap),
    ))


def build_panels(snap: Snapshot) -> list[Panel]:
    return [_radio_panel(snap), _audio_panel(snap), _connexion_panel(snap), _sante_panel(snap), _materiel_panel(snap)]


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
        stamped = [f"{self.now_text()}  {text}" for text in new]
        self.lines.extend(stamped)
        return stamped
