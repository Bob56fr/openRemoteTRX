// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Faux Yaesu FTDX10 (CAT ASCII) pour les tests d'openRemoteTRX-Autotest : une écriture ne répond rien (« ?; » si
   refusée), une lecture répond « XX…; ». Garde son état et le journal de ses émissions. Options pour les pannes. */
"use strict";
const path = require("path");
const ya = require(path.join(__dirname, "..", "..", "autotest", "web", "yaesu.js"));

const PREFIXES = ["AC00", "MD0", "SM0", "RM4", "RM5", "RM6", "NB0", "NL0", "NR0", "RL0", "RA0", "PA0", "BC0", "PR0",
                  "ID", "FA", "FB", "VS", "SV", "PC", "TX", "RT", "ST", "AC", "VX", "EX", "PS", "MX"];
const CARRIER = new Set(["4", "5", "6", "9"]);             // FM, AM, RTTY

function invTable(t, y) {                                   // valeur -> brut (inverse d'une table)
  for (let i = 1; i < t.length; i++) if (y <= t[i][1]) { const [a, va] = t[i - 1], [b, vb] = t[i]; return Math.round(a + (b - a) * (y - va) / (vb - va)); }
  return 255;
}
const PO_TABLE = [[0, 0], [10, 0.8], [50, 8], [100, 26], [150, 54], [200, 92], [250, 140], [255, 145]];

class FakeYaesu {
  constructor(opts) {
    this.o = Object.assign({ baud: 38400, ident: "0761", silent: [], ng: [], ngWrite: [], stuck: [], alreadyTx: false,
                             ignorePttOff: 0, delay: 2, swrRaw: 10, alcRaw: 60 }, opts || {});
    this.st = { FA: "007074000", FB: "014074000", VS: "0", MD0: "1", PC: "100", TX: this.o.alreadyTx ? "2" : "0" };
    this.fn = Object.assign({ RA0: "0", PA0: "1", NB0: "0", NL0: "005", NR0: "1", RL0: "08", BC0: "0", PR0: "1", RT: "0", ST: "0", AC00: "1" }, this.o.fn);
    this.initialFn = JSON.stringify(this.fn); this.toneOn = false; this.txLog = []; this.txSince = this.o.alreadyTx ? Date.now() : null;
    this.writes = []; this.buf = "";
  }
  get ptt() { return this.st.TX !== "0"; }
  transport(baud) {
    const rig = this; let cb = () => {}; let open = true;
    return {
      onData(f) { cb = f; },
      async write(bytes) {
        if (!open) throw new Error("port fermé");
        if (baud !== rig.o.baud) { setTimeout(() => cb(Uint8Array.from([0x00, 0x7F, 0x13])), 0); return; }
        rig.buf += Buffer.from(bytes).toString("latin1");
        let i;
        while ((i = rig.buf.indexOf(";")) >= 0) {
          const c = rig.buf.slice(0, i); rig.buf = rig.buf.slice(i + 1);
          const reply = rig.handle(c);
          if (reply) setTimeout(() => cb(Uint8Array.from(Buffer.from(reply + ";", "latin1"))), rig.o.delay);
        }
      },
      async close() { open = false; },
    };
  }
  key(on) {
    const now = Date.now();
    if (on && !this.ptt) this.txSince = now;
    if (!on && this.ptt) { this.txLog.push(now - this.txSince); this.txSince = null; }
    this.st.TX = on ? "1" : "0";
  }
  maxTx() { return Math.max(0, ...this.txLog, this.ptt ? Date.now() - this.txSince : 0); }
  meter(cmd) {
    const tx = this.ptt, data = ["8", "C", "A"].includes(this.st.MD0);
    const mod = tx && (CARRIER.has(this.st.MD0) || (data && this.toneOn));
    const v = { SM0: tx ? 0 : 45, RM5: mod ? invTable(PO_TABLE, Number(this.st.PC)) : 0, RM6: tx ? this.o.swrRaw : 0, RM4: tx && data && this.toneOn ? this.o.alcRaw : 0 }[cmd];
    return cmd + String(v).padStart(3, "0") + (cmd.startsWith("RM") ? "000" : "");
  }
  handle(c) {
    const pre = PREFIXES.find(p => c.startsWith(p));
    if (!pre) return "?";
    const param = c.slice(pre.length), isRead = param === "" && pre !== "SV";
    this.writes.push({ cmd: c, ptt: this.ptt });
    if (this.o.silent.includes(pre)) return null;
    if (this.o.ng.includes(pre)) return "?";
    if (isRead) {
      if (pre === "ID") return "ID" + this.o.ident;
      if (pre === "AC") return "AC00" + this.fn.AC00;
      if (pre in this.fn) return pre + this.fn[pre];
      if (pre in this.st) return pre + this.st[pre];
      if (["SM0", "RM4", "RM5", "RM6"].includes(pre)) return this.meter(pre);
      return "?";
    }
    // Écritures : rien en retour, « ? » si refusée.
    if (this.o.ngWrite.includes(pre)) return "?";
    if (["VX", "EX", "PS", "MX"].includes(pre)) return null;           // jamais envoyées par la page (test)
    if (pre === "TX") { if (param === "0" && this.o.ignorePttOff > 0) { this.o.ignorePttOff--; return null; } this.key(param === "1"); return null; }
    if (pre === "SV") { if (this.ptt) return "?"; [this.st.FA, this.st.FB] = [this.st.FB, this.st.FA]; return null; }
    if ((pre === "FA" || pre === "FB" || pre === "MD0") && this.ptt) return "?";
    if (pre === "AC00" && param === "2") return "?";
    if (pre in this.fn) { if (!this.o.stuck.includes(pre)) this.fn[pre] = param; return null; }
    if (pre in this.st) { this.st[pre] = param; return null; }
    return "?";
  }
}

function fakeAudio(rig, opts) {
  const o = Object.assign({ input: true, output: true, db: -62 }, opts || {});
  return {
    hasInput: () => o.input, hasOutput: () => o.output,
    async measureInput() { return o.db; },
    async startTone() { rig.toneOn = true; },
    stopTone() { rig.toneOn = false; },
  };
}

module.exports = { FakeYaesu, fakeAudio, ya };
