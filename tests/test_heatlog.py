# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Historique de chauffe (heatlog.py, étape 377) : faux /proc et /sys, comme minix-bzh (i3-N300, 8 cœurs)."""
import json

from trxstation import heatlog
from trxstation.diagnostics import System
from trxstation.heatlog import HeatLog, program_name
from trxstation.report import heat_history
from trxstation.supervisor.core import Supervisor


class FakeHost:
    """Faux /proc et /sys : temps processeur des programmes et des cœurs avancés à la main."""

    def __init__(self, root):
        self.proc, self.sys = root / "proc", root / "sys"
        self.proc.mkdir(parents=True)
        self.cores = [[0, 0] for _ in range(4)]            # tics occupés, tics inactifs
        self.progs: dict[int, list] = {}
        self.temp(47000, cores=(42000, 41000, 41000, 44000))
        (self.proc / "loadavg").write_text("0.79 0.86 0.89 2/600 1234\n")
        freq = self.sys / "devices" / "system" / "cpu" / "cpu0" / "cpufreq"
        freq.mkdir(parents=True)
        (freq / "scaling_cur_freq").write_text("3800000\n")
        self.write()

    def temp(self, package, cores):
        chip = self.sys / "class" / "hwmon" / "hwmon2"
        chip.mkdir(parents=True, exist_ok=True)
        (chip / "name").write_text("coretemp\n")
        for i, (label, milli) in enumerate([("Package id 0", package)] + [(f"Core {n}", c) for n, c in enumerate(cores)], 1):
            (chip / f"temp{i}_input").write_text(f"{milli}\n")
            (chip / f"temp{i}_label").write_text(label + "\n")
        nvme = self.sys / "class" / "hwmon" / "hwmon1"
        nvme.mkdir(parents=True, exist_ok=True)
        (nvme / "name").write_text("nvme\n")
        (nvme / "temp1_input").write_text("42850\n")
        (nvme / "temp1_label").write_text("Composite\n")

    def spawn(self, pid, comm, cmdline=b""):
        self.progs[pid] = [comm, cmdline, 0]

    def run(self, seconds, usage: dict[int, float], core_busy: list[float]):
        """`usage` : pid -> part d'un cœur ; `core_busy` : part occupée de chaque cœur (100 tics par seconde)."""
        for pid, share in usage.items():
            self.progs[pid][2] += round(share * 100 * seconds)
        for core, share in zip(self.cores, core_busy):
            core[0] += round(share * 100 * seconds)
            core[1] += round((1 - share) * 100 * seconds)
        self.write()

    def write(self):
        busy = sum(c[0] for c in self.cores)
        idle = sum(c[1] for c in self.cores)
        lines = [f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0"]
        lines += [f"cpu{i} {b} 0 0 {d} 0 0 0 0 0 0" for i, (b, d) in enumerate(self.cores)]
        (self.proc / "stat").write_text("\n".join(lines) + "\nintr 0\n")
        for entry in self.proc.iterdir():
            if entry.name.isdigit() and int(entry.name) not in self.progs:
                for f in entry.iterdir():
                    f.unlink()
                entry.rmdir()
        for pid, (comm, cmdline, ticks) in self.progs.items():
            d = self.proc / str(pid)
            d.mkdir(exist_ok=True)
            fields = ["S"] + ["0"] * 10 + [str(ticks), "0"] + ["0"] * 30
            (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n")
            (d / "cmdline").write_bytes(cmdline)


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0


def make(tmp_path):
    host, clock = FakeHost(tmp_path / "host"), Clock()
    log = HeatLog(tmp_path / "etat" / "chauffe.jsonl", proc_root=host.proc, sys_root=host.sys, wall=lambda: clock.t)
    log.hz = 100
    return host, clock, log


def lines(log):
    return [json.loads(l) for l in log.path.read_text(encoding="utf-8").splitlines()]


def test_program_names_never_carry_paths_or_arguments():
    assert program_name("sdr-core", b"/opt/x/sdr-core\0--port\0/home/bob/secret\0") == "sdr-core"
    assert program_name("python", b"/home/bob/venv/bin/python\0-m\0trxstation.gateway\0") == "python:trxstation.gateway"
    assert program_name("python3.11", b"python3.11\0-u\0/home/bob/ais/ais-rssi.py\0--key\0x\0") == "python:ais-rssi.py"
    assert program_name("trx-gateway", b"/usr/bin/python3\0/opt/venv/bin/trx-gateway\0") == "trx-gateway"
    assert program_name("bash", b"bash\0-c\0rm -rf /tmp/x\0") == "bash:-c"
    assert program_name("python", b"") == "python"
    assert program_name("kworker/u32:4-kvfree_rcu_reclaim", b"") == "noyau (kworker)"


def test_one_line_every_ten_seconds_with_the_busiest_programs(tmp_path):
    host, clock, log = make(tmp_path)
    host.spawn(10, "sdr-core")
    host.spawn(11, "AIS-catcher")
    host.spawn(12, "python", b"python\0-m\0trxstation.gateway\0")
    host.spawn(13, "sshd", b"")
    assert log.tick(0.0) is None                   # première lecture : la référence, rien d'écrit
    assert not log.path.exists()
    clock.t += 10
    host.run(10, {10: 0.15, 11: 0.95, 12: 0.11, 13: 0.001}, [0.9, 0.2, 0.1, 0.1])
    assert log.tick(5.0) is None                   # pas encore 10 s
    line = log.tick(10.0)
    assert line == lines(log)[0]
    assert line["temp_c"] == 47.0 and line["capteur"] == "coretemp Package id 0"
    assert line["top"] == [["AIS-catcher", 95.0, 1], ["sdr-core", 15.0, 1], ["python:trxstation.gateway", 11.0, 1]]
    assert line["cpu_pct"] == 32.5 and line["charge_1min"] == 0.79 and line["mhz_max"] == 3800
    assert "capteurs" not in line and "chaud" not in line          # ligne ordinaire : courte


def test_hot_sample_at_once_with_every_sensor_and_core(tmp_path):
    host, clock, log = make(tmp_path)
    host.spawn(11, "AIS-catcher")
    log.tick(0.0)
    clock.t += 3
    host.temp(83000, cores=(80000, 79000, 84000, 70000))
    host.run(3, {11: 1.0}, [0.1, 0.1, 1.0, 0.1])
    line = log.tick(3.0, hot=True)                 # passage du seuil : relevé sans attendre les 10 s
    assert line["chaud"] is True
    assert line["plus_chaud"] == ["coretemp Core 2", 84.0]
    assert line["capteurs"]["nvme Composite"] == 42.85 or line["capteurs"]["nvme Composite"] == 42.9
    assert line["coeurs_pct"] == [10.0, 10.0, 100.0, 10.0]
    assert line["top"][0][:2] == ["AIS-catcher", 100.0]
    assert log.tick(5.0, hot=True) is None         # toujours chaud : rythme normal ensuite
    summary = log.summary()
    assert "coretemp Core 2 (84 °C)" in summary and "cœur le plus chargé : 100 %" in summary
    assert "AIS-catcher 100 %" in summary


def test_program_started_between_two_samples_counts(tmp_path):
    host, clock, log = make(tmp_path)
    log.tick(0.0)
    host.spawn(20, "AIS-catcher")                  # relancé souvent : né après le premier relevé
    clock.t += 10
    host.run(10, {20: 0.6}, [0.6, 0, 0, 0])
    assert log.tick(10.0)["top"] == [["AIS-catcher", 60.0, 1]]


def test_reused_pid_is_not_a_negative_number(tmp_path):
    host, clock, log = make(tmp_path)
    host.spawn(30, "vieux")
    host.run(100, {30: 1.0}, [1, 0, 0, 0])
    log.tick(0.0)
    host.progs[30] = ["neuf", b"", 50]             # même pid, autre programme
    clock.t += 10
    host.write()
    assert log.tick(10.0)["top"] == [["neuf", 5.0, 1]]


def test_kernel_workers_renamed_on_the_fly_are_grouped_and_not_counted_twice(tmp_path):
    host, clock, log = make(tmp_path)
    host.spawn(40, "kworker/1:1-events")
    host.spawn(41, "kworker/u32:3-flush-259:0")
    host.run(500, {40: 0.5, 41: 0.5}, [1, 0, 0, 0])     # 250 s de temps avant le premier relevé
    log.tick(0.0)
    host.progs[40][0] = "kworker/1:1-mm_percpu_wq"     # le noyau renomme le fil selon sa tâche
    clock.t += 10
    host.run(10, {40: 0.3, 41: 0.1}, [0.4, 0, 0, 0])
    assert log.tick(10.0)["top"] == [["noyau (kworker)", 40.0, 2]]


def test_file_is_rotated(tmp_path, monkeypatch):
    host, clock, log = make(tmp_path)
    log.max_bytes = 300
    for i in range(12):
        clock.t += 10
        host.run(10, {}, [0.1] * 4)
        log.tick(10.0 * i)
    names = sorted(p.name for p in log.path.parent.iterdir())
    assert names == ["chauffe.jsonl", "chauffe.jsonl.1", "chauffe.jsonl.2"]


def test_nothing_without_proc(tmp_path):
    log = HeatLog(tmp_path / "chauffe.jsonl", proc_root=tmp_path / "absent", sys_root=tmp_path / "absent")
    assert not log.available
    assert log.tick(0.0) is None and log.tick(20.0) is None and log.summary() == ""


def test_report_joins_the_last_day(tmp_path, monkeypatch):
    monkeypatch.setattr("trxstation.report.HEAT_LINES", 3)
    (tmp_path / "chauffe.jsonl.1").write_text("a\nb\n", encoding="utf-8")
    (tmp_path / "chauffe.jsonl").write_text("c\nd\n", encoding="utf-8")
    assert heat_history(System(), tmp_path) == "b\nc\nd\n"
    assert heat_history(System(), tmp_path / "vide") is None


def test_supervisor_alert_names_the_hot_sensor_and_programs(tmp_path):
    from test_supervisor_core import World
    host, clock, log = make(tmp_path)
    host.spawn(11, "AIS-catcher")
    w = World(tmp_path)
    w.sup = Supervisor(w.cfg, read_status=lambda: w.status, probe_rig=lambda: w.rig, actions=w, store=w.store,
                       clock=lambda: w.now, wall=lambda: w.wall, port_exists=lambda p: True,
                       read_temp=lambda: w.temp, heat=log)
    w.run(0.25)                                                  # première lecture (référence)
    w.run(1)
    clock.t += 5
    host.temp(83000, cores=(80000, 79000, 84000, 70000))
    host.run(5, {11: 0.97}, [0.1, 0.1, 1.0, 0.1])
    w.temp = 83.0
    details = []
    w.notify = lambda code, detail="", key="": details.append((code, detail))
    w.run(3)
    assert w.calls == []
    hot = [d for c, d in details if c == "ORT-1010"]
    assert hot and hot[0].startswith("83 °C (seuil 70 °C) — capteur le plus chaud : coretemp Core 2 (84 °C)")
    assert "AIS-catcher 97 %" in hot[0]


def test_supervisor_survives_an_unwritable_history(tmp_path, monkeypatch):
    from test_supervisor_core import World
    host, clock, log = make(tmp_path)
    w = World(tmp_path)
    w.sup.heat = log
    events = []
    monkeypatch.setattr("trxstation.supervisor.core.emit_event", lambda code, **kw: events.append(code))

    def boom(line):
        raise PermissionError("lecture seule")
    log.write = boom
    for _ in range(4):
        clock.t += 10
        host.run(10, {}, [0.1] * 4)
        w.now += 10
        w.sup.step()
    assert events == ["ORT-1009"]                  # signalé une seule fois, supervision intacte


def test_constants():
    assert heatlog.EVERY_S == 10.0


def test_hot_just_after_a_sample_waits_one_second_only(tmp_path):
    host, clock, log = make(tmp_path)
    host.spawn(11, "AIS-catcher")
    log.tick(0.0)
    clock.t += 10
    host.run(10, {11: 0.2}, [0.2, 0, 0, 0])
    assert "chaud" not in log.tick(10.0)
    assert log.tick(10.5, hot=True) is None        # trop tôt : rien de faux
    clock.t += 1
    host.run(1, {11: 1.0}, [1, 0, 0, 0])
    line = log.tick(11.0, hot=True)                # toujours au-dessus : relevé chaud sans attendre 10 s
    assert line["chaud"] is True and line["top"][0][:2] == ["AIS-catcher", 100.0]
