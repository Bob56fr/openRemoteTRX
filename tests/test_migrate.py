"""Import d'une configuration Windows vers Debian."""
from __future__ import annotations

import os
import subprocess

from trxstation import config as cfgmod
from trxstation.config import ClientAuth
from trxstation.migrate import LINUX_STATE_DIR, LINUX_STATUS_PATH, import_config, is_desktop, main
from trxstation.passwords import hash_password
from trxstation.setup_wizard import dummy_config


def windows_config():
    cfg = dummy_config()
    cfg.rig.model, cfg.rig.port, cfg.rig.ptt_port = 3094, "COM8", r"\\.\COM9"
    cfg.rig.tx_modes, cfg.rig.max_power_w = ["PKTUSB", "PKTLSB"], 100
    cfg.audio.capture_device, cfg.audio.playback_device = "Microphone (USB Audio Device)", "Haut-parleurs (USB Audio Device)"
    cfg.tools.hamlib_dir = r"C:\Program Files\hamlib-w64-4.6"
    cfg.network.gateway_bind, cfg.network.allow_insecure_http = "192.168.1.21", True
    cfg.network.tls_cert, cfg.network.tls_key = r"C:\ProgramData\trx-remote\tls\c.pem", r"C:\ProgramData\trx-remote\tls\k.pem"
    cfg.supervisor.notify_url = "https://ntfy.sh/sujet-secret"
    cfg.supervisor.status_path, cfg.supervisor.state_dir = r"C:\ProgramData\trx-remote\run\s.json", r"C:\ProgramData\trx-remote\state"
    cfg.supervisor.service_mode = "managed"
    cfg.clients = [ClientAuth(id="phone", password_hash=hash_password("un mot de passe solide 42")), ClientAuth()]
    return cfg


def test_machine_specific_settings_are_cleared_and_the_rest_is_kept():
    source = windows_config()
    cfg, notes = import_config(source, desktop=True)
    assert cfg.rig.port == "" and cfg.rig.ptt_port == "" and cfg.tools.hamlib_dir == ""
    assert cfg.audio.capture_device == "" and cfg.audio.playback_device == ""
    assert cfg.network.gateway_bind == "127.0.0.1" and cfg.network.tls_cert == "" and cfg.network.tls_key == ""
    assert cfg.supervisor.status_path == LINUX_STATUS_PATH and cfg.supervisor.state_dir == LINUX_STATE_DIR
    assert cfg.supervisor.service_mode == "auto" and cfg.supervisor.max_reboots_per_hour == 0
    assert [c.id for c in cfg.clients] == ["phone"] and cfg.clients[0].password_hash == source.clients[0].password_hash
    assert cfg.supervisor.notify_url == "https://ntfy.sh/sujet-secret"
    assert (cfg.rig.model, cfg.rig.tx_modes, cfg.rig.max_power_w) == (3094, ["PKTUSB", "PKTLSB"], 100)
    assert cfg.bands == source.bands and cfg.safety == source.safety
    assert source.rig.port == "COM8"                                      # la source n'est pas modifiée
    assert cfgmod.validate(cfg) == ["[rig] port : requis pour un vrai poste"]
    text = "\n".join(notes)
    assert "COM8" in text and "ntfy" in text and "phone" in text and "1 compte(s) incomplet(s)" in text
    assert "sujet-secret" not in text                                      # pas de secret dans les messages


def test_synthetic_audio_loopback_and_wildcard_bind_are_kept():
    cfg = dummy_config()
    cfg.audio.capture_device, cfg.audio.playback_device = "tone:1000", "null"
    for bind in ("0.0.0.0", "127.0.0.1"):
        cfg.network.gateway_bind = bind
        new, _ = import_config(cfg, desktop=False)
        assert new.network.gateway_bind == bind and new.audio.capture_device == "tone:1000"
        assert new.supervisor.max_reboots_per_hour == cfg.supervisor.max_reboots_per_hour


def test_main_writes_a_protected_starting_point(tmp_path, capsys):
    source, destination = tmp_path / "station.toml", tmp_path / "etc" / "station.import.toml"
    source.write_text(cfgmod.render_toml(windows_config()), encoding="utf-8")
    assert main([str(source), str(destination), "--bureau"]) == 0
    cfg, problems = cfgmod.load_unchecked(destination)
    assert cfg.rig.port == "" and cfg.clients[0].id == "phone" and problems == ["[rig] port : requis pour un vrai poste"]
    out = capsys.readouterr().out
    assert "À compléter" in out and "sujet-secret" not in out
    if os.name == "posix":
        assert destination.stat().st_mode & 0o007 == 0


def test_main_refuses_an_unreadable_file(tmp_path, capsys):
    bad = tmp_path / "station.toml"
    bad.write_text("ceci n'est [pas du toml", encoding="utf-8")
    assert main([str(bad), str(tmp_path / "out.toml")]) == 2
    assert not (tmp_path / "out.toml").exists()


def test_is_desktop_reads_the_default_boot_target(monkeypatch):
    monkeypatch.setattr("trxstation.migrate.shutil.which", lambda name: "/bin/systemctl")
    graphical = lambda *a, **k: subprocess.CompletedProcess(a, 0, "graphical.target\n", "")
    text_only = lambda *a, **k: subprocess.CompletedProcess(a, 0, "multi-user.target\n", "")
    assert is_desktop(graphical, platform="linux") is True
    assert is_desktop(text_only, platform="linux") is False
    assert is_desktop(graphical, platform="win32") is False


def test_windows_spectrum_port_is_disabled_with_a_note_and_the_address_kept():
    cfg = windows_config()
    cfg.rig.model = 3094
    cfg.spectrum.enabled, cfg.spectrum.source, cfg.spectrum.port, cfg.spectrum.civ_address = True, "civ_port", "COM7", "B6"
    out, notes = import_config(cfg, desktop=True)
    assert (out.spectrum.enabled, out.spectrum.port, out.spectrum.civ_address, out.spectrum.source) == (False, "", "B6", "civ_port")
    assert any("trx-setup --spectre" in n and "COM7" in n for n in notes)
    assert not [p for p in cfgmod.validate(out) if "spectrum" in p]                     # aucun blocage dû au spectre
