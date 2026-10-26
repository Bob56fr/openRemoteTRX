"""Mode géré avec de VRAIS processus enfants (cross-platform : de simples scripts Python),
et passerelle réelle (`trxstation.gateway.main`) lancée en sous-processus."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from trxstation import config as cfgmod
from trxstation.procutil import pid_alive
from trxstation.setup_wizard import dummy_config
from trxstation.status import read_status
from trxstation.supervisor.backends import ManagedBackend
from trxstation.supervisor.rigctl import RigctlProbe

SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]
EXITER = [sys.executable, "-c", "pass"]
ROOT = Path(__file__).resolve().parent.parent
POSIX = os.name != "nt"


def wait_until(predicate, timeout=8.0, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def backend(commands, *, safe_mode=lambda: None, **kw):
    cfg = dummy_config()
    cfg.network.rigctld_port = kw.pop("rigctld_port", free_port())
    kw.setdefault("restart_delay_s", 0.0)
    kw.setdefault("rigctld_wait_s", 0.0)
    return ManagedBackend(cfg, commands=commands, safe_mode=safe_mode, port_open=kw.pop("port_open", lambda: False), **kw)


def alive(b, name):
    return b.children[name].proc is not None and b.children[name].proc.poll() is None


def test_start_and_stop_all_manage_real_processes():
    b = backend({"rigctld": SLEEPER, "gateway": SLEEPER})
    b.start()
    try:
        assert alive(b, "rigctld") and alive(b, "gateway")
        assert b.children["rigctld"].proc.pid != b.children["gateway"].proc.pid
    finally:
        b.stop_all()
    assert not alive(b, "rigctld") and not alive(b, "gateway")


def test_crashed_child_is_restarted_by_maintain():
    b = backend({"rigctld": SLEEPER, "gateway": EXITER})
    b.start()
    try:
        assert wait_until(lambda: b.children["gateway"].proc.poll() is not None)
        b.maintain()
        assert b.children["gateway"].restarts == 1
    finally:
        b.stop_all()


def test_restart_delay_prevents_tight_restart_loops():
    b = backend({"rigctld": SLEEPER, "gateway": EXITER}, restart_delay_s=60.0)
    b.start()
    try:
        assert wait_until(lambda: b.children["gateway"].proc.poll() is not None)
        b.maintain()
        b.maintain()
        assert b.children["gateway"].restarts == 0
    finally:
        b.stop_all()


def test_kill_gateway_is_immediate_then_maintain_restarts_it():
    b = backend({"rigctld": SLEEPER, "gateway": SLEEPER})
    b.start()
    try:
        first_pid = b.children["gateway"].proc.pid
        b.kill_gateway()
        assert not alive(b, "gateway")
        b.maintain()
        assert alive(b, "gateway") and b.children["gateway"].proc.pid != first_pid
    finally:
        b.stop_all()


def test_restart_gateway_replaces_the_process():
    b = backend({"rigctld": SLEEPER, "gateway": SLEEPER})
    b.start()
    try:
        first_pid = b.children["gateway"].proc.pid
        b.restart_gateway()
        assert alive(b, "gateway") and b.children["gateway"].proc.pid != first_pid
    finally:
        b.stop_all()


def test_deliberate_stop_is_not_undone_by_maintain():
    b = backend({"rigctld": SLEEPER, "gateway": SLEEPER})
    b.start()
    try:
        b.stop_gateway()
        assert not alive(b, "gateway")
        b.maintain()
        assert not alive(b, "gateway")
    finally:
        b.stop_all()


def test_safe_mode_blocks_gateway_until_cleared():
    state = {"safe": "trop de redémarrages"}
    b = backend({"rigctld": SLEEPER, "gateway": SLEEPER}, safe_mode=lambda: state["safe"])
    b.start()
    try:
        assert alive(b, "rigctld") and b.children["gateway"].proc is None
        b.maintain()
        assert b.children["gateway"].proc is None
        state["safe"] = None                                       # l'opérateur sort du mode sûr
        b.maintain()
        assert alive(b, "gateway")
    finally:
        b.stop_all()


def test_running_rigctld_is_adopted_not_relaunched():
    b = backend({"rigctld": SLEEPER, "gateway": SLEEPER}, port_open=lambda: True)
    b.start()
    try:
        assert b.rigctld_adopted and b.children["rigctld"].proc is None
        b.restart_rigctld()                                        # sans effet, sans plantage
        assert b.children["rigctld"].proc is None
    finally:
        b.stop_all()


def test_reboot_and_usb_reset_per_platform():
    ran = []
    b = backend({"rigctld": SLEEPER, "gateway": SLEEPER}, platform="win32",
                runner=lambda cmd, **kw: ran.append(cmd))
    b.reboot()
    b.reset_usb()                                                  # non pris en charge : ne plante pas
    assert ran == [["shutdown", "/r", "/t", "0"]]


# --------------------------------------------------------------------------- passerelle réelle

def _env():
    return dict(os.environ, PYTHONPATH=str(ROOT))


def _config(tmp_path, port, **supervisor):
    cfg = dummy_config()
    cfg.network.rigctld_port = port
    for key, value in supervisor.items():
        setattr(cfg.supervisor, key, value)
    cfg.supervisor.status_path = str(tmp_path / "status.json")
    cfg.supervisor.state_dir = str(tmp_path / "state")
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return path, cfg


def _start_fake_rig(port):
    rig = subprocess.Popen([sys.executable, "-m", "trxstation.devtools.fake_rigctld", "--port", str(port)],
                           cwd=ROOT, env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    probe = RigctlProbe("127.0.0.1", port, timeout=1.0)
    assert wait_until(lambda: probe.read().ok, 10), "faux rigctld injoignable"
    return rig, probe


def _stop(*procs):
    for proc in procs:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(5)


def test_real_gateway_publishes_state_and_forces_rx_at_startup(tmp_path):
    port = free_port()
    config, cfg = _config(tmp_path, port)
    rig, probe = _start_fake_rig(port)
    gateway = None
    try:
        gateway = subprocess.Popen([sys.executable, "-m", "trxstation.gateway.main", "--config", str(config)],
                                   cwd=ROOT, env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status_path = tmp_path / "status.json"

        def ready():
            s = read_status(status_path)
            return s is not None and s.rig.get("connected") and s.ptt["state"] == "RX" and s.rig.get("frequency_hz")
        assert wait_until(ready, 15), "la passerelle n'a pas publié un état valide"
        first = read_status(status_path)
        assert wait_until(lambda: read_status(status_path).seq > first.seq, 5)      # elle vit
        assert first.pid == gateway.pid and probe.read().ptt is False
        if POSIX:                                                  # arrêt propre : SIGTERM
            gateway.terminate()
            assert gateway.wait(10) == 0
    finally:
        _stop(gateway, rig)


def test_real_gateway_exits_when_its_parent_disappears(tmp_path):
    port = free_port()
    config, _ = _config(tmp_path, port)
    rig, _probe = _start_fake_rig(port)
    parent = gateway = None
    try:
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2.5)"])
        gateway = subprocess.Popen([sys.executable, "-m", "trxstation.gateway.main", "--config", str(config),
                                    "--parent-pid", str(parent.pid)],
                                   cwd=ROOT, env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert wait_until(lambda: (s := read_status(tmp_path / "status.json")) is not None, 15)
        assert gateway.poll() is None                              # tant que le parent vit, elle tourne
        parent.wait()                                              # le « superviseur » disparaît
        assert wait_until(lambda: gateway.poll() is not None, 15), "la passerelle ne s'est pas arrêtée"
        assert gateway.returncode == 0
    finally:
        _stop(gateway, parent, rig)


def test_managed_backend_runs_a_real_gateway_end_to_end(tmp_path):
    port = free_port()
    config, cfg = _config(tmp_path, port)
    rig, probe = _start_fake_rig(port)
    b = ManagedBackend(cfg, config_path=config, restart_delay_s=0.0, rigctld_wait_s=0.0)   # rigctld adopté
    try:
        b.start()
        assert b.rigctld_adopted and alive(b, "gateway")
        status_path = tmp_path / "status.json"
        assert wait_until(lambda: (s := read_status(status_path)) is not None and s.rig.get("connected"), 15)
        pid = b.children["gateway"].proc.pid
        b.kill_gateway()                                           # le superviseur tue une passerelle gelée
        assert wait_until(lambda: not alive(b, "gateway"), 5)
        b.maintain()                                               # ... et la relance
        assert alive(b, "gateway") and b.children["gateway"].proc.pid != pid
        assert wait_until(lambda: (s := read_status(status_path)) is not None and s.pid == b.children["gateway"].proc.pid, 15)
    finally:
        b.stop_all()
        _stop(rig)


def test_supervisor_process_manages_gateway_and_refuses_a_second_instance(tmp_path):
    port = free_port()
    config, _ = _config(tmp_path, port, service_mode="managed", instance_lock_port=free_port())
    rig, _probe = _start_fake_rig(port)
    supervisor = second = None
    gateway_pid = None
    command = [sys.executable, "-m", "trxstation.supervisor.main", "--config", str(config)]
    try:
        supervisor = subprocess.Popen(command, cwd=ROOT, env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status_path = tmp_path / "status.json"
        assert wait_until(lambda: (s := read_status(status_path)) is not None and s.rig.get("connected"), 25), \
            "le superviseur n'a pas lancé une passerelle fonctionnelle"
        gateway_pid = read_status(status_path).pid
        assert gateway_pid != supervisor.pid and pid_alive(gateway_pid)

        second = subprocess.Popen(command, cwd=ROOT, env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert second.wait(20) == 4                                # une seule instance autorisée

        if POSIX:                                                  # arrêt propre : la passerelle suit
            supervisor.terminate()
            assert supervisor.wait(20) == 0
            assert wait_until(lambda: not pid_alive(gateway_pid), 10), "la passerelle est restée orpheline"
    finally:
        _stop(supervisor, second, rig)
        if gateway_pid is not None and pid_alive(gateway_pid):
            try:
                os.kill(gateway_pid, 9)
            except OSError:
                pass


def test_gateway_refuses_to_start_when_the_audio_device_is_missing(tmp_path):
    """Un périphérique audio configuré mais introuvable : arrêt franc (code 5), sans rien lancer d'autre."""
    config, cfg = _config(tmp_path, free_port())
    cfg.audio.capture_device = "Micro-qui-n-existe-pas-xyz"
    config.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    gateway = subprocess.Popen([sys.executable, "-m", "trxstation.gateway.main", "--config", str(config)],
                               cwd=ROOT, env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        assert gateway.wait(30) == 5
        assert "Audio" in gateway.stderr.read()
        assert read_status(tmp_path / "status.json") is None       # elle n'a jamais publié d'état
    finally:
        _stop(gateway)
