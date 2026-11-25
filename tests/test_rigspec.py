# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fiche technique du poste (étape 393) : fichiers livrés valides, fiche générique pour un poste inconnu, et délais du
poste appliqués à la détection « poste utilisé sur place » (signalement du 2026-11-25 : FTDX10 jugé « pris en main sur
place » à tort après un changement de fréquence de la station)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trxstation import rigspec
from trxstation.gateway.safety.local import EXPECT_S, LocalPresence
from trxstation.rigspec import RigSpec, RigSpecError, Timing

EXAMPLE = json.loads((Path(__file__).parent / "protocol" / "messages.json").read_text(encoding="utf-8"))["hello"]


def test_every_shipped_spec_is_valid_and_named_after_its_model():
    files = sorted((rigspec.FOLDER / "models").glob("*.toml"))
    assert files, "aucune fiche de poste"
    for path in files:
        spec = rigspec.parse(path.read_text(encoding="utf-8"), path.name)
        assert spec.model == int(path.stem) and spec.name
        assert rigspec.load(spec.model) == spec
    generic = rigspec.parse((rigspec.FOLDER / "generic.toml").read_text(encoding="utf-8"))
    assert generic.model == 0 and rigspec.load(999_999) == generic and rigspec.load(1) == generic   # poste factice


def test_known_rigs_say_what_the_user_decided():
    ftdx10, ftdx101, ic7300 = rigspec.load(1042), rigspec.load(1040), rigspec.load(3094)
    assert ftdx10.timing.read_delay_s > 0 and ftdx10.timing.linked_changes and ftdx10.filters.kind == "steps"
    assert ftdx10.squelch.source == "busy" and ftdx101.receivers == 2
    assert ic7300.filters == rigspec.Filters("presets", 3) and not ic7300.timing.linked_changes


@pytest.mark.parametrize("text, words", [
    ("format = 2\nmodel = 5\nname = 'x'", "format"),
    ("format = 1\nmodel = 5\nname = 'x'\ncouleur = 'bleu'", "inconnu"),
    ("format = 1\nmodel = 5\nname = 'x'\n[timing]\nread_delay_s = 99", "délais"),
    ("format = 1\nmodel = 5\nname = 'x'\n[timing]\nlinked_changes = 'oui'", "bool"),
    ("format = 1\nmodel = 5\nname = 'x'\nreceivers = 3", "receivers"),
    ("format = 1\nmodel = 5\nname = 'x'\n[filters]\nkind = 'presets'", "presets"),
    ("format = 1\nmodel = 5\nname = 'x'\n[squelch]\nsource = 'magie'", "squelch"),
    ("format = 1\nmodel = 'cinq'", "int"),
    ("format = 1\nmodel = 5\nname = 'x'\n[filters]\nkind = 'steps'\n[filters.steps]\nUSB = [2400, 1800]", "croissantes"),
    ("format = 1\nmodel = 5\nname = 'x'\n[filters]\nkind = 'steps'\n[filters.steps]\nusb = [1800, 2400]", "steps"),
    ("format = 1\nmodel = 5\nname = 'x'\n[filters]\nkind = 'presets'\npresets = 3\nquick = [1800, 2400]", "quick"),
])
def test_a_wrong_spec_is_refused(text, words):
    with pytest.raises(RigSpecError, match=words):
        rigspec.parse(text)


def test_hello_example_has_every_field_of_the_spec():
    spec = EXAMPLE["rig_spec"]
    full = RigSpec().to_dict()
    assert set(spec) == set(full)
    for section in ("timing", "filters", "squelch"):
        assert set(spec[section]) == set(full[section])


# --------------------------------------------------------------------------- délais du poste et poste sur place

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def presence(timing: Timing):
    clock = Clock()
    return LocalPresence(clock=clock, timing=timing), clock


def see(p, *, freq=14_200_000, mode="USB", panel=None):
    return p.observe(True, False, freq, mode, "RX", panel, None)


def test_slow_rig_reading_after_the_command_is_still_the_station_own_change():
    slow = rigspec.load(1042).timing
    p, clock = presence(slow)
    see(p)
    p.expect("frequency")                                  # avant la commande
    clock.now += 2.5                                       # commande lente (FTDX10)
    p.expect("frequency")                                  # après la commande : la fenêtre repart d'ici
    clock.now += EXPECT_S + slow.read_delay_s - 0.5        # relecture tardive, encore dans la fenêtre
    assert see(p, freq=14_250_000) is False and not p.active()
    clock.now += 5
    assert see(p, freq=14_260_000) is True and p.reason == "frequency"   # bouton tourné plus tard : vu


def test_mode_restored_by_the_band_memory_is_not_a_local_action():
    p, clock = presence(rigspec.load(1042).timing)
    see(p, freq=14_200_000, mode="USB")
    p.expect("frequency")
    see(p, freq=7_100_000, mode="USB")
    clock.now += 1
    assert see(p, freq=7_100_000, mode="LSB") is False and not p.active()   # mode de la bande remis par le poste
    # poste sans mémoire par bande (fiche Icom) : un mode changé après une commande de fréquence reste une action locale
    p, clock = presence(rigspec.load(3094).timing)
    see(p, freq=14_200_000, mode="USB")
    p.expect("frequency")
    see(p, freq=7_100_000, mode="USB")
    clock.now += 1
    assert see(p, freq=7_100_000, mode="LSB") is True and p.reason == "mode"


def test_tuner_in_service_lengthens_the_wait():
    timing = Timing(read_delay_s=0.0, tuner_delay_s=3.0, linked_changes=False)
    p, clock = presence(timing)
    see(p, panel={"f:TUNER": False})
    assert p.expect_window_s() == EXPECT_S
    see(p, panel={"f:TUNER": True})
    assert p.expect_window_s() == EXPECT_S + 3.0
    p.expect("frequency")
    clock.now += EXPECT_S + 2.0
    assert see(p, freq=14_210_000, panel={"f:TUNER": True}) is False


def test_generic_spec_keeps_the_old_wait():
    p, clock = presence(rigspec.load(1).timing)
    assert p.expect_window_s() == EXPECT_S


def test_ftdx10_short_press_list_is_the_user_choice_and_only_in_ssb():
    spec = rigspec.load(1042)
    assert spec.filters.quick == (1800, 2400, 2800, 3000, 3500, 4000)
    assert rigspec.quick_widths(spec, "USB") == spec.filters.quick and rigspec.quick_widths(spec, "LSB")
    assert rigspec.quick_widths(spec, "CW") == () and rigspec.quick_widths(spec, "FM") == ()
    assert spec.filters.steps["USB"][0] == 300 and spec.filters.steps["USB"][-1] == 4000 and len(spec.filters.steps["USB"]) == 23
    assert len(spec.filters.steps["CW"]) == 21
