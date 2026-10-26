"""Tests de panne de la couche de sécurité PTT, sur le faux rigctld (aucun matériel)."""
import asyncio
import contextlib
import pathlib

import pytest

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.cat import CatLink
from trxstation.gateway.safety import PttController, PttLimits, Refused
from trxstation.setup_wizard import dummy_config


def run(scenario):
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        try:
            await asyncio.wait_for(scenario(fake), 20)
        finally:
            await fake.stop()
    asyncio.run(wrapper())


async def until(predicate, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("condition jamais atteinte")
        await asyncio.sleep(0.01)


def fast_limits(**kw):
    base = dict(tot_s=5.0, warn_before_s=1.0, heartbeat_timeout_s=1.0, tick_s=0.02, rig_poll_s=5.0,
                rekey_cooldown_s=0.0, unkey_retry_s=0.05, unkey_deadline_s=0.5)
    base.update(kw)
    return PttLimits(**base)


@contextlib.asynccontextmanager
async def station(fake, *, limits=None, cfg=None, clients=("phone", "car")):
    cfg = cfg or dummy_config()
    link = CatLink("127.0.0.1", fake.port, poll_fast_s=0.02, slow_every=2,
                   backoff_min_s=0.05, backoff_max_s=0.2, timeout=0.5)
    gate = []   # (ouvert ?, état du PTT du poste à cet instant)
    ctrl = PttController(link, cfg, limits=limits or fast_limits(),
                         audio_gate=lambda open_: gate.append((open_, fake.ptt)))
    link_task = asyncio.create_task(link.run())
    await ctrl.start()
    for c in clients:
        ctrl.connect_client(c)
    await until(lambda: link.state.connected and not ctrl.starting)
    try:
        yield ctrl, link, gate
    finally:
        await asyncio.wait_for(ctrl.close(), 5)
        link.stop()
        await asyncio.wait_for(link_task, 3)


async def refusal(coro):
    try:
        await coro
    except Refused as exc:
        return exc.reason
    raise AssertionError("un refus était attendu")


async def beating(ctrl, client_id, every=0.05):
    while True:
        ctrl.heartbeat(client_id)
        await asyncio.sleep(every)


def state_is(ctrl, name):
    return ctrl.snapshot().state == name


# --------------------------------------------------------------------------- démarrage et toggle

def test_startup_forces_rx_even_if_rig_was_transmitting():
    async def scenario(fake):
        fake.ptt = 1
        async with station(fake) as (ctrl, link, gate):
            assert fake.ptt == 0 and fake.ptt_commands[0] == 0
            assert state_is(ctrl, "RX")
    run(scenario)


def test_keying_refused_until_startup_rx_confirmed():
    async def scenario(fake):
        link = CatLink("127.0.0.1", fake.port, timeout=0.5)
        ctrl = PttController(link, dummy_config(), limits=fast_limits())
        ctrl.connect_client("phone")
        assert await refusal(ctrl.toggle("phone")) == "starting"
        assert fake.ptt_commands == []
    run(scenario)


def test_toggle_on_off_and_microphone_closed_before_ptt_off():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            snap = await ctrl.toggle("phone")
            assert snap.state == "TX" and snap.owner == "phone" and fake.ptt == 1
            assert gate[-1] == (True, 1)
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await ctrl.toggle("car")                 # un autre client peut toujours COUPER
            hb.cancel()
            assert state_is(ctrl, "RX") and fake.ptt == 0 and ctrl.snapshot().owner is None
            assert gate[-1] == (False, 1)            # micro coupé alors que le PTT était encore actif
            assert fake.ptt_commands[-2:] == [1, 0]
    run(scenario)


def test_snapshot_reports_remaining_tot():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(tot_s=3.0)) as (ctrl, link, gate):
            snap = await ctrl.toggle("phone")
            assert 0 < snap.tot_remaining_s <= 3.0
    run(scenario)


# --------------------------------------------------------------------------- refus de prise d'émission

def test_unknown_client_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            assert await refusal(ctrl.toggle("intrus")) == "unknown_client"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_out_of_band_refused_using_fresh_frequency():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.freq = 14_500_000            # le poste vient d'être déplacé hors bande
            assert await refusal(ctrl.toggle("phone")) == "out_of_band"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_no_bands_means_no_transmission():
    async def scenario(fake):
        cfg = dummy_config()
        cfg.bands = []
        async with station(fake, cfg=cfg) as (ctrl, link, gate):
            assert await refusal(ctrl.toggle("phone")) == "tx_disabled"
            assert 1 not in fake.ptt_commands
    run(scenario)


def test_rig_already_transmitting_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.ptt = 1
            assert await refusal(ctrl.toggle("phone")) == "rig_already_tx"
            assert 1 not in fake.ptt_commands
            fake.ptt = 0
    run(scenario)


def test_unreadable_ptt_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.errors["t"] = -11
            assert await refusal(ctrl.toggle("phone")) == "ptt_unreadable"
            assert 1 not in fake.ptt_commands
            del fake.errors["t"]
    run(scenario)


def test_cat_down_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await fake.stop()
            await until(lambda: not link.state.connected)
            assert await refusal(ctrl.toggle("phone")) == "cat_down"
    run(scenario)


def test_rekey_cooldown():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(rekey_cooldown_s=0.4)) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            await ctrl.toggle("phone")                       # coupure
            assert await refusal(ctrl.toggle("phone")) == "cooldown"
            await asyncio.sleep(0.45)
            assert (await ctrl.toggle("phone")).state == "TX"
    run(scenario)


# --------------------------------------------------------------------------- coupures automatiques

def test_tot_cuts_transmission_and_warns_first():
    async def scenario(fake):
        events = []
        async with station(fake, limits=fast_limits(tot_s=0.6, warn_before_s=0.3)) as (ctrl, link, gate):
            ctrl.add_listener(lambda s: events.append(s.event))
            await ctrl.toggle("phone")
            hb = asyncio.create_task(beating(ctrl, "phone"))
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "tot" and fake.ptt == 0
            assert events.index("tot_warning") < events.index("cut")
    run(scenario)


def test_heartbeat_loss_cuts():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(heartbeat_timeout_s=0.3)) as (ctrl, link, gate):
            await ctrl.toggle("phone")                       # aucun battement ensuite
            await until(lambda: state_is(ctrl, "RX"), 3)
            assert ctrl.snapshot().last_cut_reason == "heartbeat" and fake.ptt == 0
    run(scenario)


def test_heartbeat_from_other_client_does_not_keep_transmission_alive():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(heartbeat_timeout_s=0.3)) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            assert ctrl.heartbeat("car") is False
            hb = asyncio.create_task(beating(ctrl, "car"))
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "heartbeat"
    run(scenario)


def test_owner_disconnect_cuts_immediately_other_disconnect_does_not():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            await ctrl.disconnect_client("car")
            assert state_is(ctrl, "TX")
            await ctrl.disconnect_client("phone")
            assert state_is(ctrl, "RX") and fake.ptt == 0
            assert ctrl.snapshot().last_cut_reason == "client_disconnected"
    run(scenario)


def test_frequency_changed_on_the_rig_cuts():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(rig_poll_s=0.1)) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            hb = asyncio.create_task(beating(ctrl, "phone"))
            fake.freq = 14_250_000                           # molette tournée sur le poste
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "frequency_changed" and fake.ptt == 0
    run(scenario)


def test_rig_unkeyed_externally_is_reflected():
    async def scenario(fake):
        async with station(fake, limits=fast_limits(rig_poll_s=0.1)) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            hb = asyncio.create_task(beating(ctrl, "phone"))
            fake.ptt = 0
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "rig_reported_rx"
    run(scenario)


def test_cat_link_loss_during_tx_ends_in_rx_after_reconnect():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            hb = asyncio.create_task(beating(ctrl, "phone"))
            fake.drop_connections()
            await until(lambda: state_is(ctrl, "RX") and fake.ptt == 0, 6)
            hb.cancel()
    run(scenario)


# --------------------------------------------------------------------------- fréquence et mode

def test_tuning_refused_while_transmitting_then_allowed():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            assert await refusal(ctrl.set_frequency(7_100_000)) == "tx_active"
            assert await refusal(ctrl.set_mode("LSB")) == "tx_active"
            assert fake.freq == 14_200_000 and fake.mode == "USB"
            await ctrl.toggle("phone")                       # coupure
            await ctrl.set_frequency(7_100_000)
            await ctrl.set_mode("LSB")
            assert fake.freq == 7_100_000 and fake.mode == "LSB"
    run(scenario)


# --------------------------------------------------------------------------- retour RX difficile

def test_transient_unkey_errors_are_retried():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            fake.fail_t = 2
            await ctrl.toggle("car")
            assert state_is(ctrl, "RX") and fake.ptt == 0 and ctrl.snapshot().fault == ""
    run(scenario)


def test_persistent_unkey_failure_latches_fault_and_never_reports_rx():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            fake.errors["T"] = -9
            await ctrl.toggle("car")
            snap = ctrl.snapshot()
            assert snap.state == "UNKEYING" and snap.fault == "unkey_failed" and fake.ptt == 1
            del fake.errors["T"]                             # le poste répond de nouveau
            await until(lambda: state_is(ctrl, "RX"), 3)
            assert fake.ptt == 0 and ctrl.snapshot().fault == "unkey_failed"
            assert await refusal(ctrl.toggle("phone")) == "fault_latched"
            ctrl.clear_fault()
            assert (await ctrl.toggle("phone")).state == "TX"
    run(scenario)


def test_rig_that_ignores_unkey_is_detected_by_readback():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            fake.ignore_unkey = True
            await ctrl.toggle("car")
            assert state_is(ctrl, "UNKEYING")                # pas de faux « RX »
            fake.ignore_unkey = False
            await until(lambda: state_is(ctrl, "RX"), 3)
            assert fake.ptt == 0
    run(scenario)


def test_write_failure_while_keying_cuts_and_refuses():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.fail_t = 1                                  # « T 1 » échoue : a-t-il émis ? inconnu
            assert await refusal(ctrl.toggle("phone")) == "ptt_write_failed"
            await until(lambda: state_is(ctrl, "RX"), 3)
            assert fake.ptt == 0 and fake.ptt_commands[-1] == 0
    run(scenario)


def test_rig_that_does_not_key_is_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.errors["t"] = -11                           # relecture impossible après écriture
            fake.errors.pop("t")
            fake.ptt = 0
            original = fake._reply

            def reply(line):                                 # « T 1 » accepté mais sans effet
                if line.startswith("+T 1"):
                    return "set_ptt: 1\nRPRT 0\n"
                return original(line)
            fake._reply = reply
            assert await refusal(ctrl.toggle("phone")) == "rig_did_not_key"
            await until(lambda: state_is(ctrl, "RX"), 3)
            assert fake.ptt == 0
    run(scenario)


# --------------------------------------------------------------------------- courses

@pytest.mark.parametrize("delay", [0, 0.001, 0.004, 0.01, 0.03])
def test_cut_racing_with_keying_always_ends_in_rx(delay):
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            attempt = asyncio.create_task(ctrl.toggle("phone"))
            await asyncio.sleep(delay)
            await ctrl.force_rx("test")
            try:
                await attempt
            except Refused:
                pass
            await until(lambda: state_is(ctrl, "RX"), 3)
            await asyncio.sleep(0.1)                         # laisse arriver une écriture tardive éventuelle
            assert fake.ptt == 0 and state_is(ctrl, "RX")
    run(scenario)


def test_shutdown_while_transmitting_cuts():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.toggle("phone")
            await ctrl.close()
            assert fake.ptt == 0
    run(scenario)


# --------------------------------------------------------------------------- garde-fous de structure

def test_only_the_safety_layer_references_write_ptt():
    root = pathlib.Path(__file__).resolve().parent.parent / "trxstation"
    allowed = {root / "gateway" / "cat" / "client.py", root / "gateway" / "safety" / "ptt.py"}
    offenders = [p for p in root.rglob("*.py")
                 if "write_ptt" in p.read_text(encoding="utf-8") and p.resolve() not in allowed]
    assert offenders == []


def test_limits_validation_and_from_config():
    with pytest.raises(ValueError):
        PttLimits(tot_s=5, warn_before_s=5)
    with pytest.raises(ValueError):
        PttLimits(tick_s=0)
    cfg = dummy_config()
    cfg.safety.tot_s = 100
    assert PttLimits.from_config(cfg).tot_s == 100.0
    cfg.safety.tot_ceiling_s = 120
    cfg.safety.tot_s = 100
    assert PttLimits.from_config(cfg).heartbeat_timeout_s == cfg.safety.heartbeat_timeout_ms / 1000


# --------------------------------------------------------------------------- modes d'émission autorisés (tx_modes)

def data_modes_config():
    cfg = dummy_config()
    cfg.rig.tx_modes = ["PKTUSB", "PKTLSB"]
    return cfg


def test_transmission_refused_in_a_mode_where_usb_audio_is_not_the_source():
    async def scenario(fake):
        async with station(fake, cfg=data_modes_config()) as (ctrl, link, gate):
            assert fake.mode == "USB"                                          # mode normal : le poste modulerait avec son micro
            assert await refusal(ctrl.toggle("phone")) == "mode_not_allowed"
            assert 1 not in fake.ptt_commands and not gate                      # rien n'est parti, la porte n'a jamais été ouverte
    run(scenario)


def test_transmission_allowed_once_the_rig_is_in_an_allowed_mode():
    async def scenario(fake):
        async with station(fake, cfg=data_modes_config()) as (ctrl, link, gate):
            await ctrl.set_mode("PKTUSB")                                      # changement de mode permis en réception
            assert (await ctrl.toggle("phone")).state == "TX" and fake.ptt == 1
            assert await refusal(ctrl.set_mode("USB")) == "tx_active"           # mais pas pendant l'émission
    run(scenario)


def test_mode_changed_on_the_rig_during_transmission_cuts_it():
    async def scenario(fake):
        async with station(fake, cfg=data_modes_config(), limits=fast_limits(rig_poll_s=0.1)) as (ctrl, link, gate):
            await ctrl.set_mode("PKTUSB")
            await ctrl.toggle("phone")
            hb = asyncio.create_task(beating(ctrl, "phone"))
            fake.mode = "USB"                                                   # bouton du poste : retour en USB normal
            await until(lambda: state_is(ctrl, "RX"), 3)
            hb.cancel()
            assert ctrl.snapshot().last_cut_reason == "mode_changed" and fake.ptt == 0
    run(scenario)


def test_unreadable_mode_refuses_transmission_when_modes_are_restricted():
    async def scenario(fake):
        async with station(fake, cfg=data_modes_config()) as (ctrl, link, gate):
            fake.errors["m"] = -11
            assert await refusal(ctrl.toggle("phone")) == "cat_error"
            assert 1 not in fake.ptt_commands
            del fake.errors["m"]
    run(scenario)


def test_no_restriction_by_default_other_makes_keep_working_in_any_mode():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):                         # tx_modes vide
            assert fake.mode == "USB" and (await ctrl.toggle("phone")).state == "TX"
            fake.mode = "FM"                                                   # un changement de mode ne coupe rien
            await asyncio.sleep(0.3)
            assert state_is(ctrl, "TX")
    run(scenario)


# --------------------------------------------------------------------------- contrôle des bandes optionnel (enforce_bands)

def test_band_control_can_be_delegated_to_the_rig():
    async def scenario(fake):
        cfg = dummy_config()
        cfg.safety.enforce_bands = False
        async with station(fake, cfg=cfg) as (ctrl, link, gate):
            fake.freq = 27_495_000                                        # hors des bandes amateur : au poste de refuser
            assert (await ctrl.toggle("phone")).state == "TX" and fake.ptt == 1
    run(scenario)


def test_band_control_delegated_also_works_with_an_empty_band_list():
    async def scenario(fake):
        cfg = dummy_config()
        cfg.safety.enforce_bands, cfg.bands = False, []
        async with station(fake, cfg=cfg) as (ctrl, link, gate):
            assert (await ctrl.toggle("phone")).state == "TX"
        assert not any("IMPOSSIBLE" in w for w in cfgmod_warnings(cfg))
        assert any("DÉSACTIVÉ" in w for w in cfgmod_warnings(cfg))        # mais l'utilisateur est prévenu
    run(scenario)


def test_band_control_stays_on_by_default():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            fake.freq = 27_495_000
            assert await refusal(ctrl.toggle("phone")) == "out_of_band" and 1 not in fake.ptt_commands
    run(scenario)


def cfgmod_warnings(cfg):
    from trxstation import config
    return config.warnings(cfg)


# --------------------------------------------------------------------------- réglages du poste : jamais pendant l'émission

def test_rig_settings_are_applied_in_reception_and_refused_during_transmission():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await until(lambda: "NR" in link.state.functions and "PREAMP" in link.state.levels)
            await ctrl.set_function("NR", True)
            await ctrl.set_level("AGC", 2)
            assert fake.funcs["NR"] == 1 and fake.levels["AGC"] == 2
            await ctrl.toggle("phone")
            assert await refusal(ctrl.set_function("TUNER", True)) == "tx_active"             # un accord lancerait une porteuse
            assert await refusal(ctrl.set_function("NB", False)) == "tx_active"
            assert await refusal(ctrl.set_level("PREAMP", 20)) == "tx_active"
            assert fake.funcs["TUNER"] == 0 and fake.funcs["NB"] == 1 and fake.levels["PREAMP"] == 10
            await ctrl.force_rx("stop", by="phone")
            await until(lambda: state_is(ctrl, "RX"))
            await ctrl.set_function("TUNER", True)                                              # de retour en réception : permis
            assert fake.funcs["TUNER"] == 1
    run(scenario)


def test_tx_power_can_only_be_changed_in_reception():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await until(lambda: "RFPOWER" in link.state.levels)
            await ctrl.set_level("RFPOWER", 0.25)
            assert fake.levels["RFPOWER"] == 0.25
            await ctrl.toggle("phone")
            assert await refusal(ctrl.set_level("RFPOWER", 1.0)) == "tx_active"                # jamais d'augmentation en pleine émission
            assert fake.levels["RFPOWER"] == 0.25
            await ctrl.force_rx("stop", by="phone")
            await until(lambda: state_is(ctrl, "RX"))
            await ctrl.set_level("RFPOWER", 0.5)
            assert fake.levels["RFPOWER"] == 0.5
    run(scenario)
