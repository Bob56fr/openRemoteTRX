// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Tests du module SDR de la page (sdr.js) : `node tests/js/sdr_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const sdr = require(path.join(__dirname, "../../trxstation/gateway/api/static/sdr.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("ligne base64 -> cases, niveaux comme la station (frames.py)", () => {
  const v = sdr.decodeLine(Buffer.from([0, 128, 255]).toString("base64"));
  assert.deepEqual(Array.from(v), [0, 128, 255]);
  assert.equal(sdr.levelDb(0), -150); assert.equal(sdr.levelDb(255), -22.5);
  assert.equal(sdr.decodeLine(""), null); assert.equal(sdr.decodeLine(null), null);
});

test("fréquences : case, abscisse, graduations", () => {
  assert.equal(sdr.binFreq(0, 4, 7100000, 2000000), 6350000);
  assert.equal(sdr.freqAt(500, 1000, 14100000, 2000000), 14100000);
  assert.equal(sdr.freqAt(0, 1000, 14100000, 2000000), 13100000);
  assert.equal(sdr.freqAt(2000, 1000, 14100000, 2000000), 15100000);       // borné au bord
  assert.equal(sdr.freqAt(10, 0, 1, 1), null);
  const t = sdr.ticks(7100000, 2000000, 6);
  assert.deepEqual(t, [6500000, 7000000, 7500000, 8000000]);             // pas de 500 kHz sur 2 MHz
});

test("couleurs : plancher noir, plancher + dynamique blanc", () => {
  const floorV = (-110 - sdr.DB_MIN) / sdr.DB_STEP;
  assert.equal(sdr.colorIndex(floorV, -110, 50), 0);
  assert.equal(sdr.colorIndex(floorV + 100, -110, 50), 255);
  assert.equal(sdr.colorIndex(floorV + 50, -110, 50), 128);
  const values = new Uint8Array(100).fill(80); values[3] = 250;
  assert.equal(sdr.floorDb(values), sdr.levelDb(80));
  assert.equal(sdr.floorDb([]), null);
});

test("saisie de fréquence et limites des réglages (mêmes que la station)", () => {
  assert.equal(sdr.parseMHz("14.1"), 14100000);
  assert.equal(sdr.parseMHz("7,074"), 7074000);
  assert.equal(sdr.parseMHz("14100"), 14100000);                         // en kHz
  assert.equal(sdr.parseMHz("abc"), null); assert.equal(sdr.parseMHz("0"), null);
  assert.equal(sdr.checkSettings({ center_hz: 14100000, lna: 3, gr: 45, rate: 8 }), "");
  assert.match(sdr.checkSettings({ gr: 60 }), /gr/);
  assert.match(sdr.checkSettings({ rate: 16 }), /rate/);
  assert.match(sdr.checkSettings({ ptt: 1 }), /inconnu/);
  assert.match(sdr.checkSettings({}), /aucun/);
});

test("curseurs de gain à l'endroit et ligne de gain", () => {
  assert.equal(sdr.rfFromLna(0), 8); assert.equal(sdr.lnaFromRf(8), 0); assert.equal(sdr.lnaFromRf(sdr.rfFromLna(3)), 3);
  assert.equal(sdr.ifFromGr(59), 0); assert.equal(sdr.grFromIf(39), 20); assert.equal(sdr.grFromIf(sdr.ifFromGr(45)), 45);
  assert.equal(sdr.checkSettings({ agc: false }), ""); assert.match(sdr.checkSettings({ agc: 1 }), /agc/);
  const auto = sdr.gainText({ lna: 2, gr: 50, agc: true, gr_now: 38, gain_db: 61.5 });
  assert.match(auto, /Gain RF 6\/8/); assert.match(auto, /FI auto \(gain FI 21\/39\)/); assert.match(auto, /61\.5 dB/);
  assert.match(sdr.gainText({ lna: 2, gr: 50, agc: false }), /gain FI 9\/39/);
  assert.match(sdr.gainText({ lna: 0, gr: 50, agc: true, overload: 1 }), /SURCHARGE/);
  assert.equal(sdr.gainText(null), "");
});

test("ligne d'état lisible", () => {
  assert.match(sdr.stateText(null), /attente/);
  const run = { state: "running", serial: "170502E910", center: 7100000, fs: 2000000, lna: 2, gr: 50, overload: 1, cpu: 12.5 };
  const t = sdr.stateText(run);
  assert.match(t, /170502E910/); assert.match(t, /7\.100 MHz/); assert.match(t, /SURCHARGE/); assert.match(t, /CPU 12\.5/);
  assert.match(sdr.stateText({ state: "error", code: "busy" }), /autre application/);
  assert.match(sdr.stateText({ state: "error", code: "zz", detail: "x" }), /x/);
  assert.equal(sdr.nextRange(80), 30);
});

test("volume du SDR : courbe au carré, bornée", () => {
  assert.strictEqual(sdr.volumeOf(100), 1);
  assert.strictEqual(sdr.volumeOf(0), 0);
  assert.strictEqual(sdr.volumeOf(50), 0.25);
  assert.strictEqual(sdr.volumeOf(150), 1);
  assert.strictEqual(sdr.volumeOf("x"), 0);
});

test("fréquence écoutée saisie : centre déplacé seulement hors de la fenêtre", () => {
  assert.deepStrictEqual(sdr.tuneArgs(7100000, 7093000, 1536000), { dfreq_hz: 7100000 });
  assert.deepStrictEqual(sdr.tuneArgs(14200000, 7093000, 1536000), { center_hz: 14200000, dfreq_hz: 14200000 });
  assert.deepStrictEqual(sdr.tuneArgs(7093000 + 760000, 7093000, 1536000), { center_hz: 7853000, dfreq_hz: 7853000 });
  assert.deepStrictEqual(sdr.tuneArgs(7000000, undefined, 0), { center_hz: 7000000, dfreq_hz: 7000000 });
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du module SDR (page) réussis");
process.exit(failed ? 1 : 0);
