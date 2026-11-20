# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Tronc commun des textes des clients (cahier docs/application-traduction-cahier-des-charges.md, lot T0) :
`trxstation/i18n/client.<langue>.json`, lu par la station, la page web (i18n.js) et l'application Android (copie à la
compilation). Mêmes clés et mêmes variables dans les quatre langues, textes de sécurité vraiment traduits, catalogues
servis par la passerelle et seulement eux."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from trxstation.i18n import FOLDER, LANGS

ROOT = Path(__file__).resolve().parent.parent
FIELD = re.compile(r"\{([a-z_]+)\}")


def load(lang: str, domain: str = "client") -> dict[str, str]:
    return json.loads((FOLDER / f"{domain}.{lang}.json").read_text(encoding="utf-8"))


def test_every_language_has_the_same_keys_and_fields_as_french():
    fr = load("fr")
    assert fr and all(isinstance(v, str) and v.strip() for v in fr.values())
    for lang in LANGS:
        other = load(lang)
        assert list(other) == list(fr), (lang, set(other) ^ set(fr))           # mêmes clés, même ordre (relecture)
        for key, text in other.items():
            assert isinstance(text, str) and text.strip(), (lang, key)
            assert set(FIELD.findall(text)) == set(FIELD.findall(fr[key])), (lang, key)


def test_safety_texts_are_really_translated():
    """Refus et coupures disent pourquoi on n'émet pas ou plus : jamais laissés en français dans une autre langue."""
    fr = load("fr")
    for lang in LANGS:
        if lang == "fr":
            continue
        other = load(lang)
        same = [key for key in fr if key.startswith(("refus.", "coupure.")) and other[key] == fr[key]]
        assert not same, (lang, same)


def test_catalogues_are_served_to_the_page_in_a_closed_list():
    from aiohttp.test_utils import TestClient, TestServer

    from trxstation.gateway.api.server import I18N_FILES, make_app

    assert set(I18N_FILES) == {f"client.{lang}.json" for lang in LANGS}

    async def scenario():
        app = make_app(object(), object())
        async with TestClient(TestServer(app)) as client:
            got = {}
            for lang in LANGS:
                resp = await client.get(f"/i18n/client.{lang}.json")
                got[lang] = (resp.status, await resp.json(content_type=None), resp.headers.get("Content-Security-Policy"))
            other = [(await client.get(path)).status
                     for path in ("/i18n/console.fr.json", "/i18n/client.xx.json", "/i18n/../i18n/__init__.py")]
            return got, other
    got, other = asyncio.run(scenario())
    for lang, (status, data, csp) in got.items():
        assert status == 200 and data == load(lang) and csp
    assert all(status == 404 for status in other)


def test_page_asks_the_route_the_station_serves():
    script = (ROOT / "trxstation" / "gateway" / "api" / "static" / "i18n.js").read_text(encoding="utf-8")
    assert '"i18n/" + domain + "." + lang + ".json"' in script
    assert re.search(r'const DOMAINS = \["client"\]', script)
