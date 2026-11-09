# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""trx-netreport et export anonyme de la sonde réseau (docs/netprobe-cahier-des-charges.md § 10.3, EF10)."""
import io
import json
import time
import zipfile

from trxstation import config as cfgmod
from trxstation.netprobe.export import build_export, report_text
from trxstation.netprobe.netreport import main
from trxstation.netprobe.store import NetStore

NOW = int(time.time() * 1000)


def filled(folder):
    store = NetStore(folder / "netprobe")
    store.add_outage({"start_ms": NOW - 60_000, "end_ms": NOW - 54_000, "duration_ms": 6000, "device": "a" * 32,
                      "agent": "android 0.53.0", "client": "bob", "net_type": "4g", "kind": "in_session",
                      "diagnosis": "vpn_shared", "basis": ["regular_pattern"], "seen_by": "station"})
    stats = {"expected": 10, "received": 10, "lost": 0, "late": 0, "loss_pct": 0.0, "rtt_mean_ms": 40.0,
             "rtt_p95_ms": 50, "rtt_max_ms": 50, "jitter_ms": 1.0, "out_of_order": 0}
    store.add_window(NOW - 30_000, "a" * 32, "android 0.53.0", "4g", stats, False)
    store.log({"ts": NOW - 20_000, "src": "sonde", "kind": "mesure",
               "lan": {"address": "192.168.1.254", "method": "icmp", "ok": True, "loss_pct": 0.0, "rtt_ms": 2}})
    store.log({"ts": NOW - 10_000, "src": "client", "kind": "mesure", "device": "a" * 32, "client": "bob", "net_type": "4g"})
    store.flush()
    return store


def test_report_text_and_anonymous_export(tmp_path):
    store = filled(tmp_path)
    text = report_text(store.stats(1, "", {}))
    assert "Coupures            : 1" in text and "profil VPN probablement partagé" in text
    blob = build_export(store, 30, version="9.9.9", station_id="1234", settings={"enabled": True, "lan_target": "192.168.1.254"})
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert sorted(z.namelist()) == ["donnees.json", "rapport.html"]
        data = json.loads(z.read("donnees.json"))
        page = z.read("rapport.html").decode("utf-8")
    raw = json.dumps(data)
    assert "a" * 32 not in raw and '"bob"' not in raw and "192.168." not in raw and "lan_target" not in raw
    assert data["outages"][0]["device"] == "appareil-1" and data["hours"][0]["device"] == "appareil-1"
    assert data["version"] == "9.9.9" and data["station_id"] == "1234"
    assert any(r.get("lan", {}).get("method") == "icmp" for r in data["last_24h"])
    assert "Qualité du réseau" in page and page.startswith("<!doctype html>")


def test_netreport_command(tmp_path, capsys):
    cfg = cfgmod.Config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert main(["--config", str(path)]) == 1                                   # aucune mesure encore
    assert "Aucune mesure" in capsys.readouterr().out
    filled(tmp_path / "etat")
    assert main(["--config", str(path), "--jours", "7"]) == 0
    assert "7 derniers jours" in capsys.readouterr().out
    out = tmp_path / "sortie"
    out.mkdir()
    assert main(["--config", str(path), "--export", str(out)]) == 0
    files = list(out.glob("openremotetrx-reseau-*.zip"))
    assert len(files) == 1 and zipfile.is_zipfile(files[0])
    assert main(["--config", str(path), "--jours", "200"]) == 2
