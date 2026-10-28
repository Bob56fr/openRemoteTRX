# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Préréglages de filtre FIL1 / FIL2 / FIL3 par le port B (commande CI-V 26 00) : liste fermée, seul le filtre change
(mode et mode données réécrits tels que relus), refus pendant l'émission, relecture, poste qui ne connaît pas 26."""
from __future__ import annotations

import asyncio

import pytest

from trxstation.gateway.api.protocol import ProtocolError, parse_command
from trxstation.spectrum import civ
from trxstation.spectrum.civ import FrameReader, decode_mode_filter, encode_mode_filter

from test_civ_scope import RIG, rig_frame
from test_safety import run, station
from test_spectrum_service import make_service, wait_for
from test_spectrum_settings import ScopePortB


# ------------------------------------------------------------------ codage

def test_decoding_and_closed_list():
    assert decode_mode_filter(bytes.fromhex("2600010102")) == (1, 1, 2)            # USB-D, FIL2
    for bad in ("26000101", "2600010104", "2600060101", "2600010401", "2601010101", "2700010101"):
        assert decode_mode_filter(bytes.fromhex(bad)) is None, bad
    assert encode_mode_filter(3, 0, 3) == bytes([3, 0, 3])
    for args in ((1, 0, 0), (1, 0, 4), (6, 0, 1), (1, 4, 1), (1, 0, True)):
        with pytest.raises(ValueError):
            encode_mode_filter(*args)
    assert len(civ.ALLOWED[(0x26, 0x00)]) == 8 * 4 * 3 + 1
    with pytest.raises(civ.CivRefused):
        civ.encode_request(RIG, 0x26, 0x00, bytes([1, 0, 4]))
    with pytest.raises(civ.CivRefused):
        civ.encode_request(RIG, 0x26, 0x01, bytes([1, 0, 1]))                        # autre VFO : hors liste


# ------------------------------------------------------------------ faux poste

class FilterPortB(ScopePortB):
    """Second port avec la commande 26 00 (mode, mode données, filtre) ; `knows_26 = False` : poste qui l'ignore."""

    def __init__(self, *, knows_26=True, refuse_26=False, **kw):
        super().__init__(**kw)
        self.mode, self.knows_26, self.refuse_26 = [0x01, 0x01, 2], knows_26, refuse_26     # USB-D, FIL2
        self.filter_writes: list[bytes] = []

    def write(self, data: bytes):
        frame = next(FrameReader().feed(data))
        p = frame.payload
        if p[:1] == b"\x26":
            self.written.append(bytes(data))
            if not self.knows_26:
                reply = b"\xFA"
            elif len(p) == 2:
                reply = b"\x26\x00" + bytes(self.mode)
            elif self.refuse_26:
                reply = b"\xFA"
            else:
                self.filter_writes.append(p[2:])
                self.mode = list(p[2:5])
                reply = b"\xFB"
            self.out += rig_frame(reply, to=frame.frm, frm=self.address)
            return
        super().write(data)


async def started(rig):
    svc, link, ctrl, _ = make_service(rig)
    await svc.start()
    assert await wait_for(lambda: svc.snapshot()["state"] == "ok")
    assert await wait_for(lambda: svc.snapshot()["settings"].get("ref") is not None)
    return svc, link, ctrl


# ------------------------------------------------------------------ service

def test_preset_is_read_then_changed_keeping_mode_and_data_mode():
    rig = FilterPortB()

    async def scenario():
        svc, _, _ = await started(rig)
        first = svc.snapshot()["settings"]["filter"]
        results = [await svc.set_setting("filter", 3), await svc.set_setting("filter", 1)]
        after = svc.snapshot()["settings"]["filter"]
        await svc.stop()
        return first, results, after
    first, results, after = asyncio.run(scenario())
    assert first == 2 and results == [(True, ""), (True, "")] and after == 1
    assert rig.filter_writes == [bytes([1, 1, 3]), bytes([1, 1, 1])]                # USB-D gardé, seul le filtre change
    assert all(w[4] in (0x19, 0x03, 0x27, 0x26) for w in rig.written)               # jamais 1C


def test_preset_refused_during_transmission_bad_values_and_rig_refusal():
    rig = FilterPortB()

    async def scenario():
        svc, link, ctrl = await started(rig)
        out = [await svc.set_setting("filter", 4), await svc.set_setting("filter", True)]
        ctrl.state = "TX"                                                           # verrou du contrôleur : refus
        out.append(await svc.set_setting("filter", 3))
        ctrl.state, link.state.ptt = "RX", True                                     # PTT relu actif : le fil refuse aussi
        out.append(await svc.set_setting("filter", 3))
        link.state.ptt = False
        rig.refuse_26 = True
        out.append(await svc.set_setting("filter", 3))
        out.append(svc.snapshot()["settings"]["filter"])
        await svc.stop()
        return out
    out = asyncio.run(scenario())
    assert out == [(False, "bad_setting"), (False, "bad_setting"), (False, "tx_active"), (False, "tx_active"),
                   (False, "spectrum_refused"), 2]
    assert rig.filter_writes == []


def test_preset_changed_on_the_rig_reaches_the_page():
    rig = FilterPortB()

    async def scenario():
        svc, *_ = make_service(rig)
        svc.FILTER_EVERY_S = 0.05
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["settings"].get("filter") == 2)
        rig.mode[2] = 3                                                             # bouton FIL appuyé sur le poste
        ok = await wait_for(lambda: svc.snapshot()["settings"].get("filter") == 3, 3)
        await svc.stop()
        return ok
    assert asyncio.run(scenario())


def test_rig_without_command_26_keeps_the_old_button():
    rig = FilterPortB(knows_26=False)

    async def scenario():
        svc, _, _ = await started(rig)
        snap = svc.snapshot()["settings"]
        result = await svc.set_setting("filter", 1)
        await svc.stop()
        return snap, result
    snap, result = asyncio.run(scenario())
    assert snap["filter"] is None and snap["ref"] == -14.5 and result == (False, "spectrum_unavailable")
    assert rig.filter_writes == []


# ------------------------------------------------------------------ contrôleur, protocole

def test_controller_lock_refuses_outside_confirmed_reception():
    from trxstation.gateway.safety import Refused
    from test_safety import beating

    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            async with ctrl.rig_setting():
                pass                                                                # RX : permis
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            try:
                await ctrl.toggle("phone")
                with pytest.raises(Refused) as exc:
                    async with ctrl.rig_setting():
                        raise AssertionError("jamais exécuté pendant l'émission")
                assert exc.value.reason == "tx_active"
                await ctrl.toggle("phone")
            finally:
                beat.cancel()
    run(scenario)


def test_protocol_filter_values():
    cmd = parse_command('{"cmd":"spectrum_set","id":1,"name":"filter","value":3}')
    assert cmd.params == {"name": "filter", "value": 3}
    for bad in ("0", "4", "true", "2.5", '"2"'):
        with pytest.raises(ProtocolError):
            parse_command('{"cmd":"spectrum_set","id":1,"name":"filter","value":%s}' % bad)


def test_station_without_port_b_has_no_preset():
    svc, *_ = make_service(FilterPortB(), enabled=False)
    assert svc.snapshot()["settings"] == {}
    assert asyncio.run(svc.set_setting("filter", 1)) == (False, "spectrum_unavailable")
