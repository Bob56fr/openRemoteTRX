# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Relevé du spectre Icom par le CI-V : trames, balayages, liste fermée des commandes, faux poste."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from trxstation.devtools import civ_scope as cs
from trxstation.devtools.civ_scope import (CivRefused, FrameReader, ScopeAssembler, ScopeProbe, bcd_le,
                                           encode_request)

ROOT = Path(__file__).resolve().parents[1]
RIG = 0xB6


def to_bcd_le(value: int, size: int) -> bytes:
    out = []
    for _ in range(size):
        value, low = divmod(value, 10)
        value, high = divmod(value, 10)
        out.append(high << 4 | low)
    return bytes(out)


def bcd(n: int) -> int:
    return (n // 10) << 4 | n % 10


def rig_frame(payload: bytes, to: int = cs.CONTROLLER, frm: int = RIG) -> bytes:
    return bytes([0xFE, 0xFE, to, frm]) + payload + bytes([0xFD])


def sweep_frames(points: list[int], *, divisions: int = 11, selector: bool = True, center_hz: int = 14_074_000,
                 span_hz: int = 25_000) -> list[bytes]:
    """Un balayage découpé comme sur un IC-7300 : division 1 = en-tête, puis les points."""
    head = bytes([0x00]) + to_bcd_le(center_hz, 5) + to_bcd_le(span_hz, 5) + bytes([0x00])
    per = -(-len(points) // (divisions - 1)) if divisions > 1 else 0
    chunks = [head] + [bytes(points[i * per:(i + 1) * per]) for i in range(divisions - 1)]
    if divisions == 1:
        chunks = [head + bytes(points)]
    frames = []
    for i, chunk in enumerate(chunks, start=1):
        prefix = (b"\x00" if selector else b"") + bytes([bcd(i), bcd(divisions)])
        frames.append(rig_frame(b"\x27\x00" + prefix + chunk, to=0x00))
    return frames


# ------------------------------------------------------------------ liste fermée

def test_only_whitelisted_commands_can_be_encoded():
    assert encode_request(RIG, 0x19, 0x00) == bytes([0xFE, 0xFE, RIG, 0xE0, 0x19, 0x00, 0xFD])
    assert encode_request(RIG, 0x27, 0x11, b"\x01")[-3:] == bytes([0x11, 0x01, 0xFD])
    for cmd, sub, data in [(0x1C, 0x00, b"\x01"),          # émission : JAMAIS
                           (0x1C, 0x00, None), (0x05, None, b"\x00\x00\x07\x14\x00"),   # accord
                           (0x06, None, b"\x01"), (0x27, 0x10, b"\x02"), (0x27, 0x12, None), (0x14, 0x0A, b"\x02\x55")]:
        with pytest.raises(CivRefused):
            encode_request(RIG, cmd, sub, data)
    with pytest.raises(CivRefused):
        encode_request(0xFE, 0x19, 0x00)


def test_transmit_command_does_not_exist_in_the_tool():
    tree = ast.parse((ROOT / "trxstation" / "devtools" / "civ_scope.py").read_text(encoding="utf-8"))
    keys = [k for node in ast.walk(tree) if isinstance(node, ast.Dict) for k in node.keys]
    assert all(not (isinstance(k, ast.Tuple) and isinstance(k.elts[0], ast.Constant) and k.elts[0].value == 0x1C)
               for k in keys)
    assert set(cs.ALLOWED) == {(0x19, 0x00), (0x03, None), (0x27, 0x10), (0x27, 0x11), (0x27, 0x14), (0x27, 0x15), (0x27, 0x19), (0x27, 0x1A),
                                (0x26, 0x00)}
    assert not any(k[0] == 0x1C for k in cs.ALLOWED)                                         # émission : jamais
    for sub in (0x14, 0x15, 0x19, 0x1A):                       # lectures, et seulement des valeurs de réglage décodables
        from trxstation.spectrum.civ import decode_setting
        assert all(v in (None, b"\x00") or decode_setting(sub, bytes([0x27, sub]) + v) is not None for v in cs.ALLOWED[(0x27, sub)])


# ------------------------------------------------------------------ trames et BCD

def test_frame_reader_handles_noise_split_collisions_and_truncation():
    reader = FrameReader()
    good = rig_frame(b"\x03" + to_bcd_le(14_074_000, 5))
    frames = list(reader.feed(b"\x00\x13" + good[:5]))
    frames += list(reader.feed(good[5:] + b"\xFE\xFE\xE0\xB6\xFC\xFD"))           # collision : jetée
    frames += list(reader.feed(b"\xFE\xFE\xE0\xB6\x03\x12" + good))                 # trame coupée puis trame complète
    assert [f.payload[0] for f in frames] == [0x03, 0x03]
    assert bcd_le(frames[0].payload[1:]) == 14_074_000 and reader.dropped > 0
    assert list(reader.feed(b"\xFE" * 3 + good[2:])) and not list(reader.feed(b"\xFE\xFE" + b"\x01" * 300))


def test_bcd_little_endian():
    assert bcd_le(to_bcd_le(7_074_000, 5)) == 7_074_000
    assert bcd_le(b"\x00\x00\x00\x45\x01") == 145_000_000
    assert bcd_le(b"\x0A") is None


# ------------------------------------------------------------------ balayages

def _assemble(frames: list[bytes]) -> tuple[ScopeAssembler, list]:
    reader, scope, out = FrameReader(), ScopeAssembler(), []
    for raw in frames:
        for frame in reader.feed(raw):
            sweep = scope.feed(frame.payload[2:], 0.0)
            if sweep:
                out.append(sweep)
    return scope, out


@pytest.mark.parametrize("selector", [True, False])
def test_sweep_is_rebuilt_from_its_divisions(selector):
    points = [i % 161 for i in range(475)]
    scope, sweeps = _assemble(sweep_frames(points, selector=selector))
    assert len(sweeps) == 1 and sweeps[0].points == points
    assert (sweeps[0].f1_hz, sweeps[0].f2_hz, sweeps[0].mode, sweeps[0].out_of_range) == (14_074_000, 25_000, 0, False)
    assert list(scope.layouts) == [f"{'avec' if selector else 'sans'} octet de choix, 11 division(s)"]
    assert scope.lengths == {475: 1}


def test_single_division_sweep_lan_style():
    points = [80] * 689
    _, sweeps = _assemble(sweep_frames(points, divisions=1))
    assert len(sweeps) == 1 and len(sweeps[0].points) == 689


def test_missing_division_drops_the_sweep_and_counts_it():
    frames = sweep_frames([10] * 475)
    scope, sweeps = _assemble(frames[:4] + frames[5:] + sweep_frames([20] * 475))
    assert len(sweeps) == 1 and sweeps[0].points == [20] * 475 and scope.incomplete >= 1


def test_unreadable_scope_payload_is_counted():
    scope = ScopeAssembler()
    assert scope.feed(b"\x99\x99", 0.0) is None and scope.feed(b"", 0.0) is None and scope.unreadable == 2


def test_ascii_line():
    line = cs.ascii_line([0] * 50 + [160] * 50, width=10)
    assert len(line) == 10 and line[0] == " " and line[-1] == "█"
    assert cs.ascii_line([]) == ""


# ------------------------------------------------------------------ faux poste

class FakeRig:
    """Faux IC-7300 : répond à l'identification, aux réglages du spectre et à la fréquence ; diffuse le spectre."""

    def __init__(self, address=RIG, answer_broadcast=True, echo=False, scope_on=0, refuse=()):
        self.address, self.answer_broadcast, self.echo = address, answer_broadcast, echo
        self.settings = {0x10: scope_on, 0x11: 0}
        self.refuse = set(refuse)
        self.out = bytearray()
        self.written: list[bytes] = []
        self.ticks = 0
        self.rts = self.dtr = False

    @property
    def in_waiting(self):
        return len(self.out)

    def write(self, data: bytes):
        self.written.append(bytes(data))
        if self.echo:
            self.out += data
        frame = next(FrameReader().feed(data))
        if frame.to not in (self.address,) and not (frame.to == 0 and self.answer_broadcast):
            return
        p = frame.payload
        reply = None
        if p == b"\x19\x00":
            reply = b"\x19\x00" + bytes([self.address])
        elif p == b"\x03":
            reply = b"\x03" + to_bcd_le(14_074_000, 5)
        elif p[:1] == b"\x27" and len(p) == 2:
            reply = p + bytes([self.settings[p[1]]])
        elif p[:1] == b"\x27" and len(p) == 3:
            if p[1] in self.refuse:
                reply = b"\xFA"
            else:
                self.settings[p[1]] = p[2]
                reply = b"\xFB"
        if reply is not None:
            self.out += rig_frame(reply, frm=self.address)

    def read(self, n):
        self.ticks += 1
        if self.settings[0x11] == 1 and self.settings[0x10] == 1 and self.ticks % 3 == 0:
            for frame in sweep_frames([(self.ticks + i) % 161 for i in range(475)]):
                self.out += frame
        data = bytes(self.out[:n])
        del self.out[:n]
        return data


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.005
        return self.t


def test_probe_finds_rig_records_sweeps_measures_cat_and_restores_settings(tmp_path):
    rig = FakeRig(echo=True)
    probe = ScopeProbe(rig, address=None, say=lambda m: None, clock=Clock())
    assert probe.detect((0x94,)) and probe.address == RIG
    probe.run(3.0, show=False)
    assert len(probe.sweeps) >= 5 and len(probe.sweeps[-1].points) == 475
    assert probe.cat_ms and probe.echo > 0                               # échos de nos trames ignorés
    assert rig.settings == {0x10: 0, 0x11: 0}                            # remis comme au départ
    sent = [bytes(w[4:-1]) for w in rig.written]
    assert all(cmd[0] in (0x19, 0x03, 0x27) for cmd in sent) and not any(cmd[0] == 0x1C for cmd in sent)
    summary = probe.summary("COM8", 115200)
    assert "adresse du poste B6h" in summary and "475 (" in summary and "avec octet de choix, 11 division(s)" in summary
    cs.save(tmp_path / "out", probe, summary)
    assert (tmp_path / "out" / "rapport.html").read_text(encoding="utf-8").count("<canvas") == 1
    first = json.loads((tmp_path / "out" / "balayages.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert len(first["points"]) == 475 and "->" in (tmp_path / "out" / "trames.txt").read_text(encoding="utf-8")


def test_scope_already_on_is_left_untouched(tmp_path):
    rig = FakeRig(scope_on=1)
    probe = ScopeProbe(rig, address=RIG, say=lambda m: None, clock=Clock())
    assert probe.detect(())
    probe.run(1.0, show=False)
    assert rig.settings == {0x10: 1, 0x11: 0}
    assert not any(w[4:-1] == b"\x27\x10\x00" for w in rig.written)


def test_settings_are_restored_even_after_an_interruption():
    rig = FakeRig()
    probe = ScopeProbe(rig, address=RIG, say=lambda m: None, clock=Clock())
    calls = {"n": 0}
    real = probe._frames

    def boom():
        calls["n"] += 1
        if calls["n"] == 40:                                             # Ctrl+C pendant le relevé
            raise KeyboardInterrupt
        return real()
    probe._frames = boom
    with pytest.raises(KeyboardInterrupt):
        probe.run(5.0, show=False)
    assert rig.settings == {0x10: 0, 0x11: 0}


def test_one_failed_restore_does_not_prevent_the_other():
    rig = FakeRig()
    probe = ScopeProbe(rig, address=RIG, say=lambda m: None, clock=Clock())
    real_set = probe.set_setting
    state = {"running": True}

    def flaky_set(sub, value):
        if not state["running"] and sub == 0x11:
            raise KeyboardInterrupt                                      # second Ctrl+C pendant la remise en état
        return real_set(sub, value)
    probe.set_setting = flaky_set
    real_frames = probe._frames
    calls = {"n": 0}

    def stop_after_a_while():
        calls["n"] += 1
        if calls["n"] == 40:
            state["running"] = False
            raise KeyboardInterrupt
        return real_frames()
    probe._frames = stop_after_a_while
    with pytest.raises(KeyboardInterrupt):
        probe.run(5.0, show=False)
    assert rig.settings[0x10] == 0                                       # l'affichage du spectre est quand même remis
    assert any("NON confirmée : 27 11" in n for n in probe.notes)


def test_refused_activation_is_reported():
    rig = FakeRig(refuse=(0x11,))
    messages = []
    probe = ScopeProbe(rig, address=RIG, say=messages.append, clock=Clock())
    probe.run(1.0, show=False)
    assert any("REFUSÉ" in m for m in messages) and not probe.sweeps
    assert "activation refusée : 27 11 01" in probe.summary("COM8", 115200)


def test_wrong_address_or_silent_rig_is_explained():
    messages = []
    probe = ScopeProbe(FakeRig(answer_broadcast=False, address=0x88), address=None, say=messages.append, clock=Clock())
    assert not probe.detect((0x94,))
    assert "--adresse" in messages[-1]


def test_main_refuses_while_the_station_runs(monkeypatch, capsys):
    monkeypatch.setattr(cs, "station_running", lambda: 4532)
    assert cs.main(["--port", "COM8"]) == 3
    assert "Arrête-la d'abord" in capsys.readouterr().err


def test_main_rejects_bad_arguments(monkeypatch):
    monkeypatch.setattr(cs, "station_running", lambda: None)
    assert cs.main(["--port", "COM8", "--adresse", "zz"]) == 2
    assert cs.main(["--port", "COM8", "--adresse", "FE"]) == 2
    assert cs.main(["--port", "COM8", "--duree", "0"]) == 2


def test_serial_port_is_opened_with_rts_and_dtr_low(monkeypatch):
    serial = pytest.importorskip("serial")
    seen = {}

    class Recorder(serial.Serial):
        def open(self):
            seen["rts"], seen["dtr"], seen["port"] = self.rts, self.dtr, self.port
    monkeypatch.setattr(serial, "Serial", Recorder)
    cs.open_serial("COM99", 115200)
    assert seen == {"rts": False, "dtr": False, "port": "COM99"}


class SettingsRig(FakeRig):
    """Répond aux lectures des réglages AVEC l'octet de choix, refuse sans (comportement à confirmer sur le vrai poste)."""

    def write(self, data: bytes):
        frame = next(FrameReader().feed(data))
        p = frame.payload
        if p[:1] == b"\x27" and len(p) >= 2 and p[1] in (0x14, 0x15, 0x19, 0x1A):
            self.written.append(bytes(data))
            reply = (p + {0x14: b"\x00", 0x15: b"\x00\x50\x00\x00\x00", 0x19: b"\x00\x00\x00", 0x1A: b"\x01"}[p[1]]
                     if len(p) == 3 else b"\xFA")
            self.out += rig_frame(reply, frm=self.address)
            return
        if p == b"\x26\x00":                                                     # USB-D, FIL2
            self.written.append(bytes(data))
            self.out += rig_frame(b"\x26\x00\x01\x01\x02", frm=self.address)
            return
        super().write(data)


def test_settings_survey_is_read_only_and_reports_raw_answers():
    rig = SettingsRig()
    probe = ScopeProbe(rig, address=RIG, say=lambda m: None, clock=Clock())
    lines = cs.read_scope_settings(probe)
    assert len(lines) == 9
    assert "27 15 avec 00" in lines[2] and lines[2].endswith("27 15 00 00 50 00 00 00")
    assert lines[3].endswith("refusé (FA)")
    assert lines[8].startswith("26 00") and lines[8].endswith("26 00 01 01 02")
    sent = [bytes(w[4:-1]) for w in rig.written]
    assert all((len(cmd) <= 3 and cmd[0] == 0x27) or cmd == b"\x26\x00" for cmd in sent)   # lectures seules : jamais de valeur écrite
    assert rig.settings == {0x10: 0, 0x11: 0}


def test_settings_mode_writes_a_report(monkeypatch, tmp_path, capsys):
    rig = SettingsRig()
    monkeypatch.setattr(cs, "station_running", lambda: None)
    monkeypatch.setattr(cs, "open_serial", lambda port, baud: rig)
    rig.close = lambda: None
    assert cs.main(["--port", "COM7", "--adresse", "B6", "--reglages", "--sortie", str(tmp_path / "r")]) == 0
    text = (tmp_path / "r" / "reglages.txt").read_text(encoding="utf-8")
    assert "largeur (SPAN)" in text and "lecture seule" in text

