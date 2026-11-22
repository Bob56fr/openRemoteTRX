# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diagnostic d'openRemoteTRX Console et rapport de dépannage (système simulé)."""
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
        self.modules = {"aiohttp", "aiortc", "sounddevice", "cryptography", "textual", "serial"}
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
    assert by_name(checks, "Mise en sécurité").status == d.FAIL and "3 redémarrage" in by_name(checks, "Mise en sécurité").message
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


def test_safe_mode_file_unreadable_is_still_reported(tmp_path):
    from trxstation.config import Config
    cfg = Config()
    cfg.supervisor.state_dir = "/var/lib/trx-remote"
    sysm = FakeSystem(tmp_path)
    sysm.present.add(str(Path("/var/lib/trx-remote") / "safe_mode"))              # fichier du superviseur (root, 0600)
    sysm.commands["systemctl is-active trx-gateway.service"] = (0, "inactive")
    checks = [c for c in d.check_services(sysm, cfg) if c.name == "Mise en sécurité"]
    assert checks and checks[0].status == d.FAIL and "illisible" in checks[0].message



ARECORD = ("**** List of CAPTURE Hardware Devices ****\n"
           "card 0: Camera [USB Camera], device 0: USB Audio [USB Audio]\n"
           "card 2: CODEC [USB Audio CODEC], device 0: USB Audio [USB Audio]\n")


def test_busy_sound_card_is_not_reported_as_a_switched_off_rig(tmp_path):
    """Relevé sur Debian : la carte du poste, sortie par défaut du bureau, était tenue par PipeWire ; PortAudio ne liste
    pas une carte occupée et le diagnostic disait « poste éteint ». Le noyau, lui, la voit : présente mais occupée."""
    sysm, path = healthy(tmp_path)
    sysm.devices = [("USB Camera: Audio (hw:0,0)", "USB Camera  [ALSA]")]       # carte du poste absente de PortAudio
    sysm.commands["arecord -l"] = (0, ARECORD)
    sysm.commands["aplay -l"] = (0, ARECORD.replace("CAPTURE", "PLAYBACK"))
    check = by_name(d.run_all(sysm, path), "Carte son (capture)")
    assert check.status == d.WARN and "occupée" in check.message and "carte 2" in check.message
    assert "éteint" not in check.message + check.fix
    sysm.commands["systemctl is-active trx-gateway"] = (0, "active\n")             # c'est la station qui la tient
    check = by_name(d.run_all(sysm, path), "Carte son (capture)")
    assert check.status == d.OK and "utilisée par la station" in check.message
    sysm.commands["arecord -l"] = (0, ARECORD.replace("card 2: CODEC [USB Audio CODEC]", "card 2: Other [Other]"))
    sysm.commands["systemctl is-active trx-gateway"] = (0, "inactive\n")
    check = by_name(d.run_all(sysm, path), "Carte son (capture)")
    assert check.status == d.FAIL and "éteint" in check.fix                         # vraiment absente : erreur


WPCTL_SINK = ('id 71, type PipeWire:Interface:Node\n  * alsa.card_name = "USB Audio CODEC"\n'
              '  * node.description = "USB Audio CODEC Analog Stereo"\n')


def test_rig_card_used_as_the_desktop_default_is_explained(tmp_path):
    """Relevé sur Debian : la carte du poste était la sortie par défaut du bureau. Le diagnostic le dit, avec les
    réglages à faire (Paramètres > Son)."""
    sysm, path = healthy(tmp_path)
    sysm.commands["pgrep -x pipewire"] = (0, "1234\n")
    sysm.commands["wpctl inspect @DEFAULT_AUDIO_SINK@"] = (0, WPCTL_SINK)
    sysm.commands["wpctl inspect @DEFAULT_AUDIO_SOURCE@"] = (0, 'alsa.card_name = "USB Camera"\n')
    check = by_name(d.run_all(sysm, path), "Son du bureau (PipeWire)")
    assert check.status == d.WARN and "sortie son par défaut" in check.message and "entrée" not in check.message
    assert "Paramètres > Son" in check.fix
    text = d.format_checks([check])
    assert "\n         " in text                                                 # conseil sur plusieurs lignes, indenté
    sysm.commands["wpctl inspect @DEFAULT_AUDIO_SINK@"] = (0, 'alsa.card_name = "HDA Intel PCH"\n')
    assert by_name(d.run_all(sysm, path), "Son du bureau (PipeWire)").status == d.INFO


def test_desktop_audio_advice_per_system():
    from trxstation.audio_devices import card_name, desktop_audio_advice
    assert "Paramètres > Son" in desktop_audio_advice("linux")
    assert "Périphérique de communication par défaut" in desktop_audio_advice("win32")
    assert card_name("USB Audio Device: - (hw:2,0)") == "USB Audio Device"
    assert card_name("plughw:CARD=CODEC,DEV=0") == "CODEC"


# --------------------------------------------------------------------------- rapport complété pour l'analyseur (étape 354)

DENIED = "No journal files were opened due to insufficient permissions."
JOURNAL = "journalctl --no-pager -n 400 " + " ".join(f"--unit={u}" for u in d.UNITS)


def test_report_has_meta_kernel_and_pi_files_and_masks_serials(tmp_path):
    import json
    sysm, path = healthy(tmp_path)
    sysm.commands["ls -l /dev/serial/by-id/"] = (0, "usb-Icom_Inc._IC-7300MK2_IC-7300MK2_13003336-if00 -> ../../ttyUSB0")
    sysm.commands["journalctl -k -b --no-pager -n 400"] = (0, "usb 1-1.3: SerialNumber: 13003336\nUnder-voltage detected! (0x00050005)")
    sysm.commands["vcgencmd get_throttled"] = (0, "throttled=0x50005")
    sysm.commands["cat /proc/device-tree/model"] = (0, "Raspberry Pi 4 Model B Rev 1.5")
    sysm.commands["timedatectl show -p Timezone --value"] = (0, "Europe/Paris\n")
    target = make_report(tmp_path, sysm=sysm, config_path=path)
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist()[0] == "rapport.json"                                  # en tête du zip
        meta = json.loads(archive.read("rapport.json"))
        kernel = archive.read("noyau.txt").decode("utf-8")
        hardware = archive.read("materiel.txt").decode("utf-8")
    assert meta["format"] == 1 and meta["fuseau"] == "Europe/Paris" and meta["cree_utc"].endswith("Z")
    assert isinstance(meta["decalage_min"], int) and meta["station"]
    assert "$ journalctl -k -b --no-pager -n 400  (code 0)" in kernel and "Under-voltage detected" in kernel
    assert "$ journalctl -k -b -1 --no-pager -n 200  (code 0)" in kernel                 # démarrage précédent
    assert "13003336" not in kernel + hardware and "SerialNumber: ***" in kernel
    assert "IC-7300MK2_***-if00" in hardware and "throttled=0x50005" in hardware and "Raspberry Pi 4" in hardware


def test_journal_refused_is_retried_by_sudo_and_both_attempts_stay_visible(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.commands[JOURNAL] = (1, DENIED)
    sysm.commands["sudo -n " + JOURNAL] = (1, "sudo: a password is required")
    target = make_report(tmp_path, sysm=sysm, config_path=path)
    with zipfile.ZipFile(target) as archive:
        journal = archive.read("journal.txt").decode("utf-8")
    assert f"$ {JOURNAL}  (code 1)\n{DENIED}" in journal
    assert f"$ sudo -n {JOURNAL}  (code 1)\nsudo: a password is required" in journal       # jamais caché


def test_kernel_falls_back_to_dmesg_when_journalctl_gives_nothing(tmp_path):
    sysm, path = healthy(tmp_path)
    for cmd in ("journalctl -k -b --no-pager -n 400", "journalctl -k -b -1 --no-pager -n 200"):
        sysm.commands[cmd] = (1, "Specifying boot ID or boot offset has no effect, no persistent journal was found.")
    sysm.commands["dmesg --ctime"] = (0, "[lun. nov. 18 10:00:00 2026] usb 1-1.3: USB disconnect, device number 4")
    target = make_report(tmp_path, sysm=sysm, config_path=path)
    with zipfile.ZipFile(target) as archive:
        kernel = archive.read("noyau.txt").decode("utf-8")
    assert "$ dmesg --ctime  (code 0)" in kernel and "USB disconnect" in kernel


def test_diagnostic_says_when_the_system_journal_is_unreadable(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_USER", "thierry")
    sysm, path = healthy(tmp_path)
    sysm.commands["journalctl --no-pager -q -n 1"] = (1, DENIED)
    check = next(c for c in d.check_system(sysm) if c.name == "Journal système")
    assert check.status == d.WARN and "thierry" in check.message and "systemd-journal thierry" in check.fix
    sysm.commands["journalctl --no-pager -q -n 1"] = (0, "-- No entries --")
    assert next(c for c in d.check_system(sysm) if c.name == "Journal système").status == d.OK


# --------------------------------------------------------------------------- réseau et Wi-Fi de la station (étape 356)

IW_DEV = "phy#0\n\tInterface wlan0\n\t\taddr dc:a6:32:01:02:03\n\t\tssid MaBox-1234\n\t\ttype managed"


def test_report_network_file_masks_mac_ssid_and_public_addresses(tmp_path):
    sysm, path = healthy(tmp_path)
    sysm.commands["ip -br link"] = (0, "wlan0  UP  dc:a6:32:01:02:03 <BROADCAST,UP>")
    sysm.commands["iw dev"] = (0, IW_DEV)
    sysm.commands["cat /proc/net/wireless"] = (0, " wlan0: 0000   43.  -67.  -256        0      0      0      0     12        0")
    sysm.commands["iw dev wlan0 link"] = (0, "Connected to 34:27:92:aa:bb:cc (on wlan0)\n\tSSID: MaBox-1234\n\tsignal: -67 dBm")
    sysm.commands["iw dev wlan0 get power_save"] = (0, "Power save: on")
    target = make_report(tmp_path, sysm=sysm, config_path=path)
    with zipfile.ZipFile(target) as archive:
        net = archive.read("reseau.txt").decode("utf-8")
    assert "$ iw dev wlan0 get power_save  (code 0)\nPower save: on" in net and "signal: -67 dBm" in net
    assert "MaBox" not in net and "dc:a6" not in net and "34:27:92" not in net
    assert "ssid ***" in net and "SSID: ***" in net
    assert "historique de la sonde réseau" in net                                 # présent ou absent : toujours dit


def test_report_joins_the_anonymous_network_history(tmp_path, monkeypatch):
    from trxstation import report
    state = tmp_path / "etat"
    (state / "netprobe").mkdir(parents=True)
    monkeypatch.setattr(report, "_state_dir", lambda sysm, config_path: state)
    data, note = report.network_history(state, "id-essai")
    assert data is not None and '"format": 1' in data and "reseau/donnees.json" in note
    assert report.network_history(tmp_path / "rien", "")[0] is None


def test_public_addresses_are_masked_private_ones_kept():
    from trxstation.report import redact_network
    text = redact_network("192.168.1.19 90.12.34.56 2a01:cb00:1234:5678::1 fe80::1 10:00:00 fd00::5")
    assert text == "192.168.1.19 adresse-publique adresse-publique fe80::1 10:00:00 fd00::5"
