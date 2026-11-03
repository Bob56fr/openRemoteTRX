// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Tests de la spatialisation stéréo de la réception (spatial.js) : `node tests/js/spatial_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const st = require(path.join(__dirname, "../../trxstation/gateway/api/static/spatial.js"));
const SHARED = path.join(__dirname, "../protocol/spatial_presets.json");

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

const RATE = 48000, D = st.LATENCY;
const on = (key) => st.choose(Object.assign(st.defaults(), { on: true }), key);
function run(settings, x, ab = false) {
  const sp = new st.Spatial(RATE, st.params(settings, ab));
  const l = new Float64Array(x.length), r = new Float64Array(x.length);
  sp.process(x, l, r);
  return { l, r, sp };
}
const sine = (f, n, a = 0.3) => Float64Array.from({ length: n }, (_, i) => a * Math.sin(2 * Math.PI * f * i / RATE));
function phase(y, f, from, n) {
  let c = 0, s = 0;
  for (let i = from; i < from + n; i++) { c += y[i] * Math.cos(2 * Math.PI * f * i / RATE); s += y[i] * Math.sin(2 * Math.PI * f * i / RATE); }
  return { ph: Math.atan2(c, s), amp: 2 * Math.hypot(c, s) / n };
}
function voiceNoise(n, seed = 1) {
  // Somme de sinus 300-3 000 Hz à phases pseudo-aléatoires (bruit de la bande de la voix)
  let r = seed; const rnd = () => (r = (r * 16807) % 2147483647) / 2147483647;
  const x = new Float64Array(n);
  for (let f = 300; f <= 3000; f += 37) { const p = 2 * Math.PI * rnd(); for (let i = 0; i < n; i++) x[i] += 0.01 * Math.sin(2 * Math.PI * f * i / RATE + p); }
  return x;
}
const power = (y, from = 4800) => { let p = 0; for (let i = from; i < y.length; i++) p += y[i] * y[i]; return p / (y.length - from); };

test("binaural : 90° ± 2° et amplitudes égales de 300 à 3 000 Hz", () => {
  for (const f of [300, 450, 700, 1000, 1500, 2200, 3000]) {
    const { l, r } = run(on("cw"), sine(f, 24000));
    const a = phase(l, f, 9600, 14400), b = phase(r, f, 9600, 14400);
    let d = Math.abs(a.ph - b.ph) * 180 / Math.PI;
    if (d > 180) d = 360 - d;
    assert.ok(Math.abs(d - 90) <= 2, f + " Hz : " + d.toFixed(2) + "°");
    assert.ok(Math.abs(20 * Math.log10(a.amp / b.amp)) <= 0.5, f + " Hz : amplitudes " + a.amp + " / " + b.amp);
  }
});

test("décorrélation : G + D proportionnel au signal (somme mono sans peigne)", () => {
  const x = voiceNoise(9600);
  for (const width of [0, 40, 70, 150]) {
    const s = Object.assign(on("comfort"), { width });
    const { l, r } = run(s, x);
    const w = width / 100, we = w * (1 - s.presence / 100), g = 1 / Math.sqrt(1 + we * we);
    for (let i = D; i < x.length; i++) assert.ok(Math.abs(l[i] + r[i] - 2 * g * x[i - D]) < 1e-9, "largeur " + width + ", échantillon " + i);
  }
});

test("sonie : écart ≤ 1 dB entre le mono et chaque préréglage", () => {
  const x = voiceNoise(48000), ref = power(x);
  for (const key of Object.keys(st.PRESETS)) {
    const { l, r } = run(on(key), x);
    for (const [side, y] of [["G", l], ["D", r]]) {
      const db = 10 * Math.log10(power(y) / ref);
      assert.ok(Math.abs(db) <= 1, key + " " + side + " : " + db.toFixed(2) + " dB");
    }
  }
});

test("effet réel : corrélation G/D nettement sous 1 avec un préréglage, 1 en mono", () => {
  const x = voiceNoise(48000);
  const corr = (key) => { const { sp } = run(on(key), x); return sp.correlation(); };
  assert.ok(Math.abs(corr("mono") - 1) < 1e-9);
  for (const key of ["comfort", "dx", "cw"]) assert.ok(corr(key) < 0.8, key + " : " + corr(key));
});

test("bypass (ST éteint, Mono, sortie mono, A/B) : G = D = signal retardé du retard commun", () => {
  const x = voiceNoise(4800);
  const cases = [Object.assign(on("cw"), { on: false }), on("mono"), Object.assign(on("dx"), { monoOut: true })];
  for (const s of cases) {
    const { l, r } = run(s, x);
    for (let i = D; i < x.length; i++) { assert.equal(l[i], x[i - D]); assert.equal(r[i], x[i - D]); }
  }
  const { l, r } = run(on("cw"), x, true);
  for (let i = D; i < x.length; i++) { assert.equal(l[i], x[i - D]); assert.equal(r[i], x[i - D]); }
});

test("aucun clic : 100 changements de préréglage et d'A/B enchaînés sur un sinus de 1 kHz", () => {
  const sp = new st.Spatial(RATE, st.params(on("comfort"), false));
  const keys = Object.keys(st.PRESETS), block = 480, x = sine(1000, block * 100, 0.5);
  const l = new Float64Array(x.length), r = new Float64Array(x.length);
  for (let k = 0; k < 100; k++) {
    sp.set(st.params(Object.assign(on(keys[k % keys.length]), { width: (k * 37) % 151 }), k % 7 === 0));
    sp.process(x.subarray(k * block, (k + 1) * block), l.subarray(k * block, (k + 1) * block), r.subarray(k * block, (k + 1) * block));
  }
  const natural = 2 * Math.PI * 1000 / RATE * 0.5;
  for (const y of [l, r]) {
    let worst = 0;
    for (let i = 1; i < y.length; i++) worst = Math.max(worst, Math.abs(y[i] - y[i - 1]));
    assert.ok(worst < 1.6 * natural, "saut " + worst.toFixed(4) + " (sinus seul : " + natural.toFixed(4) + ")");
  }
});

test("limiteur et entrées extrêmes : jamais au-dessus du plafond, jamais NaN", () => {
  const n = 9600, x = new Float64Array(n);
  for (let i = 0; i < n; i++) x[i] = i % 1000 === 3 ? NaN : i % 1000 === 7 ? Infinity : i % 997 === 0 ? 1e30 : 4 * Math.sin(i / 7);
  for (const key of Object.keys(st.PRESETS)) {
    const { l, r } = run(Object.assign(on(key), { width: 150, balance: 30 }), x);
    for (let i = 0; i < n; i++) {
      assert.ok(Number.isFinite(l[i]) && Number.isFinite(r[i]), key + " " + i);
      assert.ok(Math.abs(l[i]) <= st.CEILING + 1e-12 && Math.abs(r[i]) <= st.CEILING + 1e-12, key + " " + i);
    }
  }
});

test("latence ajoutée ≤ 10 ms", () => {
  assert.ok(D / RATE <= 0.010, (1000 * D / RATE).toFixed(2) + " ms");
});

test("réglages : bornes, préréglage inconnu, choix d'un préréglage, « (modifié) »", () => {
  assert.deepEqual(st.validate(null), st.defaults());
  const v = st.validate({ on: true, preset: "cw", width: 999, presence: -5, balance: 300, monoOut: "oui" });
  assert.deepEqual(v, { on: true, preset: "cw", width: 150, presence: 0, balance: 100, monoOut: false });
  assert.equal(st.validate({ preset: "inconnu" }).preset, "comfort");
  const s = st.choose(v, "dx");
  assert.equal(s.width, 80); assert.equal(s.presence, 25); assert.equal(s.balance, 100);
  assert.equal(st.label(s), "DX BLU");
  assert.equal(st.label(Object.assign({}, s, { width: 81 })), "DX BLU (modifié)");
  assert.equal(st.isModified(st.choose(v, "mono")), false);
});

test("préréglages et réponses de référence partagés avec l'application (spatial_presets.json)", () => {
  const now = st.sharedTable();
  if (process.env.TRX_WRITE_SHARED) fs.writeFileSync(SHARED, JSON.stringify(now, null, 1) + "\n", "utf-8");
  const file = JSON.parse(fs.readFileSync(SHARED, "utf-8"));
  assert.deepEqual(file.presets, now.presets);
  for (const key of Object.keys(now.impulse)) for (const side of ["left", "right"]) {
    file.impulse[key][side].forEach((v, i) => assert.ok(Math.abs(v - now.impulse[key][side][i]) < 1e-6, key + " " + side + " " + i));
  }
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n     " + (e && e.message)); }
}
if (failed) { console.log(failed + " échec(s)"); process.exit(1); }
