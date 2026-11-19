// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, protocole CI-V d'Icom (docs/prequalif-web-cahier-des-charges.md § 6.1) : calculs PURS
   (trames, BCD, échelles des mesures) et liaison CivLink au-dessus d'un transport (Web Serial dans la page, faux poste
   dans les tests). Aucune commande hors de la liste fermée ci-dessous n'est jamais envoyée. */
(function (root) {
  "use strict";

  const CTRL = 0xE0;                                   // adresse du contrôleur (la page)
  const PREAMBLE = 0xFE, END = 0xFD, OK = 0xFB, NG = 0xFA, COLLISION = 0xFC;

  // Liste FERMÉE des commandes que la page peut envoyer (lecture ou écriture).
  const CMD = {
    ID: [0x19, 0x00],            // identité : adresse du poste
    READ_FREQ: [0x03],
    READ_MODE: [0x04],
    SET_FREQ: [0x05],
    SET_MODE: [0x06],
    RF_POWER: [0x14, 0x0A],      // puissance réglée, 0-255
    S_METER: [0x15, 0x02],
    PO_METER: [0x15, 0x11],
    SWR_METER: [0x15, 0x12],
    ALC_METER: [0x15, 0x13],
    PTT: [0x1C, 0x00],
    DATA_MODE: [0x1A, 0x06],
    // Sortie des données du spectre (01 = marche, 00 = arrêt) : lecture seule. Avec le pilote USB d'Icom (IC-7300MK2)
    // sous Windows, Chrome se fige tant qu'une lecture attend sur un port vide (essai du 2026-11-19) : un flux
    // continu du poste l'empêche d'attendre.
    SCOPE_OUT: [0x27, 0x11],
    // Fonctions de réception (essai R9 : lue, changée, relue, remise, relue). JAMAIS le VOX (16 46).
    ATT: [0x11],                 // atténuateur : 00 ou 20 (dB)
    PREAMP: [0x16, 0x02],        // P.AMP : 00, 01, 02
    AGC: [0x16, 0x12],           // 01 rapide, 02 moyen, 03 lent
    NB: [0x16, 0x22],
    NR: [0x16, 0x40],
    ANF: [0x16, 0x41],           // notch automatique
    COMP: [0x16, 0x44],          // compresseur (phonie)
    IPPLUS: [0x16, 0x65],        // IP+
    NR_LEVEL: [0x14, 0x06],
    NB_LEVEL: [0x14, 0x12],
    COMP_LEVEL: [0x14, 0x0E],
    SPLIT: [0x0F],               // 00 / 01
    RIT_ON: [0x21, 0x01],        // 00 / 01
    TUNER: [0x1C, 0x01],         // 00 / 01 seulement : 02 = lancer l'accord (émission) JAMAIS
    VFO_EXCH: [0x07, 0xB0],      // échange VFO A / B
    VFO_FREQ: [0x25],            // lecture : 00 VFO choisi, 01 l'autre (jamais d'écriture)
  };
  const ALLOWED = Object.values(CMD).map(c => c.join(","));
  // Données permises après certaines commandes (le reste : toute donnée). Une donnée hors liste = refus de la page.
  const DATA_RULES = {
    [CMD.TUNER.join(",")]: [[], [0x00], [0x01]],
    [CMD.VFO_EXCH.join(",")]: [[]],
    [CMD.VFO_FREQ.join(",")]: [[0x00], [0x01]],
    [CMD.SPLIT.join(",")]: [[], [0x00], [0x01]],
    [CMD.RIT_ON.join(",")]: [[], [0x00], [0x01]],
    [CMD.ATT.join(",")]: [[], [0x00], [0x20]],
  };

  const MODES = { 0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM", 0x06: "WFM",
                  0x07: "CW-R", 0x08: "RTTY-R", 0x17: "DV" };
  const MODE_CODES = Object.fromEntries(Object.entries(MODES).map(([k, v]) => [v, Number(k)]));

  function frame(addr, cmd, data) {
    const body = [...cmd, ...(data || [])], key = cmd.join(",");
    // La commande doit être EXACTEMENT une de la liste (avant : un préfixe de texte, « 3 » acceptait « 36 »).
    if (!ALLOWED.includes(key)) throw new Error("commande hors de la liste fermée : " + hex(body));
    const rule = DATA_RULES[key];
    if (rule && !rule.some(r => r.join(",") === (data || []).join(","))) throw new Error("donnée hors de la liste fermée : " + hex(body));
    return Uint8Array.from([PREAMBLE, PREAMBLE, addr, CTRL, ...body, END]);
  }

  function hex(bytes) { return Array.from(bytes, b => b.toString(16).padStart(2, "0").toUpperCase()).join(" "); }

  /* Découpe un flux d'octets en trames {to, from, payload}. Garde le reste incomplet. Une trame avec FC (collision)
     est jetée. */
  class Parser {
    constructor() { this.buf = []; }
    push(bytes) {
      const out = [];
      for (const b of bytes) this.buf.push(b);
      for (;;) {
        let s = -1;
        for (let i = 0; i + 1 < this.buf.length; i++) if (this.buf[i] === PREAMBLE && this.buf[i + 1] === PREAMBLE) { s = i; break; }
        if (s < 0) { if (this.buf.length > 1) this.buf = this.buf.slice(-1); break; }
        let p = s + 2;
        while (p < this.buf.length && this.buf[p] === PREAMBLE) p++;          // préambules en trop
        const e = this.buf.indexOf(END, p);
        if (e < 0) { this.buf = this.buf.slice(s); if (this.buf.length > 64) this.buf = []; break; }
        const raw = this.buf.slice(p, e);
        this.buf = this.buf.slice(e + 1);
        if (raw.length < 3 || raw.includes(COLLISION)) continue;
        out.push({ to: raw[0], from: raw[1], payload: raw.slice(2) });
      }
      return out;
    }
  }

  // Fréquence : 5 octets BCD, le moins significatif d'abord (Hz).
  function decodeFreq(bytes) {
    let f = 0, m = 1;
    for (const b of bytes) { f += ((b & 0x0F) + 10 * (b >> 4)) * m; m *= 100; }
    return f;
  }
  function encodeFreq(hz) {
    const out = []; let v = Math.round(hz);
    for (let i = 0; i < 5; i++) { const two = v % 100; out.push(((Math.floor(two / 10)) << 4) | (two % 10)); v = Math.floor(v / 100); }
    return out;
  }
  // Niveaux : 2 octets BCD, 0000 à 0255.
  function decodeLevel(bytes) {
    if (bytes.length < 2) return null;
    const d = n => (n >> 4) * 10 + (n & 0x0F);
    return d(bytes[0]) * 100 + d(bytes[1]);
  }
  function encodeLevel(v) {
    v = Math.max(0, Math.min(255, Math.round(v)));
    const hi = Math.floor(v / 100), lo = v % 100;
    return [hi, (Math.floor(lo / 10) << 4) | (lo % 10)];
  }

  function interp(table, x) {
    if (x <= table[0][0]) return table[0][1];
    for (let i = 1; i < table.length; i++) {
      const [a, va] = table[i - 1], [b, vb] = table[i];
      if (x <= b) return va + (vb - va) * (x - a) / (b - a);
    }
    return table[table.length - 1][1];
  }
  // Échelles des Icom récents (mêmes valeurs brutes pour l'IC-7300 et l'IC-705, en % de la puissance maximale) :
  // à confirmer poste par poste (champ `verifie` de la table des modèles).
  const PO_TABLE = [[0, 0], [21, 5], [43, 10], [65, 15], [83, 20], [95, 25], [105, 30], [114, 35], [124, 40], [143, 50], [183, 75], [213, 100], [255, 120]];
  const SWR_TABLE = [[0, 1.0], [48, 1.5], [80, 2.0], [120, 3.0], [240, 6.0], [255, 9.9]];
  const poPercent = raw => interp(PO_TABLE, raw);
  const swrValue = raw => interp(SWR_TABLE, raw);
  const alcPercent = raw => Math.min(100, raw / 240 * 100);       // 0-120 = zone ALC du constructeur = 0-50 %
  function sText(raw) {
    if (raw == null) return "—";
    if (raw <= 120) return "S" + Math.round(raw / (120 / 9));
    return "S9+" + Math.round((raw - 120) * 60 / 121) + " dB";
  }

  /* Liaison : une requête à la fois, réponse reconnue par la commande, NG = refus, silence = délai dépassé (un poste
     qui ne gère pas une commande peut ne rien répondre : jamais une panne de câble). sendNow() passe DEVANT la file
     (coupure d'urgence). Toute trame envoyée et reçue est tracée. */
  class CivLink {
    constructor(transport, addr, clock) {
      this.t = transport; this.addr = addr; this.clock = clock || (() => Date.now());
      this.parser = new Parser(); this.trace = []; this.waiter = null; this.queue = Promise.resolve();
      this.t0 = this.clock();
      transport.onData(bytes => this._rx(bytes));
    }
    _log(dir, bytes) { this.trace.push({ t: this.clock() - this.t0, d: dir, h: hex(bytes) }); }
    _rx(bytes) {
      this._log("rx", bytes);
      for (const f of this.parser.push(bytes)) {
        if (f.from === CTRL) continue;                         // écho de nos propres trames
        if (f.to !== CTRL) continue;                           // émis pour tous (transceive) : ignoré
        if (this.addr != null && this.addr !== 0x00 && f.from !== this.addr) continue;   // 00 = question à tous
        if (this.waiter && this.waiter.match(f)) { const w = this.waiter; this.waiter = null; clearTimeout(w.timer); w.resolve(w.result(f)); }
      }
    }
    async sendNow(cmd, data) {
      const fr = frame(this.addr, cmd, data); this._log("tx", fr); await this.t.write(fr);
    }
    request(cmd, data, opts) {
      const o = Object.assign({ timeout: 400, read: true }, opts || {});
      const run = () => new Promise(resolve => {
        const fr = frame(this.addr, cmd, data);
        const started = this.clock();
        const match = f => f.payload[0] === NG || f.payload[0] === OK ||
          cmd.every((c, i) => f.payload[i] === c);
        const result = f => {
          const ms = this.clock() - started;
          if (f.payload[0] === NG) return { ng: true, ms };
          if (f.payload[0] === OK) return { ok: true, ms, data: [] };
          return { ok: true, ms, data: f.payload.slice(cmd.length), from: f.from };
        };
        const timer = setTimeout(() => { if (this.waiter && this.waiter.timer === timer) this.waiter = null; resolve({ timeout: true, ms: this.clock() - started }); }, o.timeout);
        this.waiter = { match, result, resolve, timer };
        this._log("tx", fr);
        Promise.resolve(this.t.write(fr)).catch(() => { clearTimeout(timer); this.waiter = null; resolve({ error: true, ms: 0 }); });
      });
      const p = this.queue.then(run, run);
      this.queue = p.then(() => undefined, () => undefined);
      return p;
    }
    // Lectures et écritures nommées
    async readId() { const r = await this.request(CMD.ID, [], { timeout: 300 }); return r.ok && r.data.length ? { addr: r.data[0], from: r.from, ms: r.ms } : null; }
    async readFreq() { const r = await this.request(CMD.READ_FREQ); return r.ok && r.data.length >= 5 ? decodeFreq(r.data.slice(0, 5)) : null; }
    async readMode() { const r = await this.request(CMD.READ_MODE); return r.ok && r.data.length >= 1 ? { code: r.data[0], name: MODES[r.data[0]] || ("0x" + r.data[0].toString(16)), filter: r.data[1] || 1 } : null; }
    async readDataMode() { const r = await this.request(CMD.DATA_MODE); return r.ok && r.data.length >= 1 ? { on: r.data[0], filter: r.data[1] || 0 } : null; }
    async level(cmd) { const r = await this.request(cmd); return r.ok ? decodeLevel(r.data) : null; }
    async readPtt() { const r = await this.request(CMD.PTT, [], { timeout: 300 }); return r.ok && r.data.length ? r.data[0] === 1 : null; }
    async setFreq(hz) { const r = await this.request(CMD.SET_FREQ, encodeFreq(hz)); return !!r.ok; }
    async setMode(code, filter) { const r = await this.request(CMD.SET_MODE, [code, filter || 1]); return !!r.ok; }
    async setDataMode(on, filter) { const r = await this.request(CMD.DATA_MODE, [on, on ? (filter || 1) : 0]); return !!r.ok; }
    async setPower(raw) { const r = await this.request(CMD.RF_POWER, encodeLevel(raw)); return !!r.ok; }
    // Lecture / écriture génériques (essai R9) : { ok, data } / { ng } / { timeout }.
    async readRaw(cmd) { return this.request(cmd, [], { timeout: 300 }); }
    async writeRaw(cmd, data) { return this.request(cmd, data, { timeout: 300 }); }
    async setPtt(on) { const r = await this.request(CMD.PTT, [on ? 1 : 0], { timeout: 300 }); return !!r.ok; }

    // ---- Interface commune aux familles (yaesu.js a la même) : le déroulé des essais ne connaît pas la marque.
    get family() { return "icom"; }
    get dataLabel() { return "USB-D"; }
    get scale() { return SCALE; }
    get funcs() { return FUNCS; }
    modeCode(name) { return MODE_CODES[name]; }
    async meter(kind) { return this.level({ s: CMD.S_METER, po: CMD.PO_METER, swr: CMD.SWR_METER, alc: CMD.ALC_METER, power: CMD.RF_POWER }[kind]); }
    powerRaw(pct) { return Math.round(255 * pct / 100); }
    powerPct(raw) { return raw / 2.55; }
    powerClose(a, b) { return a != null && b != null && Math.abs(a - b) <= 2; }
    // Retour en réception en tête de file (coupure d'urgence).
    async pttOffNow() { await this.sendNow(CMD.PTT, [0]); }
    // Fonctions (R9) : valeurs en hexadécimal (« 01 94 »).
    async fnRead(f) {
      const r = await this.readRaw(f.cmd);
      if (!r.ok || !r.data || !r.data.length) return null;
      return hex(f.level ? r.data.slice(0, 2) : r.data.slice(0, 1));
    }
    async fnWrite(f, v) { const r = await this.writeRaw(f.cmd, unhex(v)); return { ok: !!r.ok, ng: !!r.ng }; }
    fnOther(f, v0) {
      const b = unhex(v0);
      if (f.level) { const n = decodeLevel(b); return hex(encodeLevel(n >= 128 ? n - 51 : n + 51)); }
      const other = f.values.find(x => x !== b[0]);
      return hex([other == null ? f.values[0] : other]);
    }
    // Un niveau est arrondi au cran du poste (IC-7300MK2 : NR écrit 123 relu 120, COMP 155 relu 151) : écart accepté
    // jusqu'à un demi-cran du réglage le plus grossier (11 crans : 255 / 10 / 2 ≈ 13).
    fnNear(f, r1, v1) { return !!(f.level && r1 && v1 && Math.abs(decodeLevel(unhex(r1)) - decodeLevel(unhex(v1))) <= 13); }
    fnShow(v) { return v ? String(decodeLevel(unhex(v))) : v; }
    async vfoOther() {
      const r = await this.request(CMD.VFO_FREQ, [0x01], { timeout: 300 });
      return r.ok && r.data.length >= 6 ? decodeFreq(r.data.slice(1, 6)) : null;
    }
    async vfoSwap() { const r = await this.writeRaw(CMD.VFO_EXCH, []); return { ok: !!r.ok, ng: !!r.ng }; }
  }

  /* Fonctions essayées en R9, SANS émission : lue, changée, relue, remise, relue. Le VOX n'y est JAMAIS. */
  const FUNCS = [
    { code: "ATT", label: "Atténuateur", cmd: CMD.ATT, values: [0x00, 0x20] },
    { code: "P.AMP", label: "Préampli", cmd: CMD.PREAMP, values: [0x00, 0x01, 0x02] },
    { code: "IP+", label: "IP+", cmd: CMD.IPPLUS, values: [0x00, 0x01] },
    { code: "AGC", label: "AGC", cmd: CMD.AGC, values: [0x01, 0x02, 0x03] },
    { code: "NB", label: "Noise blanker", cmd: CMD.NB, values: [0x00, 0x01] },
    { code: "NB niv.", label: "Niveau NB", cmd: CMD.NB_LEVEL, level: true },
    { code: "NR", label: "Réduction de bruit", cmd: CMD.NR, values: [0x00, 0x01] },
    { code: "NR niv.", label: "Niveau NR", cmd: CMD.NR_LEVEL, level: true },
    { code: "ANF", label: "Notch automatique", cmd: CMD.ANF, values: [0x00, 0x01] },
    { code: "COMP", label: "Compresseur", cmd: CMD.COMP, values: [0x00, 0x01] },
    { code: "COMP niv.", label: "Niveau du compresseur", cmd: CMD.COMP_LEVEL, level: true },
    { code: "RIT", label: "RIT", cmd: CMD.RIT_ON, values: [0x00, 0x01] },
    { code: "SPLIT", label: "Split", cmd: CMD.SPLIT, values: [0x00, 0x01] },
    { code: "TUNER", label: "Coupleur (en / hors service, sans accord)", cmd: CMD.TUNER, values: [0x00, 0x01] },
  ];
  const SCALE = { sText, poPercent, swrValue, alcPercent };
  function unhex(s) { return String(s || "").trim().split(/\s+/).filter(Boolean).map(x => parseInt(x, 16)); }

  const api = { FUNCS, SCALE, unhex, CTRL, CMD, MODES, MODE_CODES, frame, hex, Parser, decodeFreq, encodeFreq, decodeLevel, encodeLevel,
                PO_TABLE, SWR_TABLE, poPercent, swrValue, alcPercent, sText, CivLink };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtCiv = api;
})(typeof window !== "undefined" ? window : globalThis);
