// Tests du calcul du waterfall (waterfall.js) : `node tests/js/waterfall_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const wf = require(path.join(__dirname, "../../trxstation/gateway/api/static/waterfall.js"));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const SR = 48000, FFT = 4096, BIN = SR / FFT;

function spectrum(peaks, floor) {                       // spectre synthétique : un fond plat et des raies { hz, db }
  const out = new Float32Array(FFT / 2).fill(floor === undefined ? -100 : floor);
  for (const { hz, db } of peaks) out[Math.round(hz / BIN)] = db;
  return out;
}
const argmax = (values) => values.indexOf(Math.max(...values));

test("boutons : chaque appui passe à la valeur suivante puis reboucle", () => {
  assert.deepEqual(wf.SPEEDS, [3, 6, 12, 25, 50]); assert.deepEqual(wf.WIDTHS, [5000, 3000, 2500, 2000, 1000]);
  for (const [list, name] of [[wf.SPEEDS, "speed"], [wf.WIDTHS, "width"], [wf.GAINS, "gain"], [wf.PEAK_TIMES, "peak"]]) {
    let s = Object.assign({}, wf.DEFAULTS), seen = [];
    for (let i = 0; i < list.length; i++) { s = wf.nextSetting(s, name); seen.push(s[name]); }
    assert.equal(new Set(seen).size, list.length, name);                          // toutes les valeurs sont visitées
    assert.equal(s[name], wf.DEFAULTS[name], name);                                // et on revient au point de départ
  }
  assert.equal(wf.cycle([1, 2, 3], 9), 1);                                         // valeur inconnue : retour au début
  assert.deepEqual(wf.nextSetting(wf.DEFAULTS, "inconnu"), wf.DEFAULTS);
  assert.equal(wf.nextSetting(wf.DEFAULTS, "speed").gain, wf.DEFAULTS.gain);       // un bouton ne touche qu'à son réglage
});

test("étiquettes des boutons", () => {
  assert.equal(wf.speedLabel(12), "VIT 12"); assert.equal(wf.widthLabel(5000), "LARG 5k"); assert.equal(wf.widthLabel(2500), "LARG 2.5k");
  assert.equal(wf.gainLabel(6), "GAIN +6"); assert.equal(wf.gainLabel(0), "GAIN 0"); assert.equal(wf.gainLabel(-12), "GAIN -12");
  assert.equal(wf.peakLabel(0), "PIC OFF"); assert.equal(wf.peakLabel(0.5), "PIC 0.5s"); assert.equal(wf.peakLabel(2), "PIC 2s"); assert.equal(wf.peakLabel(Infinity), "PIC MAX");
});

test("palette : gris sombre, gris-bleu, bleu, bleu clair, blanc ; toujours plus clair quand le signal monte", () => {
  const dark = wf.paletteRGB(0), white = wf.paletteRGB(1), mid = wf.paletteRGB(0.5);
  assert.ok(dark[0] < 20 && dark[1] < 20 && dark[2] < 30);                         // presque noir
  assert.deepEqual(white, [255, 255, 255]);
  assert.ok(mid[2] > mid[0] + 40, "bleu au milieu");
  const gray = wf.paletteRGB(0.2); assert.ok(Math.abs(gray[0] - gray[1]) < 12 && gray[2] > gray[0], "gris légèrement bleuté");
  let last = -1;
  for (let i = 0; i <= 100; i++) {
    const [r, g, b] = wf.paletteRGB(i / 100), lum = 0.3 * r + 0.59 * g + 0.11 * b;
    assert.ok(lum >= last - 1e-9, "luminosité croissante à " + i); last = lum;
  }
  assert.deepEqual(wf.paletteRGB(-3), dark); assert.deepEqual(wf.paletteRGB(9), white); assert.deepEqual(wf.paletteRGB(NaN), dark);
  assert.equal(wf.LUT.length, 768); assert.deepEqual([wf.LUT[0], wf.LUT[1], wf.LUT[2]], dark); assert.deepEqual([wf.LUT[765], wf.LUT[766], wf.LUT[767]], white);
});

test("niveau -> couleur : le gain décale la fenêtre de sensibilité", () => {
  assert.equal(wf.levelToT(-85, 0), 0); assert.ok(Math.abs(wf.levelToT(-30, 0) - 1) < 1e-9); assert.ok(Math.abs(wf.levelToT(-57.5, 0) - 0.5) < 1e-9);
  assert.equal(wf.levelToT(-200, 0), 0); assert.equal(wf.levelToT(0, 0), 1); assert.equal(wf.levelToT(-Infinity, 0), 0); assert.equal(wf.levelToT(NaN, 0), 0);
  assert.ok(wf.levelToT(-80, 12) > wf.levelToT(-80, 0) && wf.levelToT(-80, 0) > wf.levelToT(-80, -12));          // plus de gain = plus de couleur
  assert.ok(Math.abs(wf.levelToT(-91, 6) - 0) < 1e-9);
});

test("spectre -> pixels : la raie apparaît à la bonne fréquence, sur chaque largeur de bande", () => {
  for (const span of wf.WIDTHS) {
    for (const hz of [300, 700, 1000, 1500, 2400].filter((f) => f < span)) {
      const px = wf.resample(spectrum([{ hz, db: -20 }]), SR, FFT, span, 500);
      const exact = Math.round(hz / BIN) * BIN;                                                                                  // la raie FFT tombe sur un multiple de la largeur de raie
      const at = argmax(px), expected = (exact / span) * 500;
      assert.ok(Math.abs(at + 0.5 - expected) <= 1.2, `raie ${hz} Hz (${exact.toFixed(1)}), bande ${span} : pixel ${at} au lieu de ${expected.toFixed(1)}`);   // à ± 1 pixel
      assert.ok(Math.abs(px[at] - (-20)) < 1e-6 || px[at] > -45, "une raie fine garde son niveau, elle n'est pas diluée par l'interpolation");
      const lit = Array.from(px).map((v, i) => [v, i]).filter(([v]) => v > -60).map(([, i]) => (i + 0.5) / 500 * span);
      assert.ok(lit.length && lit.every((f) => Math.abs(f - exact) <= 2.2 * span / 500 + BIN), `raie ${hz} Hz : pixels allumés ${lit.map((f) => f.toFixed(0))}`);
    }
  }
  const coarse = wf.resample(spectrum([{ hz: 1000, db: -20 }]), SR, FFT, 5000, 60);              // beaucoup de raies par pixel : la raie fine est conservée
  assert.ok(Math.max(...coarse) > -25);
  const flat = wf.resample(new Float32Array(FFT / 2).fill(-70), SR, FFT, 2000, 300);
  assert.ok(flat.every((v) => Math.abs(v + 70) < 1e-4));                                          // un fond plat reste plat
  const lone = wf.resample(spectrum([{ hz: 1500, db: -20 }]), SR, FFT, 5000, 500);                                                // la raie la plus forte est restituée à son niveau exact
  assert.equal(Math.max(...lone), -20);
  const holes = wf.resample(Float32Array.from([-Infinity, NaN, -50, undefined]), SR, FFT, 5000, 40);
  assert.ok(holes.every((v) => Number.isFinite(v)));                                              // -Infinity, NaN : jamais propagés
  const short = wf.resample(new Float32Array(10).fill(-60), SR, FFT, 5000, 50);                   // tableau trop court : pas d'exception
  assert.equal(short.length, 50);
  const reuse = new Float32Array(500); assert.equal(wf.resample(spectrum([]), SR, FFT, 5000, 500, reuse), reuse);
});

test("ligne de pixels : RGBA complet, couleur selon le niveau", () => {
  const row = wf.fillRow(new Uint8ClampedArray(4 * 3), Float32Array.from([-120, -57.5, -10]), 0);
  assert.deepEqual([row[3], row[7], row[11]], [255, 255, 255]);
  assert.ok(row[0] < 20 && row[2] < 30);                                                          // silence : sombre
  assert.deepEqual([row[8], row[9], row[10]], [255, 255, 255]);                                   // signal fort : blanc
  assert.ok(row[6] > row[4] + 40);                                                                // niveau moyen : bleu
  const boosted = wf.fillRow(new Uint8ClampedArray(4), Float32Array.from([-70]), 18);
  const plain = wf.fillRow(new Uint8ClampedArray(4), Float32Array.from([-70]), 0);
  assert.ok(boosted[0] + boosted[1] + boosted[2] > plain[0] + plain[1] + plain[2]);
});

test("pics : maintien, décroissance selon la constante de temps, remise à zéro", () => {
  const t = new wf.PeakTracker();
  const loud = Float32Array.from([-30, -90, -90]), quiet = Float32Array.from([-90, -90, -90]);
  assert.equal(t.update(loud, 0.1, 0), null);                                                     // pics désactivés
  assert.deepEqual(Array.from(t.update(loud, 0.1, 2)), [-30, -90, -90]);
  const decayed = t.update(quiet, 1, 2);                                                          // 1 s avec tau = 2 s : -27,5 dB
  assert.ok(Math.abs(decayed[0] - (-30 - 27.5)) < 1e-4, String(decayed[0]));
  assert.ok(decayed[1] === -90 && decayed[2] === -90);                                            // jamais sous le signal courant
  const fast = new wf.PeakTracker(); fast.update(loud, 0.1, 0.5);
  const slow = new wf.PeakTracker(); slow.update(loud, 0.1, 5);
  assert.ok(fast.update(quiet, 0.2, 0.5)[0] < slow.update(quiet, 0.2, 5)[0]);                    // petite constante de temps = décroissance plus rapide
  const hold = new wf.PeakTracker(); hold.update(loud, 0.1, Infinity);
  for (let i = 0; i < 100; i++) hold.update(quiet, 1, Infinity);
  assert.equal(hold.peaks[0], -30);                                                               // maintien : ne décroît jamais
  assert.equal(hold.update(Float32Array.from([-10, -90, -90]), 1, Infinity)[0], -10);              // mais monte si le signal dépasse
  hold.reset(); assert.equal(hold.peaks, null);
  const resized = new wf.PeakTracker(); resized.update(loud, 0.1, 2);
  assert.equal(resized.update(new Float32Array(5).fill(-80), 0.1, 2).length, 5);                  // largeur changée : on repart de zéro
  const zero = new wf.PeakTracker(); zero.update(loud, 0, 2);
  assert.equal(zero.update(quiet, 0, 2)[0], -30);                                                 // pas de temps écoulé : pas de décroissance
});

test("raie la plus forte : fréquence en Hz, rien si tout est sous le seuil", () => {
  const px = wf.resample(spectrum([{ hz: 1500, db: -25 }, { hz: 700, db: -45 }]), SR, FFT, 5000, 500);
  const s = wf.strongest(px, 5000);
  assert.ok(Math.abs(s.hz - 1500) <= 12 && s.db > -30, "fréquence annoncée : " + s.hz);                                   // à moins d'un pixel (10 Hz) de la vraie raie
  assert.equal(wf.strongest(wf.resample(spectrum([]), SR, FFT, 5000, 500), 5000), null);
  assert.equal(wf.strongest(new Float32Array(0), 5000), null); assert.equal(wf.strongest(Float32Array.from([-70]), 5000, -80).hz, 2500);
});

test("graduations : une tous les 500 Hz, en kHz sans unité", () => {
  const t5 = wf.axisTicks(5000);
  assert.deepEqual(t5.map((x) => x.label), ["0", "0.5", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5"]);
  assert.deepEqual(t5.map((x) => x.hz), [0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000]);
  assert.equal(t5[0].fraction, 0); assert.equal(t5.at(-1).fraction, 1); assert.equal(t5[2].fraction, 0.2);
  assert.deepEqual(wf.axisTicks(2500).map((x) => x.label), ["0", "0.5", "1", "1.5", "2", "2.5"]);
  assert.deepEqual(wf.axisTicks(1000).map((x) => x.label), ["0", "0.5", "1"]);
  assert.ok(wf.axisTicks(3000).every((x) => !/[a-zA-Z]/.test(x.label)));                           // aucune unité
  for (const span of wf.WIDTHS) assert.equal(wf.axisTicks(span).at(-1).hz, span);                  // la dernière graduation est le bord de la bande
});

test("réglages mémorisés : valeurs inconnues écartées, maintien conservé", () => {
  assert.deepEqual(wf.normalizeSettings(undefined), wf.DEFAULTS); assert.deepEqual(wf.normalizeSettings("x"), wf.DEFAULTS); assert.deepEqual(wf.normalizeSettings(null), wf.DEFAULTS);
  assert.deepEqual(wf.normalizeSettings({ speed: 7, width: 1234, gain: 99, peak: 42 }), wf.DEFAULTS);
  assert.deepEqual(wf.normalizeSettings({ speed: 25, width: 2000, gain: -6, peak: 1 }), { speed: 25, width: 2000, gain: -6, peak: 0.5 });
  for (const s of [{ speed: 50, width: 1000, gain: 18, peak: Infinity }, { speed: 3, width: 3000, gain: -12, peak: 0 }, wf.DEFAULTS]) {
    const text = wf.serializeSettings(s);
    assert.ok(!text.includes("Infinity") && !text.includes("null"), text);                          // JSON valide (Infinity n'existe pas en JSON)
    assert.deepEqual(wf.normalizeSettings(JSON.parse(text)), s);
  }
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du waterfall réussis");
process.exit(failed ? 1 : 0);
