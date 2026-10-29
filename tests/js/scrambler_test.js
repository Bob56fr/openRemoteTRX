// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Tests du scrambler à bandes inversées / permutées (scrambler.js) : `node tests/js/scrambler_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const sc = require(path.join(__dirname, "../../trxstation/gateway/api/static/scrambler.js"));
const shared = JSON.parse(fs.readFileSync(path.join(__dirname, "../protocol/scrambler_modes.json"), "utf-8"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

const RATE = 48000, N = 96000, TONES = [500, 1100, 1900, 2600];
const voice = () => {
  const x = new Float64Array(N);
  for (let i = 0; i < N; i++) for (const f of TONES) x[i] += 0.2 * Math.sin(2 * Math.PI * f * i / RATE + f);
  return x;
};

function toneRatioDb(y) {
  /* Énergie aux fréquences d'origine (±25 Hz) / énergie ailleurs dans 300-3 000 Hz, sur un passage stable. */
  const n = 16384, re = new Float64Array(n), im = new Float64Array(n);
  for (let i = 0; i < n; i++) re[i] = y[60000 + i] * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / n));
  sc.fft(re, im, false);
  let tone = 0, rest = 0;
  for (let k = 0; k < n / 2; k++) {
    const f = k * RATE / n, p = re[k] * re[k] + im[k] * im[k];
    if (f < 300 || f > 3000) continue;
    if (TONES.some((t) => Math.abs(f - t) < 25)) tone += p; else rest += p;
  }
  return 10 * Math.log10(tone / rest);
}

function through(mode, x, { delay = 0, channelHz = 0, fixHz = 0, block = 128 } = {}) {
  const tx = new sc.Scrambler(RATE, "tx"); tx.set(mode, 0);
  const a = new Float64Array(N); tx.process(x, a);
  const ch = new sc.Shifter(RATE); ch.hz = channelHz;
  const b = new Float64Array(N);
  for (let i = 0; i + delay < N; i++) b[i + delay] = ch.run(a[i]);
  const rx = new sc.Scrambler(RATE, "rx"); rx.set(mode, fixHz);
  const y = new Float64Array(N);
  for (let i = 0; i < N; i += block) rx.process(b.subarray(i, i + block), y.subarray(i, i + block), Math.min(block, N - i));
  return { scrambled: a, back: y };
}

test("bandes sur des bins pairs : chaque déplacement est pair (indépendant du découpage en trames)", () => {
  for (const key of Object.keys(sc.MODES)) for (const dir of ["tx", "rx"]) {
    const { dest, conj } = sc.binMap(key, dir, RATE, sc.FRAME);
    dest.forEach((d, k) => {
      if (d < 0) return;
      assert.equal(Math.abs(conj[k] ? d + k : d - k) % 2, 0, key + " " + dir + " bin " + k);
      assert.ok(d * RATE / sc.FRAME >= 290 && d * RATE / sc.FRAME <= 3000, "hors de 300-3 000 Hz");
    });
  }
});

test("mêmes correspondances que le fichier partagé avec l'application (tests/protocol/scrambler_modes.json)", () => {
  assert.equal(shared.frame, sc.FRAME);
  assert.deepEqual(Object.keys(shared.modes), Object.keys(sc.MODES));
  for (const [key, m] of Object.entries(shared.modes)) {
    assert.equal(m.label, sc.MODES[key].label);
    assert.deepEqual(m.bands, sc.bands(m.perm.length, RATE, sc.FRAME));
    for (const dir of ["tx", "rx"]) {
      const { dest, conj } = sc.binMap(key, dir, RATE, sc.FRAME);
      const pairs = []; dest.forEach((d, k) => { if (d >= 0) pairs.push([k, d, conj[k]]); });
      assert.deepEqual(pairs, m[dir], key + " " + dir);
    }
  }
});

test("brouillé : plus rien aux fréquences d'origine ; débrouillé : la voix revient, quel que soit le décalage temporel", () => {
  const x = voice();
  assert.ok(toneRatioDb(x) > 55);
  for (const key of Object.keys(sc.MODES)) for (const delay of [0, 333, 777]) {
    const { scrambled, back } = through(key, x, { delay });
    assert.ok(toneRatioDb(scrambled) < 0, key + " brouillé " + toneRatioDb(scrambled));
    assert.ok(toneRatioDb(back) > 30, key + " décalé de " + delay + " : " + toneRatioDb(back));
  }
});

test("BLU mal accordée de 40 Hz : brouillée sans correction, rétablie par le décalage fin", () => {
  const x = voice();
  assert.ok(toneRatioDb(through("inv3", x, { channelHz: 40 }).back) < 0);
  assert.ok(toneRatioDb(through("inv3", x, { channelHz: 40, fixHz: -40 }).back) > 20);
});

test("éteint (mode nul) : transparent ; réglages relus : jamais réactivé seul, bornes respectées", () => {
  const s = new sc.Scrambler(RATE, "tx"); s.set(null, 0);
  const x = Float64Array.from([0.1, -0.2, 0.3]), y = new Float64Array(3);
  s.process(x, y);
  assert.deepEqual(Array.from(y), Array.from(x));
  assert.deepEqual(sc.validate({ tx: true, rx: true, mode: "mix4", offsetHz: 999 }), { tx: false, rx: false, mode: "mix4", offsetHz: 300 });
  assert.deepEqual(sc.validate({ mode: "inconnu" }), sc.defaults());
  assert.throws(() => sc.binMap("inconnu", "tx", RATE, sc.FRAME));
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du scrambler réussis");
process.exit(failed ? 1 : 0);
