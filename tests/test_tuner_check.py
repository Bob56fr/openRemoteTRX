# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Réglages du coupleur vérifiés à la connexion d'un opérateur (décision de l'utilisateur, 2026-11-19) : lus par le
second port CI-V, JAMAIS écrits ; l'opérateur est prévenu s'ils sont faux ou impossibles à vérifier."""
from __future__ import annotations

import asyncio

from test_api import connect, run, station, until

from trxstation.errors import codes
from trxstation.spectrum.menus import RIG_MENUS, decode_menu, tuner_check


def test_tuner_check_verdicts():
    assert tuner_check(3094, {"tuner_switch": 1, "ptt_start": 1}) == ("", {})
    event, ctx = tuner_check(3094, {"tuner_switch": 0, "ptt_start": 0})
    assert event == "tuner_settings" and "PTT Start à mettre sur ON" in ctx["reglages"] and "Auto" in ctx["reglages"]
    assert tuner_check(3094, {})[0] == "tuner_unverified"
    assert tuner_check(3094, {"tuner_switch": 1, "ptt_start": None})[0] == "tuner_unverified"
    assert tuner_check(1042, {"tuner_switch": 1})[0] == "tuner_unverified"           # modèle sans table
    assert decode_menu(b"\x00\x38", b"\x1a\x05\x00\x38\x01") == 1
    assert decode_menu(b"\x00\x38", b"\x1a\x05\x00\x37\x01") is None and decode_menu(b"\x00\x38", b"\xfa") is None
    assert all(len(sub) == 2 for menus in RIG_MENUS.values() for sub, *_ in menus.values())


class Spectrum:
    active = True

    def __init__(self, menus):
        self.menus = menus

    def rig_menus(self):
        return dict(self.menus)

    def capability(self):
        return None

    def snapshot(self):
        return {"state": "ok", "code": "", "message": "", "settings": {}}


def _notices(client):
    return [m for m in client.messages if m.get("type") == "rig_notice" and m["event"].startswith("tuner")]


def _scenario(menus, *, tuner=True, listener=False, model=3094):
    seen = {}

    async def scenario(fake):
        fake.funcs["VOX"] = 0
        async with station(fake) as st:
            st.ctrl.config.rig.tuner = tuner
            st.ctrl.config.rig.model = model
            kwargs = {"spectrum": Spectrum(menus) if menus is not None else None}
            if listener:
                kwargs["role"] = "listener"
            phone = await connect(st, "phone", **kwargs)
            await asyncio.sleep(0.4)
            seen["notices"] = _notices(phone)
    run(scenario)
    return seen["notices"]


def test_wrong_tuner_settings_warn_the_operator():
    notices = _scenario({"tuner_switch": 1, "ptt_start": 0})
    assert len(notices) == 1 and notices[0]["event"] == "tuner_settings" and notices[0]["ort"] == codes.ORT_5037
    assert "PTT Start" in notices[0]["detail"] and "phone" in notices[0]["detail"]


def test_good_tuner_settings_say_nothing():
    assert _scenario({"tuner_switch": 1, "ptt_start": 1}) == []


def test_no_second_port_or_unknown_model_means_unverified():
    notices = _scenario(None)
    assert len(notices) == 1 and notices[0]["event"] == "tuner_unverified" and notices[0]["ort"] == codes.ORT_5038
    assert _scenario({"tuner_switch": 1, "ptt_start": 1}, model=1042)[0]["event"] == "tuner_unverified"


def test_no_check_when_the_tuner_is_not_used_or_for_a_visitor():
    assert _scenario({"tuner_switch": 0, "ptt_start": 0}, tuner=False) == []
    assert _scenario({"tuner_switch": 0, "ptt_start": 0}, listener=True) == []
