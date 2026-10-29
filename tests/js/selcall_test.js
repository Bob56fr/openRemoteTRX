// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Tests du SELCALL de la page (selcall.js) : `node tests/js/selcall_test.js [fichier.wav]`
// Avec un chemin : écrit aussi le fichier de test du code 4721 en 8 kHz (décodé par la station dans test_selcall_protocol.py).
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const sc = require(path.join(__dirname, "../../trxstation/gateway/api/static/selcall.js"));
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, "../protocol/selcall_vectors.json"), "utf-8"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("mêmes symboles et mêmes tons que la station (vecteurs partagés)", () => {
  assert.equal(sc.F0_HZ, vectors.f0_hz); assert.equal(sc.PILOT_S, vectors.pilot_s); assert.equal(sc.SYMBOL_S, vectors.symbol_s);
  for (const c of vectors.cases) {
    assert.deepEqual(sc.symbols(c.code), c.symbols, c.code);
    assert.deepEqual(sc.tones(c.code), c.tones, c.code);
  }
  for (const bad of vectors.invalid) { assert.equal(sc.validCode(bad), false); assert.throws(() => sc.symbols(bad)); }
});

test("trame : longueur, niveau -6 dBFS, rampes sans clic, phase continue", () => {
  const x = sc.frameSamples("4477", 8000);
  assert.equal(x.length, 2.5 * 8000);
  let peak = 0, jump = 0;
  for (let i = 0; i < x.length; i++) { peak = Math.max(peak, Math.abs(x[i])); if (i) jump = Math.max(jump, Math.abs(x[i] - x[i - 1])); }
  assert.ok(peak <= Math.pow(10, -6 / 20) + 1e-6);
  assert.ok(Math.abs(x[0]) < 1e-3 && Math.abs(x[x.length - 1]) < 1e-3);
  assert.ok(jump < 2 * Math.PI * 2200 / 8000 * Math.pow(10, -6 / 20));
});

test("fichier de test : 2 s de silence, 3 trames séparées de 0,5 s, WAV valide", () => {
  const rate = 48000, s = sc.testSamples("4721", { rate });
  const frame = 2.5 * rate;
  assert.equal(s.length, 2 * rate + 3 * frame + 2 * 0.5 * rate + 0.5 * rate);
  assert.equal(Math.max(...s.slice(0, 2 * rate).map(Math.abs)), 0);
  const wav = sc.testWav("4721");
  const v = new DataView(wav.buffer);
  assert.equal(String.fromCharCode(...wav.slice(0, 4)), "RIFF");
  assert.equal(v.getUint32(24, true), rate); assert.equal(v.getUint16(22, true), 1); assert.equal(v.getUint16(34, true), 16);
  assert.equal(v.getUint32(40, true), 2 * s.length);
});

test("indicateur de l'en-tête", () => {
  assert.equal(sc.indicator(null), null);
  assert.equal(sc.indicator({ state: "disabled", code: "4721" }), null);
  assert.deepEqual(sc.indicator({ state: "standby", code: "4721" }), { text: "SEL 4721", open: false });
  assert.deepEqual(sc.indicator({ state: "open", code: "4721" }), { text: "SEL OUVERT", open: true });
});

if (process.argv[2]) fs.writeFileSync(process.argv[2], sc.testWav("4721", { rate: 8000 }));

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du SELCALL (page) réussis");
process.exit(failed ? 1 : 0);
