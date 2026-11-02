# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Santé de la machine de la station (bargraph state.host) et synthèse host_info : calculs sans matériel."""
from __future__ import annotations

from trxstation import hostinfo as h


def test_health_shows_the_measure_closest_to_its_red_limit():
    assert h.health({"cpu": 10, "mem": 40, "disk": 30, "temp": 45}) == (0.476, "ok", "temp")     # 45/85*0,9
    assert h.health({"cpu": 80, "mem": 40, "disk": 30, "temp": None})[1:] == ("warn", "cpu")
    assert h.health({"cpu": 10, "mem": 91, "disk": 30, "temp": 45}) == (0.91, "bad", "mem")
    assert h.health({"cpu": 90, "mem": 0, "disk": 0, "temp": 0})[0] == 0.9                      # rouge à 90 % de la barre
    assert h.health({"cpu": None, "mem": None, "disk": None, "temp": None}) == (0.0, "ok", "")   # rien de lisible
    assert h.health({"cpu": 5}, throttled_now=True) == (1.0, "bad", "power")                     # Pi en sous-tension
    assert h.health({"disk": 120})[0] == 1.0


def test_raspberry_pi_throttling_flags():
    assert h.parse_throttled("throttled=0x50005\n") == 0x50005
    assert h.parse_throttled("erreur") is None
    assert h.describe_throttled(0) == "normale"
    assert h.describe_throttled(0x50005) == "EN CE MOMENT : sous-tension, ralenti ; depuis le démarrage : sous-tension, ralenti"
    assert h.describe_throttled(0x10000) == "depuis le démarrage : sous-tension"


def test_linux_readings_from_proc(tmp_path):
    (tmp_path / "meminfo").write_text("MemTotal:  8000000 kB\nMemFree: 1000 kB\nMemAvailable:  2000000 kB\n", encoding="ascii")
    used, total = h.memory_linux(tmp_path / "meminfo")
    assert round(used) == 75 and total == 8000000 * 1024
    assert h.memory_linux(tmp_path / "absent") is None
    (tmp_path / "uptime").write_text("93784.5 1000.0\n", encoding="ascii")
    assert h.uptime_s(tmp_path) == 93784.5 or h._windows()
    assert h.format_uptime(93784.5) == "1 j 2 h 03 min" and h.format_uptime(59) == "0 h 00 min"


def test_cpu_meter_needs_two_readings(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "_windows", lambda: False)
    stat = tmp_path / "stat"
    meter = h.CpuMeter(tmp_path)
    stat.write_text("cpu  100 0 100 800 0 0 0 0 0 0\n", encoding="ascii")
    assert meter.read() is None
    stat.write_text("cpu  150 0 150 900 0 0 0 0 0 0\n", encoding="ascii")                  # 100 occupés sur 200
    assert meter.read() == 50.0


def test_summary_is_cached_and_reads_throttling_rarely():
    now = [0.0]
    calls = []
    monitor = h.HostMonitor(clock=lambda: now[0], throttled=lambda: calls.append(1) or 0x0)
    first = monitor.summary()
    assert set(first) == {"cpu_pct", "mem_pct", "disk_pct", "temp_c", "throttled", "load", "level", "worst"}
    assert first["level"] in ("ok", "warn", "bad") and 0.0 <= first["load"] <= 1.0
    now[0] = 1.0
    assert monitor.summary() is first                                    # moins de 2 s : même résumé
    now[0] = 10.0
    monitor.summary()
    assert len(calls) == 1 and first["throttled"] is False               # vcgencmd : toutes les 30 s au plus
    now[0] = 40.0
    monitor.summary()
    assert len(calls) == 2


def test_details_are_written_sections_without_ports(tmp_path):
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.rig.port = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_IC-7300_13003336-if00"
    sections = h.host_details(h.HostMonitor(throttled=lambda: None), cfg, None, "4.7.2", {"VD_METER": 14.368, "SQL": 0.0})
    titles = [s["title"] for s in sections]
    assert titles == ["Machine", "Charge en ce moment", "Station", "Son"]
    rows = {label: value for s in sections for label, value in s["rows"]}
    assert rows["Hamlib"] == "4.7.2" and rows["TRX distant"]
    assert rows["Poste"] == f"modèle Hamlib {cfg.rig.model}\nalimentation 14,4 V"                 # modèle, puis tension
    assert h.rig_vitals_text({"VD_METER": 13.8, "TEMP_METER": 41.6}) == "alimentation 13,8 V, température 42 °C"
    assert h.rig_vitals_text({"TEMP_METER": True}) == "" and h.rig_vitals_text(None) == ""
    assert all(isinstance(v, str) for v in rows.values())
    assert "13003336" not in str(sections)                               # numéro de série de l'interface : jamais
