// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Spatialisation stéréo de l'audio reçu, « ST » (docs/spatialisation-cahier-des-charges.md, V1).
   Traitement CLIENT seulement, réception seulement : la station n'en sait rien, le flux réseau reste mono.

   Chaque moteur fournit un couple milieu / côté (M, S) de même puissance que le signal ; sortie
   G = g·(M + w·S), D = g·(M − w·S), g = 1/√(1 + (w·(1 − p))²) : même sonie que le mono dans la bande de la voix.
   - Décorrélation : M = signal, S = signal passé dans 6 passe-tout de Schroeder (G + D = 2·g·signal, sans peigne).
   - Binaural : paire de passe-tout à 90° (Niemitalo), M = (A + B)/√2, S = (A − B)/√2 : à w = 1, G = A et D = B.
   Présence voix p : S ← S − p·passe-bande 300-2 700 Hz(S) (FIR à phase linéaire, tout est retardé de 127 échantillons,
   2,6 ms à 48 kHz), la voix reste au centre. Paramètres lissés (20 ms),
   moteur et bypass en fondu linéaire (50 ms), limiteur stéréo lié (plafond −1 dBFS) toujours en service.

   Même fichier : module Node (tests), script de la page et module AudioWorklet (registerProcessor). */
(function (root) {
  "use strict";

  const SMOOTH_S = 0.02, FADE_S = 0.05, CEILING = Math.pow(10, -1 / 20), RELEASE_S = 0.1;
  const VOICE_LO_HZ = 300, VOICE_HI_HZ = 2700, FIR_TAPS = 255, LATENCY = (FIR_TAPS - 1) / 2;
  // Paire de passe-tout à 90° (O. Niemitalo) : cellules a²·(x + y[n-2]) − x[n-2] ; voie A retardée d'un échantillon
  const HILBERT_A = [0.6923878, 0.9360654322959, 0.9882295226860, 0.9987488452737];
  const HILBERT_B = [0.4021921162426, 0.8561710882420, 0.9722909545651, 0.9952884791278];
  // Décorrélation : retards (ms) et gain des 6 passe-tout de Schroeder
  const DECOR_MS = [1.3, 2.1, 2.9, 3.7, 4.9, 6.7], DECOR_G = 0.5;
  const ENGINES = ["decor", "binaural"];
  const PRESETS = {
    mono: { label: "Mono", engine: null, width: 0, presence: 0 },
    comfort: { label: "Confort", engine: "decor", width: 70, presence: 40 },
    dx: { label: "DX BLU", engine: "binaural", width: 80, presence: 25 },
    cw: { label: "CW binaural", engine: "binaural", width: 100, presence: 0 },
  };
  const WIDTH_MAX = 150;

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function num(v, lo, hi, dflt) { return typeof v === "number" && Number.isFinite(v) ? Math.round(clamp(v, lo, hi)) : dflt; }

  function defaults() {
    return { on: false, preset: "comfort", width: PRESETS.comfort.width, presence: PRESETS.comfort.presence, balance: 0, monoOut: false };
  }

  function validate(raw) {
    /* Réglages enregistrés sur l'appareil ; toute valeur hors bornes est ramenée dans les bornes. */
    const d = defaults();
    if (!raw || typeof raw !== "object") return d;
    if (typeof raw.on === "boolean") d.on = raw.on;
    if (typeof raw.monoOut === "boolean") d.monoOut = raw.monoOut;
    if (typeof raw.preset === "string" && PRESETS[raw.preset]) {
      d.preset = raw.preset;
      d.width = PRESETS[d.preset].width; d.presence = PRESETS[d.preset].presence;
    }
    d.width = num(raw.width, 0, WIDTH_MAX, d.width);
    d.presence = num(raw.presence, 0, 100, d.presence);
    d.balance = num(raw.balance, -100, 100, 0);
    return d;
  }

  function choose(s, key) {
    /* Choix d'un préréglage : ses valeurs remplacent les curseurs (l'équilibre reste). */
    const p = PRESETS[key];
    if (!p) return s;
    return Object.assign({}, s, { preset: key, width: p.width, presence: p.presence });
  }

  function isModified(s) {
    const p = PRESETS[s.preset];
    return !!p && p.engine !== null && (s.width !== p.width || s.presence !== p.presence);
  }

  function label(s) { const p = PRESETS[s.preset]; return p ? p.label + (isModified(s) ? " (modifié)" : "") : "?"; }

  function params(s, abMono) {
    /* Réglages -> paramètres du traitement. Bypass : ST éteint, préréglage Mono, sortie mono, ou A/B maintenu. */
    const p = PRESETS[s.preset] || PRESETS.mono;
    const bypass = !s.on || s.monoOut || !!abMono || p.engine === null;
    return { engine: p.engine || "decor", width: s.width / 100, presence: s.presence / 100, balance: s.balance / 100, bypass };
  }

  function voiceFir(rate) {
    /* Passe-bande 300-2 700 Hz à phase linéaire (sinus cardinal fenêtré de Hamming, FIR_TAPS coefficients) : le
       côté S et le milieu M sont retardés d'autant, le dosage de présence reste donc sans rotation de phase. */
    const h = new Float64Array(FIR_TAPS), c = (FIR_TAPS - 1) / 2;
    const lp = (fc, k) => k === 0 ? 2 * fc / rate : Math.sin(2 * Math.PI * fc * k / rate) / (Math.PI * k);
    for (let i = 0; i < FIR_TAPS; i++) {
      const k = i - c, win = 0.54 - 0.46 * Math.cos(2 * Math.PI * i / (FIR_TAPS - 1));
      h[i] = (lp(VOICE_HI_HZ, k) - lp(VOICE_LO_HZ, k)) * win;
    }
    return h;
  }

  class AllpassPair {
    /* Deux sorties en quadrature (90°), amplitude plate. */
    constructor() {
      this.ka = HILBERT_A.map((a) => a * a); this.kb = HILBERT_B.map((a) => a * a);
      this.sa = new Float64Array(16); this.sb = new Float64Array(16); this.aDelay = 0;
    }
    static cells(k, st, x) {
      // st[4i..4i+3] = x[n-1], x[n-2], y[n-1], y[n-2] de la cellule i
      for (let i = 0; i < 4; i++) {
        const j = 4 * i, y = k[i] * (x + st[j + 3]) - st[j + 1];
        st[j + 1] = st[j]; st[j] = x; st[j + 3] = st[j + 2]; st[j + 2] = y;
        x = y;
      }
      return x;
    }
    run(x, out) {
      out[0] = this.aDelay; this.aDelay = AllpassPair.cells(this.ka, this.sa, x);
      out[1] = AllpassPair.cells(this.kb, this.sb, x);
    }
  }

  class Decorrelator {
    constructor(rate) {
      this.lines = DECOR_MS.map((ms) => new Float64Array(Math.max(1, Math.round(ms * rate / 1000))));
      this.pos = DECOR_MS.map(() => 0);
    }
    run(x) {
      for (let i = 0; i < this.lines.length; i++) {
        const line = this.lines[i], p = this.pos[i], old = line[p];
        const v = x + DECOR_G * old;
        line[p] = v;
        this.pos[i] = p + 1 === line.length ? 0 : p + 1;
        x = old - DECOR_G * v;
      }
      return x;
    }
  }

  class Spatial {
    constructor(rate, initial) {
      this.rate = rate;
      this.smooth = 1 - Math.exp(-1 / (SMOOTH_S * rate));
      this.fadeStep = 1 / (FADE_S * rate);
      this.release = 1 - Math.exp(-1 / (RELEASE_S * rate));
      this.pair = new AllpassPair(); this.decor = new Decorrelator(rate);
      this.fir = voiceFir(rate);
      this.hist = { x: new Float64Array(FIR_TAPS), m: new Float64Array(FIR_TAPS), s: new Float64Array(FIR_TAPS), pos: 0 };
      this.ab = new Float64Array(2);
      this.gain = 1;
      this.corr = { lr: 0, ll: 0, rr: 0, n: 0, value: 1 };
      this.target = { engine: "decor", width: 0, presence: 0, balance: 0, bypass: true };
      this.set(initial || this.target);
      this.jump();
    }
    set(p) {
      /* Nouveaux paramètres : atteints en douceur (curseurs 20 ms, moteur et bypass 50 ms). */
      const t = this.target;
      if (ENGINES.includes(p.engine)) t.engine = p.engine;
      t.width = clamp(Number(p.width) || 0, 0, WIDTH_MAX / 100);
      t.presence = clamp(Number(p.presence) || 0, 0, 1);
      t.balance = clamp(Number(p.balance) || 0, -1, 1);
      t.bypass = !!p.bypass;
    }
    jump() {
      /* Valeurs atteintes tout de suite (création, tests). */
      const t = this.target;
      this.w = t.width; this.p = t.presence; this.bal = t.balance;
      this.mixB = t.engine === "binaural" ? 1 : 0;
      this.dry = t.bypass ? 1 : 0;
    }
    reset() {
      this.pair = new AllpassPair(); this.decor = new Decorrelator(this.rate);
      for (const a of [this.hist.x, this.hist.m, this.hist.s]) a.fill(0);
      this.gain = 1;
    }
    correlation() { return this.corr.value; }
    reduction() { return this.gain; }
    process(input, outL, outR, n) {
      n = n === undefined ? input.length : n;
      const t = this.target, ab = this.ab, c = this.corr;
      const wantB = t.engine === "binaural" ? 1 : 0, wantDry = t.bypass ? 1 : 0;
      for (let i = 0; i < n; i++) {
        let x = input[i];
        if (!Number.isFinite(x)) x = 0;
        this.w += (t.width - this.w) * this.smooth;
        this.p += (t.presence - this.p) * this.smooth;
        this.bal += (t.balance - this.bal) * this.smooth;
        this.mixB += clamp(wantB - this.mixB, -this.fadeStep, this.fadeStep);
        this.dry += clamp(wantDry - this.dry, -this.fadeStep, this.fadeStep);
        // Les deux moteurs tournent toujours : changement de moteur sans transitoire
        this.pair.run(x, ab);
        const mB = (ab[0] + ab[1]) * Math.SQRT1_2, sB = (ab[0] - ab[1]) * Math.SQRT1_2;
        const sD = this.decor.run(x);
        // Lignes de retard communes (LATENCY échantillons) : signal direct, milieu, côté ; présence = côté filtré
        const hs = this.hist, pos = hs.pos;
        hs.x[pos] = x; hs.m[pos] = this.mixB * mB + (1 - this.mixB) * x; hs.s[pos] = this.mixB * sB + (1 - this.mixB) * sD;
        hs.pos = pos + 1 === FIR_TAPS ? 0 : pos + 1;
        const old = (pos + FIR_TAPS - LATENCY) % FIR_TAPS;
        x = hs.x[old];
        const m = hs.m[old];
        let s = hs.s[old];
        if (this.p > 1e-6) {
          let band = 0;
          for (let k = 0, j = pos; k < FIR_TAPS; k++, j = j === 0 ? FIR_TAPS - 1 : j - 1) band += this.fir[k] * hs.s[j];
          s -= this.p * band;
        }
        // Sonie : la présence retire du côté dans la bande de la voix, qui domine => largeur effective w·(1 − p)
        const w = this.w, we = w * (1 - this.p), g = 1 / Math.sqrt(1 + we * we);
        let l = g * (m + w * s), r = g * (m - w * s);
        l = this.dry * x + (1 - this.dry) * l;
        r = this.dry * x + (1 - this.dry) * r;
        if (this.bal > 0) l *= 1 - this.bal; else r *= 1 + this.bal;
        // Limiteur lié : réduction instantanée, remontée en 100 ms sans jamais dépasser le plafond
        const peak = Math.max(Math.abs(l), Math.abs(r));
        const need = peak > CEILING ? CEILING / peak : 1;
        this.gain = Math.min(need, this.gain + (1 - this.gain) * this.release);
        l *= this.gain; r *= this.gain;
        if (!Number.isFinite(l) || !Number.isFinite(r)) { this.reset(); l = r = 0; }
        outL[i] = l; outR[i] = r;
        c.lr += l * r; c.ll += l * l; c.rr += r * r;
        if (++c.n >= this.rate / 4) {
          c.value = c.ll > 1e-12 && c.rr > 1e-12 ? c.lr / Math.sqrt(c.ll * c.rr) : 1;
          c.lr = c.ll = c.rr = 0; c.n = 0;
        }
      }
    }
  }

  function sharedTable() {
    /* tests/protocol/spatial_presets.json : préréglages et réponses impulsionnelles de référence (48 kHz, 64
       échantillons après le retard commun) que la page et l'application doivent trouver à l'identique. */
    const out = {
      _note: "Spatialisation (spatial.js) : préréglages et réponses à une impulsion de 0,5 à 48 kHz (64 échantillons à partir du retard commun de 127), valeurs atteintes d'emblée. La page et l application (logic/Spatial.kt) doivent trouver ces échantillons à 1e-6 près. Fabriqué par spatial.js.",
      rate: 48000, presets: {}, impulse: {},
    };
    for (const [key, p] of Object.entries(PRESETS)) {
      out.presets[key] = { label: p.label, engine: p.engine, width: p.width, presence: p.presence };
      const s = choose(Object.assign(defaults(), { on: true }), key);
      const sp = new Spatial(48000, params(s, false));
      const n = LATENCY + 64, x = new Float64Array(n), l = new Float64Array(n), r = new Float64Array(n);
      x[0] = 0.5;
      sp.process(x, l, r, n);
      const round = (v) => Math.round(v * 1e9) / 1e9;
      out.impulse[key] = { left: Array.from(l.subarray(LATENCY), round), right: Array.from(r.subarray(LATENCY), round) };
    }
    return out;
  }

  const api = { PRESETS, ENGINES, WIDTH_MAX, CEILING, FIR_TAPS, LATENCY, HILBERT_A, HILBERT_B, DECOR_MS, DECOR_G, VOICE_LO_HZ, VOICE_HI_HZ,
    defaults, validate, choose, isModified, label, params, Spatial, sharedTable };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TrxSpatial = api;

  // Module AudioWorklet de la page : node.port.postMessage(params) ; renvoie {corr, gain} toutes les 250 ms
  if (typeof registerProcessor === "function" && typeof AudioWorkletProcessor !== "undefined") {
    registerProcessor("trx-spatial", class extends AudioWorkletProcessor {
      constructor(options) {
        super();
        const o = (options && options.processorOptions) || {};
        this.s = new Spatial(sampleRate, o);
        this.s.dry = 1;                                              // démarrage en mono, fondu vers l'effet
        this.tick = 0;
        this.port.onmessage = (ev) => this.s.set(ev.data || {});
      }
      process(inputs, outputs) {
        const out = outputs[0];
        if (!out || !out[0]) return true;
        const l = out[0], r = out[1] || out[0];
        const inp = inputs[0] && inputs[0][0];
        if (!inp) { l.fill(0); if (r !== l) r.fill(0); return true; }
        this.s.process(inp, l, r, l.length);
        this.tick += l.length;
        if (this.tick >= sampleRate / 4) { this.tick = 0; this.port.postMessage({ corr: this.s.correlation(), gain: this.s.reduction() }); }
        return true;
      }
    });
  }
})(typeof window !== "undefined" ? window : globalThis);
