# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Diffusion en direct : raison d'un silence voulu, dite aux auditeurs (étape 247, docs/protocole-diffusion.md § 3.1)."""
from __future__ import annotations

import json
import time

import pytest

from trxstation.diffusion import protocol as p
from trxstation.diffusion.service import DiffusionService
from trxstation.setup_wizard import dummy_config


def service(tmp_path, *, outside_bands=False):
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    cfg.diffusion.outside_bands = outside_bands
    cfg.diffusion.server, cfg.diffusion.station = "diffusion.example.org", "bob56fr"
    svc = DiffusionService(cfg, tmp_path / "station.toml")
    svc._session = {"access": "public", "voice": False, "phase": "en_direct"}
    svc._last_audio = time.monotonic()
    return svc


def test_body_carries_the_reason_only_when_there_is_one():
    plain = json.loads(p.meta_body("bob56fr", 1, "public", {"pseudo": "B"}))
    assert "silence" not in plain
    body = json.loads(p.meta_body("bob56fr", 2, "public", {"pseudo": "B"}, "hors_bandes"))
    assert body["silence"] == "hors_bandes" and body["meta"] == {"pseudo": "B"}
    with pytest.raises(p.DiffusionRefused):
        p.meta_body("bob56fr", 3, "public", {}, "autre")


def test_reasons_follow_the_gateway_rule(tmp_path):
    svc = service(tmp_path)
    in_band = int(svc.cfg.bands[0].low_mhz * 1e6) + 1000
    assert svc.silence_reason() is None                       # fréquence encore inconnue : rien d'affirmé
    svc.values["frequence_hz"] = 6_655_700                    # marine HF : hors des [[bands]]
    assert svc.silence_reason() == "hors_bandes"
    svc.values["frequence_hz"] = in_band
    assert svc.silence_reason() is None
    svc.values["tx"] = True                                   # émission, voix non cochée
    assert svc.silence_reason() == "emission"
    svc._session["voice"] = True
    assert svc.silence_reason() is None
    svc._last_audio = time.monotonic() - 5                    # plus de son de la passerelle
    assert svc.silence_reason() == "pas_de_son"
    svc._session = None
    assert svc.silence_reason() is None


def test_outside_bands_allowed_means_no_reason(tmp_path):
    svc = service(tmp_path, outside_bands=True)
    svc.values["frequence_hz"] = 6_655_700
    assert svc.silence_reason() is None


def test_status_publishes_the_reason(tmp_path):
    svc = service(tmp_path)
    svc._session.update({"started": 0, "ends": None, "listeners": 0, "operator": "BOB", "meta_choice": ["pseudo"],
                         "silence": "hors_bandes"})
    assert svc.status()["silence"] == "hors_bandes"
