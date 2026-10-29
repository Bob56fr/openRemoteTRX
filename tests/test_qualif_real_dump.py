# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Référence RÉELLE : `rigctl -m 3094 -u` de l'IC-7300MK2 avec Hamlib 4.7.2 (fichier relevé par l'utilisateur).

Ces tests figent ce que le vrai Hamlib publie, et vérifient que la qualification et les modes données
s'en accommodent : FM-D et AM-D (et non PKTFM, PKTAM), pas d'IP+, AGC sans valeur 1, préamplis 1 et 2.
"""
import asyncio
from pathlib import Path

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.devtools.hwtest import EMIT_WORD
from trxstation.gateway.cat.capabilities import ALL_DATA_MODES, CapabilitiesError, data_mode_for
from trxstation.qualif.plan import build_plan
from trxstation.qualif.profile import parse_profile
from trxstation.qualif.results import IN_VALIDATION, compute_verdict, latest
from trxstation.qualif.runner import Qualification
from trxstation.qualif.trace import TraceProxy
from trxstation.setup_wizard import data_modes_for_model, dummy_config

REAL = (Path(__file__).parent / "data" / "dump_caps_ic7300mk2_hamlib472.txt").read_text(encoding="utf-8")


def real_profile():
    return parse_profile(REAL, 3094)


def test_real_dump_is_read_as_published_by_hamlib_4_7_2():
    p = real_profile()
    assert p.name == "Icom IC-7300MK2" and p.backend_status == "Beta" and p.hamlib_version == "4.7.2"
    assert p.modes == ("AM", "CW", "USB", "LSB", "RTTY", "FM", "CWR", "RTTYR", "PKTLSB", "PKTUSB", "FM-D", "AM-D")
    assert p.preamps == (1, 2) and p.attenuators == (20,) and p.agc_levels == (0, 2, 5, 3)
    assert p.caps.filters["USB"] == [3000, 2400, 1800] and p.caps.filters["FM"] == [15000, 10000, 7000]
    assert p.caps.filters["CW"] == [1200, 500, 250]
    assert "AIP" not in p.declared() and "TUNER" in p.set_functions
    assert p.level_ranges["RFPOWER"].low == 0.05 and "RFPOWER_METER_WATTS" in p.get_levels
    assert p.can["get PTT"] and p.can["set PTT"] and p.caps.has_s_meter


def test_real_plan_matches_what_trx_qualif_printed():
    plan = build_plan(real_profile())
    ids = {i.id for i in plan.items}
    assert {"mode_FM-D", "mode_AM-D", "write_level_AGC", "write_level_PREAMP", "read_level_VD_METER"} <= ids
    assert not any("AIP" in i for i in ids) and "read_level_TEMP_METER" not in ids
    assert {"SPECTRUM", "RFPOWER_METER_WATTS", "PBT_IN", "USB_AF"} <= set(plan.unused)     # RIT et XIT : utilisés depuis 0.55.0


def test_data_mode_names_follow_the_hamlib_version():
    modes = real_profile().modes
    assert data_mode_for("FM", modes) == "FM-D" and data_mode_for("AM", modes) == "AM-D"
    assert data_mode_for("USB", modes) == "PKTUSB" and data_mode_for("CW", modes) is None
    assert data_mode_for("FM", ("PKTFM",)) == "PKTFM" and data_mode_for("FM", ()) == "PKTFM"
    assert data_mode_for("FM", ("USB",)) is None


def test_setup_proposes_only_data_modes_that_exist_for_the_model():
    assert data_modes_for_model(3094, dump=lambda m, d: REAL) == ["PKTUSB", "PKTLSB", "FM-D", "AM-D"]

    def broken(model, hamlib_dir):
        raise CapabilitiesError("rigctl introuvable")
    assert data_modes_for_model(3094, dump=broken) == list(ALL_DATA_MODES)      # que des modes données
    assert set(ALL_DATA_MODES) == {"PKTUSB", "PKTLSB", "PKTFM", "PKTAM", "FM-D", "AM-D"}


def run(tmp_path, scenario, *, fake_setup=None, answers=None):
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        if fake_setup:
            fake_setup(fake)
        proxy = TraceProxy("127.0.0.1", fake.port)
        await proxy.start()
        cfg = dummy_config()
        cfg.safety.heartbeat_interval_ms, cfg.safety.heartbeat_timeout_ms = 300, 700
        cfg.network.rigctld_port = proxy.port
        cfg.audio.capture_device = "tone:440"
        cfg.audio.playback_device = f"file:{tmp_path / 'tx.wav'}"
        defaults = {"OUI": "OUI", EMIT_WORD: EMIT_WORD, "firmware": "1.10"}
        defaults.update(answers or {})
        q = Qualification(cfg, profile=real_profile(), dump_text=REAL, proxy=proxy,
                          ask=lambda p: next((v for k, v in defaults.items() if k in p), ""), out=lambda s: None,
                          tot_s=3.0, hold_s=0.3, tx_seconds=0.6, rx_listen_s=0.6, tx_levels_db=(-40.0,),
                          cat_timeout_s=3.0, record_wav=str(tmp_path / "rx.wav"), cycles=2, endurance_cycles=100,
                          settle_s=0.6, cat_cut_s=0.8)
        try:
            await asyncio.wait_for(scenario(q, fake), 120)
        finally:
            await proxy.stop()
            await fake.stop()
    asyncio.run(wrapper())


def test_full_qualification_with_the_real_capabilities(tmp_path):
    async def scenario(q, fake):
        fake.levels["AGC"], fake.levels["PREAMP"] = 3, 0
        await q.run()
        results = latest(q.checks)
        failed = [(c.id, c.detail) for c in results.values() if c.ok is False]
        assert failed == [], failed
        assert compute_verdict(q.checks).status == IN_VALIDATION
        agc_values = [c.split()[-1] for c in fake.commands if c.lstrip("+").startswith("L AGC")]
        assert agc_values[:2] == ["2", "3"]                   # FAST puis retour à SLOW : jamais OFF par défaut
        preamp_values = [c.split()[-1] for c in fake.commands if c.lstrip("+").startswith("L PREAMP")]
        assert preamp_values[:2] == ["1", "0"]                # valeurs publiées par Hamlib (1 et 2), pas 10 ni 20
        assert results["mode_FM-D"].ok and results["mode_AM-D"].ok
        assert fake.levels["AGC"] == 3 and fake.levels["PREAMP"] == 0 and fake.ptt == 0
    run(tmp_path, scenario)


def test_filters_set_differently_on_the_rig_are_not_a_failure(tmp_path):
    """Icom : Hamlib choisit FIL1/2/3, le poste relit la largeur réglée par l'utilisateur."""
    def user_fil(fake):
        original = fake._reply
        mapping = {3000: 2800, 2400: 2100, 1800: 1500, 1200: 1000, 500: 600, 250: 300,
                   9000: 9000, 6000: 6000, 15000: 15000, 10000: 10000, 7000: 7000}

        def reply(line):
            parts = line.lstrip("+").split()
            if parts[:1] == ["M"] and len(parts) == 3 and int(parts[2]) in mapping:
                return original(f"+M {parts[1]} {mapping[int(parts[2])]}")
            return original(line)
        fake._reply = reply

    async def scenario(q, fake):
        await q.setup()
        try:
            assert await q.stage_cat()
            await q.test_filters()
        finally:
            await q.teardown()
        check = latest(q.checks)["filters"]
        assert check.ok is True and "réglages FIL" in check.detail
    run(tmp_path, scenario, fake_setup=user_fil)


def test_filters_that_do_not_switch_are_a_failure(tmp_path):
    def stuck(fake):
        original = fake._reply

        def reply(line):
            parts = line.lstrip("+").split()
            if parts[:1] == ["M"] and len(parts) == 3 and parts[2] != "0":
                return original(f"+M {parts[1]} 2400")       # toujours le même filtre
            return original(line)
        fake._reply = reply

    async def scenario(q, fake):
        await q.setup()
        try:
            assert await q.stage_cat()
            await q.test_filters()
        finally:
            await q.teardown()
        check = latest(q.checks)["filters"]
        assert check.ok is False and "filtres distincts" in check.detail
    run(tmp_path, scenario, fake_setup=stuck)
