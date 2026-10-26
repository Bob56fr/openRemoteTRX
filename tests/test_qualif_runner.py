"""Qualification (lot Q1) sur le faux poste : relais de trace, trois phases, sécurité, rapport.

Comme trx-hwtest, l'outil est testé avec des réponses scriptées : il ne doit rien émettre sans
confirmation, toujours rendre la réception, rétablir l'état du poste et ne jamais refuser un poste
sur une erreur d'installation.
"""
import asyncio
import json
import tomllib

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.devtools.hwtest import EMIT_WORD
from trxstation.devtools.sample_caps import SAMPLE_DUMP_CAPS
from trxstation.gateway.cat import RigctldClient
from trxstation.qualif import main as qmain
from trxstation.qualif.profile import parse_profile
from trxstation.qualif.results import INCOMPLETE, IN_VALIDATION, REFUSE, compute_verdict, latest
from trxstation.qualif.runner import Qualification
from trxstation.qualif.sheet import load_sheet, render_sheet
from trxstation.qualif.trace import TraceProxy
from trxstation.setup_wizard import dummy_config


def scripted(prompts, answers=None):
    defaults = {"OUI": "OUI", EMIT_WORD: EMIT_WORD, "plus fort": "O", "firmware": "1.10", "indique-t-il": "o",
                "maintenant": "o", "entends-tu": "o"}
    defaults.update(answers or {})

    def ask(prompt):
        prompts.append(prompt)
        for key, answer in defaults.items():
            if key in prompt:
                return answer
        return ""
    return ask


def run(tmp_path, scenario, *, answers=None, fake_setup=None, enforce_bands=True, dump=SAMPLE_DUMP_CAPS, **kwargs):
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        if fake_setup:
            fake_setup(fake)
        proxy = TraceProxy("127.0.0.1", fake.port)
        await proxy.start()
        cfg = dummy_config()
        cfg.safety.heartbeat_interval_ms, cfg.safety.heartbeat_timeout_ms = 300, 700
        cfg.safety.enforce_bands = enforce_bands
        cfg.network.rigctld_port = proxy.port
        cfg.audio.capture_device = "tone:440"
        cfg.audio.playback_device = f"file:{tmp_path / 'tx.wav'}"
        prompts, out = [], []
        params = dict(tot_s=3.0, hold_s=0.3, tx_seconds=0.6, rx_listen_s=0.6, tx_levels_db=(-40.0,), cat_timeout_s=3.0,
                      record_wav=str(tmp_path / "rx.wav"), cycles=2, endurance_cycles=100, settle_s=0.6, cat_cut_s=0.8)
        params.update(kwargs)
        q = Qualification(cfg, profile=parse_profile(dump, 3094), dump_text=dump, proxy=proxy,
                          ask=scripted(prompts, answers), out=out.append, **params)
        try:
            await asyncio.wait_for(scenario(q, fake, proxy, prompts), 120)
        finally:
            await proxy.stop()
            await fake.stop()
    asyncio.run(wrapper())


def by_id(q):
    return latest(q.checks)


# --------------------------------------------------------------------------- relais de trace

def test_trace_proxy_relays_records_and_simulates_a_cut():
    async def scenario():
        fake = FakeRigctld()
        await fake.start()
        proxy = TraceProxy("127.0.0.1", fake.port)
        await proxy.start()
        client = RigctldClient("127.0.0.1", proxy.port, timeout=1.0)
        try:
            await client.connect()
            assert await client.get_frequency() == 14_200_000
            assert any(d == ">" and "+f" in t for _, d, t in proxy.records)
            assert any(d == "<" and "Frequency: 14200000" in t for _, d, t in proxy.records)
            cut = asyncio.create_task(proxy.interrupt(0.5))
            await asyncio.sleep(0.1)
            try:
                await client.get_frequency()
                raise AssertionError("la coupure aurait dû faire tomber la liaison")
            except ConnectionError:
                pass
            client2 = RigctldClient("127.0.0.1", proxy.port, timeout=0.5)
            await client2.connect()                       # acceptée puis fermée aussitôt pendant la coupure
            try:
                await client2.get_frequency()
                raise AssertionError("connexion acceptée pendant la coupure")
            except ConnectionError:
                pass
            await cut
            await client.connect()
            assert await client.get_frequency() == 14_200_000   # rétablie
            text = proxy.render()
            assert "COUPURE SIMULÉE" in text and "LIAISON RÉTABLIE" in text
        finally:
            await client.close()
            await proxy.stop()
            await fake.stop()
    asyncio.run(scenario())


# --------------------------------------------------------------------------- déroulement complet

def test_full_qualification_of_a_healthy_rig(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        fake.freq, fake.mode, fake.passband = 7_074_000, "USB", 2400
        before_funcs, before_levels = dict(fake.funcs), dict(fake.levels)
        await q.run()
        results = by_id(q)
        verdict = compute_verdict(q.checks)
        failed = [c for c in results.values() if c.ok is False]
        assert failed == [] and verdict.status == IN_VALIDATION, (failed, verdict)
        for item in ("cat", "cat_endurance", "freq_rw", "mode_rw", "audio_rx", "ptt_cycle", "cat_loss_rx"):
            assert results[item].ok is True, item
        assert "cat_down" in results["cat_loss_rx"].detail
        assert results["write_level_RFPOWER"].ok and results["write_level_AGC"].ok and results["filters"].ok
        assert results["write_func_TUNER"].ok is None and results["usb_replug"].ok is None
        assert results["decl_freq"].ok is True and results["decl_func_NR"].ok is True
        assert results["latency"].data["polling_max_hz"] > 0
        # sécurité et remise en état
        assert fake.ptt == 0 and q.ctrl.snapshot().state == "RX" and fake.ptt_commands[-1] == 0
        assert not any(c.lstrip("+").startswith("U TUNER") for c in fake.commands)    # tuner jamais touché
        assert fake.funcs == before_funcs
        assert {k: fake.levels[k] for k in ("SQL", "AGC", "PREAMP", "RFPOWER")} == \
               {k: before_levels[k] for k in ("SQL", "AGC", "PREAMP", "RFPOWER")}
        assert max(float(c.split()[-1]) for c in fake.commands if c.lstrip("+").startswith("L RFPOWER")) <= 1.0
        assert q.firmware == "1.10"
        # rapport
        directory = q.write_report(tmp_path / "rapport")
        data = json.loads((directory / "results.json").read_text(encoding="utf-8"))
        assert data["verdict"]["statut"] == IN_VALIDATION and data["poste"]["firmware"] == "1.10"
        assert "SCOPE" in data["plan"]["disponibles_non_exploitees"]
        sheet = load_sheet(directory / "fiche.toml")
        assert sheet.statut == "validation_en_cours" and sheet.available("ptt") and sheet.fonctions["tuner"] is False
        assert "COUPURE SIMULÉE" in (directory / "cat_trace.log").read_text(encoding="utf-8")
        assert (directory / "dump_caps.txt").exists() and "BILAN" not in (directory / "journal.txt").read_text(encoding="utf-8")
        tomllib.loads((directory / "fiche.toml").read_text(encoding="utf-8"))
    run(tmp_path, scenario)


def test_the_rig_state_is_restored_after_phase_one(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        fake.freq, fake.mode, fake.passband = 14_074_000, "PKTUSB", 3000
        fake.funcs["NR"], fake.levels["SQL"] = 1, 0.45
        await q.run()
        assert (fake.freq, fake.mode, fake.passband) == (14_074_000, "PKTUSB", 3000)
        assert fake.funcs["NR"] == 1 and abs(fake.levels["SQL"] - 0.45) < 0.001
    run(tmp_path, scenario, answers={EMIT_WORD: "non"})


def test_nothing_is_transmitted_without_confirmation_and_the_result_is_incomplete(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        await q.run()
        assert 1 not in fake.ptt_commands and fake.ptt == 0
        results = by_id(q)
        assert results["ptt_cycle"].ok is None and results["cat_loss_rx"].ok is None
        assert compute_verdict(q.checks).status == INCOMPLETE
        sheet = load_sheet_from(q, tmp_path)
        assert sheet.statut == "refuse" and not sheet.usable           # incomplet = jamais utilisable
    run(tmp_path, scenario, answers={EMIT_WORD: "non"})


def load_sheet_from(q, tmp_path):
    return load_sheet(q.write_report(tmp_path / "r") / "fiche.toml")


def test_preflight_refused_touches_nothing(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        assert await q.run() == [] and fake.commands == [] and q.checks == []
    run(tmp_path, scenario, answers={"OUI": "non"})


def test_a_rig_that_ignores_frequency_commands_is_refused(tmp_path):
    def frozen(fake):
        original = fake._reply

        def reply(line):
            if line.lstrip("+").startswith("F "):
                return "set_freq: x\nRPRT 0\n"            # accepte sans rien changer
            return original(line)
        fake._reply = reply

    async def scenario(q, fake, proxy, prompts):
        await q.run()
        assert by_id(q)["freq_rw"].ok is False and compute_verdict(q.checks).status == REFUSE
    run(tmp_path, scenario, fake_setup=frozen, answers={EMIT_WORD: "non"})


def test_a_failing_optional_function_is_reported_but_does_not_refuse(tmp_path):
    def broken_nr(fake):
        original = fake._reply

        def reply(line):
            if line.lstrip("+").startswith("U NR"):
                return "set_func: NR\nRPRT 0\n"           # accepté, sans effet
            return original(line)
        fake._reply = reply

    async def scenario(q, fake, proxy, prompts):
        await q.run()
        results = by_id(q)
        assert results["write_func_NR"].ok is False and "decl_func_NR" not in results
        assert compute_verdict(q.checks).status == IN_VALIDATION
        sheet = load_sheet_from(q, tmp_path)
        assert sheet.fonctions["nr"] is False and "échec" in sheet.avertissements["nr"]
    run(tmp_path, scenario, fake_setup=broken_nr)


def test_power_outside_trx_remote_steps_is_left_untouched(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        await q.run()
        assert by_id(q)["write_level_RFPOWER"].ok is None and fake.levels["RFPOWER"] == 0.37
        assert not any(c.lstrip("+").startswith("L RFPOWER") for c in fake.commands)
    run(tmp_path, scenario, fake_setup=lambda f: f.levels.update(RFPOWER=0.37), answers={EMIT_WORD: "non"})


def test_power_test_never_goes_above_the_starting_level(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        await q.run()
        values = [float(c.split()[-1]) for c in fake.commands if c.lstrip("+").startswith("L RFPOWER")]
        assert values[:2] == [0.25, 0.5] and max(values) == 0.5 and fake.levels["RFPOWER"] == 0.5
    run(tmp_path, scenario, fake_setup=lambda f: f.levels.update(RFPOWER=0.5), answers={EMIT_WORD: "non"})


def test_band_misconfiguration_gives_incomplete_not_refused(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        q.cfg.bands = []
        await q.run()
        assert by_id(q)["ptt_cycle"].ok is None and 1 not in fake.ptt_commands
        assert compute_verdict(q.checks).status == INCOMPLETE
    run(tmp_path, scenario)


def test_unreachable_rigctld_is_incomplete_and_never_transmits(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        q.cfg.network.rigctld_port = 1
        await q.run()
        assert by_id(q)["cat"].ok is None and compute_verdict(q.checks).status == INCOMPLETE
        assert list(by_id(q)) == ["cat"]                  # arrêt immédiat : aucun autre test lancé
        assert not any(EMIT_WORD in p for p in prompts)
    run(tmp_path, scenario, cat_timeout_s=1.0)


def test_unreadable_ptt_refuses_the_rig(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        await q.run()
        assert by_id(q)["cat"].ok is False and compute_verdict(q.checks).status == REFUSE
        assert list(by_id(q)) == ["cat"] and 1 not in fake.ptt_commands
    run(tmp_path, scenario, fake_setup=lambda f: f.errors.update({"t": -11}))


def test_usb_replug_detects_loss_and_recovery(tmp_path):
    async def scenario(q, fake, proxy, prompts):
        await q.setup()
        try:
            assert await q.stage_cat()

            async def unplug_then_replug():
                await asyncio.sleep(0.3)
                fake.errors["f"] = -6                     # le poste ne répond plus
                while not any("Rebranche" in p for p in prompts):
                    await asyncio.sleep(0.05)
                fake.errors.pop("f")
            task = asyncio.create_task(unplug_then_replug())
            await q.test_usb_replug(wait_s=10.0)
            await task
            assert by_id(q)["usb_replug"].ok is True
        finally:
            await q.teardown()
    run(tmp_path, scenario, answers={"débranchement": "o"})


# --------------------------------------------------------------------------- ligne de commande

def test_plan_option_does_not_touch_the_rig(tmp_path, monkeypatch):
    cfg_path = tmp_path / "station.toml"
    from trxstation import config as cfgmod
    cfg_path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    monkeypatch.setattr(qmain, "_run_dump_caps", lambda model, hamlib_dir="": SAMPLE_DUMP_CAPS)
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))
    assert qmain.main(["--config", str(cfg_path), "--plan"]) == 0
    assert any("Cahier de test" in line for line in printed)


def test_catalogue_option_reports_rejected_sheets(tmp_path):
    from trxstation.qualif.sheet import RigSheet
    sheet = RigSheet(nom="X", hamlib_model=1, hamlib_min="4.6", statut="refuse")
    (tmp_path / "ok.toml").write_text(render_sheet(sheet), encoding="utf-8")
    assert qmain.check_catalogue(tmp_path, out=lambda s: None) == 0
    (tmp_path / "ko.toml").write_text("[rig]\nnom = 'Y'\nhamlib_model = 2\nhamlib_min = '4.6'\nstatut = 'valide'\n"
                                      "fiche_version = 1\n", encoding="utf-8")
    lines = []
    assert qmain.check_catalogue(tmp_path, out=lines.append) == 1
    assert any("socle" in line for line in lines)


def test_a_zero_latency_measure_never_becomes_a_zero_polling_rate(tmp_path, monkeypatch):
    """Horloge trop grossière (cas de time.monotonic sous Windows) : aucune cadence inventée."""
    import trxstation.qualif.runner as runner_module

    async def scenario(q, fake, proxy, prompts):
        await q.setup()
        try:
            assert await q.stage_cat()
            monkeypatch.setattr(runner_module.time, "perf_counter", lambda: 100.0)
            await q.test_endurance()
            monkeypatch.undo()
        finally:
            await q.teardown()
        latency = by_id(q)["latency"]
        assert latency.ok is True and latency.data["latence_cat_ms"] == 0 and "polling_max_hz" not in latency.data
        assert by_id(q)["cat_endurance"].ok is True
    run(tmp_path, scenario)


def test_missing_config_gives_a_clear_message_not_a_traceback(tmp_path, monkeypatch):
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))
    assert qmain.main(["--config", str(tmp_path / "absente.toml"), "--plan"]) == qmain.EXIT_CONFIG
    assert any("Configuration introuvable" in line and "--config" in line for line in printed)


def test_config_falls_back_to_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(qmain, "default_config_path", lambda: tmp_path / "standard" / "station.toml")
    assert qmain.find_config(tmp_path) == tmp_path / "standard" / "station.toml"     # rien nulle part : message sur le standard
    (tmp_path / "station.toml").write_text("", encoding="utf-8")
    assert qmain.find_config(tmp_path) == tmp_path / "station.toml"
    (tmp_path / "standard").mkdir()
    (tmp_path / "standard" / "station.toml").write_text("", encoding="utf-8")
    assert qmain.find_config(tmp_path) == tmp_path / "standard" / "station.toml"     # le standard reste prioritaire
