# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Température du processeur (cpu_temp.py) : arborescence /sys relevée sur minix-bzh (Intel i3-N300, Debian 13),
où thermal_zone0 est le capteur ACPI de la carte mère (27,8 °C) et coretemp le processeur (42 °C)."""
from trxstation.cpu_temp import cpu_celsius, read_cpu_temp


def _hwmon(root, index, name, sensors):
    chip = root / "class" / "hwmon" / f"hwmon{index}"
    chip.mkdir(parents=True)
    (chip / "name").write_text(name + "\n")
    for i, (label, milli) in enumerate(sensors, 1):
        (chip / f"temp{i}_input").write_text(f"{milli}\n")
        if label:
            (chip / f"temp{i}_label").write_text(label + "\n")


def _zone(root, index, kind, milli):
    zone = root / "class" / "thermal" / f"thermal_zone{index}"
    zone.mkdir(parents=True)
    (zone / "type").write_text(kind + "\n")
    (zone / "temp").write_text(f"{milli}\n")


def minix(root):
    _zone(root, 0, "acpitz", 27800)
    _zone(root, 1, "iwlwifi_1", 46000)
    _zone(root, 2, "x86_pkg_temp", 42000)
    _hwmon(root, 0, "acpitz", [("", 27800)])
    _hwmon(root, 1, "nvme", [("Composite", 41850), ("Sensor 2", 44850)])
    _hwmon(root, 2, "iwlwifi_1", [("", 44000)])
    _hwmon(root, 3, "coretemp", [("Package id 0", 42000), ("Core 0", 40000), ("Core 1", 39000)])


def test_minix_bzh_reads_the_processor_package_not_the_motherboard(tmp_path):
    minix(tmp_path)
    found = read_cpu_temp(tmp_path)
    assert (found.celsius, found.source) == (42.0, "coretemp Package id 0")


def test_hottest_core_without_package_label_and_amd_tctl(tmp_path):
    _hwmon(tmp_path / "intel", 0, "coretemp", [("Core 0", 51000), ("Core 1", 57000)])
    assert read_cpu_temp(tmp_path / "intel").celsius == 57.0
    _hwmon(tmp_path / "amd", 0, "k10temp", [("Tccd1", 60000), ("Tctl", 55500)])
    assert read_cpu_temp(tmp_path / "amd").source == "k10temp Tctl"


def test_thermal_zone_of_the_processor_as_fallback_never_acpitz(tmp_path):
    _zone(tmp_path / "zones", 0, "acpitz", 27800)
    _zone(tmp_path / "zones", 1, "x86_pkg_temp", 43000)
    assert read_cpu_temp(tmp_path / "zones").source == "thermal x86_pkg_temp"
    _zone(tmp_path / "pi", 0, "cpu-thermal", 48300)                        # Raspberry Pi
    assert cpu_celsius(tmp_path / "pi") == 48.3
    _zone(tmp_path / "acpi", 0, "acpitz", 27800)
    assert read_cpu_temp(tmp_path / "acpi") is None                         # carte mère seule : inconnue
    assert read_cpu_temp(tmp_path / "rien") is None                         # Windows, machine virtuelle


def test_absurd_values_are_ignored(tmp_path):
    _hwmon(tmp_path, 0, "coretemp", [("Package id 0", -273000), ("Core 0", 41000)])
    assert read_cpu_temp(tmp_path).celsius == 41.0
