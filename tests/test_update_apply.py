"""Installation d'une mise à jour : refusée en émission ou au moindre doute, jamais sans signature valide."""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from trxstation import config as cfgmod  # noqa: E402
from trxstation.status import GatewayStatus  # noqa: E402
from trxstation.supervisor.rigctl import RigProbe  # noqa: E402
from trxstation.update import apply as ap  # noqa: E402
from trxstation.update import check as chk  # noqa: E402
from trxstation.update import keyfile, signing  # noqa: E402
from trxstation.update.apply import TransmitRefused, UpdateRefused, transmit_doubt  # noqa: E402

V = "9.0.0"                     # toujours plus récente que la version installée
ROOT_DIR = f"trx-remote-debian-{V}"
ZIP_NAME = f"{ROOT_DIR}.zip"
DL = f"{chk.DOWNLOAD_PREFIX}v{V}/"


def make_zip(files: dict[str, bytes] | None = None, *, version: str = V, links: tuple[str, ...] = ()) -> bytes:
    root = f"trx-remote-debian-{version}"
    files = files if files is not None else {
        f"{root}/install.sh": b"#!/bin/bash\necho installe\n",
        f"{root}/releases.sh": b"# versions\n",
        f"{root}/app/pyproject.toml": f'[project]\nname = "trx-station"\nversion = "{version}"\n'.encode(),
        f"{root}/app/trxstation/__init__.py": b"",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            archive.writestr(info, data)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return buf.getvalue()


def gh_release(version: str = V, size: int = 100) -> dict:
    name = f"trx-remote-debian-{version}.zip"
    base = f"{chk.DOWNLOAD_PREFIX}v{version}/"
    return {"tag_name": f"v{version}", "name": version, "body": "Notes", "draft": False, "prerelease": False,
            "published_at": "", "html_url": f"{chk.PAGE_PREFIX}tag/v{version}",
            "assets": [{"name": name, "size": size, "browser_download_url": base + name},
                       {"name": name + ".sig", "size": 300, "browser_download_url": base + name + ".sig"}]}


def status(seq: int, state: str = "RX") -> GatewayStatus:
    return GatewayStatus(pid=42, seq=seq, written_at=0.0, ptt={"state": state}, rig={})


class FakeSystem:
    def __init__(self, *, active=("trx-gateway.service", "rigctld.service"), states=("RX",),
                 probe=RigProbe(True, False), install_code=0, frozen=False):
        self.active, self.states, self.probe_result = set(active), list(states), probe
        self.install_code, self.frozen = install_code, frozen
        self.calls: list[str] = []
        self.seq = 0
        self.seen_install: bytes | None = None

    def system(self) -> ap.System:
        return ap.System(is_active=lambda unit: unit in self.active, stop_station=self.stop, run_script=self.run,
                         read_status=self.read, probe=self.probe, sleep=lambda s: None)

    def read(self):
        if "trx-gateway.service" not in self.active:
            return None
        if not self.frozen:
            self.seq += 1
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return status(self.seq, state)

    def probe(self):
        self.calls.append("probe")
        return self.probe_result

    def stop(self):
        self.calls.append("stop")
        self.active.clear()
        return True

    def run(self, cmd):
        self.calls.append("run:" + " ".join(Path(c).name if "/" in c or "\\" in c else c for c in cmd))
        script = Path(cmd[1])
        self.seen_install = script.read_bytes()
        return self.install_code


@pytest.fixture
def world(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(signing, "PUBLIC_KEYS", (keyfile.public_text(private),))
    package = tmp_path / "src" / ZIP_NAME
    package.parent.mkdir()
    package.write_bytes(make_zip())
    files = {DL + ZIP_NAME: package.read_bytes(), DL + ZIP_NAME + ".sig": signing.sign_file(package, V, private).encode()}
    return {"files": files, "releases": [gh_release(size=len(files[DL + ZIP_NAME]))], "work": tmp_path / "cache",
            "private": private, "fetched": []}


def updater(world, fake: FakeSystem, messages=None) -> ap.Updater:
    def fetch(url):
        world["fetched"].append(url)
        return json.dumps(world["releases"]).encode()

    def download(url, max_bytes):
        world["fetched"].append(url)
        data = world["files"][url]
        assert len(data) <= max_bytes
        return data
    cfg = cfgmod.from_dict({"rig": {"model": 1}})
    return ap.Updater(cfg, fake.system(), say=(messages.append if messages is not None else lambda m: None),
                      fetch=fetch, download=download, installed="0.22.0", work_root=world["work"])


# ------------------------------------------------------------------ émission en cours ?

@pytest.mark.parametrize("kwargs,refused", [
    ({"gateway_active": True, "rigctld_active": True, "first": status(1), "second": status(2),
      "probe": RigProbe(True, False)}, False),
    ({"gateway_active": True, "rigctld_active": True, "first": status(1), "second": status(2, "TX"),
      "probe": RigProbe(True, False)}, True),
    ({"gateway_active": True, "rigctld_active": True, "first": status(1, "KEYING"), "second": status(2),
      "probe": RigProbe(True, False)}, True),
    ({"gateway_active": True, "rigctld_active": True, "first": status(1, "UNKEYING"), "second": status(2, "UNKEYING"),
      "probe": RigProbe(True, False)}, True),
    ({"gateway_active": True, "rigctld_active": True, "first": status(1), "second": status(1),
      "probe": RigProbe(True, False)}, True),                                          # passerelle gelée
    ({"gateway_active": True, "rigctld_active": True, "first": None, "second": None,
      "probe": RigProbe(True, False)}, True),                                          # pas de fichier d'état
    ({"gateway_active": True, "rigctld_active": True, "first": status(1), "second": status(2),
      "probe": RigProbe(True, True)}, True),                                           # le poste émet
    ({"gateway_active": False, "rigctld_active": True, "first": None, "second": None,
      "probe": RigProbe(False, error="x")}, True),                                     # rigctld muet
    ({"gateway_active": False, "rigctld_active": True, "first": None, "second": None,
      "probe": RigProbe(True, None)}, True),                                           # PTT illisible, sans passerelle
    ({"gateway_active": True, "rigctld_active": True, "first": status(1), "second": status(2),
      "probe": RigProbe(True, None)}, False),                                          # illisible mais passerelle RX vivante
    ({"gateway_active": False, "rigctld_active": False, "first": None, "second": None,
      "probe": RigProbe(False, error="x")}, False),                                    # station arrêtée
    ({"gateway_active": False, "rigctld_active": False, "first": None, "second": None,
      "probe": RigProbe(True, False)}, False),
])
def test_transmit_doubt(kwargs, refused):
    assert (transmit_doubt(**kwargs) is not None) == refused


# ------------------------------------------------------------------ installation

def test_verified_package_is_installed_after_stopping_the_station(world):
    fake, messages = FakeSystem(), []
    assert updater(world, fake, messages).install(V) == ap.EXIT_OK
    assert fake.calls[-2:] == ["stop", "run:bash install.sh"]
    assert fake.seen_install == b"#!/bin/bash\necho installe\n"
    assert "Signature vérifiée." in messages
    assert not any(world["work"].iterdir())                                   # dossier de travail effacé


def test_transmitting_refuses_before_anything_is_downloaded(world):
    fake = FakeSystem(states=("TX",))
    with pytest.raises(TransmitRefused):
        updater(world, fake).install(V)
    assert world["fetched"] == [] and "stop" not in fake.calls


def test_rig_keyed_without_gateway_is_refused(world):
    fake = FakeSystem(probe=RigProbe(True, True))
    with pytest.raises(TransmitRefused, match="poste est en émission"):
        updater(world, fake).install(V)
    assert "stop" not in fake.calls


def test_frozen_gateway_is_refused(world):
    fake = FakeSystem(frozen=True)
    with pytest.raises(TransmitRefused, match="muette"):
        updater(world, fake).install(V)


def test_transmission_started_during_download_is_refused_before_stopping(world):
    fake = FakeSystem(states=("RX", "RX", "TX"))              # 2 lectures au début, TX à la seconde vérification
    with pytest.raises(TransmitRefused):
        updater(world, fake).install(V)
    assert "stop" not in fake.calls and not any(c.startswith("run:") for c in fake.calls)


def test_stopped_station_can_be_updated(world):
    fake = FakeSystem(active=(), probe=RigProbe(False, error="refusé"))
    assert updater(world, fake).install(V) == ap.EXIT_OK


def _assert_nothing_installed(fake):
    assert "stop" not in fake.calls and not any(c.startswith("run:") for c in fake.calls)


def test_signature_from_another_key_is_refused(world):
    other = Ed25519PrivateKey.generate()
    package = world["work"].parent / "src" / ZIP_NAME
    world["files"][DL + ZIP_NAME + ".sig"] = signing.sign_file(package, V, other).encode()
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="SIGNATURE REFUSÉE"):
        updater(world, fake).install(V)
    _assert_nothing_installed(fake)


def test_tampered_package_of_same_size_is_refused(world):
    data = bytearray(world["files"][DL + ZIP_NAME])
    data[-30] ^= 0xFF
    world["files"][DL + ZIP_NAME] = bytes(data)
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="SIGNATURE REFUSÉE"):
        updater(world, fake).install(V)
    _assert_nothing_installed(fake)


def test_truncated_download_is_refused(world):
    world["files"][DL + ZIP_NAME] = world["files"][DL + ZIP_NAME][:-5]
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="taille"):
        updater(world, fake).install(V)
    _assert_nothing_installed(fake)


def test_missing_signature_is_refused(world):
    world["files"][DL + ZIP_NAME + ".sig"] = b""
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="SIGNATURE"):
        updater(world, fake).install(V)
    _assert_nothing_installed(fake)


def test_no_trusted_key_means_no_installation(world, monkeypatch):
    monkeypatch.setattr(signing, "PUBLIC_KEYS", ())
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="aucune clé"):
        updater(world, fake).install(V)
    _assert_nothing_installed(fake)


def test_confirmed_version_must_still_be_the_one_offered(world):
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="0.24.0"):
        updater(world, fake).install("0.24.0")
    world["releases"] = []
    with pytest.raises(UpdateRefused, match="aucune"):
        updater(world, fake).install(V)
    _assert_nothing_installed(fake)


def test_github_unreachable_is_refused(world):
    fake = FakeSystem()
    up = updater(world, fake)

    def offline(url):
        raise chk.CheckError("GitHub injoignable")
    up.fetch = offline
    with pytest.raises(UpdateRefused, match="injoignable"):
        up.install(V)
    _assert_nothing_installed(fake)


def test_failed_install_script_is_reported(world):
    fake = FakeSystem(install_code=1)
    assert updater(world, fake).install(V) == ap.EXIT_FAILED


# ------------------------------------------------------------------ contenu du zip

def _members(data: bytes, version: str = V):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return ap.safe_members(archive, version)


def test_valid_package_contents_are_accepted():
    assert len(_members(make_zip())) == 4


@pytest.mark.parametrize("extra", [
    {"../evil.sh": b"x"},
    {f"{ROOT_DIR}/../../etc/cron.d/x": b"x"},
    {"/etc/passwd": b"x"},
    {"autre-dossier/install.sh": b"x"},
    {f"{ROOT_DIR}\\..\\x": b"x"},
    {f"C:/{ROOT_DIR}/x": b"x"},
])
def test_dangerous_paths_are_refused(extra):
    files = {f"{ROOT_DIR}/install.sh": b"", f"{ROOT_DIR}/releases.sh": b"",
             f"{ROOT_DIR}/app/pyproject.toml": f'[project]\nversion = "{V}"\n'.encode(),
             f"{ROOT_DIR}/app/trxstation/__init__.py": b""} | extra
    with pytest.raises(UpdateRefused):
        _members(make_zip(files))


def test_symlinks_are_refused():
    with pytest.raises(UpdateRefused, match="lien"):
        _members(make_zip(links=(f"{ROOT_DIR}/app/lien",)))


def test_incomplete_package_is_refused():
    with pytest.raises(UpdateRefused, match="install.sh"):
        _members(make_zip({f"{ROOT_DIR}/app/pyproject.toml": f'[project]\nversion = "{V}"\n'.encode()}))


def test_package_version_must_match():
    data = make_zip({f"{ROOT_DIR}/install.sh": b"", f"{ROOT_DIR}/releases.sh": b"",
                     f"{ROOT_DIR}/app/pyproject.toml": b'[project]\nversion = "0.24.0"\n',
                     f"{ROOT_DIR}/app/trxstation/__init__.py": b""})
    with pytest.raises(UpdateRefused, match="contient la version 0.24.0"):
        _members(data)


def test_extraction_keeps_script_executable(tmp_path):
    package = tmp_path / ZIP_NAME
    package.write_bytes(make_zip())
    source = ap.extract(package, V, tmp_path / "out")
    assert (source / "install.sh").read_bytes().startswith(b"#!/bin/bash")
    if sys.platform != "win32":
        assert os.stat(source / "install.sh").st_mode & 0o111


# ------------------------------------------------------------------ retour à la version précédente

def test_rollback_without_previous_version_is_refused(world, tmp_path):
    up = updater(world, FakeSystem())
    up.app_dir = tmp_path / "opt"
    with pytest.raises(UpdateRefused, match="aucune version précédente"):
        up.rollback()


@pytest.mark.skipif(sys.platform == "win32", reason="liens symboliques")
def test_rollback_runs_previous_install_script_after_checking_ptt(world, tmp_path):
    app = tmp_path / "opt"
    (app / "releases" / "0.22.0").mkdir(parents=True)
    (app / "releases" / "0.22.0" / "install.sh").write_text("#!/bin/bash\n")
    os.symlink("releases/0.22.0", app / "previous")
    fake = FakeSystem()
    up = updater(world, fake)
    up.app_dir = app
    assert up.rollback() == ap.EXIT_OK
    assert fake.calls[-2:] == ["stop", "run:bash install.sh --reactiver"]
    tx = FakeSystem(states=("TX",))
    up = updater(world, tx)
    up.app_dir = app
    with pytest.raises(TransmitRefused):
        up.rollback()
    assert "stop" not in tx.calls


@pytest.mark.skipif(sys.platform == "win32", reason="liens symboliques")
def test_previous_link_outside_releases_is_ignored(world, tmp_path):
    app = tmp_path / "opt"
    (app / "releases").mkdir(parents=True)
    (tmp_path / "ailleurs").mkdir()
    (tmp_path / "ailleurs" / "install.sh").write_text("#!/bin/bash\n")
    os.symlink(tmp_path / "ailleurs", app / "previous")
    up = updater(world, FakeSystem())
    up.app_dir = app
    assert up.previous_release() is None


# ------------------------------------------------------------------ commande

def _main(world, fake, *argv, tmp_path):
    cfg = tmp_path / "station.toml"
    cfg.write_text("[rig]\nmodel = 1\n", encoding="utf-8")
    up = updater(world, fake)
    return ap.main(["--config", str(cfg), *argv], system=fake.system(), fetch=up.fetch, download=up.download,
                   work_root=world["work"])


def test_main_exit_codes(world, tmp_path, capsys):
    assert _main(world, FakeSystem(states=("TX",)), "install", "--version", V, tmp_path=tmp_path) == ap.EXIT_TX
    assert "Rien n'a été installé" in capsys.readouterr().err
    world["files"][DL + ZIP_NAME + ".sig"] = b"faux"
    assert _main(world, FakeSystem(), "install", "--version", V, tmp_path=tmp_path) == ap.EXIT_REFUSED


# ------------------------------------------------------------------ paquet déposé sur la machine (menu 13)

def dropped(tmp_path, *, version=V, signed=None, data=None, name=None):
    """Paquet posé sur le « Bureau » ; `signed` : clé privée qui signe (None = pas de .sig)."""
    desk = tmp_path / "Bureau"
    desk.mkdir(exist_ok=True)
    package = desk / (name or f"trx-remote-debian-{version}.zip")
    package.write_bytes(data if data is not None else make_zip(version=version))
    if signed is not None:
        package.with_name(package.name + ".sig").write_text(signing.sign_file(package, version, signed), encoding="utf-8")
    return package


def test_local_signed_package_is_verified_then_installed(world, tmp_path):
    package = dropped(tmp_path, signed=world["private"])
    fake, messages = FakeSystem(), []
    assert updater(world, fake, messages).install_local(package) == ap.EXIT_OK
    assert "Signature vérifiée." in messages and fake.calls[-2:] == ["stop", "run:bash install.sh"]
    assert world["fetched"] == []                                              # rien n'est demandé à Internet
    assert package.exists() and not any(world["work"].iterdir())               # original laissé, travail effacé


def test_local_unsigned_package_needs_the_explicit_flag(world, tmp_path):
    package = dropped(tmp_path)
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="non signé"):
        updater(world, fake).install_local(package)
    _assert_nothing_installed(fake)
    messages = []
    assert updater(world, fake, messages).install_local(package, allow_unsigned=True) == ap.EXIT_OK
    assert any("NON signé" in m for m in messages)


def test_local_bad_signature_is_refused_even_with_the_flag(world, tmp_path):
    package = dropped(tmp_path, signed=Ed25519PrivateKey.generate())         # signé par une autre clé
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="SIGNATURE REFUSÉE"):
        updater(world, fake).install_local(package, allow_unsigned=True)
    _assert_nothing_installed(fake)


def test_local_package_checks_name_content_and_transmission(world, tmp_path):
    fake = FakeSystem()
    with pytest.raises(UpdateRefused, match="nom de paquet"):
        updater(world, fake).install_local(dropped(tmp_path, name="station.zip"), allow_unsigned=True)
    root = "trx-remote-debian-9.0.1"                                          # nom et dossier 9.0.1, pyproject 9.0.0
    lying = make_zip({f"{root}/install.sh": b"#!/bin/bash\n", f"{root}/releases.sh": b"#\n",
                      f"{root}/app/pyproject.toml": f'[project]\nversion = "{V}"\n'.encode(),
                      f"{root}/app/trxstation/__init__.py": b""})
    wrong = dropped(tmp_path, version="9.0.1", data=lying)
    with pytest.raises(UpdateRefused, match="contient la version"):
        updater(world, fake).install_local(wrong, allow_unsigned=True)
    with pytest.raises(UpdateRefused, match="lien"):
        updater(world, fake).install_local(dropped(tmp_path, data=make_zip(links=(f"{ROOT_DIR}/x",))),
                                           allow_unsigned=True)
    _assert_nothing_installed(fake)
    tx = FakeSystem(states=("TX",))
    with pytest.raises(TransmitRefused):
        updater(world, tx).install_local(dropped(tmp_path), allow_unsigned=True)
    _assert_nothing_installed(tx)


def test_local_command_line(world, tmp_path, capsys):
    package = dropped(tmp_path)
    assert _main(world, FakeSystem(), "local", "--zip", str(package), tmp_path=tmp_path) == ap.EXIT_REFUSED
    assert "non signé" in capsys.readouterr().err
    assert _main(world, FakeSystem(), "local", "--zip", str(package), "--sans-signature", tmp_path=tmp_path) == ap.EXIT_OK
