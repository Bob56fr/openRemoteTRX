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

    assert set(I18N_FILES) == {f"{domain}.{lang}.json" for domain in ("client", "shared", "page") for lang in LANGS}

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
    assert re.search(r'const DOMAINS = \["client", "shared", "page"\]', script)


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


def test_set_lang_changes_the_language_of_the_texts_without_reconnecting():
    """Station 0.243.0+ : `set_lang` change la langue de CE client en cours de connexion (application : Réglages >
    Langue), visiteurs compris ; liste fermée ; n'agit sur rien d'autre."""
    sent = []
    session = _session("fr", sent)
    asyncio.run(session.on_message('{"cmd":"set_lang","id":7,"lang":"de"}'))
    assert sent[-1]["ok"] is True and sent[-1]["lang"] == "de" and session.lang == "de"
    asyncio.run(session.on_message('{"cmd":"spectrum_watch","id":8,"on":true}'))
    assert sent[-1]["detail"] == load("de")["refus.spectrum_unavailable"]
    asyncio.run(session.on_message('{"cmd":"set_lang","id":9,"lang":"it"}'))
    assert sent[-1]["type"] == "error" and sent[-1]["code"] == "invalid_params" and session.lang == "de"
    asyncio.run(session.on_message('{"cmd":"set_lang","id":10,"lang":"fr"}'))
    assert session.lang == "fr"
    from trxstation.gateway.api.access import LISTENER_COMMANDS
    from trxstation.gateway.api.protocol import BASE_FEATURES
    assert "set_lang" in LISTENER_COMMANDS and "set_lang" in BASE_FEATURES


def test_access_refusal_of_the_offer_is_sent_in_the_language_of_the_client():
    from aiohttp.test_utils import TestClient, TestServer

    from trxstation.gateway.api.access import AccessRefused
    from trxstation.gateway.api.server import make_app

    class Registry:
        def verify(self, client_id, secret, source):
            return True

        def canonical(self, client_id):
            return client_id

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


# ---------------------------------------------------------------- lot T5 : textes encore français jusqu'ici
# Chaque texte est un Text (i18n/text.py) : sa valeur est le français d'avant (journal, fichiers d'état, clients
# français : rien ne change), la passerelle le refabrique pour chaque client au moment de l'envoi.

def _both(message: dict) -> tuple[dict, dict]:
    """Ce que reçoivent un client français et un client anglais pour le même message."""
    out = {}
    for lang in ("fr", "en"):
        sent = []
        _session(lang, sent).send(message)
        out[lang] = json.loads(json.dumps(sent[-1], ensure_ascii=False))      # comme sur le canal de données
    return out["fr"], out["en"]


def test_text_keeps_the_french_value_and_is_rebuilt_in_each_language():
    import copy
    import pickle

    from trxstation.i18n.text import Text
    what = Text("station.power_port_rig")
    text = Text("station.power_port_missing", what=what, port="COM6")
    assert text == "port du poste COM6 absent : poste débranché ou câble USB ?"            # français d'avant, exact
    assert isinstance(text, str) and json.dumps({"d": text}, ensure_ascii=False) == \
        '{"d": "port du poste COM6 absent : poste débranché ou câble USB ?"}'
    assert text.render("en") == "port of the radio COM6 missing: radio unplugged or USB cable?"
    assert text.render("fr") == text and type(text.render("fr")) is str
    for clone in (copy.deepcopy(text), pickle.loads(pickle.dumps(text))):
        assert clone == text and clone.render("de") == text.render("de")
    for lang in LANGS:                                   # toutes les clés station.* se fabriquent dans chaque langue
        cat = load(lang)
        for key in (k for k in cat if k.startswith("station.")):
            fields = {name: "X" for name in FIELD.findall(load("fr")[key])}
            assert Text(key, **fields).render(lang) == cat[key].format(**fields)


def test_power_steps_and_refusals_are_sent_in_the_language_of_the_client():
    from types import SimpleNamespace

    from trxstation import config as cfgmod
    from trxstation.gateway.power import PowerControl, PowerError, _rig_text
    cfg = cfgmod.Config()
    cfg.rig.port, cfg.rig.port_usb = "COM6", "10C4:EA70 SN=01D0F21E IF=00"
    power = PowerControl(cfg, SimpleNamespace(), SimpleNamespace(), port_present=lambda p: False,
                         identity=lambda p: None, list_ports=lambda: [])
    try:
        power._check_ports()
        raise AssertionError("port absent attendu")
    except PowerError as exc:
        detail = exc.detail
    assert detail == "port du poste COM6 absent : poste débranché ou câble USB ?"
    rig = _rig_text({"frequency_hz": 7074000, "mode": "USB"})
    assert rig.endswith(" kHz USB, en réception") and rig.render("en").endswith(" kHz USB, receiving")
    assert _rig_text({}) == "fréquence non relue, en réception"
    fr, en = _both({"type": "power_progress", "step": "ports", "status": "error", "detail": detail, "ort": "ORT-2809"})
    assert fr["detail"] == detail and fr["step"] == en["step"] == "ports" and en["ort"] == "ORT-2809"
    assert en["detail"] == "port of the radio COM6 missing: radio unplugged or USB cable?"
    sent = []
    session = _session("en", sent)
    session._result(7, False, reason="port_missing", ort="ORT-2809", step="ports", detail=detail)
    assert sent[-1]["detail"] == en["detail"] and sent[-1]["reason"] == "port_missing"
    session._result(8, True, result="on", rig=rig)
    assert sent[-1]["rig"].endswith("receiving")


def test_breizh_events_are_sent_in_the_language_of_the_client(tmp_path):
    from trxstation.breizh.link import BreizhLink
    from trxstation.breizh.store import BreizhStore
    store = BreizhStore(tmp_path)
    link = BreizhLink("127.0.0.1", 9, b"k" * 32, reactivate_after_s=60, station_version="0", notify=store.event)
    link._refuse("busy")
    entry = store.last(1)[0]
    assert entry["event"] == "refused"
    assert entry["detail"] == "liaison refusée : Breizh sert déjà une autre station (nouvel essai dans 60 s)"
    fr, en = _both({"type": "breizh_event", **entry})
    assert fr["detail"] == entry["detail"] and en["event"] == "refused"
    assert en["detail"] == "link refused: Breizh is already serving another station (new attempt in 60 s)"
    assert json.loads((tmp_path / "breizh-log.jsonl").read_text(encoding="utf-8"))["detail"] == entry["detail"]
    fr, en = _both({"type": "result", "id": 1, "ok": True, "entries": store.last(50)})     # breizh_log
    assert en["entries"][0]["detail"].startswith("link refused") and fr["entries"][0]["detail"] == entry["detail"]


def test_freedv_events_are_sent_in_the_language_of_the_client():
    from trxstation.freedv.quality import quality_note
    from trxstation.i18n.text import Text
    note, detail = quality_note([(True, 3.4)] * 100, 1, 58.0)
    assert detail == "SNR médian +3.4 dB, synchro 100 %, 1 perte(s) de synchro"
    fr, en = _both({"type": "freedv_event", "kind": "sequence", "start": 1.0, "duration_s": 58.0, "note": note,
                    "detail": detail, "callsigns": []})
    assert fr["detail"] == detail and en["detail"] == "median SNR +3.4 dB, sync 100 %, 1 sync loss(es)"
    cause = Text("station.freedv_exited", program="radae_rx", code="1")
    fr, en = _both({"type": "freedv_event", "kind": "fault", "cause": cause})
    assert fr["cause"] == "radae_rx s'est arrêté (code 1)" and en["cause"] == "radae_rx stopped (code 1)"


def test_module_texts_are_built_by_the_gateway_for_each_client():
    """Règle du § 3.3 : un module envoie le CODE de son texte et ses variables (`_texts`), la passerelle fabrique le
    texte pour chaque client ; `_texts` ne part jamais vers un client ; un module ne fait pas dire un refus."""
    import threading

    from trxstation.freedv import activity as act
    from trxstation.freedv import reporter as rep
    from trxstation.freedv.activity_service import build_message
    st, lock = act.ReporterState(), threading.Lock()
    client = rep.ReporterClient(st, lock)
    client._set(rep.ERROR, rep.Text("station.freedv_reporter_error", error="HTTPError", seconds="15"))
    data = json.loads(json.dumps(build_message(client, st, lock, "", 0.0)))                # passé par le bus
    assert data["message"] == "FreeDV Reporter injoignable (HTTPError) ; nouvel essai dans 15 s"
    fr, en = _both({"type": "module", "module": "freedv_activity", "data": data})
    assert "_texts" not in fr["data"] and "_texts" not in en["data"] and fr["data"]["status"] == "erreur"
    assert fr["data"]["message"] == data["message"]
    assert en["data"]["message"] == "FreeDV Reporter unreachable (HTTPError); new attempt in 15 s"
    forged = {"type": "module", "module": "x", "data": {"message": "texte du module",
                                                         "_texts": {"message": {"key": "refus.tx_active"}}}}
    fr, en = _both(forged)
    assert fr["data"] == en["data"] == {"message": "texte du module"}


def test_overload_message_is_sent_in_the_language_of_the_client():
    from trxstation.gateway.api.overload import HOLD_S, Limits, OverloadGuard, Sample
    t = [0.0]
    guard = OverloadGuard(lambda: Sample(temp_c=87.0), Limits(), clock=lambda: t[0])
    for _ in range(int(HOLD_S) + 2):
        guard.step(1)
        t[0] += 1
    message = guard.message()
    assert message == ("Station surchargée (processeur à 87 °C) : écoute des visiteurs suspendue pour protéger la "
                       "station. Réouverture automatique après 5 minutes de fonctionnement normal.")
    status = guard.status()
    assert type(status["reason"]) is str and status["reason"] == "processeur à 87 °C"     # inchangé pour tous
    fr, en = _both({"type": "state", "presence": {"suspended": status}})
    assert fr["presence"]["suspended"]["message"] == message
    assert en["presence"]["suspended"]["message"].startswith("Station overloaded (processor at 87 °C)")
    for lang, expected in (("fr", message), ("en", message.render("en"))):
        sent = []
        _session(lang, sent).bye("station_overload", message=message)
        assert sent[-1] == {"type": "bye", "reason": "station_overload", "message": expected}

    from aiohttp.test_utils import TestClient, TestServer

    from trxstation.gateway.api.access import AccessRefused
    from trxstation.gateway.api.server import make_app

    class Registry:
        def verify(self, client_id, secret, source):
            return True

        def canonical(self, client_id):
            return client_id

    class Manager:
        async def handle_offer(self, client_id, sdp, sdp_type, source="", device="", agent="", lang="fr"):
            raise AccessRefused("station_overload", message)

    async def scenario():
        async with TestClient(TestServer(make_app(Registry(), Manager(), web_client=False))) as client:
            out = {}
            for lang in ("fr", "en"):
                body = {"client_id": "visiteur", "password": "x", "sdp": "v=0", "type": "offer", "lang": lang}
                out[lang] = (await (await client.post("/offer", json=body)).json())["message"]
            return out
    out = asyncio.run(scenario())
    assert out == {"fr": message, "en": message.render("en")}
