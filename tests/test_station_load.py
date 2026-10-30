# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
from pathlib import Path

from trxstation.devtools import station_load as sl


def _process(proc: Path, pid: int, cmdline: list[str], utime: int, stime: int) -> None:
    folder = proc / str(pid)
    folder.mkdir(parents=True)
    (folder / "cmdline").write_bytes(("\0".join(cmdline) + "\0").encode())
    fields = ["S"] + ["0"] * 10 + [str(utime), str(stime)] + ["0"] * 30
    (folder / "stat").write_text(f"{pid} (python3 a b) " + " ".join(fields))


def _proc(tmp_path: Path, busy_idle: tuple[int, int], gateway: int, sectors: int) -> Path:
    proc = tmp_path
    proc.mkdir(parents=True, exist_ok=True)
    busy, idle = busy_idle
    (proc / "stat").write_text(f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 0 0 1 0 0 0 0 0 0\n")
    (proc / "meminfo").write_text("MemTotal:  3900000 kB\nMemAvailable:  2048000 kB\n")
    (proc / "diskstats").write_text(
        f" 179       0 mmcblk0 10 0 20 0 30 0 {sectors} 0 0 0 0\n"
        f" 179       1 mmcblk0p1 10 0 20 0 30 0 999999 0 0 0 0\n"
        "   7       0 loop0 1 0 2 0 3 0 777 0 0 0 0\n")
    _process(proc, 100, ["/opt/trx-remote/venv/bin/python", "-m", "trxstation.gateway.main", "--config", "x"], gateway, 0)
    _process(proc, 101, ["/usr/bin/rigctld", "-m", "1"], 5, 5)
    _process(proc, 102, ["/opt/trx-remote/venv/bin/python", "-m", "trxstation.supervisor.main"], 1, 1)
    _process(proc, 103, ["/usr/bin/bash"], 500, 500)
    return proc


def test_services_are_recognised_from_their_command_line():
    assert sl.service_of(["/usr/local/bin/rigctld", "-m", "3094"]) == "rigctld"
    assert sl.service_of(["python", "-m", "trxstation.run_rigctld"]) == "rigctld"
    assert sl.service_of(["python", "-m", "trxstation.gateway.main"]) == "passerelle"
    assert sl.service_of(["python", "-m", "trxstation.supervisor.main"]) == "superviseur"
    assert sl.service_of(["/usr/local/bin/trx-monitor"]) is None
    assert sl.service_of(["python", "-m", "trxstation.cluster.service"]) == "autres trx"
    assert sl.service_of(["/usr/bin/rigctld-wrapper"]) is None
    assert sl.service_of([]) is None


def test_one_full_core_of_gateway_and_partition_lines_ignored(tmp_path):
    before = sl.snapshot(_proc(tmp_path / "a", (1000, 3000), 200, 1000), tmp_path / "sys")
    after = sl.snapshot(_proc(tmp_path / "b", (1100, 3300), 300, 3048), tmp_path / "sys")
    after.when = before.when + 1.0
    sample = sl.delta(before, after, clk_tck=100)
    assert round(sample.cpu_pct) == 25                   # 100 occupés sur 400
    assert round(sample.services_pct["passerelle"]) == 100
    assert sample.services_pct["rigctld"] == 0.0
    assert sample.write_kb_s == 1024.0                   # 2048 secteurs de mmcblk0 seul, en 1 s
    assert sample.mem_available_mb == 2000.0


def test_measuring_tool_does_not_count_itself(tmp_path):
    proc = _proc(tmp_path, (1, 1), 0, 0)
    _process(proc, 104, ["python", "-m", "trxstation.devtools.station_load"], 50, 50)
    assert sl.read_services(proc, skip_pid=104)["autres trx"] == 0
    assert sl.read_services(proc)["autres trx"] == 100


def test_throttled_flags_of_the_raspberry_pi():
    assert sl.parse_throttled("throttled=0x50005\n") == 0x50005
    assert sl.parse_throttled("error") is None
    text = sl.describe_throttled(0x50005)
    assert "EN CE MOMENT : sous-tension, ralenti" in text
    assert "depuis le démarrage : sous-tension, ralenti" in text
    assert sl.describe_throttled(0) == "aucun ralentissement"
    assert "illisible" in sl.describe_throttled(None)


def test_summary_reports_worst_values_and_megabytes_per_hour():
    def sample(cpu, temp):
        return sl.Sample(cpu, {"passerelle": cpu * 2}, 1024.0 / 3600, 1500.0, temp, 1500.0, 0)
    summary = sl.Summary([sample(10.0, 50.0), sample(30.0, 60.0)], 600.0)
    text = summary.text()
    assert "pire  30.0 %" in text and "pire  60.0 %" in text
    assert "pire 60.0 °C" in text
    assert "1.0 Mo par heure" in text
    assert "aucun ralentissement" in text
    assert sl.Summary().text() == "Aucune mesure."
