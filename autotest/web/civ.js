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
    // Affichage du spectre (01 = marche, 00 = arrêt) : essai R10, lu puis remis comme il était.
    SCOPE_ON: [0x27, 0x10],
    // Fonctions de réception (essai R9 : lue, changée, relue, remise, relue). JAMAIS le VOX (16 46).
    ATT: [0x11],                 // atténuateur : 00 ou la valeur en dB du modèle (BCD : 20, 12, 10, 06, 18…)
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
    // Coupleur : lu au début (R6), écrit SEULEMENT pendant l'essai E7, sous la garde d'émission. Avec un AH-4 / AH-740,
    // le mettre en service (01) LANCE l'accord (CW, ~10 W : manuel IC-7100 p. 16-5) ; 02 = lancer l'accord : seulement
    // par tunerStart(), jamais par frame() sans l'autorisation de la garde.
    TUNER: [0x1C, 0x01],
    VFO_EXCH: [0x07, 0xB0],      // échange VFO A / B
    VFO_FREQ: [0x25],            // lecture : 00 VFO choisi, 01 l'autre (jamais d'écriture)
  };
  const ALLOWED = Object.values(CMD).map(c => c.join(","));
  // Données permises après certaines commandes (le reste : toute donnée). Une donnée hors liste = refus de la page.
  // Valeurs d'atténuateur connues chez Icom (dB en BCD), essayées dans cet ordre pour un modèle sans valeur dans la
  // table (IC-7300 / IC-705 : 20 ; IC-7100 : 12 ; IC-9700 : 10 ; IC-7610 / IC-7851 : 6, 12, 18).
  function ATT_VALUES() { return [0x20, 0x12, 0x10, 0x06, 0x18, 0x30]; }
  const DATA_RULES = {
    [CMD.TUNER.join(",")]: [[], [0x00], [0x01]],
    [CMD.VFO_EXCH.join(",")]: [[]],
    [CMD.VFO_FREQ.join(",")]: [[0x00], [0x01]],
    [CMD.SPLIT.join(",")]: [[], [0x00], [0x01]],
    [CMD.RIT_ON.join(",")]: [[], [0x00], [0x01]],
    [CMD.ATT.join(",")]: [[], [0x00], ...ATT_VALUES().map(v => [v])],
    [CMD.SCOPE_ON.join(",")]: [[], [0x00], [0x01]],
    [CMD.SCOPE_OUT.join(",")]: [[], [0x00], [0x01]],
  };
  const SCOPE_DATA = [0x27, 0x00];                     // trames du spectre envoyées par le poste (jamais par la page)
  const LEVEL_MAX = 160;                               // niveau maximal d'un point du spectre (0xA0)

  const MODES = { 0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM", 0x06: "WFM",
                  0x07: "CW-R", 0x08: "RTTY-R", 0x17: "DV" };
  const MODE_CODES = Object.fromEntries(Object.entries(MODES).map(([k, v]) => [v, Number(k)]));

  function frame(addr, cmd, data, tuneStart) {
    const body = [...cmd, ...(data || [])], key = cmd.join(",");
    // Seule exception à la liste : « 1C 01 02 » (lancer l'accord), demandée par tunerStart() sous la garde d'émission.
    if (tuneStart === true && key === CMD.TUNER.join(",") && (data || []).join(",") === "2") return Uint8Array.from([PREAMBLE, PREAMBLE, addr, CTRL, ...body, END]);
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
        if (e < 0) { this.buf = this.buf.slice(s); if (this.buf.length > 256) this.buf = []; break; }   // 256 : une division du spectre dépasse 64 octets
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

  /* Spectre (essai R10) : recompose un balayage à partir de ses divisions « 27 00 [choix] nn tt … » (numéros en BCD),
     comme trxstation/spectrum/civ.py (ScopeAssembler, format relevé sur un IC-7300MK2 : 11 divisions, division 1 =
     en-tête de 12 octets : mode, deux fréquences BCD de 5 octets, hors plage ; 475 points de 0 à 160). */
  const isBcd = b => (b >> 4) <= 9 && (b & 0x0F) <= 9;
  const bcdByte = b => (b >> 4) * 10 + (b & 0x0F);
  const bcdLe = bytes => bytes.every(isBcd) ? decodeFreq(bytes) : null;
  class ScopeAssembler {
    constructor() { this.current = null; this.expected = 0; this.complete = 0; this.incomplete = 0; this.unreadable = 0; this.layouts = {}; }
    _split(d) {
      const valid = (div, top) => isBcd(div) && isBcd(top) && bcdByte(div) >= 1 && bcdByte(div) <= bcdByte(top) && bcdByte(top) <= 50;
      if (d.length >= 3 && (d[0] === 0 || d[0] === 1) && valid(d[1], d[2])) return { sel: d[0], div: bcdByte(d[1]), top: bcdByte(d[2]), body: d.slice(3) };
      if (d.length >= 2 && valid(d[0], d[1])) return { sel: null, div: bcdByte(d[0]), top: bcdByte(d[1]), body: d.slice(2) };
      return null;
    }
    // `data` : octets qui suivent 27 00. Rend le balayage quand sa dernière division arrive.
    feed(data, t) {
      const p = this._split(data);
      if (!p) { this.unreadable++; return null; }
      const lay = (p.sel != null ? "avec" : "sans") + " octet de choix, " + p.top + " division(s)";
      this.layouts[lay] = (this.layouts[lay] || 0) + 1;
      if (p.div === 1) {
        if (this.current) this.incomplete++;
        const b = p.body, h = b.length >= 12;
        this.current = { t, mode: h ? b[0] : null, f1: h ? bcdLe(b.slice(1, 6)) : null, f2: h ? bcdLe(b.slice(6, 11)) : null,
                         outOfRange: h ? !!b[11] : null, points: h ? Array.from(b.slice(12)) : [] };
        this.expected = 2;
      } else if (!this.current || p.div !== this.expected) {
        if (this.current) this.incomplete++;
        this.current = null; return null;
      } else { for (const v of p.body) this.current.points.push(v); this.expected++; }
      if (p.div === p.top) { const s = this.current; this.current = null; this.complete++; return s; }
      return null;
    }
  }
  // Bornes d'un balayage : f2 > f1 = bornes fixes, sinon centre ± demi-largeur (trxstation/spectrum/frame.py).
  function scopeEdges(s) {
    if (!s || !s.f1 || !s.f2) return null;
    return s.f2 > s.f1 ? [s.f1, s.f2] : [Math.max(0, s.f1 - s.f2), s.f1 + s.f2];
  }
  // Aperçu d'un balayage en `width` valeurs (maximum de chaque tranche), pour le rapport.
  function scopePreview(points, width) {
    const n = points.length, out = [];
    if (!n) return out;
    for (let i = 0; i < width; i++) {
      const a = Math.floor(i * n / width), b = Math.max(a + 1, Math.floor((i + 1) * n / width));
      out.push(Math.max(...points.slice(a, b)));
    }
    return out;
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
    _log(dir, bytes) {
      // Pendant la capture du spectre (R10), seuls les premiers blocs reçus sont tracés (le flux ferait des centaines
      // de ko) ; les octets suivants sont comptés.
      const q = this.quiet;
      if (q && dir === "rx") { if (q.kept >= q.max) { q.bytes += bytes.length; return; } q.kept++; }
      this.trace.push({ t: this.clock() - this.t0, d: dir, h: hex(bytes) });
    }
    _rx(bytes) {
      this._log("rx", bytes);
      for (const f of this.parser.push(bytes)) {
        if (f.from === CTRL) continue;                         // écho de nos propres trames
        // Trames du spectre : jamais une réponse à une requête ; données à l'essai R10 s'il écoute, sinon ignorées.
        if (f.payload[0] === SCOPE_DATA[0] && f.payload[1] === SCOPE_DATA[1]) { if (this.onScope) this.onScope(f); continue; }
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
        const fr = frame(this.addr, cmd, data, o.tuneStart === true);
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
    async fnWrite(f, v) {
      // Atténuateur mis en marche : valeur du modèle, sinon les valeurs connues l'une après l'autre (refus = suivante).
      if (f.att && v !== "00") {
        const tries = (this.attValues && this.attValues.length ? this.attValues : ATT_VALUES()).map(x => hex([x]));
        let last = { ok: false, ng: false };
        for (const t of tries) {
          const r = await this.writeRaw(f.cmd, unhex(t));
          if (r.ok) return { ok: true, ng: false, written: t };
          last = { ok: false, ng: !!r.ng };
          if (!r.ng) break;                                         // silence : pas la peine d'insister
        }
        return last;
      }
      const r = await this.writeRaw(f.cmd, unhex(v)); return { ok: !!r.ok, ng: !!r.ng };
    }
    fnOther(f, v0) {
      const b = unhex(v0);
      if (f.att) return b[0] ? "00" : hex([(this.attValues && this.attValues[0]) || ATT_VALUES()[0]]);
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

    // ---- Coupleur d'antenne. Lecture : 0 hors service, 1 en service, 2 accord en cours ; null = pas de coupleur vu.
    async tunerRead() { const r = await this.readRaw(CMD.TUNER); return r.ok && r.data.length ? r.data[0] : null; }
    // 00 / 01 seulement. 01 peut LANCER un accord (AH-4) : l'appelant le fait sous la garde (essai E7), jamais ailleurs.
    async tunerSet(v) {
      if (v !== 0 && v !== 1) throw new Error("coupleur : valeur refusée");
      const r = await this.writeRaw(CMD.TUNER, [v]); return { ok: !!r.ok, ng: !!r.ng };
    }
    // Lancer l'accord (émission) : seulement quand la garde d'émission a ouvert un accord.
    async tunerStart(guard) {
      if (!guard || !guard.tuning || !guard.on) throw new Error("accord refusé : hors de la garde d'émission");
      const r = await this.request(CMD.TUNER, [0x02], { timeout: 300, tuneStart: true }); return { ok: !!r.ok, ng: !!r.ng };
    }
    // Arrêt d'urgence d'un accord : coupleur hors service, en tête de file.
    async tunerAbortNow() { await this.sendNow(CMD.TUNER, [0x00]); }

    // ---- Spectre (essai R10, SANS émission). État : { display, output } (0 / 1, null = illisible).
    async scopeRead() {
      const v = r => r.ok && r.data.length ? r.data[r.data.length - 1] : null;
      const a = await this.readRaw(CMD.SCOPE_ON), b = await this.readRaw(CMD.SCOPE_OUT);
      return { display: v(a), output: v(b) };
    }
    // Sortie coupée AVANT l'affichage (et remise dans l'ordre inverse) ; rend true si les deux écritures sont acceptées.
    async scopeSet(display, output) {
      if (output === 0) { const a = await this.writeRaw(CMD.SCOPE_OUT, [0]), b = await this.writeRaw(CMD.SCOPE_ON, [display ? 1 : 0]); return !!(a.ok && b.ok); }
      const a = await this.writeRaw(CMD.SCOPE_ON, [display ? 1 : 0]), b = await this.writeRaw(CMD.SCOPE_OUT, [output ? 1 : 0]);
      return !!(a.ok && b.ok);
    }
    /* Écoute les trames 27 00 pendant `ms` (attente fournie par l'appelant : STOP l'abrège). Le poste envoie ses trames
       au contrôleur qui a mis la sortie en marche : celles adressées à un autre (station en E1) sont COMPTÉES, jamais
       reprises. Rend les comptes, la forme des balayages et un aperçu du dernier. */
    async scopeCapture(ms, wait) {
      const asm = new ScopeAssembler(), t0 = this.clock();
      const st = { frames: 0, other: 0, sweeps: 0, lengths: {}, levelMax: 0, levelMin: null, last: null, firstT: null, lastT: null };
      this.quiet = { kept: 0, max: 40, bytes: 0 };
      this.onScope = f => {
        if (this.addr != null && this.addr !== 0x00 && f.from !== this.addr) return;
        if (f.to !== CTRL && f.to !== 0x00) { st.other++; return; }
        st.frames++;
        const t = (this.clock() - t0) / 1000, s = asm.feed(f.payload.slice(2), t);
        if (!s) return;
        st.sweeps++; st.lengths[s.points.length] = (st.lengths[s.points.length] || 0) + 1;
        for (const v of s.points) { if (v > st.levelMax) st.levelMax = v; if (st.levelMin == null || v < st.levelMin) st.levelMin = v; }
        if (st.firstT == null) st.firstT = s.t; st.lastT = s.t; st.last = s;
      };
      try { await wait(ms); }
      finally {
        this.onScope = null;
        st.untraced = this.quiet.bytes; this.quiet = null;     // trace : toujours des octets, le reste compté ici
      }
      st.incomplete = asm.incomplete; st.unreadable = asm.unreadable; st.layouts = asm.layouts;
      return st;
    }
  }

  /* Fonctions essayées en R9, SANS émission : lue, changée, relue, remise, relue. Le VOX n'y est JAMAIS, le coupleur
     non plus (le mettre en service peut lancer un accord : essai E7). */
  const FUNCS = [
    { code: "ATT", label: "Atténuateur", cmd: CMD.ATT, values: [0x00], att: true },
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
  ];
  const SCALE = { sText, poPercent, swrValue, alcPercent };
  function unhex(s) { return String(s || "").trim().split(/\s+/).filter(Boolean).map(x => parseInt(x, 16)); }

  const api = { FUNCS, SCALE, unhex, CTRL, CMD, MODES, MODE_CODES, frame, hex, Parser, decodeFreq, encodeFreq, decodeLevel, encodeLevel,
                PO_TABLE, SWR_TABLE, poPercent, swrValue, alcPercent, sText, CivLink,
                ScopeAssembler, scopeEdges, scopePreview, LEVEL_MAX };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtCiv = api;
})(typeof window !== "undefined" ? window : globalThis);
