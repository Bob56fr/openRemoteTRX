# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Coupure du VOX du poste à l'ouverture d'une connexion d'opérateur (décision de l'utilisateur, 2026-11-19).

Un VOX en marche peut faire émettre le poste sur un bruit de la pièce, sans aucune commande de la station : à chaque
connexion d'OPÉRATEUR, la station le relit et le coupe s'il est en marche, et le dit à l'opérateur (`rig_notice`).
Elle ne peut jamais le mettre en marche ; un visiteur ne déclenche rien ; rien pendant une émission."""
from __future__ import annotations

import asyncio

from test_api import connect, run, station, until

from trxstation.errors import codes


def notices(client):
    return client.of_type("rig_notice")


def test_vox_found_on_is_switched_off_and_the_operator_is_told():
    async def scenario(fake):
        fake.funcs["VOX"] = 1
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await until(lambda: notices(phone))
            notice = notices(phone)[0]
            assert notice["event"] == "vox_off" and notice["ort"] == codes.ORT_5034
            assert "VOX" in notice["detail"] and "phone" in notice["detail"]
            assert fake.funcs["VOX"] == 0
    run(scenario)


def test_vox_already_off_or_absent_says_nothing():
    async def scenario(fake):
        fake.funcs["VOX"] = 0
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await asyncio.sleep(0.3)
            assert notices(phone) == [] and fake.funcs["VOX"] == 0
        del fake.funcs["VOX"]                            # poste sans VOX : RPRT -11, rien à dire
        async with station(fake) as st:
            phone = await connect(st, "phone2")
            await asyncio.sleep(0.3)
            assert notices(phone) == []
    run(scenario)


def test_unreadable_vox_is_reported_as_unknown():
    async def scenario(fake):
        fake.funcs["VOX"] = 1
        original = fake._reply

        def reply(line):
            if line.strip().lstrip("+").startswith("u VOX"):
                return "RPRT -9\n"
            return original(line)
        fake._reply = reply
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await until(lambda: notices(phone))
            assert notices(phone)[0]["event"] == "vox_unknown" and notices(phone)[0]["ort"] == codes.ORT_5035
            assert fake.funcs["VOX"] == 1                # rien écrit sans lecture sûre
    run(scenario)


def test_vox_that_cannot_be_switched_off_is_reported_and_never_switched_on():
    async def scenario(fake):
        fake.funcs["VOX"] = 1
        original = fake._reply
        writes = []

        def reply(line):
            if line.strip().lstrip("+").startswith("U VOX"):
                writes.append(line.strip().lstrip("+"))
                return "RPRT -9\n"                       # le poste refuse la coupure
            return original(line)
        fake._reply = reply
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await until(lambda: notices(phone), timeout=5)
            assert notices(phone)[0]["event"] == "vox_still_on" and notices(phone)[0]["ort"] == codes.ORT_5036
            assert writes and all(w == "U VOX 0" for w in writes)    # jamais « U VOX 1 »
            assert fake.ptt == 0
    run(scenario)


def test_a_listener_never_triggers_the_vox_check():
    async def scenario(fake):
        fake.funcs["VOX"] = 1
        async with station(fake) as st:
            visitor = await connect(st, "club", role="listener")
            await asyncio.sleep(0.3)
            assert notices(visitor) == [] and fake.funcs["VOX"] == 1
    run(scenario)


def test_no_vox_write_while_transmitting():
    async def scenario(fake):
        fake.funcs["VOX"] = 0
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await phone.say(cmd="toggle", id=1)
            assert phone.result(1)["ok"] and fake.ptt == 1
            fake.funcs["VOX"] = 1
            assert await st.ctrl.vox_guard("tablet") == ("", None, {})
            assert fake.funcs["VOX"] == 1                # jamais d'écriture au poste pendant une émission
            await phone.say(cmd="toggle", id=2)
    run(scenario)


def test_the_shared_example_has_the_fields_the_station_really_sends():
    import json
    from pathlib import Path
    example = json.loads((Path(__file__).parent / "protocol" / "messages.json").read_text(encoding="utf-8"))["rig_notice"]

    async def scenario(fake):
        fake.funcs["VOX"] = 1
        async with station(fake) as st:
            phone = await connect(st, "phone")
            await until(lambda: notices(phone))
            assert set(notices(phone)[0]) == set(example) and example["type"] == "rig_notice"
    run(scenario)
