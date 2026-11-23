// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, protocole CAT des Yaesu « nouveaux » (ASCII terminé par « ; », manuel FTDX10 CAT 2308-F ;
   docs/prequalif-web-cahier-des-charges.md § 6.2). Même interface que la liaison CI-V (civ.js) : le déroulé des essais
   (runner.js) ne connaît pas la marque. Une ÉCRITURE n'a pas de réponse chez Yaesu (sauf « ?; » = refusée) : chaque
   écriture est suivie de la lecture de la même commande, qui la confirme. Aucune commande hors de la liste fermée.
   Poste lent (piège du FTDX10) : délais longs, une lecture trop lente rend « absente », jamais une panne. */
(function (root) {
  "use strict";

  // Lectures permises (préfixe envoyé « XX; » ou « XX0; »).
  const READ = new Set(["ID", "FA", "FB", "VS", "MD0", "PC", "SM0", "RM4", "RM5", "RM6", "TX",
                        "NB0", "NL0", "NR0", "RL0", "RA0", "PA0", "BC0", "PR0", "RT", "ST", "AC"]);
  // Écritures permises et forme exacte du paramètre. JAMAIS : VX (VOX), EX (menus), PS (alimentation), MX (MOX),
  // AC002 (lancer l'accord = émission), ST2 (split + 5 kHz).
  const WRITE = {
    FA: /^\d{9}$/, FB: /^\d{9}$/, MD0: /^[1-9A-F]$/, PC: /^\d{3}$/, TX: /^[01]$/,
    NB0: /^[01]$/, NL0: /^\d{3}$/, NR0: /^[01]$/, RL0: /^\d{2}$/, RA0: /^[0-3]$/, PA0: /^[0-2]$/, BC0: /^[01]$/,
    PR0: /^[12]$/, RT: /^[01]$/, ST: /^[01]$/, AC00: /^[01]$/, SV: /^$/,
  };
  function frame(cmd, param) {
    if (param == null) { if (!READ.has(cmd)) throw new Error("commande hors de la liste fermée : " + cmd); return cmd + ";"; }
    const rule = WRITE[cmd];
    if (!rule || !rule.test(String(param))) throw new Error("commande hors de la liste fermée : " + cmd + param);
    return cmd + param + ";";
  }

  const MODES = { 1: "LSB", 2: "USB", 3: "CW-U", 4: "FM", 5: "AM", 6: "RTTY-L", 7: "CW-L", 8: "DATA-L", 9: "RTTY-U",
                  A: "DATA-FM", B: "FM-N", C: "DATA-U", D: "AM-N", E: "PSK", F: "DATA-FM-N" };
  const MODE_CODES = Object.fromEntries(Object.entries(MODES).map(([k, v]) => [v, k]));
  const DATA_OF = { 1: "8", 2: "C", 4: "A" };                 // LSB -> DATA-L, USB -> DATA-U, FM -> DATA-FM
  const BASE_OF = { 8: "1", C: "2", A: "4" };

  function interp(table, x) {
    if (x <= table[0][0]) return table[0][1];
    for (let i = 1; i < table.length; i++) { const [a, va] = table[i - 1], [b, vb] = table[i]; if (x <= b) return va + (vb - va) * (x - a) / (b - a); }
    return table[table.length - 1][1];
  }
  // Échelles des mesures (0-255) : d'après Hamlib (famille FTDX10 / FTDX101), À CONFIRMER sur le vrai poste.
  const PO_TABLE = [[0, 0], [10, 0.8], [50, 8], [100, 26], [150, 54], [200, 92], [250, 140], [255, 145]];   // % de la puissance max
  const SWR_TABLE = [[0, 1.0], [26, 1.2], [52, 1.5], [89, 2.0], [126, 3.0], [173, 4.0], [236, 5.0], [255, 9.9]];
  const scale = {
    sText: raw => raw == null ? "—" : raw <= 130 ? "S" + Math.round(raw * 9 / 130) : "S9+" + Math.round((raw - 130) * 60 / 125) + " dB",
    poPercent: raw => interp(PO_TABLE, raw),
    swrValue: raw => interp(SWR_TABLE, raw),
    alcPercent: raw => Math.min(100, raw / 255 * 100),
  };

  /* Fonctions essayées en R9 (lue, changée, relue, remise, relue). `read` = commande de lecture, `pre` = début de la
     réponse et de l'écriture, `w` = nombre de chiffres de la valeur. */
  const FUNCS = [
    { code: "ATT", label: "Atténuateur", read: "RA0", pre: "RA0", w: 1, values: ["0", "1", "2", "3"] },
    { code: "P.AMP", label: "Préampli (IPO / AMP 1 / AMP 2)", read: "PA0", pre: "PA0", w: 1, values: ["0", "1", "2"] },
    { code: "NB", label: "Noise blanker", read: "NB0", pre: "NB0", w: 1, values: ["0", "1"] },
    { code: "NB niv.", label: "Niveau NB", read: "NL0", pre: "NL0", w: 3, range: [0, 10] },
    { code: "NR", label: "Réduction de bruit", read: "NR0", pre: "NR0", w: 1, values: ["0", "1"] },
    { code: "NR niv.", label: "Niveau NR", read: "RL0", pre: "RL0", w: 2, range: [1, 15] },
    { code: "ANF", label: "Notch automatique", read: "BC0", pre: "BC0", w: 1, values: ["0", "1"] },
    { code: "COMP", label: "Processeur de parole", read: "PR0", pre: "PR0", w: 1, values: ["1", "2"], slow: true },
    { code: "RIT", label: "Clarifier (RIT)", read: "RT", pre: "RT", w: 1, values: ["0", "1"] },
    { code: "SPLIT", label: "Split", read: "ST", pre: "ST", w: 1, values: ["0", "1"] },
  ];

  class YaesuLink {
    constructor(transport, model, clock) {
      this.t = transport; this.model = model || null; this.clock = clock || (() => Date.now());
      this.family = "yaesu"; this.dataLabel = "DATA-U"; this.scale = scale; this.funcs = FUNCS;
      this.buf = ""; this.trace = []; this.waiter = null; this.queue = Promise.resolve(); this.t0 = this.clock();
      this.cur = "FA";
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
        const w = this.waiter;
        if (!w) continue;
        if (tok === "?") { this.waiter = null; clearTimeout(w.timer); w.resolve({ ng: true }); }
        else if (tok.startsWith(w.prefix)) { this.waiter = null; clearTimeout(w.timer); w.resolve({ ok: true, value: tok.slice(w.prefix.length) }); }
      }
      if (this.buf.length > 256) this.buf = "";
    }
    async _write(text) { this._log("tx", text); await this.t.write(new TextEncoder().encode(text)); }
    // Envoi + attente de la réponse qui commence par `prefix` (« ?; » = refusée, rien = délai dépassé).
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
    // Écriture puis lecture de la même commande (la confirme) ; « ?; » avant la lecture = écriture refusée.
    set(cmd, param, readCmd, prefix, timeout) { return this.request(frame(cmd, param) + frame(readCmd || cmd), prefix || cmd, timeout); }

    async readId() { const r = await this.read("ID", "ID", 800); return r.ok && /^\d{4}$/.test(r.value) ? { id: r.value, ms: r.ms } : null; }
    async init() { const r = await this.read("VS"); this.cur = r.ok && r.value === "1" ? "FB" : "FA"; }
    async readFreq() { const r = await this.read(this.cur); return r.ok && /^\d{9}$/.test(r.value) ? Number(r.value) : null; }
    async setFreq(hz) { const r = await this.set(this.cur, String(Math.round(hz)).padStart(9, "0")); return !!r.ok; }
    async readMode() { const r = await this.read("MD0"); const c = r.ok ? r.value.slice(0, 1) : null; return c && MODES[c] ? { code: c, name: MODES[c], filter: 0 } : null; }
    async setMode(code) { const r = await this.set("MD0", code); return !!r.ok && r.value.slice(0, 1) === code; }
    modeCode(name) { return MODE_CODES[name]; }
    async readDataMode() { const m = await this.readMode(); return m ? { on: BASE_OF[m.code] ? 1 : 0, filter: 0 } : null; }
    async setDataMode(on) {
      const m = await this.readMode(); if (!m) return false;
      if (on) { const d = DATA_OF[m.code]; return d ? this.setMode(d) : false; }
      const b = BASE_OF[m.code]; return b ? this.setMode(b) : true;
    }
    async meter(kind) {
      const cmd = { s: "SM0", po: "RM5", swr: "RM6", alc: "RM4", power: "PC" }[kind];
      const r = await this.read(cmd);
      if (!r.ok || !/^\d{3}/.test(r.value)) return null;
      return Number(r.value.slice(0, 3));
    }
    powerRaw(pct) { return Math.max(5, Math.min(this.maxW, Math.round(this.maxW * pct / 100))); }
    powerPct(raw) { return raw / this.maxW * 100; }
    powerClose(a, b) { return a != null && b != null && Math.abs(a - b) <= 1; }
    async setPower(raw) { const r = await this.set("PC", String(raw).padStart(3, "0")); return !!r.ok; }
    async readPtt() { const r = await this.read("TX", "TX", 800); return r.ok && /^[0-2]$/.test(r.value) ? r.value !== "0" : null; }
    async setPtt(on) { const r = await this.set("TX", on ? "1" : "0", "TX", "TX", 800); return !!r.ok; }
    // Retour en réception en tête de file (coupure d'urgence), sans attendre de réponse.
    async pttOffNow() { await this._write(frame("TX", "0")); }

    // Fonctions (R9) : valeurs en texte.
    async fnRead(f) { const r = await this.read(f.read, f.pre, f.slow ? 3500 : 1500); return r.ok && r.value.length >= f.w ? r.value.slice(0, f.w) : null; }
    async fnWrite(f, v) { const r = await this.set(f.pre, v, f.read, f.pre, f.slow ? 3500 : 1500); return { ok: !!r.ok, ng: !!r.ng }; }
    fnOther(f, v0) {
      if (f.range) { const [lo, hi] = f.range, n = Number(v0), d = Math.max(1, Math.round((hi - lo) / 3)); const x = n + d <= hi ? n + d : n - d; return String(Math.max(lo, x)).padStart(f.w, "0"); }
      return f.values.find(x => x !== v0) || f.values[0];
    }
    fnNear() { return false; }
    fnShow(v) { return v; }
    // VFO A / B : l'autre VFO lu, échange par SV.
    async vfoOther() { const r = await this.read(this.cur === "FA" ? "FB" : "FA"); return r.ok && /^\d{9}$/.test(r.value) ? Number(r.value) : null; }
    async vfoSwap() { const r = await this.set("SV", "", this.cur, this.cur); return { ok: !!r.ok, ng: !!r.ng }; }
  }

  /* Détection : vitesses essayées (FTDX10 : 38400 d'usine), identité « ID; » (FTDX10 = 0761). */
  async function detect({ openAt, model, bauds, onTry, byId }) {
    for (const baud of bauds) {
      if (onTry) onTry(baud);
      let tr;
      try { tr = await openAt(baud); } catch (e) { return { error: "port", detail: String(e && e.message || e) }; }
      const link = new YaesuLink(tr, model);
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

  const api = { READ, WRITE, MODES, MODE_CODES, FUNCS, frame, scale, YaesuLink, detect };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtYaesu = api;
})(typeof window !== "undefined" ? window : globalThis);
