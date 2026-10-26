"""Signature du paquet Debian par build_debian_zip.py, telle que la station la vérifiera."""
from __future__ import annotations

import importlib.util
import tomllib
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from trxstation.update import keyfile, signing  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
PASS = "une phrase de passe assez longue"


def _builder():
    spec = importlib.util.spec_from_file_location("build_debian_zip", ROOT / "scripts" / "build_debian_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def key(tmp_path):
    path = tmp_path / "cle" / "signature.pem"
    public = keyfile.public_text(keyfile.create(path, PASS.encode()))
    return path, (public,)


def _run(tmp_path, *argv, keys, ask=lambda _p: PASS):
    out = tmp_path / "dist"
    code = _builder().main(list(argv), out_dir=out, ask=ask, public_keys=keys)
    target = out / f"trx-remote-debian-{VERSION}.zip"
    return code, target, target.with_name(target.name + ".sig")


def test_signed_package_verifies_like_on_the_station(tmp_path, key):
    path, keys = key
    code, target, sig = _run(tmp_path, "--cle", str(path), keys=keys)
    assert code == 0 and sig.is_file()
    info = signing.verify_file(target, sig.read_text(encoding="utf-8"), expected_file=target.name,
                               expected_version=VERSION, public_keys=keys)
    assert info.version == VERSION
    assert b"\r\n" not in sig.read_bytes()


def test_package_ships_the_verifier_and_public_keys_but_no_private_key(tmp_path, key):
    path, keys = key
    _, target, _ = _run(tmp_path, "--cle", str(path), keys=keys)
    names = zipfile.ZipFile(target).namelist()
    prefix = f"trx-remote-debian-{VERSION}/app/trxstation/update/"
    assert {prefix + "signing.py", prefix + "pubkey.py"} <= set(names)
    assert not [n for n in names if n.endswith((".pem", ".key", ".sig"))]


def test_missing_key_gives_no_signature(tmp_path, key):
    _, keys = key
    code, target, sig = _run(tmp_path, "--cle", str(tmp_path / "absente.pem"), keys=keys)
    assert code == 1 and target.is_file() and not sig.exists()


def test_key_unknown_to_the_stations_is_refused(tmp_path, key):
    path, _ = key
    code, _, sig = _run(tmp_path, "--cle", str(path), keys=())
    assert code == 1 and not sig.exists()


def test_wrong_passphrase_is_refused(tmp_path, key):
    path, keys = key
    code, _, sig = _run(tmp_path, "--cle", str(path), keys=keys, ask=lambda _p: "fausse phrase de passe")
    assert code == 1 and not sig.exists()


def test_rebuild_removes_stale_signature(tmp_path, key):
    path, keys = key
    _, _, sig = _run(tmp_path, "--cle", str(path), keys=keys)
    assert sig.exists()
    code, target, sig = _run(tmp_path, "--sans-signature", keys=keys)
    assert code == 0 and target.is_file() and not sig.exists()


def test_unencrypted_key_does_not_ask_for_passphrase(tmp_path):
    path = tmp_path / "claire.pem"
    keys = (keyfile.public_text(keyfile.create(path, None)),)

    def never(_prompt):
        raise AssertionError("phrase de passe demandée pour une clé non chiffrée")
    code, _, sig = _run(tmp_path, "--cle", str(path), keys=keys, ask=never)
    assert code == 0 and sig.is_file()
