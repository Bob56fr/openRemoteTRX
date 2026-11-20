# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Garde de fin (cahier du Microsoft Store § 4.1) : tests de panne avec de VRAIS processus et un faux rigctld.

Le superviseur tué net (mise à jour forcée, désinstallation, Gestionnaire des tâches) laisse rigctld orphelin et le
poste EN ÉMISSION : la garde doit le remettre en réception, n'arrêter QUE le rigctld de la station, et la station ne
doit jamais démarrer sans elle."""
import json
import subprocess
import sys
import time

import pytest

from trxstation import packaging
from trxstation.errors import codes
from trxstation.setup_wizard import dummy_config
from trxstation.supervisor import guard
from trxstation.supervisor.backends import GuardUnavailable, ManagedBackend
from trxstation.supervisor.rigctl import RigctlProbe

from test_managed import EXITER, SLEEPER, alive, free_port, wait_until
from test_supervisor_io import ServerThread


def _spawn(cmd):
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _guard_cmd(parent: int, port: int, state_dir) -> list[str]:
    return [sys.executable, "-m", "trxstation.supervisor.guard", "--parent", str(parent), "--port", str(port),
            "--state-dir", str(state_dir)]


# --------------------------------------------------------------------------- la garde seule

def test_guard_puts_the_rig_back_to_receive_when_the_supervisor_is_killed(tmp_path):
    srv = ServerThread().start()
    supervisor = _spawn(SLEEPER)
    rigctld = _spawn(SLEEPER)                        # tient lieu du rigctld lancé par la station
    keeper = None
    try:
        guard.write_rigctld_pid(tmp_path, rigctld.pid, None)
        srv.fake.ptt = 1                                # station tuée PENDANT une émission
        keeper = _spawn(_guard_cmd(supervisor.pid, srv.fake.port, tmp_path))
        time.sleep(1.0)
        assert srv.fake.ptt == 1 and keeper.poll() is None, "la garde ne fait rien tant que le superviseur vit"
        supervisor.kill()                               # comme une fermeture forcée du paquet
        assert wait_until(lambda: srv.fake.ptt == 0, 10), "poste resté en émission"
        assert keeper.wait(10) == 0
        assert wait_until(lambda: rigctld.poll() is not None, 5), "rigctld de la station non arrêté"
    finally:
        for proc in (supervisor, rigctld, keeper):
            if proc is not None and proc.poll() is None:
                proc.kill()
        srv.stop()


def test_guard_reports_an_unconfirmed_receive_when_the_rig_ignores_t0(tmp_path):
    srv = ServerThread().start()
    gone = _spawn(EXITER)
    gone.wait(10)
    events = []
    try:
        srv.fake.ptt, srv.fake.ignore_unkey = 1, True
        rc = guard.run(gone.pid, "127.0.0.1", srv.fake.port, tmp_path, retry_s=0.5,
                       notify=lambda code, **ctx: events.append((code, ctx)))
        assert rc == 1
        assert events and events[0][0] == codes.ORT_8028 and events[0][1]["ptt_avant"] == "émission"
    finally:
        srv.stop()


def test_guard_reports_receive_when_rigctld_is_unreachable_as_unconfirmed(tmp_path):
    gone = _spawn(EXITER)
    gone.wait(10)
    events = []
    rc = guard.run(gone.pid, "127.0.0.1", free_port(), tmp_path, retry_s=0.3,
                   probe=RigctlProbe("127.0.0.1", free_port(), timeout=0.2),
                   notify=lambda code, **ctx: events.append(code))
    assert rc == 1 and events == [codes.ORT_8028]


def test_guard_only_stops_the_process_recorded_as_rigctld(tmp_path):
    other = _spawn(SLEEPER)
    try:
        (tmp_path / guard.RIGCTLD_PID_FILE).write_text(json.dumps({"pid": other.pid, "exe": r"C:\x\rigctld.exe"}))
        assert "n'est plus rigctld" in guard.stop_rigctld(tmp_path)
        assert other.poll() is None, "un autre programme qui a repris le numéro ne doit jamais être tué"
    finally:
        other.kill()
    assert guard.stop_rigctld(tmp_path / "absent") == "aucun rigctld noté par la station"


# --------------------------------------------------------------------------- la garde dans le superviseur

def _backend(tmp_path, commands, **kw):
    cfg = dummy_config()
    cfg.network.rigctld_port = free_port()
    cfg.supervisor.state_dir = str(tmp_path)
    return ManagedBackend(cfg, commands=commands, port_open=lambda: False, restart_delay_s=0.0, rigctld_wait_s=0.0,
                          guard=True, **kw)


def test_the_station_starts_the_guard_first_writes_the_rigctld_pid_and_stops_the_guard_last(tmp_path):
    b = _backend(tmp_path, {"guard": SLEEPER, "rigctld": SLEEPER, "gateway": SLEEPER})
    b.start()
    try:
        assert alive(b, "guard") and alive(b, "rigctld") and alive(b, "gateway")
        assert b.children["guard"].last_start <= b.children["rigctld"].last_start
        recorded = json.loads((tmp_path / guard.RIGCTLD_PID_FILE).read_text(encoding="utf-8"))
        assert recorded["pid"] == b.children["rigctld"].proc.pid
    finally:
        b.stop_all()
    assert not alive(b, "guard") and not alive(b, "rigctld") and not alive(b, "gateway")


@pytest.mark.parametrize("command", [EXITER, [str("C:/nulle-part/introuvable.exe")]])
def test_no_station_without_a_guard(tmp_path, command):
    b = _backend(tmp_path, {"guard": command, "rigctld": SLEEPER, "gateway": SLEEPER})
    with pytest.raises(GuardUnavailable):
        b.start()
    try:
        assert b.children["rigctld"].proc is None and b.children["gateway"].proc is None, "rien ne doit démarrer"
    finally:
        b.stop_all()


def test_a_dead_guard_is_restarted(tmp_path):
    b = _backend(tmp_path, {"guard": SLEEPER, "rigctld": SLEEPER, "gateway": SLEEPER})
    b.start()
    try:
        first = b.children["guard"].proc
        first.kill()
        first.wait(10)
        assert wait_until(lambda: (b.maintain() or True) and alive(b, "guard") and b.children["guard"].proc is not first)
    finally:
        b.stop_all()


def test_without_a_guard_able_to_restart_remote_transmission_stops(tmp_path):
    b = _backend(tmp_path, {"guard": SLEEPER, "rigctld": SLEEPER, "gateway": SLEEPER})
    b.start()
    try:
        b._commands["guard"] = ["C:/nulle-part/introuvable.exe"]
        b.children["guard"].proc.kill()
        b.children["guard"].proc.wait(10)
        b.maintain()
        assert b.children["guard"].stopped and not alive(b, "gateway"), "plus de garde = plus de passerelle"
        assert alive(b, "rigctld"), "la réception par le poste n'est pas touchée"
    finally:
        b.stop_all()


def test_guard_command_runs_the_real_interpreter_and_never_carries_the_ntfy_address(tmp_path):
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path)
    cfg.supervisor.notify_url = "https://ntfy.example/sujet-secret"
    b = ManagedBackend(cfg, guard=True)
    command = b._command("guard")
    assert command[:3] == [packaging.python_executable(windowed=True), "-m", "trxstation.supervisor.guard"]
    assert str(cfg.network.rigctld_port) in command and str(tmp_path) in command
    assert not any("sujet-secret" in part for part in command)


def test_guard_is_on_by_default_under_windows_only():
    cfg = dummy_config()
    assert "guard" in ManagedBackend(cfg, platform="win32").children
    assert "guard" not in ManagedBackend(cfg, platform="linux").children


# --------------------------------------------------------------------------- paquet MSIX

def test_outside_a_package_the_interpreter_is_unchanged():
    assert packaging.is_store() is False
    assert packaging.python_executable() == sys.executable


def test_an_execution_alias_is_replaced_by_the_package_interpreter(tmp_path, monkeypatch):
    aliases = tmp_path / "Microsoft" / "WindowsApps"
    aliases.mkdir(parents=True)
    prefix = tmp_path / "pkg" / "python"
    prefix.mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (prefix / name).write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "executable", str(aliases / "trx-console.exe"))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    assert packaging.python_executable(windowed=False) == str(prefix / "python.exe")
    assert packaging.python_executable(windowed=True) == str(prefix / "pythonw.exe")
