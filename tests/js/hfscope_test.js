// Tests de la vue du spectre HF (calculs purs) : `node tests/js/hfscope_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const hf = require(path.join(__dirname, "../../trxstation/gateway/api/static/hfscope.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("cycle de la zone : puissance -> audio -> HF (seulement s'il est disponible) -> puissance", () => {
  assert.equal(hf.nextView("tx", true), "audio");
  assert.equal(hf.nextView("audio", true), "hf");
  assert.equal(hf.nextView("audio", false), "tx");
  assert.equal(hf.nextView("hf", true), "tx");
});

test("disponibilité : annoncé par la station ET reçu en ce moment", () => {
  const hello = { spectrum: { level_max: 160 } };
  assert.equal(hf.available(hello, { spectrum: { state: "ok" } }), true);
  assert.equal(hf.available(hello, { spectrum: { state: "error" } }), false);      // mode normal
  assert.equal(hf.available({ spectrum: null }, { spectrum: { state: "ok" } }), false);
  assert.equal(hf.available(null, null), false);
});

test("niveaux : 0..level_max, gain en dB (2 niveaux par dB), bornés", () => {
  assert.equal(hf.levelT(80, 160, 0), 0.5);
  assert.equal(hf.levelT(80, 160, 6), 92 / 160);
  assert.equal(hf.levelT(200, 160, 0), 1); assert.equal(hf.levelT(-5, 160, 0), 0); assert.equal(hf.levelT(NaN, 160, 0), 0);
});

test("graduations rondes en MHz entre les bords", () => {
  const ticks = hf.scopeTicks(14_000_000, 14_200_000);               // 200 kHz : pas de 25 kHz
  assert.equal(ticks[0].label, "14.000"); assert.equal(ticks.at(-1).label, "14.200");
  assert.equal(ticks.length, 9); assert.equal(ticks[4].fraction, 0.5);
  const narrow = hf.scopeTicks(7_074_000 - 2_500, 7_074_000 + 2_500, 6);   // 5 kHz : pas de 1 kHz
  assert.deepEqual(narrow.map((t) => t.label), ["7.072", "7.073", "7.074", "7.075", "7.076"]);
  assert.equal(hf.mhzLabel(14_052_500, 2500), "14.0525");
  assert.deepEqual(hf.scopeTicks(10, 10), []);
});

test("repère de la fréquence du poste, null hors de l'écran", () => {
  assert.equal(hf.markerFraction(14_100_000, 14_000_000, 14_200_000), 0.5);
  assert.equal(hf.markerFraction(13_000_000, 14_000_000, 14_200_000), null);
  assert.equal(hf.markerFraction(null, 14_000_000, 14_200_000), null);
});

test("même échelle : l'historique du waterfall n'est gardé que si les bords et la taille sont identiques", () => {
  const a = { lowHz: 1, highHz: 2, points: new Uint8Array(475) };
  assert.equal(hf.sameScale(a, { lowHz: 1, highHz: 2, points: new Uint8Array(475) }), true);
  assert.equal(hf.sameScale(a, { lowHz: 1, highHz: 3, points: new Uint8Array(475) }), false);
  assert.equal(hf.sameScale(null, a), false);
  assert.equal(hf.spanLabel(14_000_000, 14_200_000), "200 kHz"); assert.equal(hf.spanLabel(7_071_500, 7_076_500), "5 kHz");
});

test("réglages mémorisés : gain et plage de listes fermées", () => {
  assert.deepEqual(hf.normalizeSettings({ gain: 6, range: 30 }), { gain: 6, range: 30 });
  assert.deepEqual(hf.normalizeSettings({ gain: 7, range: 33 }), { gain: 0, range: 40 });
  assert.deepEqual(hf.normalizeSettings("n'importe quoi"), { gain: 0, range: 40 });
  assert.equal(hf.nextGain(18), -12); assert.equal(hf.gainLabel(6), "GAIN +6");
  assert.equal(hf.nextRange(20), 80); assert.equal(hf.nextRange(80), 60); assert.equal(hf.rangeLabel(40), "PLAGE 40 dB");
});

test("contraste : pleine échelle, ou fenêtre posée sur le plancher de bruit (médiane, lissée)", () => {
  const noise = new Uint8Array(475).fill(30); noise[100] = 120;                     // bruit à 30, un signal fort
  assert.equal(hf.noiseFloor(noise), 30); assert.equal(hf.noiseFloor([]), 0);
  assert.deepEqual(hf.colorWindow(noise, 160, 80), { bottom: 0, span: 160, floor: null });
  const win = hf.colorWindow(noise, 160, 40);
  assert.deepEqual(win, { bottom: 26, span: 80, floor: 30 });                       // 2 dB sous le bruit, 40 dB de plage
  assert.equal(hf.windowT(26, win, 0), 0); assert.equal(hf.windowT(106, win, 0), 1); assert.equal(hf.windowT(66, win, 0), 0.5);
  assert.equal(hf.windowT(66, win, 6), 0.65);                                       // le gain éclaircit
  const later = hf.colorWindow(new Uint8Array(475).fill(80), 160, 40, win.floor);   // bruit qui monte d'un coup : plancher lissé
  assert.equal(later.floor, 40);
  assert.equal(hf.colorWindow(new Uint8Array(475).fill(155), 160, 20).bottom, 120); // jamais au-delà du haut de l'échelle
});

test("rendu à la résolution de l'écran : interpolation sans marches, tailles en pixels réels", () => {
  const row = hf.interpolateRow([0, 100, 0], 5);
  assert.deepEqual(Array.from(row), [0, 50, 100, 50, 0]);
  assert.equal(hf.interpolateRow(new Uint8Array(475).fill(7), 2400).length, 2400);
  assert.deepEqual(Array.from(hf.interpolateRow([42], 3)), [42, 42, 42]);
  assert.deepEqual(hf.canvasSize(800, 300, 3, 475, 120), { width: 2400, height: 900 });
  assert.deepEqual(hf.canvasSize(0, 0, 0, 475, 120), { width: 475, height: 120 });     // élément pas encore affiché : repli
  assert.deepEqual(hf.canvasSize(3000, 2000, 3, 1, 1), { width: 4096, height: 4096 }); // borné
  assert.equal(hf.lineHeight(1), 2); assert.equal(hf.lineHeight(2.75), 6); assert.equal(hf.lineHeight(undefined), 2);
});

test("réglages du poste : libellés, cycles et pas du niveau de référence (grille 0,5 dB, ±20 dB)", () => {
  assert.equal(hf.modeSettingLabel("center"), "CENT"); assert.equal(hf.modeSettingLabel("scroll_center"), "SCR-C");
  assert.equal(hf.nextMode("center"), "fixed"); assert.equal(hf.nextMode("scroll_fixed"), "center");
  assert.equal(hf.spanSettingLabel(500000), "±500k"); assert.equal(hf.spanSettingLabel(2500), "±2,5k"); assert.equal(hf.spanSettingLabel(undefined), "SPAN ?");
  assert.equal(hf.nextSpan(500000), 2500); assert.equal(hf.nextSpan(100000), 250000); assert.equal(hf.nextSpan(7), 2500);
  assert.equal(hf.nextSpeed("slow"), "fast"); assert.equal(hf.speedSettingLabel("mid"), "VIT MOY");
  assert.equal(hf.refLabel(-14.5), "REF -14,5"); assert.equal(hf.refLabel(20), "REF +20,0"); assert.equal(hf.refLabel(null), "REF ?");
  assert.equal(hf.stepRef(-14.5, 1), -13.5); assert.equal(hf.stepRef(19.5, 1), 20); assert.equal(hf.stepRef(-20, -1), -20);
  assert.equal(hf.stepRef(0.3, 1), 1.5); assert.equal(hf.stepRef(undefined, 1), null);
  assert.deepEqual(hf.SPANS_HZ, [2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000]);
});

test("accord au doigt : pas selon la largeur, sens d'un VFO", () => {
  assert.equal(hf.tuneStep(5000), 10); assert.equal(hf.tuneStep(200000), 500); assert.equal(hf.tuneStep(1000000), 1000);
  assert.equal(hf.dragSteps(-95, 475, 200000, 500), 80);                   // spectre tiré à gauche : fréquence qui monte
  assert.equal(hf.dragSteps(95, 475, 200000, 500), -80);
  assert.equal(hf.dragSteps(1, 475, 5000, 10), -1);
  assert.equal(hf.dragSteps(50, 0, 200000, 500), 0); assert.equal(hf.dragSteps(NaN, 475, 200000, 500), 0);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + err.stack); }
  }
  console.log(`${tests.length - failed}/${tests.length} tests du spectre HF réussis`);
  process.exit(failed ? 1 : 0);
})();
