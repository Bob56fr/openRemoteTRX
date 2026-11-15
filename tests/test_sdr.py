# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Module SDR, lot S1a (docs/sdr-cahier-des-charges.md) : trames de sdr-core, [sdr], liste des SDR, service du
module contre le faux sdr-core (devtools/fake_sdr_core.py), et sdr-core compilé quand gcc et liquid-dsp sont là."""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.errors import codes
from trxstation.modules.manifest import load_manifest
from trxstation.sdr import devices, frames
from trxstation.sdr.service import Settings, SdrService, SetRefused, clean_settings, core_args, line_message

ROOT = Path(__file__).resolve().parents[1]
FAKE = [sys.executable, "-m", "trxstation.devtools.fake_sdr_core"]


# ------------------------------------------------------------------ trames
def test_frames_roundtrip_in_arbitrary_chunks() -> None:
    raw = (frames.encode_json({"t": "started", "serial": "X1"}) + frames.encode_line(7.1e6, 2e6, bytes(range(128)))
           + frames.encode_json({"t": "status", "drops": 0}))
    reader, out = frames.FrameReader(), []
    for i in range(0, len(raw), 7):                       # octets livrés par petits morceaux
        out += reader.feed(raw[i:i + 7])
    assert [type(f).__name__ for f in out] == ["dict", "Line", "dict"]
    line = out[1]
    assert (line.center_hz, line.span_hz, line.bins, line.values[5]) == (7.1e6, 2e6, 128, 5)
    assert frames.level_db(0) == -150.0 and frames.level_db(255) == -22.5


@pytest.mark.parametrize("raw", [b"XXXX" + bytes(8), frames.HEADER.pack(b"ORS1", 9, 0),
                                 frames.HEADER.pack(b"ORS1", 1, 1 << 20), frames.encode_frame(2, b"[1]"),
                                 frames.encode_frame(1, frames.LINE_HEAD.pack(1.0, 1.0, 10, 0) + bytes(3))])
def test_frames_refuse_a_garbled_stream(raw: bytes) -> None:
    with pytest.raises(frames.FrameError):
        frames.FrameReader().feed(raw)


def test_line_message_is_base64_for_the_page() -> None:
    msg = line_message(frames.Line(14.1e6, 2e6, bytes([0, 128, 255])), 12.5)
    assert msg == {"kind": "sdr_line", "scope": "sdr_view", "c": 14100000, "s": 2000000,
                   "d": base64.b64encode(bytes([0, 128, 255])).decode(), "t": 12500}


# ------------------------------------------------------------------ configuration
def _problems(**sdr) -> list[str]:
    cfg = cfgmod.Config()
    for k, v in sdr.items():
        setattr(cfg.sdr, k, v)
    return [p for p in cfgmod.validate(cfg) if p.startswith("[sdr]")]


def test_sdr_defaults_are_valid_and_disabled() -> None:
    assert _problems() == [] and cfgmod.Config().sdr.enabled is False


def test_sdr_enabled_requires_a_serial_and_the_module() -> None:
    probs = _problems(enabled=True)
    assert any("serial" in p for p in probs) and any("[modules] run" in p for p in probs)
    cfg = cfgmod.Config()
    cfg.sdr.enabled, cfg.sdr.serial, cfg.modules.run = True, "170502E910", ["sdr"]
    assert [p for p in cfgmod.validate(cfg) if p.startswith("[sdr]")] == []


@pytest.mark.parametrize("field,value", [("serial", "17-05"), ("sample_rate_hz", 4_000_000), ("lna_state", 9),
                                         ("gain_reduction_db", 60), ("fft_size", 3000), ("bins", 8192),
                                         ("lines_per_s", 20), ("antenna", "C"), ("driver", "rtl"),
                                         ("core_path", "a\nb")])
def test_sdr_values_out_of_range_are_refused(field: str, value) -> None:
    assert _problems(**{field: value})


def test_sdr_section_survives_the_station_toml_writer(tmp_path: Path) -> None:
    cfg = cfgmod.Config()
    cfg.sdr.serial, cfg.sdr.center_hz = "170502E910", 14_100_000
    text = cfgmod.render_toml(cfg)
    import tomllib
    back, _ = cfgmod.build(tomllib.loads(text))           # config incomplète (sans poste) : on relit sans refuser
    assert (back.sdr.serial, back.sdr.center_hz) == ("170502E910", 14_100_000)


def test_manifest_gives_no_right_on_the_radio() -> None:
    m = load_manifest(ROOT / "trxstation" / "modules" / "builtin" / "sdr" / "manifest.toml")
    assert m.name == "sdr" and m.rights.commands == frozenset() and m.rights.events == frozenset()
    assert m.rights.client_commands and m.rights.client_messages and m.resources.nice >= 10


# ------------------------------------------------------------------ réglages et arguments
def test_settings_from_an_operator_are_checked() -> None:
    base = Settings(7_100_000, 2, 50, 8)
    assert clean_settings({"center_hz": 14_100_000, "gr": 40}, base) == Settings(14_100_000, 2, 40, 8)
    for bad in ({"center_hz": 0}, {"lna": 9}, {"gr": 19.5}, {"rate": 16}, {"ptt": 1}, {"lna": True}):
        with pytest.raises(SetRefused):
            clean_settings(bad, base)


def test_core_arguments_always_name_the_serial() -> None:
    sd = cfgmod.Sdr(serial="170502E910", sample_rate_hz=8_000_000)
    args = core_args(sd, Settings(7_100_000, 2, 50, 8))
    assert args[:2] == ["--serial", "170502E910"] and args[args.index("--bw") + 1] == "8000"


# ------------------------------------------------------------------ liste des SDR (lecture seule)
def test_busy_sdr_seen_on_usb_but_not_by_the_api(tmp_path: Path) -> None:
    for name, serial in (("3-3", "170502EC10"), ("3-5", "170502E910"), ("3-2", "")):
        d = tmp_path / name
        d.mkdir()
        (d / "idVendor").write_text("1df7\n" if name != "3-2" else "0c26\n")
        (d / "serial").write_text(serial + "\n")
    usb = devices.usb_devices(tmp_path)
    merged = devices.merge([{"serial": "170502E910", "hw": 2}], usb)
    assert [(d.serial, d.state, d.usb_port) for d in merged] == [("170502E910", "libre", "3-5"),
                                                                 ("170502EC10", "pris", "3-3")]


def test_api_listing_through_the_core() -> None:
    found, error = devices.api_devices(sys.executable, run=lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout='{"api":3.15,"devices":[{"serial":"170502E910","hw":2}]}\n', stderr=""))
    assert error == "" and found == [{"serial": "170502E910", "hw": 2}]
    found, error = devices.api_devices(sys.executable, run=lambda *a, **k: subprocess.CompletedProcess(
        a, 4, stdout='{"api":null,"devices":[],"error":"service"}\n', stderr=""))
    assert found == [] and "fabricant" in error


# ------------------------------------------------------------------ service du module contre le faux cœur
class FakeBus:
    def __init__(self) -> None:
        self.connected = asyncio.Event()
        self.connected.set()
        self.sent: list[dict] = []
        self.on_call = self.on_connect = None

    async def client_message(self, **message) -> None:
        self.sent.append(message)

    async def run_forever(self) -> None:
        await asyncio.sleep(3600)


def _service(tmp_path: Path, extra: list[str] | None = None) -> tuple[SdrService, FakeBus, list]:
    bus, emitted = FakeBus(), []
    sd = cfgmod.Sdr(enabled=True, serial="TEST1234", lines_per_s=10)
    svc = SdrService(sd, tmp_path, bus, core_prefix=FAKE + (extra or []),
                     emit=lambda code, **kw: emitted.append((code, kw)))
    return svc, bus, emitted


def test_service_publishes_lines_and_state_then_applies_a_setting(tmp_path: Path) -> None:
    async def scenario():
        svc, bus, emitted = _service(tmp_path)
        task = asyncio.ensure_future(svc.run())
        for _ in range(100):
            if any(m["kind"] == "sdr_line" for m in bus.sent) and svc.state["state"] == "running":
                break
            await asyncio.sleep(0.05)
        result = await svc.on_call({"action": "set", "args": {"center_hz": 14_100_000, "lna": 4}})
        for _ in range(100):
            lines = [m for m in bus.sent if m["kind"] == "sdr_line"]
            if lines and lines[-1]["c"] == 14_100_000:
                break
            await asyncio.sleep(0.05)
        svc.stop()
        await asyncio.wait_for(task, 10)
        return svc, bus, emitted, result
    svc, bus, emitted, result = asyncio.run(scenario())
    lines = [m for m in bus.sent if m["kind"] == "sdr_line"]
    states = [m for m in bus.sent if m["kind"] == "sdr_state"]
    assert lines and all(m["scope"] == "sdr_view" for m in lines) and lines[-1]["c"] == 14_100_000
    assert len(base64.b64decode(lines[0]["d"])) == 1024
    assert states and all(m["scope"] == "operators" and m["retain"] == "snapshot" for m in states)
    assert result["center"] == 14_100_000 and result["lna"] == 4
    assert json.loads((tmp_path / "sdr" / "last.json").read_text())["center_hz"] == 14_100_000
    assert emitted == []                                   # aucune panne
    again = SdrService(cfgmod.Sdr(serial="TEST1234"), tmp_path, None, core_prefix=FAKE)
    assert again.settings.center_hz == 14_100_000          # réglage repris au redémarrage


def test_absent_serial_is_reported_and_never_replaced(tmp_path: Path) -> None:
    async def scenario():
        svc, bus, emitted = _service(tmp_path, ["--fail", "absent"])
        rc, error = await svc.run_core_once()
        delay = await svc._after_exit(rc, error, 0.1)
        return svc, emitted, rc, delay
    svc, emitted, rc, delay = asyncio.run(scenario())
    assert rc == 3 and delay == 30.0 and svc.state["state"] == "error" and svc.state["code"] == "absent"
    assert [c for c, _ in emitted] == [codes.ORT_6001] and emitted[0][1]["serial"] == "TEST1234"


def test_vendor_service_down_is_reported_without_touching_it(tmp_path: Path) -> None:
    async def scenario():
        svc, bus, emitted = _service(tmp_path, ["--fail", "service"])
        rc, error = await svc.run_core_once()
        return emitted, await svc._after_exit(rc, error, 0.1)
    emitted, delay = asyncio.run(scenario())
    assert [c for c, _ in emitted] == [codes.ORT_6002] and delay == 30.0


def test_core_crash_is_restarted_with_a_growing_delay(tmp_path: Path) -> None:
    async def scenario():
        svc, bus, emitted = _service(tmp_path, ["--fail", "crash", "--crash-after", "0.3"])
        delays = []
        for _ in range(3):
            rc, error = await svc.run_core_once()
            delays.append(await svc._after_exit(rc, error, 0.5))
        return emitted, delays
    emitted, delays = asyncio.run(scenario())
    assert delays == [2.0, 4.0, 8.0]
    assert [c for c, _ in emitted] == [codes.ORT_6004] * 3 and emitted[-1][1]["relances"] == 3


def test_missing_core_is_reported(tmp_path: Path) -> None:
    async def scenario():
        bus, emitted = FakeBus(), []
        svc = SdrService(cfgmod.Sdr(serial="TEST1234"), tmp_path, bus, core=str(tmp_path / "absent"),
                         emit=lambda code, **kw: emitted.append(code))
        task = asyncio.ensure_future(svc.run())
        await asyncio.sleep(0.3)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return svc, emitted
    svc, emitted = asyncio.run(scenario())
    assert emitted == [codes.ORT_6003] and svc.state["code"] == "core_missing"


def test_unknown_action_is_refused(tmp_path: Path) -> None:
    from trxstation.modules.client import CallRefused
    svc, _, _ = _service(tmp_path)
    with pytest.raises(CallRefused):
        asyncio.run(svc.on_call({"action": "ptt"}))
    with pytest.raises(CallRefused):
        asyncio.run(svc.on_call({"action": "set", "args": {"gr": 99}}))


# ------------------------------------------------------------------ le vrai sdr-core, compilé sans l'API (fichier IQ)
@pytest.mark.skipif(shutil.which("gcc") is None or sys.platform == "win32", reason="gcc et liquid-dsp absents")
def test_real_core_reads_an_iq_file(tmp_path: Path) -> None:
    exe = tmp_path / "sdr-core"
    build = subprocess.run(["gcc", "-O2", "-DSDR_NO_SDRPLAY", "-o", str(exe),
                            str(ROOT / "trxstation" / "sdr" / "core" / "sdr_core.c"), "-lliquid", "-lm", "-lpthread"],
                           capture_output=True, text=True)
    if build.returncode != 0:
        pytest.skip("liquid-dsp absent : " + build.stderr[-200:])
    import math
    import struct
    fs, n = 200_000, 200_000
    iq = b"".join(struct.pack("<hh", int(8000 * math.cos(2 * math.pi * 25_000 * i / fs)),
                              int(8000 * math.sin(2 * math.pi * 25_000 * i / fs))) for i in range(n))
    (tmp_path / "t.iq").write_bytes(iq)
    proc = subprocess.run([str(exe), "--iq-file", str(tmp_path / "t.iq"), "--fs", str(fs), "--fft", "1024",
                           "--bins", "256", "--rate", "10"], input=b"", capture_output=True, timeout=10)
    out = frames.FrameReader().feed(proc.stdout)
    assert out and out[0]["t"] == "started"
    lines = [f for f in out if isinstance(f, frames.Line)]
    if lines:                                              # entrée fermée tout de suite : parfois aucune ligne
        peak = max(range(256), key=lambda i: lines[-1].values[i])
        assert abs(peak - (128 + 32)) <= 2                  # +25 kHz sur 200 kHz : case 160


# ------------------------------------------------------------------ passerelle : diffusion et commande « sdr »
def test_lines_reach_only_operators_who_show_the_sdr_section_and_state_is_replayed() -> None:
    from types import SimpleNamespace
    from trxstation.modules.gateway_bridge import ModuleBridge
    bridge = ModuleBridge(cfgmod.Config(), SimpleNamespace(), SimpleNamespace())
    watching, other, visitor = [], [], []
    sessions = [SimpleNamespace(listener=False, sdr_view=True, send=watching.append),
                SimpleNamespace(listener=False, sdr_view=False, send=other.append),
                SimpleNamespace(listener=True, sdr_view=True, send=visitor.append)]
    bridge.clients = lambda: sessions
    bridge.to_clients("sdr", {"kind": "sdr_state", "retain": "snapshot", "scope": "operators", "state": "running"})
    bridge.to_clients("sdr", {"kind": "sdr_line", "scope": "sdr_view", "d": "AA=="})
    assert [m["data"]["kind"] for m in watching] == ["sdr_state", "sdr_line"]
    assert [m["data"]["kind"] for m in other] == ["sdr_state"] and visitor == []
    late, late_visitor = [], []
    bridge.on_sdr_view(SimpleNamespace(listener=False, send=late.append), True)
    bridge.on_sdr_view(SimpleNamespace(listener=True, send=late_visitor.append), True)
    assert [m["data"]["kind"] for m in late] == ["sdr_state"] and late_visitor == []


def test_sdr_command_in_a_gateway_session() -> None:
    from types import SimpleNamespace
    from trxstation.gateway.api.session import ControlSession
    from trxstation.modules.bus import CommandRefused

    def session(sent, role="operator", call=None):
        ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), heartbeat=lambda cid: None,
                               config=SimpleNamespace(rig=SimpleNamespace(), safety=SimpleNamespace(allow_replay=False)))
        s = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append, role=role)
        s.sdr_call, s.on_sdr_view = call, (lambda sess, on: replayed.append(on))
        return s

    calls, replayed, sent = [], [], []

    async def call(data):
        calls.append(data)
        if data["args"].get("gr") == 99:
            raise CommandRefused("sdr_invalid", "gr : entier de 20 à 59")
        return {"state": "running"}

    s = session(sent, call=call)
    assert "sdr" in s.features()
    asyncio.run(s.on_message(json.dumps({"cmd": "sdr", "id": 1, "action": "watch", "args": {"on": True}})))
    assert sent[-1] == {"type": "result", "id": 1, "ok": True, "action": "watch", "on": True}
    assert s.sdr_view is True and replayed == [True] and calls == []          # traité par la passerelle
    asyncio.run(s.on_message(json.dumps({"cmd": "sdr", "id": 2, "action": "set", "args": {"gr": 99}})))
    assert sent[-1]["ok"] is False and sent[-1]["reason"] == "sdr_invalid"
    asyncio.run(s.on_message(json.dumps({"cmd": "sdr", "id": 3, "action": "state"})))
    assert sent[-1]["data"] == {"state": "running"} and calls[-1]["client"] == "phone"
    bare = session(sent)
    assert "sdr" not in bare.features()
    asyncio.run(bare.on_message(json.dumps({"cmd": "sdr", "id": 4, "action": "state"})))
    assert sent[-1]["reason"] == "sdr_unavailable"
    visitor_sent = []
    visitor = session(visitor_sent, role="listener", call=call)
    before = len(calls)
    assert "sdr" not in visitor.features()
    asyncio.run(visitor.on_message(json.dumps({"cmd": "sdr", "id": 5, "action": "state"})))
    assert len(calls) == before and visitor_sent[-1].get("ok") is not True and visitor.sdr_view is False


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
def test_page_sdr_js_under_node() -> None:
    done = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "js" / "sdr_test.js")], capture_output=True,
                          text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_an_overload_burst_does_not_flood_the_bus(tmp_path: Path) -> None:
    async def scenario():
        svc, bus, _ = _service(tmp_path, ["--overloads", "200"])
        task = asyncio.ensure_future(svc.run())
        await asyncio.sleep(2.5)
        svc.stop()
        await asyncio.wait_for(task, 10)
        return svc, bus
    svc, bus = asyncio.run(scenario())
    states = [m for m in bus.sent if m["kind"] == "sdr_state"]
    assert svc.state["overloads"] == 200 and len(states) <= 6          # au plus ~1 par seconde, pas 400


def test_if_agc_setting_reaches_the_core_and_real_gain_is_reported(tmp_path: Path) -> None:
    base = Settings(7_100_000, 2, 50, 8)
    assert base.agc is True and clean_settings({"agc": False}, base).agc is False
    with pytest.raises(SetRefused):
        clean_settings({"agc": 1}, base)
    assert core_args(cfgmod.Sdr(serial="170502E910"), base)[-2:] == ["--agc", "1"]

    async def scenario():
        svc, bus, _ = _service(tmp_path)
        task = asyncio.ensure_future(svc.run())
        for _ in range(100):
            if svc.state.get("gr_now") is not None:
                break
            await asyncio.sleep(0.05)
        auto = dict(svc.snapshot())
        res = await svc.on_call({"action": "set", "args": {"agc": False, "gr": 40}})
        for _ in range(100):
            if svc.state.get("gr_now") == 40:
                break
            await asyncio.sleep(0.05)
        manual = dict(svc.snapshot())
        svc.stop()
        await asyncio.wait_for(task, 10)
        return auto, res, manual
    auto, res, manual = asyncio.run(scenario())
    assert auto["agc"] is True and auto["gr_now"] == 38 and auto["gain_db"] == 61.5
    assert res["agc"] is False and manual["gr_now"] == 40          # le faux cœur applique la réduction choisie
