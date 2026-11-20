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

test("bridage, balance et séparation gauche / droite", () => {
  assert.strictEqual(sdr.loadText({ load: 0 }), "");
  assert.ok(sdr.loadText({ load: 2, load_reason: "station chargée : processeur à 95 %" }).includes("waterfall ralenti"));
  assert.ok(sdr.stateText({ state: "suspended", load_reason: "station chargée : passerelle en retard" }).includes("SUSPENDU"));
  assert.deepStrictEqual(sdr.balanceGains(0), { trx: 1, sdr: 1 });
  assert.deepStrictEqual(sdr.balanceGains(50), { trx: 0.5, sdr: 1 });
  assert.deepStrictEqual(sdr.balanceGains(-100), { trx: 1, sdr: 0 });
  assert.deepStrictEqual(sdr.balanceGains(500), { trx: 0, sdr: 1 });
  assert.strictEqual(sdr.splitPans(0), null);
  assert.deepStrictEqual(sdr.splitPans(1), { trx: -1, sdr: 1 });
  assert.deepStrictEqual(sdr.splitPans(2), { trx: 1, sdr: -1 });
  assert.ok(sdr.stateText({ state: "running", serial: "X", center: 7e6, fs: 2e6, cpu_total: 40.5, mem_mb: 61.2 }).includes("61 Mo"));
});

test("fenêtre affichée et en-tête : zoom décalé, fréquence écoutée", () => {
  // essai du 2026-11-20 : récepteur à 6,650 MHz, zoom ×8 décalé de 380 kHz, écoute à 7,050 MHz
  const st = { state: "running", serial: "X", center: 6650000, fs: 2000000, zoom: 8, zoom_off: 380000, dfreq: 7050000 };
  assert.deepStrictEqual(sdr.viewWindow(st), { center: 7030000, span: 250000 });
  assert.ok(sdr.stateText(st).includes("affiché 6.905 à 7.155 MHz"), sdr.stateText(st));
  assert.strictEqual(sdr.badgeText(st), "7.0500 MHz");
  const plain = { state: "running", center: 6650000, fs: 2000000, zoom: 1, zoom_off: 380000 };
  assert.deepStrictEqual(sdr.viewWindow(plain), { center: 6650000, span: 2000000 });
  assert.ok(!sdr.stateText(plain).includes("affiché"));
  assert.strictEqual(sdr.badgeText(plain), "6.650 MHz");
  assert.strictEqual(sdr.badgeText({ state: "error" }), "");
});

test("graduations plus nombreuses et décimales suivant le pas", () => {
  const marks = sdr.ticks(7093000, 1536000, 15);
  assert.ok(marks.length >= 10, "au moins dix graduations sur 1,5 MHz");
  assert.strictEqual(marks[1] - marks[0], 100000);
  assert.strictEqual(sdr.tickDigits(marks), 1);
  assert.strictEqual(sdr.tickDigits([7000000, 7050000]), 2);
  assert.strictEqual(sdr.tickDigits([7000000, 7010000]), 2);
  assert.strictEqual(sdr.tickDigits([7000000, 7002000]), 3);
  assert.strictEqual(sdr.tickDigits([7000000]), 3);
});

test("grand écran : pas de 50 kHz sur 1,5 MHz", () => {
  const marks = sdr.ticks(7093000, 1536000, 30);
  assert.strictEqual(marks[1] - marks[0], 50000);
  assert.strictEqual(sdr.tickDigits(marks), 2);
  assert.ok(marks.length >= 25);
});

test("zoom du waterfall : échelle, déplacement, libellé, limites (étape 203)", () => {
  assert.equal(sdr.zoomStep(1, 1), 2); assert.equal(sdr.zoomStep(16, 1), null);
  assert.equal(sdr.zoomStep(1, -1), null); assert.equal(sdr.zoomStep(8, -1), 4);
  assert.equal(sdr.zoomStep(undefined, 1), 2);                             // station sans zoom annoncé : départ à ×1
  assert.deepEqual(sdr.panArgs({ zoom: 4, zoom_off: 100000, fs: 2000000 }, 1), { zoom_off: 350000 });
  assert.deepEqual(sdr.panArgs({ zoom: 4, zoom_off: 0, fs: 2000000 }, -1), { zoom_off: -250000 });
  assert.equal(sdr.panArgs({ zoom: 1, zoom_off: 0, fs: 2000000 }, 1), null);
  assert.equal(sdr.zoomLabel({ zoom: 4, fs: 2000000 }), "×4 · 500 kHz");
  assert.equal(sdr.checkSettings({ zoom: 8 }), "");
  assert.equal(sdr.checkSettings({ zoom_off: -250000 }), "");
  assert.notEqual(sdr.checkSettings({ zoom: 3 }), "");
  assert.notEqual(sdr.checkSettings({ zoom_off: 0.5 }), "");
  // le centre ne bouge que hors de la largeur ENTIÈRE du SDR (ui.js passe st.center et st.fs, pas la fenêtre zoomée)
  assert.deepEqual(sdr.tuneArgs(7400000, 7100000, 2000000), { dfreq_hz: 7400000 });
});

test("palettes, largeur et antenne du SDR (étape 204)", () => {
  assert.equal(sdr.paletteLut("theme"), null);                            // couleurs du thème de la page
  assert.equal(sdr.paletteLut("inconnue"), null);
  for (const [name] of sdr.PALETTES.slice(1)) {
    const lut = sdr.paletteLut(name);
    assert.equal(lut.length, 768);
    assert.deepEqual(Array.from(lut.slice(0, 3)), [0, 0, 0]);             // plancher noir partout
  }
  assert.deepEqual(Array.from(sdr.paletteLut("gris").slice(765)), [255, 255, 255]);
  assert.equal(sdr.nextPalette("theme"), "classique");
  assert.equal(sdr.nextPalette(sdr.PALETTES[sdr.PALETTES.length - 1][0]), "theme");
  assert.equal(sdr.paletteName("chaud"), "Chaud"); assert.equal(sdr.paletteName("?"), "Thème");
  assert.equal(sdr.rateLabel(2000000), "2 MHz"); assert.equal(sdr.rateLabel(2048000), "2,048 MHz");
  assert.equal(sdr.checkSettings({ fs: 2000000, ant: "B" }), "");
  assert.notEqual(sdr.checkSettings({ ant: "C" }), "");
  assert.notEqual(sdr.checkSettings({ fs: -5 }), "");
});

test("spot du Cluster écouté par le SDR (étape 205)", () => {
  assert.deepEqual(sdr.spotListen({ hz: 7150000, qsyMode: "LSB" }, 7100000, 2000000), { dfreq_hz: 7150000, mode: "LSB" });
  assert.deepEqual(sdr.spotListen({ hz: 7074000, qsyMode: "PKTUSB" }, 7100000, 2000000), { dfreq_hz: 7074000, mode: "USB" });
  assert.deepEqual(sdr.spotListen({ hz: 145500000, qsyMode: "FM" }, 145000000, 2000000), { dfreq_hz: 145500000, mode: "NFM" });
  assert.deepEqual(sdr.spotListen({ hz: 14025000, qsyMode: "" }, 7100000, 2000000), { center_hz: 14025000, dfreq_hz: 14025000 });
  assert.equal(sdr.spotListen(null, 7100000, 2000000), null);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du module SDR (page) réussis");
process.exit(failed ? 1 : 0);
