# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sonde de qualité réseau, calculs purs (docs/netprobe-cahier-des-charges.md) : les exemples partagés
tests/protocol/netprobe_vectors.json (lus aussi par la page et l'application) et quelques cas recomptés à la main."""
import json
import shutil
import subprocess
from pathlib import Path

from trxstation.netprobe import calc
from trxstation.netprobe.calc import Beat, OutageDetector

SHARED = json.loads((Path(__file__).parent / "protocol" / "netprobe_vectors.json").read_text(encoding="utf-8"))
EDGES = {"rtt": calc.RTT_EDGES_MS, "loss": calc.LOSS_EDGES_PCT}


def test_constants_are_the_shared_ones():
    k = SHARED["constants"]
    assert (k["late_ms"], tuple(k["windows_ms"]), k["min_measured_ms"], k["recent_outage_ms"]) == \
        (calc.LATE_MS, calc.WINDOWS_MS, calc.MIN_MEASURED_MS, calc.RECENT_OUTAGE_MS)
    assert tuple(k["diagnoses"]) == calc.DIAGNOSES
    assert tuple(SHARED["buckets"]["rtt_edges_ms"]) == calc.RTT_EDGES_MS
    assert tuple(SHARED["buckets"]["loss_edges_pct"]) == calc.LOSS_EDGES_PCT


def test_shared_examples():
    for c in SHARED["window_stats"]:
        assert calc.window_stats([Beat(*b) for b in c["beats"]], c["now_ms"], c["window_ms"]) == c["expect"], c["name"]
    for c in SHARED["outages"]:
        d, got = OutageDetector(c["missed"], c["interval_ms"]), []
        for e in c["events"]:
            got += d.tick(e[1]) if e[0] == "tick" else getattr(d, e[0])(e[1], e[2])
        assert got == c["expect"], c["name"]
    th = SHARED["thresholds"]
    for c in SHARED["level"]:
        assert calc.level(c["measured_ms"], c["loss_pct"], c["rtt_p95_ms"], c["outage_active"], c["since_outage_end_ms"],
                          c["rsrp_dbm"], c["sinr_db"], th) == c["expect"], c["name"]
    for c in SHARED["diagnose"]:
        assert calc.diagnose(c["facts"]) == c["expect"], c["name"]
    for c in SHARED["regular_pattern"]:
        assert calc.regular_pattern(c["outages"], c["now_ms"]) == c["expect"], c["name"]
    for c in SHARED["buckets"]["cases"]:
        assert calc.bucket(c["value"], EDGES[c["metric"]]) == c["expect"], c
    for c in SHARED["propose"]:
        assert calc.propose(c["hist"], EDGES[c["metric"]], c["days"]) == c["expect"], c["name"]
    for c in SHARED["simulate"]:
        assert calc.simulate(c["hist"], EDGES[c["metric"]], c["warn"], c["alert"]) == c["expect"], c["name"]


def test_shared_examples_cover_every_rule():
    """Chaque diagnostic et chaque niveau apparaît au moins une fois dans les exemples partagés."""
    assert {c["expect"] for c in SHARED["diagnose"]} == set(calc.DIAGNOSES)
    assert {c["expect"] for c in SHARED["level"]} == {"gray", "green", "orange", "red"}
    assert any(c["expect"]["regular"] for c in SHARED["regular_pattern"])
    assert any(c["expect"]["out_of_order"] for c in SHARED["window_stats"])
    assert any(c["expect"]["late"] for c in SHARED["window_stats"])


def test_window_counts_recomputed_by_hand():
    beats = [Beat(1, 1000, 1050), Beat(2, 2000, None), Beat(3, 3000, 9100), Beat(4, 4000, 4060), Beat(5, 5000, None),
             Beat(6, 6000, 6045), Beat(7, 7000, 7055), Beat(8, 8000, None), Beat(9, 9000, None), Beat(10, 10000, 10050)]
    s = calc.window_stats(beats, 10600, 10000)
    # reçus : 1, 4, 6, 7, 10 ; perdus : 2 et 5 (plus de 5 s sans écho), 3 (écho tardif) ; en attente : 8 et 9
    assert (s["received"], s["lost"], s["late"], s["expected"], s["loss_pct"]) == (5, 3, 1, 8, 37.5)
    assert (s["rtt_mean_ms"], s["rtt_max_ms"]) == (52.0, 60)
    # gigue RFC 3550 sur 50, 60, 45, 55, 50 : 10/16 = 0,625 ; +(15-0,625)/16 ; +(10-…)/16 ; +(5-…)/16
    j = 0.0
    for d in (10, 15, 10, 5):
        j += (d - j) / 16
    assert s["jitter_ms"] == calc.round1(j)


def test_out_of_order_echo_is_counted_once():
    beats = [Beat(1, 1000, 1040), Beat(2, 2000, 2600), Beat(3, 3000, 2900 + 100)]   # 2 arrive à 2600, 3 à 3000 : en ordre
    assert calc.window_stats(beats, 4000, 10000)["out_of_order"] == 0
    beats = [Beat(1, 1000, 1040), Beat(2, 2000, 3600), Beat(3, 3000, 3050)]          # 3 arrive avant 2
    assert calc.window_stats(beats, 4000, 10000)["out_of_order"] == 1


def test_outage_needs_the_configured_number_of_missed_beats_and_ends_at_any_echo():
    d = OutageDetector(3, 1000)
    assert d.ping(1, 0) == [] and d.ping(2, 1000) == [] and d.ping(3, 2000) == []
    assert d.tick(2999) == []                                     # le 3e n'a pas encore eu un intervalle entier
    assert d.tick(3000) == [{"type": "start", "start_ms": 0, "detected_ms": 3000}]
    assert d.tick(5000) == [] and d.start_ms == 0                 # une seule annonce par coupure
    assert d.pong(1, 6000) == [{"type": "end", "start_ms": 0, "end_ms": 6000, "duration_ms": 6000}]
    assert d.tick(9000) == []                                     # les battements d'avant l'écho ne comptent plus


def test_round1_is_half_up_like_javascript_and_kotlin():
    assert (calc.round1(0.25), calc.round1(0.35), calc.round1(2.45), calc.round1(-0.25)) == (0.3, 0.4, 2.5, -0.2)


def test_page_calculations_are_the_same():
    """netprobe.js (page) sur les mêmes exemples ; l'application les vérifie dans NetProbeTest (gradlew test)."""
    node = shutil.which("node")
    if not node:
        return                                                                          # Node absent : test ignoré
    script = Path(__file__).parent / "js" / "netprobe_test.js"
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_regular_pattern_period_of_the_vpn_incident():
    """Incident du 2026-11-09 (PC et S25 sur le même profil WireGuard) : coupures de ~3 s toutes les ~30 s."""
    outages = [{"start_ms": 30_000 * i + (500 if i % 2 else 0), "duration_ms": 3_000} for i in range(1, 7)]
    got = calc.regular_pattern(outages, 200_000)
    assert got["regular"] and 29_000 < got["period_ms"] < 31_000
