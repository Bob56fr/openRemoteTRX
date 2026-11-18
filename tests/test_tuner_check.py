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
        self.stamp = 0
        self.refreshed = 0

    def rig_menus(self):
        return dict(self.menus)

    def menus_stamp(self):
        return self.stamp

    def refresh_menus(self):                       # relecture immédiate (fil du port B simulé)
        self.refreshed += 1
        self.stamp += 1

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



def test_icom_nb_level_range_is_corrected_from_0_10_to_0_1():
    """Hamlib déclare « NB 0..10 » pour les Icom mais écrit 0 à 1 (×255) : au-delà de 1, le poste refuse (IC-7300MK2,
    RPRT -9, 2026-11-19). Plage corrigée pour la station ET la qualification ; un Yaesu garde la sienne."""
    from trxstation.gateway.cat.capabilities import parse_dump_caps
    from trxstation.qualif.profile import parse_profile
    text = "Set level: NB(0.000000..10.000000/1.000000) NR(0.000000..1.000000/0.066667)\n"
    assert parse_dump_caps(text, 3094).level_ranges["NB"] == [0.0, 1.0, 0.1]
    assert parse_dump_caps(text, 1042).level_ranges["NB"] == [0.0, 10.0, 1.0]
    assert parse_dump_caps(text, 3094).level_ranges["NR"] == [0.0, 1.0, 0.066667]
    nb = parse_profile(text, 3094).level_ranges["NB"]
    assert (nb.low, nb.high) == (0.0, 1.0)



def test_data_mod_not_on_usb_warns_every_operator_even_without_the_tuner():
    """DATA MOD (2026-11-19) : la voix de la station ne module en mode données que s'il est sur USB."""
    from trxstation.spectrum.menus import data_mod_check

    def notices(menus, **kw):
        seen = {}

        async def scenario(fake):
            fake.funcs["VOX"] = 0
            async with station(fake) as st:
                st.ctrl.config.rig.tuner = kw.get("tuner", False)
                st.ctrl.config.rig.model = kw.get("model", 3094)
                phone = await connect(st, "phone", spectrum=Spectrum(menus) if menus is not None else None)
                await asyncio.sleep(0.4)
                seen["n"] = [m for m in phone.messages if m.get("type") == "rig_notice"]
        run(scenario)
        return seen["n"]
    wrong = notices({"data_mod": 4})
    assert [n["event"] for n in wrong] == ["data_mod"] and wrong[0]["ort"] == codes.ORT_5040
    assert "MIC,ACC" in wrong[0]["detail"] and "USB" in wrong[0]["detail"]
    assert notices({"data_mod": 1}) == []
    assert notices(None) == []                                          # illisible : rien (pas d'avis sans port B)
    assert notices({"data_mod": 4}, model=1042) == []                   # modèle sans ce réglage
    both_ = notices({"data_mod": 0, "tuner_switch": 1, "ptt_start": 0}, tuner=True)
    assert sorted(n["event"] for n in both_) == ["data_mod", "tuner_settings"]
    assert data_mod_check(3094, {"data_mod": 9}) == ("data_mod", {"valeur": "valeur 9", "attendu": "USB"})
