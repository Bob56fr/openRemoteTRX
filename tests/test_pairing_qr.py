# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""QR code d'appairage (TRX Console menu 19, `trx-setup --empreinte`) : contenu partagé avec l'application
(tests/protocol/pairing.json, lu aussi par android/protocol PairingTest), jamais de mot de passe."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trxstation import setup_wizard as wizard
from trxstation.setup_wizard import _make_certificate, add_client, dummy_config, pairing_uri, qr_lines, show_pairing

EXAMPLES = json.loads((Path(__file__).parent / "protocol" / "pairing.json").read_text(encoding="utf-8"))


def test_station_produces_exactly_the_shared_example():
    s = EXAMPLES["station"]
    assert pairing_uri(s["name"], s["url"], s["user"], s["fingerprint"]) == EXAMPLES["valid"][0]["uri"]


def test_qr_drawing_is_the_exact_qr_matrix():
    segno = pytest.importorskip("segno")
    text = EXAMPLES["valid"][0]["uri"]
    lines = qr_lines(text, border=2)
    matrix = [[bool(m) for m in row] for row in segno.make(text, error="m", micro=False).matrix]
    size = len(matrix)
    assert len(lines[0]) == size + 4 and len(lines) == (size + 5) // 2
    top = {"█": True, "▀": True, "▄": False, " ": False}
    bottom = {"█": True, "▀": False, "▄": True, " ": False}
    light = []                                                   # rangées reconstruites depuis les caractères
    for line in lines:
        light.append([top[ch] for ch in line])
        light.append([bottom[ch] for ch in line])
    for r in range(size + 4):
        for c in range(size + 4):
            inside = 2 <= r < size + 2 and 2 <= c < size + 2
            expected_light = not (inside and matrix[r - 2][c - 2])
            assert light[r][c] == expected_light, (r, c)


def station(tmp_path, accounts=("S25",)):
    cfg = dummy_config()
    cfg.network.gateway_bind = "0.0.0.0"
    passwords = [add_client(cfg, name, "Mot-De-Passe-Secret-42") for name in accounts]
    _make_certificate(["192.168.1.10"], tmp_path / "tls", cfg)
    return cfg, passwords


def run(cfg, answers=()):
    out: list[str] = []
    replies = iter(answers)
    show_pairing(cfg, ask=lambda _p: next(replies, ""), say=out.append, addresses=lambda: ["192.168.1.10", "10.8.0.2"],
                 hostname=lambda: "station-radio")
    return "\n".join(out)


def test_pairing_shows_a_qr_code_without_any_password(tmp_path, monkeypatch):
    pytest.importorskip("segno")
    cfg, passwords = station(tmp_path)
    seen: list[str] = []
    real = wizard.pairing_uri
    monkeypatch.setattr(wizard, "pairing_uri", lambda *a: seen.append(real(*a)) or seen[-1])
    text = run(cfg, answers=["2"])                                   # seconde adresse (VPN)
    assert "█" in text and "AUCUN mot de passe" in text
    assert seen and "u=https%3A%2F%2F10.8.0.2%3A8443" in seen[0] and "id=S25" in seen[0] and "n=station-radio" in seen[0]
    for secret in passwords + ["Mot-De-Passe"]:
        assert secret not in text and secret not in seen[0]
    assert "pw=" not in seen[0]


def test_several_accounts_are_offered_and_enter_means_none(tmp_path, monkeypatch):
    pytest.importorskip("segno")
    cfg, _ = station(tmp_path, accounts=("S25", "PC"))
    seen: list[str] = []
    real = wizard.pairing_uri
    monkeypatch.setattr(wizard, "pairing_uri", lambda *a: seen.append(real(*a)) or seen[-1])
    text = run(cfg, answers=["", ""])
    assert "1) S25" in text and "2) PC" in text and "id=" not in seen[0]
    run(cfg, answers=["", "2"])
    assert "id=PC" in seen[1]


def test_without_segno_the_fingerprint_text_remains(tmp_path, monkeypatch):
    cfg, _ = station(tmp_path)
    monkeypatch.setattr(wizard, "qr_lines", lambda *a, **k: None)
    text = run(cfg)
    assert "segno" in text and "Empreinte du certificat" in text


def test_no_qr_code_when_the_station_is_not_reachable_or_has_no_certificate(tmp_path):
    cfg, _ = station(tmp_path)
    cfg.network.gateway_bind = "127.0.0.1"
    assert "█" not in run(cfg)
    cfg, _ = station(tmp_path)
    cfg.network.tls_cert = ""
    assert "█" not in run(cfg)
