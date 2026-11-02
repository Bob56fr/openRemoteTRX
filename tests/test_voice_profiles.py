# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Profils d'égaliseur des opérateurs rangés sur la station (étape 102) : par compte, bornés, jamais pour un visiteur."""
from __future__ import annotations

import json

import pytest
from test_api import connect, run, station

from trxstation.gateway.voice_profiles import MAX_PROFILES, VoiceProfileStore, validate_settings

PAGE_DEFAULTS = {   # voice.js defaults() : rangés tels quels
    "version": 1, "enabled": True, "highpassHz": 100, "lowpassHz": 3000,
    "bands": [{"hz": hz, "gainDb": 0, "q": 1.4, "shelf": i in (0, 9)}
              for i, hz in enumerate((100, 160, 250, 370, 570, 880, 1350, 2100, 3250, 5000))],
    "chorus": {"on": False, "type": "classic", "mix": 30, "rateHz": 0.8, "depthMs": 3},
    "reverb": {"on": True, "type": "hall", "mix": 25, "seconds": 1.8},
    "mic": {"gainDb": 0, "gateOn": False, "gateDb": -50},
}


def test_settings_are_bounded_like_the_page():
    assert validate_settings(PAGE_DEFAULTS) == PAGE_DEFAULTS                       # réglages de la page : inchangés
    wild = validate_settings({"enabled": "oui", "highpassHz": 5000, "lowpassHz": 1000, "bands": [{"gainDb": 99, "q": 0}, "x"],
                              "chorus": {"on": True, "type": "flanger", "mix": 500}, "reverb": {"seconds": -3},
                              "mic": {"gainDb": float("nan")}, "inconnu": 1})
    assert wild["enabled"] is False and wild["highpassHz"] == 1000 and wild["lowpassHz"] == 1500   # coupe-haut > coupe-bas + 300
    assert wild["bands"][0]["gainDb"] == 12 and wild["bands"][0]["q"] == 0.3 and wild["bands"][1]["gainDb"] == 0
    assert wild["chorus"] == {"on": True, "type": "classic", "mix": 100, "rateHz": 0.8, "depthMs": 3}
    assert wild["reverb"]["seconds"] == 0.2 and wild["mic"]["gainDb"] == 0 and "inconnu" not in wild
    assert validate_settings(None)["bands"][9]["shelf"] is True


def test_store_keeps_profiles_per_account_and_survives_a_restart(tmp_path):
    path = tmp_path / "voice_profiles.json"
    store = VoiceProfileStore(path)
    store.save("phone", "Mon DX", PAGE_DEFAULTS)
    store.save("phone", "Soirée", {**PAGE_DEFAULTS, "enabled": False})
    assert [p["name"] for p in store.save("phone", "mon dx", {**PAGE_DEFAULTS, "highpassHz": 300})] == ["Soirée", "mon dx"]
    assert store.list("car") == []                                                 # autre compte : rien
    again = VoiceProfileStore(path)
    assert [p["name"] for p in again.list("phone")] == ["Soirée", "mon dx"]
    assert again.list("phone")[1]["settings"]["highpassHz"] == 300
    assert [p["name"] for p in again.delete("phone", "SOIRÉE")] == ["mon dx"]
    with pytest.raises(ValueError):
        again.delete("phone", "absent")
    for i in range(MAX_PROFILES - 1):
        again.save("phone", f"p{i}", PAGE_DEFAULTS)
    with pytest.raises(ValueError):
        again.save("phone", "un de trop", PAGE_DEFAULTS)
    again.save("phone", "p0", PAGE_DEFAULTS)                                       # remplacer reste possible
    with pytest.raises(ValueError):
        again.save("phone", " ", PAGE_DEFAULTS)
    path.write_text("{pas du json", encoding="utf-8")
    assert VoiceProfileStore(path).list("phone") == []                            # illisible : démarre quand même


def test_operator_saves_lists_and_deletes_through_the_protocol(tmp_path):
    async def scenario(fake):
        async with station(fake) as st:
            voices = VoiceProfileStore(tmp_path / "v.json")
            phone = await connect(st, "phone", voices=voices)
            assert "voice_profiles" in phone.of_type("hello")[0]["features"]
            settings = json.loads(json.dumps(PAGE_DEFAULTS))
            message = json.dumps({"cmd": "voice_profile_save", "id": 1, "name": "Mon DX", "settings": settings}, separators=(",", ":"))
            assert len(message.encode()) < 2048                                    # tient dans un message ordinaire
            await phone.session.on_message(message)
            res = next(m for m in phone.of_type("result") if m["id"] == 1)
            assert res["ok"] and res["profiles"][0]["name"] == "Mon DX"
            await phone.say(cmd="voice_profiles", id=2)
            assert next(m for m in phone.of_type("result") if m["id"] == 2)["profiles"][0]["settings"]["reverb"]["type"] == "hall"
            await phone.say(cmd="voice_profile_delete", id=3, name="absent")
            res = next(m for m in phone.of_type("result") if m["id"] == 3)
            assert not res["ok"] and res["reason"] == "voice_profile_refused"
            await phone.say(cmd="voice_profile_delete", id=4, name="Mon DX")
            assert next(m for m in phone.of_type("result") if m["id"] == 4)["profiles"] == []
            car = await connect(st, "car", voices=voices)
            await car.say(cmd="voice_profiles", id=5)
            assert next(m for m in car.of_type("result") if m["id"] == 5)["profiles"] == []
    run(scenario)
