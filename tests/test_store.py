# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Version Microsoft Store (cahier `docs/store-microsoft-cahier-des-charges.md`) : identité, manifeste, lanceur de la
station, TRX Console, coexistence avec le zip."""
import importlib.util
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from trxstation import packaging, store_boot
from trxstation.errors import codes

ROOT = Path(__file__).resolve().parent.parent
NS = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
      "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
      "uap5": "http://schemas.microsoft.com/appx/manifest/uap/windows10/5",
      "uap10": "http://schemas.microsoft.com/appx/manifest/uap/windows10/10",
      "desktop": "http://schemas.microsoft.com/appx/manifest/desktop/windows10",
      "desktop2": "http://schemas.microsoft.com/appx/manifest/desktop/windows10/2"}


def build_msix():
    spec = importlib.util.spec_from_file_location("build_msix", ROOT / "scripts" / "build_msix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- identité


def test_publisher_id_matches_windows():
    microsoft = "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US"
    assert packaging.publisher_id(microsoft) == "8wekyb3d8bbwe"            # Microsoft.WindowsCalculator_8wekyb3d8bbwe


def test_package_family_name_and_links(monkeypatch):
    ident = build_msix().identity()
    family = packaging.family_name(ident["name"], ident["publisher"])
    assert family == "RF-DIY.COM.openRemoteTRX_5fxpmskyjpc1g"
    monkeypatch.setattr(packaging, "package_full_name", lambda: "RF-DIY.COM.openRemoteTRX_0.253.0.0_x64__5fxpmskyjpc1g")
    assert packaging.package_family_name() == family
    assert packaging.store_page_link() == f"ms-windows-store://pdp/?PFN={family}"
    assert packaging.app_launch_command("Supervisor") == ["explorer.exe", f"shell:AppsFolder\\{family}!Supervisor"]
    monkeypatch.setattr(packaging, "package_full_name", lambda: None)
    assert packaging.store_page_link() is None and packaging.app_launch_command("Supervisor") is None


def test_the_zip_installer_refuses_next_to_the_store_package():
    name = build_msix().identity()["name"]
    text = (ROOT / "windows" / "installer.ps1").read_text(encoding="utf-8-sig")
    assert f'Get-AppxPackage -Name "{name}"' in text


# --------------------------------------------------------------------------- manifeste


def _manifest():
    mod = build_msix()
    return mod, ET.fromstring(mod.manifest(mod.identity(), mod.package_version("0.253.0")).encode("utf-8"))


def test_manifest_identity_version_and_windows():
    mod, root = _manifest()
    ident = root.find("m:Identity", NS)
    assert ident.get("Name") == "RF-DIY.COM.openRemoteTRX"
    assert ident.get("Publisher") == "CN=4DBA8C0D-D395-454A-A7A5-5CB99996408C"
    assert ident.get("Version") == "0.253.0.0" and ident.get("ProcessorArchitecture") == "x64"
    assert root.find("m:Properties/m:PublisherDisplayName", NS).text == "RF-DIY.COM"
    assert root.find("m:Dependencies/m:TargetDeviceFamily", NS).get("MinVersion") == "10.0.19045.0"   # Windows 10 22H2
    assert [r.get("Language") for r in root.findall("m:Resources/m:Resource", NS)] == ["fr-FR", "en-US", "de-DE", "es-ES"]
    with pytest.raises(SystemExit):
        mod.package_version("0.253")


def test_manifest_aliases_are_the_commands_of_the_zip():
    _, root = _manifest()
    aliases = {a.get("Alias") for a in root.iter(f"{{{NS['uap5']}}}ExecutionAlias")}
    zip_line = re.search(r"^\$Commands = @\((.*)\)", (ROOT / "windows" / "installer.ps1").read_text(encoding="utf-8-sig"), re.M)
    zip_commands = {c.strip().strip('"') for c in zip_line.group(1).split(",")}
    assert aliases == {c + ".exe" for c in zip_commands}


def test_manifest_applications_pass_the_store_validation():
    _, root = _manifest()
    apps = root.findall("m:Applications/m:Application", NS)
    assert [a.get("Id") for a in apps] == ["Console", "Supervisor"]
    assert len(apps) <= 8, "le Store refuse plus de 8 applications par paquet"
    assert all(a.find("uap:VisualElements", NS).get("AppListEntry") is None for a in apps), \
        "le Store refuse une application cachée du menu Démarrer sans dérogation (HeadlessAppBypass)"
    console, station = apps
    assert console.get(f"{{{NS['uap10']}}}Parameters") == "-m trxstation.store_cli"
    assert station.get("Executable") == "python\\trx-station.exe"
    assert station.get(f"{{{NS['uap10']}}}Parameters") is None, "la tâche de démarrage ignore les paramètres"
    assert station.find(".//desktop:StartupTask", NS) is not None
    assert not list(station.iter(f"{{{NS['uap5']}}}ExecutionAlias")), "jamais d'alias pour pythonw avec paramètres"
    rules = root.findall(".//desktop2:FirewallRules", NS)
    assert {r.get("Executable") for r in rules} == {"python\\python.exe", "python\\pythonw.exe", "python\\trx-station.exe"}
    assert all(rule.get("Profile") == "private" for r in rules for rule in r.findall("desktop2:Rule", NS))
    assert root.find("m:Capabilities", NS)[0].get("Name") == "runFullTrust"


def test_every_alias_reaches_its_command():
    from trxstation import store_cli
    assert store_cli.COMMANDS == build_msix().commands(), "même liste que [project.scripts] moins les services"
    aliases = Path(r"C:\Users\x\AppData\Local\Microsoft\WindowsApps")
    for command, module in store_cli.COMMANDS.items():
        source = ROOT / (module.replace(".", "/") + ".py")
        assert '__name__ == "__main__"' in source.read_text(encoding="utf-8"), module
        assert store_cli.module_for(str(aliases / f"{command}.exe")) == module
    assert store_cli.module_for(r"C:\Program Files\WindowsApps\pkg\python\python.exe") == "trxstation.console"


def test_boot_module_only_acts_for_the_launcher_without_arguments():
    mod = build_msix()
    assert "trx-station.exe" in mod.BOOT_MODULE and "sys.argv in ([], [\"\"])" in mod.BOOT_MODULE
    assert "import site" in mod.PTH and "Lib\\site-packages" in mod.PTH


# --------------------------------------------------------------------------- lanceur de la station


def test_maybe_boot_never_acts_for_another_program(monkeypatch):
    called = []
    monkeypatch.setattr(store_boot, "boot", lambda **kw: called.append(1) or 0)
    monkeypatch.setattr(sys, "executable", r"C:\pkg\python\pythonw.exe")
    monkeypatch.setattr(sys, "argv", [""])
    store_boot.maybe_boot()
    monkeypatch.setattr(sys, "executable", r"C:\pkg\python\trx-station.exe")
    monkeypatch.setattr(sys, "argv", ["-m", "trxstation.gateway.main"])         # passerelle lancée par le superviseur
    store_boot.maybe_boot()
    assert called == []


def test_boot_runs_the_supervisor_with_the_default_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("TRX_REMOTE_HOME", str(tmp_path / "data"))
    seen = []
    assert store_boot.boot(supervisor_main=seen.append, zip_check=lambda: False, setup_logs=False) == 0
    assert seen == [], "station pas configurée : rien ne démarre"
    assert (tmp_path / "data" / "logs").is_dir()
    (tmp_path / "data" / "station.toml").write_text("", encoding="utf-8")
    store_boot.boot(supervisor_main=lambda argv: seen.append(argv) or 0, zip_check=lambda: False, setup_logs=False)
    assert seen == [["--config", str(tmp_path / "data" / "station.toml"), "--log-dir", str(tmp_path / "data" / "logs")]]


def test_boot_refuses_when_the_zip_version_is_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRX_REMOTE_HOME", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "station.toml").write_text("", encoding="utf-8")
    events, seen = [], []
    monkeypatch.setattr("trxstation.errors.emit.emit_event", lambda code, **kw: events.append(code))
    rc = store_boot.boot(supervisor_main=seen.append, zip_check=lambda: True, setup_logs=False)
    assert rc == store_boot.EXIT_ZIP_INSTALLED and seen == [] and events == [codes.ORT_8029]


def test_data_dir_is_restricted_only_when_created(tmp_path, monkeypatch):
    monkeypatch.setattr(store_boot.sys, "platform", "win32")
    calls = []
    run = lambda cmd, **kw: calls.append(cmd)                                      # noqa: E731
    store_boot.prepare_data_dir(tmp_path / "trx-remote", run=run)
    assert calls and calls[0][0] == "icacls" and "/inheritance:r" in calls[0]
    store_boot.prepare_data_dir(tmp_path / "trx-remote", run=run)
    assert len(calls) == 1, "dossier existant (zip, installation précédente) : droits inchangés"


def test_zip_installed_reads_the_scheduled_task(monkeypatch):
    monkeypatch.setattr(store_boot.sys, "platform", "win32")

    class Done:
        def __init__(self, rc):
            self.returncode = rc
    assert store_boot.zip_installed(run=lambda cmd, **kw: Done(0)) is True
    assert store_boot.zip_installed(run=lambda cmd, **kw: Done(1)) is False


# --------------------------------------------------------------------------- TRX Console


def test_console_store_starts_the_station_like_windows_and_sends_updates_to_the_store(tmp_path, monkeypatch):
    import trxstation.console as module
    from test_console_tools import make
    monkeypatch.setattr(module, "IS_WINDOWS", True)
    monkeypatch.setattr(packaging, "package_full_name", lambda: "RF-DIY.COM.openRemoteTRX_0.253.0.0_x64__5fxpmskyjpc1g")
    monkeypatch.setattr(store_boot, "zip_installed", lambda: False)
    con, fake, out = make(tmp_path)
    con._start_station()
    assert fake.calls[-1][0] == ["explorer.exe", "shell:AppsFolder\\RF-DIY.COM.openRemoteTRX_5fxpmskyjpc1g!Supervisor"]
    for menu in ("update", "rollback", "install_zip"):
        con, fake, out = make(tmp_path)
        getattr(con, menu)()
        assert "Microsoft Store" in out[-1] and "ms-windows-store://pdp/?PFN=" in out[-1] and fake.calls == []
    monkeypatch.setattr(store_boot, "zip_installed", lambda: True)
    con, fake, out = make(tmp_path)
    assert con._start_station() == 1 and fake.calls == [] and "ORT-8029" in out[-1]


def test_subprocesses_never_use_an_execution_alias(tmp_path, monkeypatch):
    import trxstation.console as module
    from test_console_tools import Runner
    aliases = tmp_path / "Microsoft" / "WindowsApps"
    aliases.mkdir(parents=True)
    prefix = tmp_path / "pkg" / "python"
    prefix.mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (prefix / name).write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "executable", str(aliases / "trx-console.exe"))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    con = module.Console(tmp_path / "station.toml", Runner(), ask=lambda _: "", say=lambda _: None,
                         installed="0.253.0", home=tmp_path)
    assert con.module("trxstation.x")[0] == str(prefix / "python.exe")
    assert module.windows_pythonw() == str(prefix / "pythonw.exe")
