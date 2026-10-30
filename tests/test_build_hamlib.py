# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Dernière version publique de Hamlib écrite dans le compiler-hamlib.sh du paquet Debian (sans réseau ici)."""
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "ae1fcf2dbc80ea0786ea8f047b09399c3f7737d1930442f61a031708ed33e88f"


def _builder():
    spec = importlib.util.spec_from_file_location("build_debian_zip", ROOT / "scripts" / "build_debian_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _github(tag="4.8.0", sums=None):
    pages = {"https://api.github.com/repos/Hamlib/Hamlib/releases/latest": json.dumps({"tag_name": tag}),
             f"https://github.com/Hamlib/Hamlib/releases/download/{tag}/SHA256SUM-{tag}":
                 sums if sums is not None else f"{SHA} *hamlib-{tag}.tar.gz\n"}

    def fetch(url):
        if url not in pages:
            raise OSError(f"adresse inattendue {url}")
        return pages[url]
    return fetch


def test_latest_release_and_its_checksum_are_read_from_github():
    b = _builder()
    assert b.latest_hamlib(_github()) == ("4.8.0", SHA)
    assert b.parse_hamlib_sums(f"{SHA.upper()}  hamlib-4.8.0.tar.gz\n", "4.8.0") == SHA


@pytest.mark.parametrize("fetch", [
    _github(tag="4.8.0; rm -rf /"),                                     # numéro de version douteux
    _github(sums=f"{SHA}  hamlib-4.7.9.tar.gz\n"),                      # empreinte d'une autre archive
    _github(sums="pas une empreinte  hamlib-4.8.0.tar.gz\n"),
    lambda url: (_ for _ in ()).throw(OSError("pas de réseau")),
    lambda url: "pas du json",
])
def test_anything_unexpected_is_a_lookup_error(fetch):
    b = _builder()
    with pytest.raises(b.HamlibLookupError):
        b.latest_hamlib(fetch)


def test_zip_carries_the_version_found_and_the_repository_keeps_its_pinned_one(tmp_path):
    b = _builder()
    target = b.build(ROOT, tmp_path, ("4.8.0", SHA))
    with zipfile.ZipFile(target) as archive:
        script = next(archive.read(n).decode() for n in archive.namelist() if n.endswith("/compiler-hamlib.sh"))
    assert "\nHAMLIB_VERSION=4.8.0\n" in script and f"\nHAMLIB_SHA256={SHA}\n" in script
    assert b.pinned_hamlib(ROOT) != "?"
    with pytest.raises(ValueError):
        b.with_hamlib(b"HAMLIB_VERSION=1\nHAMLIB_SHA256=x\n", ("4.8.0", "court"))


def test_signed_package_is_refused_without_hamlib_but_trial_zip_keeps_the_pinned_version(tmp_path, capsys):
    b = _builder()

    def offline():
        raise b.HamlibLookupError("pas de réseau")
    assert b.main(["--cle", str(tmp_path / "absente.pem")], out_dir=tmp_path, find_hamlib=offline) == 1
    assert not list(tmp_path.glob("*.zip"))
    assert b.main(["--sans-signature"], out_dir=tmp_path, find_hamlib=offline) == 0
    assert "ATTENTION" in capsys.readouterr().out
