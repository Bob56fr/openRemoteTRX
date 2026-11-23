# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Ports USB (usbcheck.py, étape 384) : faux /sys calqué sur minix-bzh (relevé du 2026-11-24 : IC-7300MK2 derrière
son hub interne à 12 Mbit/s, deux RSP2 et le Bluetooth sur le même bus USB 2, bus 1 libre, bus 2 et 4 en USB 3)."""
from pathlib import Path

import pytest

from trxstation import usbcheck
from trxstation.diagnostics import OK, WARN, INFO, System, check_usb_ports
from trxstation.i18n import tool_translator
from trxstation.monitor.model import Snapshot, SystemInfo, build_panels


def _dev(root: Path, name: str, **attrs) -> None:
    d = root / "bus" / "usb" / "devices" / name
    d.mkdir(parents=True)
    for key, value in attrs.items():
        if key == "interfaces":
            for i, cls in enumerate(value):
                sub = d / f"interface{i}"    # « 3-2.1:1.0 » sous Linux ; « : » refusé par Windows
                sub.mkdir()
                (sub / "bInterfaceClass").write_text(cls + "\n")
            continue
        (d / key).write_text(f"{value}\n")


def minix(root: Path, *, sdr_speed: str = "480", sdr_parent: str = "") -> Path:
    for bus, speed in ((1, "480"), (2, "20000"), (3, "480"), (4, "10000")):
        _dev(root, f"usb{bus}", idVendor="1d6b", idProduct="0002", busnum=bus, speed=speed, bDeviceClass="09")
    _dev(root, "3-10", idVendor="8087", idProduct="0026", busnum=3, speed="12", bMaxPower="100mA", bDeviceClass="e0",
         interfaces=["e0"])
    _dev(root, "3-2", idVendor="0424", idProduct="2422", busnum=3, speed="12", bMaxPower="2mA", bDeviceClass="09",
         bmAttributes="e0", interfaces=["09"])
    _dev(root, "3-2.1", idVendor="0c26", idProduct="0052", busnum=3, speed="12", bMaxPower="100mA", product="IC-7300MK2",
         serial="IC-7300MK2 13003336", interfaces=["02", "0a"])
    _dev(root, "3-2.2", idVendor="0d8c", idProduct="0013", busnum=3, speed="12", bMaxPower="100mA",
         product="USB Audio Device", interfaces=["01", "01", "01", "03"])
    _dev(root, "3-3", idVendor="1df7", idProduct="3010", busnum=3, speed="480", bMaxPower="400mA", serial="AIS0001",
         interfaces=["ff"])
    station = sdr_parent + "3-6" if not sdr_parent else sdr_parent
    _dev(root, station, idVendor="1df7", idProduct="3010", busnum=3, speed=sdr_speed, bMaxPower="400mA",
         serial="SDR0002", interfaces=["ff"])
    return root


@pytest.fixture
def fr(monkeypatch):
    monkeypatch.setenv("TRX_LANG", "fr")
    return tool_translator("monitor")


def test_minix_today_is_fine_and_the_station_sdr_is_recognised(tmp_path, monkeypatch, fr):
    monkeypatch.setattr(usbcheck, "rig_device_path", lambda port, root: "3-2.1" if port else None)
    r = usbcheck.analyze(minix(tmp_path), rig_port="/dev/ttyACM0", sdr_serial="SDR0002", sdr_fs=2_000_000)
    bus3 = next(b for b in r.buses if b.number == 3)
    assert bus3.speed == 480 and round(bus3.mbit) == 131 and round(bus3.load_pct) == 47   # 2 × 64 + son 3
    assert r.findings == [] and r.level == "ok"
    assert usbcheck.summary(r, fr) == ("OK · bus le plus chargé : 47 % (estimation)", "ok")
    lines = usbcheck.bus_lines(r, fr)
    assert lines == ["bus 3 (USB 2, 480 Mbit/s partagés) : IC-7300MK2 (poste), USB Audio Device (son), SDRplay (SDR), "
                     "SDRplay (SDR de la station) · ~131 Mbit/s estimés (47 %)"]
    assert "13003336" not in " ".join(lines) and "SDR0002" not in " ".join(lines)          # jamais de numéro de série


def test_two_sdr_at_eight_megahertz_saturate_a_usb2_bus(tmp_path, fr):
    r = usbcheck.analyze(minix(tmp_path), sdr_fs=8_000_000)
    assert [f.code for f in r.findings] == ["saturated"] and r.level == "bad"
    text, level = usbcheck.summary(r, fr)
    assert level == "bad" and text == "bus 3 saturé : ~515 Mbit/s estimés pour ~280 utilisables (184 %)"


def test_busy_bus_is_a_warning(tmp_path):
    r = usbcheck.analyze(minix(tmp_path), sdr_fs=3_200_000)   # 2 × 102 + 3 = 208 Mbit/s : 74 %
    assert [(f.code, f.level) for f in r.findings] == [("busy", "warn")]


def test_sdr_slowed_down_by_an_old_hub_or_cable(tmp_path, fr):
    r = usbcheck.analyze(minix(tmp_path, sdr_speed="12"), sdr_fs=2_000_000)
    assert ("sdr_slow", "bad") in [(f.code, f.level) for f in r.findings]
    assert usbcheck.finding_text(r.findings[-1], fr) == "SDRplay ralenti à 12 Mbit/s (port 3-6) : hub ou câble USB 1.1"


def test_sdr_behind_the_transceiver_hub(tmp_path, monkeypatch, fr):
    monkeypatch.setattr(usbcheck, "rig_device_path", lambda port, root: "3-2.1")
    root = minix(tmp_path, sdr_parent="3-2.3")
    (root / "bus" / "usb" / "devices" / "3-2" / "bmAttributes").write_text("a0\n")   # hub alimenté par le bus
    r = usbcheck.analyze(root, rig_port="/dev/ttyACM0", sdr_fs=2_000_000)
    hub = [f for f in r.findings if f.code == "sdr_on_rig_hub"]
    assert hub and usbcheck.finding_text(hub[0], fr) == "SDRplay branché sur le même hub que le poste (port 3-2.3)"
    power = [f for f in r.findings if f.code == "hub_power"]            # 100 + 100 + 400 mA sur un hub du bus
    assert power and power[0].fields == {"port": "3-2", "ma": 600, "max": 500}


def test_self_powered_hub_is_not_a_power_problem(tmp_path, monkeypatch):
    root = minix(tmp_path, sdr_parent="3-2.3")
    (root / "bus" / "usb" / "devices" / "3-2" / "bmAttributes").write_text("e0\n")
    (root / "bus" / "usb" / "devices" / "3-2" / "bmAttributes").write_text("a0\n")   # bit 6 à 0 : alimenté par le bus
    assert any(f.code == "hub_power" for f in usbcheck.analyze(root).findings)
    (root / "bus" / "usb" / "devices" / "3-2" / "bmAttributes").write_text("e0\n")   # bit 6 à 1 : bloc secteur
    assert not any(f.code == "hub_power" for f in usbcheck.analyze(root).findings)


def test_nothing_outside_linux(tmp_path):
    assert usbcheck.analyze(tmp_path / "absent") is None
    assert usbcheck.cached_reader(tmp_path / "absent")() is None


def test_reader_keeps_the_result_ten_seconds(tmp_path):
    now = [0.0]
    read = usbcheck.cached_reader(minix(tmp_path), sdr_fs=2_000_000, clock=lambda: now[0])
    first = read()
    now[0] = 5.0
    assert read() is first
    now[0] = 11.0
    assert read() is not first


def test_dashboard_computer_card_has_the_usb_line(tmp_path, fr):
    report = usbcheck.analyze(minix(tmp_path), sdr_fs=8_000_000)
    panels = build_panels(Snapshot(None, False, None, None, SystemInfo(host="minix"), usb=report), t=fr)
    card = next(p for p in panels if p.key == "materiel")
    row = next(r for r in card.rows if r.label == "Ports USB")
    assert row.level == "bad" and row.text.startswith("bus 3 saturé")
    plain = build_panels(Snapshot(None, False, None, None, SystemInfo(host="minix")), t=fr)
    assert not any(r.label == "Ports USB" for p in plain for r in p.rows)    # Windows : pas de ligne


def test_diagnostic_lists_the_buses_and_explains_the_fix(tmp_path, fr):
    class Fake(System):
        platform = "linux"
        sys_root = str(minix(tmp_path))
    checks = check_usb_ports(Fake(), None)
    assert [c.status for c in checks] == [INFO, OK]
    sat = minix(tmp_path / "b")
    from trxstation import config as cfgmod
    from trxstation.setup_wizard import dummy_config
    cfg = dummy_config()
    cfg.sdr = cfgmod.Sdr(enabled=True, serial="SDR0002", sample_rate_hz=8_000_000)

    class Fake8(System):
        platform = "linux"
        sys_root = str(sat)
    checks = check_usb_ports(Fake8(), cfg)
    warn = [c for c in checks if c.status == WARN]
    assert warn and "menu 2.4" in warn[0].fix and "prise bleue" in warn[0].fix
