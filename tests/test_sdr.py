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
from trxstation.sdr.service import (Settings, SdrService, SetRefused, clean_settings, core_args, line_message,
                                    zoom_window, fs_choices, base_fs, antenna)

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


def test_line_carries_the_listened_channel_level_only_while_listening() -> None:
    """S-SDR de la page (étape 332) : niveau du canal dans le champ libre de l'en-tête ; 0 = pas d'écoute."""
    reader = frames.FrameReader()
    [line] = reader.feed(frames.encode_line(7.05e6, 250e3, bytes([1, 2, 3]), -63.27))
    assert line.chan_db is not None and abs(line.chan_db - -63.3) < 0.051
    assert line_message(line, 1.0)["l"] == -63.3
    [silent] = reader.feed(frames.encode_line(7.05e6, 250e3, bytes([1, 2, 3])))
    assert silent.chan_db is None and "l" not in line_message(silent, 1.0)
    # sdr-core d'avant la station 0.250.0 : champ « réservé » à 0 = pas de niveau
    [old] = reader.feed(frames.encode_frame(1, frames.LINE_HEAD.pack(1.0, 1.0, 3, 0) + bytes(3)))
    assert old.chan_db is None


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
    assert args[args.index("--serial") + 1] == "170502E910" and args[args.index("--bw") + 1] == "8000"
    assert args[args.index("--dfreq") + 1] == "7100000" and args[args.index("--mode") + 1] == "USB"


def test_zoom_window_stays_inside_the_sdr_width_and_follows_the_listened_frequency() -> None:
    assert zoom_window(2_000_000, 1, 300_000) == 0                       # sans zoom : toute la largeur
    assert zoom_window(2_000_000, 4, 900_000) == 750_000                 # bornée : fenêtre de 500 kHz dans 2 MHz
    assert zoom_window(2_000_000, 4, -900_000) == -750_000
    assert zoom_window(2_000_000, 4, 100_000, listen_off=200_000) == 100_000   # écoute dans la fenêtre : rien ne bouge
    assert zoom_window(2_000_000, 4, 0, listen_off=400_000) == 400_000   # écoute sortie de la fenêtre : recentrée
    base = Settings(7_100_000, 2, 50, 8)
    assert clean_settings({"zoom": 8, "zoom_off": -50_000}, base).zoom == 8
    for bad in ({"zoom": 3}, {"zoom": True}, {"zoom_off": 0.5}, {"zoom_off": 9_000_000}):
        with pytest.raises(SetRefused):
            clean_settings(bad, base)


def test_zoom_reaches_the_core_only_when_used() -> None:
    sd = cfgmod.Sdr(serial="170502E910", sample_rate_hz=2_000_000)
    assert "--zoom" not in core_args(sd, Settings(7_100_000, 2, 50, 8))    # sdr-core ancien : jamais d'argument inconnu
    args = core_args(sd, Settings(7_100_000, 2, 50, 8, zoom=4, zoom_off=2_000_000))
    assert args[args.index("--zoom") + 1] == "4" and args[args.index("--zoom-off") + 1] == "750000"


def test_zoomed_waterfall_centres_on_the_listened_frequency_and_follows_it(tmp_path: Path) -> None:
    async def wait_line(bus, c, s):
        for _ in range(100):
            lines = [m for m in bus.sent if m["kind"] == "sdr_line"]
            if lines and lines[-1]["c"] == c and lines[-1]["s"] == s:
                return True
            await asyncio.sleep(0.05)
        return False

    async def scenario():
        svc, bus, _ = _service(tmp_path)
        task = asyncio.ensure_future(svc.run())
        ok = [await wait_line(bus, 7_100_000, 2_000_000)]
        await svc.on_call({"action": "set", "args": {"dfreq_hz": 7_300_000}})
        res = await svc.on_call({"action": "set", "args": {"zoom": 4}})        # zoom autour de l'écoute
        ok.append(res["zoom"] == 4 and res["zoom_off"] == 200_000)
        ok.append(await wait_line(bus, 7_300_000, 500_000))
        res = await svc.on_call({"action": "set", "args": {"dfreq_hz": 6_900_000}})   # écoute hors fenêtre : elle suit
        ok.append(res["zoom_off"] == -200_000)
        ok.append(await wait_line(bus, 6_900_000, 500_000))
        res = await svc.on_call({"action": "set", "args": {"zoom": 1}})
        ok.append(res["zoom_off"] == 0 and await wait_line(bus, 7_100_000, 2_000_000))
        svc.stop()
        await asyncio.wait_for(task, 10)
        return ok
    assert asyncio.run(scenario()) == [True] * 6


def test_width_and_antenna_from_the_page_stay_under_the_station_ceiling() -> None:
    sd = cfgmod.Sdr(serial="170502E910", sample_rate_hz=6_000_000, antenna="A")
    assert fs_choices(sd) == [2_000_000, 6_000_000]                      # 8 MHz : seulement par station.toml
    s = clean_settings({"fs": 2_000_000, "ant": "B"}, Settings(7_100_000, 2, 50, 8))
    args = core_args(sd, s)
    assert args[args.index("--fs") + 1] == "2000000" and args[args.index("--ant") + 1] == "B"
    assert args[args.index("--bw") + 1] == "1536"
    assert base_fs(sd, Settings(7_100_000, 2, 50, 8, fs=8_000_000)) == 6_000_000   # au-delà du plafond : ignorée
    rtl = cfgmod.Sdr(serial="00000001", driver="rtlsdr", sample_rate_hz=2_048_000)
    assert fs_choices(rtl) == [1_024_000, 2_048_000]
    assert antenna(rtl, Settings(100_000_000, 0, 20, 8, ant="B")) == rtl.antenna     # clé RTL-SDR : pas de choix
    for bad in ({"fs": -1}, {"fs": True}, {"ant": "C"}):
        with pytest.raises(SetRefused):
            clean_settings(bad, Settings(7_100_000, 2, 50, 8))


def test_new_width_or_antenna_restarts_the_core_without_counting_a_failure(tmp_path: Path) -> None:
    from trxstation.modules.client import CallRefused

    async def scenario():
        bus, emitted = FakeBus(), []
        sd = cfgmod.Sdr(enabled=True, serial="TEST1234", lines_per_s=10, sample_rate_hz=6_000_000)
        svc = SdrService(sd, tmp_path, bus, core_prefix=FAKE, emit=lambda code, **kw: emitted.append((code, kw)))
        task = asyncio.ensure_future(svc.run())
        for _ in range(100):
            if svc.state["state"] == "running" and any(m["kind"] == "sdr_line" and m["s"] == 6_000_000 for m in bus.sent):
                break
            await asyncio.sleep(0.05)
        refused = []
        for bad in ({"fs": 8_000_000}, {"fs": 1_000_000}):
            try:
                await svc.on_call({"action": "set", "args": bad})
            except CallRefused as exc:
                refused.append(exc)
        res = await svc.on_call({"action": "set", "args": {"fs": 2_000_000, "ant": "B"}})
        seen = False
        for _ in range(100):
            if any(m["kind"] == "sdr_line" and m["s"] == 2_000_000 for m in bus.sent):
                seen = True
                break
            await asyncio.sleep(0.05)
        svc.stop()
        await asyncio.wait_for(task, 10)
        return res, refused, seen, emitted, svc
    res, refused, seen, emitted, svc = asyncio.run(scenario())
    assert len(refused) == 2 and res["fs"] == 2_000_000 and res["ant"] == "B" and res["fs_max"] == 6_000_000
    assert res["fs_choices"] == [2_000_000, 6_000_000] and res["ant_choices"] == ["A", "B"]
    assert seen and emitted == [] and svc.restarts == 0                 # relance voulue, pas une panne
    assert json.loads((tmp_path / "sdr" / "last.json").read_text())["ant"] == "B"


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


# ------------------------------------------------------------------ son du SDR (lot S1b)
def _sdr_audio(clock, tx, asked=None):
    from trxstation.gateway.audio.sdr_audio import SdrAudio
    return SdrAudio(0, b"T" * 16, lambda: tx[0], request_audio=(lambda on: asked.append(on)) if asked is not None
                    else None, clock=lambda: clock[0])


def _packet(value: int, token: bytes = b"T" * 16, seq: int = 1) -> bytes:
    import struct
    return b"ORSA" + token + seq.to_bytes(4, "little") + struct.pack("<960h", *([value] * 960))


def test_sdr_audio_packets_need_the_token_and_queues_are_bounded() -> None:
    from trxstation.gateway.audio.sdr_audio import QUEUE_MAX
    clock, tx = [0.0], [False]
    audio = _sdr_audio(clock, tx)
    sub = audio.subscribe()
    assert audio.on_packet(_packet(100, token=b"X" * 16)) is False and audio.on_packet(b"ORSA") is False
    for i in range(QUEUE_MAX + 5):
        assert audio.on_packet(_packet(i, seq=i))
    assert len(sub.queue) == QUEUE_MAX and audio.refused == 2          # le plus ancien part : retard borné


def test_sdr_audio_is_silent_during_any_transmission_with_fades() -> None:
    import array
    from trxstation.gateway.audio.sdr_audio import SILENCE

    def level(pcm):
        a = array.array("h"); a.frombytes(pcm)
        return a[0], a[-1]
    clock, tx = [0.0], [False]
    audio = _sdr_audio(clock, tx)
    sub = audio.subscribe()
    for _ in range(6):
        audio.on_packet(_packet(1000))
    assert audio.next_block(sub, True) != SILENCE                       # écoute normale
    tx[0] = True                                                        # émission : fondu vers le silence (50 ms)
    first = level(audio.next_block(sub, True))
    assert first[0] > first[1] > 0
    blocks = [audio.next_block(sub, True) for _ in range(3)]
    assert blocks[-1] == SILENCE
    tx[0] = False
    clock[0] += 0.3                                                     # 0,3 s après : toujours le silence
    audio.on_packet(_packet(1000)); audio.on_packet(_packet(1000))
    assert audio.next_block(sub, True) == SILENCE
    clock[0] += 0.3                                                     # 0,6 s : reprise en fondu
    for _ in range(4):
        audio.on_packet(_packet(1000))
    rising = level(audio.next_block(sub, True))
    assert rising[0] < rising[1] and 0 < rising[1] <= 1000
    audio.next_block(sub, False)                                        # n'écoute plus : file vidée
    assert audio.next_block(sub, False) == SILENCE and not sub.queue


def test_sdr_audio_asks_the_module_only_when_someone_listens() -> None:
    clock, tx, asked = [0.0], [False], []
    audio = _sdr_audio(clock, tx, asked)
    audio.set_listeners(1); audio.set_listeners(2); audio.set_listeners(1)
    assert asked == [True]
    clock[0] = 10.0
    audio.tick()                                                        # rien reçu depuis 10 s : on redemande
    assert asked == [True, True]
    audio.on_packet(_packet(5)); audio.tick()
    assert asked == [True, True]
    audio.set_listeners(0)
    assert asked == [True, True, False]


def test_module_sends_audio_packets_with_the_gateway_token(tmp_path: Path) -> None:
    from trxstation.gateway.audio.sdr_audio import PACKET_BYTES, SdrAudio
    from trxstation.sdr.service import audio_token
    got = []
    gateway = SdrAudio(0, audio_token("secret-du-module"), lambda: False)
    sub = gateway.subscribe()

    async def scenario():
        bus = FakeBus()
        svc = SdrService(cfgmod.Sdr(enabled=True, serial="TEST1234"), tmp_path, bus, core_prefix=FAKE,
                         audio_secret="secret-du-module", audio_sink=lambda p: (got.append(p), gateway.on_packet(p)))
        task = asyncio.ensure_future(svc.run())
        await asyncio.sleep(0.5)
        assert got == []                                                # personne n'écoute : aucun son
        await svc.on_call({"action": "audio", "args": {"on": True}})
        await svc.on_call({"action": "set", "args": {"dfreq_hz": 7_150_000, "mode": "AM"}})
        await asyncio.sleep(1.0)
        snap = svc.snapshot()
        svc.stop()
        await asyncio.wait_for(task, 10)
        return snap
    snap = asyncio.run(scenario())
    assert got and all(len(p) == PACKET_BYTES for p in got) and gateway.packets == len(got) and sub.queue
    assert snap["audio"] is True and (snap["dfreq"], snap["mode"], snap["dbw"]) == (7_150_000, "AM", 8000)


def test_listened_frequency_outside_the_sdr_width_is_refused(tmp_path: Path) -> None:
    from trxstation.modules.client import CallRefused
    svc, _, _ = _service(tmp_path)
    with pytest.raises(CallRefused):
        asyncio.run(svc.on_call({"action": "set", "args": {"dfreq_hz": 9_000_000}}))   # 2 MHz autour de 7,1 MHz
    for bad in ({"mode": "WFM"}, {"sql": 50}, {"dbw": 50}):
        with pytest.raises(SetRefused):
            clean_settings(bad, Settings(7_100_000, 2, 50, 8))


def test_listen_command_needs_a_second_audio_track() -> None:
    from types import SimpleNamespace
    from trxstation.gateway.api.session import ControlSession
    ctrl = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="RX"), heartbeat=lambda cid: None,
                           config=SimpleNamespace(rig=SimpleNamespace(), safety=SimpleNamespace(allow_replay=False)))
    sent, changes = [], []

    async def call(data):
        return {}
    s = ControlSession("phone", ctrl, SimpleNamespace(), None, None, sent.append, role="operator")
    s.sdr_call, s.on_sdr_listen = call, lambda: changes.append(s.sdr_listen)
    assert "sdr_audio" not in s.features()
    asyncio.run(s.on_message(json.dumps({"cmd": "sdr", "id": 1, "action": "listen", "args": {"on": True}})))
    assert sent[-1]["reason"] == "sdr_audio_unavailable" and changes == []
    s.sdr_audio_offered = True
    assert "sdr_audio" in s.features()
    asyncio.run(s.on_message(json.dumps({"cmd": "sdr", "id": 2, "action": "listen", "args": {"on": True}})))
    assert sent[-1] == {"type": "result", "id": 2, "ok": True, "action": "listen", "on": True} and changes == [True]


# ------------------------------------------------------------------ charge (lot S1b-2)
class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_load_ladder_climbs_one_step_per_hold_and_comes_back_slowly() -> None:
    from trxstation.sdr.load import Ladder
    clock = _Clock()
    ladder = Ladder(clock=clock)
    for _ in range(10):                                    # 10 mesures (9 s après la première) : rien
        clock.t += 1
        assert not ladder.step("processeur à 99 %", False)
    clock.t += 1
    assert ladder.step("processeur à 99 %", False) and ladder.level == 1 and "99" in ladder.reason
    for _ in range(60):
        clock.t += 1
        ladder.step("processeur à 99 %", False)
    assert ladder.level == 5                               # plafonné
    clock.t += 200
    assert not ladder.step("", True)                       # au vert, mais pas assez longtemps
    clock.t += 100
    ladder.step("", False)                                 # pas « nettement » sous les seuils : compteur remis
    clock.t += 299
    assert not ladder.step("", True)
    clock.t += 299
    assert not ladder.step("", True)
    clock.t += 1
    assert ladder.step("", True) and ladder.level == 4     # un cran rendu après 5 min au vert
    for _ in range(4):
        clock.t += 300
        ladder.step("", True)
    assert ladder.level == 0 and ladder.reason == ""


def test_load_levels_effects() -> None:
    from trxstation.sdr.load import sample_rate, waterfall_rate
    assert [waterfall_rate(8, n) for n in range(6)] == [8, 8, 4, 1, 1, 1]
    assert waterfall_rate(1, 2) == 1
    assert [sample_rate(8_000_000, n) for n in (0, 3, 4, 5)] == [8_000_000, 8_000_000, 2_000_000, 2_000_000]
    assert sample_rate(2_000_000, 4) == 2_000_000
    sd = cfgmod.Sdr(serial="X1234", sample_rate_hz=8_000_000)
    args = core_args(sd, Settings(7_100_000, 2, 50, 8), 4)
    assert args[args.index("--fs") + 1] == "2000000" and args[args.index("--rate") + 1] == "1"


def test_gateway_governor_cuts_sdr_audio_first_then_throttles_and_resends() -> None:
    from trxstation.gateway.api.overload import Limits, Sample
    from trxstation.gateway.audio.sdr_audio import SdrAudio
    from trxstation.gateway.sdr_load import RESEND_S, SdrGovernor, limits_from_access
    from trxstation.sdr.load import Ladder
    clock, sample, sent, emitted, asked = _Clock(), [Sample(cpu_pct=50)], [], [], []
    audio = SdrAudio(0, b"x" * 16, lambda: False, request_audio=asked.append)
    audio.set_listeners(1)
    xr = type("Src", (), {"xruns": 0, "overruns": 0})()
    gov = SdrGovernor(lambda: sample[0], Limits(), lambda lvl, why: sent.append((lvl, why)), audio=audio,
                      xrun_source=xr, ladder=Ladder(clock=clock), emit=lambda code, **kw: emitted.append((code, kw)))

    def second():
        clock.t += 1
        gov.measure()
        asyncio.run(gov.push())
    second()
    assert sent == [(0, "")] and not audio.blocked              # premier envoi : niveau 0 (module relancé ?)
    sample[0] = Sample(cpu_pct=95)
    for _ in range(11):
        second()
    assert gov.ladder.level == 1 and audio.blocked and asked == [True, False]   # son coupé, démodulation arrêtée
    assert sent[-1][0] == 1 and emitted[-1][0] == codes.ORT_6006
    sample[0] = Sample(cpu_pct=10)
    n = len(sent)
    for _ in range(int(RESEND_S)):
        second()
    assert len(sent) == n + 1 and sent[-1][0] == 1             # niveau renvoyé (module relancé entre-temps)
    for _ in range(300):
        second()
    assert gov.ladder.level == 0 and not audio.blocked and asked[-1] is True and emitted[-1][0] == codes.ORT_6007
    for _ in range(20):                                          # un décrochage par seconde (carte son du poste)
        xr.xruns += 1
        second()
    assert gov.ladder.level == 1 and "décrochages" in gov.ladder.reason
    lim = limits_from_access(cfgmod.Access())
    assert lim.cpu_pct < cfgmod.Access().overload_cpu_pct and lim.lag_ms < cfgmod.Access().overload_lag_ms


def test_governor_never_raises_when_the_module_is_absent() -> None:
    from trxstation.gateway.api.overload import Limits, Sample
    from trxstation.gateway.sdr_load import SdrGovernor

    def send(level, why):
        raise ConnectionError("module absent")
    gov = SdrGovernor(lambda: Sample(), Limits(), send)
    gov.measure()
    asyncio.run(gov.push())
    assert gov._sent is None


def test_module_applies_the_gateway_load_level_and_suspends(tmp_path: Path) -> None:
    from trxstation.modules.client import CallRefused

    async def scenario():
        svc, bus, emitted = _service(tmp_path)
        task = asyncio.ensure_future(svc.run())
        for _ in range(100):
            if svc.state["state"] == "running":
                break
            await asyncio.sleep(0.05)
        await svc.on_call({"action": "audio", "args": {"on": True}})
        assert svc.snapshot()["audio"] is True
        await svc.on_call({"action": "load", "args": {"level": 3, "reason": "processeur à 95 %"}})
        mid = svc.snapshot()
        await svc.on_call({"action": "load", "args": {"level": 5, "reason": "processeur à 99 %"}})
        for _ in range(100):
            if svc.state["state"] == "suspended":
                break
            await asyncio.sleep(0.05)
        suspended = (svc.snapshot(), svc.proc)
        await svc.on_call({"action": "load", "args": {"level": 0}})
        for _ in range(100):
            if svc.state["state"] == "running":
                break
            await asyncio.sleep(0.05)
        back = svc.snapshot()
        with pytest.raises(CallRefused):
            await svc.on_call({"action": "load", "args": {"level": 9}})
        svc.stop()
        await asyncio.wait_for(task, 10)
        return mid, suspended, back, emitted
    mid, (susp, proc), back, emitted = asyncio.run(scenario())
    assert mid["load"] == 3 and mid["rate_eff"] == 1 and mid["audio"] is False and "95" in mid["load_reason"]
    assert susp["state"] == "suspended" and proc is None and susp["load"] == 5
    assert back["state"] == "running" and back["load"] == 0 and back["rate_eff"] == 10 and back["audio"] is True
    assert emitted == []                                   # un arrêt voulu n'est pas une panne


def test_module_throttles_itself_above_its_cpu_limit(tmp_path: Path) -> None:
    clock = _Clock()
    sd = cfgmod.Sdr(enabled=True, serial="TEST1234", max_cpu_pct=50)
    emitted = []
    svc = SdrService(sd, tmp_path, None, core_prefix=FAKE, clock=clock, emit=lambda code, **kw: emitted.append((code, kw)))
    svc._self_cpu = lambda: 80.0                           # module seul à 80 % d'un cœur
    for _ in range(11):
        clock.t += 1
        changed = svc._self_measure()
    assert changed and svc.ladder.level == 1 and svc.level == 1 and emitted[-1][0] == codes.ORT_6008
    assert "plafond 50" in svc.load_reason()
    svc.gw_level, svc.gw_reason = 2, "passerelle en retard de 90 ms"
    assert svc.level == 2 and "passerelle" in svc.load_reason()


# ------------------------------------------------------------------ recherche USB (étape 196)
def _usb(root: Path, name: str, vid: str, pid: str, serial: str = "", driver: str = "", **strings) -> None:
    d = root / name
    d.mkdir()
    for key, value in (("idVendor", vid), ("idProduct", pid), ("serial", serial), ("busnum", "3"),
                       ("devnum", str(len(list(root.iterdir())))), *strings.items()):
        (d / key).write_text(value + "\n")
    DRIVERS[name] = driver                    # « 3-3:1.0 » n'est pas un nom de fichier possible sous Windows


DRIVERS: dict[str, str] = {}


def test_usb_scan_finds_sdrplay_and_rtl_sdr_behind_hubs_and_flags_problems(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(devices, "driver_of", lambda _sysfs, name: DRIVERS.get(name, ""))
    sysfs, proc = tmp_path / "sys", tmp_path / "proc"
    sysfs.mkdir(); proc.mkdir()
    _usb(sysfs, "3-3", "1df7", "3010", "170502EC10", "usbfs")                      # RSP de l'AIS
    _usb(sysfs, "3-5", "1df7", "3010", "170502E910", "usbfs")                      # RSP de la station
    _usb(sysfs, "3-2", "0424", "2422")                                              # hub interne du poste
    _usb(sysfs, "3-2.1", "0c26", "0052", "IC-7300MK2 13003336", "cdc_acm")
    _usb(sysfs, "3-2.4", "0bda", "2838", "00000001", manufacturer="RTLSDRBlog", product="Blog V4")
    _usb(sysfs, "3-6.2", "0bda", "2838", "00000001", "dvb_usb_rtl28xxu")
    _usb(sysfs, "3-6.3", "0bda", "2832", "RTL42", "usbfs")
    api = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout='{"api":3.15,"devices":[{"serial":"170502E910","hw":2}]}\n', stderr="")
    found, warnings = devices.scan("sdr-core", "170502E910", sysfs=sysfs, proc=proc, run=api)
    by = {d["name"]: d for d in found}
    assert set(by) == {"3-3", "3-5", "3-2.4", "3-6.2", "3-6.3"}                    # le poste n'est pas un SDR
    assert by["3-3"]["state"] == "pris" and by["3-5"]["state"] == "station"
    assert by["3-2.4"]["state"] == "libre" and by["3-2.4"]["model"] == "RTL-SDR (RTLSDRBlog Blog V4)"
    assert by["3-2.4"]["location"] == "bus 3, port 2 -> hub, port 4" and by["3-2.4"]["radio_hub"] is True
    assert by["3-6.2"]["state"] == "noyau" and by["3-6.3"]["state"] == "pris"
    assert by["3-2.4"]["duplicate"] and by["3-6.2"]["duplicate"] and not by["3-5"]["duplicate"]
    text = "\n".join(warnings)
    assert "00000001 en DOUBLE" in text and "MÊME hub que le poste" in text and "pilote TV du noyau" in text


def test_usb_scan_never_opens_a_device_and_survives_without_sysfs(tmp_path: Path) -> None:
    found, warnings = devices.scan(None, sysfs=tmp_path / "absent", proc=tmp_path)
    assert found == [] and warnings == []
    assert devices.location_text("3-6.2.1") == "bus 3, port 6 -> hub, port 2 -> hub, port 1"


# ------------------------------------------------------------------ clés RTL-SDR (étape 197)
def test_rtl_sdr_driver_rates_and_core_arguments() -> None:
    from trxstation.sdr.service import low_rate
    sd = cfgmod.Sdr(enabled=True, serial="00000042", driver="rtlsdr", sample_rate_hz=2_048_000)
    problems = cfgmod._sdr_problems(sd, cfgmod.Modules(run=["sdr"]))
    assert problems == []
    assert cfgmod._sdr_problems(cfgmod.Sdr(driver="rtlsdr", sample_rate_hz=8_000_000), cfgmod.Modules())   # 8 MHz : RSP seulement
    args = core_args(sd, Settings(100_000_000, 2, 50, 8))
    assert args[args.index("--driver") + 1] == "rtlsdr" and args[args.index("--fs") + 1] == "2048000"
    assert args[args.index("--bw") + 1] == "0"                          # filtre du tuner : propre au RSP
    assert low_rate(sd) == 1_024_000 and core_args(sd, Settings(100_000_000, 2, 50, 8), 4)[
        args.index("--fs") + 1] == "1024000"                            # bridage niveau 4


def test_rtl_keys_stay_listed_when_the_sdrplay_service_is_down() -> None:
    out = '{"devices":[{"serial":"00000042","hw":0,"driver":"rtlsdr","product":"Blog V4"}],"api":null,"error":"service"}\n'
    found, error = devices.api_devices(sys.executable, run=lambda *a, **k: subprocess.CompletedProcess(a, 4, stdout=out, stderr=""))
    assert [d["serial"] for d in found] == ["00000042"] and "fabricant" in error
