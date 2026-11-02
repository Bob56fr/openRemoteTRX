// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Mesure de TOS, calculs de la page (swr.js) : mêmes résultats que la station et l'application (swr_plans.json). */
"use strict";
const assert = require("assert");
const path = require("path");
const fs = require("fs");
const sw = require(path.join(__dirname, "..", "..", "trxstation", "gateway", "api", "static", "swr.js"));
const shared = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "protocol", "swr_plans.json"), "utf8"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("table des bandes, pas lisibles et lignes du graphique : ceux de la station", () => {
  assert.deepEqual(sw.BANDS, shared.bands);
  assert.deepEqual(sw.NICE_STEPS_HZ, shared.nice_steps_hz);
  assert.deepEqual(sw.GRID, shared.grid);
});

test("plans : pas lisible, points ronds, trop de points, plages impossibles", () => {
  for (const c of shared.plans) {
    const got = sw.plan(c.low_hz, c.high_hz, c.points, c.max_points);
    if (c.error) assert.equal(got.error, c.error, JSON.stringify(c));
    else assert.deepEqual({ step_hz: got.stepHz, freqs: got.freqs, amateur_only: got.amateurOnly }, c.expect, JSON.stringify(c));
  }
});

test("centre et largeur, bande du poste, échelle et couleurs", () => {
  for (const c of shared.center) assert.deepEqual(sw.rangeFromCenter(c.center_hz, c.width_hz), { lowHz: c.low_hz, highHz: c.high_hz });
  for (const c of shared.band_at) {
    const b = sw.bandAt(c.hz);
    assert.deepEqual([b ? b.name : null, b ? b.kind : null], [c.name, c.kind]);
  }
  for (const c of shared.scale) assert.ok(Math.abs(sw.scaleY(c.swr) - c.y) < 1e-9, JSON.stringify(c));
  for (const c of shared.levels) assert.equal(sw.level(c.swr), c.level);
  assert.equal(sw.rangeFromCenter(7100000, 0), null);
});

test("textes : fréquences, TOS, couleurs, état remis et légende anonyme", () => {
  assert.equal(sw.freqLabel(14050000), "14.050"); assert.equal(sw.freqLabel(5357500), "5.3575");
  assert.equal(sw.swrText(1.234), "1,23"); assert.equal(sw.swrText(7), "> 5");
  assert.equal(sw.pointColor({ swr: 1.4 }), sw.COLORS.good); assert.equal(sw.pointColor({ swr: 1.9 }), sw.COLORS.fair);
  assert.equal(sw.pointColor({ swr: 2.5 }), sw.COLORS.bad); assert.equal(sw.pointColor({ swr: null, status: "out_of_band" }), sw.COLORS.none);
  const result = { restored: { frequency_hz: 14074000, mode: "PKTUSB", passband_hz: 3000, rfpower: 1, tuner: true },
                   differences: ["coupleur : non remis en service, à rallumer à la main"], power_w: 15, power_pct: 15, fm_mode: "FM-D",
                   best: { hz: 14150000, swr: 1.18 } };
  const r = sw.restoredLines(result, (m) => (m === "PKTUSB" ? "USB-D" : m));
  assert.deepEqual(r.lines, ["Fréquence : 14,0740 MHz", "Mode : USB-D (3000 Hz)", "Puissance : 100 %", "Coupleur : en service"]);
  assert.deepEqual(r.differences, ["coupleur : non remis en service, à rallumer à la main"]);
  assert.match(sw.restoredLines({}, null).lines[0], /non relu/);
  assert.deepEqual(sw.legendLines(result, " Dipôle 20 m ", null, "02/11/2026"),
                   ["Dipôle 20 m", "02/11/2026 · 15 W en FM-D · meilleur TOS 1,18 à 14.150 MHz"]);
  assert.equal(sw.legendLines(null, "", null, "")[0], "Mesure de TOS");
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (e) { failed++; console.log("ECHEC " + name + "\n      " + (e.stack || e)); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests de la mesure de TOS réussis");
if (failed) process.exit(1);
