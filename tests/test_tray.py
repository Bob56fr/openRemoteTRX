# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Indicateur Windows près de l'horloge (trxstation/tray) : même logique que l'indicateur GNOME (exemples communs),
lecture seule des fichiers de la station, infobulle et menu."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from trxstation.tray import main as tray
from trxstation.tray.status import DEBIAN_HINTS, WINDOWS_HINTS, summarize

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests" / "protocol" / "indicator_vectors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("vector", VECTORS, ids=[v["name"] for v in VECTORS])
def test_same_result_as_the_gnome_indicator(vector):
    assert summarize(vector["input"]) == vector["expect"]                 # arrondis et formats de JavaScript compris


def test_windows_hints_replace_trx_console_menus():
    view = summarize({"status": None, "nowS": 1.0, "safeMode": "pannes"}, WINDOWS_HINTS)
    texts = " ".join(line["text"] for line in view["lines"])
    assert "TRX Console" not in texts and "menu Démarrer" in texts
    assert "TRX Console, menu 1.1" in summarize({"status": None, "nowS": 1.0}, DEBIAN_HINTS)["lines"][0]["text"]


def test_collect_reads_the_station_files_and_never_raises(tmp_path):
    state = tmp_path / "state"
    (state / "cluster").mkdir(parents=True)
    status = tmp_path / "status.json"
    now = time.time()
    status.write_text(json.dumps({"pid": 1, "seq": 3, "written_at": now, "schema": 1, "clients": ["pc"],
                                  "ptt": {"state": "RX"}, "rig": {"connected": True, "frequency_hz": 14074000,
                                                                  "mode": "PKTUSB", "passband_hz": 3000}}), encoding="utf-8")
    (state / "cluster" / "status.json").write_text('{"enabled": true, "health": "orange"}', encoding="utf-8")
    (state / "station-id").write_text("abc\n", encoding="utf-8")
    view = summarize(tray.collect(status, state, now), WINDOWS_HINTS)
    assert view["level"] == "warn" and view["label"] == "14.074 USB-D"
    assert any(line["key"] == "Cluster DX" for line in view["lines"])
    (state / "cluster" / "status.json").write_text("{pas du json", encoding="utf-8")
    status.unlink()
    view = summarize(tray.collect(status, state, now), WINDOWS_HINTS)       # fichiers absents ou abîmés
    assert view["level"] == "off"


def test_tooltip_and_menu_lines():
    tx = summarize(VECTORS[1]["input"])
    assert tray.tooltip(tx) == "TRX distant : TX 1:12"
    assert tray.tooltip(summarize({"status": None, "nowS": 1.0})) == "TRX distant : arrêtée"
    warn = summarize(next(v["input"] for v in VECTORS if v["name"] == "liaison perdue"))
    tip = tray.tooltip(warn)
    assert tip.startswith("TRX distant : ") and "Poste : liaison perdue" in tip and len(tip) <= tray.TOOLTIP_MAX
    lines = tray.menu_lines(warn)
    assert "! Poste : liaison perdue (connexion refusée) : poste éteint ou débranché ?" in lines
    assert "Clients web : aucun" in lines


def test_tooltip_is_cut_to_the_windows_limit():
    view = {"level": "warn", "label": "7.195 LSB-D", "lines": [{"key": "Défaut", "text": "x" * 300, "level": "bad"}]}
    assert len(tray.tooltip(view)) == tray.TOOLTIP_MAX


def test_the_indicator_never_commands_the_station():
    source = (ROOT / "trxstation" / "tray" / "main.py").read_text(encoding="utf-8")
    for forbidden in ("PttController", "CatLink", "rigctld", "stop_tx", "force_rx", "write_ptt", "--stop", "aiohttp"):
        assert forbidden not in source, forbidden


def test_icon_colors_for_every_level():
    pytest.importorskip("PIL")
    for level in ("off", "ok", "tx", "warn", "stale", "safe"):
        img = tray.icon_image(level)
        assert img.size == (64, 64) and img.getpixel((12, 32))[3] == 255     # pastille opaque
    assert tray.icon_image("tx").getpixel((32, 32))[:3] == (255, 255, 255)    # point blanc en émission


def test_menu_builds_with_pystray(tmp_path):
    pytest.importorskip("pystray")
    from trxstation import config as cfgmod
    cfg = cfgmod.Config()
    cfg.supervisor.status_path = str(tmp_path / "absent.json")
    cfg.supervisor.state_dir = str(tmp_path)
    t = tray.Tray(cfg, tmp_path / "station.toml")
    t.refresh()
    items = t._menu()
    labels = [str(i.text) for i in items if hasattr(i, "text")]
    assert "Ouvrir la page web de la station" in labels and "Quitter l'indicateur" in labels
    assert not any(i.enabled for i in items[:len(t.view["lines"])])          # lignes d'état non cliquables
