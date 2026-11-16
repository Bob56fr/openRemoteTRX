# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""« Poste utilisé sur place » : logique seule (horloge simulée), puis avec le contrôleur PTT et le faux rigctld.

Décision de l'utilisateur (2026-10-27) : une action faite sur le poste lui-même (micro, bouton d'accord, mode) bloque le
PTT À DISTANCE pendant l'émission locale puis 2 minutes ; l'accord et le mode à distance restent permis ; un client
peut « reprendre la main » plus tôt, jamais pendant une émission locale. La station ne coupe pas l'opérateur local.
"""
import asyncio

from test_safety import beating, refusal, run, station, until

from trxstation.gateway.safety.local import HOLD_S, PANEL_EXPECT_S, PRESENCE_S, SETTLE_S, LocalPresence, panel_of


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def presence():
    clock = Clock()
    return LocalPresence(clock=clock), clock


def see(p, *, ptt=False, freq=14_200_000, mode="USB", gateway="RX", connected=True, panel=None, writes=None):
    return p.observe(connected, ptt, freq, mode, gateway, panel, writes)


def knobs(af=0.5, nr=False, preamp=1):
    return panel_of({"NR": nr}, {"AF": af, "PREAMP": preamp, "SWR": 1.1, "TEMP_METER": 31.0}, {"RIT": 0}, False, None)


# --------------------------------------------------------------------------- logique seule

def test_local_transmission_blocks_until_two_minutes_after_its_end():
    p, clock = presence()
    see(p)
    assert not p.active()
    assert see(p, ptt=True) is True                       # micro du poste
    assert p.active() and p.transmitting and p.reason == "tx" and p.remaining() == HOLD_S
    clock.now += 300                                      # longue émission locale : toujours bloqué
    see(p, ptt=True)
    assert p.active() and p.remaining() == HOLD_S
    see(p, ptt=False)                                     # fin de l'émission locale : l'attente part d'ici
    assert p.active() and not p.transmitting
    clock.now += HOLD_S - 1
    assert p.active() and 0 < p.remaining() <= 1
    clock.now += 2
    assert not p.active() and p.remaining() is None


def test_knob_and_mode_changes_on_the_rig_are_noticed_but_not_the_station_own_commands():
    p, clock = presence()
    see(p)
    p.expect("frequency")
    assert see(p, freq=14_205_000) is False               # changement commandé par la station
    assert not p.active()
    clock.now += 5
    assert see(p, freq=14_210_000) is True and p.reason == "frequency"
    p, clock = presence()
    see(p)
    p.expect("mode")
    assert see(p, mode="LSB") is False
    clock.now += 5
    assert see(p, mode="CW") is True and p.reason == "mode"


def test_nothing_is_deduced_right_after_the_station_own_transmission():
    p, clock = presence()
    see(p)
    p.station_busy()                                      # la passerelle vient de couper SON émission
    assert see(p, ptt=True) is False                      # relecture en retard : pas l'opérateur
    clock.now += SETTLE_S + 0.1
    see(p, ptt=False)
    assert not p.active()
    assert see(p, ptt=True, gateway="TX") is False        # pendant l'émission de la station : rien


def test_release_is_refused_during_a_local_transmission_and_allowed_after():
    p, clock = presence()
    see(p)
    see(p, ptt=True)
    assert p.release() is False and p.active()
    see(p, ptt=False)
    assert p.release() is True and not p.active() and p.reason == ""


def test_a_link_loss_does_not_make_a_change_out_of_a_reconnection():
    p, clock = presence()
    see(p, freq=7_074_000)
    see(p, connected=False)
    clock.now += 10
    assert see(p, freq=14_074_000) is False               # nouvelle référence après la coupure
    assert not p.active()


# --------------------------------------------------------------------------- présence prouvée (étape 206)

def test_panel_keeps_settings_only_never_meters():
    assert set(knobs()) == {"f:NR", "l:AF", "l:PREAMP", "o:RIT", "split"}


def test_volume_turned_just_before_keying_proves_presence_without_blocking_remote_ptt():
    p, clock = presence()
    see(p, panel=knobs())
    clock.now += 10
    see(p, panel=knobs(af=0.7))                           # volume tourné sur le poste
    assert not p.active()                                 # un réglage ne bloque PAS le PTT à distance (étape 34 inchangée)
    clock.now += PRESENCE_S - 5
    assert see(p, ptt=True, panel=knobs(af=0.7)) is True
    assert p.transmitting and p.present


def test_action_too_old_does_not_prove_presence_but_one_during_the_transmission_does():
    p, clock = presence()
    see(p, panel=knobs())
    see(p, panel=knobs(af=0.7))
    clock.now += PRESENCE_S + 1
    see(p, ptt=True, panel=knobs(af=0.7))
    assert p.transmitting and not p.present               # micro coincé longtemps après une action : pas de preuve
    clock.now += 30
    assert see(p, ptt=True, panel=knobs(af=0.3)) is True  # changement de l'état publié
    assert p.present
    see(p, ptt=False, panel=knobs(af=0.3))
    assert not p.present                                  # fin de l'émission locale


def test_leaving_data_mode_or_tuning_before_keying_proves_presence():
    for change in ({"mode": "USB"}, {"freq": 14_210_000}):
        p, clock = presence()
        see(p, mode="PKTUSB")
        clock.now += 10
        see(p, **{"mode": "PKTUSB", **change})            # sortie du mode DATA pour parler au micro, ou accord
        clock.now += 20
        see(p, ptt=True, **{"mode": "PKTUSB", **change})
        assert p.present


def test_a_transmission_alone_proves_nothing():
    p, clock = presence()
    see(p, panel=knobs())
    clock.now += 10
    see(p, ptt=True, panel=knobs())
    assert p.transmitting and not p.present
    see(p, ptt=False, panel=knobs())
    clock.now += 10
    see(p, ptt=True, panel=knobs())                       # nouvelle prise peu après la précédente : toujours rien
    assert not p.present


def test_settings_written_by_the_station_are_not_presence():
    p, clock = presence()
    see(p, panel=knobs())
    clock.now += 10
    see(p, panel=knobs(nr=True), writes={"f:NR": clock.now - 30})   # relu tard, écrit par la station
    see(p, ptt=True, panel=knobs(nr=True))
    assert not p.present
    p, clock = presence()
    see(p, panel=knobs())
    clock.now += 10
    see(p, panel=knobs(preamp=0), writes={"*": clock.now - 5})       # préampli mémorisé par bande après un QSY de la station
    see(p, ptt=True, panel=knobs(preamp=0))
    assert not p.present
    clock.now += PANEL_EXPECT_S
    see(p, ptt=False, panel=knobs(preamp=0))
    see(p, panel=knobs(preamp=1), writes={"*": clock.now - PANEL_EXPECT_S - 5})   # bien après : le poste
    see(p, ptt=True, panel=knobs(preamp=1))
    assert p.present


def test_first_reading_of_a_setting_and_station_transmission_prove_nothing():
    p, clock = presence()
    see(p, panel={})
    see(p, panel=knobs())                                 # réglages lus pour la première fois
    see(p, ptt=True, panel=knobs())
    assert not p.present
    p, clock = presence()
    see(p, panel=knobs())
    see(p, gateway="TX", ptt=True, panel=knobs(preamp=0))  # pendant l'émission de la station : rien
    clock.now += SETTLE_S + 1
    see(p, ptt=False, panel=knobs(preamp=0))
    see(p, ptt=True, panel=knobs(preamp=0))
    assert not p.present


def test_link_loss_forgets_the_settings():
    p, clock = presence()
    see(p, panel=knobs())
    see(p, connected=False)
    see(p, panel=knobs(af=0.9))                           # nouvelle référence après la coupure
    see(p, ptt=True, panel=knobs(af=0.9))
    assert not p.present


# --------------------------------------------------------------------------- avec le contrôleur PTT

def test_operator_at_the_mic_blocks_remote_ptt_without_being_cut():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            cuts = len(fake.ptt_commands)
            fake.ptt = 1                                  # l'opérateur passe en émission au micro du poste
            await until(lambda: ctrl.local.transmitting)
            snap = ctrl.snapshot().to_dict()
            assert snap["local_tx"] is True and snap["local_reason"] == "tx" and snap["local_remaining_s"] > 0
            assert snap["state"] == "RX"                  # la passerelle n'émet pas
            assert await refusal(ctrl.toggle("phone")) == "local_active"
            assert await refusal(_release(ctrl, "phone")) == "local_tx"   # pas de reprise pendant qu'il parle
            await asyncio.sleep(0.2)
            assert fake.ptt == 1 and len(fake.ptt_commands) == cuts   # la station ne coupe PAS l'opérateur local
            fake.ptt = 0                                  # fin de son émission
            await until(lambda: not ctrl.local.transmitting)
            assert ctrl.local.active()
            assert await refusal(ctrl.toggle("phone")) == "local_active"   # attente de 2 minutes
            snap = ctrl.release_local("phone")            # « reprendre la main »
            assert snap.local_remaining_s is None
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            try:
                await ctrl.toggle("phone")
                assert ctrl.snapshot().state == "TX" and fake.ptt == 1
                await ctrl.toggle("phone")
            finally:
                beat.cancel()
            assert fake.ptt == 0 and not ctrl.local.active()   # sa propre émission ne passe pas pour une action locale
    run(scenario)


async def _release(ctrl, client):
    ctrl.release_local(client)


def test_knob_turned_on_the_rig_blocks_remote_ptt_but_not_remote_tuning():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await ctrl.set_frequency(7_074_000)           # accord à distance : pas une action locale
            await until(lambda: link.state.frequency_hz == 7_074_000)
            await asyncio.sleep(0.1)
            assert not ctrl.local.active()
            await asyncio.sleep(3.2)                      # au-delà de l'attribution à la station
            fake.freq = 7_080_000                         # bouton d'accord tourné sur le poste
            await until(lambda: ctrl.local.active())
            assert ctrl.snapshot().local_reason == "frequency"
            assert await refusal(ctrl.toggle("phone")) == "local_active"
            await ctrl.set_frequency(7_090_000)           # accord à distance toujours permis
            await until(lambda: fake.freq == 7_090_000)
            await ctrl.set_mode("LSB")
            await until(lambda: fake.mode == "LSB")
    run(scenario)


def test_hold_expires_by_itself_and_stop_is_never_refused():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            ctrl.local.hold_s = 0.4
            fake.ptt = 1
            await until(lambda: ctrl.local.transmitting)
            await ctrl.force_rx("stop", by="phone")      # STOP : toujours accepté (coupe aussi le poste)
            assert fake.ptt == 0
            await until(lambda: not ctrl.local.transmitting)
            await until(lambda: not ctrl.local.active(), timeout=2)
            beat = asyncio.ensure_future(beating(ctrl, "phone"))
            try:
                await ctrl.toggle("phone")                # attente écoulée : le PTT à distance est permis
                assert ctrl.snapshot().state == "TX"
            finally:
                beat.cancel()
    run(scenario)


def test_unknown_client_cannot_release():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            assert await refusal(_release(ctrl, "intrus")) == "unknown_client"
    run(scenario)


def test_volume_turned_on_the_rig_then_mic_is_published_as_operator_present():
    async def scenario(fake):
        async with station(fake) as (ctrl, link, gate):
            await until(lambda: "AF" in link.state.levels, timeout=5)
            await ctrl.set_level("NR", 0.6)               # réglage de la station : pas une preuve
            await until(lambda: link.state.levels.get("NR") == 0.6)
            fake.ptt = 1
            await until(lambda: ctrl.local.transmitting)
            await asyncio.sleep(0.3)
            assert ctrl.snapshot().local_present is False
            fake.levels["AF"] = 0.8                       # volume tourné sur le poste pendant qu'il parle
            await until(lambda: ctrl.snapshot().local_present, timeout=5)
            assert ctrl.snapshot().to_dict()["local_present"] is True
            assert fake.ptt == 1                          # la station ne coupe toujours pas l'opérateur local
            fake.ptt = 0
            await until(lambda: not ctrl.snapshot().local_present)
    run(scenario)
