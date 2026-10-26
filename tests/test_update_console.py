"""TRX Console : annonce de la nouvelle version, installation confirmée, retour à la version précédente."""
from __future__ import annotations

import os
import sys

import pytest

from trxstation import console as con_mod
from trxstation.console import Console, previous_version
from trxstation.update import apply as upd
from trxstation.update import check as chk


def release(version="0.23.0", notes="Corrections", prerelease=False) -> chk.Release:
    name = chk.package_name(version)
    base = f"{chk.DOWNLOAD_PREFIX}v{version}/"
    return chk.Release(version=version, tag=f"v{version}", name=f"Version {version}", notes=notes,
                       published_at="2026-11-01", page_url=f"{chk.PAGE_PREFIX}tag/v{version}",
                       prerelease=prerelease, zip_name=name, zip_url=base + name, zip_size=1000,
                       sig_url=base + name + ".sig")


class Runner:
    def __init__(self, code=0):
        self.calls: list[tuple[list[str], bool]] = []
        self.code = code

    def run(self, cmd, *, admin=False):
        self.calls.append((cmd, admin))
        return self.code if "trxstation.update.apply" in cmd else 0

    def output(self, cmd):
        return "inactive"


def make(tmp_path, answers=(), state=None, previous=None, code=0, installed="0.22.0"):
    script = iter(answers)
    out: list[str] = []
    runner = Runner(code)
    con = Console(tmp_path / "station.toml", runner, ask=lambda _: next(script, ""), say=out.append, python="py",
                  update_state=lambda: state, previous=lambda: previous, installed=installed)
    return con, runner, out


def text(out):
    return "\n".join(out)


def test_header_announces_a_newer_version(tmp_path):
    con, _, _ = make(tmp_path, state=chk.UpdateState(installed="0.22.0", ok=True, release=release()))
    assert "Nouvelle version 0.23.0 disponible : menu 10" in con.header()
    con, _, _ = make(tmp_path, state=chk.UpdateState(installed="0.22.0", ok=True, release=release()),
                     installed="0.23.0")                         # déjà installée : plus annoncée
    assert "Nouvelle version" not in con.header()
    con, _, _ = make(tmp_path, state=None)
    assert "Nouvelle version" not in con.header()


def test_menu_lists_update_and_rollback(tmp_path):
    con, _, _ = make(tmp_path)
    keys = {key: label for key, label, _ in con.items}
    assert keys["10"].startswith("Mise à jour") and keys["11"] == "Revenir à la version précédente"


def test_update_shows_notes_and_installs_only_after_typed_confirmation(tmp_path):
    state = chk.UpdateState(installed="0.22.0", ok=True, release=release(notes="Ligne 1\nLigne 2"))
    con, runner, out = make(tmp_path, answers=["o"], state=state)            # « o » n'est pas le numéro
    con.update()
    assert runner.calls == [] and "annulée" in text(out) and "Ligne 1\nLigne 2" in text(out)
    con, runner, out = make(tmp_path, answers=["0.23.0"], state=state)
    con.update()
    cmd, admin = runner.calls[0]
    assert admin and cmd == ["py", "-m", "trxstation.update.apply", "--config", str(tmp_path / "station.toml"),
                             "install", "--version", "0.23.0"]
    assert "Version 0.23.0 installée" in text(out)


def test_notes_from_a_tampered_state_file_are_cleaned_again(tmp_path):
    state = chk.UpdateState(installed="0.22.0", ok=True, release=release(notes="\x1b[2Jefface\x07"))
    con, _, out = make(tmp_path, state=state)
    con.update()
    assert "\x1b" not in text(out) and "\x07" not in text(out) and "efface" in text(out)


def test_prerelease_is_flagged(tmp_path):
    con, _, out = make(tmp_path, state=chk.UpdateState(installed="0.22.0", ok=True,
                                                       release=release("0.23.0rc1", prerelease=True)))
    con.update()
    assert "PRÉ-VERSION" in text(out)


@pytest.mark.parametrize("code,expected", [
    (upd.EXIT_TX, "le poste émet"), (upd.EXIT_REFUSED, "paquet non vérifié"), (upd.EXIT_FAILED, "inchangée")])
def test_update_failures_are_explained(tmp_path, code, expected):
    state = chk.UpdateState(installed="0.22.0", ok=True, release=release())
    con, _, out = make(tmp_path, answers=["0.23.0"], state=state, code=code)
    con.update()
    assert expected in text(out)


def test_up_to_date_and_failed_check(tmp_path):
    con, runner, out = make(tmp_path, state=chk.UpdateState(installed="0.22.0", ok=False, error="GitHub injoignable"))
    con.update()
    assert "injoignable" in text(out) and "à jour" in text(out) and runner.calls == []


def test_no_check_yet_can_start_one_as_the_trx_account(tmp_path):
    (tmp_path / "station.toml").write_text("", encoding="utf-8")
    con, runner, out = make(tmp_path, answers=["o"], state=None)
    con.update()
    assert runner.calls == [(["systemctl", "start", con_mod.CHECK_UNIT], True)]


def test_rollback_requires_a_previous_version_and_an_explicit_yes(tmp_path):
    con, runner, out = make(tmp_path, previous=None)
    con.rollback()
    assert runner.calls == [] and "Aucune version précédente" in text(out)
    con, runner, _ = make(tmp_path, answers=[""], previous="0.22.0", installed="0.23.0")
    con.rollback()
    assert runner.calls == []                                             # défaut : non
    con, runner, out = make(tmp_path, answers=["o"], previous="0.22.0", installed="0.23.0")
    con.rollback()
    cmd, admin = runner.calls[0]
    assert admin and cmd[-1] == "rollback" and "trxstation.update.apply" in cmd
    assert "Retour à la version 0.22.0 fait" in text(out)


@pytest.mark.skipif(sys.platform == "win32", reason="liens symboliques")
def test_previous_version_reads_the_link(tmp_path):
    assert previous_version(tmp_path) is None
    (tmp_path / "releases" / "0.22.0").mkdir(parents=True)
    os.symlink("releases/0.22.0", tmp_path / "previous")
    assert previous_version(tmp_path) is None                             # pas d'install.sh : inutilisable
    (tmp_path / "releases" / "0.22.0" / "install.sh").write_text("#!/bin/bash\n")
    assert previous_version(tmp_path) == "0.22.0"


def test_previous_version_without_link_is_none(tmp_path):
    assert previous_version(tmp_path) is None
