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
                             silent: [], ng: [], ignorePttOff: 0, alreadyTx: false, sRaw: 50 }, opts || {});
    this.st = { freq: 14074000, mode: 0x01, filter: 1, data: 0, dataFilter: 0, power: 255, ptt: !!this.o.alreadyTx };
    this.toneOn = false; this.txLog = []; this.txSince = this.st.ptt ? Date.now() : null; this.writes = [];
    this.parser = new civ.Parser();
  }
  // Transport ouvert à une vitesse : le poste ne comprend que la sienne.
  transport(baud) {
    const rig = this; let cb = () => {}; let open = true;
    return {
      onData(f) { cb = f; },
      async write(bytes) {
        if (!open) throw new Error("port fermé");
        if (rig.o.echo) setTimeout(() => cb(Uint8Array.from(bytes)), 0);
        if (baud !== rig.o.baud) { setTimeout(() => cb(Uint8Array.from([0x00, 0x7F, 0x13])), 0); return; }   // octets illisibles
        for (const f of rig.parser.push(bytes)) {
          const reply = rig.handle(f);
          if (reply) setTimeout(() => cb(Uint8Array.from([0xFE, 0xFE, 0xE0, rig.o.addr, ...reply, 0xFD])), rig.o.delay);
        }
      },
      async close() { open = false; },
    };
  }
  key(on) {
    const now = Date.now();
    if (on && !this.st.ptt) this.txSince = now;
    if (!on && this.st.ptt) { this.txLog.push(now - this.txSince); this.txSince = null; }
    this.st.ptt = on;
  }
  maxTx() { return Math.max(0, ...this.txLog, this.st.ptt ? Date.now() - this.txSince : 0); }
  handle(f) {
    if (f.to !== this.o.addr && f.to !== 0x00) return null;
    const p = f.payload, key = civ.hex(p.slice(0, p[0] === 0x03 || p[0] === 0x04 || p[0] === 0x05 || p[0] === 0x06 ? 1 : 2));
    if (p[0] !== 0x19 || f.to === this.o.addr) this.writes.push({ cmd: civ.hex(p), ptt: this.st.ptt });
    if (this.o.silent.includes(key)) return null;
    if (this.o.ng.includes(key)) return [0xFA];
    const s = this.st, ok = [0xFB];
    switch (p[0]) {
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
        if (p[1] !== 0x00) return [0xFA];
        if (p.length > 2) { if (p[2] === 0 && this.o.ignorePttOff > 0) { this.o.ignorePttOff--; return ok; } this.key(p[2] === 1); return ok; }
        return [0x1C, 0x00, s.ptt ? 1 : 0];
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
