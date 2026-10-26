"""Section [spectrum] : désactivée par défaut, rigctld lancé en diffusion locale, serveur de commandes UDP interdit."""
from __future__ import annotations

import tomllib

import pytest

from trxstation import config as cfgmod
from trxstation import migrate
from trxstation.hamlib import rigctld_command

ICOM = {"rig": {"model": 3094, "port": "COM8", "speed": 115200}}


def build(**sections) -> cfgmod.Config:
    return cfgmod.from_dict({**ICOM, **sections})


def command(cfg) -> list[str]:
    return rigctld_command(cfg, env={}, which=lambda name: "/usr/bin/" + name, globber=lambda p: [])


def test_disabled_by_default_and_rigctld_unchanged():
    cfg = build()
    assert cfg.spectrum.enabled is False
    cmd = command(cfg)
    assert not any("async" in a or "multicast" in a for a in cmd)          # Hamlib 4.5 (Debian 12) ne connaît pas ces options


def test_enabled_spectrum_stays_on_the_machine_and_never_opens_the_udp_command_server():
    cmd = command(build(spectrum={"enabled": True, "data_port": 4600}))
    conf = cmd[cmd.index("-C") + 1]
    assert conf == "async=1,multicast_data_addr=127.0.0.1,multicast_data_port=4600,multicast_cmd_addr=0.0.0.0"
    assert cmd[cmd.index("-T") + 1] == "127.0.0.1"


def test_roundtrip():
    cfg = build(spectrum={"enabled": True, "data_port": 4600, "max_fps": 5})
    again = cfgmod.from_dict(tomllib.loads(cfgmod.render_toml(cfg)))
    assert (again.spectrum.enabled, again.spectrum.data_port, again.spectrum.max_fps) == (True, 4600, 5)


@pytest.mark.parametrize("extra", [["multicast_cmd_addr=224.0.0.1"], ["dtr_state=OFF,Multicast_Cmd_Addr=0.0.0.0"],
                                   ["async=1"], ["multicast_data_addr=192.168.1.255"], ["multicast_cmd_port=4532"]])
def test_reserved_options_are_refused_in_extra_conf_even_when_disabled(extra):
    with pytest.raises(cfgmod.ConfigError, match="extra_conf"):
        cfgmod.from_dict({"rig": {**ICOM["rig"], "extra_conf": extra}})


def test_other_extra_conf_still_accepted():
    cfg = cfgmod.from_dict({"rig": {**ICOM["rig"], "extra_conf": ["rts_state=OFF,dtr_state=OFF"]}})
    assert "rts_state=OFF,dtr_state=OFF" in command(cfg)


def test_low_serial_speed_is_refused_when_enabled():
    with pytest.raises(cfgmod.ConfigError, match="115200"):
        cfgmod.from_dict({"rig": {**ICOM["rig"], "speed": 19200}, "spectrum": {"enabled": True}})
    cfgmod.from_dict({"rig": {**ICOM["rig"], "speed": 19200}})              # désactivé : aucune exigence


def test_default_speed_is_a_warning():
    cfg = cfgmod.from_dict({"rig": {"model": 3094, "port": "COM8"}, "spectrum": {"enabled": True}})
    assert any("[spectrum]" in w and "115200" in w for w in cfgmod.warnings(cfg))


@pytest.mark.parametrize("spectrum", [{"enabled": "true"}, {"enabled": 1}, {"data_port": 80}, {"data_port": True},
                                      {"max_fps": 0}, {"max_fps": 21}, {"max_fps": 2.5}, {"inconnu": 1}])
def test_invalid_values_are_refused(spectrum):
    with pytest.raises(cfgmod.ConfigError, match=r"\[spectrum\]"):
        build(spectrum=spectrum)


def test_print_shows_the_spectrum_options(tmp_path, capsys):
    from trxstation import run_rigctld
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(build(spectrum={"enabled": True})), encoding="utf-8")
    assert run_rigctld.main(["--config", str(path), "--print"]) == 0
    assert "multicast_cmd_addr=0.0.0.0" in capsys.readouterr().out


def test_import_from_another_pc_keeps_the_choice():
    cfg, _ = migrate.import_config(build(spectrum={"enabled": True, "max_fps": 4}), desktop=True)
    assert (cfg.spectrum.enabled, cfg.spectrum.max_fps) == (True, 4)


def test_diagnostic_requires_hamlib_46_when_spectrum_is_enabled():
    from trxstation import diagnostics as d

    class Sys(d.System):
        def __init__(self, version):
            self.version = version

        def module_present(self, name):
            return True

        def find_tool(self, name, hamlib_dir=""):
            return "/usr/bin/rigctld"

        def run(self, cmd, timeout=15):
            return 0, f"rigctld Hamlib {self.version} 2024-01-01T00:00:00Z SHA=x\n"

    enabled = build(spectrum={"enabled": True})
    status = lambda version, cfg: {c.name: c for c in d.check_software(Sys(version), cfg)}.get("Spectre HF")   # noqa: E731
    assert status("4.5.4", enabled).status == d.FAIL
    assert status("4.6", enabled).status == d.OK and status("4.7.2", enabled).status == d.OK
    assert status("4.5.4", build()) is None                                  # désactivé : pas de contrôle
    assert d.hamlib_version("rigctld Hamlib 4.7.2 2026") == (4, 7, 2) and d.hamlib_version("rien") is None
