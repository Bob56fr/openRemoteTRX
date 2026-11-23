// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, protocole des Kenwood récents (ASCII terminé par « ; », manuel « TS-890S PC Control Command
   Reference Guide » rev. 1 ; docs/prequalif-web-cahier-des-charges.md § 6.2). Même interface que civ.js et yaesu.js.
   Une écriture n'a pas de réponse (« ?; » si refusée) : chaque écriture est suivie de la lecture qui la confirme.
   PARTICULARITÉ : le manuel ne donne AUCUNE commande pour LIRE l'état d'émission ; « TX » / « RX » ne sont annoncés que
   si l'information automatique (AI) est en marche. La page met donc AI2 (non sauvegardé dans le poste) pendant l'essai,
   suit ces annonces et remet l'AI d'origine à la fin. Sans annonces, le PTT est « illisible » : aucune émission. */
(function (root) {
  "use strict";

  const READ = new Set(["ID", "FA", "FB", "FR", "OM0", "PC", "SM", "RM", "AI",
                        "NB1", "NL1", "NR", "NT", "BC", "RA", "PA", "GC", "PR0", "RT", "XT", "TB", "AC"]);
  // Écritures permises. JAMAIS : TX2 (TX TUNE), VX (VOX), EX (menus), PS (alimentation), AC avec P3 = 1 (accord =
  // émission), AI4 (information automatique sauvegardée dans le poste).
  const WRITE = {
    FA: /^\d{11}$/, FB: /^\d{11}$/, OM0: /^[1-79A-F]$/, PC: /^\d{3}$/, TX: /^[01]$/, RX: /^$/, EC: /^$/, AI: /^[02]$/,
    RM: /^[12][01]$/, NB1: /^[01]$/, NL1: /^\d{3}$/, NR: /^[0-2]$/, NT: /^[01]$/, BC: /^[0-2]$/, RA: /^[0-3]$/,
    PA: /^[0-2]$/, GC: /^[0-3]$/, PR0: /^[01]$/, RT: /^[01]$/, XT: /^[01]$/, TB: /^[01]$/, AC: /^1[01]0$/,
  };
  function frame(cmd, param) {
    if (param == null) { if (!READ.has(cmd)) throw new Error("commande hors de la liste fermée : " + cmd); return cmd + ";"; }
    const rule = WRITE[cmd];
    if (!rule || !rule.test(String(param))) throw new Error("commande hors de la liste fermée : " + cmd + param);
    return cmd + param + ";";
  }

  const MODES = { 1: "LSB", 2: "USB", 3: "CW", 4: "FM", 5: "AM", 6: "FSK", 7: "CW-R", 9: "FSK-R", A: "PSK", B: "PSK-R",
                  C: "LSB-D", D: "USB-D", E: "FM-D", F: "AM-D" };
  const MODE_CODES = Object.fromEntries(Object.entries(MODES).map(([k, v]) => [v, k]));
  MODE_CODES.RTTY = "6";                                           // FSK = RTTY pour le déroulé des essais
  const DATA_OF = { 1: "C", 2: "D", 4: "E", 5: "F" };
  const BASE_OF = { C: "1", D: "2", E: "4", F: "5" };

  function interp(table, x) {
    if (x <= table[0][0]) return table[0][1];
    for (let i = 1; i < table.length; i++) { const [a, va] = table[i - 1], [b, vb] = table[i]; if (x <= b) return va + (vb - va) * (x - a) / (b - a); }
    return table[table.length - 1][1];
  }
  // Mesures en « points » de l'afficheur (0-70). Échelles À CONFIRMER sur le vrai poste (le manuel ne les donne pas).
  const SWR_TABLE = [[0, 1.0], [11, 1.5], [21, 2.0], [33, 3.0], [70, 9.9]];
  const scale = {
    sText: raw => raw == null ? "—" : raw <= 35 ? "S" + Math.round(raw * 9 / 35) : "S9+" + Math.round((raw - 35) * 60 / 35) + " dB",
    poPercent: raw => raw / 70 * 150,                               // échelle Po de 0 à 150 W (à confirmer)
    swrValue: raw => interp(SWR_TABLE, raw),
    alcPercent: raw => Math.min(100, raw / 70 * 100),
  };

  // Fonctions essayées en R9. `w` = chiffres de la valeur ; le coupleur est traité à part (seul P2 compte).
  const FUNCS = [
    { code: "ATT", label: "Atténuateur", cmd: "RA", w: 1, values: ["0", "1", "2", "3"] },
    { code: "P.AMP", label: "Préampli", cmd: "PA", w: 1, values: ["0", "1", "2"] },
    { code: "AGC", label: "AGC", cmd: "GC", w: 1, values: ["1", "2", "3"] },
    { code: "NB", label: "Noise blanker 1", cmd: "NB1", w: 1, values: ["0", "1"] },
    { code: "NB niv.", label: "Niveau NB 1", cmd: "NL1", w: 3, range: [1, 20] },
    { code: "NR", label: "Réduction de bruit (NR1 / NR2)", cmd: "NR", w: 1, values: ["0", "1", "2"] },
    { code: "NOTCH", label: "Notch", cmd: "NT", w: 1, values: ["0", "1"] },
    { code: "BC", label: "Beat cancel", cmd: "BC", w: 1, values: ["0", "1", "2"] },
    { code: "COMP", label: "Processeur de parole", cmd: "PR0", w: 1, values: ["0", "1"] },
    { code: "RIT", label: "RIT", cmd: "RT", w: 1, values: ["0", "1"] },
    { code: "XIT", label: "XIT", cmd: "XT", w: 1, values: ["0", "1"] },
    { code: "SPLIT", label: "Split", cmd: "TB", w: 1, values: ["0", "1"] },
  ];

  class KenwoodLink {
    constructor(transport, model, clock) {
      this.t = transport; this.model = model || null; this.clock = clock || (() => Date.now());
      this.family = "kenwood"; this.dataLabel = "USB-D"; this.scale = scale; this.funcs = FUNCS;
      this.buf = ""; this.trace = []; this.waiter = null; this.queue = Promise.resolve(); this.t0 = this.clock();
      this.cur = "FA"; this.mode = null; this.ptt = null; this.pttTracked = true; this.aiOrig = null; this.pttWaiters = [];
      transport.onData(bytes => this._rx(bytes));
    }
    get maxW() { return this.model && this.model.maxW || 100; }
    _log(d, h) { this.trace.push({ t: this.clock() - this.t0, d, h }); }
    _rx(bytes) {
      this.buf += String.fromCharCode(...bytes);
      let i;
      while ((i = this.buf.indexOf(";")) >= 0) {
        const tok = this.buf.slice(0, i).replace(/[^\x20-\x7E]/g, "").trim(); this.buf = this.buf.slice(i + 1);
        if (!tok) continue;
        this._log("rx", tok + ";");
        // Annonces d'émission / réception (AI en marche).
        if (/^TX[0-2]$/.test(tok) || tok === "RX") { this.ptt = tok !== "RX"; this.pttWaiters.splice(0).forEach(f => f()); }
        const w = this.waiter;
        if (!w) continue;
        if (tok === "?" || tok === "E" || tok === "O") { this.waiter = null; clearTimeout(w.timer); w.resolve({ ng: true }); }
        else if (tok.startsWith(w.prefix)) { this.waiter = null; clearTimeout(w.timer); w.resolve({ ok: true, value: tok.slice(w.prefix.length) }); }
      }
      if (this.buf.length > 512) this.buf = "";
    }
    async _write(text) { this._log("tx", text); await this.t.write(new TextEncoder().encode(text)); }
    request(text, prefix, timeout) {
      const run = () => new Promise(resolve => {
        const t0 = this.clock();
        const timer = setTimeout(() => { if (this.waiter && this.waiter.timer === timer) this.waiter = null; resolve({ timeout: true, ms: this.clock() - t0 }); }, timeout || 1500);
        this.waiter = { prefix, timer, resolve: r => resolve(Object.assign({ ms: this.clock() - t0 }, r)) };
        this._write(text).catch(() => { clearTimeout(timer); this.waiter = null; resolve({ error: true, ms: 0 }); });
      });
      const p = this.queue.then(run, run);
      this.queue = p.then(() => undefined, () => undefined);
      return p;
    }
    read(cmd, prefix, timeout) { return this.request(frame(cmd), prefix || cmd, timeout); }
    set(cmd, param, readCmd, prefix, timeout) { return this.request(frame(cmd, param) + frame(readCmd || cmd), prefix || readCmd || cmd, timeout); }

    async readId() { const r = await this.read("ID", "ID", 800); return r.ok && /^\d{3}$/.test(r.value) ? { id: r.value, ms: r.ms } : null; }
    // Mise en route : VFO de réception, AI2 pour suivre l'émission, lecture du TOS et de l'ALC.
    async init() {
      const fr = await this.read("FR"); this.cur = fr.ok && fr.value === "1" ? "FB" : "FA";
      const ai = await this.read("AI"); this.aiOrig = ai.ok ? ai.value : null;
      if (this.aiOrig === "2" || this.aiOrig === "4") this.ptt = false;
      else { const s = await this.set("AI", "2", "AI"); this.ptt = s.ok && s.value === "2" ? false : null; }
      await this.request(frame("RM", "11") + frame("RM", "21") + frame("ID"), "ID");
    }
    async finish() {
      try { await this.request(frame("RM", "10") + frame("RM", "20") + frame("ID"), "ID"); } catch (e) { /* rien */ }
      if (this.aiOrig === "0") { try { await this.set("AI", "0", "AI"); } catch (e) { /* rien */ } }
    }
    async readFreq() { const r = await this.read(this.cur); return r.ok && /^\d{11}$/.test(r.value) ? Number(r.value) : null; }
    async setFreq(hz) { const r = await this.set(this.cur, String(Math.round(hz)).padStart(11, "0")); return !!r.ok; }
    async readMode() { const r = await this.read("OM0"); const c = r.ok ? r.value.slice(0, 1) : null; if (c && MODES[c]) { this.mode = c; return { code: c, name: MODES[c], filter: 0 }; } return null; }
    async setMode(code) { const r = await this.set("OM0", code); const ok = !!r.ok && r.value.slice(0, 1) === code; if (ok) this.mode = code; return ok; }
    modeCode(name) { return MODE_CODES[name]; }
    async readDataMode() { const m = await this.readMode(); return m ? { on: BASE_OF[m.code] ? 1 : 0, filter: 0 } : null; }
    async setDataMode(on) {
      const m = await this.readMode(); if (!m) return false;
      if (on) { const d = DATA_OF[m.code]; return d ? this.setMode(d) : false; }
      const b = BASE_OF[m.code]; return b ? this.setMode(b) : true;
    }
    async meter(kind) {
      if (kind === "power") { const r = await this.read("PC"); return r.ok && /^\d{3}$/.test(r.value) ? Number(r.value) : null; }
      if (kind === "s" || kind === "po") {                         // SM : S-mètre en réception, puissance en émission
        if (kind === "po" && !this.ptt) return 0;
        const r = await this.read("SM"); return r.ok && /^\d{4}$/.test(r.value) ? Number(r.value) : null;
      }
      const r = await this.read("RM", kind === "swr" ? "RM2" : "RM1");
      return r.ok && /^\d{4}$/.test(r.value) ? Number(r.value) : null;
    }
    powerRaw(pct) { return Math.max(5, Math.min(this.maxW, Math.round(this.maxW * pct / 100))); }
    powerPct(raw) { return raw / this.maxW * 100; }
    powerClose(a, b) { return a != null && b != null && Math.abs(a - b) <= 1; }
    async setPower(raw) { const r = await this.set("PC", String(raw).padStart(3, "0")); return !!r.ok; }
    // État d'émission : suivi par les annonces (aucune commande de lecture dans le manuel).
    async readPtt() { await new Promise(r => setTimeout(r, 30)); return this.ptt; }
    _waitPtt(target, ms) {
      if (this.ptt === target) return Promise.resolve(true);
      return new Promise(resolve => {
        const t = setTimeout(() => resolve(this.ptt === target), ms);
        const check = () => { if (this.ptt === target) { clearTimeout(t); resolve(true); } else this.pttWaiters.push(check); };
        this.pttWaiters.push(check);
      });
    }
    // TX1 = DATA SEND (son par l'USB) en mode données, TX0 = SEND / PTT sinon.
    async setPtt(on) {
      if (on) { await this._write(frame("TX", BASE_OF[this.mode] ? "1" : "0")); return this._waitPtt(true, 800); }
      await this._write(frame("RX", "")); return this._waitPtt(false, 800);
    }
    async pttOffNow() { await this._write(frame("RX", "")); }

    async fnRead(f) {
      const r = await this.read(f.cmd, f.cmd);
      if (!r.ok || r.value.length < f.w) return null;
      return f.tuner ? r.value.slice(1, 2) : r.value.slice(0, f.w);
    }
    async fnWrite(f, v) {
      const r = await this.set(f.cmd, f.tuner ? "1" + v + "0" : v, f.cmd, f.cmd);
      return { ok: !!r.ok, ng: !!r.ng };
    }
    fnOther(f, v0) {
      if (f.range) { const [lo, hi] = f.range, n = Number(v0), d = Math.max(1, Math.round((hi - lo) / 3)); const x = n + d <= hi ? n + d : n - d; return String(Math.max(lo, x)).padStart(f.w, "0"); }
      return f.values.find(x => x !== v0) || f.values[0];
    }
    fnNear() { return false; }
    fnShow(v) { return v; }
    async vfoOther() { const r = await this.read(this.cur === "FA" ? "FB" : "FA"); return r.ok && /^\d{11}$/.test(r.value) ? Number(r.value) : null; }
    async vfoSwap() { const r = await this.set("EC", "", this.cur, this.cur); return { ok: !!r.ok, ng: !!r.ng }; }
  }

  async function detect({ openAt, model, bauds, onTry, byId }) {
    for (const baud of bauds) {
      if (onTry) onTry(baud);
      let tr;
      try { tr = await openAt(baud); } catch (e) { return { error: "port", detail: String(e && e.message || e) }; }
      const link = new KenwoodLink(tr, model);
      const id = await link.readId();
      if (id) {
        const guess = byId ? byId(id.id) : null;
        if (!model && guess) link.model = guess;
        await link.init();
        return { baud, addr: null, ident: id.id, transport: tr, link, idSupported: true, guess };
      }
      try { await tr.close(); } catch (e) { /* rien */ }
    }
    return { error: "silence" };
  }

  const api = { READ, WRITE, MODES, MODE_CODES, FUNCS, frame, scale, KenwoodLink, detect };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtKenwood = api;
})(typeof window !== "undefined" ? window : globalThis);
