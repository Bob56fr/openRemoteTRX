# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
import asyncio

import pytest

from trxstation.devtools.fake_rigctld import FakeRigctld
from trxstation.gateway.cat import (CatConnectionError, CatLink, CatProtocolError, Capabilities, RigctldClient,
                                    RigError, parse_dump_caps)


def run(coro_fn):
    """Exécute un scénario async avec un faux rigctld démarré ; l'arrête toujours à la fin."""
    async def wrapper():
        fake = FakeRigctld()
        await fake.start()
        try:
            await asyncio.wait_for(coro_fn(fake), 10)
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


def make_link(fake, **kw):
    kw.setdefault("poll_fast_s", 0.02)
    kw.setdefault("slow_every", 2)
    kw.setdefault("backoff_min_s", 0.05)
    kw.setdefault("backoff_max_s", 0.2)
    kw.setdefault("timeout", 0.5)
    return CatLink("127.0.0.1", fake.port, **kw)


# --------------------------------------------------------------------------- client

def test_read_and_write_roundtrip():
    async def scenario(fake):
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        assert await c.get_frequency() == 14_200_000
        assert await c.get_mode() == ("USB", 2400)
        assert await c.get_strength() == -54
        assert await c.get_ptt() is False
        await c.set_frequency(7_074_000)
        await c.set_mode("LSB", 2700)
        assert await c.get_frequency() == 7_074_000
        assert await c.get_mode() == ("LSB", 2700)
        await c.close()
    run(scenario)


@pytest.mark.parametrize("bad", ["USB\nT 1", "USB;T 1", "", "A" * 40, "U SB", None])
def test_set_mode_rejects_injection(bad):
    async def scenario(fake):
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        with pytest.raises(ValueError):
            await c.set_mode(bad)
        assert fake.commands == []          # rien n'est parti vers rigctld
        await c.close()
    run(scenario)


@pytest.mark.parametrize("bad", [0, -5, 14.2e6, "14200000", True, 10**11])
def test_set_frequency_rejects_invalid(bad):
    async def scenario(fake):
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        with pytest.raises(ValueError):
            await c.set_frequency(bad)
        assert fake.commands == []
        await c.close()
    run(scenario)


def test_rig_error_keeps_connection_usable():
    async def scenario(fake):
        fake.errors["l"] = -11
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        with pytest.raises(RigError) as exc:
            await c.get_strength()
        assert exc.value.code == -11
        assert c.connected
        assert await c.get_frequency() == 14_200_000   # le flux est resté synchronisé
        await c.close()
    run(scenario)


def test_timeout_drops_connection():
    async def scenario(fake):
        fake.delay_s = 1.0
        c = RigctldClient("127.0.0.1", fake.port, timeout=0.2)
        await c.connect()
        with pytest.raises(CatConnectionError):
            await c.get_frequency()
        assert not c.connected
    run(scenario)


def test_dropped_connection_is_reported():
    async def scenario(fake):
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        fake.drop_connections()
        await asyncio.sleep(0.05)
        with pytest.raises(CatConnectionError):
            await c.get_frequency()
        assert not c.connected
    run(scenario)


def test_connect_refused_is_reported():
    async def scenario(fake):
        c = RigctldClient("127.0.0.1", 1, timeout=0.5)   # port fermé
        with pytest.raises(CatConnectionError):
            await c.connect()
    run(scenario)


# --------------------------------------------------------------------------- lien

def test_link_publishes_state_and_never_sets_ptt():
    async def scenario(fake):
        link = make_link(fake)
        seen = []
        link.add_listener(seen.append)
        task = asyncio.create_task(link.run())
        await until(lambda: None not in (link.state.frequency_hz, link.state.strength_db, link.state.ptt))
        s = link.state
        assert (s.connected, s.frequency_hz, s.mode, s.ptt) == (True, 14_200_000, "USB", False)
        await link.set_frequency(3_650_000)
        await link.set_mode("LSB")
        await until(lambda: link.state.frequency_hz == 3_650_000 and link.state.mode == "LSB")
        assert seen and seen[-1].frequency_hz == 3_650_000
        link.stop()
        await asyncio.wait_for(task, 3)
        assert fake.ptt_set_calls == 0      # la couche CAT ne commande jamais le PTT
    run(scenario)


def test_link_resets_values_and_reconnects():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.frequency_hz is not None)
        fake.freq = 21_100_000
        fake.drop_connections()
        await until(lambda: not link.state.connected)
        s = link.state
        assert (s.frequency_hz, s.mode, s.strength_db, s.ptt) == (None, None, None, None)
        await until(lambda: link.state.connected and link.state.frequency_hz == 21_100_000)
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_link_survives_rigctld_not_running_yet():
    async def scenario(fake):
        port = fake.port
        await fake.stop()
        link = CatLink("127.0.0.1", port, poll_fast_s=0.02, slow_every=2,
                       backoff_min_s=0.05, backoff_max_s=0.1, timeout=0.3)
        task = asyncio.create_task(link.run())
        # Sous Windows, un port fermé met parfois plus d'une seconde à être refusé : on attend l'erreur.
        await until(lambda: link.state.last_error, timeout=5.0)
        assert not link.state.connected
        revived = FakeRigctld()
        await revived.start(port)
        try:
            await until(lambda: link.state.connected and link.state.frequency_hz is not None)
        finally:
            link.stop()
            await asyncio.wait_for(task, 3)
            await revived.stop()
    run(scenario)


def test_link_without_s_meter_stops_asking():
    async def scenario(fake):
        fake.errors["l"] = -11
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.frequency_hz is not None)
        await asyncio.sleep(0.2)
        assert link.state.strength_db is None
        assert fake.count_command("l STRENGTH") == 1  # une seule tentative, puis on n'insiste plus
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_link_rig_off_clears_values_but_stays_connected():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.frequency_hz is not None)
        fake.errors["f"] = -5               # poste muet : rigctld répond, le poste non
        await until(lambda: link.state.frequency_hz is None)
        assert link.state.connected and "RPRT -5" in link.state.last_error
        del fake.errors["f"]
        await until(lambda: link.state.frequency_hz == 14_200_000)
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_set_mode_checked_against_capabilities():
    async def scenario(fake):
        caps = Capabilities(modes=("USB", "LSB"), complete=True)
        link = make_link(fake, capabilities=caps)
        await link.client.connect()
        with pytest.raises(ValueError):
            await link.set_mode("FM")
        assert fake.commands == []
        await link.client.close()
    run(scenario)


# --------------------------------------------------------------------------- capacités

SAMPLE_CAPS = """Caps dump for model:\t3073
Model name:\tIC-7300
Mfg name:\tIcom
Backend version:\t20230101.0
Mode list: AM CW USB LSB RTTY FM CWR RTTYR
Get level: AF(0..1/0.00390625) RF(0..1/0.00390625) STRENGTH(0..0/0) SWR(0..0/0)
Can set Frequency:\tY
Can get Frequency:\tY
Can set Mode:\tY
Can get Mode:\tY
Can set PTT:\tY
Can get PTT:\tY
"""


def test_parse_dump_caps_full():
    caps = parse_dump_caps(SAMPLE_CAPS, 3073)
    assert (caps.model_name, caps.manufacturer, caps.complete) == ("IC-7300", "Icom", True)
    assert caps.modes == ("AM", "CW", "USB", "LSB", "RTTY", "FM", "CWR", "RTTYR")
    assert caps.has_s_meter and caps.can_get_ptt
    assert caps.to_dict()["modes"][0] == "AM"


def test_parse_dump_caps_without_s_meter():
    caps = parse_dump_caps(SAMPLE_CAPS.replace("STRENGTH(0..0/0) ", ""), 3073)
    assert not caps.has_s_meter


def test_parse_dump_caps_unknown_format_falls_back_and_says_so():
    caps = parse_dump_caps("n'importe quoi", 42)
    assert not caps.complete and caps.modes == ("USB", "LSB", "FM", "AM")


def test_generic_level_read_is_validated_and_read_only():
    async def scenario(fake):
        fake.levels["ALC"] = 0.25
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        assert await c.get_level("ALC") == 0.25 and await c.get_level("STRENGTH") == -54.0
        with pytest.raises(RigError) as exc:
            await c.get_level("INEXISTANT")
        assert exc.value.code == -11 and c.connected
        for bad in ("alc", "ALC\nT 1", "A", "", None, "SWR;T 1"):
            with pytest.raises(ValueError):
                await c.get_level(bad)
        assert fake.ptt_set_calls == 0
        await c.close()
    run(scenario)


def test_client_reads_label_less_responses_as_returned_by_some_hamlib_versions():
    async def scenario(fake):
        fake.bare = True
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        assert await c.get_frequency() == 14_200_000 and await c.get_mode() == ("USB", 2400)
        assert await c.get_strength() == -54 and await c.get_level("SWR") == 1.1 and await c.get_ptt() is False
        await c.close()
    run(scenario)


def test_unreadable_response_names_the_raw_answer_and_keeps_the_connection():
    async def scenario(fake):
        fake.broken_strength = True
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        with pytest.raises(CatProtocolError) as exc:
            await c.get_strength()
        assert "'l STRENGTH'" in str(exc.value) and "réponse vide" in str(exc.value)
        assert c.connected and await c.get_frequency() == 14_200_000            # le flux est resté synchronisé
        await c.close()
    run(scenario)


def test_link_stays_up_with_label_less_responses():
    async def scenario(fake):
        fake.bare = True
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: None not in (link.state.frequency_hz, link.state.strength_db, link.state.ptt))
        assert link.state.connected and link.state.mode == "USB"
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_unreadable_s_meter_never_takes_the_whole_link_down():
    async def scenario(fake):
        fake.broken_strength = True
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.frequency_hz is not None and link.state.ptt is not None)
        await asyncio.sleep(0.3)
        assert link.state.connected and link.state.mode == "USB" and link.state.strength_db is None
        assert fake.count_command("l STRENGTH") == 1                      # une tentative, puis on n'insiste plus
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_garbled_frequency_does_not_drop_the_link_either():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.frequency_hz is not None)
        original = fake._reply
        fake._reply = lambda line: "get_freq:\nRPRT 0\n" if line.startswith("+f") else original(line)
        await until(lambda: link.state.frequency_hz is None)                     # valeur inconnue : None, jamais périmée
        assert link.state.connected and link.state.last_error
        fake._reply = original
        await until(lambda: link.state.frequency_hz == 14_200_000)
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


# --------------------------------------------------------------------------- indicateurs du poste, mesures d'émission, squelch

def test_link_reads_functions_and_levels_round_robin_without_flooding_the_bus():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: {"NR", "NB", "AIP", "COMP", "TUNER", "ANF", "MN"} <= set(link.state.functions) and
                    {"PREAMP", "ATT", "AGC", "SQL", "VD_METER", "TEMP_METER", "NR", "NB"} <= set(link.state.levels))
        s = link.state
        assert s.functions == {"NR": False, "NB": True, "AIP": False, "COMP": False, "TUNER": False, "ANF": False, "MN": False}
        assert s.levels["NR"] == 0.4 and s.levels["NB"] == 5.0                  # NR/NB : fonction ET niveau, sans se mélanger
        assert s.levels["PREAMP"] == 10 and s.levels["SQL"] == 0.2 and s.levels["VD_METER"] == 13.8
        assert not {"RFPOWER_METER", "SWR", "ALC"} & set(s.levels)               # mesures d'émission : seulement en émission
        extras = fake.count_command("u NR") + fake.count_command("u NB") + fake.count_command("l PREAMP") + fake.count_command("l SQL")
        cycles = fake.count_command("l STRENGTH")
        assert extras <= cycles + 4                                               # au plus UNE lecture facultative par cycle de S-mètre
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_function_changes_on_the_rig_are_picked_up_and_published():
    async def scenario(fake):
        link = make_link(fake)
        seen = []
        link.add_listener(seen.append)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.functions.get("NR") is False)
        fake.funcs["NR"] = 1                                                      # on active NR sur le poste
        await until(lambda: link.state.functions.get("NR") is True, 5)
        assert any(s.functions.get("NR") for s in seen)
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_transmit_meters_only_during_transmission_then_cleared():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.ptt is False and "PREAMP" in link.state.levels)
        fake.ptt = 1
        fake.levels.update(RFPOWER_METER=0.42, SWR=1.3, ALC=0.1, COMP_METER=0.2)
        await until(lambda: link.state.levels.get("RFPOWER_METER") == 0.42 and {"SWR", "ALC", "COMP_METER"} <= set(link.state.levels), 5)
        assert link.state.levels["SWR"] == 1.3
        fake.ptt = 0
        await until(lambda: not ({"RFPOWER_METER", "SWR", "ALC", "COMP_METER"} & set(link.state.levels)), 5)
        assert "PREAMP" in link.state.levels                                      # les indicateurs permanents restent
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_unsupported_readings_are_dropped_after_one_attempt_and_the_link_stays_up():
    async def scenario(fake):
        del fake.funcs["AIP"]                                                     # ce poste n'a pas d'IP+
        del fake.levels["TEMP_METER"]
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: "NR" in link.state.functions and "PREAMP" in link.state.levels)
        await asyncio.sleep(0.6)
        assert "AIP" not in link.state.functions and "TEMP_METER" not in link.state.levels and link.state.connected
        assert fake.count_command("u AIP") == 1 and fake.count_command("l TEMP_METER") == 1     # une seule tentative
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_garbled_optional_reading_is_dropped_without_losing_the_link():
    async def scenario(fake):
        original = fake._reply
        fake._reply = lambda line: "get_func: NB\nRPRT 0\n" if line.startswith("+u NB") else original(line)
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: "NR" in link.state.functions and "PREAMP" in link.state.levels)
        await asyncio.sleep(0.5)
        assert "NB" not in link.state.functions and link.state.connected and link.state.frequency_hz == 14_200_000
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_capabilities_limit_what_is_asked():
    async def scenario(fake):
        caps = Capabilities(complete=True, functions=("NR", "NB"), levels=("PREAMP", "SQL", "STRENGTH"))
        link = make_link(fake, capabilities=caps)
        task = asyncio.create_task(link.run())
        await until(lambda: {"NR", "NB"} <= set(link.state.functions) and {"PREAMP", "SQL"} <= set(link.state.levels))
        await asyncio.sleep(0.4)
        assert fake.count_command("u AIP") == 0 and fake.count_command("l ATT") == 0 and fake.count_command("u ANF") == 0
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_squelch_can_be_set_and_nothing_else_can():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: "SQL" in link.state.levels)
        await link.set_squelch(0.55)
        assert fake.levels["SQL"] == 0.55 and link.state.levels["SQL"] == 0.55
        for bad in (-0.1, 1.1, float("nan"), float("inf"), "0.5", None, True):
            with pytest.raises(ValueError):
                await link.set_squelch(bad)
        c = link.client
        for name in ("AF", "MICGAIN", "sql", "SQL\nT 1", "PTT", "RFPOWER2"):         # aucun autre niveau n'est modifiable
            with pytest.raises(ValueError):
                await c.set_level(name, 0.5)
        assert fake.ptt_set_calls == 0 and fake.levels["SQL"] == 0.55
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_get_func_is_validated():
    async def scenario(fake):
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        assert await c.get_func("NB") is True and await c.get_func("NR") is False
        with pytest.raises(RigError):
            await c.get_func("INCONNU")
        for bad in ("nb", "NB\nT 1", "A", "", None, "NB;T 1"):
            with pytest.raises(ValueError):
                await c.get_func(bad)
        assert fake.ptt_set_calls == 0
        await c.close()
    run(scenario)


def test_capabilities_parse_functions_and_levels():
    text = SAMPLE_CAPS + "Get functions: FAGC NB COMP VOX TONE TSQL ANF NR AIP\n"
    caps = parse_dump_caps(text, 3094)
    assert caps.functions == ("FAGC", "NB", "COMP", "VOX", "TONE", "TSQL", "ANF", "NR", "AIP")
    assert "STRENGTH" in caps.levels and "AF" in caps.levels and "RF" in caps.levels and "0" not in caps.levels
    data = caps.to_dict()
    assert data["functions"][-1] == "AIP" and isinstance(data["levels"], list)
    assert parse_dump_caps("n'importe quoi", 1).functions == ()                     # format inconnu : pas de filtrage


# --------------------------------------------------------------------------- commandes du poste : NR, NB, IP+, compresseur, tuner, AGC, préampli

def test_functions_can_be_switched_and_the_display_follows_immediately():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: {"NR", "NB", "COMP", "TUNER"} <= set(link.state.functions))
        for name in ("NR", "AIP", "COMP", "TUNER"):
            await link.set_function(name, True)
            assert fake.funcs[name] == 1 and link.state.functions[name] is True            # affichage immédiat, relecture ensuite
        await link.set_function("NB", False)
        assert fake.funcs["NB"] == 0 and link.state.functions["NB"] is False
        assert "U COMP 1" in [c.lstrip("+") for c in fake.commands]
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_agc_and_preamp_levels_are_integers_in_a_closed_range():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: {"AGC", "PREAMP"} <= set(link.state.levels))
        await link.set_level("AGC", 5)
        await link.set_level("PREAMP", 20)
        assert fake.levels["AGC"] == 5 and fake.levels["PREAMP"] == 20
        assert link.state.levels["AGC"] == 5 and link.state.levels["PREAMP"] == 20
        await link.set_level("PREAMP", 0)
        assert link.state.levels["PREAMP"] == 0
        for name, bad in (("AGC", 7), ("AGC", -1), ("AGC", 2.5), ("AGC", "2"), ("AGC", True), ("PREAMP", 31), ("PREAMP", None), ("SQL", 1.5)):
            with pytest.raises(ValueError):
                await link.set_level(name, bad)
        assert fake.levels["AGC"] == 5
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_only_a_closed_list_of_functions_and_levels_can_be_written_and_never_the_ptt():
    async def scenario(fake):
        c = RigctldClient("127.0.0.1", fake.port)
        await c.connect()
        for name in ("PTT", "TONE", "VOX", "MON", "nr", "NR\nT 1", "NR T", "", None, "TUNER;T 1"):
            with pytest.raises(ValueError):
                await c.set_func(name, True)
        for bad in (1, 0, "1", None, "true"):
            with pytest.raises(ValueError):
                await c.set_func("NR", bad)
        for name in ("MICGAIN", "AF", "COMP", "RF", "AGC\nT 1", "PTT", "RFPOWER\nT 1"):
            with pytest.raises(ValueError):
                await c.set_level(name, 1)
        for name, bad in (("ATT", 1.5), ("ATT", 99), ("NR", 1.5), ("NB", 11), ("NB", float("nan"))):
            with pytest.raises(ValueError):
                await c.set_level(name, bad)                                       # plages bornées, entiers pour ATT
        assert fake.ptt_set_calls == 0
        await c.close()
    run(scenario)


def test_functions_the_rig_does_not_declare_are_refused_before_asking_it():
    async def scenario(fake):
        caps = Capabilities(complete=True, functions=("NR", "NB"), levels=("PREAMP", "SQL"))
        link = make_link(fake, capabilities=caps)
        task = asyncio.create_task(link.run())
        await until(lambda: "NR" in link.state.functions)
        with pytest.raises(ValueError):
            await link.set_function("TUNER", True)
        with pytest.raises(ValueError):
            await link.set_level("AGC", 2)
        assert fake.count_command("U TUNER 1") == 0 and fake.count_command("L AGC 2") == 0
        await link.set_function("NR", True)
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_unreadable_function_can_still_be_written_and_keeps_the_written_value():
    async def scenario(fake):
        del fake.funcs["TUNER"]
        fake.funcs["TUNER"] = 0
        original = fake._reply
        fake._reply = lambda line: "RPRT -11\n" if line.startswith("+u TUNER") else original(line)    # lecture non gérée, écriture permise
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: "NR" in link.state.functions and "COMP" in link.state.functions)
        await asyncio.sleep(0.3)
        assert "TUNER" not in link.state.functions                                                        # jamais inventé
        await link.set_function("TUNER", True)
        await asyncio.sleep(0.5)
        assert link.state.functions["TUNER"] is True and fake.funcs["TUNER"] == 1
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


BANDWIDTH_CAPS = SAMPLE_CAPS + """Preamp: 10dB, 20dB,
Bandwidths:
\tAM\tNormal: 6 kHz,\tNarrow: 3 kHz,\tWide: 9 kHz
\tCW\tNormal: 500 Hz,\tNarrow: 250 Hz,\tWide: 1.2 kHz
\tUSB\tNormal: 2.4 kHz,\tNarrow: 1.8 kHz,\tWide: 3 kHz
\tPKTUSB\tNormal: 2.4 kHz,\tNarrow: 1.8 kHz,\tWide: 3 kHz
"""


def test_capabilities_parse_filter_widths_and_preamp_values():
    caps = parse_dump_caps(BANDWIDTH_CAPS, 3094)
    assert caps.filters["USB"] == [3000, 2400, 1800] and caps.filters["CW"] == [1200, 500, 250] and caps.filters["AM"] == [9000, 6000, 3000]
    assert caps.filters["PKTUSB"] == [3000, 2400, 1800]
    assert caps.preamps == (10, 20)
    data = caps.to_dict()
    assert data["filters"]["USB"] == [3000, 2400, 1800] and data["preamps"] == [10, 20]
    bare = parse_dump_caps(SAMPLE_CAPS, 3094)
    assert bare.filters == {} and bare.preamps == ()                                                  # format absent : on ne devine pas
    assert parse_dump_caps(SAMPLE_CAPS + "Preamp: None\n", 1).preamps == ()
    odd = parse_dump_caps(SAMPLE_CAPS + "Bandwidths:\n\tUSB\tNormal: ?, Narrow: ?, Wide: ?\n\tLSB\tNormal: 2.4 kHz,\tNarrow: 1.8 kHz,\tWide: 2.4 kHz\n", 1)
    assert "USB" not in odd.filters and odd.filters["LSB"] == [2400, 1800]                            # ligne illisible écartée, doublons fusionnés


# --------------------------------------------------------------------------- puissance d'émission (RFPOWER) : liste fermée de valeurs

def test_tx_power_is_read_and_set_among_a_closed_list_of_steps():
    async def scenario(fake):
        link = make_link(fake)
        task = asyncio.create_task(link.run())
        await until(lambda: "RFPOWER" in link.state.levels)
        assert link.state.levels["RFPOWER"] == 1.0
        for step in (0.05, 0.10, 0.25, 0.50, 0.80, 1.00):
            await link.set_level("RFPOWER", step)
            assert fake.levels["RFPOWER"] == step and link.state.levels["RFPOWER"] == step
        assert "L RFPOWER 0.250" in [c.lstrip("+") for c in fake.commands]
        for bad in (0, 0.0, 0.3, 0.06, 0.99, 1.5, -0.1, 5, 100, float("nan"), float("inf"), "0.5", None, True):
            with pytest.raises(ValueError):
                await link.set_level("RFPOWER", bad)
        assert fake.levels["RFPOWER"] == 1.0                                         # une valeur refusée n'est jamais envoyée
        assert fake.count_command("L RFPOWER 0.300") == 0 and fake.count_command("L RFPOWER 0.000") == 0
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_capabilities_read_attenuator_and_level_ranges_from_a_real_ic7300mk2_dump():
    """Extraits RÉELS de « rigctl -m 3094 -u » (Hamlib 5.0.0~git, Debian, 2026-10-28)."""
    from trxstation.gateway.cat.capabilities import parse_dump_caps
    text = ("Model name:\tIC-7300MK2\nMode list: AM CW USB LSB RTTY FM CWR RTTYR PKTLSB PKTUSB FM-D AM-D \n"
            "Preamp: 1dB 2dB\nAttenuator: 20dB\n"
            "Set level: PREAMP(0..20/10) ATT(0..12/0) NR(0.000000..1.000000/0.066667) NOTCHF_RAW(0.000000..0.000000/0.000000) "
            "NB(0.000000..10.000000/1.000000) AGC(0..0/0) \n")
    caps = parse_dump_caps(text, 3094)
    assert caps.attenuators == (20,)
    assert caps.level_ranges["NR"] == [0.0, 1.0, 0.066667] and caps.level_ranges["NB"] == [0.0, 10.0, 1.0]
    assert "NOTCHF_RAW" not in caps.level_ranges and "AGC" not in caps.level_ranges   # plages vides « 0..0 » ignorées
    assert caps.to_dict()["attenuators"] == [20]


def test_declared_level_range_is_enforced_by_the_link():
    async def scenario(fake):
        caps = Capabilities(complete=True, functions=("NR",), levels=("NB", "NR", "STRENGTH"), level_ranges={"NB": [0.0, 10.0, 1.0]})
        link = make_link(fake, capabilities=caps)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.connected)
        await link.set_level("NB", 7)
        assert fake.levels["NB"] == 7.0
        with pytest.raises(ValueError):
            await link.set_level("NB", 10.5)                                      # au-delà de la plage du poste
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)


def test_declared_attenuator_values_win_over_an_inconsistent_range():
    """Hamlib 5 (IC-7300MK2) : « Attenuator: 20dB » ET « ATT(0..12) » : 20 dB doit passer, 15 non."""
    async def scenario(fake):
        caps = Capabilities(complete=True, levels=("ATT", "STRENGTH"), attenuators=(20,), level_ranges={"ATT": [0.0, 12.0, 0.0]})
        link = make_link(fake, capabilities=caps)
        task = asyncio.create_task(link.run())
        await until(lambda: link.state.connected)
        await link.set_level("ATT", 20)
        assert fake.levels["ATT"] == 20
        with pytest.raises(ValueError):
            await link.set_level("ATT", 15)                                      # ni dans la liste, ni dans la plage
        link.stop()
        await asyncio.wait_for(task, 3)
    run(scenario)
