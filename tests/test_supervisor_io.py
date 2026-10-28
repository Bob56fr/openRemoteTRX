# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Entrées/sorties du superviseur : sonde rigctld, alertes, état, USB, sd_notify, boucle principale,
et un test de bout en bout avec de VRAIS processus (POSIX uniquement : il utilise SIGSTOP)."""
import asyncio
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.setup_wizard import dummy_config
from trxstation.status import GatewayStatus, read_status, write_status
from trxstation.supervisor.actions import find_usb_authorized
from trxstation.supervisor.core import Supervisor
from trxstation.supervisor.main import run_forever
from trxstation.supervisor.notify import Notifier
from trxstation.supervisor.rigctl import RigctlProbe
from trxstation.supervisor.sdnotify import sd_notify
from trxstation.supervisor.state import StateStore

POSIX = sys.platform != "win32"


class ServerThread:
    """Faux rigctld dans son propre fil : la sonde bloquante du superviseur peut lui parler."""

    def __init__(self):
        self.fake = FakeRigctld()
        self.loop = None
        self.thread = None

    def start(self):
        ready = threading.Event()

        def target():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.fake.start())
            ready.set()
            self.loop.run_forever()
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        assert ready.wait(5)
        return self

    def stop(self):
        asyncio.run_coroutine_threadsafe(self.fake.stop(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


# --------------------------------------------------------------------------- sonde rigctld

def test_probe_reads_state_and_force_rx():
    srv = ServerThread().start()
    try:
        probe = RigctlProbe("127.0.0.1", srv.fake.port)
        r = probe.read()
        assert r.ok and r.ptt is False and r.frequency_hz == 14_200_000
        srv.fake.ptt = 1
        assert probe.read().ptt is True
        assert probe.force_rx() is True and srv.fake.ptt == 0
    finally:
        srv.stop()


def test_probe_force_rx_reports_failure_when_rig_ignores_it():
    srv = ServerThread().start()
    try:
        srv.fake.ptt = 1
        srv.fake.ignore_unkey = True
        assert RigctlProbe("127.0.0.1", srv.fake.port).force_rx() is False
    finally:
        srv.stop()


def test_probe_unreadable_ptt_is_unknown_not_down():
    srv = ServerThread().start()
    try:
        srv.fake.errors["t"] = -11
        r = RigctlProbe("127.0.0.1", srv.fake.port).read()
        assert r.ok and r.ptt is None
    finally:
        srv.stop()


def test_probe_reports_unreachable_rigctld():
    r = RigctlProbe("127.0.0.1", 1, timeout=0.5).read()
    assert not r.ok and r.error
    assert RigctlProbe("127.0.0.1", 1, timeout=0.5).force_rx() is False


# --------------------------------------------------------------------------- alertes

def test_notifier_rate_limit_and_scheme_check():
    sent, now = [], [0.0]
    n = Notifier("https://ntfy.sh/x", post=lambda *a: sent.append(a), clock=lambda: now[0],
                 min_interval_s=60, threaded=False)
    assert n.send("A", "m1") and not n.send("A", "m2")        # même titre : limité
    assert n.send("B", "m3")                                   # autre titre : passe
    now[0] = 61
    assert n.send("A", "m4")
    assert [s[2] for s in sent] == ["m1", "m3", "m4"]
    assert not Notifier("file:///etc/passwd", post=lambda *a: sent.append(a), threaded=False).send("A", "x")
    assert not Notifier("", threaded=False).send("A", "x")


def test_notifier_swallows_post_errors():
    def boom(*_):
        raise OSError("réseau coupé")
    assert Notifier("https://ntfy.sh/x", post=boom, threaded=False).send("A", "m") is True


# --------------------------------------------------------------------------- état persistant

def test_state_store(tmp_path):
    s = StateStore(tmp_path / "state")
    assert s.safe_mode() is None and s.reboot_times() == []
    s.set_safe_mode("trop de redémarrages")
    assert s.safe_mode() == "trop de redémarrages"
    s.clear_safe_mode()
    s.clear_safe_mode()                                        # idempotent
    assert s.safe_mode() is None
    for t in range(30):
        s.add_reboot(float(t))
    assert s.reboot_times() == [float(t) for t in range(10, 30)]   # 20 dernières


def test_state_store_tolerates_corruption(tmp_path):
    (tmp_path / "reboots.json").write_text("{pas du json")
    assert StateStore(tmp_path).reboot_times() == []


# --------------------------------------------------------------------------- fichier d'état

def make_status(seq=1):
    return GatewayStatus(pid=42, seq=seq, written_at=1.0, ptt={"state": "RX", "owner": None},
                         rig={"connected": True}, clients=["phone"])


def test_status_roundtrip_and_atomicity(tmp_path):
    path = tmp_path / "run" / "status.json"
    assert read_status(path) is None
    write_status(path, make_status(1))
    write_status(path, make_status(2))
    assert read_status(path) == make_status(2)
    assert [p.name for p in path.parent.iterdir()] == ["status.json"]   # aucun fichier temporaire


def test_status_rejects_garbage(tmp_path):
    path = tmp_path / "status.json"
    for text in ("{pas du json", "[]", '{"schema": 99}', '{"schema": 1, "pid": "x", "seq": 1, "ptt": {}, "rig": {}}',
                 '{"schema": 1, "pid": 1, "seq": 1, "ptt": {"x": 1}, "rig": {}}'):
        path.write_text(text)
        assert read_status(path) is None


# --------------------------------------------------------------------------- USB

def test_find_usb_authorized(tmp_path):
    if not POSIX:
        return                                                 # liens symboliques réservés à POSIX
    sysroot = tmp_path / "sys"
    usb = sysroot / "devices" / "pci0" / "usb1" / "1-1"
    interface = usb / "1-1:1.0" / "ttyUSB0"
    interface.mkdir(parents=True)
    (usb / "authorized").write_text("1")
    (usb / "idVendor").write_text("10c4")
    (sysroot / "class" / "tty" / "ttyUSB0").mkdir(parents=True)
    os.symlink(usb / "1-1:1.0", sysroot / "class" / "tty" / "ttyUSB0" / "device")
    assert find_usb_authorized("/dev/ttyUSB0", str(sysroot)) == usb / "authorized"
    assert find_usb_authorized("/dev/ttyUSB7", str(sysroot)) is None


# --------------------------------------------------------------------------- systemd

def test_sd_notify_without_socket_is_a_noop():
    saved = os.environ.pop("NOTIFY_SOCKET", None)
    try:
        assert sd_notify("READY=1") is False
    finally:
        if saved is not None:
            os.environ["NOTIFY_SOCKET"] = saved


def test_sd_notify_delivers_message():
    if not POSIX:
        return
    directory = tempfile.mkdtemp(dir="/tmp")
    path = os.path.join(directory, "n.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    saved = os.environ.get("NOTIFY_SOCKET")
    try:
        server.bind(path)
        server.settimeout(2)
        os.environ["NOTIFY_SOCKET"] = path
        assert sd_notify("WATCHDOG=1") is True
        assert server.recv(100) == b"WATCHDOG=1"
    finally:
        server.close()
        os.environ.pop("NOTIFY_SOCKET", None)
        if saved is not None:
            os.environ["NOTIFY_SOCKET"] = saved


# --------------------------------------------------------------------------- boucle principale

class Stub:
    def __init__(self, tx_active=False, fail=False):
        self.tx_active, self.fail, self.steps = tx_active, fail, 0

    def step(self):
        self.steps += 1
        if self.fail:
            raise RuntimeError("bug")


def test_run_forever_exits_after_repeated_failures_so_systemd_restarts_us():
    sent = []
    stub = Stub(fail=True)
    code = run_forever(stub, 1.0, sleep=lambda s: None, notify=sent.append)
    assert code == 1 and stub.steps == 5 and sent[0] == "READY=1"


def test_run_forever_pings_watchdog_and_polls_faster_during_tx():
    sent, sleeps = [], []
    stub = Stub(tx_active=True)
    done = iter([False, False, True])
    code = run_forever(stub, 1.0, stop=lambda: next(done), sleep=sleeps.append, notify=sent.append)
    assert code == 0 and sent == ["READY=1", "WATCHDOG=1", "WATCHDOG=1"] and sleeps == [0.25, 0.25]
    sleeps.clear()
    run_forever(Stub(tx_active=False), 1.0, stop=iter([False, True]).__next__, sleep=sleeps.append,
                notify=lambda s: None)
    assert sleeps == [1.0]


# --------------------------------------------------------------------------- vrais processus

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until(predicate, timeout, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return False


def test_frozen_gateway_during_real_transmission_is_cut_by_supervisor(tmp_path):
    """Faux poste + vraie passerelle (processus) qui émet ; on la gèle avec SIGSTOP."""
    if not POSIX:
        return
    root = Path(__file__).resolve().parent.parent
    env = dict(os.environ, PYTHONPATH=str(root))
    port, status_path = _free_port(), tmp_path / "status.json"
    rig = gateway = None
    try:
        rig = subprocess.Popen([sys.executable, "-m", "trxstation.devtools.fake_rigctld", "--port", str(port)],
                               cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        probe = RigctlProbe("127.0.0.1", port, timeout=1.0)
        assert _wait_until(lambda: probe.read().ok, 10), "faux rigctld injoignable"
        gateway = subprocess.Popen([sys.executable, "-m", "trxstation.devtools.fake_gateway",
                                    "--rigctld-port", str(port), "--status", str(status_path), "--key"],
                                   cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert _wait_until(lambda: probe.read().ptt is True, 20), "la passerelle n'a pas pris l'émission"

        cfg = dummy_config()
        cfg.network.rigctld_port = port
        cfg.supervisor.stale_after_s = 1.0
        cfg.supervisor.startup_grace_s = 0.0
        cfg.supervisor.recovery_wait_s = 60.0
        calls = []

        class Actions:
            def force_rx(self):
                calls.append("force_rx")
                return probe.force_rx()

            def kill_gateway(self):
                calls.append("kill_gateway")
                os.kill(gateway.pid, signal.SIGKILL)

            def restart_gateway(self): calls.append("restart_gateway")
            def stop_gateway(self): calls.append("stop_gateway")
            def restart_rigctld(self): calls.append("restart_rigctld")
            def reset_usb(self): calls.append("reset_usb")
            def reboot(self): calls.append("reboot")
            def notify(self, title, message): pass

        sup = Supervisor(cfg, read_status=lambda: read_status(status_path), probe_rig=probe.read,
                         actions=Actions(), store=StateStore(tmp_path / "state"), read_temp=lambda: None)

        # 1) émission expliquée par une passerelle vivante : le superviseur ne doit rien faire
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            sup.step()
            time.sleep(0.2)
        assert calls == []

        # 2) la passerelle gèle en pleine émission
        os.kill(gateway.pid, signal.SIGSTOP)
        started = time.monotonic()
        cut = _wait_until(lambda: (sup.step(), probe.read().ptt is False and gateway.poll() is not None)[1],
                          12, step=0.2)
        elapsed = time.monotonic() - started
        assert cut, f"émission non coupée ou passerelle non tuée (actions : {calls})"
        assert elapsed < 8 and "force_rx" in calls and "kill_gateway" in calls
        assert probe.read().ptt is False
    finally:
        for proc in (gateway, rig):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(5)


@pytest.mark.skipif(os.name != "posix", reason="droits POSIX")
def test_gateway_status_file_is_readable_by_the_desktop_account(tmp_path):
    """trx-monitor et le diagnostic tournent sous le compte de bureau : 0644 (mkstemp créait du 0600)."""
    from trxstation.status import GatewayStatus, write_status
    path = tmp_path / "gateway-status.json"
    write_status(path, GatewayStatus(pid=1, seq=1, written_at=0.0, ptt={"state": "RX"}, rig={}))
    assert path.stat().st_mode & 0o777 == 0o644
