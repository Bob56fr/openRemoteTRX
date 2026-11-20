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


# ---------------------------------------------------------------- lot T1 : textes de la station dans la langue du client

def test_client_language_is_a_closed_list_and_error_texts_fall_back_to_english():
    from trxstation.gateway.api.texts import clean_lang, client_text, errors_lang

    assert [clean_lang(v) for v in ("de", "es", "en", "fr", "it", "", None, 3, "DE")] == \
        ["de", "es", "en", "fr", "fr", "fr", "fr", "fr", "fr"]
    assert errors_lang("fr") == "fr" and errors_lang("en") == "en"
    assert errors_lang("de") in ("de", "en") and errors_lang("es") in ("es", "en")      # catalogue d'erreurs : lot T8
    assert client_text("de", "refus.out_of_band") == load("de")["refus.out_of_band"]
    assert client_text("es", "refus._inconnu", code="x") == "Rechazado por la estación (x)."
    assert client_text("de", "cle.absente") is None


def _session(lang, sent):
    from types import SimpleNamespace

    from trxstation.gateway.api.session import ControlSession
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), config=SimpleNamespace(rig=SimpleNamespace()))
    return ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append, lang=lang)


def test_refusals_and_goodbye_are_sent_in_the_language_of_the_client():
    for lang in LANGS:
        sent = []
        session = _session(lang, sent)
        assert session.lang == lang
        asyncio.run(session.on_message('{"cmd":"spectrum_watch","id":1,"on":true}'))
        result = sent[-1]
        assert result["ok"] is False and result["reason"] == "spectrum_unavailable"        # le CODE ne change jamais
        if lang == "fr":
            assert result.get("detail", "") in ("", load("fr")["refus.spectrum_unavailable"])   # comme avant
        else:
            assert result["detail"] == load(lang)["refus.spectrum_unavailable"]
        session.bye("kicked")
        assert sent[-1] == {"type": "bye", "reason": "kicked", "message": load(lang)["acces.kicked"]}
    sent = []
    assert _session("it", sent).lang == "fr"


def test_access_refusal_of_the_offer_is_sent_in_the_language_of_the_client():
    from aiohttp.test_utils import TestClient, TestServer

    from trxstation.gateway.api.access import AccessRefused
    from trxstation.gateway.api.server import make_app

    class Registry:
        def verify(self, client_id, secret, source):
            return True

    class Manager:
        langs: list[str] = []

        async def handle_offer(self, client_id, sdp, sdp_type, source="", device="", agent="", lang="fr"):
            self.langs.append(lang)
            raise AccessRefused("listeners_full")

    manager = Manager()

    async def scenario():
        async with TestClient(TestServer(make_app(Registry(), manager, web_client=False))) as client:
            out = {}
            for lang in (*LANGS, None, "klingon"):
                body = {"client_id": "visiteur", "password": "x", "sdp": "v=0", "type": "offer"}
                if lang is not None:
                    body["lang"] = lang
                resp = await client.post("/offer", json=body)
                out[lang] = (resp.status, await resp.json())
            return out
    out = asyncio.run(scenario())
    for lang in LANGS:
        status, body = out[lang]
        assert status == 503 or status == 403
        assert body == {"error": "listeners_full", "message": load(lang)["acces.listeners_full"]}
    assert out[None][1]["message"] == out["klingon"][1]["message"] == load("fr")["acces.listeners_full"]
    assert manager.langs == [*LANGS, "fr", "fr"]


def test_access_messages_of_the_station_are_the_french_catalogue():
    from trxstation.gateway.api.access import MESSAGES
    fr = load("fr")
    assert {key: fr["acces." + key] for key in MESSAGES} == MESSAGES
    assert {k[len("acces."):] for k in fr if k.startswith("acces.")} == set(MESSAGES)
