# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Aides de trx-setup pour les Yaesu FTDX10 / FTDX101 (double port CP2105, menus, modes d'émission)."""
from __future__ import annotations

from trxstation.config import Config
from trxstation.rig_hints import hint_for, port_label, port_role
from trxstation.setup_wizard import apply_rig_hint, choose_cat_port

ENH = "/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_01A9994B-if00-port0"
STD = "/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_01A9994B-if01-port0"
ICOM = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_IC-7300_13003336-if00-port0"


def test_yaesu_models_known_icom_left_alone():
    for model in (1042, 1040, 1044):
        hint = hint_for(model)
        assert hint is not None and hint.speed == 38400 and hint.ptt_type == "RIG"
        assert any("RPTT SELECT" in line for line in hint.checklist)       # RTS/DTR : risque d'émission
    assert hint_for(3094) is None and hint_for(1) is None


def test_cp2105_interfaces():
    assert port_role(ENH) == "enhanced" and "CAT" in port_label(ENH)
    assert port_role(STD) == "standard" and "pas le CAT" in port_label(STD)
    assert port_role(ICOM) == "" and port_label(ICOM) == ICOM
    assert port_role("COM8") == ""


def test_enhanced_port_offered_first_standard_refused_without_confirmation():
    seen = {}

    def chooser(title, options, current=""):
        seen["options"] = [v for v, _ in options]
        return seen.setdefault("answers", [STD, ENH]).pop(0)

    asked = []
    port = choose_cat_port([STD, ICOM, ENH], "", chooser=chooser,
                           yes_no_fn=lambda q, d: asked.append(q) or False, say=lambda s: None)
    assert seen["options"] == [ENH, ICOM, STD]
    assert port == ENH and len(asked) == 1                                  # Standard refusé, nouvelle question
    assert choose_cat_port([STD], "", chooser=lambda *a, **k: STD, yes_no_fn=lambda q, d: True, say=lambda s: None) == STD


def test_tx_modes_fail_safe_unless_usb_voice_confirmed():
    cfg = Config()
    out = []
    apply_rig_hint(cfg, hint_for(1042), data_modes=lambda: ["PKTUSB", "PKTLSB"], yes_no_fn=lambda q, d: d, say=out.append)
    assert cfg.rig.tx_modes == ["PKTUSB", "PKTLSB"]                        # réponse par défaut : modes données seuls
    assert any("CAT RATE" in line for line in out)
    apply_rig_hint(cfg, hint_for(1042), data_modes=lambda: ["PKTUSB"], yes_no_fn=lambda q, d: True, say=out.append)
    assert cfg.rig.tx_modes == []                                           # voix par l'USB confirmée : tous les modes
