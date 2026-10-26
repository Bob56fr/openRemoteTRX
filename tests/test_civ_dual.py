"""Essai à deux ports CI-V : rigctld sur le port A, spectre sur le port B, surveillance du PTT, bus partagé."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation import config as cfgmod
from trxstation.devtools import civ_dual as cd
from trxstation.devtools.civ_scope import CivRefused, ScopeProbe, encode_request

from test_civ_scope import RIG, Clock, FakeRig, rig_frame, to_bcd_le

ROOT = Path(__file__).resolve().parents[1]


class BusRig(FakeRig):
    """Faux poste qui répond À L'EXPÉDITEUR (comme un Icom) et peut montrer sur B le trafic de rigctld (E0h)."""

    def __init__(self, *, answers=(0xE0, 0xE1), shared_bus=False, **kw):
        super().__init__(**kw)
        self.answers, self.shared_bus = set(answers), shared_bus

    def write(self, data: bytes):
        sender = data[3]
        if sender not in self.answers:
            self.written.append(bytes(data))
            return
        before = len(self.out)
        super().write(data)
        if len(self.out) > before and self.out[before + 2] == 0xE0:
            self.out[before + 2] = sender

    def read(self, n):
        if self.shared_bus and self.ticks % 5 == 0:
            self.out += rig_frame(b"\x03", to=RIG, frm=0xE0)                       # commande de rigctld
            self.out += rig_frame(b"\x03" + to_bcd_le(14_074_000, 5), to=0xE0)     # réponse pour rigctld
        return super().read(n)


class FakeLink:
    """rigctld simulé : f et t ; `ptt_after` = nombre de lectures du PTT avant qu'il passe à 1."""

    def __init__(self, ptt_after=None, fail_from=None, freq=14_074_000):
        self.sent: list[str] = []
        self.ptt_after, self.fail_from, self.freq = ptt_after, fail_from, freq
        self.t_reads = 0

    def command(self, cmd):
        self.sent.append(cmd)
        if self.fail_from is not None and len(self.sent) > self.fail_from:
            raise TimeoutError("timed out")
        if cmd == "f":
            return 0, {"Frequency": str(self.freq)}
        if cmd == "t":
            self.t_reads += 1
            return 0, {"PTT": "1" if self.ptt_after is not None and self.t_reads > self.ptt_after else "0"}
        if cmd == "T 0":
            return 0, {}
        raise AssertionError(cmd)


# ------------------------------------------------------------------ sécurité

def test_tool_never_sends_a_transmit_order():
    text = (ROOT / "trxstation" / "devtools" / "civ_dual.py").read_text(encoding="utf-8")
    strings = [n.value for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any(re.fullmatch(r"\+?T\s*1", s.strip()) for s in strings)
    assert "T 0" in strings


def test_second_controller_is_allowed_but_the_closed_list_still_holds():
    assert encode_request(RIG, 0x03, frm=0xE1)[3] == 0xE1
    with pytest.raises(CivRefused):
        encode_request(RIG, 0x1C, 0x00, b"\x01", frm=0xE1)
    with pytest.raises(CivRefused):
        encode_request(RIG, 0x03, frm=0xE2)


def test_ptt_read_active_stops_the_test():
    dual = cd.DualProbe(FakeLink(ptt_after=0), say=lambda m: None, clock=Clock())
    with pytest.raises(cd.TransmitDetected):
        dual.read_ptt()
    dual.unkey("essai")
    assert dual.link.sent == ["t", "T 0"] and "RPRT 0" in dual.unkeys[0]


def test_silent_rigctld_stops_the_test_after_three_misses():
    dual = cd.DualProbe(FakeLink(fail_from=0), say=lambda m: None, clock=Clock())
    assert dual.read_freq() is None and dual.read_ptt() is None
    with pytest.raises(cd.RigctldLost):
        dual.read_freq()


def test_unkey_never_raises():
    dual = cd.DualProbe(FakeLink(fail_from=0), say=lambda m: None, clock=Clock())
    dual.unkey("panne")
    assert "TimeoutError" in dual.unkeys[0]


def test_tick_is_throttled():
    clock = Clock()
    dual = cd.DualProbe(FakeLink(), say=lambda m: None, clock=clock, period_s=0.5)
    for _ in range(50):                                   # 50 × 5 ms = 0,25 s : une seule interrogation
        dual.tick()
    assert dual.link.sent == ["f", "t"]


# ------------------------------------------------------------------ port B

def test_spectrum_on_port_b_while_rigctld_is_polled_and_settings_restored():
    rig, clock = BusRig(), Clock()
    probe = ScopeProbe(rig, address=None, say=lambda m: None, clock=clock, controller=cd.SECOND_CONTROLLER)
    dual = cd.DualProbe(FakeLink(), say=lambda m: None, clock=clock)
    assert cd.detect_b(probe, lambda m: None) and probe.controller == 0xE1
    assert cd.read_freq_b(probe) == 14_074_000
    probe.run(3.0, show=False, tick=dual.tick)
    assert probe.scope.complete >= 5 and dual.latency_ms["t"] and set(dual.ptt_values) == {"0"}
    assert rig.settings == {0x10: 0, 0x11: 0}
    assert all(w[3] == 0xE1 for w in rig.written)
    ok, lines = cd.verdict(probe, dual, tx_seen=False, lost=False, freq_match=True, log_scope=0)
    assert ok and any("spectre reçu sur le port B" in line for line in lines)
    assert dual.link.t_reads >= 5


def test_rigctld_traffic_seen_on_port_b_is_counted_not_taken_as_ours():
    rig = BusRig(shared_bus=True)
    probe = ScopeProbe(rig, address=RIG, say=lambda m: None, clock=Clock(), controller=cd.SECOND_CONTROLLER)
    probe.run(2.0, show=False)
    assert probe.counts["commandes d'un autre contrôleur"] > 0
    assert probe.counts["réponses pour un autre contrôleur"] > 0
    assert probe.echo == 0                                 # le trafic de rigctld n'est pas compté comme notre écho


def test_rig_that_ignores_the_second_controller_falls_back_to_e0():
    rig = BusRig(answers=(0xE0,))
    probe = ScopeProbe(rig, address=None, say=lambda m: None, clock=Clock(), controller=cd.SECOND_CONTROLLER)
    assert cd.detect_b(probe, lambda m: None)
    assert probe.controller == 0xE0 and any("E1h" in n for n in probe.notes)


def test_transmit_during_the_run_restores_the_spectrum_settings():
    rig, clock = BusRig(), Clock()
    probe = ScopeProbe(rig, address=RIG, say=lambda m: None, clock=clock, controller=cd.SECOND_CONTROLLER)
    dual = cd.DualProbe(FakeLink(ptt_after=2), say=lambda m: None, clock=clock)
    with pytest.raises(cd.TransmitDetected):
        probe.run(5.0, show=False, tick=dual.tick)
    assert rig.settings == {0x10: 0, 0x11: 0} and dual.link.t_reads == 3


# ------------------------------------------------------------------ bilan

def test_verdict_failures_and_shared_bus():
    probe = ScopeProbe(BusRig(), address=RIG, say=lambda m: None, clock=Clock())
    dual = cd.DualProbe(FakeLink(), say=lambda m: None, clock=Clock())
    dual.failures["t"] = 2
    ok, lines = cd.verdict(probe, dual, tx_seen=True, lost=False, freq_match=False, log_scope=12)
    text = "\n".join(lines)
    assert not ok
    for part in ("PTT relu ACTIF", "aucun balayage", "2 lecture(s)", "fréquence différente", "aussi le spectre"):
        assert part in text


def test_scan_log(tmp_path):
    log = tmp_path / "rigctld.log"
    log.write_text("****4:icom.c(9356):icom_process_async_frame entered\n"           # forme d'un vrai journal 4.7.2
                   "*****5:event.c(609):rig_fire_freq_event entered\n"
                   "****4:icom.c(9356):icom_process_async_frame entered\n"
                   "*****5:event.c(700):rig_fire_spectrum_event entered\n"
                   "icom_one_transaction: unknown async? read again\nnormal\n", encoding="utf-8")
    received, scope, trouble, first = cd.scan_log(log)
    assert (received, scope, trouble) == (2, 1, 1) and "read again" in first[0]
    assert cd.scan_log(tmp_path / "absent.log") == (0, 0, 0, [])


# ------------------------------------------------------------------ lancement

@pytest.fixture
def no_station(monkeypatch, tmp_path):
    monkeypatch.setattr(cd, "station_running", lambda ports: None)
    cfg = SimpleNamespace(rig=SimpleNamespace(port="COM8", ptt_port="", model=3094))
    monkeypatch.setattr(cfgmod, "load", lambda path: cfg)

    def never(*a, **k):
        raise AssertionError("le port B ne doit pas être ouvert")
    monkeypatch.setattr(cd, "open_serial", never)
    monkeypatch.setattr(cd, "rigctld_probe_command", never)
    return tmp_path / "station.toml"


def test_main_refuses_the_cat_port_as_port_b(no_station, capsys):
    assert cd.main(["--port-b", "com8", "--config", str(no_station), "--reglages-verifies"]) == 2
    assert "SECOND port" in capsys.readouterr().err


def test_main_asks_for_the_menu_check_before_opening_port_b(no_station, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "o")        # seul « OUI » (toute casse) vaut accord
    assert cd.main(["--port-b", "COM7", "--config", str(no_station)]) == 2
    out = capsys.readouterr().out
    assert "USB SEND" in out and "PAS été ouvert" in out


def test_main_accepts_lowercase_oui(no_station, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: " oui ")
    with pytest.raises(AssertionError, match="ne doit pas"):        # passe la confirmation : va jusqu'au lancement
        cd.main(["--port-b", "COM7", "--config", str(no_station)])


def test_main_refuses_while_the_station_runs(monkeypatch, capsys):
    monkeypatch.setattr(cd, "station_running", lambda ports: 4532)
    assert cd.main(["--port-b", "COM7"]) == 3


def test_main_rejects_bad_arguments(no_station):
    assert cd.main(["--port-b", "COM7", "--duree", "1"]) == 2
    assert cd.main(["--port-b", "COM7", "--adresse", "FE"]) == 2
