"""Diagnostic de TRX Console et rapport de dépannage (système simulé)."""
from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

from trxstation import config as cfgmod
from trxstation import diagnostics as d
from trxstation.config import ClientAuth
from trxstation.passwords import hash_password
from trxstation.report import make_report, redact_config
from trxstation.setup_wizard import dummy_config

OS_RELEASE = 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_ID="13"\n'
PORT = "/dev/serial/by-id/usb-IC-7300"
HASH = hash_password("un mot de passe solide 42")


class FakeSystem(d.System):
    platform = "linux"

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.files: dict[str, str] = {"/etc/os-release": OS_RELEASE}
        self.present: set[str] = set()
        self.commands: dict[str, tuple[int, str]] = {}
        self.modules = {"aiohttp", "aiortc", "sounddevice", "cryptography", "textual"}
        self.groups = {"dialout": (20, ["luc"]), "trx": (996, ["luc"])}
        self.gids = [20, 996]
        self.ports = [PORT]
        self.devices = [("USB Audio CODEC: - (hw:2,0)", "USB Audio CODEC  [ALSA]")]
        self.listening = True
        self.mtimes: dict[str, float] = {}
        self.stats: dict[str, SimpleNamespace] = {}

    def run(self, cmd, timeout=15):
        return self.commands.get(" ".join(cmd), (0, ""))

    def which(self, name):
        return f"/usr/bin/{name}" if name != "ufw" else None

    def exists(self, path):
        real = str(path).startswith(str(self.tmp)) and Path(path).exists()     # seuls les fichiers du test
        return str(path) in self.present or str(path) in self.files or real

    def read_text(self, path):
        return self.files.get(str(Path(path).as_posix()), self.files.get(str(path)))

    def mtime(self, path):
        return self.mtimes.get(str(path))

    def now(self):
        return 1000.0

    def stat(self, path):
        return self.stats.get(str(path))

    def free_bytes(self, path):
        return 50 * 10**9

    def module_present(self, name):
        return name in self.modules

    def user(self):
        return "luc"

    def group_members(self, group):
        return self.groups.get(group, (None, []))

    def process_gids(self):
        return self.gids

    def primary_gid(self, user):
        return 1000

    def serial_ports(self):
        return self.ports

    def audio_devices(self, kind):
        return self.devices

    def find_tool(self, name, hamlib_dir=""):
        return f"/usr/bin/{name}"

    def can_connect(self, host, port):
        return self.listening

    def local_addresses(self):
        return ["192.168.1.30"]


def station(tmp_path, **changes) -> Path:
    cfg = dummy_config()
    cfg.rig.model, cfg.rig.port = 3094, PORT
    cfg.audio.capture_device = cfg.audio.playback_device = "USB Audio CODEC"
    cfg.supervisor.status_path = str(tmp_path / "status.json")
    cfg.supervisor.state_dir = str(tmp_path / "state")
    cfg.supervisor.notify_url = "https://ntfy.sh/sujet-secret"
    cfg.clients = [ClientAuth(id="phone", password_hash=HASH)]
    for key, value in changes.items():
        section, name = key.split("__")
        setattr(getattr(cfg, section), name, value)
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return path


def healthy(tmp_path) -> tuple[FakeSystem, Path]:
    sysm = FakeSystem(tmp_path)
    path = station(tmp_path)
    sysm.present.add(PORT)
    sysm.commands["/usr/bin/rigctl -l"] = (0, "  3094  Icom                   IC-7300MK2              20240101.0      Stable      RIG_MODEL_IC7300MK2\n")
    for unit in d.UNITS:
        sysm.commands[f"systemctl is-active {unit}"] = (0, "active\n")
        sysm.commands[f"systemctl is-enabled {unit}"] = (0, "enabled\n")
    sysm.mtimes[str(tmp_path / "status.json")] = 999.0
    sysm.stats[str(path)] = SimpleNamespace(st_gid=996, st_mode=0o100640)
    return sysm, path


def by_name(checks, name):
    return next(c for c in checks if c.name == name)


def test_a_healthy_station_has_no_error(tmp_path):
    sysm, path = healthy(tmp_path)
    checks = d.run_all(sysm, path)
    assert d.exit_code(checks) == 0, d.format_checks(checks)
    assert by_name(checks, "Modèle du poste").status == d.OK and by_name(checks, "Port CAT").status == d.OK
    assert by_name(checks, "trx-gateway.service").status == d.OK
    text = d.format_checks(checks)
    assert "[OK] Système d'exploitation : Debian GNU/Linux 13 (trixie)" in text and "Bilan" in text


def test_missing_configuration_is_a_warning_not_a_crash(tmp_path):
    sysm = FakeSystem(tmp_path)
    checks = d.run_all(sysm, tmp_path / "absent.toml")
    check = by_name(checks, "Fichier de configuration")
    assert check.status == d.WARN and "Assistant" in check.fix


def test_invalid_configuration_is_an_error(tmp_path):
    sysm = FakeSystem(tmp_path)
    path = tmp_path / "station.toml"
    path.write_text("[rig]\nmodel = 3094\n", encoding="utf-8")
    assert by_name(d.run_all(sysm, path), "Fichier de configuration").status == d.FAIL


def test_unreadable_by_the_service_account_is_an_error(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.stats[str(path)] = SimpleNamespace(st_gid=0, st_mode=0o100600)
    check = by_name(d.run_all(sysm, path), "Droits du fichier")
    assert check.status == d.FAIL and "chgrp trx" in check.fix


def test_group_granted_but_session_too_old_asks_to_log_in_again(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.gids = [996]
    check = by_name(d.run_all(sysm, path), "Groupe dialout")
    assert check.status == d.WARN and "reconnecte" in check.fix


def test_rig_switched_off_unknown_model_and_missing_sound_card(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.present.discard(PORT)
    sysm.devices = []
    sysm.commands["/usr/bin/rigctl -l"] = (0, "     1  Hamlib                 Dummy                   20240101.0      Stable      RIG_MODEL_DUMMY\n")
    checks = d.run_all(sysm, path)
    assert by_name(checks, "Port CAT").status == d.FAIL and "éteint" in by_name(checks, "Port CAT").message
    assert by_name(checks, "Modèle du poste").status == d.FAIL
    assert by_name(checks, "Carte son (capture)").status == d.FAIL
    assert d.exit_code(checks) == 1


def test_usb_intruders_are_reported(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.commands["systemctl is-active ModemManager"] = (0, "active\n")
    sysm.present.add("/usr/lib/udev/rules.d/85-brltty.rules")
    checks = d.run_all(sysm, path)
    assert by_name(checks, "ModemManager").status == d.WARN and by_name(checks, "brltty").status == d.WARN
    sysm.present |= {str(d.MM_RULE), "/etc/udev/rules.d/85-brltty.rules"}
    names = [c.name for c in d.run_all(sysm, path)]
    assert "ModemManager" not in names and "brltty" not in names


def test_failed_service_safe_mode_and_stale_gateway(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.commands["systemctl is-active trx-gateway.service"] = (3, "failed\n")
    sysm.files[(tmp_path / "state" / "safe_mode").as_posix()] = "3 redémarrage(s) sans succès"
    sysm.mtimes[str(tmp_path / "status.json")] = 900.0
    checks = d.run_all(sysm, path)
    assert by_name(checks, "trx-gateway.service").status == d.FAIL
    assert by_name(checks, "Mode sûr").status == d.FAIL and "3 redémarrage" in by_name(checks, "Mode sûr").message
    assert by_name(checks, "État de la passerelle").status == d.WARN


def test_network_exposure_and_closed_port(tmp_path):
    sysm = FakeSystem(tmp_path)
    path = station(tmp_path, network__gateway_bind="0.0.0.0")
    sysm.listening = False
    checks = d.check_network(sysm, cfgmod.load(path))
    assert by_name(checks, "Sécurité de l'accès").status == d.FAIL
    path = station(tmp_path, network__gateway_bind="0.0.0.0", network__allow_insecure_http=True)
    checks = d.check_network(sysm, cfgmod.load(path))
    assert by_name(checks, "Port de la station").status == d.WARN
    assert "http://192.168.1.30:8443" in by_name(checks, "Accès depuis le téléphone").message


def test_missing_modules_rank_by_importance(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.modules -= {"aiortc", "textual"}
    checks = d.run_all(sysm, path)
    assert by_name(checks, "Module aiortc").status == d.FAIL and by_name(checks, "Module textual").status == d.WARN


def test_report_is_complete_and_contains_no_secret(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.files[path.as_posix()] = path.read_text(encoding="utf-8")
    sysm.files[str(path)] = path.read_text(encoding="utf-8")
    target = make_report(tmp_path, sysm=sysm, config_path=path)
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert {"diagnostic.txt", "station.toml", "journal.txt", "materiel.txt", "installation.log"} <= names
        everything = b"".join(archive.read(n) for n in names).decode("utf-8")
    assert "sujet-secret" not in everything and "scrypt$" not in everything
    assert 'notify_url = "https://ntfy.sh/***"' in everything and 'password_hash = "***"' in everything


def test_redact_config_masks_tokens_and_empty_alert_url():
    text = 'token = "abcdefghijklmnopqrst"\nnotify_url = ""\nport = "/dev/x"\n'
    assert redact_config(text) == 'token = "***"\nnotify_url = ""\nport = "/dev/x"\n'
