"""Réglages du spectre DU POSTE depuis la page (mode, largeur, référence, vitesse) : codage relevé sur l'IC-7300MK2,
liste fermée, service (réception seulement, relecture), protocole, session, cohérence avec la page."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation.gateway.api.protocol import ProtocolError, parse_command
from trxstation.spectrum import civ
from trxstation.spectrum.civ import FrameReader, decode_setting, encode_setting

from test_civ_scope import RIG, rig_frame
from test_spectrum_service import PortB, make_service, wait_for

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "trxstation" / "gateway" / "api" / "static"


# ------------------------------------------------------------------ codage (relevés réels)

@pytest.mark.parametrize("sub, payload, value", [
    (0x14, "27 14 00 00", "center"), (0x14, "27 14 00 02", "scroll_center"),
    (0x15, "27 15 00 00 00 10 00 00", 100_000), (0x15, "27 15 00 00 00 50 00 00", 500_000),
    (0x19, "27 19 00 20 00 00", 20.0), (0x19, "27 19 00 14 50 01", -14.5),
    (0x1A, "27 1A 00 00", "fast"), (0x1A, "27 1A 00 02", "slow"),
])
def test_decoding_matches_the_two_surveys_of_the_real_rig(sub, payload, value):
    assert decode_setting(sub, bytes.fromhex(payload.replace(" ", ""))) == value


def test_encoding_round_trips_and_unknown_values_are_refused():
    for sub, value in [(0x14, "fixed"), (0x15, 2_500), (0x19, -14.5), (0x19, 0.0), (0x19, 20.0), (0x1A, "mid")]:
        assert decode_setting(sub, bytes([0x27, sub]) + encode_setting(sub, value)) == value
    for sub, value in [(0x14, "scroll_center"), (0x15, 7_000), (0x19, 20.5), (0x19, 0.3), (0x19, True), (0x1A, "turbo"), (0x10, 1)]:
        with pytest.raises(ValueError):
            encode_setting(sub, value)
    assert decode_setting(0x19, bytes.fromhex("27190014AA01")) is None                # BCD invalide
    assert decode_setting(0x15, bytes.fromhex("2715")) is None


def test_closed_list_holds_only_the_permitted_values():
    assert len(civ.ALLOWED[(0x27, 0x19)]) == 81 + 2                                   # -20..+20 dB par 0,5 + lectures
    assert len(civ.ALLOWED[(0x27, 0x15)]) == 8 + 2
    with pytest.raises(civ.CivRefused):
        civ.encode_request(RIG, 0x27, 0x15, b"\x00" + bytes(5))                       # largeur nulle : hors liste
    with pytest.raises(civ.CivRefused):
        civ.encode_request(RIG, 0x1C, 0x00, b"\x01")                                  # émission : jamais


# ------------------------------------------------------------------ faux port B avec réglages

class ScopePortB(PortB):
    """Second port d'IC-7300MK2 avec les réglages du spectre (octet de choix 00 obligatoire, FA sans lui)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.scope_settings = {0x14: "center", 0x15: 100_000, 0x19: -14.5, 0x1A: "fast"}
        self.writes: list[tuple[int, object]] = []

    def write(self, data: bytes):
        frame = next(FrameReader().feed(data))
        p = frame.payload
        if p[:1] == b"\x27" and len(p) >= 2 and p[1] in self.scope_settings:
            self.written.append(bytes(data))
            sub = p[1]
            if len(p) < 3 or p[2] != 0:
                reply = b"\xFA"
            elif len(p) == 3:
                reply = bytes([0x27, sub]) + encode_setting(sub, self.scope_settings[sub])
            else:
                value = decode_setting(sub, p)
                if value is None or (sub == 0x15 and self.scope_settings[0x14] != "center"):
                    reply = b"\xFA"                                                    # en mode fixe, le poste refuse la largeur
                else:
                    self.scope_settings[sub] = value
                    self.writes.append((sub, value))
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


def test_settings_are_read_at_opening_written_then_read_back():
    rig = ScopePortB()

    async def scenario():
        svc, _, _ = await started(rig)
        first = svc.snapshot()["settings"]
        results = [await svc.set_setting("span", 10_000), await svc.set_setting("ref", -3.0),
                   await svc.set_setting("speed", "slow")]
        after = svc.snapshot()["settings"]
        await svc.stop()
        return first, results, after
    first, results, after = asyncio.run(scenario())
    assert first == {"mode": "center", "span": 100_000, "ref": -14.5, "speed": "fast"}
    assert results == [(True, ""), (True, ""), (True, "")]
    assert after == {"mode": "center", "span": 10_000, "ref": -3.0, "speed": "slow"}
    assert rig.writes == [(0x15, 10_000), (0x19, -3.0), (0x1A, "slow")]
    assert all(w[4] in (0x19, 0x03, 0x27) for w in rig.written)                       # jamais 1C


def test_rig_refusal_is_reported_and_state_reread():
    rig = ScopePortB()

    async def scenario():
        svc, _, _ = await started(rig)
        assert await svc.set_setting("mode", "fixed") == (True, "")
        refused = await svc.set_setting("span", 25_000)                                # le poste refuse en mode fixe
        settings = svc.snapshot()["settings"]
        await svc.stop()
        return refused, settings
    refused, settings = asyncio.run(scenario())
    assert refused == (False, "spectrum_refused") and settings["span"] == 100_000 and settings["mode"] == "fixed"


def test_settings_are_refused_during_transmission_bad_values_and_when_unavailable():
    rig = ScopePortB()

    async def scenario():
        svc, link, ctrl = await started(rig)
        out = [await svc.set_setting("span", 12_345), await svc.set_setting("volume", 3)]
        ctrl.state = "TX"
        out.append(await svc.set_setting("span", 10_000))
        ctrl.state, link.state.ptt = "RX", True                                        # PTT relu actif : le fil refuse aussi
        out.append(await svc.set_setting("span", 10_000))
        link.state.ptt = False
        await svc.stop()
        return out
    out = asyncio.run(scenario())
    assert out == [(False, "bad_setting"), (False, "bad_setting"), (False, "tx_active"), (False, "tx_active")]
    assert rig.writes == []

    async def unavailable():
        svc, *_ = make_service(ScopePortB(answers=False))
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["state"] == "error")
        result = await svc.set_setting("span", 10_000)
        await svc.stop()
        return result
    assert asyncio.run(unavailable()) == (False, "spectrum_unavailable")


def test_a_setting_changed_on_the_rig_reaches_the_page():
    rig = ScopePortB()

    async def scenario():
        svc, *_ = make_service(rig)
        svc.IDENT_EVERY_S = 0.1                                                        # relecture rapprochée pour l'essai
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["settings"].get("ref") == -14.5)
        rig.scope_settings[0x19] = 5.0                                                 # niveau changé sur le poste
        ok = await wait_for(lambda: svc.snapshot()["settings"].get("ref") == 5.0, 3)
        await svc.stop()
        return ok
    assert asyncio.run(scenario())


# ------------------------------------------------------------------ protocole et session

def test_protocol_spectrum_set():
    cmd = parse_command(json.dumps({"cmd": "spectrum_set", "id": 4, "name": "ref", "value": -3}))
    assert cmd.params == {"name": "ref", "value": -3.0}
    assert parse_command('{"cmd":"spectrum_set","name":"span","value":10000}').params["value"] == 10_000
    for bad in ({"name": "ptt", "value": 1}, {"name": "span", "value": "10k"}, {"name": "ref", "value": True},
                {"name": "ref", "value": 1e9}, {"name": "mode", "value": 3}, {"name": "speed", "value": "x" * 40}):
        with pytest.raises(ProtocolError):
            parse_command(json.dumps({"cmd": "spectrum_set", **bad}))


def test_protocol_spectrum_watch():
    assert parse_command('{"cmd":"spectrum_watch","id":1,"on":true}').params == {"on": True}
    assert parse_command('{"cmd":"spectrum_watch","on":false}').params == {"on": False}
    for bad in ({}, {"on": 1}, {"on": "true"}, {"on": None}):
        with pytest.raises(ProtocolError):
            parse_command(json.dumps({"cmd": "spectrum_watch", **bad}))


def test_session_spectrum_watch_reaches_the_fanout_of_this_client_only():
    from trxstation.gateway.api.session import ControlSession
    sent, calls = [], []
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), config=SimpleNamespace(rig=SimpleNamespace()))
    spectrum = SimpleNamespace(snapshot=lambda: {"state": "ok"})
    session = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append,
                             spectrum=spectrum, spectrum_watch=calls.append)
    asyncio.run(session.on_message('{"cmd":"spectrum_watch","id":1,"on":true}'))
    asyncio.run(session.on_message('{"cmd":"spectrum_watch","id":2,"on":false}'))
    assert calls == [True, False]
    assert sent == [{"type": "result", "id": 1, "ok": True, "on": True}, {"type": "result", "id": 2, "ok": True, "on": False}]
    bare = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append)
    asyncio.run(bare.on_message('{"cmd":"spectrum_watch","id":3,"on":true}'))
    assert sent[-1]["ok"] is False and sent[-1]["reason"] == "spectrum_unavailable"


def test_session_spectrum_set_returns_the_reread_settings():
    from trxstation.gateway.api.session import ControlSession
    sent = []

    class Spectrum:
        def __init__(self):
            self.calls = []

        async def set_setting(self, name, value):
            self.calls.append((name, value))
            return (True, "") if value == 10_000 else (False, "spectrum_refused")

        def snapshot(self):
            return {"state": "ok", "code": "", "message": "", "settings": {"span": 10_000}}

    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), config=SimpleNamespace(rig=SimpleNamespace()))
    session = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append, spectrum=Spectrum())
    asyncio.run(session.on_message('{"cmd":"spectrum_set","id":1,"name":"span","value":10000}'))
    asyncio.run(session.on_message('{"cmd":"spectrum_set","id":2,"name":"span","value":25000}'))
    assert sent[0] == {"type": "result", "id": 1, "ok": True, "settings": {"span": 10_000}}
    assert sent[1]["ok"] is False and sent[1]["reason"] == "spectrum_refused"
    bare = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append)
    asyncio.run(bare.on_message('{"cmd":"spectrum_set","id":3,"name":"span","value":10000}'))
    assert sent[-1]["reason"] == "spectrum_unavailable"


def test_page_and_station_share_the_same_lists_and_every_refusal_is_translated():
    from trxstation.spectrum.service import SETTING_REASONS
    hf = (STATIC / "hfscope.js").read_text(encoding="utf-8")
    spans = [int(v) for v in re.search(r"const SPANS_HZ = \[([^\]]+)\]", hf).group(1).split(",")]
    assert tuple(spans) == civ.SPANS_HZ
    logic = (STATIC / "client.js").read_text(encoding="utf-8")
    block = re.search(r"const REASONS = \{(.*?)\n  \};", logic, re.S).group(1)
    reasons = set(re.findall(r"^\s+([a-z_]+):", block, re.M))
    assert set(SETTING_REASONS) <= reasons, set(SETTING_REASONS) - reasons
