# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Modèle d'affichage de trx-monitor : tout ce qui se calcule sans écran, donc testable.

Le moniteur est un LECTEUR. Il ne commande jamais le poste, sauf l'unique action « STOP TX »
(voir actions.py), qui ne peut que couper.

Textes en quatre langues (domaine « monitor » de `trxstation/i18n/`) : chaque fonction qui produit un texte reçoit
un `Translator` (`t`) ; à défaut, celui de l'outil (`tool_translator("monitor")`), choisi À L'EXÉCUTION. Les CLÉS
des panneaux (radio, audio…) et les niveaux (ok, warn, bad, info, dim) ne se traduisent jamais (la page s'en sert).
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..i18n import Translator, tool_translator
from ..status import GatewayStatus

ACTIVE_STATES = ("KEYING", "TX", "UNKEYING")
DOMAIN = "monitor"

# Valeurs : clés du catalogue « monitor » (traduites à l'affichage) et niveau.
PTT_LABELS = {
    "RX": ("ptt.RX", "ok"),
    "KEYING": ("ptt.KEYING", "bad"),
    "TX": ("ptt.TX", "bad"),
    "UNKEYING": ("ptt.UNKEYING", "bad"),
}

CUT_REASONS = {reason: f"cut.{reason}" for reason in (
    "tot", "heartbeat", "toggle", "client_disconnected", "frequency_changed", "rig_reported_rx", "cat_down",
    "rig_silent", "rig_overheat", "ptt_write_failed", "rig_did_not_key", "shutdown", "startup")}


def translator(t: Translator | None = None) -> Translator:
    """Le traducteur donné, sinon celui de l'outil (TRX_LANG, préférences, système), lu maintenant."""
    return t if t is not None else tool_translator(DOMAIN)


def cut_reason_text(reason: str, t: Translator | None = None) -> str:
    t = translator(t)
    return t(CUT_REASONS[reason]) if reason in CUT_REASONS else reason


@dataclass(frozen=True)
class Row:
    label: str
    text: str
    level: str = "info"        # ok | warn | bad | info | dim


@dataclass(frozen=True)
class Panel:
    key: str                   # radio | sdr | audio | connexion | sante | materiel | reseau (jamais traduite)
    title: str
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class SystemInfo:
    temp_c: float | None = None
    load1: float | None = None
    mem_available_mb: float | None = None
    uptime_s: float | None = None
    host: str | None = None               # nom de l'ordinateur (titre du panneau, affichage local)


@dataclass(frozen=True)
class Snapshot:
    status: GatewayStatus | None
    gateway_fresh: bool
    stale_s: float | None
    safe_mode: str | None
    system: SystemInfo = SystemInfo()
    presence: dict | None = None          # state_dir/presence/status.json (module « presence »), None : absent
    monlink: dict | None = None           # state_dir/monlink/status.json (module « monlink »), None : absent
    sdr: dict | None = None               # state_dir/sdr/status.json (module « sdr »), None : absent


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


def format_duration(seconds: float | None, t: Translator | None = None) -> str:
    if seconds is None:
        return "--"
    t = translator(t)
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return (t("duration.days", days=days) + " " if days else "") + f"{hours} h {minutes:02d} min"


# --------------------------------------------------------------------------- panneaux

def _rig_tot_row(rig_tot: dict, t: Translator) -> Row | None:
    """TOT du poste (trxstation/rigtot.py), dernière lecture : « 3 min », « ARRÊT » (orange) ou « inconnu » ; rien
    avant la première connexion d'un opérateur ni pour un poste dont la lecture n'est pas qualifiée."""
    state = rig_tot.get("state") if isinstance(rig_tot, dict) else None
    if state == "on" and isinstance(rig_tot.get("minutes"), int):
        return Row(t("label.rig_tot"), t("rig_tot.on", minutes=rig_tot["minutes"]), "info")
    if state == "off":
        return Row(t("label.rig_tot"), t("rig_tot.off"), "warn")
    if state == "unknown" and rig_tot.get("reason") not in ("model", "ptt"):
        return Row(t("label.rig_tot"), t("rig_tot.unknown"), "dim")
    return None


def _power_row(rig: dict, power: dict, t: Translator) -> Row | None:
    """Alimentation du poste (fonction « power ») : « éteint par X depuis HH:MM », éteint hors de la station, ou
    allumage / extinction en cours ; None quand le poste est allumé (ou ne dit rien)."""
    state = power.get("state") if isinstance(power, dict) else None
    if state == "starting":
        return Row(t("label.rig"), t("power.starting"), "warn")
    if state == "stopping":
        return Row(t("label.rig"), t("power.stopping"), "warn")
    if rig.get("power") != "off":
        return None
    since = power.get("since")
    if power.get("last") == "off" and power.get("by") and isinstance(since, (int, float)):
        import time as _time
        when = _time.strftime("%H:%M", _time.localtime(since))
        return Row(t("label.rig"), t("power.off_by", by=str(power["by"])[:32], since=when), "warn")
    return Row(t("label.rig"), t("power.off_unknown"), "warn")


def _radio_panel(snap: Snapshot, t: Translator | None = None) -> Panel:
    t = translator(t)
    status = snap.status
    title = t("panel.radio")
    if status is None:
        return Panel("radio", title, (Row(t("label.rig"), t("radio.no_data"), "bad"),))
    ptt, rig = status.ptt, status.rig
    state = str(ptt.get("state", "?"))
    if state in PTT_LABELS:
        key, level = PTT_LABELS[state]
        label = t(key)
    else:
        label, level = state, "warn"
    if not snap.gateway_fresh:                      # donnée périmée : ne jamais l'afficher comme vivante
        label += " ?"
        level = "bad" if state in ACTIVE_STATES else "warn"
    rows = [Row("PTT", label, level)]
    power_row = _power_row(rig, getattr(status, "power", None) or {}, t)   # poste éteint ou qui s'allume
    if power_row is not None:
        rows.append(power_row)
    swr = status.swr if isinstance(getattr(status, "swr", None), dict) else {}
    if swr.get("running"):                          # mesure de TOS : des émissions courtes vont se succéder
        step = swr.get("state")
        step_text = t(f"swr.{step}") if step in ("preparing", "calibrating", "measuring", "restoring") else str(step)
        rows.append(Row(t("label.swr"), t("swr.progress", step=step_text, done=swr.get("done", 0),
                                          total=swr.get("total", 0), owner=swr.get("owner") or "?"), "warn"))
    if state == "TX" and ptt.get("tot_remaining_s") is not None:
        rows.append(Row("TOT", t("tot.remaining", seconds=f"{ptt['tot_remaining_s']:.0f}"),
                        "warn" if ptt.get("tot_warning") else "info"))
    dim = "info" if snap.gateway_fresh else "dim"
    tot_row = _rig_tot_row(getattr(status, "rig_tot", None) or {}, t)   # TOT du poste lu à la connexion d'un opérateur
    if tot_row is not None:
        rows.append(tot_row)
    rows += [
        Row(t("label.frequency"), format_frequency(rig.get("frequency_hz")), dim),
        Row(t("label.mode"), str(rig.get("mode") or "--"), dim),
        Row(t("label.filter"), "--" if rig.get("passband_hz") is None else f"{rig['passband_hz']} Hz", dim),
        Row(t("label.smeter"), f"{s_meter_text(rig.get('strength_db'))}  {s_meter_bar(rig.get('strength_db'))}", dim),
    ]
    return Panel("radio", title, tuple(rows))


def _connexion_panel(snap: Snapshot, t: Translator | None = None) -> Panel:
    t = translator(t)
    status = snap.status
    title = t("panel.connexion")
    if status is None:
        return Panel("connexion", title, (Row(t("label.clients"), "--", "dim"),))
    clients = ", ".join(status.clients) if status.clients else t("value.none")
    owner = status.ptt.get("owner")
    reason = str(status.ptt.get("last_cut_reason") or "")
    rows = [
        Row(t("label.clients"), clients, "info" if status.clients else "dim"),
        Row(t("label.transmitter"), str(owner) if owner else "—", "bad" if owner else "dim"),
        Row(t("label.last_cut"), cut_reason_text(reason, t) if reason else "—", "info" if reason else "dim"),
    ]
    return Panel("connexion", title, tuple(rows + _visitor_rows(status.presence, t, owner=owner)
                                           + _other_rows(status, t)))


def device_text(agent, t: Translator | None = None) -> str:
    """Type d'appareil déclaré par le client : « page Windows » -> page web (Windows), « android 0.66.0 » ->
    application Android 0.66.0 ; vide si inconnu."""
    t = translator(t)
    agent = str(agent or "").strip()
    if not agent:
        return ""
    if agent.lower().startswith("android"):
        return t("device.app", version=agent[7:].strip()).strip()
    if agent.lower().startswith("page"):
        rest = agent[4:].strip()
        return t("device.page", os=rest) if rest else t("device.page_unknown")
    return agent


def _other_rows(status, t: Translator) -> list[Row]:
    """Ce qui écoute ou se relie à la station sans être une connexion de la page ou de l'application : outil local
    (essai du poste…), Breizh Audio Box reliée."""
    rows: list[Row] = []
    audio = status.audio if isinstance(status.audio, dict) else {}
    presence = status.presence if isinstance(status.presence, dict) else {}
    streams = audio.get("listeners")
    people = (presence.get("operators") or 0) + (presence.get("listeners") or 0) if presence else len(status.clients)
    if isinstance(streams, int) and streams > people:
        rows.append(Row(t("label.other_streams"), t("other_streams.text", n=streams - people), "info"))
    breizh = getattr(status, "breizh", None)
    if isinstance(breizh, dict) and breizh.get("state") in ("ready", "active"):
        rows.append(Row(t("label.app"), t("app.breizh"), "ok"))
    return rows


def _visitor_rows(presence: dict, t: Translator | None = None, owner=None) -> list[Row]:
    """Visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md) : lecture seule, aucune action ici."""
    if not isinstance(presence, dict) or not presence:
        return []
    t = translator(t)
    most = presence.get("max_listeners") or 0
    count = presence.get("listeners") or 0
    rows = [Row(t("label.visitors"), f"{count} / {most}" if most else t("visitors.closed"), "info" if count else "dim")]
    suspended = presence.get("suspended")
    if isinstance(suspended, dict):
        reason = str(suspended["reason"]) if "reason" in suspended else t("suspended.default_reason")
        rows.append(Row(t("label.listen_suspended"), reason + (t("suspended.locked") if suspended.get("locked") else ""),
                        "warn"))
    grace = presence.get("grace_remaining_s")
    if isinstance(grace, (int, float)):
        rows.append(Row(t("label.operator_absent"), t("visitors.grace", seconds=f"{grace:.0f}"), "warn"))
    for c in presence.get("connections", []) or []:
        if isinstance(c, dict):
            since = int(c.get("since_s") or 0)
            role = t("role.listener") if c.get("role") == "listener" else t("role.operator")
            device = device_text(c.get("agent"), t)
            parts = [str(c.get("id", "?"))] + ([device] if device else []) + [str(c.get("source", "?")),
                                                                               f"{since // 3600:02d}:{since % 3600 // 60:02d}"]
            sending = owner is not None and c.get("id") == owner
            rows.append(Row(role, f"{c.get('pseudo', '?')} ({', '.join(parts)})" + (t("conn.transmitting") if sending else ""),
                            "bad" if sending else "info"))
    return rows


def _sante_panel(snap: Snapshot, t: Translator | None = None) -> Panel:
    t = translator(t)
    status = snap.status
    rows: list[Row] = []
    gateway = t("label.gateway")
    if status is None:
        rows.append(Row(gateway, t("gateway.absent"), "bad"))
    elif not snap.gateway_fresh:
        age = "?" if snap.stale_s is None else f"{snap.stale_s:.0f}"
        rows.append(Row(gateway, t("gateway.frozen", age=age, pid=status.pid), "bad"))
    else:
        rows.append(Row(gateway, t("gateway.active", pid=status.pid), "ok"))
    if status is not None:
        connected = bool(status.rig.get("connected"))
        rows.append(Row(t("label.rigctld"), t("rigctld.ok") if connected else t("rigctld.down"), "ok" if connected else "bad"))
        if status.rig.get("last_error"):
            rows.append(Row(t("label.last_error"), str(status.rig["last_error"])[:70], "warn"))
        fault = status.ptt.get("fault")
        rows.append(Row(t("label.ptt_fault"), t("fault.text", fault=fault) if fault else t("fault.none"),
                        "bad" if fault else "ok"))
    rows.append(Row(t("label.safe_mode"), t("safe.active", reason=snap.safe_mode) if snap.safe_mode else t("safe.no"),
                    "bad" if snap.safe_mode else "ok"))
    for row in (presence_row(snap.presence, t), monlink_row(snap.monlink, t)):
        if row is not None:
            rows.append(row)
    return Panel("sante", t("panel.sante"), tuple(rows))


def monlink_row(monlink: dict | None, t: Translator | None = None) -> Row | None:
    """Ligne « Monitoring » (cahier § 12) : liaisons dans chaque sens, ce qui attend l'opérateur ; rien si désactivé."""
    if not monlink or not monlink.get("enabled"):
        return None
    t = translator(t)
    label = t("label.monitoring")
    if monlink.get("problem"):
        return Row(label, t("common.problem", problem=monlink["problem"]), "warn")
    links = monlink.get("links") or []
    if not links:
        return Row(label, t("monlink.no_link"), "dim")
    helping = sum(1 for l in links if l.get("role") == "receiver" and l.get("state") != "confirm")
    helped = sum(1 for l in links if l.get("role") == "emitter" and l.get("state") != "confirm")
    parts = [t("monlink.helping", n=helping)] if helping else []
    if helped:
        parts.append(t("monlink.helped", n=helped))
    waiting = sum(1 for l in links if l.get("state") == "confirm")
    if waiting:
        parts.append(t("monlink.waiting", n=waiting))
    silent = sum(1 for l in links if l.get("silent"))
    if silent:
        parts.append(t("monlink.silent", n=silent))
    if any(l.get("request") for l in links):
        return Row(label, ", ".join(parts + [t("monlink.request")]), "warn")
    if silent:
        return Row(label, ", ".join(parts), "warn")
    if any(l.get("assist_left_s") for l in links):
        parts.append(t("monlink.assist"))
    return Row(label, ", ".join(parts) or t("monlink.pending"), "ok" if not waiting else "warn")


def presence_row(presence: dict | None, t: Translator | None = None) -> Row | None:
    """Ligne « Présence » : rien si la fonction est désactivée ou jamais démarrée (cas ordinaire)."""
    if not presence or not presence.get("enabled"):
        return None
    t = translator(t)
    label = t("label.presence")
    groups = [g for g in presence.get("groups") or [] if g.get("status") == "member"]
    friends = sum(int(g.get("members") or 0) for g in groups)
    if presence.get("problem"):
        return Row(label, t("common.problem", problem=presence["problem"]), "warn")
    if not presence.get("registered"):
        return Row(label, t("presence.unregistered"), "warn")
    return Row(label, t("presence.ok", groups=len(groups), friends=friends), "ok")


def _materiel_panel(snap: Snapshot, t: Translator | None = None) -> Panel:
    t = translator(t)
    s = snap.system
    temp_level = "dim" if s.temp_c is None else "bad" if s.temp_c >= 80 else "warn" if s.temp_c >= 70 else "ok"
    return Panel("materiel", t("panel.materiel", name=s.host or "").strip(), (
        Row(t("label.temperature"), "--" if s.temp_c is None else f"{s.temp_c:.0f} °C", temp_level),
        Row(t("label.load"), "--" if s.load1 is None else f"{s.load1:.2f}", "info"),
        Row(t("label.memory"), "--" if s.mem_available_mb is None else t("memory.mb", mb=f"{s.mem_available_mb:.0f}"),
            "info"),
        Row(t("label.uptime"), format_duration(s.uptime_s, t), "info"),
    ))


SDR_STALE_S = 30.0            # le module publie toutes les 5 s : au-delà, il est arrêté ou muet
SDR_FORGET_S = 86400.0        # au-delà d'un jour sans nouvelles : rubrique masquée (SDR mis hors service)
SDR_DRIVERS = {"sdrplay": "SDRplay RSP", "rtlsdr": "RTL-SDR"}


def _num(v, fmt: str = "{:g}") -> str:
    return "--" if not isinstance(v, (int, float)) or isinstance(v, bool) else fmt.format(v)


def _sdr_panel(snap: Snapshot, t: Translator | None = None, now: float | None = None) -> Panel | None:
    """Récepteur SDR (module « sdr », `state_dir/sdr/status.json`, étape 346) : état et bridage, récepteur, fréquence
    écoutée, largeur, gain, surcharge, écoute, charge du module. Rien si le module n'a jamais tourné ou s'est tu depuis
    plus d'un jour ; lignes grisées s'il ne publie plus."""
    sd = snap.sdr
    if not isinstance(sd, dict) or not sd:
        return None
    now = time.time() if now is None else now
    stamp = sd.get("t")
    age = now - stamp if isinstance(stamp, (int, float)) else None
    if age is not None and age > SDR_FORGET_S:
        return None
    t = translator(t)
    stale = age is None or age > SDR_STALE_S
    state = sd.get("state")
    if stale:
        text, level = t("sdr.silent", age=_short(age) if age is not None else "?"), "dim"
    elif state == "running" and sd.get("load"):
        text = t("sdr.throttled", level=sd["load"], reason=str(sd.get("load_reason") or "")[:120])
        level = "warn"
    elif state == "running":
        text, level = t("sdr.running"), "ok"
    elif state == "starting":
        text, level = t("sdr.starting"), "warn"
    elif state == "suspended":
        text, level = t("sdr.suspended", reason=str(sd.get("detail") or "")[:120]), "warn"
    elif state == "error":
        text, level = t("sdr.error", detail=str(sd.get("detail") or sd.get("code") or "?")[:160]), "bad"
    else:
        text, level = t("sdr.stopped"), "dim"
    dim = "dim" if stale or state != "running" else "info"
    driver = SDR_DRIVERS.get(str(sd.get("driver") or ""), str(sd.get("driver") or "SDR"))
    device = t("sdr.device", driver=driver, serial=sd.get("serial") or "?")
    if sd.get("ant") and sd.get("driver") == "sdrplay":
        device += t("sdr.antenna", ant=sd["ant"])
    rows = [Row(t("label.sdr_state"), text, level), Row(t("label.sdr_device"), device, dim)]
    dfreq = sd.get("dfreq")
    rows.append(Row(t("label.sdr_listened"), t("sdr.listened", freq=format_frequency(dfreq if isinstance(dfreq, int) else None),
                                                mode=sd.get("mode") or "--", bw=_num(sd.get("dbw"))), dim))
    fs = sd.get("fs")
    center = sd.get("center")
    rows.append(Row(t("label.sdr_span"), t("sdr.span", width=_num(fs / 1e6 if isinstance(fs, (int, float)) else None),
                                            center=format_frequency(center if isinstance(center, int) else None)), dim))
    fi = t("sdr.fi_auto") if sd.get("agc") else t("sdr.fi_manual", gr=_num(sd.get("gr")))
    gain = t("sdr.gain", lna=_num(sd.get("lna")), fi=fi)
    if isinstance(sd.get("gain_db"), (int, float)):
        gain += t("sdr.gain_now", gain=_num(sd["gain_db"], "{:.0f}"))
    rows.append(Row(t("label.sdr_gain"), gain, dim))
    count = sd.get("overloads") or 0
    if sd.get("overload") and not stale:
        rows.append(Row(t("label.sdr_overload"), t("sdr.overload_now", n=count), "bad"))
    else:
        rows.append(Row(t("label.sdr_overload"), t("sdr.overload_none", n=count), "warn" if count and not stale else dim))
    rows.append(Row(t("label.sdr_listen"), t("sdr.listen_on") if sd.get("audio") else t("sdr.listen_off"),
                    "info" if sd.get("audio") and not stale else "dim"))
    rows.append(Row(t("label.sdr_load"), t("sdr.load", cpu=_num(sd.get("cpu_total"), "{:.0f}"),
                                            mem=_num(sd.get("mem_mb"), "{:.0f}")), dim))
    return Panel("sdr", t("panel.sdr"), tuple(rows))


def _db_bar(db: float | None, width: int = 16) -> str:
    """Barre de niveau de -60 dBFS (vide) à 0 dBFS (pleine)."""
    if db is None:
        return "░" * width
    filled = round(min(1.0, max(0.0, (db + 60) / 60)) * width)
    return "█" * filled + "░" * (width - filled)


def _spectrum_rows(snap: Snapshot, t: Translator | None = None) -> tuple[Row, ...]:
    """Spectre HF (second port CI-V) : rien s'il n'est pas configuré."""
    sp = {} if snap.status is None else getattr(snap.status, "spectrum", {}) or {}
    state = sp.get("state", "off")
    if state == "off":
        return ()
    t = translator(t)
    label = t("label.spectrum")
    if state == "ok":
        return (Row(label, t("spectrum.ok", port=sp.get("port", "?"), fps=sp.get("fps", "?")), "ok"),)
    if state == "error":
        return (Row(label, t("spectrum.error", message=str(sp.get("message", ""))[:160]), "bad"),)
    return (Row(label, t("spectrum.waiting") if state == "waiting" else t("spectrum.checking"), "dim"),)


def _audio_panel(snap: Snapshot, t: Translator | None = None) -> Panel:
    t = translator(t)
    status = snap.status
    audio = {} if status is None else status.audio
    title = t("panel.audio")
    if not audio:
        return Panel("audio", title, (Row(t("label.audio"), t("audio.no_data"), "dim"), *_spectrum_rows(snap, t)))
    rx, tx = audio.get("rx_db"), audio.get("tx_db")
    gate = bool(audio.get("gate_open"))
    dim = "info" if snap.gateway_fresh else "dim"
    return Panel("audio", title, (
        Row(t("label.rx"), f"{rx:>4} dBFS  {_db_bar(rx)}" if rx is not None else "--", dim),
        *_rx_advice_rows(audio, t),
        Row(t("label.tx"), f"{tx:>4} dBFS  {_db_bar(tx)}" if tx is not None else "--", "bad" if gate else dim),
        Row(t("label.mic_gate"), t("gate.open") if gate else t("gate.closed"), "bad" if gate else "ok"),
        Row(t("label.listeners"), str(audio.get("listeners", 0)), "info"),
        Row(t("label.frames"), t("frames.text", rx=audio.get("rx_frames", 0), tx=audio.get("tx_frames", 0)), "dim"),
        Row(t("label.losses"), t("losses.text", rx=audio.get("rx_dropped", 0), tx=audio.get("tx_dropped_not_owner", 0)),
            "warn" if audio.get("rx_dropped", 0) or audio.get("tx_dropped_not_owner", 0) else "dim"),
        *_breizh_rows(snap, t),
        *_selcall_rows(snap, t),
        *_freedv_rows(snap, t),
        *_spectrum_rows(snap, t),
    ))


RX_ADVICE_LABELS = {"high": ("rx_advice.high", "warn"), "low": ("rx_advice.low", "warn"), "ok": ("rx_advice.ok", "ok")}


def _rx_advice_rows(audio: dict, t: Translator | None = None) -> tuple[Row, ...]:
    """Niveau reçu jugé sur 30 s par la passerelle (`rx_advice`, étape 301) : trop fort / trop faible renvoie au
    menu 2.9 ; rien pour une passerelle qui ne publie pas l'avis."""
    if "rx_advice" not in audio:
        return ()
    t = translator(t)
    advice = audio.get("rx_advice")
    label = t("label.rx_advice")
    if not isinstance(advice, dict) or advice.get("verdict") not in ("high", "low", "ok"):
        return (Row(label, t("rx_advice.wait"), "dim"),)
    key, level = RX_ADVICE_LABELS[advice["verdict"]]
    return (Row(label, t(key, level=advice.get("typical_db", "?"), pct=advice.get("limited_pct", 0)), level),)


SELCALL_LABELS = {"disabled": ("selcall.disabled", "dim"), "standby": ("selcall.standby", "info"),
                  "open": ("selcall.open", "warn")}


def _label(table: dict, value, t: Translator) -> tuple[str, str]:
    """(clé, niveau) d'une table -> (texte traduit, niveau) ; valeur inconnue montrée telle quelle, en avertissement."""
    if value in table:
        key, level = table[value]
        return t(key), level
    return str(value), "warn"


def _selcall_rows(snap: Snapshot, t: Translator | None = None) -> tuple[Row, ...]:
    """SELCALL ([selcall] enabled) : état et code armé, envoi en cours, dernier appel (code, Δ, S/B), trames décodées
    et rejetées (docs/selcall-cahier-des-charges.md § 11). Affichage local : le code y figure."""
    sc = getattr(snap.status, "selcall", None) if snap.status is not None else None
    if not isinstance(sc, dict) or not sc:
        return ()
    t = translator(t)
    label, level = _label(SELCALL_LABELS, sc.get("state"), t)
    text = label + (t("selcall.code", code=sc["code"]) if sc.get("code") and sc.get("state") != "disabled" else "")
    if sc.get("sending"):
        text += t("selcall.sending", sending=sc["sending"])
        level = "bad"
    rows = [Row("SELCALL", text, level if snap.gateway_fresh else "dim")]
    call, details = sc.get("last_call"), []
    if isinstance(call, dict) and call.get("code"):
        details.append(t("selcall.last_call", code=call["code"]))
        if isinstance(call.get("delta_hz"), (int, float)):
            details.append(f"Δ {call['delta_hz']:+.0f} Hz")
        if isinstance(call.get("snr_db"), (int, float)):
            details.append(t("selcall.snr", snr=f"{call['snr_db']:.0f}"))
        if isinstance(call.get("at"), (int, float)):
            details.append(time.strftime("%H:%M:%S", time.localtime(call["at"])))
    details.append(t("selcall.frames", valid=sc.get("frames_valid", 0), rejected=sc.get("frames_rejected", 0)))
    rows.append(Row(t("label.calls"), " · ".join(details), "dim"))
    return tuple(rows)


FREEDV_ENGINE = {"demarrage": ("freedv.demarrage", "warn"), "ecoute": ("freedv.ecoute", "ok"),
                 "relance": ("freedv.relance", "warn"), "panne": ("freedv.panne", "bad"), "arret": ("freedv.arret", "dim")}


def _freedv_rows(snap: Snapshot, t: Translator | None = None) -> tuple[Row, ...]:
    """FreeDV ([freedv] enabled) : mode, état des décodeurs, synchro, SNR, dernier indicatif (cahier FreeDV § 8)."""
    fd = getattr(snap.status, "freedv", None) if snap.status is not None else None
    if not isinstance(fd, dict) or not fd:
        return ()
    t = translator(t)
    fresh = snap.gateway_fresh
    if not fd.get("on"):
        text, level = t("freedv.rig_audio"), "dim"
        if fd.get("fault"):
            text, level = t("freedv.abandoned", fault=fd["fault"]), "bad"
        return (Row("FreeDV", text, level if fresh else "dim"),)
    label, level = _label(FREEDV_ENGINE, fd.get("engine"), t)
    parts = [f"RADE V1 · {label}"]
    if fd.get("confirmed"):
        snr = fd.get("snr_db")
        parts.append(t("freedv.sync") + (f" {snr:+.1f} dB" if isinstance(snr, (int, float)) else ""))
    elif fd.get("sync") in ("sync", "candidate"):
        parts.append(t("freedv.searching"))
    if fd.get("restarts"):
        parts.append(t("freedv.restarts", n=fd["restarts"]))
    rows = [Row("FreeDV", " · ".join(parts), level if fresh else "dim")]
    call = fd.get("last_call")
    if isinstance(call, dict) and call.get("callsign"):
        detail = t("freedv.last_call", callsign=call["callsign"])
        if isinstance(call.get("snr_db"), (int, float)):
            detail += f" ({call['snr_db']} dB)"
        if isinstance(call.get("t"), (int, float)):
            detail += t("freedv.at", time=time.strftime("%H:%M:%S", time.localtime(call["t"])))
        rows.append(Row(t("label.callsign"), detail, "info" if fresh else "dim"))
    return tuple(rows)


BREIZH_LABELS = {"connecting": ("breizh.connecting", "warn"), "ready": ("breizh.ready", "ok"),
                 "active": ("breizh.active", "ok"), "fallback": ("breizh.fallback", "bad"),
                 "refused": ("breizh.refused", "bad")}


def _breizh_rows(snap: Snapshot, t: Translator | None = None) -> tuple[Row, ...]:
    """Breizh Audio Box ([breizh] enabled) : état, route de la prochaine émission, aller-retour, blocs remplacés."""
    breizh = getattr(snap.status, "breizh", None) if snap.status is not None else None
    if not isinstance(breizh, dict) or not breizh:
        return ()
    t = translator(t)
    label, level = _label(BREIZH_LABELS, breizh.get("state"), t)
    details = [t("breizh.route", route=breizh.get("route")) + (t("breizh.bypass") if breizh.get("bypass") else "")]
    if breizh.get("rtt_ms") is not None:
        details.append(t("breizh.rtt", ms=breizh["rtt_ms"]))
    if breizh.get("late"):
        details.append(t("breizh.late", n=breizh["late"]))
    if breizh.get("reactivate_in_s") is not None:
        details.append(t("breizh.back", seconds=breizh["reactivate_in_s"]))
    return (Row(t("label.breizh"), f"{label} · {' · '.join(details)}", level if snap.gateway_fresh else "dim"),)


NET_LEVELS = {"green": ("net.level.green", "ok"), "orange": ("net.level.orange", "warn"), "red": ("net.level.red", "bad"),
              "gray": ("net.level.gray", "dim")}
NET_TYPES = {k: f"net.type.{k}" for k in ("lan", "wifi", "4g", "5g", "mobile", "unknown")}
NET_DIAGNOSES = {k: f"net.diag.{k}" for k in ("app_station", "lan", "box_internet", "webrtc", "phone_radio",
                                               "vpn_shared", "mobile_or_tunnel", "unknown")}


def _net_type(value, t: Translator) -> str:
    return t(NET_TYPES[value]) if value in NET_TYPES else (value or "?")


def _diagnosis(value, t: Translator, default_key: str) -> str:
    return t(NET_DIAGNOSES[value]) if value in NET_DIAGNOSES else t(default_key)


def _short(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s" if s < 3600 else f"{s // 3600} h {s % 3600 // 60:02d}"


def _value(v, unit: str) -> str:
    return "—" if v is None else f"{v:g} {unit}"


def _reseau_panel(snap: Snapshot, detail: bool = False, t: Translator | None = None) -> Panel:
    """Sonde de qualité réseau (docs/netprobe-cahier-des-charges.md § 9.4) : une ligne par client, les sondes de la
    station, la dernière coupure, les avertissements de profil VPN partagé. `detail` (bouton « Détail » de la page,
    touche n ou clic dans trx-monitor) : tout le détail."""
    t = translator(t)
    net = getattr(snap.status, "net", None) if snap.status is not None else None
    if not isinstance(net, dict) or not net:
        return Panel("reseau", t("panel.reseau"), (Row(t("label.probe"), t("net.absent"), "dim"),))
    dim = not snap.gateway_fresh
    rows: list[Row] = []
    for c in net.get("clients") or []:
        if not isinstance(c, dict):
            continue
        if c.get("level") in NET_LEVELS:
            key, level = NET_LEVELS[c["level"]]
            label = t(key)
        else:
            label, level = "?", "warn"
        if c.get("outage"):
            label, level = t("net.outage"), "bad"
        if c.get("silent"):                       # n'a jamais répondu : outil sans sonde, pas une coupure
            rows.append(Row(str(c.get("id", "?")) + (t("net.listener") if c.get("role") == "listener" else ""),
                            t("net.silent") + (f" · {c['agent']}" if c.get("agent") else ""), "dim"))
            continue
        who = str(c.get("id", "?")) + (t("net.listener") if c.get("role") == "listener" else "")
        text = t("net.client", level=label, type=_net_type(c.get("net_type"), t), loss=_value(c.get("loss_pct"), "%"),
                 rtt=_value(c.get("rtt_ms"), "ms")) + (f" · {c['agent']}" if c.get("agent") else "")
        if c.get("rsrp_dbm") is not None or c.get("signal_level") is not None:      # radio du téléphone (application)
            text += t("net.radio") + " " + " ".join(
                x for x in (f"{c['rsrp_dbm']} dBm" if c.get("rsrp_dbm") is not None else "",
                            f"{c['signal_level']}/4" if c.get("signal_level") is not None else "") if x)
        rows.append(Row(who, text, "dim" if dim else level))
    if not rows:
        rows.append(Row(t("label.clients"), t("net.no_clients"), "dim"))
    for name, title_key in (("lan", "label.box"), ("internet", "label.internet")):
        p = (net.get("probes") or {}).get(name)
        if not isinstance(p, dict):
            continue
        ok = p.get("ok")
        state = t("net.probe_down") if ok is False else t("net.probe_ok") if ok else "—"
        text = f"{state} · {'TCP' if p.get('method') == 'tcp' else 'ping'} · {_value(p.get('rtt_ms'), 'ms')}"
        if detail:
            text += " · " + t("net.loss", loss=_value(p.get("loss_pct"), "%")) + f" · {p.get('address', '?')}"
        rows.append(Row(t(title_key), text, "dim" if dim else ("bad" if ok is False else "ok" if ok else "dim")))
    last = net.get("last_outage")
    if isinstance(last, dict) and last.get("end_ms"):
        when = time.strftime("%H:%M:%S", time.localtime(last["end_ms"] / 1000))
        text = t("net.last_outage", duration=_short((last.get("duration_ms") or 0) / 1000), when=when,
                 diagnosis=_diagnosis(last.get("diagnosis"), t, "net.diag_pending")) \
            + (f" ({last['agent']})" if last.get("agent") else "")
        if detail and last.get("basis"):
            text += t("net.basis", basis=", ".join(str(b) for b in last["basis"]))
        rows.append(Row(t("label.last_cut"), text, "warn"))
    for w in net.get("vpn") or []:
        if isinstance(w, dict):
            agents = " / ".join(str(a) for a in w.get("agents") or [])
            rows.append(Row(t("label.vpn"), t("net.vpn", agents=agents, address=w.get("address", "?"))
                            + (t("net.vpn_hint") if detail else ""), "bad"))
    return Panel("reseau", t("panel.reseau_detail") if detail else t("panel.reseau"), tuple(rows))


def build_panels(snap: Snapshot, net_detail: bool = False, t: Translator | None = None) -> list[Panel]:
    t = translator(t)
    sdr = _sdr_panel(snap, t)
    return [_radio_panel(snap, t), *([sdr] if sdr is not None else []), _audio_panel(snap, t), _connexion_panel(snap, t), _sante_panel(snap, t),
            _materiel_panel(snap, t), _reseau_panel(snap, net_detail, t)]


def render_plain(panels: list[Panel]) -> str:
    out = []
    for panel in panels:
        out.append(f"== {panel.title} ==")
        width = max(len(r.label) for r in panel.rows)
        out += [f"  {r.label.ljust(width)} : {r.text}" for r in panel.rows]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- journal

LOG_LEVELS = ("ok", "warn", "bad", "info")


class LogLines(deque):
    """Lignes du journal (chaînes, comme avant) avec, en parallèle, le niveau de chacune (`levels`). Une ligne
    ajoutée par `append` / `extend` sans niveau compte comme « info » : les deux files restent alignées."""

    def __init__(self, maxlen: int) -> None:
        super().__init__(maxlen=maxlen)
        self.levels: deque[str] = deque(maxlen=maxlen)

    def append(self, text: str, level: str = "info") -> None:          # type: ignore[override]
        super().append(text)
        self.levels.append(level if level in LOG_LEVELS else "info")

    def extend(self, texts: Iterable[str], level: str = "info") -> None:     # type: ignore[override]
        for text in texts:
            self.append(text, level)

    def clear(self) -> None:
        super().clear()
        self.levels.clear()


class EventLog:
    """Déduit des événements lisibles en comparant deux instantanés successifs.

    `lines` : chaînes horodatées (inchangé) ; `entries()` : [{"text", "level"}] avec le niveau de chaque ligne
    (bad = grave : passerelle figée, rigctld injoignable, défaut PTT, mode sûr, profil VPN partagé, STOP TX en
    échec ; ok = retour à la normale ; warn = coupure réseau ; info = le reste), quelle que soit la langue.
    `record(texte, niveau)` : ajoute une ligne horodatée venue d'ailleurs (résultat de STOP TX)."""

    def __init__(self, now_text: Callable[[], str] = lambda: time.strftime("%H:%M:%S"), limit: int = 200,
                 t: Translator | None = None):
        self.now_text = now_text
        self.t = t                               # None : traducteur de l'outil, lu à chaque observation
        self.lines: LogLines = LogLines(limit)
        self._prev: dict | None = None

    def entries(self) -> list[dict[str, str]]:
        return [{"text": text, "level": level} for text, level in zip(self.lines, self.lines.levels)]

    def record(self, text: str, level: str = "info") -> str:
        stamped = f"{self.now_text()}  {text}"
        self.lines.append(stamped, level)
        return stamped

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
        t = translator(self.t)
        now, new = self._facts(snap), []          # new : (texte, niveau)
        prev, self._prev = self._prev, now
        if prev is None:
            new.append((t("log.started"), "info"))
        else:
            if now["fresh"] != prev["fresh"]:
                new.append((t("log.gateway_active"), "ok") if now["fresh"] else (t("log.gateway_frozen"), "bad"))
            if now["state"] != prev["state"] and now["state"] is not None:
                owner = t("log.owner", owner=now["owner"]) if now["owner"] else ""
                new.append((t("log.ptt", before=prev["state"] or "?", after=now["state"], owner=owner), "info"))
            if now["cut"] and now["cut"] != prev["cut"]:
                new.append((t("log.cut", reason=cut_reason_text(now["cut"], t)), "info"))
            for client in sorted(set(now["clients"]) - set(prev["clients"])):
                new.append((t("log.client_on", client=client), "info"))
            for client in sorted(set(prev["clients"]) - set(now["clients"])):
                new.append((t("log.client_off", client=client), "info"))
            if now["rig"] != prev["rig"] and now["rig"] is not None:
                new.append((t("log.rig_ok"), "ok") if now["rig"] else (t("log.rig_down"), "bad"))
            if now["fault"] != prev["fault"]:
                new.append((t("log.fault", fault=now["fault"]), "bad") if now["fault"] else (t("log.fault_cleared"), "ok"))
            if now["safe"] != prev["safe"]:
                new.append((t("log.safe_on", reason=now["safe"]), "bad") if now["safe"] else (t("log.safe_off"), "ok"))
            if now["net_outage"] and now["net_outage"] != prev["net_outage"]:
                o = now["net_last"] or {}
                new.append((t("log.net_outage", duration=_short((o.get("duration_ms") or 0) / 1000),
                              agent=t("log.agent", agent=o["agent"]) if o.get("agent") else "",
                              diagnosis=_diagnosis(o.get("diagnosis"), t, "net.diag.unknown")), "warn"))
            for address in sorted(set(now["vpn"]) - set(prev["vpn"])):
                new.append((t("log.vpn", address=address), "bad"))
        return [self.record(text, level) for text, level in new]
