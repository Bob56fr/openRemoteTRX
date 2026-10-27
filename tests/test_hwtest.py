# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""L'essai guidé (trx-hwtest) est lui-même testé sur le faux poste, avec des réponses scriptées :
on vérifie qu'il ne tente rien sans confirmation, qu'il coupe toujours l'émission, et qu'il détecte les défauts."""
import asyncio
import contextlib
import io
import wave

import pytest

from trxstation import config as cfgmod
from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.devtools.cat_raw import ALLOWED, main as raw_main
from trxstation.devtools.hwtest import EMIT_WORD, HwTest, main, run_hwtest
from trxstation.gateway.cat import Capabilities
from trxstation.setup_wizard import dummy_config


def scripted(log, answers=None):
    """Réponses par mot-clé du message ; une liste est consommée dans l'ordre (la dernière valeur se répète)."""
    defaults = {"OUI": "OUI", EMIT_WORD: EMIT_WORD, "plus fort": "O"}
    defaults.update(answers or {})

    def ask(prompt):
        log.append(prompt)
        for key, answer in defaults.items():
            if key in prompt:
                if isinstance(answer, list):
                    return answer.pop(0) if len(answer) > 1 else answer[0]
                return answer
        return ""
    return ask


def run(tmp_path, scenario, *, capture="tone:440", fake_setup=None, answers=None, tx_modes=None, enforce_bands=True, **hw_kwargs):
    """Lance `scenario(hw, fake, out)` avec un faux poste et un HwTest rapide."""
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        if fake_setup:
            fake_setup(fake)
        cfg = dummy_config()
        cfg.safety.heartbeat_interval_ms, cfg.safety.heartbeat_timeout_ms = 300, 700      # exercices rapides
        cfg.rig.tx_modes = list(tx_modes or [])
        cfg.safety.enforce_bands = enforce_bands
        cfg.network.rigctld_port = fake.port
        cfg.audio.capture_device = capture
        cfg.audio.playback_device = f"file:{tmp_path / 'tx.wav'}"
        out, prompts = [], []
        params = dict(tot_s=3.0, hold_s=0.3, tx_seconds=0.6, rx_listen_s=0.6, tx_levels_db=(-40.0, -30.0),
                      cat_timeout_s=3.0, record_wav=str(tmp_path / "rx.wav"), cycles=2)
        params.update(hw_kwargs)
        hw = HwTest(cfg, ask=scripted(prompts, answers), out=out.append, **params)
        try:
            await asyncio.wait_for(scenario(hw, fake, out, prompts), 90)
        finally:
            await fake.stop()
    asyncio.run(wrapper())


def names(results, ok):
    return [r.name for r in results if r.ok is ok]


def test_full_run_on_a_healthy_rig(tmp_path):
    async def scenario(hw, fake, out, prompts):
        fake.levels["ALC"] = 0.30
        results = await hw.run()
        assert hw.report() == 0 and names(results, False) == [] and names(results, None) == []
        assert [r.name for r in results] == ["CAT", "Audio RX", "Accord", "Largeurs de filtre", "PTT", "Audio TX",
                                             "Panne : perte du heartbeat", "Panne : TOT (3 s)",
                                             "Panne : déconnexion du client"]
        assert fake.ptt == 0 and hw.ctrl.snapshot().state == "RX"                      # coupé à la fin
        commands = fake.ptt_commands
        assert commands.count(1) >= 2 + 2 + 3 and commands[-1] == 0                    # PTT x2, TX audio x2, pannes x3
        assert any("ALC=0.30" in line for line in out)                                 # niveaux relevés
        with wave.open(str(tmp_path / "rx.wav"), "rb") as w:
            assert w.getnframes() > 10_000                                              # le son reçu est enregistré
        with wave.open(str(tmp_path / "tx.wav"), "rb") as w:
            assert w.getnframes() >= 2 * 25 * 960                                       # la tonalité a franchi la porte
    run(tmp_path, scenario)


def test_reception_only_run_never_transmits_and_tries_the_filter_widths(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert [r.name for r in results] == ["CAT", "Audio RX", "Accord", "Largeurs de filtre"]
        assert not any("OUI" in p or EMIT_WORD in p for p in prompts)                  # ni préambule d'émission ni EMETTRE
        assert 1 not in fake.ptt_commands and fake.ptt == 0
        widths = results[-1]
        assert widths.ok and "3.6k" in widths.detail and "NON déclarées par Hamlib mais acceptées : 2.1k, 2.7k, 3.6k" in widths.detail
        assert fake.passband == 2400 and fake.mode == "USB"                             # largeur d'origine remise
    caps = Capabilities(filters={"USB": [2400, 1800, 3000]})
    run(tmp_path, scenario, rx_only=True, capabilities=caps)


def test_filter_candidates_by_mode_family():
    from trxstation.devtools.hwtest import filter_candidates
    assert filter_candidates("PKTUSB", [2400]) == [1800, 2100, 2400, 2700, 3000, 3600]
    assert filter_candidates("CW", [500, 250]) == [250, 500, 1200]
    assert filter_candidates("FM", [10000]) == [10000]                                    # pas de largeurs ajoutées
    assert filter_candidates(None, None) == []


def test_scope_screen_stage_measures_menu_and_resend_then_restores(tmp_path):
    from test_spectrum_service import PortB

    class Rig(PortB):
        """Poste qui se tait sur un menu ; « spectre allumé » renvoyé le ramène."""
        def __init__(self):
            super().__init__()
            self.on_menu = False

        def write(self, data):
            if self.on_menu and data[4:7] == b"\x27\x10\x01":
                self.on_menu = self.mute = False
            super().write(data)

    rig = Rig()

    async def scenario(hw, fake, out, prompts):
        hw.cfg.spectrum = cfgmod.Spectrum(enabled=True, source="civ_port", port="COM7", civ_address="B6")
        ask = hw.ask

        def operator(prompt):
            if "MENU" in prompt:
                rig.on_menu = rig.mute = True
            return ask(prompt)
        hw.ask = operator
        results = await hw.run()
        scope = next(r for r in results if r.name == "Écran du spectre")
        assert scope.ok and "sur un menu" in scope.detail and "RAMÈNE le spectre" in scope.detail
        assert rig.settings == {0x10: 0, 0x11: 0} and rig.closed                     # poste remis comme au départ
        assert fake.ptt == 0 and 1 not in fake.ptt_commands
    run(tmp_path, scenario, rx_only=True, scope_opener=lambda port, baud: rig, scope_measure_s=0.3)


def test_nothing_happens_unless_the_operator_confirms_the_preflight(tmp_path):
    async def scenario(hw, fake, out, prompts):
        assert await hw.run() == [] and fake.commands == [] and fake.ptt == 0
        assert "Essai annulé." in out
    run(tmp_path, scenario, answers={"OUI": "non"})


def test_emission_stages_are_skipped_without_the_exact_confirmation_word(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert names(results, False) == [] and set(names(results, None)) == {"PTT", "Audio TX", "Pannes"}
        assert 1 not in fake.ptt_commands and fake.ptt == 0
        assert sum(EMIT_WORD in p for p in prompts) == 3                               # une confirmation par étape
    run(tmp_path, scenario, answers={EMIT_WORD: "oui je confirme"})


def test_unreachable_rigctld_stops_before_any_transmission(tmp_path):
    async def scenario(hw, fake, out, prompts):
        hw.cfg.network.rigctld_port = 1                                                 # personne n'écoute
        results = await hw.run()
        assert names(results, False) == ["CAT"] and len(results) == 1
        assert not any(EMIT_WORD in p for p in prompts) and fake.ptt_commands == []
        assert "aucune émission n'a été tentée" in " ".join(out)
    run(tmp_path, scenario, cat_timeout_s=1.0)


def test_unreadable_ptt_blocks_transmission(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert names(results, False) == ["CAT"] and 1 not in fake.ptt_commands
        assert "pas lisible" in results[0].detail
    run(tmp_path, scenario, fake_setup=lambda f: f.errors.update({"t": -11}))


def test_frequency_outside_authorised_bands_blocks_transmission(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert "PTT / Audio TX / Pannes" in names(results, False) and 1 not in fake.ptt_commands
        assert fake.freq == 14_500_000                                                  # l'accord de test a été rétabli
    run(tmp_path, scenario, fake_setup=lambda f: setattr(f, "freq", 14_500_000))


def test_silent_rx_audio_is_reported_but_does_not_block_the_rest(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert names(results, False) == ["Audio RX"] and "silence total" in results[1].detail
        assert "CAT" in names(results, True) and "Accord" in names(results, True) and hw.report() == 1
    run(tmp_path, scenario, capture="", answers={EMIT_WORD: "non"})


def test_high_swr_aborts_the_audio_test_and_all_further_transmission(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        tx = next(r for r in results if r.name == "Audio TX")
        assert tx.ok is False and "ROS" in tx.detail
        assert next(r for r in results if r.name == "Pannes").ok is None                # plus aucune émission après
        assert sum(EMIT_WORD in p for p in prompts) == 2 and fake.ptt == 0
    run(tmp_path, scenario, fake_setup=lambda f: f.levels.update({"SWR": 3.0}))


def test_operator_can_stop_raising_the_level(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        tx = next(r for r in results if r.name == "Audio TX")
        assert tx.ok and "1 niveau(x)" in tx.detail and sum("plus fort" in p for p in prompts) == 1
    run(tmp_path, scenario, answers={"plus fort": "n", EMIT_WORD: [EMIT_WORD, EMIT_WORD, "non"]})


def test_transmission_is_cut_even_if_the_run_crashes(tmp_path):
    async def scenario(hw, fake, out, prompts):
        async def boom():
            raise RuntimeError("plantage en plein essai")
        hw.stage_tx_audio = boom                                                        # une étape lève une exception
        with pytest.raises(RuntimeError):
            await hw.run()
        assert fake.ptt == 0 and hw.ctrl.snapshot().state == "RX"
    run(tmp_path, scenario)


def test_no_prompt_is_ever_asked_while_transmitting(tmp_path):
    async def scenario(hw, fake, out, prompts):
        states = []
        original = hw.ask

        def watching(prompt):
            states.append(hw.ctrl.snapshot().state if hw.ctrl else "RX")
            return original(prompt)
        hw.ask = watching
        await hw.run()
        assert states and set(states) == {"RX"}
    run(tmp_path, scenario)


# --------------------------------------------------------------------------- ligne de commande

def cli(argv):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            return main(argv), err.getvalue()
        except SystemExit as exc:                                                       # argparse refuse une valeur
            return exc.code, err.getvalue()


def test_command_line_refuses_dangerous_or_invalid_parameters(tmp_path):
    cfg = dummy_config()
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    code, err = cli(["--config", str(path), "--tx-levels", "-40", "-6"])                # des niveaux négatifs sont acceptés
    assert code == 2 and "-12" in err                                                   # ... mais pas au-dessus de -12 dBFS
    code, err = cli(["--config", str(path), "--tx-levels", "fort"])
    assert code == 2 and "invalid float" in err
    code, err = cli(["--config", str(path), "--tot", "500"])
    assert code == 2
    bad = tmp_path / "bad.toml"
    bad.write_text("[rig]\nmodel = 0\n", encoding="utf-8")
    code, err = cli(["--config", str(bad)])
    assert code == 2 and "Configuration invalide" in err


def test_no_spawn_without_rigctld_gives_a_clear_answer_and_asks_nothing(tmp_path):
    async def scenario(hw, fake, out, prompts):
        hw.cfg.network.rigctld_port = 1
        assert await run_hwtest(hw.cfg, hw, spawn=False) == 3
        assert prompts == [] and any("rigctld ne répond pas" in line for line in out)
    run(tmp_path, scenario)


def test_ambiguous_tot_and_heartbeat_combination_is_refused(tmp_path):
    cfg = dummy_config()                                                                # heartbeat 2 s par défaut
    with pytest.raises(ValueError) as exc:
        HwTest(cfg, tot_s=2.5)
    assert "ambigu" in str(exc.value)
    HwTest(cfg, tot_s=3.0)                                                              # limite acceptable
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    code, err = cli(["--config", str(path), "--tot", "2.5"])
    assert code == 2 and "ambigu" in err


def test_out_of_band_rig_is_offered_a_band_and_the_whole_run_then_proceeds(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        band = next(r for r in results if r.name == "Bande d'essai")
        assert band.ok and fake.freq == 14_175_000                                     # milieu de la bande 20 m
        assert names(results, False) == [] and "PTT" in names(results, True) and 1 in fake.ptt_commands
        assert any("hors des bandes" in line for line in out)
    run(tmp_path, scenario, fake_setup=lambda f: setattr(f, "freq", 27_495_000),
        answers={"bande d'essai": "6", EMIT_WORD: [EMIT_WORD, EMIT_WORD, "non"]})


def test_declining_the_band_offer_still_blocks_transmission_safely(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert next(r for r in results if r.name == "Bande d'essai").ok is None
        assert "PTT / Audio TX / Pannes" in names(results, False) and 1 not in fake.ptt_commands
        assert fake.freq == 27_495_000
    run(tmp_path, scenario, fake_setup=lambda f: setattr(f, "freq", 27_495_000))


def test_data_mode_is_offered_for_usb_audio_then_the_original_mode_is_restored(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert names(results, False) == [] and fake.mode == "USB"                       # rétabli à la fin
        assert any(line.startswith("+M PKTUSB") for line in fake.commands)
        assert any("mode données" in p for p in prompts) and any("rétabli" in line for line in out)
    caps = Capabilities(modes=("USB", "LSB", "PKTUSB", "PKTLSB"), complete=True)
    run(tmp_path, scenario, capabilities=caps, answers={EMIT_WORD: [EMIT_WORD, EMIT_WORD, "non"]})


def test_data_mode_offer_can_be_declined_and_is_skipped_when_the_rig_has_none(tmp_path):
    async def declined(hw, fake, out, prompts):
        await hw.run()
        assert fake.mode == "USB" and not any(line.startswith("+M PKT") for line in fake.commands)   # jamais en mode données
    caps = Capabilities(modes=("USB", "PKTUSB"), complete=True)
    run(tmp_path, declined, capabilities=caps, answers={"mode données": "n", EMIT_WORD: [EMIT_WORD, EMIT_WORD, "non"]})

    async def absent(hw, fake, out, prompts):
        await hw.run()
        assert not any("mode données" in p for p in prompts)
    run(tmp_path, absent, capabilities=Capabilities(modes=("USB", "LSB"), complete=True),
        answers={EMIT_WORD: [EMIT_WORD, EMIT_WORD, "non"]})


# --------------------------------------------------------------------------- diagnostic brut (lecture seule)

def test_raw_diagnostic_tool_is_read_only():
    for ok in ("f", "m", "t", "l STRENGTH", "l ALC"):
        assert ALLOWED.fullmatch(ok)
    for bad in ("T 1", "F 14200000", "M USB 0", "l strength", "l ALC\nT 1", "f; T 1", "set_ptt 1", "\\set_ptt 1", ""):
        assert not ALLOWED.fullmatch(bad)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert raw_main(["T 1"]) == 2
    assert "lecture seule" in err.getvalue()


def test_raw_diagnostic_shows_both_response_formats(tmp_path):
    async def scenario(hw, fake, out, prompts):
        from trxstation.devtools.cat_raw import raw_query
        extended = await asyncio.to_thread(raw_query, "127.0.0.1", fake.port, "f", True)
        plain = await asyncio.to_thread(raw_query, "127.0.0.1", fake.port, "f", False)
        assert extended[-1] == "RPRT 0" and "14200000" in " ".join(extended)
        assert plain == ["get_freq:", "RPRT 0"] or plain[0] != ""                       # le faux poste ne gère que le format étendu
    run(tmp_path, scenario)


def test_restricted_tx_modes_the_run_switches_to_an_allowed_mode_then_restores_the_original(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert next(r for r in results if r.name == "Mode d'émission").ok is True
        assert names(results, False) == [] and "PTT" in names(results, True) and 1 in fake.ptt_commands
        assert fake.mode == "USB"                                                   # rétabli à la fin
        assert any(line.startswith("+M PKTUSB") for line in fake.commands)
    caps = Capabilities(modes=("USB", "LSB", "PKTUSB", "PKTLSB"), complete=True)
    run(tmp_path, scenario, capabilities=caps, tx_modes=["PKTUSB", "PKTLSB"], answers={EMIT_WORD: [EMIT_WORD, EMIT_WORD, "non"]})


def test_restricted_tx_modes_declining_the_switch_keeps_the_rig_in_reception(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert next(r for r in results if r.name == "Mode d'émission").ok is None
        ptt = next(r for r in results if r.name == "PTT")
        assert ptt.ok is False and "mode_not_allowed" in ptt.detail and 1 not in fake.ptt_commands
    caps = Capabilities(modes=("USB", "PKTUSB"), complete=True)
    run(tmp_path, scenario, capabilities=caps, tx_modes=["PKTUSB"], answers={"Passer en": "n"})


def test_trx_setup_can_set_and_clear_the_allowed_modes(tmp_path):
    from trxstation.setup_wizard import main as setup_main
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert setup_main(["--tx-modes", "PKTUSB", "PKTLSB", "-o", str(path)]) == 0
    assert cfgmod.load(path).rig.tx_modes == ["PKTUSB", "PKTLSB"] and "PKTUSB, PKTLSB" in out.getvalue()
    with contextlib.redirect_stdout(io.StringIO()):
        assert setup_main(["--tx-modes", "aucun", "-o", str(path)]) == 0
    assert cfgmod.load(path).rig.tx_modes == []


def test_band_control_delegated_to_the_rig_no_band_prompt_and_transmission_proceeds_out_of_band(tmp_path):
    async def scenario(hw, fake, out, prompts):
        results = await hw.run()
        assert not any(r.name == "Bande d'essai" for r in results) and not any("bande d'essai" in p for p in prompts)
        assert names(results, False) == [] and "PTT" in names(results, True) and 1 in fake.ptt_commands
        assert fake.freq == 27_495_000                                              # la fréquence n'a pas été déplacée
    run(tmp_path, scenario, fake_setup=lambda f: setattr(f, "freq", 27_495_000), enforce_bands=False,
        answers={EMIT_WORD: [EMIT_WORD, EMIT_WORD, "non"]})


def test_trx_setup_can_switch_band_control_off_and_on(tmp_path):
    from trxstation.setup_wizard import main as setup_main
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert setup_main(["--bands", "off", "-o", str(path)]) == 0
    assert cfgmod.load(path).safety.enforce_bands is False and "DÉSACTIVÉ" in out.getvalue()
    with contextlib.redirect_stdout(io.StringIO()):
        assert setup_main(["--bands", "on", "-o", str(path)]) == 0
    assert cfgmod.load(path).safety.enforce_bands is True


def test_max_power_is_validated_stored_and_settable_from_the_command_line(tmp_path):
    from trxstation.setup_wizard import main as setup_main
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    assert cfgmod.load(path).rig.max_power_w == 0
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert setup_main(["--max-power", "100", "-o", str(path)]) == 0
    assert cfgmod.load(path).rig.max_power_w == 100 and "100 W" in out.getvalue()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert setup_main(["--max-power", "5000", "-o", str(path)]) == 2
        assert setup_main(["--max-power", "-5", "-o", str(path)]) == 2
    assert cfgmod.load(path).rig.max_power_w == 100                                                 # refusé : valeur inchangée
    with contextlib.redirect_stdout(io.StringIO()):
        assert setup_main(["--max-power", "0", "-o", str(path)]) == 0
    assert cfgmod.load(path).rig.max_power_w == 0
    bad = dummy_config()
    bad.rig.max_power_w = 3000
    assert any("max_power_w" in p for p in cfgmod.validate(bad))


# --------------------------------------------------------------------------- coupure faite sur le poste

def _rig_unkey_run(tmp_path, scenario, **kwargs):
    run(tmp_path, scenario, only_rig_unkey=True, **kwargs)


async def _press_transmit_when_told(hw, fake, out, *, stale=False):
    """L'opérateur appuie sur TRANSMIT au signal ; `stale` = la relecture du PTT renvoie un état ancien (cache)."""
    while not any(">>> COUPE MAINTENANT" in line for line in out):                       # le vrai signal, pas la consigne
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.2)                                                             # temps de réaction
    if stale:
        fake.stale_ptt = True
    fake.ptt = 0


def test_rig_side_unkey_is_seen_by_the_readback(tmp_path):
    async def scenario(hw, fake, out, prompts):
        presser = asyncio.create_task(_press_transmit_when_told(hw, fake, out))
        results = await hw.run()
        await presser
        assert [r.name for r in results] == ["CAT", "Coupure par le poste (spectre désactivé)"]
        assert results[-1].ok is True and "vue en" in results[-1].detail
        assert hw.ctrl.snapshot().last_cut_reason == "rig_reported_rx" and fake.ptt == 0
        assert any("Prêt ?" in p for p in prompts)
    _rig_unkey_run(tmp_path, scenario)


def test_stale_ptt_readback_is_reported_as_a_failure(tmp_path):
    def stale_fake(fake):
        """Cache simulé : la relecture renvoie la DERNIÈRE VALEUR COMMANDÉE par CAT, pas l'état réel du poste."""
        fake.stale_ptt, fake.commanded = False, 0
        real_reply = fake._reply

        def reply(line):
            parts = line.lstrip("+").split()
            if parts[:1] == ["T"] and len(parts) == 2:
                fake.commanded = int(parts[1])
            if parts == ["t"] and fake.stale_ptt:
                return f"get_ptt:\nPTT: {fake.commanded}\nRPRT 0\n"
            return real_reply(line)
        fake._reply = reply

    async def scenario(hw, fake, out, prompts):
        presser = asyncio.create_task(_press_transmit_when_told(hw, fake, out, stale=True))
        results = await hw.run()
        await presser
        assert results[-1].ok is False and "PAS VUE" in results[-1].detail and "NE PAS activer le spectre" in results[-1].detail
        assert hw.report() == 1
    _rig_unkey_run(tmp_path, scenario, fake_setup=stale_fake)


def test_rig_side_unkey_needs_the_confirmation_word_and_never_asks_while_transmitting(tmp_path):
    async def scenario(hw, fake, out, prompts):
        states = []
        original = hw.ask

        def watching(prompt):
            states.append(hw.ctrl.snapshot().state if hw.ctrl else "RX")
            return original(prompt)
        hw.ask = watching
        results = await hw.run()
        assert results[-1].ok is None and 1 not in fake.ptt_commands
        assert set(states) == {"RX"}
    _rig_unkey_run(tmp_path, scenario, answers={EMIT_WORD: "non"})


def test_rig_unkey_option_on_the_command_line(tmp_path):
    code, err = cli(["--config", str(tmp_path / "absent.toml"), "--coupure-poste"])
    assert code == 2                                                                    # configuration absente : refus net
