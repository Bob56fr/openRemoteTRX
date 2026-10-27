# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console : enchaînement des actions (commandes simulées)."""
from __future__ import annotations

from trxstation import config as cfgmod
from trxstation.console import TARGET, Console, main
from trxstation.setup_wizard import dummy_config


class FakeRunner:
    def __init__(self, running: bool = False, code: int = 0, creates=None):
        self.calls: list[tuple[list[str], bool]] = []
        self.running, self.code, self.creates = running, code, creates

    def run(self, cmd, *, admin=False):
        self.calls.append((cmd, admin))
        if cmd[:2] == ["systemctl", "stop"]:
            self.running = False
        if cmd[:2] in (["systemctl", "restart"], ["systemctl", "start"]):
            self.running = True
        if "trxstation.setup_wizard" in cmd:
            if self.code == 0 and self.creates is not None:          # l'assistant a écrit la configuration
                self.creates.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
            return self.code
        return 0

    def output(self, cmd):
        return "active" if self.running else "inactive"


def console(tmp_path, answers=(), **runner):
    script = iter(answers)
    out: list[str] = []
    fake = FakeRunner(**runner)
    con = Console(tmp_path / "station.toml", fake, ask=lambda _: next(script, ""), say=out.append, python="py")
    return con, fake, out


def write_config(tmp_path):
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")


def test_assistant_stops_the_station_uses_the_import_and_restarts(tmp_path):
    (tmp_path / "station.import.toml").write_text("", encoding="utf-8")
    con, fake, out = console(tmp_path, answers=["o"], running=True, creates=tmp_path / "station.toml")
    con.assistant()
    commands = [c for c, _ in fake.calls]
    assert commands[0] == ["systemctl", "stop", TARGET]
    setup = next(c for c in commands if "trxstation.setup_wizard" in c)
    assert setup[:3] == ["py", "-m", "trxstation.setup_wizard"] and "--base" in setup
    assert all(admin for c, admin in fake.calls if c[0] == "systemctl" or "setup_wizard" in c)
    assert ["systemctl", "restart", TARGET] in commands               # station relancée à la demande
    assert any("Reprise de la configuration importée" in line for line in out)


def test_failed_assistant_changes_nothing_and_restores_the_running_station(tmp_path):
    write_config(tmp_path)
    con, fake, out = console(tmp_path, running=True, code=1)
    con.assistant()
    commands = [c for c, _ in fake.calls]
    assert ["systemctl", "start", TARGET] in commands and "--base" not in commands[1]
    assert any("rien n'a été modifié" in line for line in out)


def test_hwtest_needs_a_configuration_and_frees_the_port_first(tmp_path):
    con, fake, out = console(tmp_path)
    con.hwtest()
    assert fake.calls == [] and any("menu 2" in line for line in out)
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["2", "n"], running=True)
    con.hwtest()
    commands = [c for c, _ in fake.calls]
    assert commands[0] == ["systemctl", "stop", TARGET] and "trxstation.devtools.hwtest" in commands[1]
    assert "--reception-seule" not in commands[1]                      # essai complet
    assert ["systemctl", "restart", TARGET] not in commands            # « n » : station laissée arrêtée


def test_hwtest_offers_a_reception_only_run_and_can_be_cancelled(tmp_path):
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["1", "n"])
    con.hwtest()
    assert fake.calls[-1][0][-1] == "--reception-seule"
    con, fake, out = console(tmp_path, answers=[""], running=True)
    con.hwtest()
    assert fake.calls == [] and out[-1] == "Annulé."                    # rien arrêté, rien lancé


def test_leaving_safe_mode_requires_an_explicit_yes(tmp_path):
    write_config(tmp_path)
    con, fake, _ = console(tmp_path, answers=[""])
    con.clear_safe_mode()
    assert fake.calls == []                                            # défaut : non
    con, fake, _ = console(tmp_path, answers=["o"])
    con.clear_safe_mode()
    assert "--clear-safe-mode" in fake.calls[0][0] and fake.calls[0][1] is True
    assert fake.calls[1][0] == ["systemctl", "restart", TARGET]


def test_first_launch_offers_the_assistant_then_menu_quits(tmp_path):
    con, fake, out = console(tmp_path, answers=["n", "z", "", "q"])
    assert con.loop() == 0
    assert any("PAS ENCORE CONFIGURÉE" in line for line in out) and any("Choix inconnu" in line for line in out)
    assert fake.calls == []


def test_diagnostic_command_line_returns_an_exit_code(tmp_path, capsys):
    assert main(["--diagnostic", "--config", str(tmp_path / "absent.toml")]) in (0, 1)
    assert "Bilan" in capsys.readouterr().out
