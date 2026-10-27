"""Modules branchés dans la passerelle et le superviseur (sans aiortc ni vrai poste)."""
import asyncio
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.gateway.cat import RigState
from trxstation.gateway.safety import Refused
from trxstation.modules.client import ModuleClient, RequestFailed
from trxstation.modules.gateway_bridge import ModuleBridge
from trxstation.modules.keys import key_path, load_or_create_key, module_secret
from trxstation.modules.launcher import RUNNING
from trxstation.modules.supervisor_glue import build_launcher, make_tick, start_modules

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Snap:
    state: str = "RX"


class FakeCtrl:
    """Doublure du PttController : mêmes points d'accroche, refus configurables."""

    def __init__(self):
        self.snap, self.listeners, self.calls, self.refuse = Snap(), [], [], None

    def snapshot(self):
        return self.snap

    def add_listener(self, cb):
        self.listeners.append(cb)

    def set_ptt(self, state):
        self.snap = Snap(state)
        for cb in self.listeners:
            cb(self.snap)

    async def set_mode(self, mode, passband_hz=0):
        if self.refuse:
            raise Refused(self.refuse)
        self.calls.append(("mode", mode))

    async def set_frequency(self, hz):
        if self.refuse:
            raise Refused(self.refuse)
        self.calls.append(("freq", hz))


class FakeLink:
    def __init__(self):
        self.state = RigState(connected=True, frequency_hz=14_074_000, mode="PKTUSB")
        self.listeners = []

    def add_listener(self, cb):
        self.listeners.append(cb)

    def change(self, **kw):
        for k, v in kw.items():
            setattr(self.state, k, v)
        for cb in self.listeners:
            cb(self.state)


class FakeSession:
    def __init__(self, broken=False):
        self.sent, self.broken = [], broken

    def send(self, message):
        if self.broken:
            raise RuntimeError("canal fermé")
        self.sent.append(message)


def make_cfg(tmp_path, run=("demo",), extra=True):
    cfg = cfgmod.Config()
    cfg.rig.model = cfgmod.DUMMY_MODEL
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    cfg.modules.run = list(run)
    if extra:                                      # module « qsyfactice » avec le droit de QSY
        folder = tmp_path / "extra" / "qsyfactice"
        folder.mkdir(parents=True)
        (folder / "manifest.toml").write_text(
            '[module]\nname = "qsyfactice"\nversion = "0.1.0"\napi = "1.0"\nentry = "x.y"\n'
            '[rights]\nevents = ["ptt", "freq_mode"]\ncommands = ["qsy"]\nclient_messages = true\n',
            encoding="utf-8")
        cfg.modules.extra_dir = str(tmp_path / "extra")
    return cfg


async def wait_until(pred, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return pred()


async def connect(bridge, cfg, name):
    key = load_or_create_key(key_path(cfg.supervisor.state_dir))
    client = ModuleClient(name, module_secret(key, name), port=bridge.bus.port, heartbeat_s=0.05)
    task = asyncio.ensure_future(client.run_session())
    await asyncio.wait_for(client.connected.wait(), 2)
    assert await wait_until(lambda: name in bridge.bus.sessions)
    return client, task


async def disconnect(client, task, bridge):
    client.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await bridge.stop()


# ------------------------------------------------------------------ passerelle

def test_sans_modules_demandes_pas_de_bus(tmp_path):
    async def scenario():
        bridge = ModuleBridge(make_cfg(tmp_path, run=(), extra=False), FakeCtrl(), FakeLink(), port=0)
        assert await bridge.start() is False and bridge.bus is None
        assert not key_path(tmp_path / "etat").exists()          # rien n'est créé
        await bridge.stop()
    asyncio.run(scenario())


def test_evenements_ptt_frequence_et_poste_publies(tmp_path):
    async def scenario():
        cfg, ctrl, link = make_cfg(tmp_path), FakeCtrl(), FakeLink()
        bridge = ModuleBridge(cfg, ctrl, link, port=0)
        assert await bridge.start()
        client, task = await connect(bridge, cfg, "demo")
        got = []
        client.on_event = lambda n, d: got.append((n, d))
        assert (await client.get_state()) == {"ptt": False, "ptt_state": "RX", "freq": 14_074_000,
                                              "mode": "PKTUSB", "trx_connected": True}
        ctrl.set_ptt("KEYING")                 # prise d'émission : la vidéo doit déjà se mettre en pause
        ctrl.set_ptt("TX")
        ctrl.set_ptt("RX")
        link.change(frequency_hz=7_074_000)
        link.change(strength_db=-20)           # sans changement de fréquence ni de mode : rien
        link.change(connected=False)
        assert await wait_until(lambda: len(got) >= 5)
        await asyncio.sleep(0.05)
        assert got == [("ptt", {"active": True, "state": "KEYING"}),
                       ("ptt", {"active": True, "state": "TX"}),
                       ("ptt", {"active": False, "state": "RX"}),
                       ("freq_mode", {"freq": 7_074_000, "mode": "PKTUSB"}),
                       ("trx_state", {"connected": False})]
        await disconnect(client, task, bridge)
    asyncio.run(scenario())


def test_qsy_passe_par_le_ptt_controller(tmp_path):
    async def scenario():
        cfg, ctrl = make_cfg(tmp_path, run=("qsyfactice",)), FakeCtrl()
        bridge = ModuleBridge(cfg, ctrl, FakeLink(), port=0)
        assert await bridge.start()
        client, task = await connect(bridge, cfg, "qsyfactice")
        assert await client.command("qsy", freq=7_074_000, mode="PKTLSB") == {"freq": 7_074_000, "mode": "PKTLSB"}
        assert ctrl.calls == [("mode", "PKTLSB"), ("freq", 7_074_000)]
        ctrl.calls.clear()
        await client.command("qsy", freq=14_075_000, mode="PKTUSB")   # même mode : fréquence seule
        assert ctrl.calls == [("freq", 14_075_000)]
        await disconnect(client, task, bridge)
    asyncio.run(scenario())


def test_qsy_refuse_pendant_lemission_et_refus_du_controleur_transmis(tmp_path):
    async def scenario():
        cfg, ctrl = make_cfg(tmp_path, run=("qsyfactice",)), FakeCtrl()
        bridge = ModuleBridge(cfg, ctrl, FakeLink(), port=0)
        assert await bridge.start()
        client, task = await connect(bridge, cfg, "qsyfactice")
        for state in ("KEYING", "TX", "UNKEYING"):
            ctrl.set_ptt(state)
            with pytest.raises(RequestFailed) as exc:
                await client.command("qsy", freq=7_074_000)
            assert exc.value.code == "ptt_active"
        assert ctrl.calls == []
        ctrl.set_ptt("RX")
        ctrl.refuse = "tx_active"              # le contrôleur a le dernier mot
        with pytest.raises(RequestFailed) as exc:
            await client.command("qsy", freq=7_074_000)
        assert exc.value.code == "tx_active"
        await disconnect(client, task, bridge)
    asyncio.run(scenario())


@pytest.mark.parametrize("params", [{"freq": "7074000"}, {"freq": True}, {"freq": 50},
                                    {"freq": 7_074_000, "mode": "USB;rm"}, {}])
def test_qsy_parametres_invalides(tmp_path, params):
    async def scenario():
        cfg, ctrl = make_cfg(tmp_path, run=("qsyfactice",)), FakeCtrl()
        bridge = ModuleBridge(cfg, ctrl, FakeLink(), port=0)
        assert await bridge.start()
        client, task = await connect(bridge, cfg, "qsyfactice")
        with pytest.raises(RequestFailed) as exc:
            await client.command("qsy", **params)
        assert exc.value.code == "invalid" and ctrl.calls == []
        await disconnect(client, task, bridge)
    asyncio.run(scenario())


def test_module_sans_droit_de_qsy_refuse(tmp_path):
    async def scenario():
        cfg, ctrl = make_cfg(tmp_path), FakeCtrl()
        bridge = ModuleBridge(cfg, ctrl, FakeLink(), port=0)
        assert await bridge.start()
        client, task = await connect(bridge, cfg, "demo")
        with pytest.raises(RequestFailed) as exc:
            await client.command("qsy", freq=7_074_000)
        assert exc.value.code == "forbidden" and ctrl.calls == []
        await disconnect(client, task, bridge)
    asyncio.run(scenario())


def test_messages_des_modules_relayes_aux_clients(tmp_path):
    async def scenario():
        cfg = make_cfg(tmp_path)
        ok, broken = FakeSession(), FakeSession(broken=True)
        bridge = ModuleBridge(cfg, FakeCtrl(), FakeLink(), clients=lambda: [broken, ok], port=0)
        assert await bridge.start()
        client, task = await connect(bridge, cfg, "demo")
        await client.client_message(text="Démo en pause pendant l'émission", paused=True)
        assert ok.sent == [{"type": "module", "module": "demo",
                            "data": {"text": "Démo en pause pendant l'émission", "paused": True}}]
        await disconnect(client, task, bridge)
    asyncio.run(scenario())


def test_port_occupe_la_station_continue_sans_modules(tmp_path):
    async def scenario():
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            bridge = ModuleBridge(make_cfg(tmp_path), FakeCtrl(), FakeLink(), port=port)
            assert await bridge.start() is False and bridge.bus is None
            await bridge.stop()
    asyncio.run(scenario())


def test_ecouteurs_inertes_apres_arret(tmp_path):
    async def scenario():
        ctrl, link = FakeCtrl(), FakeLink()
        bridge = ModuleBridge(make_cfg(tmp_path), ctrl, link, port=0)
        assert await bridge.start()
        await bridge.stop()
        await bridge.stop()                    # idempotent
        ctrl.set_ptt("TX")                     # ne lève rien
        link.change(frequency_hz=7_000_000)
    asyncio.run(scenario())


def test_la_passerelle_branche_le_pont():
    source = (ROOT / "trxstation" / "gateway" / "main.py").read_text(encoding="utf-8")
    assert "await bridge.start()" in source
    # Le pont s'arrête AVANT la coupure de l'émission, et ne peut pas l'empêcher (stop ne lève pas).
    assert source.index("await bridge.stop()") < source.index("await ctrl.close()")


# ------------------------------------------------------------------ superviseur

def test_superviseur_sans_modules_rien_ne_change(tmp_path):
    maintain = lambda: None
    assert build_launcher(make_cfg(tmp_path, run=(), extra=False)) is None
    assert make_tick(maintain, None) is maintain
    start_modules(None)


def test_erreur_des_modules_ninterrompt_pas_la_supervision(tmp_path):
    calls = []

    class Broken:
        def check(self):
            raise RuntimeError("bug du lanceur")

    tick = make_tick(lambda: calls.append("station"), Broken())
    tick()
    tick()
    assert calls == ["station", "station"]


def test_superviseur_attend_la_cle_de_la_passerelle_puis_lance(tmp_path):
    cfg = make_cfg(tmp_path)
    (tmp_path / "etat").mkdir()
    alerts = []
    la = build_launcher(cfg, alert=lambda t, m: alerts.append((t, m)), is_root=lambda: False,
                        command_override=lambda m: [sys.executable, "-c", "import time; time.sleep(30)"])
    assert set(la.modules) == {"demo"}
    start_modules(la)
    assert la.pending == {"demo"}                          # la passerelle n'a pas encore créé la clé
    key = load_or_create_key(key_path(cfg.supervisor.state_dir))
    la.check()
    mp = la.modules["demo"]
    assert mp.state == RUNNING
    assert la.env_for(mp.manifest)["TRX_MODULE_SECRET"] == module_secret(key, "demo")
    la.stop_all()


def test_le_superviseur_branche_les_modules():
    source = (ROOT / "trxstation" / "supervisor" / "main.py").read_text(encoding="utf-8")
    assert "make_tick(backend.maintain, launcher)" in source and "launcher.stop_all()" in source


# ------------------------------------------------------------------ bout en bout

def test_bout_en_bout_module_demo_reel(tmp_path):
    """Superviseur (lanceur) + passerelle (pont) + vrai module factice en processus séparé."""
    async def scenario():
        cfg, ctrl, link = make_cfg(tmp_path, extra=False), FakeCtrl(), FakeLink()
        session = FakeSession()
        bridge = ModuleBridge(cfg, ctrl, link, clients=lambda: [session], port=0)
        assert await bridge.start()                        # crée la clé
        cfg.modules.bus_port = bridge.bus.port
        la = build_launcher(cfg, is_root=lambda: False)
        start_modules(la)
        texts = lambda: [m["data"].get("text") for m in session.sent]
        try:
            assert await wait_until(lambda: "demo" in bridge.bus.sessions, timeout=20)
            ctrl.set_ptt("KEYING")
            assert await wait_until(lambda: "Démo en pause pendant l'émission" in texts(), 10)
            ctrl.set_ptt("RX")
            assert await wait_until(lambda: "Démo reprise" in texts(), 10)
            pid = la.modules["demo"].proc.pid
            la.modules["demo"].proc.kill()                 # plantage brutal du module
            assert await wait_until(lambda: "demo" not in bridge.bus.sessions, 10)
            ctrl.set_ptt("TX")                             # la passerelle continue sans lui
            for _ in range(100):
                la.check()
                if "demo" in bridge.bus.sessions:
                    break
                await asyncio.sleep(0.2)
            assert "demo" in bridge.bus.sessions and la.modules["demo"].proc.pid != pid
            # Reconnecté pendant l'émission : il relit l'état et se met en pause.
            assert await wait_until(lambda: texts().count("Démo en pause pendant l'émission") >= 2, 10)
        finally:
            la.stop_all()
            await bridge.stop()

    old = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(ROOT) + (os.pathsep + old if old else "")
    try:
        asyncio.run(scenario())
    finally:
        if old is None:
            del os.environ["PYTHONPATH"]
        else:
            os.environ["PYTHONPATH"] = old
