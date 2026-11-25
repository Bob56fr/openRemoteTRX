# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Largeurs des préréglages FIL1 / FIL2 / FIL3 des Icom par le port B (étape 395, fenêtre FIL à trois curseurs) :
codage « 1A 03 » en liste fermée, lecture des trois largeurs du mode en cours, écriture d'une seule, préréglage du départ
TOUJOURS remis, refus pendant l'émission, FM sans réglage, largeurs oubliées quand le mode change."""
from __future__ import annotations

import asyncio

import pytest

from trxstation.gateway.api.protocol import ProtocolError, parse_command
from trxstation.spectrum import civ
from trxstation.spectrum.civ import FrameReader, decode_width, encode_width, width_steps

from test_civ_scope import RIG, rig_frame
from test_filter_presets import FilterPortB, started
from test_spectrum_service import make_service, wait_for


# ------------------------------------------------------------------ codage (manuel CI-V de l'IC-7300MK2, p. 19)

def test_width_tables_follow_the_icom_manual():
    ssb = width_steps(0x01)
    assert ssb[0] == 50 and ssb[9] == 500 and ssb[10] == 600 and ssb[-1] == 3600 and len(ssb) == 41
    assert width_steps(0x04)[-1] == 2700 and len(width_steps(0x04)) == 32                 # RTTY
    assert width_steps(0x02)[0] == 200 and width_steps(0x02)[-1] == 10_000                 # AM
    assert width_steps(0x05) == ()                                                         # FM : fixe
    assert encode_width(0x01, 2400) == b"\x28" and decode_width(0x01, b"\x1a\x03\x28") == 2400   # index 28 en BCD
    assert encode_width(0x02, 10_000) == b"\x49"
    for mode, hz in ((0x01, 2450), (0x01, 4000), (0x05, 2400), (0x04, 3000), (0x01, True)):
        with pytest.raises(ValueError):
            encode_width(mode, hz)
    for bad in (b"\x1a\x03\x41", b"\x1a\x03\x4a", b"\x1a\x05\x10", b"\x1a\x03"):
        assert decode_width(0x01, bad) is None, bad


def test_closed_list_holds_fifty_widths_and_the_reading():
    assert len(civ.ALLOWED[(0x1A, 0x03)]) == 50 + 1
    with pytest.raises(civ.CivRefused):
        civ.encode_request(RIG, 0x1A, 0x03, b"\x50")


# ------------------------------------------------------------------ faux poste : une largeur par préréglage

class WidthPortB(FilterPortB):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.widths = {1: 3000, 2: 2400, 3: 1800}          # USB : défauts de l'IC-7300
        self.width_writes: list[tuple[int, int]] = []
        self.refuse_width = False

    def write(self, data: bytes):
        frame = next(FrameReader().feed(data))
        p = frame.payload
        if p[:2] == b"\x1a\x03":
            self.written.append(bytes(data))
            filt = self.mode[2]
            if len(p) == 2:
                index = width_steps(self.mode[0]).index(self.widths[filt])
                reply = b"\x1a\x03" + bytes([(index // 10) << 4 | index % 10])
            elif self.refuse_width:
                reply = b"\xFA"
            else:
                hz = decode_width(self.mode[0], p)
                self.widths[filt] = hz
                self.width_writes.append((filt, hz))
                reply = b"\xFB"
            self.out += rig_frame(reply, to=frame.frm, frm=self.address)
            return
        super().write(data)


def test_three_widths_are_read_and_the_selected_preset_is_put_back():
    rig = WidthPortB()

    async def scenario():
        svc, _, _ = await started(rig)
        result = await svc.set_setting("filter_widths", None)
        snap = svc.snapshot()["settings"]
        await svc.stop()
        return result, snap
    result, snap = asyncio.run(scenario())
    assert result == (True, "") and snap["filter_widths"] == [3000, 2400, 1800] and snap["filter"] == 2
    assert snap["filter_steps"][0] == 50 and snap["filter_steps"][-1] == 3600
    assert rig.mode == [0x01, 0x01, 2] and rig.width_writes == []                   # FIL2 remis, rien écrit
    assert all(w[4] in (0x19, 0x03, 0x27, 0x26, 0x1A) for w in rig.written)         # jamais 1C


def test_one_width_is_written_then_all_reread_and_the_preset_put_back():
    rig = WidthPortB()

    async def scenario():
        svc, _, _ = await started(rig)
        out = [await svc.set_setting("filter_width", {"filter": 3, "hz": 1500}),
               await svc.set_setting("filter_width", {"filter": 2, "hz": 2450})]    # pas un palier
        snap = svc.snapshot()["settings"]
        await svc.stop()
        return out, snap
    out, snap = asyncio.run(scenario())
    assert out == [(True, ""), (False, "bad_setting")]
    assert rig.width_writes == [(3, 1500)] and snap["filter_widths"] == [3000, 2400, 1500]
    assert rig.mode == [0x01, 0x01, 2]                                              # FIL2 toujours sélectionné


def test_refusals_during_transmission_in_fm_and_by_the_rig_always_put_the_preset_back():
    rig = WidthPortB()

    async def scenario():
        svc, link, ctrl = await started(rig)
        out = []
        ctrl.state = "TX"
        out.append(await svc.set_setting("filter_width", {"filter": 1, "hz": 2800}))
        ctrl.state = "RX"
        rig.refuse_width = True
        out.append(await svc.set_setting("filter_width", {"filter": 1, "hz": 2800}))
        out.append(list(rig.mode))
        rig.refuse_width = False
        rig.mode[0] = 0x05                                                          # FM
        out.append(await svc.set_setting("filter_widths", None))
        out.append(svc.snapshot()["settings"].get("filter_widths"))
        out.append(await svc.set_setting("filter_width", {"filter": 1, "hz": 2800}))
        await svc.stop()
        return out
    out = asyncio.run(scenario())
    assert out[0] == (False, "tx_active")
    assert out[1] == (False, "spectrum_refused") and out[2] == [0x01, 0x01, 2]
    assert out[3] == (True, "") and out[4] is None and out[5] == (False, "bad_setting")
    assert rig.width_writes == []


def test_widths_are_forgotten_when_the_mode_changes_on_the_rig():
    rig = WidthPortB()

    async def scenario():
        svc, *_ = make_service(rig)
        svc.FILTER_EVERY_S = 0.05
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["settings"].get("filter") == 2)
        await svc.set_setting("filter_widths", None)
        kept = svc.snapshot()["settings"]["filter_widths"]
        rig.mode[0] = 0x00                                                          # LSB choisi sur le poste
        gone = await wait_for(lambda: svc.snapshot()["settings"].get("filter_widths") is None, 3)
        await svc.stop()
        return kept, gone
    kept, gone = asyncio.run(scenario())
    assert kept == [3000, 2400, 1800] and gone


def test_protocol_filter_width_values():
    cmd = parse_command('{"cmd":"spectrum_set","id":1,"name":"filter_width","value":{"filter":2,"hz":2400}}')
    assert cmd.params == {"name": "filter_width", "value": {"filter": 2, "hz": 2400}}
    assert parse_command('{"cmd":"spectrum_set","id":1,"name":"filter_widths","value":null}').params["value"] is None
    for bad in ('{"filter":4,"hz":2400}', '{"filter":2,"hz":20}', '{"filter":2}', '2400', '{"filter":2,"hz":2400,"x":1}'):
        with pytest.raises(ProtocolError):
            parse_command('{"cmd":"spectrum_set","id":1,"name":"filter_width","value":%s}' % bad)
