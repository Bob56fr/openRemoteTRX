# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Logique du superviseur, testée dans un monde simulé : aucune attente réelle, aucun système."""
import pytest

from trxstation import config as cfgmod
from trxstation.setup_wizard import dummy_config
from trxstation.status import GatewayStatus
from trxstation.supervisor.core import Supervisor
from trxstation.supervisor.rigctl import RigProbe
from trxstation.supervisor.state import StateStore

FREQ = 14_200_000
ACTION_NAMES = {"force_rx", "kill_gateway", "restart_gateway", "stop_gateway",
                "restart_rigctld", "reset_usb", "reboot"}


class World:
    """Poste, passerelle et horloge simulés. Le World joue aussi le rôle des `actions`."""

    def __init__(self, tmp_path, *, real_rig=False, **supervisor_settings):
        self.cfg = dummy_config()
        self.cfg.supervisor.startup_grace_s = 0.0
        supervisor_settings.setdefault("allow_local_tx", False)   # mode A (« station distante seule ») sauf mention contraire
        for key, value in supervisor_settings.items():
            setattr(self.cfg.supervisor, key, value)
        if real_rig:
            self.cfg.rig.model, self.cfg.rig.port = 3073, "/dev/ttyUSB0"
        self.now, self.wall = 1000.0, 1_800_000_000.0
        self.rig = RigProbe(True, False, FREQ)
        self.gateway_up, self.frozen, self.heals = True, False, True
        self.pid, self.seq, self.status = 100, 0, None
        self.gw_state, self.gw_owner, self.gw_fault, self.gw_clients = "RX", None, "", []
        self.cut_works, self.port_present, self.temp = True, True, None
        self.boom: set[str] = set()
        self.calls: list[str] = []
        self.alerts: list[str] = []
        self.store = StateStore(tmp_path)
        self.sup = self.make_supervisor()

    def make_supervisor(self, store=None):
        return Supervisor(self.cfg, read_status=lambda: self.status, probe_rig=lambda: self.rig,
                          actions=self, store=store or self.store, clock=lambda: self.now,
                          wall=lambda: self.wall, port_exists=lambda p: self.port_present,
                          read_temp=lambda: self.temp)

    def gateway_transmitting(self):
        self.gw_state, self.gw_owner, self.gw_clients = "TX", "phone", ["phone"]
        self.rig = RigProbe(True, True, FREQ)

    def freeze_gateway(self):
        self.frozen = True

    def tick(self, dt=0.25):
        self.now += dt
        self.wall += dt
        if self.gateway_up and not self.frozen:
            self.seq += 1
            self.status = GatewayStatus(
                pid=self.pid, seq=self.seq, written_at=self.wall,
                ptt={"state": self.gw_state, "owner": self.gw_owner, "fault": self.gw_fault},
                rig={}, clients=list(self.gw_clients))
        return self.sup.step()

    def run(self, seconds, dt=0.25):
        return [self.tick(dt) for _ in range(round(seconds / dt))]

    # ---- actions
    def _record(self, name):
        self.calls.append(name)
        if name in self.boom:
            raise RuntimeError(f"{name} en panne")

    def force_rx(self):
        self._record("force_rx")
        if self.cut_works and self.rig.ok:
            self.rig = RigProbe(True, False, FREQ)
        return self.cut_works

    def kill_gateway(self):
        self._record("kill_gateway")
        self.gateway_up = False

    def restart_gateway(self):
        self._record("restart_gateway")
        self.pid += 1
        self.frozen = False
        self.gw_state, self.gw_owner, self.gw_clients = "RX", None, []
        self.gateway_up = self.heals

    def stop_gateway(self):
        self._record("stop_gateway")
        self.gateway_up = False

    def restart_rigctld(self):
        self._record("restart_rigctld")

    def reset_usb(self):
        self._record("reset_usb")

    def reboot(self):
        self._record("reboot")

    def notify(self, title, message):
        self.alerts.append(title)


def W(tmp_path, **kw):
    return World(tmp_path, **kw)


# --------------------------------------------------------------------------- situation normale

def test_healthy_station_does_nothing(tmp_path):
    w = W(tmp_path)
    reports = w.run(60)
    assert w.calls == [] and all(r.problems == [] for r in reports) and w.alerts == []


def test_explained_transmission_is_left_alone(tmp_path):
    w = W(tmp_path)
    w.gateway_transmitting()
    w.run(100)                                    # < TOT absolu (135 s)
    assert w.calls == []


def test_unknown_ptt_is_ignored(tmp_path):
    w = W(tmp_path)
    w.rig = RigProbe(True, None, FREQ)
    w.run(30)
    assert w.calls == []


def test_gateway_unkeying_is_not_a_mismatch(tmp_path):
    w = W(tmp_path)
    w.gateway_transmitting()
    w.gw_state = "UNKEYING"
    w.run(5)
    assert w.calls == []


# --------------------------------------------------------------------------- garde TX

def test_absolute_tot_cuts_and_restarts_gateway(tmp_path):
    w = W(tmp_path)
    w.gateway_transmitting()
    w.run(134)
    assert w.calls == []
    w.run(4)
    assert "force_rx" in w.calls and "kill_gateway" in w.calls and "restart_gateway" in w.calls
    assert w.rig.ptt is False


def test_tx_timer_restarts_after_a_pause_in_reception(tmp_path):
    w = W(tmp_path)
    w.gateway_transmitting()
    w.run(100)
    w.rig = RigProbe(True, False, FREQ)
    w.run(1)
    w.rig = RigProbe(True, True, FREQ)
    w.run(100)                                    # 100 s + 100 s, mais le chrono est reparti à zéro
    assert w.calls == []


def test_frozen_gateway_during_tx_is_cut(tmp_path):
    w = W(tmp_path)
    w.gateway_transmitting()
    w.run(2)
    w.freeze_gateway()
    w.run(1.5)                                    # encore sous le délai de péremption (2 s)
    assert w.calls == []
    w.run(1.0)
    assert "force_rx" in w.calls and "kill_gateway" in w.calls
    assert w.rig.ptt is False


def test_mismatch_between_rig_and_gateway(tmp_path):
    w = W(tmp_path)
    w.rig = RigProbe(True, True, FREQ)            # le poste émet, la passerelle se croit en RX
    w.run(1.0)                                    # sous la tolérance (1,5 s)
    assert w.calls == []
    w.run(2.0)
    assert "force_rx" in w.calls and w.rig.ptt is False
    assert "restart_gateway" not in w.calls       # la coupure a pris : rien à relancer


def test_mismatch_that_resists_the_cut_escalates(tmp_path):
    w = W(tmp_path)
    w.cut_works = False
    w.rig = RigProbe(True, True, FREQ)
    w.run(6.0)                                    # 1,5 s de tolérance + moins de 5 s de résistance
    assert "force_rx" in w.calls and "restart_gateway" not in w.calls
    w.run(1.5)
    assert "restart_gateway" in w.calls           # « T 0 » sans effet : passerelle relancée


def test_operator_keying_again_after_each_cut_never_leads_to_safe_mode(tmp_path):
    """Incident du 2026-10-27 : micro du poste repris après chaque coupure (station distante seule)."""
    w = W(tmp_path, max_reboots_per_hour=0)
    for _ in range(100):                          # 5 minutes : l'opérateur reprend l'émission toutes les 3 s
        w.rig = RigProbe(True, True, FREQ)
        w.run(3.0)
    assert w.calls.count("force_rx") >= 100       # coupé à chaque fois (mode A)
    assert not set(w.calls) & {"kill_gateway", "restart_gateway", "restart_rigctld", "reset_usb", "reboot", "stop_gateway"}
    assert not w.store.safe_mode()


def test_shared_station_is_the_default(tmp_path):
    assert cfgmod.Supervisor().allow_local_tx is True
    assert dummy_config().supervisor.allow_local_tx is True


def test_shared_station_local_tx_cut_by_absolute_tot_without_escalation(tmp_path):
    w = W(tmp_path, allow_local_tx=True)
    w.rig = RigProbe(True, True, FREQ)            # opérateur local au micro du poste
    w.run(134)
    assert w.calls == []                          # pas coupé avant le TOT absolu
    w.run(2)
    assert "force_rx" in w.calls and w.rig.ptt is False
    assert "restart_gateway" not in w.calls       # la passerelle n'y est pour rien
    w.rig = RigProbe(True, True, FREQ)            # il reprend aussitôt : nouveau chrono
    w.run(30)
    assert w.calls.count("force_rx") == 1


def test_shared_station_still_cuts_a_frozen_gateway_that_was_transmitting(tmp_path):
    w = W(tmp_path, allow_local_tx=True)
    w.gateway_transmitting()
    w.run(2)
    w.freeze_gateway()                            # dernier état publié : émission à distance
    w.run(3)
    assert "force_rx" in w.calls and "kill_gateway" in w.calls


def test_shared_station_with_unknown_gateway_state_cuts(tmp_path):
    w = W(tmp_path, allow_local_tx=True)
    w.gateway_up = False                          # aucune passerelle n'a jamais publié : prudence
    w.rig = RigProbe(True, True, FREQ)
    w.run(1)
    assert "force_rx" in w.calls


def test_gateway_that_cannot_unkey_triggers_immediate_cut(tmp_path):
    w = W(tmp_path)
    w.gateway_transmitting()
    w.gw_fault = "unkey_failed"
    reports = w.run(0.25)
    assert "gateway_cannot_unkey" in reports[0].problems and "force_rx" in w.calls


def test_local_transmission_tolerated_when_allowed_but_absolute_tot_still_applies(tmp_path):
    w = W(tmp_path, allow_local_tx=True)
    w.rig = RigProbe(True, True, FREQ)            # opérateur local au micro du poste
    w.run(30)
    w.freeze_gateway()
    w.run(30)
    assert "force_rx" not in w.calls              # l'opérateur local n'est pas coupé (la passerelle gelée, si)
    w.run(80)                                     # 140 s d'émission au total
    assert "force_rx" in w.calls


def test_force_rx_repeated_every_pass_while_rig_keeps_transmitting(tmp_path):
    w = W(tmp_path)
    w.cut_works = False
    w.rig = RigProbe(True, True, FREQ)
    w.run(4)
    assert w.calls.count("force_rx") >= 8


# --------------------------------------------------------------------------- échelle de reprise

def first_times(w, names):
    return [w.calls.index(n) for n in names]


def test_ineffective_cut_escalates_in_order_with_pauses_then_safe_mode(tmp_path):
    w = W(tmp_path)
    w.cut_works = False
    w.heals = False                               # la passerelle ne revient pas
    w.rig = RigProbe(True, True, FREQ)
    w.freeze_gateway()
    stamps = []
    for _ in range(round(200 / 0.25)):
        before = len(w.calls)
        w.tick()
        for name in w.calls[before:]:
            if name in {"restart_gateway", "restart_rigctld", "reset_usb", "reboot"}:
                stamps.append((name, w.now))
    names = [n for n, _ in stamps]
    assert names[:4] == ["restart_gateway", "restart_rigctld", "reset_usb", "reboot"]
    assert all(b - a >= 19.5 for (_, a), (_, b) in zip(stamps, stamps[1:]))   # recovery_wait_s = 20
    assert names.count("reboot") == 3                                          # 3 par heure maximum
    assert w.store.safe_mode() is not None and "stop_gateway" in w.calls


def test_zero_reboot_budget_goes_straight_to_safe_mode(tmp_path):
    w = W(tmp_path, max_reboots_per_hour=0)
    w.cut_works = False
    w.heals = False
    w.rig = RigProbe(True, True, FREQ)
    w.freeze_gateway()
    w.run(120)
    assert "reboot" not in w.calls and w.store.safe_mode() is not None


def test_reboot_history_survives_supervisor_restart(tmp_path):
    w = W(tmp_path, max_reboots_per_hour=1)
    w.store.add_reboot(w.wall - 600)              # un reboot il y a 10 minutes
    w.cut_works = False
    w.heals = False
    w.rig = RigProbe(True, True, FREQ)
    w.freeze_gateway()
    w.run(120)
    assert "reboot" not in w.calls and w.store.safe_mode() is not None


def test_old_reboots_do_not_count(tmp_path):
    w = W(tmp_path, max_reboots_per_hour=1)
    w.store.add_reboot(w.wall - 7200)
    w.cut_works = False
    w.heals = False
    w.rig = RigProbe(True, True, FREQ)
    w.freeze_gateway()
    w.run(75)
    assert "reboot" in w.calls and w.store.safe_mode() is None


def test_unwritable_reboot_history_forbids_reboot(tmp_path):
    w = W(tmp_path, max_reboots_per_hour=3)
    w.cut_works = False
    w.heals = False
    w.rig = RigProbe(True, True, FREQ)
    w.freeze_gateway()

    def broken(_):
        raise OSError("disque en lecture seule")
    w.store.add_reboot = broken
    w.run(100)
    assert "reboot" not in w.calls and "stop_gateway" in w.calls


def test_safe_mode_persists_and_keeps_gateway_stopped(tmp_path):
    w = W(tmp_path)
    w.store.set_safe_mode("test")
    report = w.run(0.25)[0]
    assert report.safe_mode and "stop_gateway" in w.calls
    w.gateway_up = True                           # systemd l'a relancée malgré tout
    w.calls.clear()
    w.run(20)
    assert "stop_gateway" not in w.calls          # au plus une fois toutes les 30 s
    w.run(15)
    assert w.calls.count("stop_gateway") == 1
    assert not {"restart_gateway", "restart_rigctld", "reboot"} & set(w.calls)
    w.rig = RigProbe(True, True, FREQ)            # le poste émet : coupé à chaque passage
    w.calls.clear()
    w.run(1)
    assert "force_rx" in w.calls
    # un nouveau superviseur (redémarré) reste en mode sûr
    again = w.make_supervisor(StateStore(tmp_path))
    assert again.step().safe_mode
    w.store.clear_safe_mode()
    w.gateway_up = True
    w.calls.clear()
    w.run(10)
    assert w.calls == []


def test_ladder_level_resets_after_healthy_period(tmp_path):
    w = W(tmp_path)
    w.run(2)
    w.freeze_gateway()
    w.run(3)
    assert "restart_gateway" in w.calls
    w.calls.clear()
    w.run(130)                                    # sain plus de healthy_reset_s (120 s)
    w.freeze_gateway()
    w.run(4)
    assert "restart_gateway" in w.calls and "restart_rigctld" not in w.calls


# --------------------------------------------------------------------------- santé du système

def test_rigctld_down_restarts_rigctld_not_the_gateway(tmp_path):
    w = W(tmp_path)
    w.rig = RigProbe(False, error="connexion refusée")
    w.run(4)
    assert w.calls == []
    w.run(2.5)
    assert w.calls == ["restart_rigctld"]
    w.rig = RigProbe(True, False, FREQ)
    w.calls.clear()
    w.run(10)
    assert w.calls == []


def test_rigctld_lost_during_tx_is_restarted_immediately(tmp_path):
    w = W(tmp_path)
    w.gateway_transmitting()
    w.run(1)
    w.rig = RigProbe(False, error="connexion refusée")
    reports = w.run(0.25)
    assert "rigctld_down_during_tx" in reports[0].problems and w.calls == ["restart_rigctld"]


def test_startup_grace_period(tmp_path):
    w = W(tmp_path, startup_grace_s=30.0)
    w.gateway_up = False                          # passerelle pas encore démarrée
    w.rig = RigProbe(False, error="pas encore prêt")
    w.run(29)
    assert w.calls == []
    w.run(8)
    assert w.calls                                # le délai de grâce est écoulé


def test_unexplained_tx_is_cut_even_during_startup_grace(tmp_path):
    w = W(tmp_path, startup_grace_s=300.0)
    w.gateway_up = False
    w.rig = RigProbe(True, True, FREQ)
    w.run(1)
    assert "force_rx" in w.calls


def test_rig_switched_off_is_awaited_never_escalated_to_safe_mode(tmp_path):
    """Poste éteint au démarrage du PC (cas réel, Debian 13) : avant, l'échelle menait au mode sûr en une minute."""
    w = W(tmp_path, real_rig=True, max_reboots_per_hour=0)
    w.port_present, w.gateway_up = False, False
    w.rig = RigProbe(False, error="TimeoutError('timed out')")
    w.run(600)                                                       # dix minutes poste éteint
    assert w.calls == [] and w.store.safe_mode() is None
    assert "Problème : rig_absent" in w.alerts and "MODE SÛR" not in w.alerts
    w.port_present, w.gateway_up = True, True                       # poste rallumé : rigctld relancé par la reprise normale
    w.run(30)
    assert "restart_rigctld" in w.calls and w.store.safe_mode() is None


def test_rig_lost_while_transmitting_still_escalates(tmp_path):
    w = W(tmp_path, real_rig=True)
    w.gateway_transmitting()
    w.run(1)
    w.port_present = False
    w.rig = RigProbe(False, error="perdu")                           # dernier état connu : émission
    w.run(5)
    assert any(c in w.calls for c in ("restart_rigctld", "kill_gateway", "reset_usb"))


def test_cpu_hot_only_alerts(tmp_path):
    w = W(tmp_path)
    w.temp = 85.0
    w.run(10)
    assert w.calls == [] and "Problème : cpu_hot" in w.alerts


def test_alerts_are_not_repeated_and_recovery_is_announced(tmp_path):
    w = W(tmp_path)
    w.heals = False
    w.run(2)
    w.freeze_gateway()
    w.run(100)
    assert w.alerts.count("Problème : gateway_silent") == 1
    w.gateway_up, w.frozen = True, False
    w.run(5)
    assert "Station rétablie" in w.alerts


# --------------------------------------------------------------------------- robustesse

@pytest.mark.parametrize("name", ["force_rx", "kill_gateway", "restart_gateway"])
def test_failing_actions_never_crash_the_supervisor(tmp_path, name):
    w = W(tmp_path)
    w.boom = {name}
    w.cut_works = False                           # émission qui résiste : l'échelle de reprise est sollicitée
    w.rig = RigProbe(True, True, FREQ)
    w.run(10)                                     # ne doit lever aucune exception
    assert name in w.calls


def test_probe_and_status_exceptions_are_contained(tmp_path):
    w = W(tmp_path)

    def broken_probe():
        raise RuntimeError("sonde en panne")

    def broken_status():
        raise RuntimeError("fichier d'état en panne")
    w.sup.probe_rig, w.sup.read_status = broken_probe, broken_status
    w.run(10)
    assert "rigctld_down" in w.sup.step().problems


# --------------------------------------------------------------------------- configuration

def test_supervisor_settings_validation_and_roundtrip(tmp_path):
    cfg = dummy_config()
    cfg.supervisor.allow_local_tx = True
    cfg.supervisor.notify_url = "https://ntfy.sh/exemple"
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert cfgmod.load(path) == cfg
    for field, value in (("stale_after_s", 0.1), ("recovery_wait_s", 0), ("notify_url", "ftp://x"),
                         ("status_path", "")):
        bad = dummy_config()
        setattr(bad.supervisor, field, value)
        assert any("[supervisor]" in p for p in cfgmod.validate(bad)), field
