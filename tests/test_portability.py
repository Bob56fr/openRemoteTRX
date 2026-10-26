"""Couche de portabilité Windows / Linux / Raspberry Pi, testée avec de faux systèmes."""
import os
import subprocess
import sys
import time
from pathlib import Path

from trxstation import config as cfgmod
from trxstation.audio_devices import list_audio_devices, parse_audio_list, real_device_names
from trxstation.hamlib import find_tool, rigctld_command
from trxstation.paths import default_config_path, default_state_dir, default_status_path
from trxstation.ports import list_serial_ports, port_present, windows_com_ports
from trxstation.procutil import acquire_instance_lock, pid_alive
from trxstation.setup_wizard import dummy_config
from trxstation.supervisor.backends import ManagedBackend, SystemdBackend, choose_backend, reboot_command


class FakePlatform:
    """Change temporairement sys.platform / variables d'environnement (restaurés ensuite)."""

    def __init__(self, platform=None, **env):
        self.platform, self.env, self.saved = platform, env, {}

    def __enter__(self):
        self.saved_platform = sys.platform
        if self.platform:
            sys.platform = self.platform
        for key, value in self.env.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        sys.platform = self.saved_platform
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# --------------------------------------------------------------------------- chemins

def test_default_paths_linux_windows_and_override(tmp_path):
    with FakePlatform("linux", TRX_REMOTE_HOME=None):
        assert default_config_path() == Path("/etc/trx-remote/station.toml")
        assert default_status_path() == Path("/run/trx-remote/gateway-status.json")
        assert default_state_dir() == Path("/var/lib/trx-remote")
    with FakePlatform("win32", TRX_REMOTE_HOME=None, PROGRAMDATA="D:\\Data"):
        assert "trx-remote" in str(default_config_path()) and default_config_path().name == "station.toml"
        assert str(default_state_dir()).startswith("D:\\Data") and default_status_path().name == "gateway-status.json"
    with FakePlatform("linux", TRX_REMOTE_HOME=str(tmp_path)):
        assert default_config_path() == tmp_path / "station.toml"
        assert default_status_path() == tmp_path / "run" / "gateway-status.json"
        assert default_state_dir() == tmp_path / "state"
        assert cfgmod.Supervisor().state_dir == str(tmp_path / "state")     # la config suit


def test_windows_style_paths_survive_toml_roundtrip(tmp_path):
    cfg = dummy_config()
    cfg.supervisor.status_path = "C:\\ProgramData\\trx-remote\\run\\gateway-status.json"
    cfg.tools.hamlib_dir = "C:\\Program Files\\hamlib-w64-4.5.5"
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert cfgmod.load(path) == cfg


# --------------------------------------------------------------------------- ports série

def test_windows_com_ports_sorted_naturally_and_filtered():
    ports = windows_com_ports(lambda: ["com10", "COM3", "\\Device\\Serial0", "COM2", "COM3"])
    assert ports == ["COM2", "COM3", "COM10"]


def test_list_serial_ports_per_platform():
    assert list_serial_ports("win32", registry=lambda: ["COM4"]) == ["COM4"]
    fake = {"/dev/serial/by-id/*": ["/dev/serial/by-id/usb-B", "/dev/serial/by-id/usb-A"],
            "/dev/ttyUSB*": ["/dev/ttyUSB0"], "/dev/ttyACM*": []}
    assert list_serial_ports("linux", globber=lambda p: fake.get(p, [])) == [
        "/dev/serial/by-id/usb-A", "/dev/serial/by-id/usb-B"]              # noms stables d'abord
    fake["/dev/serial/by-id/*"] = []
    assert list_serial_ports("linux", globber=lambda p: fake.get(p, [])) == ["/dev/ttyUSB0"]


def test_port_present():
    assert port_present("com3", "win32", registry=lambda: ["COM3"])
    assert port_present("\\\\.\\COM3", "win32", registry=lambda: ["COM3"])
    assert not port_present("COM9", "win32", registry=lambda: ["COM3"])
    assert port_present(sys.executable, "linux") and not port_present("/dev/inexistant-trx", "linux")


# --------------------------------------------------------------------------- Hamlib

def test_find_tool_search_order(tmp_path):
    bin_dir = tmp_path / "hamlib" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / "rigctl.exe"
    exe.write_text("")
    none = dict(env={}, which=lambda n: None, globber=lambda p: [])
    assert find_tool("rigctl", str(tmp_path / "hamlib"), platform="win32", **none) == str(exe)
    assert find_tool("rigctl", "", platform="win32", **none) is None
    assert find_tool("rigctl", "", platform="win32", env={"TRX_HAMLIB_DIR": str(tmp_path / "hamlib")},
                     which=lambda n: None, globber=lambda p: []) == str(exe)
    assert find_tool("rigctl", "", platform="linux", env={}, which=lambda n: "/usr/bin/rigctl",
                     globber=lambda p: []) == "/usr/bin/rigctl"
    # dossiers d'installation habituels : la version la plus récente gagne
    old, new = tmp_path / "hamlib-4.4", tmp_path / "hamlib-4.5"
    for d in (old, new):
        (d / "bin").mkdir(parents=True)
        (d / "bin" / "rigctl.exe").write_text("")
    assert find_tool("rigctl", "", platform="win32", env={}, which=lambda n: None,
                     globber=lambda p: [str(old), str(new)] if "Program Files\\" in p else []) == str(new / "bin" / "rigctl.exe")


def test_rigctld_command_resolves_path_or_fails_clearly(tmp_path):
    cfg = dummy_config()
    cfg.tools.hamlib_dir = str(tmp_path)
    fake_exe = tmp_path / ("rigctld.exe" if sys.platform == "win32" else "rigctld")
    fake_exe.write_text("")
    command = rigctld_command(cfg)
    assert command[0] == str(fake_exe) and command[1:3] == ["-m", "1"]
    fake_exe.unlink()
    cfg.tools.hamlib_dir = str(tmp_path / "vide")
    try:                                                         # aucun rigctld nulle part (même sous Windows)
        rigctld_command(cfg, env={}, which=lambda n: None, globber=lambda p: [])
        assert False, "FileNotFoundError attendue"
    except FileNotFoundError as exc:
        assert "hamlib_dir" in str(exc)


# --------------------------------------------------------------------------- audio

class FakeSoundDevice:
    def __init__(self, devices, hostapis):
        self._devices, self._hostapis = devices, hostapis

    def query_devices(self):
        return self._devices

    def query_hostapis(self):
        return [{"name": n} for n in self._hostapis]


def test_audio_devices_via_sounddevice_prefers_wasapi_and_dedupes():
    sd = FakeSoundDevice([
        {"name": "Microphone (USB Audio CODEC)", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Microphone (USB Audio CODEC)", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Haut-parleurs (USB Audio CODEC)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
        {"name": "Realtek", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 2},
    ], ["MME", "Windows WASAPI"])
    capture = list_audio_devices("capture", sd=sd)
    assert [v for v, _ in capture] == ["Microphone (USB Audio CODEC)", "Realtek"]
    assert "WASAPI" in capture[0][1]
    playback = list_audio_devices("playback", sd=sd)
    assert [v for v, _ in playback] == ["Haut-parleurs (USB Audio CODEC)", "Realtek"]


def test_audio_devices_without_sounddevice_falls_back_per_platform():
    assert list_audio_devices("capture", sd=None, platform="win32") == []
    assert list_audio_devices("capture", sd=None, platform="darwin") == []
    sample = "card 1: CODEC [USB Audio CODEC], device 0: USB Audio [USB Audio]\n"
    assert parse_audio_list(sample) == [("plughw:CARD=CODEC,DEV=0", "USB Audio CODEC (carte 1)")]

    class Broken:
        def query_devices(self):
            raise OSError("PortAudio absent")
    assert list_audio_devices("capture", sd=Broken(), platform="win32") == []


# --------------------------------------------------------------------------- processus

def test_pid_alive():
    assert pid_alive(os.getpid())
    assert not pid_alive(0) and not pid_alive(-3)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()                                                   # zombie réaffecté : plus vivant
    assert not pid_alive(child.pid)


def test_instance_lock_is_exclusive():
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    first = acquire_instance_lock(port)
    assert first is not None
    assert acquire_instance_lock(port) is None
    first.close()
    again = acquire_instance_lock(port)
    assert again is not None
    again.close()


# --------------------------------------------------------------------------- sélection du backend

def test_backend_selection_per_platform_and_setting():
    cfg = dummy_config()
    assert isinstance(choose_backend(cfg, platform="linux", systemd_present=True), SystemdBackend)
    assert isinstance(choose_backend(cfg, platform="linux", systemd_present=False), ManagedBackend)
    assert isinstance(choose_backend(cfg, platform="win32", systemd_present=True), ManagedBackend)
    cfg.supervisor.service_mode = "managed"
    assert isinstance(choose_backend(cfg, platform="linux", systemd_present=True), ManagedBackend)
    cfg.supervisor.service_mode = "systemd"
    assert isinstance(choose_backend(cfg, platform="win32", systemd_present=False), SystemdBackend)
    cfg.supervisor.service_mode = "n_importe_quoi"
    assert any("service_mode" in p for p in cfgmod.validate(cfg))


def test_reboot_commands():
    assert reboot_command("win32") == ["shutdown", "/r", "/t", "0"]
    assert reboot_command("linux")[-1] in ("reboot", "now")


def test_systemd_backend_issues_expected_commands():
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    cfg = dummy_config()
    backend = SystemdBackend(cfg, runner=runner)
    backend.kill_gateway()
    backend.restart_gateway()
    backend.stop_gateway()
    backend.restart_rigctld()
    backend.reboot()
    backend.stop_all()                                             # ne touche à rien
    assert calls == [
        ["systemctl", "kill", "--signal=SIGKILL", "trx-gateway.service"],
        ["systemctl", "restart", "trx-gateway.service"],
        ["systemctl", "stop", "trx-gateway.service"],
        ["systemctl", "restart", "rigctld.service"],
        ["systemctl", "reboot"],
    ]


def test_real_device_names_excludes_test_sources_and_blanks():
    assert real_device_names("Microphone (USB Audio Device)", "Haut-parleurs (USB Audio Device)") == [
        "Microphone (USB Audio Device)", "Haut-parleurs (USB Audio Device)"]
    assert real_device_names("", "null") == [] and real_device_names("tone:440", "file:tx.wav", "click:1") == []
    assert real_device_names("  usb audio  ", None) == ["usb audio"]
