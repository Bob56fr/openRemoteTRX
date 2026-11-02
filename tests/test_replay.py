# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Rediffusion d'un enregistrement de l'audio reçu : accordée UNE FOIS par l'assistant à la demande expresse de
l'opérateur (refusée par défaut), annoncée aux opérateurs seulement, durée bornée au TOT - 5 s."""
from __future__ import annotations

from test_api import connect, run, station

from trxstation import setup_wizard
from trxstation.config import Access, ClientAuth
from trxstation.gateway.api.access import AccessControl
from trxstation.setup_wizard import dummy_config


def test_wizard_grants_replay_only_on_an_explicit_yes(monkeypatch, capsys):
    cfg = dummy_config()
    assert cfg.safety.allow_replay is False                                              # refusée par défaut
    monkeypatch.setattr("builtins.input", lambda _: "")
    setup_wizard.ask_replay(cfg)
    assert cfg.safety.allow_replay is False and "INTERDIT" in capsys.readouterr().out    # Entrée = non, avertissement
    monkeypatch.setattr("builtins.input", lambda _: "oui")
    setup_wizard.ask_replay(cfg)
    assert cfg.safety.allow_replay is True


def test_hello_announces_replay_to_operators_only_bounded_by_the_tot():
    async def scenario(fake):
        async with station(fake) as st:
            phone = await connect(st, "phone")
            assert phone.of_type("hello")[0]["replay"] is None and "replay" not in phone.of_type("hello")[0]["features"]
            st.ctrl.config.safety.allow_replay = True
            access = AccessControl([ClientAuth("car", password_hash="x"), ClientAuth("club1", password_hash="y", role="listener")],
                                   Access(max_listeners=1))
            access.switch.open = True
            access.admit("car")
            car = await connect(st, "car", access=access)
            hello = car.of_type("hello")[0]
            assert hello["replay"] == {"max_s": int(st.ctrl.limits.tot_s) - 5} and "replay" in hello["features"]
            access.admit("club1")
            visitor = await connect(st, "club1", role="listener", access=access)
            assert visitor.of_type("hello")[0]["replay"] is None and "replay" not in visitor.of_type("hello")[0]["features"]
    run(scenario)
