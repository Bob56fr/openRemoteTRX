# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Contrat du protocole client <-> station (docs/protocole.md) : les exemples partagés de tests/protocol/, lus aussi
par les tests de la page et de l'application Android, collent EXACTEMENT à ce que la station accepte et produit."""
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation.gateway.api.protocol import BASE_FEATURES, COMMANDS, OPTIONAL_FEATURES, ProtocolError, parse_command
from trxstation.gateway.api.session import build_state
from trxstation.gateway.audio.beeps import BeepConfig
from trxstation.gateway.cat import Capabilities
from trxstation.gateway.memories import Memory
from trxstation.gateway.safety.ptt import PttSnapshot

from test_api import connect, run, station

FOLDER = Path(__file__).parent / "protocol"
COMMAND_CASES = json.loads((FOLDER / "commands.json").read_text(encoding="utf-8"))
MESSAGES = json.loads((FOLDER / "messages.json").read_text(encoding="utf-8"))


def test_every_command_has_examples_and_no_example_names_an_unknown_command():
    examples = COMMAND_CASES["commands"]
    assert set(examples) == set(COMMANDS), "commande ajoutée ou retirée : mettre à jour tests/protocol/commands.json et docs/protocole.md"
    assert all(case["valid"] for case in examples.values())


def test_every_command_is_documented():
    doc = (Path(__file__).parents[1] / "docs" / "protocole.md").read_text(encoding="utf-8")
    missing = [name for name in COMMANDS if f"`{name}`" not in doc]
    assert not missing, f"commandes absentes de docs/protocole.md : {missing}"


@pytest.mark.parametrize("name", sorted(COMMAND_CASES["commands"]))
def test_shared_examples_are_accepted_or_refused_as_announced(name):
    case = COMMAND_CASES["commands"][name]
    for message in case["valid"]:
        command = parse_command(json.dumps(message))
        assert command.name == name and command.id == message.get("id")
    for bad in case["invalid"]:
        with pytest.raises(ProtocolError) as exc:
            parse_command(json.dumps(bad["message"]))
        assert exc.value.code == bad["code"], bad


def test_shared_raw_rejections():
    for bad in COMMAND_CASES["rejected"]:
        with pytest.raises(ProtocolError) as exc:
            parse_command(bad["raw"])
        assert exc.value.code == bad["code"]


def test_message_examples_have_the_fields_the_station_really_sends():
    hello, state = MESSAGES["hello"], MESSAGES["state"]
    assert set(hello["capabilities"]) == set(Capabilities().to_dict())
    assert set(hello["beeps"]) == set(BeepConfig().to_dict()) == set(MESSAGES["beeps"]["settings"])
    memory = asdict(Memory("x", "n", 1, "USB"))
    assert all(set(m) == set(memory) for m in hello["memories"] + MESSAGES["memories"]["items"])
    assert set(MESSAGES["result"][0]["ptt"]) == set(asdict(PttSnapshot("RX", None, None, False, "", "")))
    assert set(hello["features"]) <= set(BASE_FEATURES + OPTIONAL_FEATURES)
    assert all(m["type"] == kind for kind in ("result", "error") for m in MESSAGES[kind])
    assert {state["type"], MESSAGES["memories"]["type"], MESSAGES["beeps"]["type"], MESSAGES["module"]["type"],
            MESSAGES["selcall"]["type"]} == {"state", "memories", "beeps", "module", "selcall"}
    from trxstation.selcall.receiver import SelcallStatus
    assert set(hello["selcall"]) == set(SelcallStatus().to_dict()) == set(MESSAGES["selcall"]["status"])


def test_real_hello_and_state_match_the_shared_examples():
    async def scenario(fake):
        caps = Capabilities(model_name="Faux poste", modes=("USB", "LSB"), complete=True)
        async with station(fake, capabilities=caps) as st:
            phone = await connect(st, "phone")
            hello, state = phone.of_type("hello")[0], phone.of_type("state")[0]
            example = MESSAGES["hello"]
            assert set(hello) == set(example)
            assert set(hello["capabilities"]) == set(example["capabilities"])
            assert hello["features"][:len(BASE_FEATURES)] == list(BASE_FEATURES)
            assert set(hello["features"]) - set(BASE_FEATURES) == {"memories"}          # rien d'autre dans ce banc d'essai
            example = MESSAGES["state"]
            assert set(state) == set(example)
            for part in ("ptt", "rig"):
                assert set(state[part]) == set(example[part]), part
            assert {"state", "code", "message"} <= set(state["spectrum"])
            await phone.say(cmd="toggle", id=1)
            await phone.say(cmd="stop", id=2)
            assert set(phone.result(1)["ptt"]) == set(MESSAGES["result"][0]["ptt"])
    run(scenario)


def test_state_carries_local_operator_and_temperature_for_the_clients():
    """La page (et l'application) affichent « poste utilisé sur place », « Reprendre la main » et l'alerte de
    température d'après state.ptt : ces champs doivent y être (absents jusqu'à la version 0.51.0)."""
    snap = PttSnapshot("RX", None, None, False, "", "", local_remaining_s=95.4321, local_reason="frequency",
                       local_tx=False, temp_alert="warn", temp_c=43.0)
    from trxstation.gateway.cat import RigState
    rig = RigState(connected=True, frequency_hz=7074000, mode="USB", passband_hz=2400, strength_db=-60)
    ctrl = SimpleNamespace(snapshot=lambda: snap, clients=["phone"])
    ptt = build_state(SimpleNamespace(state=rig), ctrl)["ptt"]
    assert ptt["local_remaining_s"] == 95.4 and ptt["local_reason"] == "frequency" and ptt["local_tx"] is False
    assert ptt["temp_alert"] == "warn" and ptt["temp_c"] == 43.0


def test_spectrum_frames_match_the_shared_examples():
    """Trames du canal « spectrum » : la station produit exactement les octets des exemples (lus aussi par l'application)."""
    from trxstation.spectrum.civ import Sweep
    from trxstation.spectrum.frame import encode
    examples = json.loads((FOLDER / "spectrum.json").read_text(encoding="utf-8"))
    for case in examples["valid"]:
        s = case["sweep"]
        sweep = Sweep(t=0.0, mode=s["mode"], f1_hz=s["f1_hz"], f2_hz=s["f2_hz"], out_of_range=s["out_of_range"], points=s["points"])
        assert encode(sweep, case["seq"]).hex() == case["hex"], case["name"]
