// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Faux Kenwood TS-890S (commandes PC ASCII) pour les tests d'openRemoteTRX-Autotest : une écriture ne répond rien
   (« ?; » si refusée) ; l'état d'émission ne se LIT pas, il n'est annoncé (« TX0; » / « RX; ») que si l'information
   automatique (AI) est en marche, comme le dit le manuel. Options pour les pannes. */
"use strict";
const path = require("path");
const kw = require(path.join(__dirname, "..", "..", "autotest", "web", "kenwood.js"));

const PREFIXES = ["OM0", "NB1", "NL1", "PR0", "ID", "FA", "FB", "FR", "PC", "SM", "RM", "AI", "NR", "NT", "BC", "RA", "PA",
                  "GC", "RT", "XT", "TB", "AC", "TX", "RX", "EC", "VX", "EX", "PS"];
const CARRIER = new Set(["4", "5", "6"]);

class FakeKenwood {
  constructor(opts) {
    this.o = Object.assign({ baud: 115200, ident: "024", silent: [], ng: [], ngWrite: [], stuck: [], alreadyTx: false,
                             noAi: false, delay: 2, swrDots: 2, alcDots: 20, ai: "0" }, opts || {});
    this.st = { FA: "00007074000", FB: "00014074000", FR: "0", OM0: "1", PC: "100", AI: this.o.ai };
    this.rm = { 1: false, 2: false };
    this.fn = Object.assign({ RA: "0", PA: "1", GC: "2", NB1: "0", NL1: "005", NR: "1", NT: "0", BC: "0", PR0: "0", RT: "0", XT: "0", TB: "0", AC: "100" }, this.o.fn);
    this.initialFn = JSON.stringify(this.fn); this.toneOn = false; this.txLog = []; this.writes = [];
    this.tx = !!this.o.alreadyTx; this.txSince = this.tx ? Date.now() : null; this.buf = ""; this.emit = () => {};
  }
  transport(baud) {
    const rig = this; let cb = () => {}; let open = true;
    const send = s => setTimeout(() => cb(Uint8Array.from(Buffer.from(s, "latin1"))), rig.o.delay);
    return {
      onData(f) { cb = f; rig.emit = send; },
      async write(bytes) {
        if (!open) throw new Error("port fermé");
        if (baud !== rig.o.baud) { setTimeout(() => cb(Uint8Array.from([0x00, 0x7F, 0x13])), 0); return; }
        rig.buf += Buffer.from(bytes).toString("latin1");
        let i;
        while ((i = rig.buf.indexOf(";")) >= 0) {
          const c = rig.buf.slice(0, i); rig.buf = rig.buf.slice(i + 1);
          const reply = rig.handle(c);
          if (reply) send(reply);
        }
      },
      async close() { open = false; },
    };
  }
  key(on, how) {
    const now = Date.now();
    if (on && !this.tx) this.txSince = now;
    if (!on && this.tx) { this.txLog.push(now - this.txSince); this.txSince = null; }
    this.tx = on;
    if (this.st.AI !== "0" && !this.o.noAi) this.emit(on ? "TX" + how + ";" : "RX;");
  }
  maxTx() { return Math.max(0, ...this.txLog, this.tx ? Date.now() - this.txSince : 0); }
  handle(c) {
    const pre = PREFIXES.find(p => c.startsWith(p));
    if (!pre) return "?;";
    const param = c.slice(pre.length);
    const isRead = param === "" && !["RX", "EC", "TX"].includes(pre);
    this.writes.push({ cmd: c, tx: this.tx });
    if (this.o.silent.includes(pre)) return null;
    if (this.o.ng.includes(pre)) return "?;";
    const data = ["C", "D", "E", "F"].includes(this.st.OM0);
    if (isRead) {
      if (pre === "ID") return "ID" + this.o.ident + ";";
      if (pre === "SM") {
        const mod = this.tx && (CARRIER.has(this.st.OM0) || (data && this.toneOn));
        const dots = this.tx ? (mod ? Math.round(Number(this.st.PC) / 150 * 70) : 0) : 15;
        return "SM" + String(dots).padStart(4, "0") + ";";
      }
      if (pre === "RM") {
        let out = "";
        if (this.rm[1]) out += "RM1" + String(this.tx && data && this.toneOn ? this.o.alcDots : 0).padStart(4, "0") + ";";
        if (this.rm[2]) out += "RM2" + String(this.tx ? this.o.swrDots : 0).padStart(4, "0") + ";";
        return out || null;
      }
      if (pre in this.fn) return pre + this.fn[pre] + ";";
      if (pre in this.st) return pre + this.st[pre] + ";";
      return "?;";
    }
    if (this.o.ngWrite.includes(pre)) return "?;";
    if (["VX", "EX", "PS"].includes(pre)) return null;
    if (pre === "TX") { this.key(true, param || "0"); return null; }
    if (pre === "RX") { this.key(false); return null; }
    if (pre === "EC") { if (this.tx) return "?;"; [this.st.FA, this.st.FB] = [this.st.FB, this.st.FA]; return null; }
    if (pre === "RM") { this.rm[param[0]] = param[1] === "1"; return null; }
    if ((pre === "FA" || pre === "FB" || pre === "OM0") && this.tx) return "?;";
    if (pre === "AC" && param[2] === "1") return "?;";
    if (pre in this.fn) { if (!this.o.stuck.includes(pre)) this.fn[pre] = param; return null; }
    if (pre in this.st) { this.st[pre] = param; return null; }
    return "?;";
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

module.exports = { FakeKenwood, fakeAudio, kw };
