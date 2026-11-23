// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Faux Icom CI-V pour les tests d'openRemoteTRX-Autotest : répond comme un poste (OK / NG / silence), garde son état et
   le journal de ses émissions (durée de chaque passage en émission). Options pour les pannes. */
"use strict";
const path = require("path");
const civ = require(path.join(__dirname, "..", "..", "autotest", "web", "civ.js"));

const CARRIER = new Set([0x02, 0x04, 0x05]);           // AM, RTTY, FM

function invPo(pct) {                                    // % -> valeur brute (inverse de la table)
  const t = civ.PO_TABLE;
  for (let i = 1; i < t.length; i++) if (pct <= t[i][1]) { const [a, va] = t[i - 1], [b, vb] = t[i]; return Math.round(a + (b - a) * (pct - va) / (vb - va)); }
  return 255;
}

class FakeIcom {
  constructor(opts) {
    this.o = Object.assign({ addr: 0xB6, baud: 115200, echo: false, idSupported: true, delay: 2, swrRaw: 10, alcRaw: 40,
                             silent: [], ng: [], ignorePttOff: 0, alreadyTx: false, sRaw: 50,
                             ngWrite: [], stuck: [], pampClearsAtt: false, fn: {},
                             // Spectre (R10) : scope = false -> 27 10 / 27 11 refusés ; scopeTo = destination des trames
                             // 27 00 (E0 = la page) ; scopeEvery = un balayage toutes les N ms ; scopeStuck = écriture ignorée.
                             scope: true, scopeDisplay: 1, scopeOutput: 0, scopeTo: 0xE0, scopeEvery: 30, scopePoints: 475,
                             scopeLevel: 60, scopeSpan: 50000, scopeCenter: null, scopeStuck: false,
                             // Coupleur : "interne" (01 = en service sans accord, 02 = accord), "ah4" (01 LANCE l'accord),
                             // "aucun" (1C 01 refusé) ; tuner0 = état de départ ; tuneMs = durée de l'accord ; tuneResult =
                             // état en fin d'accord (1 réussi, 0 dérivation) ; att = valeurs d'atténuateur acceptées.
                             tuner: "interne", tuner0: 0, tuneMs: 120, tuneResult: 1, att: [0x20] }, opts || {});
    this.st = { freq: 14074000, mode: 0x01, filter: 1, data: 0, dataFilter: 0, power: 255, ptt: !!this.o.alreadyTx,
                otherFreq: 7100000 };
    // Fonctions (essai R9) : clé = commande en hexadécimal, valeur = octets de la donnée.
    this.fn = Object.assign({ "11": [0x00], "16 02": [0x01], "16 12": [0x02], "16 22": [0x00], "16 40": [0x01], "16 41": [0x00],
                              "16 44": [0x00], "16 65": [0x00], "14 06": [0x01, 0x28], "14 12": [0x00, 0x50], "14 0E": [0x00, 0x30],
                              "0F": [0x00], "21 01": [0x00] }, this.o.fn);
    this.tunerState = this.o.tuner0; this.tuning = false; this.tuneTimer = null; this.tunes = [];
    this.initialFn = JSON.stringify(this.fn);
    this.toneOn = false; this.txLog = []; this.txSince = this.st.ptt ? Date.now() : null; this.writes = [];
    this.parser = new civ.Parser();
    this.scope = { display: this.o.scopeDisplay, output: this.o.scopeOutput }; this.scopeTimer = null; this.scopeSent = 0;
    this.cb = () => {};
  }
  // Un balayage : division 1 = en-tête (centré : centre puis demi-largeur, BCD), puis 10 divisions de points.
  sweepFrames() {
    const o = this.o, pts = Array.from({ length: o.scopePoints }, (_, i) => Math.min(160, o.scopeLevel + (i % 7)));
    const bcd = n => ((Math.floor(n / 10)) << 4) | (n % 10), top = 11, out = [];
    const head = [0x00, ...civ.encodeFreq(o.scopeCenter == null ? this.st.freq : o.scopeCenter), ...civ.encodeFreq(o.scopeSpan), 0x00];
    out.push([0x27, 0x00, 0x00, bcd(1), bcd(top), ...head]);
    const per = Math.ceil(pts.length / (top - 1));
    for (let d = 2; d <= top; d++) out.push([0x27, 0x00, 0x00, bcd(d), bcd(top), ...pts.slice((d - 2) * per, (d - 1) * per)]);
    return out.map(p => [0xFE, 0xFE, this.o.scopeTo, this.o.addr, ...p, 0xFD]);
  }
  _scopeTick() {
    const on = this.scope.display && this.scope.output && !this.st.ptt;
    if (on && !this.scopeTimer) this.scopeTimer = setInterval(() => {
      // Envoyé en blocs coupés n'importe où (comme un port série).
      const bytes = [].concat(...this.sweepFrames()); this.scopeSent++;
      for (let i = 0; i < bytes.length; i += 37) this.cb(Uint8Array.from(bytes.slice(i, i + 37)));
    }, this.o.scopeEvery);
    if (!on && this.scopeTimer) { clearInterval(this.scopeTimer); this.scopeTimer = null; }
  }
  stopScope() { if (this.scopeTimer) clearInterval(this.scopeTimer); this.scopeTimer = null; if (this.tuneTimer) clearTimeout(this.tuneTimer); this.tuneTimer = null; }
  // Accord : le poste émet (CW, ~10 W) pendant tuneMs, puis le coupleur passe à tuneResult.
  startTune() {
    this.tuning = true; this.tunerState = 2; const t0 = Date.now();
    this.tuneTimer = setTimeout(() => { this.tuning = false; this.tunerState = this.o.tuneResult; this.tunes.push(Date.now() - t0); this.tuneTimer = null; }, this.o.tuneMs);
    this.tuneSince = t0;
  }
  abortTune() {
    if (!this.tuning) return;
    clearTimeout(this.tuneTimer); this.tuneTimer = null; this.tuning = false; this.tunes.push(Date.now() - this.tuneSince);
  }
  maxTune() { return Math.max(0, ...this.tunes, this.tuning ? Date.now() - this.tuneSince : 0); }
  // Transport ouvert à une vitesse : le poste ne comprend que la sienne.
  transport(baud) {
    const rig = this; let cb = () => {}; let open = true;
    return {
      onData(f) { cb = f; rig.cb = b => { if (open) f(b); }; },
      async write(bytes) {
        if (!open) throw new Error("port fermé");
        if (rig.o.echo) setTimeout(() => cb(Uint8Array.from(bytes)), 0);
        if (baud !== rig.o.baud) { setTimeout(() => cb(Uint8Array.from([0x00, 0x7F, 0x13])), 0); return; }   // octets illisibles
        for (const f of rig.parser.push(bytes)) {
          const reply = rig.handle(f);
          if (reply) setTimeout(() => cb(Uint8Array.from([0xFE, 0xFE, 0xE0, rig.o.addr, ...reply, 0xFD])), rig.o.delay);
        }
      },
      async close() { open = false; rig.stopScope(); },
    };
  }
  key(on) {
    const now = Date.now();
    if (on && !this.st.ptt) this.txSince = now;
    if (!on && this.st.ptt) { this.txLog.push(now - this.txSince); this.txSince = null; }
    this.st.ptt = on;
    this._scopeTick();                                   // spectre figé pendant l'émission (comme l'IC-7300)
  }
  maxTx() { return Math.max(0, ...this.txLog, this.st.ptt ? Date.now() - this.txSince : 0); }
  handle(f) {
    if (f.to !== this.o.addr && f.to !== 0x00) return null;
    const p = f.payload, one = [0x03, 0x04, 0x05, 0x06, 0x11, 0x0F, 0x25].includes(p[0]), key = civ.hex(p.slice(0, one ? 1 : 2));
    if (p[0] !== 0x19 || f.to === this.o.addr) this.writes.push({ cmd: civ.hex(p), ptt: this.st.ptt });
    if (this.o.silent.includes(key)) return null;
    if (this.o.ng.includes(key)) return [0xFA];
    const s = this.st, ok = [0xFB];
    if (key === "1C 01") {                                                     // coupleur d'antenne
      if (this.o.tuner === "aucun") return [0xFA];
      if (p.length === 2) return [0x1C, 0x01, this.tunerState];
      const v = p[2];
      if (v === 0) { this.abortTune(); this.tunerState = 0; return ok; }
      if (this.tuning || s.ptt) return [0xFA];
      if (v === 1) { if (this.o.tuner === "ah4" && this.tunerState === 0) this.startTune(); else this.tunerState = 1; return ok; }
      if (v === 2) { this.startTune(); return ok; }
      return [0xFA];
    }
    if (key === "11" && p.length > 1 && p[1] !== 0x00 && !this.o.att.includes(p[1])) return [0xFA];   // atténuateur du modèle
    if (this.tuning && [0x05, 0x06, 0x07].includes(p[0])) return [0xFA];       // poste en émission pendant l'accord
    if (key in this.fn) {                                                      // fonctions de l'essai R9
      const n = one ? 1 : 2, data = p.slice(n);
      if (!data.length) return [...p.slice(0, n), ...this.fn[key]];
      if (this.o.ngWrite.includes(key) || s.ptt) return [0xFA];
      if (key === "1C 01" && data[0] > 1) return [0xFA];
      const step = (this.o.quantize || {})[key];                         // niveau arrondi au cran du poste
      const val = step ? civ.encodeLevel(Math.round(Math.round(civ.decodeLevel(data) / step) * step)) : data;
      if (!this.o.stuck.includes(key)) this.fn[key] = val;
      if (key === "16 02" && data[0] && this.o.pampClearsAtt) this.fn["11"] = [0x00];
      return ok;
    }
    switch (p[0]) {
      case 0x27: {
        if (!this.o.scope || (p[1] !== 0x10 && p[1] !== 0x11)) return [0xFA];
        const k = p[1] === 0x10 ? "display" : "output";
        if (p.length === 2) return [0x27, p[1], this.scope[k]];
        if (p[2] > 1) return [0xFA];
        if (!this.o.scopeStuck) this.scope[k] = p[2];
        this._scopeTick(); return ok;
      }
      case 0x07: if (p[1] !== 0xB0 || s.ptt) return [0xFA]; [s.freq, s.otherFreq] = [s.otherFreq, s.freq]; return ok;
      case 0x25: return p[1] === 0x01 ? [0x25, 0x01, ...civ.encodeFreq(s.otherFreq)] : [0x25, 0x00, ...civ.encodeFreq(s.freq)];
      case 0x19: return this.o.idSupported ? [0x19, 0x00, this.o.addr] : null;
      case 0x03: return [0x03, ...civ.encodeFreq(s.freq)];
      case 0x04: return [0x04, s.mode, s.filter];
      case 0x05: if (s.ptt) return [0xFA]; s.freq = civ.decodeFreq(p.slice(1, 6)); return ok;
      case 0x06: if (s.ptt) return [0xFA]; s.mode = p[1]; s.filter = p[2] || 1; if (s.mode !== 0x01 && s.mode !== 0x00) s.data = 0; return ok;
      case 0x14: if (p.length > 2) { s.power = civ.decodeLevel(p.slice(2)); return ok; } return [0x14, 0x0A, ...civ.encodeLevel(s.power)];
      case 0x15: {
        const pct = s.power / 2.55;
        const mod = s.ptt && (CARRIER.has(s.mode) || (s.data && this.toneOn));
        const v = { 0x02: s.ptt ? 0 : this.o.sRaw + Math.round(Math.random() * 6), 0x11: mod ? invPo(pct) : 0, 0x12: s.ptt ? this.o.swrRaw : 0, 0x13: s.ptt && s.data && this.toneOn ? this.o.alcRaw : 0 }[p[1]];
        return v == null ? [0xFA] : [0x15, p[1], ...civ.encodeLevel(v)];
      }
      case 0x1A: if (p[1] !== 0x06) return [0xFA]; if (p.length > 2) { if (s.ptt) return [0xFA]; s.data = p[2]; s.dataFilter = p[3] || 0; return ok; } return [0x1A, 0x06, s.data, s.dataFilter];
      case 0x1C:
        if (p[1] !== 0x00) return [0xFA];   // 1C 01 (coupleur) : traité plus haut
        if (p.length > 2) { if (p[2] === 0 && this.o.ignorePttOff > 0) { this.o.ignorePttOff--; return ok; } this.key(p[2] === 1); return ok; }
        return [0x1C, 0x00, s.ptt || this.tuning ? 1 : 0];
      default: return [0xFA];
    }
  }
}

// Faux son : choix fait, entrée avec du bruit, tonalité reliée au poste.
function fakeAudio(rig, opts) {
  const o = Object.assign({ input: true, output: true, db: -62 }, opts || {});
  return {
    hasInput: () => o.input, hasOutput: () => o.output,
    async measureInput() { return o.db; },
    async startTone() { rig.toneOn = true; },
    stopTone() { rig.toneOn = false; },
  };
}

module.exports = { FakeIcom, fakeAudio };
