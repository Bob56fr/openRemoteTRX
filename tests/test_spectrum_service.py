"""Spectre par le second port CI-V : vérification du port B, service de la passerelle, retour au mode normal."""
from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation import config as cfgmod
from trxstation.spectrum import probe as pr
from trxstation.spectrum.civ import ALLOWED, FrameReader, encode_request
from trxstation.spectrum.service import SpectrumService

from test_civ_scope import RIG, rig_frame, sweep_frames, to_bcd_le

ROOT = Path(__file__).resolve().parents[1]
ICOM = {"rig": {"model": 3094, "port": "COM8", "speed": 115200}}
CIV = {"enabled": True, "source": "civ_port", "port": "COM7", "civ_address": "B6"}


# ------------------------------------------------------------------ faux poste sur le port B

class PortB:
    """Faux second port d'IC-7300MK2 : répond à l'expéditeur, diffuse le spectre quand sa sortie est en marche."""

    def __init__(self, *, address=RIG, freq=14_074_000, answers=True, scope=True, refuse_set=False):
        self.address, self.freq, self.answers, self.scope, self.refuse_set = address, freq, answers, scope, refuse_set
        self.settings = {0x10: 0, 0x11: 0}
        self.out = bytearray()
        self.written: list[bytes] = []
        self.closed = False
        self.rts = self.dtr = False
        self.ticks = 0
        self.mute = False                          # True : plus rien ne sort (port réglé autrement, câble…)

    @property
    def in_waiting(self):
        return len(self.out)

    def write(self, data: bytes):
        self.written.append(bytes(data))
        frame = next(FrameReader().feed(data))
        if not self.answers or self.mute or frame.to not in (self.address, 0x00):
            return
        p, reply = frame.payload, None
        if p == b"\x19\x00":
            reply = b"\x19\x00" + bytes([self.address])
        elif p == b"\x03":
            reply = b"\x03" + to_bcd_le(self.freq, 5)
        elif p[:1] == b"\x27" and len(p) >= 2 and p[1] not in (0x10, 0x11):
            reply = b"\xFA"                                                  # autres réglages : voir test_spectrum_settings
        elif p[:1] == b"\x27" and self.scope:
            if len(p) == 2:
                reply = p + bytes([self.settings[p[1]]])
            elif self.refuse_set:
                reply = b"\xFA"
            else:
                self.settings[p[1]] = p[2]
                reply = b"\xFB"
        elif p[:1] == b"\x27":
            reply = b"\xFA"
        if reply is not None:
            self.out += rig_frame(reply, to=frame.frm, frm=self.address)

    def read(self, n):
        self.ticks += 1
        if not self.mute and self.settings == {0x10: 1, 0x11: 1} and self.ticks % 3 == 0:
            for raw in sweep_frames([(self.ticks + i) % 161 for i in range(475)]):
                self.out += raw
        data = bytes(self.out[:n])
        del self.out[:n]
        return data

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.005
        return self.t


# ------------------------------------------------------------------ sécurité de la liste fermée

def test_closed_command_list_has_no_transmit_command():
    assert set(ALLOWED) == {(0x19, 0x00), (0x03, None), (0x27, 0x10), (0x27, 0x11), (0x27, 0x14), (0x27, 0x15), (0x27, 0x19), (0x27, 0x1A)}
    from trxstation.spectrum.civ import decode_setting
    for sub in (0x14, 0x15, 0x19, 0x1A):                       # lectures, et seulement des valeurs de réglage décodables
        assert all(v in (None, b"\x00") or decode_setting(sub, bytes([0x27, sub]) + v) is not None for v in ALLOWED[(0x27, sub)])
    for path in ("trxstation/spectrum/civ.py", "trxstation/spectrum/probe.py", "trxstation/spectrum/service.py"):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        assert not any(isinstance(n, ast.Constant) and n.value == 0x1C for n in ast.walk(tree)), path


def test_station_uses_its_own_controller_address():
    rig = PortB()
    port = pr.CivPort(rig, RIG, clock=Clock())
    port.identify()
    assert rig.written[0][3] == 0xE1
    assert encode_request(RIG, 0x03, frm=pr.STATION_CONTROLLER)[3] == 0xE1


# ------------------------------------------------------------------ vérification du port B

def checked(rig, cat=14_074_000):
    return pr.check(pr.CivPort(rig, RIG, clock=Clock()), lambda: cat, sleep=lambda s: None)


def test_check_passes_and_returns_the_spectrum_settings():
    assert checked(PortB()) == {0x10: 0, 0x11: 0}


@pytest.mark.parametrize("rig, cat, code", [
    (PortB(answers=False), 14_074_000, "no_answer"),            # port B pas en CI-V / mauvais débit
    (PortB(address=0x94), 14_074_000, "wrong_address"),         # adresse CI-V changée dans le menu
    (PortB(scope=False), 14_074_000, "no_scope"),               # poste sans spectre CI-V
    (PortB(freq=7_074_000), 14_074_000, "other_rig"),           # un autre appareil sur ce port
])
def test_check_failures(rig, cat, code):
    with pytest.raises(pr.CheckFailed) as err:
        checked(rig, cat)
    assert err.value.code == code
    text = err.value.message("COM7", RIG)
    assert "COM7" in text and text[0].isupper()


def test_unreadable_cat_frequency_does_not_block_the_check():
    assert checked(PortB(), cat=None) == {0x10: 0, 0x11: 0}


def test_wrong_address_message_names_both_addresses():
    with pytest.raises(pr.CheckFailed) as err:
        checked(PortB(address=0x94))
    assert "94h" in err.value.message("COM7", RIG) and "B6h" in err.value.message("COM7", RIG)


# ------------------------------------------------------------------ configuration

def test_config_civ_port_is_valid_and_leaves_rigctld_unchanged():
    from trxstation.hamlib import rigctld_command
    cfg = cfgmod.from_dict({**ICOM, "spectrum": CIV})
    cmd = rigctld_command(cfg, env={}, which=lambda n: "/usr/bin/" + n, globber=lambda p: [])
    assert not any("async" in a for a in cmd)                    # port A : rigctld exactement comme sans spectre


@pytest.mark.parametrize("spectrum, rig, match", [
    ({"port": ""}, {}, "second port"),
    ({"port": "com8"}, {}, "port CAT ou PTT"),
    ({"port": "COM9"}, {"ptt_port": "COM9"}, "port CAT ou PTT"),
    ({"civ_address": "FE"}, {}, "civ_address"),
    ({"civ_address": ""}, {}, "civ_address"),
    ({"baud": 4800}, {}, "baud"),
    ({}, {"model": 2028}, "Icom seulement"),
    ({"source": "udp"}, {}, "source"),
])
def test_config_civ_port_errors_are_blocking(spectrum, rig, match):
    with pytest.raises(cfgmod.ConfigError, match=match):
        cfgmod.from_dict({"rig": {**ICOM["rig"], **rig}, "spectrum": {**CIV, **spectrum}})


def test_disabled_civ_port_needs_nothing():
    cfgmod.from_dict({**ICOM, "spectrum": {"enabled": False, "source": "civ_port"}})


def test_render_roundtrip():
    import tomllib
    cfg = cfgmod.from_dict({**ICOM, "spectrum": CIV})
    again = cfgmod.from_dict(tomllib.loads(cfgmod.render_toml(cfg)))
    assert (again.spectrum.source, again.spectrum.port, again.spectrum.civ_address) == ("civ_port", "COM7", "B6")


def test_parse_civ_address():
    assert cfgmod.parse_civ_address("b6") == 0xB6 and cfgmod.parse_civ_address("0x94") == 0x94
    assert cfgmod.parse_civ_address("E0") is None and cfgmod.parse_civ_address("zz") is None


# ------------------------------------------------------------------ service de la passerelle

class Ctrl:
    def __init__(self):
        self.state = "RX"
        self.cuts: list[str] = []

    def snapshot(self):
        return SimpleNamespace(state=self.state)

    async def force_rx(self, reason, by=None):
        self.cuts.append(reason)


def make_service(rig=None, *, ptt=False, opener=None, **cfg):
    spectrum = cfgmod.Spectrum(**{**CIV, **cfg})
    link = SimpleNamespace(state=SimpleNamespace(connected=True, ptt=ptt, frequency_hz=14_074_000))
    ctrl = Ctrl()
    opened = []

    def default_opener(port, baud):
        opened.append((port, baud))
        return rig
    svc = SpectrumService(spectrum, link, ctrl, opener=opener or default_opener)
    svc.PTT_SETTLE_S, svc.RETRY_S, svc.SILENT_S, svc.READY_POLL_S = 0.2, 0.2, 0.6, 0.02
    return svc, link, ctrl, opened


async def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


def test_inactive_unless_civ_port():
    svc = SpectrumService(cfgmod.Spectrum(), SimpleNamespace(), Ctrl())
    assert svc.snapshot() == {"state": "off", "code": "", "message": "", "settings": {}}
    asyncio.run(svc.start())
    assert svc._thread is None


def test_service_reads_the_spectrum_then_restores_the_rig_settings():
    rig = PortB()

    async def scenario():
        svc, _, ctrl, opened = make_service(rig)
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["state"] == "ok")
        assert await wait_for(lambda: svc.sweeps >= 3)
        stats = svc.stats()
        await svc.stop()
        return svc, ctrl, opened, stats
    svc, ctrl, opened, stats = asyncio.run(scenario())
    assert opened == [("COM7", 115200)] and stats["port"] == "COM7" and stats["points"] == 475
    assert rig.settings == {0x10: 0, 0x11: 0} and rig.closed                  # poste remis comme au départ
    assert ctrl.cuts == []


def test_port_b_is_never_opened_outside_confirmed_reception():
    rig = PortB()

    async def scenario():
        svc, link, ctrl, opened = make_service(rig)
        ctrl.state = "TX"
        await svc.start()
        await asyncio.sleep(0.3)
        assert opened == [] and svc.snapshot()["state"] == "waiting"
        ctrl.state, link.state.ptt = "RX", None                            # PTT illisible : toujours pas
        await asyncio.sleep(0.3)
        assert opened == []
        link.state.ptt = False
        assert await wait_for(lambda: svc.snapshot()["state"] == "ok")
        await svc.stop()
    asyncio.run(scenario())


def test_opening_port_b_that_keys_the_rig_cuts_and_disables_until_restart():
    rig = PortB()

    async def scenario():
        svc, link, ctrl, opened = make_service(None)

        def keying_opener(port, baud):
            opened.append(port)
            link.state.ptt = True                                          # « USB SEND » réglé sur ce port
            return rig
        svc.opener = keying_opener
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["state"] == "error")
        assert await wait_for(lambda: ctrl.cuts == ["spectrum_port_keyed"])
        link.state.ptt = False
        await asyncio.sleep(0.6)                                           # bien plus que RETRY_S : jamais rouvert
        snap = svc.snapshot()
        await svc.stop()
        return snap, opened
    snap, opened = asyncio.run(scenario())
    assert snap["code"] == "ptt_on_open" and "ÉMISSION" in snap["message"] and "Mode normal" in snap["message"]
    assert opened == ["COM7"] and rig.closed


def test_misconfigured_port_falls_back_to_normal_mode_with_a_message():
    rig = PortB(answers=False)

    async def scenario():
        svc, _, ctrl, _ = make_service(rig)
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["state"] == "error")
        snap = svc.snapshot()
        await svc.stop()
        return snap, ctrl
    snap, ctrl = asyncio.run(scenario())
    assert snap["code"] == "no_answer" and "CI-V" in snap["message"] and "sans waterfall HF" in snap["message"]
    assert ctrl.cuts == [] and rig.closed


def test_open_failure_is_reported_and_retried():
    calls = []

    def failing(port, baud):
        calls.append(port)
        raise OSError("could not open port 'COM7'")

    async def scenario():
        svc, *_ = make_service(None, opener=failing)
        await svc.start()
        assert await wait_for(lambda: len(calls) >= 2)                    # nouvel essai après RETRY_S
        snap = svc.snapshot()
        await svc.stop()
        return snap
    snap = asyncio.run(scenario())
    assert snap["state"] == "error" and snap["code"] == "open_failed" and "COM7" in snap["message"]


def test_spectrum_stopping_on_the_rig_is_detected_and_recovered():
    rig = PortB()

    async def scenario():
        svc, *_ = make_service(rig)
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["state"] == "ok")
        rig.mute = True                                                    # réglage changé sur le poste
        assert await wait_for(lambda: svc.snapshot()["state"] == "error")
        code = svc.snapshot()["code"]
        rig.mute = False                                                   # remis en ordre : le spectre revient seul
        assert await wait_for(lambda: svc.snapshot()["state"] == "ok")
        await svc.stop()
        return code
    assert asyncio.run(scenario()) == "silent"


def test_missing_pyserial_is_permanent():
    def no_serial(port, baud):
        raise ImportError("serial")

    async def scenario():
        svc, *_ = make_service(None, opener=no_serial)
        await svc.start()
        assert await wait_for(lambda: svc.snapshot()["state"] == "error")
        await asyncio.sleep(0.1)
        alive = svc._thread.is_alive()
        await svc.stop()
        return svc.snapshot(), alive
    snap, alive = asyncio.run(scenario())
    assert snap["code"] == "no_pyserial" and not alive


def test_state_message_for_clients_and_status_file():
    from trxstation.gateway.api.session import build_state
    from trxstation.status import GatewayStatus, read_status, write_status
    svc, link, ctrl, _ = make_service(PortB())
    svc._set("error", "no_answer", "Aucune réponse CI-V sur COM7. Mode normal : un seul port, sans waterfall HF.")
    link.state = SimpleNamespace(connected=True, frequency_hz=1, mode="USB", passband_hz=1, strength_db=0,
                                 functions={}, levels={}, ptt=False)
    ctrl.snapshot = lambda: SimpleNamespace(state="RX", owner=None, tot_remaining_s=None, tot_warning=False,
                                            last_cut_reason="", fault="")
    ctrl.clients = []
    assert build_state(link, ctrl, None, svc)["spectrum"]["code"] == "no_answer"
    assert build_state(link, ctrl)["spectrum"]["state"] == "off"


def test_status_file_keeps_the_spectrum(tmp_path):
    from trxstation.status import GatewayStatus, read_status, write_status
    path = tmp_path / "status.json"
    write_status(path, GatewayStatus(pid=1, seq=1, written_at=0.0, ptt={"state": "RX"}, rig={},
                                     spectrum={"state": "error", "code": "silent", "message": "x"}))
    assert read_status(path).spectrum["code"] == "silent"


# ------------------------------------------------------------------ assistant (trx-setup --spectre)

class FakeRigctldSocket:
    """rigctld simulé (protocole étendu) : `keyed` passe le PTT à 1 dès que le port B est ouvert."""

    def __init__(self, world):
        self.world, self.out, self.sent = world, b"", []

    def settimeout(self, t):
        pass

    def sendall(self, data: bytes):
        cmd = data.decode().strip().lstrip("+")
        self.sent.append(cmd)
        if cmd == "t":
            self.out += f"get_ptt:\nPTT: {1 if self.world['ptt'] else 0}\nRPRT 0\n".encode()
        elif cmd == "f":
            self.out += f"get_freq:\nFrequency: {self.world['freq']}\nRPRT 0\n".encode()
        elif cmd == "T 0":
            self.world["ptt"] = False
            self.out += b"set_ptt: 0\nRPRT 0\n"
        else:
            raise AssertionError(f"commande interdite : {cmd}")

    def recv(self, n):
        data, self.out = self.out, b""
        return data


def setup_world(rig, *, keyed=False, freq=14_074_000):
    import contextlib
    world = {"ptt": False, "freq": freq}
    sock = FakeRigctldSocket(world)

    @contextlib.contextmanager
    def link():
        yield sock

    def opener(port, baud):
        if keyed:
            world["ptt"] = True
        return rig
    return world, sock, link, opener


def setup_cfg(**rig):
    return cfgmod.from_dict({"rig": {**ICOM["rig"], **rig}})


def test_setup_check_finds_the_address_and_never_transmits():
    from trxstation import setup_wizard as sw
    rig = PortB()
    _, sock, link, opener = setup_world(rig)
    address = sw.check_spectrum_port(setup_cfg(), "COM7", opener=opener, link=link, settle_s=0, say=lambda m: None)
    assert address == RIG and rig.closed
    assert set(sock.sent) <= {"t", "f"}                                   # lecture seule : aucun ordre au poste
    cfg = setup_cfg()
    sw.apply_spectrum(cfg, "COM7", address)
    assert cfgmod.validate(cfg) == [] and (cfg.spectrum.source, cfg.spectrum.civ_address) == ("civ_port", "B6")


def test_setup_check_cuts_and_refuses_when_opening_keys_the_rig():
    from trxstation import setup_wizard as sw
    rig = PortB()
    world, sock, link, opener = setup_world(rig, keyed=True)
    with pytest.raises(sw.SetupError, match="DANGER"):
        sw.check_spectrum_port(setup_cfg(), "COM7", opener=opener, link=link, settle_s=0, say=lambda m: None)
    assert "T 0" in sock.sent and world["ptt"] is False and rig.closed


@pytest.mark.parametrize("rig, freq, match", [
    (PortB(answers=False), 14_074_000, "(?i)aucune réponse CI-V"),
    (PortB(scope=False), 14_074_000, "spectre"),
    (PortB(freq=7_000_000), 14_074_000, "pas le même poste"),
])
def test_setup_check_reports_configuration_problems(rig, freq, match):
    from trxstation import setup_wizard as sw
    _, _, link, opener = setup_world(rig, freq=freq)
    with pytest.raises(sw.SetupError, match=match):
        sw.check_spectrum_port(setup_cfg(), "COM7", 0xB6 if not rig.answers else None, opener=opener, link=link,
                               settle_s=0, say=lambda m: None)


def test_setup_check_refuses_cat_port_and_non_icom():
    from trxstation import setup_wizard as sw
    with pytest.raises(sw.SetupError, match="SECOND port"):
        sw.check_spectrum_port(setup_cfg(), "com8", link=lambda: None)
    with pytest.raises(sw.SetupError, match="Icom"):
        sw.check_spectrum_port(setup_cfg(model=2028), "COM7", link=lambda: None)


def test_setup_cli_off_and_refusal_without_oui(tmp_path, monkeypatch, capsys):
    from trxstation import setup_wizard as sw
    out = tmp_path / "station.toml"
    cfg = cfgmod.from_dict({**ICOM, "spectrum": CIV})
    out.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt: "non")
    monkeypatch.setattr(sw, "check_spectrum_port", lambda *a, **k: pytest.fail("port B ouvert sans accord"))
    assert sw.main(["--output", str(out), "--spectre", "COM7"]) == 2
    assert sw.main(["--output", str(out), "--spectre", "off"]) == 0
    assert cfgmod.load(out).spectrum.enabled is False
    assert "mode normal" not in capsys.readouterr().err


# ------------------------------------------------------------------ diagnostic (TRX Console)

@pytest.mark.parametrize("published, level, text", [
    (None, "INFO", "passerelle arrêtée"),
    ({"state": "ok", "fps": 4.1}, "OK", "4.1 balayages/s"),
    ({"state": "error", "code": "no_answer", "message": "Aucune réponse CI-V sur COM7. Mode normal : un seul port, "
      "sans waterfall HF."}, "FAIL", "PROBLÈME DE CONFIGURATION"),
    ({"state": "waiting"}, "INFO", "réception confirmée"),
])
def test_diagnostic_reports_the_published_spectrum_state(tmp_path, published, level, text):
    import json
    from trxstation import diagnostics as d
    from test_diagnostics import FakeSystem
    cfg = cfgmod.from_dict({**ICOM, "spectrum": CIV, "supervisor": {"status_path": "/run/trx-remote/status.json"}})
    sysm = FakeSystem(tmp_path)
    if published is not None:
        sysm.files["/run/trx-remote/status.json"] = json.dumps({"spectrum": published})
    (check,) = d.check_spectrum(sysm, cfg)
    assert check.status == getattr(d, level) and text in check.message
    if level == "FAIL":
        assert "trx-setup --spectre COM7" in check.fix
    assert d.check_spectrum(sysm, cfgmod.from_dict(ICOM)) == []


# ------------------------------------------------------------------ trx-monitor

def test_monitor_shows_a_spectrum_problem():
    from trxstation.monitor.model import Snapshot, SystemInfo, build_panels
    from trxstation.status import GatewayStatus

    def rows(spectrum):
        st = GatewayStatus(pid=1, seq=1, written_at=0.0, ptt={"state": "RX"}, rig={}, spectrum=spectrum)
        panels = build_panels(Snapshot(status=st, gateway_fresh=True, stale_s=0.1, safe_mode=None, system=SystemInfo()))
        return [r for p in panels for r in p.rows if r.label == "Spectre HF"]
    assert rows({}) == [] and rows({"state": "off"}) == []
    (row,) = rows({"state": "error", "message": "Aucune réponse CI-V sur COM7."})
    assert row.level == "bad" and "PROBLÈME DE CONFIGURATION" in row.text
    (row,) = rows({"state": "ok", "port": "COM7", "fps": 4.1})
    assert row.level == "ok" and "COM7" in row.text


# ------------------------------------------------------------------ étape 4 : trames et diffusion aux clients

def sweep(mode=1, f1=14_000_000, f2=14_200_000, points=(0, 80, 200), out=False):
    from trxstation.spectrum.civ import Sweep
    return Sweep(t=0.0, mode=mode, f1_hz=f1, f2_hz=f2, out_of_range=out, points=list(points))


def test_frame_encoding_and_edges():
    import struct
    from trxstation.spectrum import frame as fr
    raw = fr.encode(sweep(out=True), 7)
    version, mode, flags, _, seq, low, high = struct.unpack("<BBBBIII", raw[:16])
    assert (version, mode, flags, seq, low, high) == (1, 1, 1, 7, 14_000_000, 14_200_000)
    assert list(raw[16:]) == [0, 80, 160]                                     # bornées à LEVEL_MAX
    assert fr.edges(sweep(mode=0, f1=14_074_000, f2=25_000)) == (14_049_000, 14_099_000)   # centre ± demi-largeur
    assert fr.encode(sweep(f1=None), 1) is None and fr.encode(sweep(points=()), 1) is None
    assert fr.encode(sweep(mode=None), 1)[1] == 255


def test_fanout_rate_limit_backpressure_and_failures():
    from trxstation.spectrum.frame import MAX_BUFFERED, SpectrumFanout
    now = [0.0]
    fan = SpectrumFanout(max_fps=4, clock=lambda: now[0])
    got = {"a": [], "b": [], "c": []}
    buffered = {"b": MAX_BUFFERED + 1}
    fan.add("a", got["a"].append, lambda: 0)
    fan.add("b", got["b"].append, lambda: buffered["b"])
    send_c = lambda f: (_ for _ in ()).throw(ConnectionError("fermé"))      # noqa: E731
    fan.add("c", send_c, lambda: 0)
    for client in got:
        fan.watch(client, True)
    assert fan.publish(sweep()) == 1                                         # b engorgé, c en panne
    assert len(got["a"]) == 1 and got["b"] == [] and len(fan) == 2          # c désabonné, b gardé
    now[0] = 0.1
    fan.publish(sweep())
    assert len(got["a"]) == 1                                                # 4/s au plus
    now[0], buffered["b"] = 0.3, 0
    fan.publish(sweep())
    assert len(got["a"]) == 2 and len(got["b"]) == 1
    seqs = [int.from_bytes(f[4:8], "little") for f in got["a"]]
    assert seqs == sorted(seqs) and seqs[0] < seqs[1]


def test_fanout_sends_only_while_the_hf_view_is_shown():
    from trxstation.spectrum.frame import SpectrumFanout
    now = [0.0]
    fan = SpectrumFanout(10, clock=lambda: now[0])
    got = []
    fan.add("phone", got.append, lambda: 0)
    assert fan.publish(sweep()) == 0 and got == [] and fan.seq == 0         # canal ouvert, vue fermée : rien
    fan.watch("phone", True)
    assert fan.publish(sweep()) == 1 and len(got) == 1
    fan.watch("phone", False)
    now[0] = 1.0
    assert fan.publish(sweep()) == 0 and len(got) == 1
    fan.watch("tablet", True)                                                # demande avant l'ouverture du canal
    fan.add("tablet", got.append, lambda: 0)
    assert fan.publish(sweep()) == 1
    fan.remove("tablet", got.append)                                         # canal fermé : la demande reste
    assert fan.watching("tablet")
    fan.remove("tablet")                                                     # client parti : demande oubliée
    assert not fan.watching("tablet")


def test_fanout_late_close_of_an_old_connection_keeps_the_new_one():
    from trxstation.spectrum.frame import SpectrumFanout
    fan = SpectrumFanout(10, clock=lambda: 0.0)
    old, new = (lambda f: None), (lambda f: None)
    fan.add("phone", old, lambda: 0)
    fan.add("phone", new, lambda: 0)                                         # reconnexion
    fan.remove("phone", old)                                                 # fermeture tardive de l'ancien canal
    assert len(fan) == 1
    fan.remove("phone", new)
    assert len(fan) == 0


def test_service_delivers_sweeps_to_listeners_in_the_event_loop():
    rig = PortB()

    async def scenario():
        svc, *_ = make_service(rig)
        loop_thread, got = [], []

        def listener(s):
            import threading
            loop_thread.append(threading.current_thread() is threading.main_thread())
            got.append(s)
        svc.add_listener(listener)
        svc.add_listener(lambda s: 1 / 0)                                    # un écouteur fautif ne gêne pas les autres
        await svc.start()
        assert await wait_for(lambda: len(got) >= 3)
        await svc.stop()
        return loop_thread, svc.capability()
    in_loop, capability = asyncio.run(scenario())
    assert all(in_loop)                                                      # jamais dans le fil de lecture série
    assert capability == {"source": "civ_port", "level_max": 160, "max_fps": 10}
    assert SpectrumService(cfgmod.Spectrum(), None, None).capability() is None


def test_diagnostic_fails_when_pyserial_is_missing_and_the_spectrum_is_enabled(tmp_path):
    from trxstation import diagnostics as d
    from test_diagnostics import FakeSystem
    cfg = cfgmod.from_dict({**ICOM, "spectrum": CIV})
    sysm = FakeSystem(tmp_path)
    sysm.modules.discard("serial")
    (check,) = d.check_spectrum(sysm, cfg)
    assert check.status == d.FAIL and "pyserial" in check.message

