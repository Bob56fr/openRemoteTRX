"""trx-monitor : tout ce qui ne dépend pas de Textual est testé ici ; le test de fumée de
l'interface ne tourne que si Textual est installé (sinon il ne fait rien)."""
import asyncio
import contextlib
import io
import sys
import threading

from trxstation import config as cfgmod
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.monitor.actions import stop_tx
from trxstation.monitor.main import main
from trxstation.monitor.model import (EventLog, Snapshot, SystemInfo, build_panels, format_duration,
                                      format_frequency, render_plain, s_meter_bar, s_meter_text)
from trxstation.monitor.source import StatusSource, read_system_info
from trxstation.setup_wizard import dummy_config
from trxstation.status import GatewayStatus, write_status
from trxstation.supervisor.state import StateStore


def status(state="RX", owner=None, clients=(), fault="", cut="", remaining=None, warn=False,
           connected=True, freq=14_200_000, strength=-12, seq=1, pid=42):
    return GatewayStatus(
        pid=pid, seq=seq, written_at=0.0,
        ptt={"state": state, "owner": owner, "fault": fault, "last_cut_reason": cut,
             "tot_remaining_s": remaining, "tot_warning": warn},
        rig={"connected": connected, "frequency_hz": freq, "mode": "USB", "passband_hz": 2400,
             "strength_db": strength, "last_error": ""},
        clients=list(clients))


def snap(st, fresh=True, stale_s=0.5, safe=None, system=SystemInfo()):
    return Snapshot(status=st, gateway_fresh=fresh, stale_s=stale_s, safe_mode=safe, system=system)


def panel(snapshot, key):
    return {p.key: p for p in build_panels(snapshot)}[key]


def row(p, label):
    return next(r for r in p.rows if r.label == label)


# --------------------------------------------------------------------------- formats

def test_formats():
    assert format_frequency(14_200_000) == "14 200 000 Hz" and format_frequency(7_074_000) == "7 074 000 Hz"
    assert format_frequency(None) == "--"
    assert [s_meter_text(v) for v in (None, 0, 20, -6, -48, -54, -100)] == ["--", "S9", "S9+20 dB", "S8", "S1", "S0", "S0"]
    assert s_meter_bar(None) == "░" * 20 and s_meter_bar(60) == "█" * 20 and s_meter_bar(-90) == "░" * 20
    bars = [s_meter_bar(v).count("█") for v in range(-54, 61, 6)]
    assert bars == sorted(bars) and all(len(s_meter_bar(v)) == 20 for v in range(-60, 70, 10))
    assert format_duration(None) == "--" and format_duration(3 * 3600 + 5 * 60) == "3 h 05 min"
    assert format_duration(2 * 86400 + 60) == "2 j 0 h 01 min"


# --------------------------------------------------------------------------- panneaux

def test_radio_panel_in_reception():
    p = panel(snap(status()), "radio")
    assert (row(p, "PTT").text, row(p, "PTT").level) == ("RÉCEPTION", "ok")
    assert row(p, "Fréquence").text == "14 200 000 Hz" and row(p, "Mode").text == "USB"
    assert row(p, "Filtre").text == "2400 Hz" and row(p, "S-mètre").text.startswith("S7")
    assert not any(r.label == "TOT" for r in p.rows)


def test_radio_panel_in_transmission_with_tot_warning():
    p = panel(snap(status("TX", owner="phone", remaining=8.4, warn=True)), "radio")
    assert (row(p, "PTT").text, row(p, "PTT").level) == ("ÉMISSION", "bad")
    assert (row(p, "TOT").text, row(p, "TOT").level) == ("8 s restantes", "warn")
    p = panel(snap(status("TX", owner="phone", remaining=60)), "radio")
    assert row(p, "TOT").level == "info"


def test_stale_data_is_never_shown_as_live():
    p = panel(snap(status("TX", owner="phone"), fresh=False, stale_s=5), "radio")
    assert row(p, "PTT").text == "ÉMISSION ?" and row(p, "PTT").level == "bad"
    assert row(p, "Fréquence").level == "dim"
    p = panel(snap(status("RX"), fresh=False, stale_s=5), "radio")
    assert row(p, "PTT").text == "RÉCEPTION ?" and row(p, "PTT").level == "warn"


def test_absent_gateway():
    s = snap(None, fresh=False, stale_s=None)
    assert row(panel(s, "radio"), "Poste").level == "bad"
    assert "ABSENTE" in row(panel(s, "sante"), "Passerelle").text
    assert panel(s, "connexion").rows[0].level == "dim"


def test_sante_panel_alarms():
    p = panel(snap(status(fault="unkey_failed", connected=False), fresh=False, stale_s=5.4,
                   safe="trop de redémarrages"), "sante")
    assert row(p, "Passerelle").text.startswith("FIGÉE depuis 5 s") and row(p, "Passerelle").level == "bad"
    assert row(p, "rigctld").text == "INJOIGNABLE" and row(p, "rigctld").level == "bad"
    assert "unkey_failed" in row(p, "Défaut PTT").text and row(p, "Défaut PTT").level == "bad"
    assert row(p, "Mode sûr").text.startswith("ACTIF : trop de") and row(p, "Mode sûr").level == "bad"
    healthy = panel(snap(status()), "sante")
    assert [r.level for r in healthy.rows] == ["ok", "ok", "ok", "ok"]


def test_connexion_panel_translates_cut_reasons():
    p = panel(snap(status("TX", owner="phone", clients=("phone", "car"), cut="heartbeat")), "connexion")
    assert row(p, "Clients").text == "phone, car" and row(p, "Émetteur").text == "phone"
    assert row(p, "Dernière coupure").text == "perte du heartbeat du client"
    p = panel(snap(status(cut="raison_inconnue")), "connexion")
    assert row(p, "Dernière coupure").text == "raison_inconnue" and row(p, "Clients").text == "aucun"


def test_materiel_panel_levels():
    def temp_level(t):
        return row(panel(snap(status(), system=SystemInfo(temp_c=t)), "materiel"), "Température").level
    assert [temp_level(t) for t in (None, 50, 72, 85)] == ["dim", "ok", "warn", "bad"]
    p = panel(snap(status(), system=SystemInfo(55.0, 0.42, 812.0, 7200)), "materiel")
    assert row(p, "Charge (1 min)").text == "0.42" and row(p, "Mémoire libre").text == "812 Mo"
    assert row(p, "Disponibilité").text == "2 h 00 min"


def test_render_plain_is_aligned_and_complete():
    text = render_plain(build_panels(snap(status("TX", owner="phone", remaining=30))))
    for title in ("== Radio ==", "== Connexion ==", "== Santé ==", "== Matériel =="):
        assert title in text
    assert "  PTT       : ÉMISSION" in text and "  Fréquence : 14 200 000 Hz" in text   # libellés alignés


def test_audio_panel():
    st = status()
    assert row(panel(snap(st), "audio"), "Audio").level == "dim"                    # audio inactif : pas de donnée
    st.audio = {"rx_db": -30, "tx_db": -90, "gate_open": False, "listeners": 2, "rx_dropped": 0,
                "tx_dropped_not_owner": 0}
    p = panel(snap(st), "audio")
    assert row(p, "Porte micro").text == "fermée" and row(p, "Porte micro").level == "ok"
    assert row(p, "Auditeurs").text == "2" and "-30 dBFS" in row(p, "Réception").text
    st.audio.update(rx_frames=1500, tx_frames=240)
    assert "capturées 1500" in row(panel(snap(st), "audio"), "Trames").text and "passées au poste 240" in row(panel(snap(st), "audio"), "Trames").text
    st.audio.pop("rx_frames"), st.audio.pop("tx_frames")
    assert row(p, "Pertes").level == "dim"
    st.audio.update(gate_open=True, tx_db=-12, tx_dropped_not_owner=4)
    p = panel(snap(st), "audio")
    assert row(p, "Porte micro").text.startswith("OUVERTE") and row(p, "Porte micro").level == "bad"
    assert row(p, "Émission").level == "bad" and row(p, "Pertes").level == "warn"
    p = panel(snap(st, fresh=False), "audio")
    assert row(p, "Réception").level == "dim"                                       # donnée périmée : grisée
    assert [pn.key for pn in build_panels(snap(st))] == ["radio", "audio", "connexion", "sante", "materiel"]


# --------------------------------------------------------------------------- journal

def test_event_log_reports_changes_only():
    clock = iter(f"12:00:{i:02d}" for i in range(100))
    log = EventLog(now_text=lambda: next(clock))
    assert log.observe(snap(status())) == ["12:00:00  trx-monitor démarré"]
    assert log.observe(snap(status())) == []

    lines = log.observe(snap(status("TX", owner="phone", clients=("phone",))))
    assert any("PTT RX → TX (client phone)" in l for l in lines) and any("client connecté : phone" in l for l in lines)

    lines = log.observe(snap(status("RX", clients=("phone",), cut="tot")))
    assert any("PTT TX → RX" in l for l in lines) and any("coupure : TOT dépassé" in l for l in lines)
    assert log.observe(snap(status("RX", clients=("phone",), cut="tot"))) == []   # même raison : pas répétée

    lines = log.observe(snap(status("RX", clients=(), cut="tot", fault="unkey_failed", connected=False),
                             fresh=False, safe="x"))
    joined = " | ".join(lines)
    for expected in ("client déconnecté : phone", "PASSERELLE FIGÉE", "RIGCTLD INJOIGNABLE",
                     "DÉFAUT PTT : unkey_failed", "MODE SÛR ACTIVÉ : x"):
        assert expected in joined, expected
    lines = log.observe(snap(status(), fresh=True))
    assert any("passerelle active" in l for l in lines) and any("défaut PTT effacé" in l for l in lines)
    assert any("mode sûr désactivé" in l for l in lines)


def test_event_log_is_bounded():
    log = EventLog(limit=5)
    for i in range(20):
        log.observe(snap(status(clients=(f"c{i}",))))
    assert len(log.lines) == 5


# --------------------------------------------------------------------------- sources

def test_status_source_freshness_follows_seq_changes(tmp_path):
    path, now = tmp_path / "s.json", [100.0]
    source = StatusSource(path, tmp_path / "state", stale_after_s=2.0, clock=lambda: now[0],
                          system_reader=lambda: SystemInfo())
    s = source.poll()
    assert s.status is None and not s.gateway_fresh and s.stale_s is None
    write_status(path, status(seq=1))
    assert source.poll().gateway_fresh
    now[0] += 1.0
    assert source.poll().gateway_fresh                      # seq inchangé depuis 1 s : encore tolérée
    now[0] += 2.0
    s = source.poll()
    assert not s.gateway_fresh and 2.9 < s.stale_s < 3.1    # figée depuis 3 s
    write_status(path, status(seq=2))
    assert source.poll().gateway_fresh                      # elle repart
    StateStore(tmp_path / "state").set_safe_mode("test")
    assert source.poll().safe_mode == "test"


def test_poll_once_detects_frozen_gateway(tmp_path):
    path = tmp_path / "s.json"
    write_status(path, status(seq=1))
    frozen = StatusSource(path, tmp_path / "st", sleep=lambda s: None, system_reader=lambda: SystemInfo())
    s = frozen.poll_once(0.6)
    assert not s.gateway_fresh and s.stale_s == 0.6

    def advance(_):
        write_status(path, status(seq=2))                   # la passerelle écrit pendant l'attente
    alive = StatusSource(path, tmp_path / "st", sleep=advance, system_reader=lambda: SystemInfo())
    s = alive.poll_once(0.6)
    assert s.gateway_fresh and s.status.seq == 2
    missing = StatusSource(tmp_path / "absent.json", tmp_path / "st", sleep=lambda s: None,
                           system_reader=lambda: SystemInfo())
    assert missing.poll_once().status is None


def test_read_system_info(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text("MemTotal: 4000000 kB\nMemAvailable: 2048000 kB\n")
    (proc / "loadavg").write_text("0.35 0.20 0.10 1/200 999\n")
    (proc / "uptime").write_text("3600.55 7000.1\n")
    thermal = tmp_path / "temp"
    thermal.write_text("47500\n")
    info = read_system_info(str(proc), str(thermal))
    assert (info.temp_c, info.load1, info.mem_available_mb, info.uptime_s) == (47.5, 0.35, 2000.0, 3600.55)
    empty = read_system_info(str(tmp_path / "rien"), str(tmp_path / "rien"))
    assert empty == SystemInfo()


# --------------------------------------------------------------------------- STOP TX

class ServerThread:
    def __init__(self):
        self.fake, self.loop, self.thread = FakeRigctld(), None, None

    def start(self):
        ready = threading.Event()

        def target():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.fake.start())
            ready.set()
            self.loop.run_forever()
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        assert ready.wait(5)
        return self

    def stop(self):
        asyncio.run_coroutine_threadsafe(self.fake.stop(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


def test_stop_tx_cuts_transmission_and_reports_failure():
    srv = ServerThread().start()
    try:
        cfg = dummy_config()
        cfg.network.rigctld_port = srv.fake.port
        srv.fake.ptt = 1
        ok, message = stop_tx(cfg)
        assert ok and srv.fake.ptt == 0 and "PTT coupé" in message
        assert srv.fake.ptt_commands == [0]                     # ne sait envoyer que « T 0 »
        srv.fake.ptt, srv.fake.ignore_unkey = 1, True
        ok, message = stop_tx(cfg)
        assert not ok and "ÉCHEC" in message
    finally:
        srv.stop()
    cfg.network.rigctld_port = 1
    assert stop_tx(cfg)[0] is False


# --------------------------------------------------------------------------- ligne de commande

def _config_file(tmp_path):
    cfg = dummy_config()
    cfg.supervisor.status_path = str(tmp_path / "status.json")
    cfg.supervisor.state_dir = str(tmp_path / "state")
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return path


def test_main_once_prints_snapshot(tmp_path):
    config = _config_file(tmp_path)
    write_status(tmp_path / "status.json", status("RX", clients=("phone",)))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["--once", "--config", str(config)])
    text = out.getvalue()
    assert code == 0 and "== Radio ==" in text and "14 200 000 Hz" in text
    assert "FIGÉE" in text                                    # personne n'écrit : seq ne bouge pas


def test_main_rejects_invalid_config(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[rig]\nmodel = 0\n", encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert main(["--once", "--config", str(bad)]) == 2
    assert "Configuration invalide" in err.getvalue()


def test_main_without_textual_explains_how_to_install(tmp_path):
    config = _config_file(tmp_path)
    saved = sys.modules.get("trxstation.monitor.app", "absent")
    sys.modules["trxstation.monitor.app"] = None              # force ImportError, Textual installé ou non
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            assert main(["--config", str(config)]) == 3
    finally:
        if saved == "absent":
            del sys.modules["trxstation.monitor.app"]
        else:
            sys.modules["trxstation.monitor.app"] = saved
    assert "Textual" in err.getvalue() and "--once" in err.getvalue()


# --------------------------------------------------------------------------- interface (si Textual est installé)

def test_textual_app_smoke(tmp_path):
    """Non exécuté dans mon environnement (Textual absent) : à valider chez toi."""
    try:
        from trxstation.monitor.app import MonitorApp, render_markup
    except ImportError:
        return
    write_status(tmp_path / "status.json", status("RX", clients=("phone",)))
    source = StatusSource(tmp_path / "status.json", tmp_path / "state", system_reader=lambda: SystemInfo())
    stops = []

    def fake_stop():
        stops.append(True)
        return True, "PTT coupé"
    assert "\\[" in render_markup(panel(snap(status(clients=("a[b]",))), "connexion"))   # crochets échappés

    async def scenario():
        app = MonitorApp(source, fake_stop, interval_s=0.05)
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            await pilot.press("s")
            await pilot.pause(0.3)
        assert stops == [True]
        assert any("trx-monitor démarré" in line for line in app.events.lines)
    asyncio.run(scenario())
