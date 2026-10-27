# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Relevé du spectre par rigctld : liste fermée, décodage des paquets JSON, déroulé avec faux rigctld."""
from __future__ import annotations

import base64
import json
import socket
import threading

import pytest

from trxstation.devtools import hamlib_scope as hs
from trxstation.devtools.hamlib_scope import CommandRefused, HamlibScopeProbe, PacketStats, decode_points, find_spectra


# ------------------------------------------------------------------ liste fermée

@pytest.mark.parametrize("cmd", ["T 1", "T  0", "T 01", "T 2", "T -1", "F 7074000", "M USB 2400", "U TUNER 1", "U SPECTRUM 2", "u SCOPE; T 1",
                                 "\\set_ptt 1", "L RFPOWER 1", "u SPECTRUM\nT 1"])
def test_only_read_and_scope_commands_are_allowed(cmd):
    assert not hs.ALLOWED.fullmatch(cmd)


def test_allowed_commands():
    for cmd in ("f", "t", "T 0", "u SCOPE", "u SPECTRUM", "U SCOPE 1", "U SPECTRUM 0"):   # « T 0 » = coupure
        assert hs.ALLOWED.fullmatch(cmd)


class FakeRigctld:
    """rigctld factice en TCP (protocole étendu « + ») : enregistre les commandes reçues."""

    def __init__(self, funcs=None, refuse=()):
        self.funcs = dict(funcs or {"SCOPE": 1, "SPECTRUM": 0})
        self.refuse = set(refuse)
        self.unkey_fails = False
        self.received: list[str] = []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.server.accept()
        buf = b""
        with conn:
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    conn.sendall(self._answer(line.decode().lstrip("+")).encode())

    def _answer(self, cmd: str) -> str:
        self.received.append(cmd)
        parts = cmd.split()
        if cmd == "f":
            return "get_freq:\nFrequency: 7074000\nRPRT 0\n"
        if cmd == "t":
            return "get_ptt:\nPTT: 0\nRPRT 0\n"
        if cmd == "T 0":
            return "set_ptt: 0\nRPRT -5\n" if self.unkey_fails else "set_ptt: 0\nRPRT 0\n"
        if parts[0] == "u":
            return f"get_func: {parts[1]}\nFunc Status: {self.funcs[parts[1]]}\nRPRT 0\n"
        if parts[0] == "U":
            if parts[1] in self.refuse:
                return f"set_func: {parts[1]} {parts[2]}\nRPRT -11\n"
            self.funcs[parts[1]] = int(parts[2])
            return f"set_func: {parts[1]} {parts[2]}\nRPRT 0\n"
        return "RPRT -1\n"


class BareRigctld(FakeRigctld):
    def _answer(self, cmd):
        if cmd.startswith("u "):
            self.received.append(cmd)
            return f"get_func: {cmd.split()[1]}\n{self.funcs[cmd.split()[1]]}\nRPRT 0\n"   # valeur sans libellé
        return super()._answer(cmd)


def test_unlabelled_answers_are_read():
    rig = BareRigctld(funcs={"SCOPE": 1, "SPECTRUM": 0})
    link = hs.RigctlLink("127.0.0.1", rig.port)
    probe = HamlibScopeProbe(link, lambda timeout: None, say=lambda m: None, clock=Clock())
    assert probe.read_func("SCOPE") == 1 and probe.read_func("SPECTRUM") == 0
    link.close()


class SilentRigctld(FakeRigctld):
    def _answer(self, cmd):
        self.received.append(cmd)
        return ""                                                          # rigctld bloqué : aucune réponse


def test_silent_rigctld_is_reported_not_a_crash(monkeypatch, tmp_path, capsys):
    rig = SilentRigctld()
    monkeypatch.setattr(hs, "station_running", lambda ports: None)
    monkeypatch.setattr(hs, "RIGCTLD_PORT", rig.port)
    monkeypatch.setattr(hs, "wait_port", lambda port, proc, timeout=15.0: True)
    monkeypatch.setattr(hs, "rigctld_probe_command", lambda cfg, addr, **kw: ["rigctld"])

    class Proc:
        def terminate(self): pass
        def wait(self, timeout=None): return 0
    import subprocess
    import types
    monkeypatch.setattr(hs, "subprocess", types.SimpleNamespace(Popen=lambda *a, **kw: Proc(),
                                                                TimeoutExpired=subprocess.TimeoutExpired,
                                                                STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(hs, "DATA_PORT", 0)
    real_link = hs.RigctlLink
    monkeypatch.setattr(hs, "RigctlLink", lambda host, port: real_link(host, port, timeout=0.3))
    config = tmp_path / "station.toml"
    config.write_text('[rig]\nmodel = 1\n', encoding="utf-8")
    code = hs.main(["--config", str(config), "--duree", "1", "--sortie", str(tmp_path / "out")])
    assert code == 1
    assert "NE RÉPOND PLUS" in (tmp_path / "out" / "resume.txt").read_text(encoding="utf-8")


def test_link_never_sends_a_refused_command():
    rig = FakeRigctld()
    link = hs.RigctlLink("127.0.0.1", rig.port)
    with pytest.raises(CommandRefused):
        link.command("T 1")
    assert link.command("t") == (0, {"PTT": "0"})
    link.close()
    assert rig.received == ["t"]


# ------------------------------------------------------------------ paquets

def test_points_decoding():
    assert decode_points("00A0FF") == ([0, 160, 255], "hexadécimal")
    assert decode_points(base64.b64encode(bytes([1, 2, 3])).decode()) == ([1, 2, 3], "base64")
    assert decode_points([5, 6]) == ([5, 6], "liste")
    assert decode_points("zz")[0] is None and decode_points(None)[0] is None and decode_points([True])[0] is None


def hamlib_packet(points, **extra):
    spec = {"id": 0, "name": "Main", "type": "FIXED", "lowFreq": 6_912_800, "highFreq": 7_112_800,
            "length": len(points), "data": bytes(points).hex().upper()} | extra
    return json.dumps({"app": "Hamlib", "seq": 1, "rig": {"id": {"model": "IC-7300MK2"}}, "spectra": [spec]}).encode()


def test_packet_with_spectrum_gives_a_sweep():
    stats = PacketStats()
    sweeps = stats.feed(hamlib_packet([i % 160 for i in range(475)]), 1.0)
    assert len(sweeps) == 1 and len(sweeps[0].points) == 475
    assert (sweeps[0].f1_hz, sweeps[0].f2_hz) == (6_912_800, 7_112_800)
    assert stats.encodings == {"hexadécimal": 1} and stats.lengths == {475: 1} and "spectra" in stats.top_keys


def test_center_and_span_are_used_when_edges_are_missing():
    stats = PacketStats()
    raw = json.dumps({"spectra": [{"centerFreq": 7_012_800, "span": 200_000, "data": [1, 2]}]}).encode()
    sweep = stats.feed(raw, 0.0)[0]
    assert (sweep.f1_hz, sweep.f2_hz) == (7_012_800, 200_000)


def test_state_only_and_garbage_packets_are_counted():
    stats = PacketStats()
    assert stats.feed(b'{"app": "Hamlib", "rig": {}}', 0.0) == []
    assert stats.feed(b"pas du json", 0.0) == []
    assert (stats.packets, stats.unreadable, stats.with_spectrum) == (2, 1, 0)


def test_spectra_are_found_wherever_they_are():
    assert len(find_spectra({"rig": {"spectrum": {"data": "00"}}})) == 1
    assert len(find_spectra([{"spectra": [{"data": "00"}, {"data": "01"}]}])) == 2


# ------------------------------------------------------------------ déroulé

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.01
        return self.t


def test_probe_enables_spectrum_records_measures_and_restores():
    rig = FakeRigctld()
    link = hs.RigctlLink("127.0.0.1", rig.port)
    packets = [hamlib_packet([50] * 475), b'{"app": "Hamlib"}', hamlib_packet([60] * 475)] * 20
    probe = HamlibScopeProbe(link, lambda timeout: packets.pop(0) if packets else None, say=lambda m: None, clock=Clock())
    probe.run(2.0, show=False)
    link.close()
    assert len(probe.sweeps) >= 20 and rig.funcs == {"SCOPE": 1, "SPECTRUM": 0}          # SPECTRUM remis comme au départ
    assert "U SPECTRUM 1" in rig.received and rig.received[-1] == "U SPECTRUM 0"
    assert not any(c.startswith("U SCOPE") for c in rig.received)                         # déjà actif : non touché
    assert not any(c.startswith("T") for c in rig.received)
    assert probe.latency_ms["f"] and probe.latency_ms["t"] and probe.ptt_values == {"0": len(probe.latency_ms["t"])}
    summary = probe.summary("127.0.0.1")
    assert "Points par balayage : 475" in summary and "Codage des points : hexadécimal" in summary
    assert "serveur de commandes UDP désactivé" in summary


class UnreadableRigctld(FakeRigctld):
    def _answer(self, cmd):
        if cmd.startswith("u "):
            self.received.append(cmd)
            return f"get_func: {cmd.split()[1]}\nRPRT -11\n"
        return super()._answer(cmd)


def test_unknown_start_state_leaves_the_display_on_and_turns_the_data_output_off():
    rig = UnreadableRigctld(funcs={"SCOPE": 1, "SPECTRUM": 0})                 # le poste a l'affichage allumé
    link = hs.RigctlLink("127.0.0.1", rig.port)
    probe = HamlibScopeProbe(link, lambda timeout: None, say=lambda m: None, clock=Clock())
    probe.run(0.5, show=False)
    link.close()
    assert rig.funcs == {"SCOPE": 1, "SPECTRUM": 0}                             # l'affichage n'est JAMAIS éteint sur une supposition
    assert "U SCOPE 0" not in rig.received and rig.received[-1] == "U SPECTRUM 0"
    summary = probe.summary("127.0.0.1")
    assert "SCOPE laissé à 1" in summary and "RPRT -11" in summary


def test_refused_activation_is_reported():
    rig = FakeRigctld(refuse=("SPECTRUM",))
    link = hs.RigctlLink("127.0.0.1", rig.port)
    messages = []
    probe = HamlibScopeProbe(link, lambda timeout: None, say=messages.append, clock=Clock())
    probe.run(0.5, show=False)
    link.close()
    assert any("REFUSÉE" in m for m in messages) and "activation refusée : U SPECTRUM 1" in probe.summary("127.0.0.1")


def test_rigctld_command_keeps_station_settings_and_disables_the_udp_command_server(monkeypatch):
    from trxstation import hamlib
    from trxstation.setup_wizard import dummy_config
    monkeypatch.setattr(hamlib, "find_tool", lambda name, d="": "/usr/bin/rigctld")
    cfg = dummy_config()
    cfg.rig.port, cfg.rig.speed, cfg.rig.extra_conf = "COM8", 115200, ["rts_state=OFF"]
    cmd = hs.rigctld_probe_command(cfg, "127.0.0.1")
    assert cmd[0] == "/usr/bin/rigctld" and "-T" in cmd and cmd[cmd.index("-T") + 1] == "127.0.0.1"
    assert cmd[cmd.index("-t") + 1] == str(hs.RIGCTLD_PORT) and "rts_state=OFF" in cmd and "COM8" in cmd
    conf = cmd[cmd.index("-C", cmd.index("rts_state=OFF")) + 1]
    assert "async=1" in conf and "multicast_data_addr=127.0.0.1" in conf and "multicast_cmd_addr=0.0.0.0" in conf


@pytest.mark.parametrize("addr", ["192.168.1.21", "0.0.0.0", "pas une adresse", "::1"])
def test_data_address_must_stay_local_or_be_explicit_multicast(addr, capsys):
    assert hs.main(["--adresse-donnees", addr]) == 2


def test_main_refuses_while_a_station_runs(monkeypatch, capsys):
    monkeypatch.setattr(hs, "station_running", lambda ports: 4532)
    assert hs.main([]) == 3


def test_unkey_test_sends_only_t0_and_reports_failures():
    rig = FakeRigctld()
    rig.unkey_fails = True                                                       # l'ordre de coupure n'aboutit pas
    link = hs.RigctlLink("127.0.0.1", rig.port)
    probe = HamlibScopeProbe(link, lambda timeout: None, say=lambda m: None, clock=Clock(), unkey_test=True)
    probe.run(1.5, show=False)
    link.close()
    assert "T 0" in rig.received and not any(c.startswith("T 1") for c in rig.received)
    assert probe.unkey_codes == {"RPRT -5": probe.unkey_codes["RPRT -5"]} and probe.unkey_codes["RPRT -5"] >= 2
    assert "Ordre de coupure « T 0 » : RPRT -5" in probe.summary("127.0.0.1")


def test_comparison_without_async_does_not_touch_the_spectrum():
    rig = FakeRigctld()
    link = hs.RigctlLink("127.0.0.1", rig.port)
    probe = HamlibScopeProbe(link, lambda timeout: None, say=lambda m: None, clock=Clock(), unkey_test=True,
                             use_spectrum=False)
    probe.run(1.0, show=False)
    link.close()
    assert not any(c.split()[0] in ("u", "U") for c in rig.received)
    assert probe.unkey_codes == {"RPRT 0": probe.unkey_codes["RPRT 0"]}


def test_rigctld_command_without_async(monkeypatch):
    from trxstation import hamlib
    from trxstation.setup_wizard import dummy_config
    monkeypatch.setattr(hamlib, "find_tool", lambda name, d="": "/usr/bin/rigctld")
    cmd = hs.rigctld_probe_command(dummy_config(), "127.0.0.1", use_async=False, verbose="-vvvv")
    assert not any("async" in a or "multicast" in a for a in cmd) and cmd[-1] == "-vvvv"
