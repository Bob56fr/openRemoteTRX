# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TOT du poste (docs/tot-poste-cahier-des-charges.md, lot TP1) : LU à la connexion d'un opérateur, jamais écrit ;
sur OFF lu « à coup sûr », avis `rig_notice` « rig_tot_off » une fois par jour et par compte ; toute incertitude =
« unknown » et aucun avis ; jamais pour un visiteur ; l'émission n'est jamais bloquée."""
from __future__ import annotations

import asyncio

import pytest
from test_api import connect, run, station, until

from trxstation.errors import codes
from trxstation.gateway.cat.client import RigctldClient
from trxstation.rigtot import RIG_TOT, RigTotStore, TotReading, civ_command, parse_civ_reply, read_tot

IC7300MK2 = RIG_TOT[3094]
TOT_FRAME = bytes.fromhex("FEFEB6E01A050032FD")


def test_command_is_the_frame_read_on_the_ic7300mk2_with_the_echo_counted():
    # relevé du lot TP0 (2026-11-20) : 9 octets d'écho puis 10 octets de réponse
    assert civ_command(IC7300MK2) == "W \\0xFE\\0xFE\\0xB6\\0xE0\\0x1A\\0x05\\0x00\\0x32\\0xFD 19"


def test_ic705_reads_its_own_menu_at_its_own_address():
    # étape 402 : guide CI-V de l'IC-705 (menu 0043, adresse A4h), pas encore mesuré sur le poste
    ic705 = RIG_TOT[3085]
    assert civ_command(ic705) == "W \\0xFE\\0xFE\\0xA4\\0xE0\\0x1A\\0x05\\0x00\\0x43\\0xFD 19"
    reply = ("\\0xFE\\0xFE\\0xA4\\0xE0\\0x1A\\0x05\\0x00\\0x43\\0xFD"
             "\\0xFE\\0xFE\\0xE0\\0xA4\\0x1A\\0x05\\0x00\\0x43\\0x02\\0xFD 19")
    assert parse_civ_reply(ic705, reply) == 2 and ic705.minutes[2] == 5
    mk2_menu = "\\0xFE\\0xFE\\0xE0\\0xA4\\0x1A\\0x05\\0x00\\0x32\\0x02\\0xFD"   # menu du MK2 : pas celui de l'IC-705
    assert parse_civ_reply(ic705, mk2_menu) is None


def test_reply_parsing_keeps_only_the_answer_of_the_rig():
    real = ("\\0xFE\\0xFE\\0xB6\\0xE0\\0x1A\\0x05\\0x00\\0x32\\0xFD"
            "\\0xFE\\0xFE\\0xE0\\0xB6\\0x1A\\0x05\\0x00\\0x32\\0x01\\0xFD 19")
    assert parse_civ_reply(IC7300MK2, real) == 1
    echo_only = "\\0xFE\\0xFE\\0xB6\\0xE0\\0x1A\\0x05\\0x00\\0x32\\0xFD"
    assert parse_civ_reply(IC7300MK2, echo_only) is None                  # l'écho n'est JAMAIS une réponse
    assert parse_civ_reply(IC7300MK2, "") is None
    other = "\\0xFE\\0xFE\\0xE0\\0xB6\\0x1A\\0x05\\0x00\\0x33\\0x00\\0xFD"   # autre menu
    assert parse_civ_reply(IC7300MK2, other) is None
    unknown_value = "\\0xFE\\0xFE\\0xE0\\0xB6\\0x1A\\0x05\\0x00\\0x32\\0x09\\0xFD"
    assert parse_civ_reply(IC7300MK2, unknown_value) is None
    ng = "\\0xFE\\0xFE\\0xE0\\0xB6\\0xFA\\0xFD"                              # refus du poste (NG)
    assert parse_civ_reply(IC7300MK2, ng) is None


class FakeClient:
    def __init__(self, replies, freq_ok=True):
        self.replies, self.freq_ok, self.raw = list(replies), freq_ok, []

    async def get_frequency(self):
        if not self.freq_ok:
            raise ConnectionError("muet")
        return 7_074_000

    async def send_raw(self, command):
        self.raw.append(command)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _answer(code: int) -> str:
    return "".join(f"\\0x{b:02X}" for b in TOT_FRAME + bytes([0xFE, 0xFE, 0xE0, 0xB6, 0x1A, 0x05, 0x00, 0x32, code, 0xFD]))


@pytest.mark.parametrize("replies,freq_ok,ptt,model,expected", [
    ([_answer(0), _answer(0)], True, "RIG", 3094, ("off", None, "")),
    ([_answer(1), _answer(1)], True, "RIG", 3094, ("on", 3, "")),
    ([_answer(5), _answer(5)], True, "RIG", 3094, ("on", 30, "")),
    ([_answer(0), _answer(1)], True, "RIG", 3094, ("unknown", None, "unstable")),
    ([_answer(0), TimeoutError()], True, "RIG", 3094, ("unknown", None, "unreadable")),
    (["", ""], True, "RIG", 3094, ("unknown", None, "unreadable")),
    ([_answer(0), _answer(0)], False, "RIG", 3094, ("unknown", None, "silent")),      # poste muet : jamais « off »
    ([_answer(0), _answer(0)], True, "RTS", 3094, ("unknown", None, "ptt")),        # TOT Icom : PTT CI-V seulement
    ([_answer(0), _answer(0)], True, "RIG", 1042, ("unknown", None, "model")),      # FTDX10 pas encore qualifié
])
def test_reading_is_sure_or_unknown(replies, freq_ok, ptt, model, expected):
    reading = asyncio.run(read_tot(FakeClient(replies, freq_ok), model, ptt))
    assert (reading.state, reading.minutes, reading.reason) == expected


def test_raw_commands_are_a_closed_list():
    client = RigctldClient()
    for bad in ("W \\0xFE\\0xFE\\0xB6\\0xE0\\0x1A\\0x05\\0x00\\0x32\\0x01\\0xFD 19",   # écriture du TOT
                "W EX030116; 11", "T 1", "w \\0x1C\\0x00\\0x01"):
        with pytest.raises(ValueError):
            asyncio.run(client.send_raw(bad))


def test_store_says_once_a_day_per_account(tmp_path):
    day = ["2026-11-20"]
    store = RigTotStore(tmp_path / "rig_tot.json", today=lambda: day[0])
    assert store.due("phone") and store.due("pc")
    store.shown("phone")
    assert not store.due("phone") and store.due("pc")
    again = RigTotStore(tmp_path / "rig_tot.json", today=lambda: day[0])     # station redémarrée : toujours retenu
    assert not again.due("phone")
    day[0] = "2026-11-21"
    assert again.due("phone")
    store.record(TotReading("on", minutes=3))
    assert store.snapshot()["state"] == "on" and store.snapshot()["minutes"] == 3


def _session(tmp_path, *, code=0, model=3094, ptt="RIG", listener=False, accounts=("phone",), keyed=False):
    seen = {}

    async def scenario(fake):
        fake.funcs["VOX"] = 0
        if code is not None:
            fake.civ_menus[TOT_FRAME] = code
        async with station(fake) as st:
            st.ctrl.config.rig.model, st.ctrl.config.rig.ptt_type = model, ptt
            store = RigTotStore(tmp_path / "rig_tot.json")
            if keyed:
                fake.ptt = 1                             # émission au micro du poste
                await until(lambda: st.link.state.ptt is True)
            notes = []
            for account in accounts:
                kwargs = {"role": "listener"} if listener else {}
                client = await connect(st, account, **kwargs)
                client.session.rig_tot = None if listener else store
                await client.session._rig_tot_check(__import__("trxstation.errors.emit", fromlist=["render"]).render)
                notes.append([m for m in client.messages if m.get("type") == "rig_notice" and m["event"] == "rig_tot_off"])
            seen["notes"], seen["store"], seen["raw"] = notes, store, fake.count("W")
            fake.ptt = 0
    run(scenario)
    return seen


def test_tot_off_warns_the_operator_once_a_day(tmp_path):
    seen = _session(tmp_path, accounts=("phone", "phone", "pc"))
    first, second, other = seen["notes"]
    assert len(first) == 1 and first[0]["ort"] == codes.ORT_5041 and "phone" in first[0]["detail"]
    assert second == []                                   # même compte, même jour : rien
    assert len(other) == 1                                # autre compte : son avis
    assert seen["store"].snapshot()["state"] == "off"


def test_tot_set_unknown_model_or_silent_rig_says_nothing(tmp_path):
    assert _session(tmp_path / "a", code=1)["notes"] == [[]]
    assert _session(tmp_path / "a", code=1)["store"].snapshot()["minutes"] == 3
    unknown = _session(tmp_path / "b", model=1042)
    assert unknown["notes"] == [[]] and unknown["raw"] == 0 and unknown["store"].snapshot()["reason"] == "model"
    silent = _session(tmp_path / "c", code=None)          # aucune réponse du poste à la trame
    assert silent["notes"] == [[]] and silent["store"].snapshot()["state"] == "unknown"


def test_never_for_a_visitor_nor_during_a_transmission(tmp_path):
    visitor = _session(tmp_path / "v", listener=True)
    assert visitor["notes"] == [[]] and visitor["raw"] == 0
    keyed = _session(tmp_path / "k", keyed=True)
    assert keyed["notes"] == [[]] and keyed["raw"] == 0
