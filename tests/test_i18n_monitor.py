# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""trx-monitor en quatre langues (domaine « monitor » de trxstation/i18n) : catalogues complets et cohérents, aucune
clé oubliée, panneaux et journal traduits, clés des panneaux et niveaux inchangés (la page s'en sert)."""
import json
import re
from dataclasses import replace
from pathlib import Path

from trxstation.i18n import LANGS, Translator
from trxstation.monitor import model
from trxstation.monitor.model import EventLog, Snapshot, SystemInfo, build_panels, render_plain
from trxstation.status import GatewayStatus

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "trxstation" / "i18n"
MONITOR = ROOT / "trxstation" / "monitor"


def catalog(lang):
    return json.loads((I18N / f"monitor.{lang}.json").read_text(encoding="utf-8"))


def fields(text):
    return set(re.findall(r"\{(\w+)", text))


def full_status(state="TX"):
    st = GatewayStatus(
        pid=42, seq=1, written_at=0.0,
        ptt={"state": state, "owner": "phone", "fault": "unkey_failed", "last_cut_reason": "tot",
             "tot_remaining_s": 30, "tot_warning": True},
        rig={"connected": False, "frequency_hz": 14_200_000, "mode": "USB", "passband_hz": 2400,
             "strength_db": -12, "last_error": "timeout"},
        clients=["phone"])
    return replace(
        st,
        audio={"rx_db": -20, "tx_db": -10, "gate_open": True, "listeners": 1, "rx_frames": 5, "tx_frames": 3,
               "rx_dropped": 1, "tx_dropped_not_owner": 0},
        presence={"listeners": 1, "max_listeners": 3, "grace_remaining_s": 30, "suspended": {"locked": True},
                  "connections": [{"id": "phone", "pseudo": "K", "role": "operator", "source": "x", "since_s": 60},
                                  {"id": "c", "pseudo": "C", "role": "listener", "source": "y", "since_s": 5}]},
        swr={"running": True, "state": "measuring", "done": 2, "total": 9, "owner": "phone"},
        selcall={"state": "open", "code": "4721", "sending": "4721", "frames_valid": 3, "frames_rejected": 1,
                 "last_call": {"code": "4721", "delta_hz": 12.0, "snr_db": 9.0, "at": 0.0}},
        freedv={"on": True, "engine": "ecoute", "confirmed": True, "snr_db": 4.0, "restarts": 2,
                "last_call": {"callsign": "F4XYZ", "snr_db": 5, "t": 0.0}},
        breizh={"state": "fallback", "route": "direct", "bypass": True, "rtt_ms": 3, "late": 2, "reactivate_in_s": 40},
        spectrum={"state": "error", "message": "port"},
        net={"clients": [{"id": "phone", "role": "operator", "net_type": "4g", "level": "orange", "loss_pct": 3.0,
                          "rtt_ms": 80, "rsrp_dbm": -98, "signal_level": 3},
                         {"id": "c", "role": "listener", "net_type": "lan", "level": "green", "outage": True}],
             "probes": {"lan": {"ok": True, "method": "icmp", "rtt_ms": 2, "loss_pct": 0, "address": "a"},
                        "internet": {"ok": False, "method": "tcp", "rtt_ms": None}},
             "vpn": [{"address": "10.0.0.2", "agents": ["a", "b"]}],
             "last_outage": {"end_ms": 1_000_000, "duration_ms": 6000, "diagnosis": "vpn_shared", "basis": ["x"],
                             "agent": "android"}})


def snapshots():
    full = full_status()
    yield Snapshot(full, True, 0.1, "trop de relances", SystemInfo(55.0, 0.5, 900.0, 200_000.0),
                   presence={"enabled": True, "registered": True, "groups": [{"status": "member", "members": 2}]},
                   monlink={"enabled": True, "links": [{"role": "receiver", "state": "active", "silent": True,
                                                         "request": {"assist": 1}}]})
    yield Snapshot(full, False, 9.0, None, SystemInfo())
    yield Snapshot(replace(full, audio={}, spectrum={"state": "waiting"}, freedv={"on": False, "fault": "x"},
                           net={}), True, 0.1, None,
                   presence={"enabled": True, "registered": False}, monlink={"enabled": True, "links": []})
    yield Snapshot(None, False, None, None)


def test_four_catalogs_with_the_same_keys_and_fields():
    reference = catalog("fr")
    assert set(LANGS) == {"fr", "en", "de", "es"}
    for lang in LANGS:
        path = I18N / f"monitor.{lang}.json"
        raw = path.read_bytes().decode("utf-8")
        assert raw.endswith("\n")
        data = json.loads(raw)
        assert set(data) == set(reference), (lang, set(data) ^ set(reference))
        for key, text in data.items():
            assert isinstance(text, str) and text.strip(), (lang, key)
            assert fields(text) == fields(reference[key]), (lang, key)


def test_every_key_used_by_the_monitor_exists_in_french():
    fr = catalog("fr")
    used = set()
    for path in MONITOR.glob("*.py"):
        used |= set(re.findall(r'\bt\("([\w.]+)"', path.read_text(encoding="utf-8")))
    for table in (model.PTT_LABELS, model.SELCALL_LABELS, model.FREEDV_ENGINE, model.BREIZH_LABELS, model.NET_LEVELS,
                  model.RX_ADVICE_LABELS):
        used |= {key for key, _ in table.values()}
    used |= set(model.CUT_REASONS.values()) | set(model.NET_TYPES.values()) | set(model.NET_DIAGNOSES.values())
    used |= {f"swr.{s}" for s in ("preparing", "calibrating", "measuring", "restoring")}
    assert used and used <= set(fr), used - set(fr)
    # Les clés réellement lues pendant un affichage complet existent aussi.
    t = Translator("fr", "monitor")
    log = EventLog(t=t)
    for snap in snapshots():
        build_panels(snap, net_detail=True, t=t)
        build_panels(snap, t=t)
        log.observe(snap)
    assert set(t.used) <= set(fr), set(t.used) - set(fr)


def _all_text(lang):
    t = Translator(lang, "monitor")
    texts = []
    log = EventLog(now_text=lambda: "12:00:00", t=t)
    log.observe(Snapshot(None, True, 0.1, None))
    for snap in snapshots():
        for detail in (False, True):
            texts.append(render_plain(build_panels(snap, net_detail=detail, t=t)))
        log.observe(snap)
    log.observe(Snapshot(replace(full_status("RX"), net={"vpn": [{"address": "10.9.9.9"}],
                                                         "last_outage": {"end_ms": 5, "duration_ms": 1000}}),
                         True, 0.1, "x"))
    return "\n".join(texts + list(log.lines)), log


def test_english_dashboard_has_no_french_left():
    text, log = _all_text("en")
    for french in ("ÉMISSION", "Fréquence", "RÉCEPTION", "Passerelle", "coupure", "Mémoire", "Réseau", "Visiteur",
                   "aucun", "FIGÉE", "INJOIGNABLE", "MODE SÛR", "trames", "démarré"):
        assert french not in text, french
    for english in ("TRANSMIT", "Frequency", "openRemoteTRX gateway", "Hamlib service (rigctld)", "FROZEN", "Safe mode", "S-meter", "Network", "trx-monitor started",
                    "PTT FAULT", "VPN PROFILE PROBABLY SHARED"):
        assert english in text, english
    levels = {e["text"].split("  ", 1)[1]: e["level"] for e in log.entries()}
    assert levels["trx-monitor started"] == "info"
    assert any(level == "bad" and "SAFE MODE ON" in text for text, level in levels.items())


def test_panel_keys_and_levels_do_not_depend_on_the_language():
    for snap in snapshots():
        shapes = {lang: [(p.key, [r.level for r in p.rows]) for p in build_panels(snap, t=Translator(lang, "monitor"))]
                  for lang in LANGS}
        assert all(shape == shapes["fr"] for shape in shapes.values())
        assert [key for key, _ in shapes["fr"]] == ["radio", "audio", "connexion", "sante", "materiel", "reseau"]


def test_default_language_comes_from_the_tool_at_run_time(monkeypatch):
    snap = next(snapshots())
    monkeypatch.setenv("TRX_LANG", "de")
    assert build_panels(snap)[0].rows[0].text == "SENDEN"
    monkeypatch.setenv("TRX_LANG", "es")
    assert build_panels(snap)[0].rows[0].text == "TRANSMISIÓN"


def test_event_log_levels_stay_aligned_with_the_lines():
    log = EventLog(now_text=lambda: "12:00:00", limit=3, t=Translator("en", "monitor"))
    log.observe(Snapshot(None, True, 0.1, None))
    log.lines.append("12:00:01  STOP TX: raw line")                  # ajout direct (ancienne manière) : « info »
    log.record("STOP TX: FAILED", "bad")
    log.observe(Snapshot(None, True, 0.1, "x"))
    entries = log.entries()
    assert len(entries) == 3 == len(log.lines)
    assert [e["text"] for e in entries] == list(log.lines)
    assert [e["level"] for e in entries] == ["info", "bad", "bad"]
    assert "SAFE MODE ON: x" in entries[-1]["text"]
