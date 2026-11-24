# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
from trxstation.dashboard import view


def vitals(**over):
    v = view.vitals_template()
    v["station"].update(ok=True, age_s=0.3, version="0.279.0")
    v["rig"].update(model="IC-7300MK2", connected=True, power="on", freq_hz=14_195_000, mode="USB", passband_hz=2400,
                    strength_db=-12, vfo="A", vfo_a_hz=14_195_000, split=False, tuner=True, nb=False, nr=True,
                    nr_level="5", agc="LENTE")
    for k, d in over.items():
        v[k].update(d) if isinstance(d, dict) else v.__setitem__(k, d)
    return v


INFO = {"internet_pct": 99.0, "alerts_warn": 1, "alerts_crit": 0}
ACCOUNTS = [{"id": "S25", "pseudo": None}, {"id": "PC", "pseudo": None}, {"id": "tablette", "pseudo": "BOB"}, {"id": "Android8", "pseudo": "Andro-8"}]
CFG = {"station_name": "minix-bzh", "accounts": ACCOUNTS, "version": "0.1.0"}


def test_formats():
    assert view.fmt_freq(14_195_000) == "14.195.000"
    assert view.fmt_freq(7_074_000) == "7.074.000"
    assert view.band_of(14_195_000) == "20 m" and view.band_of(15_000_000) is None
    assert view.smeter(0)["text"] == "S9" and view.smeter(-12)["text"] == "S7"
    assert view.smeter(20)["text"] == "S9+20"
    assert view.smeter(-100)["frac"] == 0 and view.smeter(100)["frac"] == 1
    assert view.fmt_uptime(3 * 86400 + 4 * 3600) == "3 j 04 h"


def test_reception():
    s = view.build_state(vitals(), INFO, CFG)
    assert s["mode"] == "rx" and s["banner"] is None and s["tx"] is None
    assert s["rig"]["freq_text"] == "14.195.000" and "20 m" in s["rig"]["detail_text"]
    labels = {f["label"]: f for f in s["rig"]["functions"]}
    assert labels["Tuner"]["on"] and not labels["NB"]["on"]
    assert labels["NR"]["value"] == "5" and labels["NB"].get("value") is None
    assert "VOX" not in labels                      # fonction que le poste ne déclare pas : masquée
    assert labels["VFO A · actif"]["on"]


def test_emission_and_terminals():
    v = vitals(ptt={"tx": True, "elapsed_s": 47, "tot_s": 90, "warn_s": 80, "owner": "S25"},
               operators=[{"id": "S25", "name": "S25", "tx": True}, {"id": "PC", "name": "PC", "tx": False}])
    s = view.build_state(v, INFO, CFG)
    assert s["mode"] == "tx" and s["tx"]["elapsed_s"] == 47
    assert s["rig"]["detail_text"] == "émet : S25"
    assert [(t["name"], t["state"]) for t in s["terminals"]] == [("S25", "tx"), ("PC", "on"), ("tablette", "off"), ("Android8", "off")]
    assert s["rig"]["smeter"] is None


def test_terminal_by_account_id_with_label():
    v = vitals(operators=[{"id": "tablette", "name": "BOB", "tx": False}, {"id": "S25", "name": "S25", "tx": True}])
    s = view.build_state(v, INFO, CFG)
    assert [(t["name"], t["state"], t["note"]) for t in s["terminals"]] == [
        ("S25", "tx", "émet"), ("PC", "off", None), ("tablette", "on", "BOB"), ("Android8", "off", "Andro-8")]


def test_unknown_terminal_is_added():
    s = view.build_state(vitals(operators=[{"name": "Portable", "tx": False}]), INFO, CFG)
    assert [t["name"] for t in s["terminals"]] == ["S25", "PC", "tablette", "Android8", "Portable"]


def test_safe_mode_hides_rig_state():
    v = vitals(safe={"active": True, "reason": "Poste injoignable."})
    s = view.build_state(v, INFO, CFG)
    assert s["mode"] == "safe" and s["banner"]["level"] == "crit"
    assert s["rig"]["freq_text"] is None
    assert all(not f["on"] for f in s["rig"]["functions"])
    assert s["rig"]["tiles"][0]["value"] == "Bloquée"


def test_station_muette():
    v = vitals(station={"ok": False, "age_s": 12})
    s = view.build_state(v, INFO, CFG)
    assert s["mode"] == "nolink" and s["stale"] and "12 s" in s["banner"]["text"]


def test_pc_levels():
    v = vitals(host={"cpu": 95, "mem": 40, "temp": 80, "uptime_s": 7200, "os": "Debian 13"})
    s = view.build_state(v, {"internet_pct": None, "alerts_warn": 0, "alerts_crit": 2}, CFG)
    assert s["pc"]["cpu"]["level"] == "crit" and s["pc"]["temp"]["level"] == "warn"
    assert s["pc"]["alerts"] == {"text": "2", "level": "crit"}
    assert s["pc"]["level"] == "crit" and s["pc"]["internet"]["text"] == "—"
