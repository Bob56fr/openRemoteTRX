"""« Poste utilisé sur place » : logique seule (horloge simulée), puis avec le contrôleur PTT et le faux rigctld.

Décision de l'utilisateur (2026-10-27) : une action faite sur le poste lui-même (micro, bouton d'accord, mode) bloque le
PTT À DISTANCE pendant l'émission locale puis 2 minutes ; l'accord et le mode à distance restent permis ; un client
peut « reprendre la main » plus tôt, jamais pendant une émission locale. La station ne coupe pas l'opérateur local.
"""
import asyncio

from test_safety import beating, refusal, run, station, until

from trxstation.gateway.safety.local import HOLD_S, SETTLE_S, LocalPresence


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def presence():
    clock = Clock()
    return LocalPresence(clock=clock), clock


def see(p, *, ptt=False, freq=14_200_000, mode="USB", gateway="RX", connected=True):
    return p.observe(connected, ptt, freq, mode, gateway)


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
