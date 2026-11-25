# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mises à jour signalées sous « Connecter » de l'application (étape 392) : la dernière APK publiée est relevée par
trx-update-check dans latest.json, et la station l'annonce dans `hello.updates` à ses opérateurs (jamais aux visiteurs)."""
from __future__ import annotations

from test_api import connect, run, station
from test_update_check import fetch_of, gh

from trxstation import __version__
from trxstation.config import Access, ClientAuth
from trxstation.gateway.api.access import AccessControl
from trxstation.update import check as chk
from trxstation.update.check import AppRelease, UpdateState, latest_app, read_state, state_path, write_state


def with_apk(item: dict, name: str) -> dict:
    item["assets"].append({"name": name, "size": 30_000_000,
                           "browser_download_url": f"{chk.DOWNLOAD_PREFIX}{item['tag_name']}/{name}"})
    return item


def test_latest_apk_is_the_highest_version_code_of_a_published_release():
    items = [with_apk(gh("0.282.0"), "openRemoteTRX-0.90.0-97.apk"),
             with_apk(gh("0.258.0"), "openRemoteTRX-0.87.0-94.apk"),
             with_apk(gh("0.290.0", draft=True), "openRemoteTRX-0.99.0-120.apk"),          # brouillon : ignoré
             with_apk(gh("0.291.0", prerelease=True), "openRemoteTRX-0.98.0-110.apk"),     # pré-version : selon le choix
             with_apk(gh("0.200.0"), "openRemoteTRX-play-0.95.0-105.aab")]                # pas une APK
    best = latest_app(items, allow_prerelease=False)
    assert best == AppRelease("0.90.0", 97, f"{chk.PAGE_PREFIX}tag/v0.282.0")
    assert latest_app(items, allow_prerelease=True).code == 110
    assert latest_app("pas une liste", allow_prerelease=False) is None


def test_suspicious_apk_entries_are_not_trusted():
    item = with_apk(gh("0.282.0"), "openRemoteTRX-0.90.0-97.apk")
    item["html_url"] = "https://exemple.invalid/piege"
    assert latest_app([item], allow_prerelease=False) is None
    assert AppRelease.from_dict({"version": "0.90.0", "code": True, "page_url": chk.PAGE_PREFIX}) is None
    assert AppRelease.from_dict({"version": "x", "code": 97, "page_url": chk.PAGE_PREFIX}) is None


def test_apk_survives_the_state_file_and_an_offline_check(tmp_path):
    items = [with_apk(gh("9.0.0"), "openRemoteTRX-1.2.3-200.apk")]
    state = chk.check(installed="0.282.0", fetch=fetch_of(items))
    assert state.ok and state.app == AppRelease("1.2.3", 200, f"{chk.PAGE_PREFIX}tag/v9.0.0")
    path = tmp_path / "latest.json"
    write_state(path, state)
    assert read_state(path).app == state.app

    def offline(url):
        raise chk.CheckError("hors ligne")
    kept = chk.check(installed="0.282.0", fetch=offline, previous=read_state(path))
    assert not kept.ok and kept.app == state.app
    old = UpdateState(installed="0.282.0").to_dict()
    del old["app"]                                                     # fichier d'une station antérieure à l'étape 392
    path.write_text(__import__("json").dumps(old), encoding="utf-8")
    assert read_state(path) is not None and read_state(path).app is None


def test_hello_announces_updates_to_operators_only(tmp_path):
    async def scenario(fake):
        async with station(fake) as st:
            st.ctrl.config.supervisor.state_dir = str(tmp_path)
            phone = await connect(st, "phone")
            assert phone.of_type("hello")[0]["updates"] is None                              # pas de latest.json
            newer = chk.Release(version="9.0.0", tag="v9.0.0", name="v9", notes="", published_at="",
                                page_url=f"{chk.PAGE_PREFIX}tag/v9.0.0", prerelease=False,
                                zip_name=chk.package_name("9.0.0"),
                                zip_url=f"{chk.DOWNLOAD_PREFIX}v9.0.0/{chk.package_name('9.0.0')}", zip_size=1000,
                                sig_url=f"{chk.DOWNLOAD_PREFIX}v9.0.0/{chk.package_name('9.0.0')}.sig")
            app = AppRelease("1.2.3", 200, f"{chk.PAGE_PREFIX}tag/v9.0.0")
            write_state(state_path(tmp_path), UpdateState(installed=__version__, ok=True, release=newer, app=app))
            access = AccessControl([ClientAuth("car", password_hash="x"), ClientAuth("club1", password_hash="y", role="listener")],
                                   Access(max_listeners=1))
            access.switch.open = True
            access.admit("car")
            car = await connect(st, "car", access=access)
            assert car.of_type("hello")[0]["updates"] == {
                "station": {"version": "9.0.0", "page_url": f"{chk.PAGE_PREFIX}tag/v9.0.0"},
                "app": {"version": "1.2.3", "code": 200, "page_url": f"{chk.PAGE_PREFIX}tag/v9.0.0"}}
            access.admit("club1")
            visitor = await connect(st, "club1", role="listener", access=access)
            assert visitor.of_type("hello")[0]["updates"] is None
            # station déjà à jour (latest.json plus ancien que la version qui tourne) : seulement l'application
            write_state(state_path(tmp_path), UpdateState(installed=__version__, ok=True, release=None, app=app))
            again = await connect(st, "car", access=access)
            assert again.of_type("hello")[0]["updates"] == {"station": None, "app": app.__dict__ | {}}
    run(scenario)
