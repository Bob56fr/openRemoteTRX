"""Diagnostic : section « Mise à jour » (lecture seule)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trxstation import __version__
from trxstation import config as cfgmod
from trxstation import diagnostics as d
from trxstation.update import check as chk
from trxstation.update import pubkey


class Sys(d.System):
    def __init__(self, files=None, previous=None):
        self.files, self.prev = files or {}, previous

    def read_text(self, path):
        return self.files.get(Path(path).as_posix())

    def now(self):
        return 100_000.0

    def previous_version(self):
        return self.prev


def cfg(**update) -> cfgmod.Config:
    return cfgmod.from_dict({"rig": {"model": 1}, "supervisor": {"state_dir": "/var/lib/trx-remote"},
                             "update": update})


def state_file(**kw) -> dict[str, str]:
    state = chk.UpdateState(installed=__version__, checked_at=kw.pop("checked_at", 100_000.0 - 3600), **kw)
    return {chk.state_path("/var/lib/trx-remote").as_posix(): json.dumps(state.to_dict())}


def release(version: str) -> chk.Release:
    name = chk.package_name(version)
    base = f"{chk.DOWNLOAD_PREFIX}v{version}/"
    return chk.Release(version=version, tag=f"v{version}", name=version, notes="", published_at="",
                       page_url=f"{chk.PAGE_PREFIX}tag/v{version}", prerelease=False, zip_name=name,
                       zip_url=base + name, zip_size=10, sig_url=base + name + ".sig")


def by_name(checks):
    return {c.name: c for c in checks}


@pytest.fixture(autouse=True)
def with_key(monkeypatch):
    monkeypatch.setattr(pubkey, "PUBLIC_KEYS", ("A" * 43 + "=",))


def test_installed_and_previous_versions_are_shown():
    checks = by_name(d.check_update(Sys(previous="0.22.0"), None))
    assert checks["Version installée"].message == __version__
    assert "0.22.0" in checks["Version précédente"].message


def test_missing_signing_key_is_a_warning(monkeypatch):
    monkeypatch.setattr(pubkey, "PUBLIC_KEYS", ())
    assert by_name(d.check_update(Sys(), None))["Clé de signature"].status == d.WARN


def test_up_to_date():
    check = by_name(d.check_update(Sys(state_file(ok=True)), cfg()))["Recherche de mise à jour"]
    assert check.status == d.OK and "il y a 1 h" in check.message


def test_new_version_points_to_the_menu():
    checks = by_name(d.check_update(Sys(state_file(ok=True, release=release("99.0.0"))), cfg()))
    assert "99.0.0" in checks["Nouvelle version"].message and "Menu 10" in checks["Nouvelle version"].fix


def test_already_installed_version_is_not_announced():
    checks = by_name(d.check_update(Sys(state_file(ok=True, release=release(__version__))), cfg()))
    assert "Nouvelle version" not in checks and checks["Recherche de mise à jour"].status == d.OK


def test_failed_or_old_check_is_a_warning():
    failed = by_name(d.check_update(Sys(state_file(ok=False, error="GitHub injoignable")), cfg()))
    assert failed["Recherche de mise à jour"].status == d.WARN and "injoignable" in failed["Recherche de mise à jour"].message
    old = by_name(d.check_update(Sys(state_file(ok=True, checked_at=100_000.0 - 4 * 86400)), cfg()))
    assert old["Recherche de mise à jour"].status == d.WARN and "jours" in old["Recherche de mise à jour"].message


def test_disabled_or_not_yet_checked_is_information():
    assert by_name(d.check_update(Sys(), cfg(enabled=False)))["Recherche de mise à jour"].status == d.INFO
    assert "pas encore" in by_name(d.check_update(Sys(), cfg()))["Recherche de mise à jour"].message


def test_update_section_never_blocks_the_diagnostic():
    checks = d.check_update(Sys(state_file(ok=False, error="x")), cfg())
    assert all(c.status != d.FAIL for c in checks)
