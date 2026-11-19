# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Allumage et extinction du poste à distance (docs/alimentation-poste-cahier-des-charges.md, lot P1) : liaison CAT,
refus, ordres, tests de panne (allumage en émission, poste muet, ports), extinction automatique, superviseur,
protocole. Faux rigctld seulement, jamais un vrai poste."""
import asyncio
import contextlib
import pathlib

import pytest

from trxstation import config as cfgmod
from trxstation import usbports
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.errors import codes
from trxstation.gateway.api.access import LISTENER_COMMANDS
from trxstation.gateway.api.protocol import OPTIONAL_FEATURES, ProtocolError, parse_command
from trxstation.gateway.cat import CatLink
from trxstation.gateway.cat.capabilities import Capabilities, parse_dump_caps
from trxstation.gateway.power import PowerControl, PowerError
from trxstation.gateway.safety import PttController, PttLimits, Refused
from trxstation.setup_wizard import dummy_config
from trxstation.status import GatewayStatus
from trxstation.supervisor.core import Supervisor
from trxstation.supervisor.rigctl import RigProbe
from trxstation.supervisor.state import StateStore

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(scenario, timeout=25):
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        try:
            await asyncio.wait_for(scenario(fake), timeout)
        finally:
            await fake.stop()
    asyncio.run(wrapper())


async def until(predicate, timeout=4.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("condition jamais atteinte")
        await asyncio.sleep(0.01)


def limits():
    return PttLimits(tot_s=5.0, warn_before_s=1.0, heartbeat_timeout_s=1.0, tick_s=0.02, rig_poll_s=5.0,
                     rekey_cooldown_s=0.0, unkey_retry_s=0.05, unkey_deadline_s=0.5)


def power_cfg(**power):
    cfg = dummy_config()
    cfg.power.enabled = True
    for key, value in power.items():
        setattr(cfg.power, key, value)
    return cfg


def caps(power=True):
    return Capabilities(can_set_power=power, can_get_power=power)


async def fast_sleep(_s):
    await asyncio.sleep(0.01)


@contextlib.asynccontextmanager
async def station(fake, cfg=None, *, wait_rx=True, alerts=None, **power_kw):
    cfg = cfg or power_cfg()
    link = CatLink("127.0.0.1", fake.port, capabilities=caps(), poll_fast_s=0.02, slow_every=2,
                   backoff_min_s=0.05, backoff_max_s=0.2, timeout=0.5)
    ctrl = PttController(link, cfg, limits=limits())
    sent = alerts if alerts is not None else []
    power = PowerControl(cfg, link, ctrl, alert=lambda code, detail="": sent.append((code, detail)),
                         sleep=fast_sleep, **power_kw)
    task = asyncio.create_task(link.run())
    await ctrl.start()
    ctrl.connect_client("phone")
    if wait_rx:
        await until(lambda: link.state.connected and not ctrl.starting)
    try:
        yield ctrl, link, power
    finally:
        await asyncio.wait_for(ctrl.close(), 5)
        link.stop()
        await asyncio.wait_for(task, 3)


def powerstat_orders(fake) -> list[int]:
    return [int(c.split()[-1]) for c in fake.commands if c.lstrip("+").startswith("\\set_powerstat")]   # protocole réseau


async def refusal(coro):
    try:
        await coro
    except Refused as exc:
        return exc.reason
    raise AssertionError("un refus était attendu")


# --------------------------------------------------------------------------- liaison CAT

def test_switched_off_rig_is_seen_and_only_its_power_is_read():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, power):
            await until(lambda: link.state.power == "on")
            fake.powered = 0
            await until(lambda: link.state.power == "off")
            assert link.state.frequency_hz is None and link.state.ptt is None and link.state.connected
            before = fake.count("f")
            await asyncio.sleep(0.4)
            assert fake.count("f") == before                       # éteint : plus aucune lecture du poste
            assert not link._disabled                               # rien d'abandonné à cause du poste éteint
    run(scenario)


def test_rig_switched_on_by_hand_is_read_again():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, power):
            fake.powered = 0
            await until(lambda: link.state.power == "off")
            fake.powered = 1
            await until(lambda: link.state.power == "on" and link.state.frequency_hz == fake.freq, timeout=8)
    run(scenario, timeout=30)


def test_capabilities_read_power_stat_from_dump_caps():
    text = (ROOT / "tests" / "data" / "dump_caps_ic7300mk2_hamlib472.txt").read_text(encoding="utf-8")
    parsed = parse_dump_caps(text, 3094)
    assert parsed.can_set_power and parsed.can_get_power
    assert parse_dump_caps("Model name: X\nMode list: USB\n").can_set_power is False


# --------------------------------------------------------------------------- refus

def test_switched_off_rig_refuses_transmission_and_settings():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, power):
            fake.powered = 0
            await until(lambda: link.state.power == "off")
            assert await refusal(ctrl.toggle("phone")) in ("rig_off", "cat_down")
            assert await refusal(ctrl.set_frequency(7_074_000)) == "rig_off"
            assert fake.ptt_commands.count(1) == 0
    run(scenario)


def test_power_refused_when_switched_off_in_station_toml_or_not_declared():
    async def scenario(fake):
        cfg = dummy_config()                                         # [power] enabled = false par défaut
        async with station(fake, cfg) as (ctrl, link, power):
            assert power.unavailable_reason() == "power_disabled"
            assert await refusal(power.power_off("phone")) == "power_disabled"
            with pytest.raises(Refused):
                power.power_on("phone")
            link.capabilities = caps(False)
            cfg.power.enabled = True
            assert power.unavailable_reason() == "power_unsupported"
            assert powerstat_orders(fake) == []
    run(scenario)


def test_power_off_refused_while_transmitting_and_no_order_sent():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, power):
            await ctrl.toggle("phone")
            assert ctrl.snapshot().state == "TX"
            assert await refusal(power.power_off("phone")) == "tx_active"
            await ctrl.force_rx("stop")
            assert powerstat_orders(fake) == [] and fake.powered == 1
    run(scenario)


def test_power_off_refused_when_the_rig_is_used_at_the_shack():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, power):
            ctrl.local.active = lambda: True
            ctrl.local.remaining = lambda: 80.0
            assert await refusal(power.power_off("phone")) == "local_active"
            assert powerstat_orders(fake) == []
    run(scenario)


# --------------------------------------------------------------------------- extinction et allumage

def test_power_off_then_on_with_progress_steps():
    async def scenario(fake):
        alerts = []
        async with station(fake, power_cfg(notify=True), alerts=alerts) as (ctrl, link, power):
            result = await power.power_off("phone")
            assert fake.powered == 0 and link.state.power == "off" and result["power"]["last"] == "off"
            steps = []
            outcome = await power.power_on("phone", progress=steps.append)
            assert outcome["result"] == "on" and fake.powered == 1 and link.state.power == "on"
            done = [s["step"] for s in steps if s["status"] == "ok"]
            assert done == ["ports", "check_off", "order", "wait", "readback", "done"]
            assert powerstat_orders(fake) == [0, 1]
            assert power.snapshot()["last"] == "on" and not power.busy
            assert [code for code, _ in alerts] == [codes.ORT_2801, codes.ORT_2802]   # [power] notify
            await until(lambda: link.state.frequency_hz == fake.freq)
    run(scenario)


def test_rig_switched_on_while_transmitting_is_put_back_to_receive_and_alerts():
    async def scenario(fake):
        alerts = []
        async with station(fake, alerts=alerts) as (ctrl, link, power):
            await power.power_off("phone")
            fake.ptt_at_boot = 1                                   # ligne RTS active au démarrage du poste
            with pytest.raises(PowerError) as err:
                await power.power_on("phone")
            assert err.value.reason == "power_on_tx" and err.value.ort == codes.ORT_2808
            assert fake.ptt == 0 and fake.ptt_commands[-1] == 0
            assert (codes.ORT_2808 in [code for code, _ in alerts])  # même sans [power] notify
    run(scenario)


def test_no_transmission_possible_while_the_rig_starts():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, power):
            await power.power_off("phone")
            fake.boot_s = 0.6
            task = power.power_on("phone")
            await asyncio.sleep(0.1)
            assert power.busy and power.snapshot()["state"] == "starting"
            assert await refusal(ctrl.toggle("phone")) == "power_busy"
            assert await refusal(ctrl.set_mode("LSB")) == "power_busy"
            await task
            assert fake.ptt_commands.count(1) == 0
    run(scenario)


def test_rig_that_does_not_start_gives_an_explicit_error():
    async def scenario(fake):
        async with station(fake, power_cfg(on_timeout_s=1)) as (ctrl, link, power):
            await power.power_off("phone")
            fake.boot_s = 30
            steps = []
            with pytest.raises(PowerError) as err:
                await power.power_on("phone", progress=steps.append)
            assert err.value.reason == "power_on_timeout" and "1 s" in err.value.detail
            assert steps[-1]["status"] == "error" and steps[-1]["step"] == "wait" and steps[-1]["ort"] == codes.ORT_2803
            assert not power.busy and not link.paused
    run(scenario)


def test_closing_the_connection_does_not_interrupt_the_switch_on():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, power):
            await power.power_off("phone")
            fake.boot_s = 0.3
            task = power.power_on("phone")
            waiter = asyncio.ensure_future(asyncio.shield(task))
            await asyncio.sleep(0.05)
            waiter.cancel()                                      # la session du client se ferme
            await task
            assert fake.powered == 1 and link.state.power == "on"
    run(scenario)


def test_station_started_with_the_rig_off_can_switch_it_on_and_then_confirms_rx():
    async def scenario(fake):
        fake.powered = 0
        async with station(fake, wait_rx=False) as (ctrl, link, power):
            await until(lambda: link.state.power == "off")
            assert ctrl.starting                                  # « T 0 » ne passe pas : aucune émission permise
            await power.power_on("phone")
            await until(lambda: not ctrl.starting, timeout=6)      # RX de démarrage confirmé après l'allumage
    run(scenario, timeout=30)


# --------------------------------------------------------------------------- ports

def test_ports_are_checked_before_any_order():
    async def scenario(fake):
        cfg = power_cfg()
        cfg.rig.port, cfg.rig.port_usb = "COM6", "10C4:EA70 SN=01D0F21E IF=00"
        here = {"COM6": usbports.UsbIdentity("10C4", "EA70", "01D0F21E", "00")}
        present = {"COM6"}
        async with station(fake, cfg, port_present=lambda p: p in present, identity=lambda p: here.get(p),
                           list_ports=lambda: sorted(present)) as (ctrl, link, power):
            await power.power_off("phone")
            present.clear()                                         # câble débranché
            with pytest.raises(PowerError) as err:
                await power.power_on("phone")
            assert err.value.reason == "port_missing" and "COM6" in err.value.detail
            present.update({"COM6", "COM7"})                         # poste sur une autre prise : COM7
            here["COM7"], here["COM6"] = here["COM6"], usbports.UsbIdentity("067B", "2303")
            with pytest.raises(PowerError) as err:
                await power.power_on("phone")
            assert err.value.reason == "port_moved" and "COM7" in err.value.detail and err.value.ort == codes.ORT_2809
            del here["COM7"]
            present.discard("COM7")
            with pytest.raises(PowerError) as err:
                await power.power_on("phone")
            assert err.value.reason == "port_mismatch"
            assert powerstat_orders(fake) == [0]                     # aucun ordre d'allumage
    run(scenario)


def test_usb_identity_from_the_windows_registry_and_linux_sysfs(tmp_path):
    entries = [("VID_10C4&PID_EA70", "01D0F21E", "", "7&1933a3de&0"),
               ("VID_10C4&PID_EA70&MI_00", "7&1933a3de&0&0000", "COM6", ""),
               ("VID_10C4&PID_EA70&MI_01", "7&1933a3de&0&0001", "COM9", ""),
               ("VID_08BB&PID_29C3&MI_00", "7&2d153f98&0&0000", "", "")]
    ident = usbports.identity("COM6", "win32", registry=lambda: entries)
    assert str(ident) == "10C4:EA70 SN=01D0F21E IF=00"
    assert str(usbports.identity("COM9", "win32", registry=lambda: entries)) == "10C4:EA70 SN=01D0F21E IF=01"
    assert usbports.identity("COM3", "win32", registry=lambda: entries) is None
    expected = usbports.parse_identity("10C4:EA70 SN=01D0F21E IF=00")
    assert usbports.locate(expected, ["COM6", "COM9"], "win32", registry=lambda: entries) == ["COM6"]


def test_usb_identity_from_linux_sysfs(tmp_path):
    # /dev/serial/by-id/… -> /dev/ttyUSB0 ; /sys/class/tty/ttyUSB0/device -> interface 00 d'un périphérique USB
    # (vrai sysfs : « 1-2:1.0 » ; le « : » est interdit sous Windows, le code ne dépend pas du nom)
    dev = tmp_path / "devices" / "usb1" / "1-2"
    iface = dev / "1-2_1.0"
    (iface / "ttyUSB0").mkdir(parents=True)
    (dev / "idVendor").write_text("10c4\n")
    (dev / "idProduct").write_text("ea70\n")
    (dev / "serial").write_text("01D0F21E\n")
    (iface / "bInterfaceNumber").write_text("00\n")
    tty = tmp_path / "class" / "tty" / "ttyUSB0"
    tty.mkdir(parents=True)
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev" / "ttyUSB0").write_text("")
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    try:
        (tty / "device").symlink_to(iface / "ttyUSB0", target_is_directory=True)
        (by_id / "usb-Silicon_Labs_CP2105-if00-port0").symlink_to(tmp_path / "dev" / "ttyUSB0")
    except OSError:
        pytest.skip("liens symboliques indisponibles (Windows sans le mode développeur)")
    found = usbports._linux_identity(str(by_id / "usb-Silicon_Labs_CP2105-if00-port0"), tmp_path)
    assert str(found) == "10C4:EA70 SN=01D0F21E IF=00"


def test_serial_with_a_space_is_kept_readable():
    # IC-7300MK2 sous Linux : sysfs donne « IC-7300MK2 13003336 » (relevé sur minix-bzh le 2026-11-19)
    assert usbports._clean_serial("IC-7300MK2 13003336") == "IC-7300MK2_13003336"
    ident = usbports.UsbIdentity("0C26", "0052", usbports._clean_serial("IC-7300MK2 13003336"), "00")
    assert usbports.parse_identity(str(ident)) == ident
    assert usbports._clean_serial("7&1933a3de&0") == ""           # identifiant fabriqué par Windows : pas un numéro


def test_partial_identity_never_designates_a_port():
    partial = usbports.UsbIdentity("10C4", "EA60")
    assert usbports.locate(partial, ["COM6"], "win32", registry=lambda: []) == []
    assert usbports.same_device(partial, usbports.UsbIdentity("10C4", "EA60", "X"))
    assert not usbports.same_device(usbports.UsbIdentity("10C4", "EA70", "A", "00"),
                                    usbports.UsbIdentity("10C4", "EA70", "A", "01"))


# --------------------------------------------------------------------------- extinction automatique

def test_idle_switch_off_after_the_delay_without_connections_only():
    async def scenario(fake):
        now = [1000.0]
        cfg = power_cfg(idle_off=True, idle_off_hours=2)
        async with station(fake, cfg, clock=lambda: now[0]) as (ctrl, link, power):
            await until(lambda: link.state.power == "on")
            power.touch()
            now[0] += 2 * 3600 - 10
            assert not await power.idle_tick(lambda: 0)
            assert await power.idle_tick(lambda: 1) is False        # une connexion remet le compteur à zéro
            now[0] += 2 * 3600 - 10
            assert not await power.idle_tick(lambda: 0, lambda: "diffusion")
            now[0] += 2 * 3600 + 1
            assert await power.idle_tick(lambda: 0)
            assert fake.powered == 0 and power.snapshot()["how"] == "idle"
    run(scenario)


def test_idle_switch_off_is_postponed_never_forced():
    async def scenario(fake):
        now = [1000.0]
        async with station(fake, power_cfg(idle_off=True, idle_off_hours=1), clock=lambda: now[0]) as (ctrl, link, power):
            await until(lambda: link.state.power == "on")
            now[0] += 3601
            original = power.power_off

            async def refused(by, how="stop_hold"):
                raise Refused("tx_active", "émission")
            power.power_off = refused
            assert not await power.idle_tick(lambda: 0)
            now[0] += 60
            assert not await power.idle_tick(lambda: 0)               # report : pas de nouvel essai avant 10 min
            power.power_off = original
            now[0] += 600
            assert await power.idle_tick(lambda: 0)
    run(scenario)


# --------------------------------------------------------------------------- superviseur

class _Actions:
    def __init__(self):
        self.calls, self.alerts = [], []

    def __getattr__(self, name):
        if name in ("force_rx", "kill_gateway", "restart_gateway", "stop_gateway", "restart_rigctld", "reset_usb", "reboot"):
            return lambda: self.calls.append(name) or True
        raise AttributeError(name)

    def notify(self, code, detail="", key=""):
        self.alerts.append(key or code)


def _supervisor(tmp_path, rig_power, last="", probe_ok=False):
    cfg = dummy_config()
    cfg.supervisor.startup_grace_s = 0.0
    clock = [1000.0]
    seq = [0]
    actions = _Actions()

    def status():
        seq[0] += 1
        return GatewayStatus(pid=1, seq=seq[0], written_at=0.0, ptt={"state": "RX", "owner": None, "fault": ""},
                             rig={"connected": True, "power": rig_power}, clients=[],
                             power={"state": rig_power, "last": last})
    probe = RigProbe(True, False, 14_200_000) if probe_ok else RigProbe(False, error="délai dépassé")
    sup = Supervisor(cfg, read_status=status, probe_rig=lambda: probe, actions=actions, store=StateStore(tmp_path),
                     clock=lambda: clock[0], wall=lambda: clock[0], port_exists=lambda p: True, read_temp=lambda: None)
    reports = []
    for _ in range(200):                                     # 50 s
        clock[0] += 0.25
        reports.append(sup.step())
    return actions, reports


def test_supervisor_leaves_a_rig_switched_off_on_purpose_alone(tmp_path):
    actions, reports = _supervisor(tmp_path, "off", last="off")
    assert actions.calls == [] and not any(r.problems for r in reports)


def test_supervisor_alerts_once_when_the_rig_is_off_without_a_station_command(tmp_path):
    actions, reports = _supervisor(tmp_path, "off", last="")
    assert actions.calls == []                               # jamais de relance pour un poste éteint
    assert actions.alerts.count("rig_off_unexpected") == 1
    assert codes.ORT_2804 == "ORT-2804"


def test_supervisor_still_restarts_rigctld_when_the_rig_is_on(tmp_path):
    actions, _ = _supervisor(tmp_path, "on")
    assert "restart_rigctld" in actions.calls


# --------------------------------------------------------------------------- protocole, réglages, structure

def test_protocol_power_commands():
    assert parse_command('{"cmd":"power_off","confirm":true}').name == "power_off"
    with pytest.raises(ProtocolError):
        parse_command('{"cmd":"power_off"}')
    with pytest.raises(ProtocolError):
        parse_command('{"cmd":"power_off","confirm":"oui"}')
    assert parse_command('{"cmd":"power_on","how":"connect"}').params == {"how": "connect"}
    assert parse_command('{"cmd":"power_on"}').params == {"how": "button"}
    with pytest.raises(ProtocolError):
        parse_command('{"cmd":"power_on","how":"auto"}')
    assert "power" in OPTIONAL_FEATURES
    assert "power_on" not in LISTENER_COMMANDS and "power_off" not in LISTENER_COMMANDS   # jamais un visiteur


def test_power_settings_are_validated_and_written():
    cfg = dummy_config()
    assert cfg.power.enabled is False and cfg.power.idle_off is False and cfg.power.notify is False
    cfg.power.idle_off_hours = 0
    cfg.rig.port_usb = "COM6"
    problems = cfgmod.validate(cfg)
    assert any("idle_off_hours" in p for p in problems) and any("port_usb" in p for p in problems)
    cfg = dummy_config()
    cfg.power.enabled, cfg.rig.port_usb = True, "10C4:EA70 SN=01D0F21E IF=00"
    assert cfgmod.validate(cfg) == []
    import tomllib
    again = cfgmod.from_dict(tomllib.loads(cfgmod.render_toml(cfg)))
    assert again.power.enabled is True and again.rig.port_usb == "10C4:EA70 SN=01D0F21E IF=00"


# --------------------------------------------------------------------------- essai du menu 2.8 (power_trial)

class _FakeRig:
    """Poste vu par `rigctl` d'une commande : allumé, en réception ; `ptt_at_boot` = se rallume en émission."""

    def __init__(self, ptt_at_boot=False, starts=True):
        self.on, self.ptt, self.ptt_at_boot, self.starts = True, 0, ptt_at_boot, starts
        self.commands: list[list[str]] = []

    def __call__(self, cmd, capture_output=True, timeout=None):
        import subprocess as sp
        command = cmd[cmd.index("-m") + 2:]
        while command and command[0].startswith("-"):
            command = command[2:]
        self.commands.append(command)
        out, code = "", 0
        if command[:1] and command[0].startswith("\\"):
            out = f"Command '{command[0]}' not found!"   # vrai rigctl 4.7.2 en ligne de commande (2026-11-19)
        elif command == ["get_powerstat"]:
            out = "1" if self.on else "0"
        elif command[:1] == ["set_powerstat"]:
            if command[1] == "1" and self.starts:
                self.on, self.ptt = True, 1 if self.ptt_at_boot else 0
            elif command[1] == "0":
                self.on = False
        elif not self.on:
            code = 1
        elif command == ["f"]:
            out = "7074000"
        elif command == ["m"]:
            out = "USB\n3000"
        elif command == ["t"]:
            out = str(self.ptt)
        elif command == ["T", "0"]:
            self.ptt = 0
        return sp.CompletedProcess(cmd, code, out.encode(), b"")


def _trial(rig, *, present=lambda p: True):
    from trxstation.power_trial import Trial
    cfg = dummy_config()
    cfg.rig.model, cfg.rig.port, cfg.power.on_timeout_s = 1042, "COM6", 5
    ident = usbports.UsbIdentity("10C4", "EA70", "01D0F21E", "00")
    clock = [0.0]

    def sleep(s):
        clock[0] += s
    out: list[str] = []
    ok = Trial(cfg, "rigctl", run=rig, say=out.append, port_present=present, identity=lambda p: ident,
               sleep=sleep, clock=lambda: clock[0]).run()
    return ok, out


def test_power_trial_switches_the_rig_off_and_on_without_ever_keying():
    rig = _FakeRig()
    ok, out = _trial(rig)
    assert ok and rig.on and rig.ptt == 0
    orders = [c for c in rig.commands if c[:1] == ["set_powerstat"]]
    assert orders == [["set_powerstat", "0"], ["set_powerstat", "1"]]
    assert not any(c[:1] == ["T"] and c[1:] != ["0"] for c in rig.commands)     # jamais « T 1 »


def test_power_trial_fails_when_the_port_disappears_or_the_rig_comes_back_transmitting():
    rig = _FakeRig()
    ok, out = _trial(rig, present=lambda p: False)
    assert not ok and not any(c == ["set_powerstat", "1"] for c in rig.commands)
    rig = _FakeRig(ptt_at_boot=True)
    ok, _ = _trial(rig)
    assert not ok and rig.ptt == 0 and ["T", "0"] in rig.commands
    rig = _FakeRig(starts=False)
    ok, _ = _trial(rig)
    assert not ok


def test_console_menu_2_8_needs_hamlib_and_a_passed_trial(tmp_path, monkeypatch):
    from test_console_tools import Runner, make, write_config
    from trxstation.console import Console, menu_number
    assert menu_number("remote_power") == "2.8"
    path = write_config(tmp_path)
    monkeypatch.setattr(Console, "_power_declared", lambda self, model, hamlib_dir: False)
    con, fake, out = make(tmp_path, answers=["o", "n"])          # (copie réécrite sous Windows : « enregistrer ? » non)
    con.remote_power()
    assert cfgmod.load(path).power.enabled is False and "Hamlib" in "\n".join(out)
    monkeypatch.setattr(Console, "_power_declared", lambda self, model, hamlib_dir: True)

    class TrialFails(Runner):
        def run(self, cmd, *, admin=False):
            if "trxstation.power_trial" in cmd:
                self.calls.append((cmd, admin))
                return 1
            return super().run(cmd, admin=admin)
    out = []
    answers = iter(["o", "o", "n"])
    con = Console(path, TrialFails(), ask=lambda _: next(answers), say=out.append, python="py", installed="0.37.0",
                  home=tmp_path / "home", editor="editeur")
    con.remote_power()
    assert cfgmod.load(path).power.enabled is False and "échec" in "\n".join(out)
    con, fake, out = make(tmp_path, answers=["o", "o", "o", "6", "n", "o"])   # service, essai, auto 6 h, pas de ntfy
    con.remote_power()
    cfg = cfgmod.load(path)
    assert cfg.power.enabled and cfg.power.idle_off and cfg.power.idle_off_hours == 6 and not cfg.power.notify
    trial = [c for c, admin in fake.calls if "trxstation.power_trial" in c]
    assert trial and all(admin for c, admin in fake.calls if "trxstation.power_trial" in c)


def test_only_the_power_control_references_set_powerstat():
    root = ROOT / "trxstation"
    allowed = {root / "gateway" / "cat" / "client.py", root / "gateway" / "power.py"}
    offenders = [p for p in root.rglob("*.py")
                 if "set_powerstat" in p.read_text(encoding="utf-8") and p.resolve() not in allowed]
    # faux rigctld des tests ; essai du menu 2.8 (rigctl, station ARRÊTÉE, poste lu en réception avant l'ordre)
    allowed_devtools = {root / "devtools" / "fake_rigctld.py", root / "power_trial.py"}
    assert [p for p in offenders if p.resolve() not in allowed_devtools] == []
