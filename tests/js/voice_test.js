// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Tests de l'égaliseur et des effets de voix (voice.js) avec un faux AudioContext : `node tests/js/voice_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const vx = require(path.join(__dirname, "../../trxstation/gateway/api/static/voice.js"));
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, "../protocol/voice_vectors.json"), "utf-8"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

// ---- faux WebAudio : chaque nœud garde ses branchements et ses paramètres
class Param { constructor(v) { this.value = v; } }
class Node {
  constructor(ctx, kind) { this.ctx = ctx; this.kind = kind; this.out = new Set(); ctx.nodes.push(this); }
  connect(target) { this.out.add(target); return target; }
  disconnect(target) { if (target) this.out.delete(target); else this.out.clear(); }
}
class FakeCtx {
  constructor() { this.nodes = []; this.sampleRate = 48000; this.destination = new Node(this, "speaker"); this.failOn = null; }
  _make(kind, extra) {
    if (this.failOn === kind) throw new Error("nœud " + kind + " indisponible");
    return Object.assign(new Node(this, kind), extra || {});
  }
  createGain() { return this._make("gain", { gain: new Param(1) }); }
  createBiquadFilter() { return this._make("biquad", { type: "lowpass", frequency: new Param(350), Q: new Param(1), gain: new Param(0) }); }
  createDelay() { return this._make("delay", { delayTime: new Param(0) }); }
  createOscillator() { return this._make("osc", { frequency: new Param(440), start() { this.started = true; }, stop() { this.stopped = true; } }); }
  createConvolver() { return this._make("convolver", { buffer: null }); }
  createDynamicsCompressor() {
    return this._make("compressor", { threshold: new Param(-24), knee: new Param(30), ratio: new Param(12), attack: new Param(0.003), release: new Param(0.25) });
  }
  createWaveShaper() { return this._make("shaper", { curve: null }); }
  createAnalyser() {
    const ctx = this;
    return this._make("analyser", { fftSize: 2048, getFloatTimeDomainData(buf) { buf.fill(ctx.micLevel || 0); } });
  }
  createMediaStreamDestination() {
    const track = { kind: "audio", enabled: true };
    return this._make("dest", { stream: { getAudioTracks: () => [track] } });
  }
  createBuffer(channels, length, rate) {
    const data = Array.from({ length: channels }, () => new Float32Array(length));
    return { length, sampleRate: rate, getChannelData: (i) => data[i] };
  }
  createBufferSource() {
    return this._make("bufsrc", { buffer: null, start() { this.started = true; }, stop() { this.stopped = true; }, onended: null });
  }
}
function chain(settings, failOn) {
  const ctx = new FakeCtx();
  const mic = new Node(ctx, "mic");
  if (failOn) ctx.failOn = failOn;
  return { ctx, mic, chain: new vx.VoiceChain(ctx, mic, settings, (t, l) => { ctx.logged = [t, l]; }) };
}

test("biquads : mêmes coefficients que le calcul de référence partagé avec l'application", () => {
  assert.ok(vectors.cases.length >= 5);
  for (const c of vectors.cases) {
    const got = vx.biquad(c.type, c.hz, c.q, c.gain_db, c.rate);
    got.forEach((x, i) => assert.ok(Math.abs(x - c.coefs[i]) < 1e-9, c.type + " " + c.hz + " coef " + i + " : " + x + " != " + c.coefs[i]));
  }
});

test("réponse d'une bande en cloche : +6 dB à sa fréquence, presque 0 loin d'elle", () => {
  const k = vx.biquad("peaking", 880, 1.4, 6, 48000);
  assert.ok(Math.abs(vx.responseDb(k, 880, 48000) - 6) < 0.01);
  assert.ok(Math.abs(vx.responseDb(k, 100, 48000)) < 0.3);
});

test("réglages validés : bornes, bandes complètes, coupe-haut au-dessus du coupe-bas, fichier étranger refusé", () => {
  const s = vx.validate({ enabled: true, highpassHz: 5000, lowpassHz: 900, bands: [{ gainDb: 40, q: 99, hz: 1 }],
                          chorus: { on: true, type: "zzz", mix: 300 }, reverb: { type: "hall", seconds: -1 } });
  assert.equal(s.highpassHz, 1000);
  assert.ok(s.lowpassHz >= s.highpassHz + 300);
  assert.equal(s.bands.length, 10);
  assert.deepEqual([s.bands[0].gainDb, s.bands[0].q], [vx.GAIN_MAX_DB, 8]);
  assert.ok(s.bands[0].hz >= 100 / 1.5);
  assert.equal(s.chorus.type, "classic"); assert.equal(s.chorus.mix, 100);
  assert.equal(s.reverb.seconds, 0.2);
  assert.equal(vx.validate("n'importe quoi").enabled, false);
  assert.deepEqual(vx.importJson(vx.exportJson(s)), s);
  assert.throws(() => vx.importJson(JSON.stringify({ enabled: true })));
  for (const p of Object.values(vx.PRESETS)) assert.deepEqual(vx.validate(p.make()), p.make());
});

test("hors émission : rien vers la station ; en émission : sortie ouverte ; limiteur toujours présent", () => {
  const { chain: c, ctx } = chain(vx.PRESETS.dx.make());
  assert.equal(c.toStation.gain.value, 0);
  assert.equal(c.input.gain.value, 0);
  c.setTx(true);
  assert.equal(c.toStation.gain.value, 1);
  assert.equal(c.input.gain.value, 1);
  assert.ok(c.bypass.out.has(c.tail) && c.processed.out.has(c.tail) && c.tail.out.has(c.limiter) && c.limiter.out.has(c.clip) && c.clip.out.has(c.toStation))
  // scrambler (scrambler.js) : inséré juste avant le limiteur, puis retiré ; le limiteur reste toujours en bout de chaîne
  const scr = ctx.createGain();
  c.setScrambler(scr);
  assert.ok(c.tail.out.has(scr) && scr.out.has(c.limiter) && !c.tail.out.has(c.limiter));
  c.setScrambler(null);
  assert.ok(c.tail.out.has(c.limiter) && !c.tail.out.has(scr) && !scr.out.has(c.limiter));
  const curve = c.clip.curve;
  assert.ok(Math.max(...curve) <= Math.pow(10, vx.LIMIT_DBFS / 20) + 1e-6);         // jamais au-dessus du plafond
});

test("éteint : contournement (limiteur seul) ; allumé : chaîne traitée", () => {
  const { chain: c } = chain(vx.defaults());
  assert.deepEqual([c.bypass.gain.value, c.processed.gain.value], [1, 0]);
  c.apply(Object.assign(vx.defaults(), { enabled: true }));
  assert.deepEqual([c.bypass.gain.value, c.processed.gain.value], [0, 1]);
});

test("erreur dans la chaîne : contournement signalé, jamais de silence", () => {
  const { ctx, chain: c } = chain(vx.PRESETS.dx.make(), "convolver");
  assert.equal(c.failed, true);
  assert.deepEqual([c.bypass.gain.value, c.processed.gain.value], [1, 0]);
  assert.equal(ctx.logged[1], "warn");
  c.setTx(true);
  assert.equal(c.toStation.gain.value, 1);
});

test("retour en réception : traîne de réverbération coupée net (réverbération recréée), sortie fermée", () => {
  const s = vx.PRESETS.dx.make(); s.reverb.on = true; s.reverb.mix = 50;
  const { chain: c } = chain(s);
  c.setTx(true);
  const before = c.convolver;
  c.setTx(false);
  assert.notEqual(c.convolver, before);
  assert.equal(before.out.size, 0);                       // l'ancienne n'est plus branchée
  assert.equal(c.toStation.gain.value, 0);
  assert.equal(c.input.gain.value, 0);
});

test("écoute de contrôle et relecture : jamais vers la station, refusées en émission, arrêtées par la prise", () => {
  const { ctx, chain: c } = chain(vx.PRESETS.neutre.make());
  assert.equal(c.setMonitor(true), true);
  assert.equal(c.monitor.gain.value, 1);
  assert.equal(c.toStation.gain.value, 0);                // écoute en réception : rien vers la station
  assert.equal(c.playBuffer(ctx.createBuffer(1, 10, 48000)), true);
  const src = c.playing;
  assert.ok(src.out.has(c.playIn) && src.started);
  c.setTx(true);                                          // prise d'émission : tout s'arrête
  assert.equal(c.monitoring, false);
  assert.equal(c.playing, null);
  assert.ok(src.stopped);
  assert.equal(c.monitor.gain.value, 0);
  assert.equal(c.setMonitor(true), false);
  assert.equal(c.playBuffer(ctx.createBuffer(1, 10, 48000)), false);
  assert.ok(!c.monitor.out.has(c.toStation) && !c.toStation.out.has(c.ctx.destination));
});

test("chorus et réverbération éteints : aucune part d'effet ; dosés : parts proportionnelles", () => {
  const s = vx.PRESETS.neutre.make();
  const { chain: c } = chain(s);
  assert.equal(c.chorusWet.gain.value, 0); assert.equal(c.revWet.gain.value, 0);
  s.chorus = { on: true, type: "ensemble", mix: 40, rateHz: 1, depthMs: 3 };
  s.reverb = { on: true, type: "hall", mix: 30, seconds: 1.8 };
  c.apply(s);
  assert.equal(c.chorusWet.gain.value, 0.4); assert.equal(c.revWet.gain.value, 0.3);
  assert.equal(c.voices.filter((v) => v.level.gain.value > 0).length, 3);
  assert.equal(c.eq[0].type, "lowshelf"); assert.equal(c.eq[9].type, "highshelf"); assert.equal(c.eq[4].type, "peaking");
});

test("réponse impulsionnelle générée : longueur, décroissance, deux canaux", () => {
  let x = 0.5;
  const rnd = () => (x = (x * 9301 + 49297) % 233280 / 233280);
  const [l, r] = vx.impulse("hall", 1, 8000, rnd);
  assert.equal(l.length, 8000); assert.equal(r.length, 8000);
  const energy = (a, b) => { let e = 0; for (let i = a; i < b; i++) e += l[i] * l[i]; return e; };
  assert.ok(energy(0, 800) > 20 * energy(7200, 8000));
});

test("micro : gain appliqué, porte de bruit réglable (atténue sans couper, maintien), coupée par défaut", () => {
  const timers = { started: 0, cleared: 0, setInterval() { this.started++; return 7; }, clearInterval() { this.cleared++; } };
  const ctx = new FakeCtx();
  const s = vx.defaults();
  assert.deepEqual(s.mic, { gainDb: 0, gateOn: false, gateDb: -50 });
  const c = new vx.VoiceChain(ctx, new Node(ctx, "mic"), s, null, timers);
  assert.equal(timers.started, 0);                                            // porte coupée : aucune minuterie
  assert.equal(c.gate.gain.value, 1);
  s.mic = { gainDb: 6, gateOn: true, gateDb: -40 };
  c.apply(s);
  assert.ok(Math.abs(c.pre.gain.value - Math.pow(10, 6 / 20)) < 1e-9);
  assert.equal(timers.started, 1);
  ctx.micLevel = 0.1;                                                         // -20 dBFS : voix au-dessus du seuil
  assert.ok(Math.abs(c.micLevelDb() + 20) < 0.01);
  assert.equal(c._gateTick(1000), 1);
  ctx.micLevel = 0.001;                                                       // -60 dBFS : fond
  assert.equal(c._gateTick(1200), 1);                                         // maintien 250 ms après la voix
  assert.equal(c._gateTick(1300), vx.GATE_FLOOR);                            // puis atténuée, jamais muette
  assert.ok(vx.GATE_FLOOR > 0);
  s.mic.gateOn = false; c.apply(s);
  assert.equal(timers.cleared, 1); assert.equal(c.gate.gain.value, 1);
  assert.equal(vx.validate({ mic: { gainDb: 99, gateDb: 0 } }).mic.gainDb, 20);
  assert.equal(vx.validate({ mic: { gateDb: 0 } }).mic.gateDb, -20);
});

let failed = 0;
test("préréglages partagés avec l'application (tests/protocol/voice_presets.json) : identiques à ceux de la page", () => {
  const shared = JSON.parse(fs.readFileSync(path.join(__dirname, "../protocol/voice_presets.json"), "utf-8"));
  for (const [key, p] of Object.entries(vx.PRESETS)) assert.deepEqual(JSON.parse(vx.exportJson(p.make())), shared.presets[key], key);
  assert.deepEqual(JSON.parse(vx.exportJson(vx.defaults())), shared.defaults);
});

for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests de l'égaliseur de voix réussis");
process.exit(failed ? 1 : 0);
