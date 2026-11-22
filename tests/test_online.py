# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Services en ligne du tableau de bord (étape 351) : relevés des clients (aucune sonde de plus), fichiers ntfy des
processus (jamais l'adresse), panneau affiché seulement pour les fonctions en service."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from trxstation import online
from trxstation.i18n import Translator
from trxstation.monitor.model import Snapshot, _online_panel, build_panels
from trxstation.supervisor.notify import Notifier


def t() -> Translator:
    return Translator("fr", "monitor")


def test_link_health_keeps_the_last_success_and_the_failure_in_progress():
    now = [1000.0]
    h = online.LinkHealth("ORT-6903", clock=lambda: now[0])
    assert h.to_dict() == {"ok_at": None, "rtt_ms": None, "fail_at": None, "fail_since": None}
    h.ok(0.085)
    now[0] = 1100.0
    h.fail()
    now[0] = 1200.0
    h.fail()
    d = h.to_dict()
    assert d == {"ok_at": 1000, "rtt_ms": 85, "fail_at": 1200, "fail_since": 1100, "code": "ORT-6903"}
    h.ok(0.01)
    assert "code" not in h.to_dict() and h.to_dict()["fail_since"] is None


def test_ntfy_records_of_each_process_are_merged_without_the_address(tmp_path):
    clock = [500.0]
    sup = online.NtfyRecord(tmp_path, "superviseur", configured=True, clock=lambda: clock[0])
    gw = online.NtfyRecord(tmp_path, "passerelle", configured=True, clock=lambda: clock[0])
    assert online.read_ntfy(tmp_path) == {"configured": True, "ok_at": None, "fail_at": None}
    sup.sent(True)
    clock[0] = 600.0
    gw.sent(False)
    assert online.read_ntfy(tmp_path) == {"configured": True, "ok_at": 500, "fail_at": 600}
    again = online.NtfyRecord(tmp_path, "superviseur", configured=True)   # redémarrage : historique gardé
    assert again.data["ok_at"] == 500
    for f in (tmp_path / "ntfy").glob("*.json"):
        assert "http" not in f.read_text(encoding="utf-8")
    assert online.read_ntfy(tmp_path / "absent") is None


def test_notifier_records_each_real_sending(tmp_path):
    record = online.NtfyRecord(tmp_path, "passerelle", configured=True)
    sent = Notifier("https://ntfy.example/sujet", post=lambda *a: None, threaded=False, min_interval_s=0, record=record)
    sent.send("essai", "ok")
    assert isinstance(record.data["ok_at"], int) and record.data["fail_at"] is None

    def boom(*_a):
        raise OSError("réseau")
    failing = Notifier("https://ntfy.example/sujet", post=boom, threaded=False, min_interval_s=0, record=record)
    failing.send("essai", "raté")
    assert isinstance(record.data["fail_at"], int)
    Notifier("", threaded=False, record=record).send("x", "y")              # pas d'adresse : rien n'est relevé


def test_online_panel_only_lists_the_features_in_service():
    now = 10_000.0
    empty = Snapshot(status=None, gateway_fresh=False, stale_s=None, safe_mode=None)
    assert _online_panel(empty, t(), now) is None
    assert all(p.key != "en_ligne" for p in build_panels(empty, t=t()))
    off = Snapshot(status=None, gateway_fresh=False, stale_s=None, safe_mode=None,
                   presence={"enabled": False}, diffusion={"enabled": False}, ntfy={"configured": False})
    assert _online_panel(off, t(), now) is None
    snap = Snapshot(status=None, gateway_fresh=False, stale_s=None, safe_mode=None,
                    presence={"enabled": True, "server": {"ok_at": now - 12, "rtt_ms": 85, "fail_since": None}},
                    monlink={"enabled": True, "server": {"ok_at": now - 3600, "rtt_ms": 90, "fail_since": now - 180,
                                                         "code": "ORT-7040"}},
                    diffusion={"enabled": True, "active": False, "last_start": {"at": now - 7200, "operator": "PC"},
                               "server": {"ok_at": now - 7000}},
                    ntfy={"configured": True, "ok_at": now - 60, "fail_at": None})
    rows = {r.label: (r.text, r.level) for r in _online_panel(snap, t(), now).rows}
    assert rows["Présence de groupe"] == ("joignable · dernier échange il y a 12 s · 85 ms", "ok")
    text, level = rows["Monitoring entre stations"]
    assert level == "bad" and "injoignable depuis 3 min 00 s (ORT-7040)" in text and "il y a 1 h 00" in text
    assert rows["Diffusion en direct"] == ("à l'arrêt · dernier lancement il y a 2 h 00 par PC", "dim")
    assert rows["Alertes ntfy"] == ("dernière alerte envoyée il y a 1 min 00 s", "ok")
    live = Snapshot(status=None, gateway_fresh=False, stale_s=None, safe_mode=None,
                    diffusion={"enabled": True, "active": True, "listeners": 2, "server": {"ok_at": now - 5, "rtt_ms": 40}},
                    ntfy={"configured": True, "ok_at": now - 600, "fail_at": now - 30})
    rows = {r.label: (r.text, r.level) for r in _online_panel(live, t(), now).rows}
    assert rows["Diffusion en direct"][0].startswith("en direct, 2 auditeur(s) · joignable")
    assert rows["Alertes ntfy"] == ("dernier envoi raté il y a 30 s (ORT-8013)", "bad")


def test_presence_relay_client_records_success_and_failure(monkeypatch):
    from trxstation.presence import relay as prelay

    class Identity:
        pass
    r = prelay.HttpRelay("https://relais.example/racine", Identity())

    async def ok(route, fields):
        return 200, {"ok": True}

    async def down(route, fields):
        raise prelay.RelayUnavailable("délai")
    monkeypatch.setattr(r, "_post", ok)
    asyncio.run(r.post("sync", {}))
    assert r.health.to_dict()["ok_at"] is not None and r.health.to_dict()["fail_since"] is None
    monkeypatch.setattr(r, "_post", down)
    try:
        asyncio.run(r.post("sync", {}))
    except prelay.RelayUnavailable:
        pass
    assert r.health.to_dict()["code"] == "ORT-6903"


def test_monitor_texts_of_the_panel_exist_in_the_four_languages():
    root = Path(__file__).resolve().parents[1] / "trxstation" / "i18n"
    keys = [k for k in json.loads((root / "monitor.fr.json").read_text(encoding="utf-8"))
            if k.startswith(("online.", "label.online_")) or k == "panel.online"]
    assert len(keys) == 16
    for lang in ("en", "de", "es"):
        data = json.loads((root / f"monitor.{lang}.json").read_text(encoding="utf-8"))
        assert all(k in data for k in keys), lang


def test_host_info_gets_the_online_section_in_the_client_language(tmp_path):
    (tmp_path / "presence").mkdir()
    (tmp_path / "presence" / "status.json").write_text(json.dumps({"enabled": True, "server": {}}), encoding="utf-8")
    section = online.online_section(tmp_path, "en")
    assert section == {"title": "Online services", "rows": [["Group presence", "not reached yet"]]}
    assert online.online_section(tmp_path / "vide", "fr") is None
