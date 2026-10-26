"""Recherche de mise à jour sur GitHub : fausses réponses de l'API, aucun accès réseau."""
from __future__ import annotations

import json

import pytest

from trxstation.update import check as chk
from trxstation.update.check import (CheckError, Release, UpdateState, choose_release, clean_text, parse_version,
                                     read_state, write_state)

DL = chk.DOWNLOAD_PREFIX


def gh(version: str, *, draft=False, prerelease=False, body="Notes", sig=True, zip_url=None, size=5_000_000,
       name=None):
    tag = f"v{version}"
    zname = f"trx-remote-debian-{version}.zip"
    assets = [{"name": zname, "size": size, "browser_download_url": zip_url or f"{DL}{tag}/{zname}"}]
    if sig:
        assets.append({"name": zname + ".sig", "size": 300, "browser_download_url": f"{DL}{tag}/{zname}.sig"})
    return {"tag_name": tag, "name": name or f"Version {version}", "body": body, "draft": draft,
            "prerelease": prerelease, "published_at": "2026-11-01T10:00:00Z",
            "html_url": f"{chk.PAGE_PREFIX}tag/{tag}", "assets": assets}


def fetch_of(items):
    payload = json.dumps(items).encode()

    def fetch(url):
        assert url == chk.API_URL
        return payload
    return fetch


def test_version_ordering():
    assert parse_version("0.23.0") > parse_version("0.22.9") > parse_version("0.22.0")
    assert parse_version("0.23.0rc1") < parse_version("0.23.0") and parse_version("0.23.0a1") < parse_version("0.23.0b1")
    assert parse_version("0.10.0") > parse_version("0.9.0")
    for bad in ("", "0.23", "0.23.0-rc1", "0.23.0.1", "latest", None, "0.23.0 ", "1.2.3\n"):
        assert parse_version(bad) is None


def test_highest_newer_stable_release_is_chosen():
    items = [gh("0.22.0"), gh("0.24.0"), gh("0.23.0"), gh("0.21.0")]
    release = choose_release(items, "0.22.0", allow_prerelease=False)
    assert release.version == "0.24.0" and release.zip_name == "trx-remote-debian-0.24.0.zip"
    assert release.sig_url.endswith("/v0.24.0/trx-remote-debian-0.24.0.zip.sig")


def test_up_to_date_gives_none():
    assert choose_release([gh("0.22.0"), gh("0.21.0")], "0.22.0", allow_prerelease=False) is None
    assert choose_release([], "0.22.0", allow_prerelease=False) is None


def test_prereleases_are_ignored_unless_allowed():
    items = [gh("0.23.0"), gh("0.24.0", prerelease=True), gh("0.25.0rc1")]
    assert choose_release(items, "0.22.0", allow_prerelease=False).version == "0.23.0"
    assert choose_release(items, "0.22.0", allow_prerelease=True).version == "0.25.0rc1"
    assert choose_release(items, "0.22.0", allow_prerelease=True).prerelease


@pytest.mark.parametrize("item", [
    gh("0.30.0", draft=True),
    gh("0.30.0", sig=False),                                               # signature absente : jamais proposée
    gh("0.30.0", zip_url="https://evil.example/trx-remote-debian-0.30.0.zip"),
    gh("0.30.0", zip_url=f"{DL}v0.29.0/trx-remote-debian-0.30.0.zip"),     # autre étiquette
    gh("0.30.0", size=0),
    gh("0.30.0", size=chk.MAX_PACKAGE_BYTES + 1),
    gh("0.30.0") | {"tag_name": "0.30.0"},                                 # étiquette sans « v »
    gh("0.30.0") | {"tag_name": "v0.30.0-beta"},
    gh("0.30.0") | {"html_url": "https://evil.example/"},
    gh("0.30.0") | {"draft": None},
    "pas un objet",
])
def test_suspicious_or_incomplete_releases_are_skipped(item):
    assert choose_release([item, gh("0.23.0")], "0.22.0", allow_prerelease=True).version == "0.23.0"


def test_unexpected_payload_is_an_error():
    with pytest.raises(CheckError):
        choose_release({"message": "Not Found"}, "0.22.0", allow_prerelease=False)
    with pytest.raises(CheckError):
        choose_release([], "inconnue", allow_prerelease=False)


def test_notes_are_cleaned_before_reaching_the_terminal():
    raw = ("Titre\x1b[2J\x1b[31m rouge\x1b[0m\r\n\x1b]0;titre fenêtre\x07ligne\x07 \x9b6n"
           "‮cba‬ fin\ttab\x00\n\n\n\nderniere")
    cleaned = clean_text(raw, 1000)
    assert "\x1b" not in cleaned and "\x07" not in cleaned and "\x9b" not in cleaned and "\x00" not in cleaned
    assert "‮" not in cleaned and "\r" not in cleaned and "\n\n\n" not in cleaned
    assert cleaned.startswith("Titre rouge\nligne") and "    tab" in cleaned and cleaned.endswith("derniere")
    assert clean_text("é" * 50, 10).startswith("é" * 10) and "suite sur GitHub" in clean_text("x" * 50, 10)
    assert clean_text("a\nb", 10, single_line=True) == "a b" and clean_text(None, 10) == ""


def test_release_title_and_notes_from_github_are_cleaned():
    release = choose_release([gh("0.23.0", name="Nom\x1b[5m\nsur deux lignes", body="\x1b[31mNotes")],
                             "0.22.0", allow_prerelease=False)
    assert release.name == "Nom sur deux lignes" and release.notes == "Notes"


def test_check_ok_and_state_file_roundtrip(tmp_path):
    state = chk.check(installed="0.22.0", fetch=fetch_of([gh("0.23.0")]), now=lambda: 1000.0)
    assert state.ok and state.release.version == "0.23.0" and state.checked_at == 1000.0
    path = chk.state_path(tmp_path)
    write_state(path, state)
    again = read_state(path)
    assert again.release == state.release and again.ok and again.installed == "0.22.0"


def test_offline_keeps_the_last_known_release_with_the_error():
    previous = chk.check(installed="0.22.0", fetch=fetch_of([gh("0.23.0")]))

    def offline(url):
        raise CheckError("GitHub injoignable (pas de réseau)")
    state = chk.check(installed="0.22.0", fetch=offline, previous=previous)
    assert not state.ok and "injoignable" in state.error and state.release.version == "0.23.0"
    # Version entre-temps installée, ou pré-version désormais refusée : plus proposée.
    assert chk.check(installed="0.23.0", fetch=offline, previous=previous).release is None
    pre = chk.check(installed="0.22.0", fetch=fetch_of([gh("0.24.0", prerelease=True)]), allow_prerelease=True)
    assert chk.check(installed="0.22.0", fetch=offline, previous=pre, allow_prerelease=False).release is None


def test_garbage_response_is_an_error_not_a_crash():
    state = chk.check(installed="0.22.0", fetch=lambda url: b"<html>pas du json")
    assert not state.ok and "illisible" in state.error and state.release is None


def test_tampered_state_file_is_not_trusted(tmp_path):
    path = chk.state_path(tmp_path)
    write_state(path, chk.check(installed="0.22.0", fetch=fetch_of([gh("0.23.0")])))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["release"]["zip_url"] = "https://evil.example/x.zip"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_state(path).release is None
    path.write_text("{", encoding="utf-8")
    assert read_state(path) is None
    assert read_state(tmp_path / "absent.json") is None
    assert Release.from_dict({"version": "0.23.0"}) is None


def test_http_get_refuses_plain_http():
    with pytest.raises(CheckError, match="https"):
        chk.http_get("http://api.github.com/")


def _config(tmp_path, update: str) -> str:
    path = tmp_path / "station.toml"
    state = (tmp_path / "state").as_posix()
    path.write_text(f'[rig]\nmodel = 1\n[supervisor]\nstate_dir = "{state}"\n{update}', encoding="utf-8")
    return str(path)


def test_main_writes_state_and_never_fails_on_network(tmp_path, capsys):
    cfg = _config(tmp_path, "")
    assert chk.main(["--config", cfg], fetch=fetch_of([gh("9.0.0")])) == 0
    assert read_state(chk.state_path(tmp_path / "state")).release.version == "9.0.0"
    assert "Nouvelle version disponible : 9.0.0" in capsys.readouterr().out

    def offline(url):
        raise CheckError("GitHub injoignable")
    assert chk.main(["--config", cfg], fetch=offline) == 0
    state = read_state(chk.state_path(tmp_path / "state"))
    assert not state.ok and state.release.version == "9.0.0"


def test_main_does_nothing_when_disabled(tmp_path):
    cfg = _config(tmp_path, "[update]\nenabled = false\n")

    def never(url):
        raise AssertionError("GitHub interrogé alors que la recherche est désactivée")
    assert chk.main(["--config", cfg], fetch=never) == 0
    assert not chk.state_path(tmp_path / "state").exists()


def test_main_refuses_invalid_config(tmp_path):
    assert chk.main(["--config", _config(tmp_path, "[update]\nallow_prerelease = \"non\"\n")],
                    fetch=fetch_of([])) == 2


def test_state_has_expected_shape():
    data = UpdateState(installed="0.22.0").to_dict()
    assert data["schema"] == chk.SCHEMA and data["release"] is None
