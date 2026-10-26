"""Lanceur des modules (superviseur) : relance, désactivation, clé attendue, jamais en root."""
import os
import sys
import time
from pathlib import Path

import pytest

from trxstation.modules.launcher import (DISABLED, INCOMPATIBLE, RUNNING, STOPPED, WAITING,
                                         ModuleLauncher, RestartPolicy, generate_systemd_unit)
from trxstation.modules.manifest import parse_manifest

SLEEP = "import time; time.sleep(30)"


def make_manifest(name="demo", api="1.0", start="auto"):
    return parse_manifest({"module": {"name": name, "version": "0.1.0", "api": api,
                                      "entry": "trxstation.modules.demo_module", "start": start}})


def launcher_with(code: str, secrets=None, **kw):
    notes = []
    kw.setdefault("is_root", lambda: False)        # le bac à sable de test peut tourner en root
    la = ModuleLauncher([make_manifest("demo")], {"demo": "s"} if secrets is None else secrets,
                        bus_port=1, command_override=lambda _m: [sys.executable, "-c", code],
                        notify=lambda n, st, msg: notes.append((n, st, msg)), **kw)
    return la, notes


def wait_exit(la, name="demo", timeout=5):
    end = time.monotonic() + timeout
    proc = la.modules[name].proc
    while proc is not None and proc.poll() is None and time.monotonic() < end:
        time.sleep(0.02)


def test_module_qui_plante_est_relance_avec_delai_croissant():
    la, notes = launcher_with("raise SystemExit(3)", policy=RestartPolicy(first_delay_s=1, max_delay_s=8))
    assert la.start("demo")
    wait_exit(la)
    la.check(now=100.0)
    mp = la.modules["demo"]
    assert mp.state == WAITING and mp.delay_s == 1 and mp.last_exit == 3
    la.check(now=101.0)
    assert mp.state == RUNNING
    wait_exit(la)
    la.check(now=102.0)
    assert mp.delay_s == 2
    assert any("code 3" in msg for _, _, msg in notes)
    la.stop_all()


def test_module_desactive_apres_trop_de_plantages():
    la, notes = launcher_with("raise SystemExit(1)", policy=RestartPolicy(first_delay_s=0.01, max_restarts=2))
    la.start("demo")
    t = 10.0
    for _ in range(6):
        wait_exit(la)
        la.check(now=t)
        t += 1
        la.check(now=t)
        if la.modules["demo"].state == DISABLED:
            break
    assert la.modules["demo"].state == DISABLED
    assert any("désactivé" in msg for _, _, msg in notes)
    la.stop_all()


def test_reactivation_par_lutilisateur():
    la, _ = launcher_with(SLEEP)
    la.modules["demo"].state = DISABLED
    assert not la.start("demo")                    # un module désactivé ne repart pas tout seul
    assert la.enable("demo") and la.modules["demo"].state == RUNNING
    la.stop("demo")
    assert la.modules["demo"].proc is None


def test_module_stable_remet_le_delai_a_zero():
    la, _ = launcher_with(SLEEP, policy=RestartPolicy(stable_after_s=5))
    la.start("demo")
    mp = la.modules["demo"]
    mp.delay_s = 8
    la.check(now=mp.started_at + 6)
    assert mp.delay_s == 0
    la.stop_all()


def test_module_incompatible_jamais_lance():
    notes = []
    la = ModuleLauncher([make_manifest("vieux", api="2.0")], {"vieux": "s"}, bus_port=1,
                        notify=lambda n, st, msg: notes.append(msg))
    assert la.modules["vieux"].state == INCOMPATIBLE and not la.start("vieux")
    assert notes and "API" in notes[0]


def test_lancement_differe_tant_que_la_cle_nexiste_pas():
    box = {"secrets": None}
    la, _ = launcher_with(SLEEP, secrets=lambda: box["secrets"])
    assert not la.start("demo")
    assert la.modules["demo"].state == STOPPED and la.pending == {"demo"}
    la.check()
    assert la.modules["demo"].state == STOPPED          # toujours pas de clé
    box["secrets"] = {"demo": "s"}                       # la passerelle a créé la clé
    la.check()
    assert la.modules["demo"].state == RUNNING and not la.pending
    assert la.env_for(la.modules["demo"].manifest)["TRX_MODULE_SECRET"] == "s"
    la.stop_all()


def test_superviseur_root_sans_compte_ne_lance_jamais_en_root():
    la, notes = launcher_with(SLEEP, is_root=lambda: True, run_as="trx", user_exists=lambda u: False)
    if os.name == "nt":
        pytest.skip("pas de compte root sous Windows")
    assert not la.start("demo")
    assert la.modules["demo"].state == DISABLED and la.modules["demo"].proc is None
    assert any("jamais en root" in msg for _, _, msg in notes)


@pytest.mark.parametrize("run_as", ["", "root"])
def test_superviseur_root_avec_compte_vide_ou_root_refuse(run_as):
    if os.name == "nt":
        pytest.skip("pas de compte root sous Windows")
    la, _ = launcher_with(SLEEP, is_root=lambda: True, run_as=run_as, user_exists=lambda u: True)
    assert not la.start("demo") and la.modules["demo"].proc is None


def test_start_auto_respecte_le_mode_de_demarrage():
    la = ModuleLauncher([make_manifest("auto1"), make_manifest("manu1", start="on_demand")],
                        {"auto1": "s", "manu1": "s"}, bus_port=1, is_root=lambda: False,
                        command_override=lambda m: [sys.executable, "-c", SLEEP])
    la.start_auto()
    assert la.modules["auto1"].state == RUNNING and la.modules["manu1"].state != RUNNING
    la.stop_all()


def test_secret_transmis_par_lenvironnement_pas_par_la_ligne_de_commande():
    la, _ = launcher_with("pass")
    m = la.modules["demo"].manifest
    la._refresh_secrets()
    assert "s" not in la.command_for(m)
    env = la.env_for(m)
    assert env["TRX_MODULE_SECRET"] == "s" and env["TRX_BUS_PORT"] == "1"


def test_unite_systemd_avec_plafonds():
    unit = generate_systemd_unit(make_manifest("video"), python="/usr/bin/python3",
                                 workdir=Path("/opt/trx"), env_file=Path("/etc/trx/video.env"),
                                 user="trx", core_unit="trx-gateway.service")
    assert "CPUQuota=25%" in unit and "MemoryMax=256M" in unit and "Nice=10" in unit
    assert "ExecStart=/usr/bin/python3 -m trxstation.modules.demo_module" in unit
    assert "EnvironmentFile=/etc/trx/video.env" in unit and "SECRET" not in unit
    assert "StartLimitBurst=5" in unit.split("[Service]")[0]


def test_unite_systemd_generee_depuis_windows_en_chemins_linux():
    from pathlib import PureWindowsPath
    unit = generate_systemd_unit(make_manifest("video"), python="/usr/bin/python3",
                                 workdir=PureWindowsPath("/opt/trx"),
                                 env_file=PureWindowsPath("/etc/trx/video.env"))
    assert "WorkingDirectory=/opt/trx" in unit and "EnvironmentFile=/etc/trx/video.env" in unit
    assert "\\" not in unit
