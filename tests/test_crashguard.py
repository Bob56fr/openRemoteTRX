# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Étape 201 : plus aucune fermeture brutale d'un outil sans message, sous Debian comme sous Windows."""
from __future__ import annotations

import importlib
import socket
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from trxstation import console as con_mod
from trxstation import crashguard
from trxstation.console import Console, Runner
from trxstation.procutil import station_running
from trxstation.setup_wizard import dummy_config
from trxstation import config as cfgmod

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {"trx-gateway", "trx-supervisor", "trx-rigctld"}       # services : journaux et relance, pas de fenêtre


def guard(tmp_path, monkeypatch, *, will_close=False):
    monkeypatch.setattr(crashguard, "crash_dirs", lambda: [tmp_path / "plantages"])
    said: list[str] = []
    paused: list[bool] = []
    monkeypatch.setattr(crashguard, "pause", lambda say: paused.append(True))
    return (lambda f: crashguard.guarded("trx-essai", say=said.append, will_close=lambda: will_close)(f)), said, paused


def test_unexpected_error_gives_a_message_a_file_and_exit_code_1(tmp_path, monkeypatch):
    deco, said, paused = guard(tmp_path, monkeypatch)

    @deco
    def main(argv=None):
        raise ValueError("réponse inattendue du poste")

    assert main([]) == 1
    text = "\n".join(said)
    assert "ORT-9312" in text and "trx-essai" in text and "réponse inattendue du poste" in text
    files = list((tmp_path / "plantages").glob("trx-essai-*.txt"))
    assert len(files) == 1 and str(files[0]) in text
    content = files[0].read_text(encoding="utf-8")
    assert "Traceback" in content and "ValueError" in content
    assert paused == []                                                     # fenêtre qui reste : pas de pause


@pytest.mark.parametrize("exc, code, word", [(EOFError(), 2, "entrée est fermée"), (KeyboardInterrupt(), 130, "Interrompu")])
def test_closed_input_and_ctrl_c_are_explained(tmp_path, monkeypatch, exc, code, word):
    deco, said, _ = guard(tmp_path, monkeypatch)

    @deco
    def main(argv=None):
        raise exc

    assert main() == code and any(word in s for s in said)
    assert not (tmp_path / "plantages").exists()                            # pas un défaut du logiciel : pas de trace


def test_normal_exit_codes_are_kept_and_pause_only_after_a_failure_in_a_closing_window(tmp_path, monkeypatch):
    deco, said, paused = guard(tmp_path, monkeypatch, will_close=True)
    assert deco(lambda argv=None: 0)() == 0 and paused == []
    assert deco(lambda argv=None: None)() is None and paused == []

    def exits(argv=None):
        sys.exit(3)
    assert deco(exits)() == 3 and paused == [True]

    def boom(argv=None):
        raise RuntimeError("x")
    assert deco(boom)() == 1 and paused == [True, True]


def test_no_pause_without_a_keyboard(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setenv(crashguard.PAUSE_ENV, "1")
    assert crashguard.window_will_close() is False


def test_crash_file_falls_back_to_the_next_folder_and_old_files_are_pruned(tmp_path, monkeypatch):
    blocked = tmp_path / "pas-un-dossier"
    blocked.write_text("", encoding="utf-8")                                 # un FICHIER : mkdir échoue
    good = tmp_path / "ok"
    monkeypatch.setattr(crashguard, "KEEP_FILES", 2)
    for i in range(4):
        path = crashguard.save_crash(f"outil{i}", RuntimeError("x"), [blocked / "sous", good])
        assert path is not None and path.parent == good
    assert len(list(good.glob("*.txt"))) == 2


def test_every_operator_tool_is_guarded():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    for name, target in scripts.items():
        if name in SERVICES:
            continue
        module, func = target.split(":")
        main = getattr(importlib.import_module(module), func)
        assert getattr(main, "__trx_guarded__", None) == name, f"{name} : main sans @guarded"
    assert getattr(importlib.import_module("trxstation.tray.main").main, "__trx_guarded__", None) == "trx-tray"


def test_windows_shortcuts_keep_their_window_open():
    text = (ROOT / "windows" / "installer.ps1").read_text(encoding="utf-8-sig")
    for line in (l for l in text.splitlines() if l.startswith("New-Shortcut ") and "trxstation." in l):
        if "pythonw" in line.split('"')[2]:                                  # indicateur près de l'horloge : sans fenêtre
            continue
        assert "$ps \"-NoExit" in line, f"raccourci qui se referme à la fin : {line[:60]}"


def test_station_running_follows_the_supervisor_lock():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    try:
        assert station_running(port) is True
    finally:
        holder.close()
    assert station_running(port) is False


# ------------------------------------------------------------------------------------------------ console sous Windows

class Recorder:
    def __init__(self):
        self.calls = []

    def run(self, cmd, *, admin=False):
        self.calls.append((cmd, admin))
        return 0

    def output(self, cmd):
        raise AssertionError(f"systemctl interrogé sous Windows : {cmd}")


def windows_console(tmp_path, monkeypatch, running=False):
    monkeypatch.setattr(con_mod, "IS_WINDOWS", True)
    import trxstation.procutil as procutil
    monkeypatch.setattr(procutil, "station_running", lambda port: running)
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    out: list[str] = []
    rec = Recorder()
    return Console(tmp_path / "station.toml", rec, ask=lambda _: "", say=out.append, python="py"), rec, out


def test_windows_console_starts_and_stops_without_sudo_nor_systemctl(tmp_path, monkeypatch):
    con, rec, out = windows_console(tmp_path, monkeypatch)
    con.start()
    con.stop()
    assert rec.calls[0] == (["schtasks", "/Run", "/TN", "TRX distant"], False)
    cmd, admin = rec.calls[1]
    assert cmd[:3] == ["py", "-m", "trxstation.supervisor.main"] and cmd[-1] == "--stop" and admin is False


def test_windows_console_stops_a_running_station_before_the_rig_test(tmp_path, monkeypatch):
    con, rec, out = windows_console(tmp_path, monkeypatch, running=True)
    assert con.stop_for_exclusive_use("essai") is True
    assert rec.calls[-1][0][-1] == "--stop"


def test_windows_journal_shows_the_log_files(tmp_path, monkeypatch):
    con, rec, out = windows_console(tmp_path, monkeypatch)
    con.journal()
    assert any("logs" in s for s in out)                                    # aucun journal : le dossier est nommé
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "passerelle.log").write_text("\n".join(f"ligne {i}" for i in range(200)), encoding="utf-8")
    out.clear()
    con.journal()
    assert "ligne 199" in "\n".join(out) and "ligne 100" not in "\n".join(out) and rec.calls == []


def test_sudo_only_on_debian(monkeypatch):
    seen = []
    envs = []
    monkeypatch.setattr(con_mod.subprocess, "call", lambda cmd, env=None: seen.append(cmd) or envs.append(env) or 0)
    runner = Runner()
    runner.is_root = False
    runner.run(["outil"], admin=True)
    assert (seen[-1][0] == "sudo") == (con_mod.os.name == "posix")
    assert envs[-1]["TRX_LANG"] == runner.t.lang                       # outils dans la langue de la console (L3)
    if con_mod.os.name == "posix":
        assert seen[-1][:3] == ["sudo", "env", f"TRX_LANG={runner.t.lang}"]   # sudo vide l'environnement


def test_report_contains_the_crash_files(tmp_path, monkeypatch):
    from trxstation import report
    crash = tmp_path / "etat" / crashguard.CRASH_DIR_NAME
    crash.mkdir(parents=True)
    (crash / "trx-hwtest-20261116-150000-1.txt").write_text("Traceback ...", encoding="utf-8")
    monkeypatch.setattr(crashguard, "crash_dirs", lambda: [])
    monkeypatch.setattr(report, "_state_dir", lambda sysm, path: tmp_path / "etat")
    path = report.make_report(tmp_path, config_path=tmp_path / "absent.toml")
    with zipfile.ZipFile(path) as z:
        assert z.read("plantages/trx-hwtest-20261116-150000-1.txt").decode() == "Traceback ..."
