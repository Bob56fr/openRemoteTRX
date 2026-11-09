// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Sonde de qualité réseau, calculs de la page (netprobe.js) : mêmes résultats que la station et l'application
   (netprobe_vectors.json). */
"use strict";
const assert = require("assert");
const path = require("path");
const fs = require("fs");
const np = require(path.join(__dirname, "..", "..", "trxstation", "gateway", "api", "static", "netprobe.js"));
const shared = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "protocol", "netprobe_vectors.json"), "utf8"));
const EDGES = { rtt: np.RTT_EDGES_MS, loss: np.LOSS_EDGES_PCT };

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("constantes : celles de la station", () => {
  const k = shared.constants;
  assert.deepEqual([k.late_ms, k.windows_ms, k.min_measured_ms, k.recent_outage_ms, k.diagnoses],
                   [np.LATE_MS, np.WINDOWS_MS, np.MIN_MEASURED_MS, np.RECENT_OUTAGE_MS, np.DIAGNOSES]);
  assert.deepEqual(shared.buckets.rtt_edges_ms, np.RTT_EDGES_MS);
  assert.deepEqual(shared.buckets.loss_edges_pct, np.LOSS_EDGES_PCT);
});

test("fenêtres : perte, aller-retour, gigue, hors séquence", () => {
  for (const c of shared.window_stats) {
    const beats = c.beats.map((b) => ({ seq: b[0], sentMs: b[1], pongMs: b[2] }));
    assert.deepEqual(np.windowStats(beats, c.now_ms, c.window_ms), c.expect, c.name);
  }
});

test("coupures", () => {
  for (const c of shared.outages) {
    const d = new np.OutageDetector(c.missed, c.interval_ms);
    let got = [];
    for (const e of c.events) got = got.concat(e[0] === "tick" ? d.tick(e[1]) : d[e[0]](e[1], e[2]));
    assert.deepEqual(got, c.expect, c.name);
  }
});

test("niveau de l'indicateur", () => {
  for (const c of shared.level) {
    const got = np.level({ measuredMs: c.measured_ms, lossPct: c.loss_pct, rttP95Ms: c.rtt_p95_ms, outageActive: c.outage_active,
                           sinceOutageEndMs: c.since_outage_end_ms, rsrpDbm: c.rsrp_dbm, sinrDb: c.sinr_db }, shared.thresholds);
    assert.equal(got, c.expect, c.name);
  }
});

test("diagnostic et motif régulier", () => {
  for (const c of shared.diagnose) assert.equal(np.diagnose(c.facts), c.expect, c.name);
  for (const c of shared.regular_pattern) assert.deepEqual(np.regularPattern(c.outages, c.now_ms), c.expect, c.name);
});

test("histogrammes : cases, seuils proposés, essai de seuils", () => {
  for (const c of shared.buckets.cases) assert.equal(np.bucket(c.value, EDGES[c.metric]), c.expect, JSON.stringify(c));
  for (const c of shared.propose) assert.deepEqual(np.propose(c.hist, EDGES[c.metric], c.days), c.expect, c.name);
  for (const c of shared.simulate) assert.deepEqual(np.simulate(c.hist, EDGES[c.metric], c.warn, c.alert), c.expect, c.name);
});

test("arrondi au dixième, moitié vers le haut", () => {
  assert.deepEqual([np.round1(0.25), np.round1(0.35), np.round1(2.45), np.round1(-0.25)], [0.3, 0.4, 2.5, -0.2]);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (e) { failed++; console.log("ECHEC " + name + "\n      " + (e.stack || e)); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests de la sonde réseau réussis");
if (failed) process.exit(1);
