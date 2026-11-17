# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""trx-setup reprend la configuration existante, et protège les fichiers qu'il écrit."""
from __future__ import annotations

import os
import subprocess

import pytest

from trxstation import config as cfgmod
from trxstation import setup_wizard as sw
from trxstation.config import ClientAuth
from trxstation.passwords import hash_password


def imported_base():
    cfg = sw.dummy_config()
    cfg.rig.model, cfg.rig.port, cfg.rig.tx_modes, cfg.rig.max_power_w = 3094, "", ["PKTUSB"], 100
    cfg.supervisor.notify_url, cfg.supervisor.max_reboots_per_hour = "https://ntfy.sh/x", 0
    cfg.safety.enforce_bands = False
    cfg.clients = [ClientAuth(id="phone", password_hash=hash_password("un mot de passe solide 42"))]
    return cfg


@pytest.fixture
def no_hardware(monkeypatch):
    port = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_IC-7300-if00-port0"
    monkeypatch.setattr(sw, "list_rig_models", lambda *_: [(1, "Hamlib", "Dummy"), (3094, "Icom", "IC-7300MK2")])
    monkeypatch.setattr(sw, "list_serial_ports", lambda: [port])
    monkeypatch.setattr(sw, "test_link", lambda *a, **k: {"freq": "14074000", "mode": "PKTUSB", "ptt": "0"})
    monkeypatch.setattr(sw, "list_audio_devices",
                        lambda kind: [("USB Audio CODEC: - (hw:2,0)", "USB Audio CODEC  [ALSA]")])
    monkeypatch.setattr(sw, "is_desktop", lambda: True)
    monkeypatch.setattr(sw, "ensure_hamlib", lambda: "")
    monkeypatch.setattr("builtins.input", lambda *_: "")            # Entrée partout : réglages par défaut
    return port


def test_rerunning_the_wizard_keeps_accounts_alerts_and_choices(no_hardware, capsys):
    base = imported_base()
    cfg = sw.interactive(base)
    assert cfg.rig.model == 3094 and cfg.rig.port == no_hardware and cfg.rig.tx_modes == ["PKTUSB"]
    assert [c.id for c in cfg.clients] == ["phone"] and cfg.clients[0].password_hash == base.clients[0].password_hash
    assert cfg.supervisor.notify_url == "https://ntfy.sh/x" and cfg.supervisor.max_reboots_per_hour == 0
    assert cfg.safety.enforce_bands is False and cfg.rig.max_power_w == 100
    assert cfg.audio.capture_device == "USB Audio CODEC: - (hw:2,0)" and cfg.network.gateway_bind == "127.0.0.1"
    assert cfgmod.validate(cfg) == [] and base.rig.port == ""             # la base n'est pas modifiée


def test_fresh_config_on_a_desktop_pc_never_reboots_it(no_hardware, monkeypatch):
    answers = iter(["dummy", "1"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers, ""))
    cfg = sw.interactive(None)
    assert cfg.rig.model == 1 and cfg.supervisor.max_reboots_per_hour == 0


def test_choose_puts_the_current_value_first():
    options = [("a", "A"), ("b", "B")]
    import builtins
    original = builtins.input
    builtins.input = lambda *_: ""
    try:
        assert sw.choose("t", options, current="b") == "b"
        assert sw.choose("t", options, current="absent") == "absent"   # gardé même s'il n'est pas détecté
        assert sw.choose("t", options) == "a"
    finally:
        builtins.input = original


def test_load_base_tolerates_an_incomplete_file_and_ignores_garbage(tmp_path, capsys):
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(imported_base()), encoding="utf-8")
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(path)                                                # le service refuse toujours
    base = sw.load_base(path)
    assert base is not None and base.clients[0].id == "phone" and "à compléter" in capsys.readouterr().out
    path.write_text("[[[", encoding="utf-8")
    assert sw.load_base(path) is None and sw.load_base(None) is None


def test_local_addresses_skips_loopback_and_duplicates():
    fake = lambda *a, **k: subprocess.CompletedProcess(a, 0, "192.168.1.30 127.0.1.1 fe80::1 192.168.1.30\n", "")
    addresses = sw.local_addresses(fake, platform="linux")
    assert addresses[0] == "192.168.1.30" and addresses.count("192.168.1.30") == 1
    assert not any(a.startswith("127.") or ":" in a for a in addresses)


@pytest.mark.skipif(os.name != "posix", reason="droits POSIX")
def test_write_config_keeps_installer_permissions_and_never_widens_them(tmp_path):
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(sw.dummy_config()), encoding="utf-8")
    os.chmod(path, 0o644)
    sw.write_config(sw.dummy_config(), path)
    assert path.stat().st_mode & 0o777 == 0o640                          # repris de l'existant, sans « autres »
    os.chmod(path, 0o600)
    sw.write_config(sw.dummy_config(), path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "station.toml.bak").stat().st_mode & 0o007 == 0


def test_a_part_asks_only_its_questions_and_keeps_everything_else(no_hardware, monkeypatch):
    base = imported_base()
    base.rig.port, base.safety.tot_s = no_hardware, 90
    answers = iter(["60"])                                     # puissance : Entrée ; TOT : 60
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers) if "TOT" in prompt else "")
    called = []
    monkeypatch.setattr(sw, "test_link", lambda *a, **k: called.append("link") or {"freq": "1", "mode": "USB", "ptt": "0"})
    cfg = sw.interactive_part("emission", base)
    assert cfg.safety.tot_s == 60 and cfg.rig.max_power_w == 100 and called == []      # poste jamais interrogé
    assert [c.id for c in cfg.clients] == ["phone"] and cfg.supervisor.notify_url == "https://ntfy.sh/x"
    assert cfg.audio.capture_device == base.audio.capture_device and base.safety.tot_s == 90   # la base intacte
    cfg = sw.interactive_part("poste", base)                   # Entrée : poste gardé, port gardé, test de liaison
    assert cfg.rig.model == 3094 and cfg.rig.tx_modes == ["PKTUSB"] and called == ["link"]
    with pytest.raises(sw.SetupError):
        sw.interactive_part("inconnue", base)


def test_part_on_the_command_line_needs_an_existing_configuration(tmp_path, no_hardware, capsys):
    path = tmp_path / "station.toml"
    assert sw.main(["--output", str(path), "--partie", "bandes"]) == 2
    assert "assistant complet" in capsys.readouterr().err and not path.exists()
    cfg = imported_base()
    cfg.rig.port = no_hardware
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert sw.main(["--output", str(path), "--partie", "bandes"]) == 0        # Entrée : contrôle délégué gardé
    assert cfgmod.load(path).safety.enforce_bands is False and (tmp_path / "station.toml.bak").exists()


def test_tot_out_of_the_station_ceiling_is_asked_again_with_a_clear_reason(no_hardware, monkeypatch, capsys):
    base = imported_base()
    base.rig.port = no_hardware
    answers = iter(["5000", "100", "200", "abc", "60"])           # puissance refusée puis 100 W ; TOT refusé puis 60 s
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cfg = sw.interactive_part("emission", base)
    assert cfg.rig.max_power_w == 100 and cfg.safety.tot_s == 60
    out = capsys.readouterr().out
    assert "Refusé : un nombre entier de 0 à 2000." in out
    assert "Refusé : un nombre entier de 11 à 120. Au plus 120 s : c'est le plafond de cette station" in out
    assert "<=" not in out and "il faut" not in out


def test_validation_messages_about_the_tot_are_readable():
    cfg = sw.dummy_config()
    cfg.safety.tot_s = 200
    problems = cfgmod.validate(cfg)
    assert any(p.startswith("Durée maximale d'une émission (TOT) de 200 s refusée : elle doit être comprise entre 1 et 120 s")
               for p in problems)
    assert not any("<=" in p for p in problems)


def test_existing_accounts_are_always_kept_and_more_are_added_only_on_request(monkeypatch, capsys):
    # Étape 239 : plus de « Les garder » (non = tout effacer) ; « Ajouter d'autres comptes » (Non par défaut)
    cfg = sw.dummy_config()
    cfg.clients = [ClientAuth(id="S25", password_hash=hash_password("Motdepasse-tres-long-1"))]
    answers = iter([""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    sw.ask_accounts(cfg)
    assert [c.id for c in cfg.clients] == ["S25"]
    out = capsys.readouterr().out
    assert "gardés" in out and "4.3" in out
    answers = iter(["o", "PC", ""])              # oui, identifiant, Entrée = terminer
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(sw, "choose_password", lambda login: "Motdepasse-tres-long-2")
    sw.ask_accounts(cfg)
    assert [c.id for c in cfg.clients] == ["S25", "PC"]


def test_first_installation_asks_the_first_account_directly(monkeypatch):
    cfg = sw.dummy_config()
    cfg.clients = []
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": (prompts.append(prompt), "")[1])
    sw.ask_accounts(cfg)
    assert len(prompts) == 1 and prompts[0].startswith("Identifiant du client")
