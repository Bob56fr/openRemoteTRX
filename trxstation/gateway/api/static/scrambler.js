// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Scrambler de voix à bandes inversées / permutées (décision de l'utilisateur du 2026-10-29, docs/scrambler.md).
   Traitement CLIENT seulement : émission brouillée avant le limiteur de voice.js, réception débrouillée avant le
   haut-parleur. La station n'en sait rien. Désactivé par défaut, jamais réactivé seul (réglage non enregistré).

   Calcul : transformée de Fourier à court terme (2 048 points, demi-recouvrement, fenêtres racine de Hann), bins de la
   bande 300-3 000 Hz découpée en 1 à 5 bandes de même largeur ; chaque bande est recopiée dans une autre (permutation)
   à l'endroit ou retournée (inversion = miroir + conjugué). Les limites sont choisies sur des bins PAIRS : le
   déplacement d'un bin est alors toujours d'un nombre pair de bins, ce qui rend l'opération indépendante du découpage
   en trames ; l'émetteur et le récepteur n'ont donc pas besoin d'être synchronisés. Réception : décalage fin (BLU mal
   accordée) par un décaleur de fréquence (transformée de Hilbert) avant le débrouillage.

   Même fichier : module Node (tests), script de la page et module AudioWorklet (registerProcessor). */
(function (root) {
  "use strict";

  const FRAME = 2048, HOP = 1024, LO_HZ = 300, HI_HZ = 3000, OFFSET_MAX_HZ = 300;
  // perm[i] = case où va la bande i ; inv[i] = 1 si la bande est retournée
  const MODES = {
    inv1: { label: "Inversion simple (1 bande)", perm: [0], inv: [1] },
    inv2: { label: "2 bandes inversées", perm: [0, 1], inv: [1, 1] },
    inv3: { label: "3 bandes inversées", perm: [0, 1, 2], inv: [1, 1, 1] },
    inv4: { label: "4 bandes inversées", perm: [0, 1, 2, 3], inv: [1, 1, 1, 1] },
    inv5: { label: "5 bandes inversées", perm: [0, 1, 2, 3, 4], inv: [1, 1, 1, 1, 1] },
    mix2: { label: "2 bandes échangées", perm: [1, 0], inv: [0, 0] },
    mix3: { label: "3 bandes mélangées", perm: [2, 0, 1], inv: [1, 0, 1] },
    mix4: { label: "4 bandes mélangées", perm: [1, 3, 0, 2], inv: [1, 1, 0, 0] },
    mix5a: { label: "5 bandes mélangées A", perm: [4, 2, 0, 3, 1], inv: [1, 1, 1, 1, 1] },
    mix5b: { label: "5 bandes mélangées B", perm: [2, 4, 1, 0, 3], inv: [0, 1, 0, 1, 1] },
  };

  function defaults() { return { tx: false, rx: false, mode: "inv1", offsetHz: 0 }; }

  function validate(raw) {
    /* Seuls le mode et le décalage sont repris : tx et rx repartent TOUJOURS éteints (jamais réactivés seuls). */
    const d = defaults();
    if (!raw || typeof raw !== "object") return d;
    if (typeof raw.mode === "string" && MODES[raw.mode]) d.mode = raw.mode;
    if (typeof raw.offsetHz === "number" && Number.isFinite(raw.offsetHz)) d.offsetHz = Math.round(Math.max(-OFFSET_MAX_HZ, Math.min(OFFSET_MAX_HZ, raw.offsetHz)));
    return d;
  }

  function bands(n, rate, frame) {
    /* Bandes [a, b] en bins (a et b pairs), un bin libre entre deux bandes. */
    const df = rate / frame;
    let lo = Math.ceil(LO_HZ / df); if (lo % 2) lo++;
    const hi = Math.floor(HI_HZ / df);
    let w = Math.floor((hi - lo) / n); if (w % 2) w--;
    const out = [];
    for (let i = 0; i < n; i++) out.push([lo + i * w, lo + i * w + w - 2]);
    return out;
  }

  function binMap(modeKey, direction, rate, frame) {
    /* dest[k] = bin où va le bin k (-1 : supprimé) ; conj[k] = 1 si retourné. direction : "tx" brouille, "rx" débrouille. */
    const mode = MODES[modeKey];
    if (!mode) throw new Error("mode de scrambler inconnu : " + modeKey);
    const half = frame / 2 + 1;
    const dest = new Int32Array(half).fill(-1), conj = new Uint8Array(half);
    const b = bands(mode.perm.length, rate, frame);
    mode.perm.forEach((slot, i) => {
      const [srcA, srcB] = direction === "tx" ? b[i] : b[slot];
      const [dstA, dstB] = direction === "tx" ? b[slot] : b[i];
      for (let k = srcA; k <= srcB; k++) {
        const off = k - srcA;
        dest[k] = mode.inv[i] ? dstB - off : dstA + off;
        conj[k] = mode.inv[i];
      }
    });
    return { dest, conj };
  }

  function fft(re, im, inverse) {
    /* FFT complexe en place (radix 2) ; inverse normalisée par 1/n. */
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const ang = (inverse ? 2 : -2) * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        for (let k = 0; k < len / 2; k++) {
          const a = i + k, b = a + len / 2;
          const xr = re[b] * cr - im[b] * ci, xi = re[b] * ci + im[b] * cr;
          re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi;
          const t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t;
        }
      }
    }
    if (inverse) for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n; }
  }

  class Shifter {
    /* Décalage de fréquence de `hz` (Hilbert FIR 127 coefficients, fenêtre de Blackman) : x·cos − H{x}·sin. */
    constructor(rate) {
      this.rate = rate; this.hz = 0; this.phase = 0;
      const n = 127, m = (n - 1) / 2;
      this.h = new Float64Array(n);
      for (let i = 0; i < n; i++) {
        const k = i - m;
        const w = 0.42 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1)) + 0.08 * Math.cos(4 * Math.PI * i / (n - 1));
        this.h[i] = k % 2 ? (2 / (Math.PI * k)) * w : 0;
      }
      this.line = new Float64Array(n); this.pos = 0; this.mid = m;
    }
    run(x) {
      const n = this.h.length;
      this.line[this.pos] = x;
      if (this.hz === 0) { this.pos = (this.pos + 1) % n; return this.line[(this.pos + n - 1 - this.mid) % n]; }
      let hil = 0;
      for (let i = 0; i < n; i++) hil += this.h[i] * this.line[(this.pos - i + n) % n];
      const direct = this.line[(this.pos - this.mid + n) % n];
      this.pos = (this.pos + 1) % n;
      this.phase += 2 * Math.PI * this.hz / this.rate;
      if (this.phase > Math.PI) this.phase -= 2 * Math.PI;
      return direct * Math.cos(this.phase) - hil * Math.sin(this.phase);
    }
  }

  class Scrambler {
    /* direction : "tx" (brouille) ou "rx" (débrouille, avec décalage fin). Mode null = transparent (sans retard). */
    constructor(rate, direction) {
      this.rate = rate; this.direction = direction === "rx" ? "rx" : "tx";
      this.win = new Float64Array(FRAME);
      for (let i = 0; i < FRAME; i++) this.win[i] = Math.sin(Math.PI * i / FRAME);
      this.inBuf = new Float64Array(FRAME); this.outAcc = new Float64Array(FRAME);
      this.re = new Float64Array(FRAME); this.im = new Float64Array(FRAME);
      this.ore = new Float64Array(FRAME); this.oim = new Float64Array(FRAME);
      this.ready = new Float64Array(HOP); this.fill = 0; this.readPos = HOP;
      this.shifter = new Shifter(rate);
      this.mode = null; this.map = null;
    }
    set(mode, offsetHz) {
      const m = mode && MODES[mode] ? mode : null;
      if (m !== this.mode) {
        this.mode = m;
        this.map = m ? binMap(m, this.direction, this.rate, FRAME) : null;
        this.clear();
      }
      this.shifter.hz = this.direction === "rx" ? Math.max(-OFFSET_MAX_HZ, Math.min(OFFSET_MAX_HZ, offsetHz || 0)) : 0;
    }
    clear() { this.inBuf.fill(0); this.outAcc.fill(0); this.ready.fill(0); this.fill = 0; this.readPos = HOP; }
    _frame() {
      const { dest, conj } = this.map;
      for (let i = 0; i < FRAME; i++) { this.re[i] = this.inBuf[i] * this.win[i]; this.im[i] = 0; }
      fft(this.re, this.im, false);
      this.ore.fill(0); this.oim.fill(0);
      for (let k = 0; k <= FRAME / 2; k++) {
        const d = dest[k];
        if (d < 0) continue;
        this.ore[d] = this.re[k]; this.oim[d] = conj[k] ? -this.im[k] : this.im[k];
      }
      for (let k = 1; k < FRAME / 2; k++) { this.ore[FRAME - k] = this.ore[k]; this.oim[FRAME - k] = -this.oim[k]; }
      fft(this.ore, this.oim, true);
      for (let i = 0; i < FRAME; i++) this.outAcc[i] += this.ore[i] * this.win[i];
      for (let i = 0; i < HOP; i++) this.ready[i] = this.outAcc[i];
      this.outAcc.copyWithin(0, HOP); this.outAcc.fill(0, FRAME - HOP);
      this.inBuf.copyWithin(0, HOP);
      this.readPos = 0;
    }
    process(input, output, n) {
      /* Bloc de taille quelconque ; sortie retardée de 2 048 échantillons (43 ms à 48 kHz). */
      n = n === undefined ? input.length : n;
      if (!this.map) { for (let i = 0; i < n; i++) output[i] = this.direction === "rx" ? this.shifter.run(input[i]) : input[i]; return; }
      for (let i = 0; i < n; i++) {
        const x = this.direction === "rx" ? this.shifter.run(input[i]) : input[i];
        this.inBuf[FRAME - HOP + this.fill] = x;
        this.fill++;
        if (this.fill === HOP) { this.fill = 0; this._frame(); }
        output[i] = this.readPos < HOP ? this.ready[this.readPos++] : 0;
      }
    }
  }

  const api = { FRAME, HOP, LO_HZ, HI_HZ, OFFSET_MAX_HZ, MODES, defaults, validate, bands, binMap, fft, Shifter, Scrambler };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TrxScrambler = api;

  // Module AudioWorklet de la page : node.port.postMessage({mode, offsetHz}) ; mode null = transparent
  if (typeof registerProcessor === "function" && typeof AudioWorkletProcessor !== "undefined") {
    registerProcessor("trx-scrambler", class extends AudioWorkletProcessor {
      constructor(options) {
        super();
        const o = (options && options.processorOptions) || {};
        this.s = new Scrambler(sampleRate, o.direction);
        this.s.set(o.mode, o.offsetHz);
        this.port.onmessage = (ev) => { const d = ev.data || {}; this.s.set(d.mode, d.offsetHz); };
      }
      process(inputs, outputs) {
        const out = outputs[0] && outputs[0][0];
        if (!out) return true;
        const inp = inputs[0] && inputs[0][0];
        if (!inp) { out.fill(0); return true; }
        this.s.process(inp, out, out.length);
        for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
        return true;
      }
    });
  }
})(typeof window !== "undefined" ? window : globalThis);
