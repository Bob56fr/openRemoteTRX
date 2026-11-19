// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, enchaînement des essais (docs/prequalif-web-cahier-des-charges.md § 4 à § 6) : détection,
   réception R1 à R8, autorisation unique, émissions E1 à E4 et E6, remise de l'état d'origine.
   Sécurités gardées (§ 5) : AUCUNE émission avant l'autorisation ; chaque émission coupée par la garde au plus tard à
   `maxTx` (10 s), même si l'essai ou la page se bloque ; STOP, erreur, onglet caché = retour en réception ; PTT relu
   après chaque retour ; état d'origine remis dans tous les cas. Indépendant de la page : testé sous Node. */
(function (root) {
  "use strict";
  const civ = (typeof module !== "undefined" && module.exports) ? require("./civ.js") : root.AtCiv;
  const { CMD, MODE_CODES } = civ;

  const DEFAULTS = { e1: 3000, e2: 5000, e4: 8000, e6: 2000, sample: 200, maxTx: 10000, settle: 150, power: 10 };

  const STEPS = [
    ["R1", "Port et vitesse"], ["R2", "Modèle identifié"], ["R3", "Fréquence et mode lus"], ["R4", "S-mètre"],
    ["R5", "Temps de réponse"], ["R6", "PTT lu"], ["R7", "Carte son du poste"], ["R8", "Écriture de fréquence et de mode"],
    ["R9", "Fonctions du poste (ATT, P.AMP, NB, NR, RIT, split, VFO…)"],
    ["E1", "Émission par la CAT"], ["E2", "Puissance lue"], ["E3", "TOS lu"], ["E4", "Tonalité 1 kHz"],
    ["E6", "STOP de la page"], ["RS", "Remise de l'état d'origine"],
  ];

  /* Fonctions essayées en R9, SANS émission : lue, changée, relue, remise, relue. Une fonction que le poste ne lit pas
     (silence ou refus) est « absente », jamais une panne. Le VOX n'y est JAMAIS (règle de la station). */
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
  const STATUS_FN = { ok: "OK", absent: "absente", refus: "écriture refusée", ecart: "relue fausse", remise: "NON REMISE" };

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const fr = (v, d) => v.toFixed(d).replace(".", ",");
  const fmtHz = hz => hz == null ? "—" : (hz / 1e6).toFixed(6).replace(/(\d+)\.(\d{3})(\d{3})/, "$1.$2.$3");

  /* Garde d'émission : SEUL chemin pour passer en émission. La minuterie de coupure est armée AVANT l'ordre
     d'émission (un accusé perdu ne laisse jamais le poste en émission sans coupure prévue). */
  class TxGuard {
    constructor(link, opts) {
      this.link = link; this.o = Object.assign({ maxTx: DEFAULTS.maxTx, settle: DEFAULTS.settle }, opts || {});
      this.armed = false; this.on = false; this.timer = null; this.since = 0; this.lastStop = null;
      this.onChange = this.o.onChange || (() => {}); this.audio = this.o.audio || null;
      this.unkeying = null;
    }
    arm() { this.armed = true; }
    disarm() { this.armed = false; }
    async key(label) {
      if (!this.armed) throw new Error("émission refusée : pas d'autorisation");
      if (this.on) return true;
      this.on = true; this.since = Date.now(); this.label = label;
      this.timer = setTimeout(() => { this.unkey("duree_max"); }, this.o.maxTx);
      this.onChange({ on: true, label, maxTx: this.o.maxTx });
      const ok = await this.link.setPtt(true);
      return ok;
    }
    /* Retour en réception : ordre envoyé en tête de file, jusqu'à 3 fois, PTT relu. Rend true si la réception est
       relue. Appels simultanés : un seul retour en cours. */
    unkey(reason) {
      if (this.unkeying) return this.unkeying;
      const wasOn = this.on;
      clearTimeout(this.timer); this.timer = null;
      if (this.audio) { try { this.audio.stopTone(); } catch (e) { /* rien */ } }
      this.unkeying = (async () => {
        let rx = null;
        for (let i = 0; i < 3; i++) {
          try { await this.link.sendNow(CMD.PTT, [0]); } catch (e) { /* port perdu : rien d'autre à faire */ }
          await sleep(this.o.settle);
          rx = await this.link.readPtt();
          if (rx === false) break;
        }
        this.on = false;
        if (wasOn) { this.lastStop = { reason, rx: rx === false }; this.onChange({ on: false, reason, rx: rx === false }); }
        return rx === false;
      })().finally(() => { this.unkeying = null; });
      return this.unkeying;
    }
  }

  /* Détection : vitesses essayées, identité `19 00` à l'adresse du modèle puis à l'adresse générale 00, et à défaut une
     lecture de fréquence à l'adresse du modèle. openAt(baud) rend un transport ouvert (close() pour le libérer). */
  async function detect({ openAt, model, bauds, onTry, byAddr }) {
    for (const baud of bauds) {
      if (onTry) onTry(baud);
      let tr;
      try { tr = await openAt(baud); } catch (e) { return { error: "port", detail: String(e && e.message || e) }; }
      const tries = model ? [model.addr, 0x00] : [0x00];
      for (const a of tries) {
        const link = new civ.CivLink(tr, a);
        link.addr = a; const id = await link.readId();
        if (id) { link.addr = id.from; return { baud, addr: id.from, transport: tr, link, idSupported: true, guess: byAddr ? byAddr(id.from) : null }; }
      }
      if (model) {
        const link = new civ.CivLink(tr, model.addr);
        const f = await link.readFreq();
        if (f != null) return { baud, addr: model.addr, transport: tr, link, idSupported: false, guess: model };
      }
      try { await tr.close(); } catch (e) { /* rien */ }
    }
    return { error: "silence" };
  }

  class Runner {
    constructor({ link, model, audio, ui, opts, detected }) {
      this.link = link; this.model = model; this.audio = audio; this.ui = ui;
      this.o = Object.assign({}, DEFAULTS, opts || {});
      this.detected = detected || {};
      this.results = []; this.samples = []; this.orig = {}; this.aborted = false; this.timings = [];
      this.guard = new TxGuard(link, { maxTx: this.o.maxTx, settle: this.o.settle, audio,
        onChange: s => this.emit(Object.assign({ type: "tx" }, s)) });
      this.na = new Set();
    }
    emit(ev) { try { this.ui.event(ev); } catch (e) { /* l'affichage ne doit jamais bloquer les essais */ } }
    now(text) { this.emit({ type: "now", text }); }
    step(code, state) { this.emit({ type: "step", code, state }); }
    result(code, status, text, values) {
      const r = { code, status, text, values: values || {} };
      const i = this.results.findIndex(x => x.code === code);
      if (i >= 0) this.results[i] = r; else this.results.push(r);
      this.emit({ type: "result", result: r });
      return r;
    }
    async wait(ms) {
      const end = Date.now() + ms;
      while (!this.aborted && Date.now() < end) await sleep(Math.min(50, end - Date.now()));
    }
    /* STOP de l'opérateur (bouton, Échap), erreur de la page, onglet caché : fin des essais d'émission. */
    stop(reason) {
      this.aborted = true; this.stopReason = this.stopReason || reason;
      return this.guard.unkey(reason || "stop");
    }

    async run() {
      const d = this.detected;
      this.result("R1", "ok", `Le poste répond à ${d.baud} bauds.`, { baud: d.baud });
      this._r2();
      try {
        await this._reception();
        if (this.aborted) return this._finish();
        const go = await this._authorize();
        if (go && !this.aborted) await this._emissions();
        else for (const c of ["E1", "E2", "E3", "E4", "E6"]) if (!this.results.find(r => r.code === c)) this.result(c, "saute", go ? "Essais arrêtés." : "Émissions non autorisées.");
      } catch (e) {
        this.emit({ type: "error", text: String(e && e.message || e) });
        await this.guard.unkey("erreur");
      } finally {
        this.guard.disarm();
        if (this.guard.on || this.guard.unkeying) await this.guard.unkey("fin");
        await this._restore();
      }
      return this._finish();
    }
    _finish() { this.emit({ type: "done", results: this.results }); return { results: this.results, samples: this.samples, orig: this.orig, stop: this.stopReason || null }; }

    _r2() {
      const d = this.detected, m = this.model, hexA = a => a.toString(16).toUpperCase().padStart(2, "0") + "h";
      if (!m) this.result("R2", d.guess ? "ok" : "avert", d.guess ? `Poste reconnu : ${d.guess.name} (adresse ${hexA(d.addr)}).` : `Poste à l'adresse ${hexA(d.addr)}, modèle inconnu de la table.`, { addr: d.addr });
      else if (d.addr === m.addr) this.result("R2", "ok", `${m.name} reconnu à son adresse ${hexA(d.addr)}${d.idSupported ? "" : " (identité non gérée par le poste, fréquence lue)"}.`, { addr: d.addr });
      else this.result("R2", "avert", `Le poste répond à l'adresse ${hexA(d.addr)}${d.guess ? " (" + d.guess.name + " ?)" : ""}, pas à celle du ${m.name} (${hexA(m.addr)}) : adresse CI-V changée dans le poste, ou autre modèle.`, { addr: d.addr });
    }

    async _timed(fn) { const t = Date.now(); const v = await fn(); this.timings.push(Date.now() - t); return v; }

    async _reception() {
      const L = this.link;
      // R3
      this.step("R3", "cur"); this.now("Lecture de la fréquence et du mode…");
      const f1 = await this._timed(() => L.readFreq()), m1 = await this._timed(() => L.readMode());
      const f2 = await this._timed(() => L.readFreq()), m2 = await this._timed(() => L.readMode());
      this.orig.freq = f1; this.orig.mode = m1;
      if (f1 == null || m1 == null) this.result("R3", "echec", "Fréquence ou mode illisible.");
      else if (f1 !== f2 || m1.code !== m2.code) this.result("R3", "avert", "Deux lectures différentes : quelqu'un touche le poste ?", { f1, f2 });
      else this.result("R3", "ok", `${fmtHz(f1)} MHz, ${m1.name}.`, { hz: f1, mode: m1.name, filter: m1.filter });
      this.orig.data = await L.readDataMode();
      this.orig.power = await L.level(CMD.RF_POWER);
      if (this.aborted) return;
      // R4
      this.step("R4", "cur"); this.now("Lecture du S-mètre…");
      const s = [];
      for (let i = 0; i < 8 && !this.aborted; i++) { s.push(await this._timed(() => L.level(CMD.S_METER))); await this.wait(150); }
      const got = s.filter(v => v != null);
      if (!got.length) this.result("R4", "na", "S-mètre non lu par la CAT.");
      else this.result("R4", "ok", `De ${civ.sText(Math.min(...got))} à ${civ.sText(Math.max(...got))}.`, { raw: got });
      // R5
      this.step("R5", "cur"); this.now("Mesure du temps de réponse…");
      const t = this.timings.slice().sort((a, b) => a - b);
      const med = t.length ? t[Math.floor(t.length / 2)] : null, max = t.length ? t[t.length - 1] : null;
      if (med == null) this.result("R5", "na", "Aucune mesure.");
      else this.result("R5", med > 200 ? "avert" : "ok", `Médiane ${med} ms, pire ${max} ms sur ${t.length} lectures.`, { median_ms: med, max_ms: max, n: t.length });
      // R6
      this.step("R6", "cur"); this.now("Lecture du PTT…");
      const ptt = await L.readPtt();
      this.pttReadable = ptt !== null;
      if (ptt === true) { this.result("R6", "echec", "Le poste est DÉJÀ en émission : essais arrêtés (la page ne touche pas à une émission de l'opérateur)."); this.aborted = true; this.stopReason = "deja_en_emission"; return; }
      if (ptt === null) this.result("R6", "avert", "PTT illisible par la CAT : les émissions d'essai ne seront pas faites (retour en réception impossible à vérifier).");
      else this.result("R6", "ok", "Réception.");
      // R7
      this.step("R7", "cur"); this.now("Carte son du poste…");
      await this._audio();
      if (this.aborted) return;
      // R8
      this.step("R8", "cur"); this.now("Écriture de la fréquence (+1 kHz) puis du mode…");
      await this._r8();
      if (this.aborted) return;
      // R9
      this.step("R9", "cur"); this.now("Fonctions du poste : lecture, changement, relecture, remise…");
      await this._r9();
    }

    // Une valeur lue : tableau d'octets après la commande, ou null (absente).
    async _fnRead(f) {
      const r = await this.link.readRaw(f.cmd);
      if (!r.ok || !r.data || !r.data.length) return null;
      return f.level ? r.data.slice(0, 2) : r.data.slice(0, 1);
    }
    _fnOther(f, v0) {
      if (f.level) { const n = civ.decodeLevel(v0); return civ.encodeLevel(n >= 128 ? n - 51 : n + 51); }
      const other = f.values.find(x => x !== v0[0]);
      return [other == null ? f.values[0] : other];
    }

    async _r9() {
      const L = this.link, same = (a, b) => !!a && !!b && a.join(",") === b.join(",");
      const out = [], changed = [];
      try {
        for (const f of FUNCS) {
          if (this.aborted) break;
          this.now(`Fonction ${f.code} : lecture, changement, relecture, remise…`);
          const row = { code: f.code, label: f.label };
          const v0 = await this._fnRead(f);
          if (!v0) { row.statut = "absent"; out.push(row); continue; }
          row.avant = civ.hex(v0);
          const v1 = this._fnOther(f, v0); row.essai = civ.hex(v1);
          const w = await L.writeRaw(f.cmd, v1);
          if (!w.ok) { row.statut = "refus"; out.push(row); continue; }
          changed.push({ f, v0 });
          const r1 = await this._fnRead(f); row.relu = r1 ? civ.hex(r1) : null;
          await L.writeRaw(f.cmd, v0);
          const r2 = await this._fnRead(f); row.remis = r2 ? civ.hex(r2) : null;
          // Un niveau est arrondi au cran du poste (IC-7300MK2 : NR écrit 123 relu 120, COMP 155 relu 151) : écart
          // accepté jusqu'à un demi-cran du réglage le plus grossier (11 crans : 255 / 10 / 2 ≈ 13).
          const near = f.level && r1 && Math.abs(civ.decodeLevel(r1) - civ.decodeLevel(v1)) <= 13;
          if (near && !same(r1, v1)) row.note = `arrondi au cran du poste (écrit ${civ.decodeLevel(v1)}, relu ${civ.decodeLevel(r1)})`;
          row.statut = !same(r2, v0) ? "remise" : !(same(r1, v1) || near) ? "ecart" : "ok";
          out.push(row);
        }
        out.push(await this._vfo());
      } finally {
        // Seconde passe : une fonction peut en changer une autre (P.AMP coupe l'ATT…) : tout est relu et remis.
        for (const { f, v0 } of changed) {
          const now = await this._fnRead(f);
          if (same(now, v0)) continue;
          await L.writeRaw(f.cmd, v0);
          const back = await this._fnRead(f);
          const row = out.find(x => x.code === f.code);
          if (row) { row.remis = back ? civ.hex(back) : null; row.statut = same(back, v0) ? (row.statut === "remise" ? "ecart" : row.statut) : "remise"; row.repasse = true; }
        }
      }
      const by = s => out.filter(x => x.statut === s).map(x => x.code);
      const ok = by("ok"), abs = by("absent"), ref = by("refus"), ec = by("ecart"), bad = by("remise");
      const parts = [];
      if (ok.length) parts.push(`${ok.length} OK : ${ok.join(", ")}`);
      if (ec.length) parts.push(`relues fausses : ${ec.join(", ")}`);
      if (ref.length) parts.push(`écriture refusée : ${ref.join(", ")}`);
      if (abs.length) parts.push(`absentes : ${abs.join(", ")}`);
      if (bad.length) parts.push(`NON REMISES (à remettre à la main) : ${bad.join(", ")}`);
      const status = bad.length ? "echec" : (ec.length || ref.length) ? "avert" : ok.length ? "ok" : "na";
      this.result("R9", status, parts.join(" ; ") + ".", { fonctions: out });
    }

    // VFO A / B : échange, relecture, échange de nouveau, relecture (on ne sait pas lire QUEL VFO est choisi).
    async _vfo() {
      const L = this.link, row = { code: "VFO A/B", label: "Échange des VFO A et B" };
      const f0 = await L.readFreq(), o0 = await this._readOtherVfo();
      if (f0 == null) { row.statut = "absent"; return row; }
      const w = await L.writeRaw(CMD.VFO_EXCH, []);
      if (!w.ok) { row.statut = w.ng ? "refus" : "absent"; return row; }
      const f1 = await L.readFreq();
      await L.writeRaw(CMD.VFO_EXCH, []);
      const f2 = await L.readFreq();
      row.avant = fmtHz(f0); row.autre = o0 == null ? null : fmtHz(o0); row.relu = fmtHz(f1); row.remis = fmtHz(f2);
      if (f2 !== f0) row.statut = "remise";
      else if (o0 != null) row.statut = f1 === o0 ? "ok" : "ecart";
      else { row.statut = "ok"; if (f1 === f0) row.note = "fréquences A et B peut-être identiques : échange non vérifiable"; }
      return row;
    }
    async _readOtherVfo() {
      const r = await this.link.request(CMD.VFO_FREQ, [0x01], { timeout: 300 });
      return r.ok && r.data.length >= 6 ? civ.decodeFreq(r.data.slice(1, 6)) : null;
    }

    async _audio() {
      const a = this.audio;
      const chosen = a ? await this.ui.chooseAudio() : null;
      if (!chosen || !a.hasInput()) { this.result("R7", "na", "Carte son du poste non choisie."); return; }
      const db = await a.measureInput(1500);
      if (db == null) this.result("R7", "echec", "Entrée de la carte son illisible.");
      else if (!isFinite(db) || db < -100) this.result("R7", "avert", "Entrée de la carte son muette (silence numérique) : réglages du son du poste ou de l'ordinateur.", { dbfs: null });
      else this.result("R7", "ok", `Entrée trouvée, bruit de réception ${db.toFixed(0)} dBFS${a.hasOutput() ? ", sortie choisie pour la tonalité" : ""}.`, { dbfs: Math.round(db) });
    }

    async _r8() {
      const L = this.link, f0 = this.orig.freq, m0 = this.orig.mode;
      if (f0 == null || m0 == null) { this.result("R8", "na", "Fréquence d'origine inconnue."); return; }
      const lines = []; let status = "ok";
      let target = f0 + 1000, okF = await L.setFreq(target);
      if (!okF) { target = f0 - 1000; okF = await L.setFreq(target); }
      const rf = okF ? await L.readFreq() : null;
      if (!okF) { status = "avert"; lines.push("fréquence non réglable par la CAT"); }
      else if (rf !== target) { status = "avert"; lines.push(`fréquence écrite ${fmtHz(target)}, relue ${fmtHz(rf)}`); }
      else lines.push(`fréquence ${fmtHz(target)} écrite et relue`);
      if (okF) await L.setFreq(f0);
      const other = m0.name === "USB" ? "LSB" : "USB";
      const okM = await L.setMode(MODE_CODES[other], m0.filter);
      const rm = okM ? await L.readMode() : null;
      if (!okM) { status = "avert"; lines.push("mode non réglable par la CAT"); }
      else if (!rm || rm.name !== other) { status = "avert"; lines.push(`mode ${other} écrit, relu ${rm ? rm.name : "—"}`); }
      else lines.push(`mode ${other} écrit et relu`);
      if (okM) await L.setMode(m0.code, m0.filter);
      const back = await L.readFreq(), bm = await L.readMode();
      if (back !== f0 || !bm || bm.code !== m0.code) { status = "avert"; lines.push("état d'origine pas encore relu (remis à la fin)"); }
      this.result("R8", status, lines.join(" ; ") + ".", { written_hz: target });
    }

    async _authorize() {
      this.step("AU", "cur");
      if (!this.pttReadable) { this.now("Émissions sautées : PTT illisible."); return false; }
      const pct = Math.max(this.o.power, this.model && this.model.minPct || 0);
      const maxW = this.model ? this.model.maxW : null;
      const info = { hz: this.orig.freq, mode: this.orig.mode && this.orig.mode.name, pct, watts: maxW ? maxW * pct / 100 : null, maxW,
                     emissions: [["E1", "émission par la CAT, sans modulation", this.o.e1], ["E2", "porteuse en FM : puissance et TOS", this.o.e2],
                                 ["E4", "tonalité 1 kHz en mode données", this.o.e4], ["E6", "coupure par la page (STOP)", this.o.e6]] };
      this.now("En attente de l'autorisation d'émettre…");
      const ok = await this.ui.authorize(info);
      if (!ok || this.aborted) return false;
      // Puissance : 10 % (ou le minimum du poste), relue.
      const raw = Math.round(255 * pct / 100);
      const set = this.orig.power != null && await this.link.setPower(raw);
      const back = set ? await this.link.level(CMD.RF_POWER) : null;
      this.powerSet = back != null && Math.abs(back - raw) <= 2;
      if (!this.powerSet) {
        const manual = await this.ui.confirmManualPower(info);
        if (!manual || this.aborted) return false;
      }
      this.guard.arm();
      return true;
    }

    async _sampleTx(ms, label) {
      const L = this.link, out = [], end = Date.now() + ms;
      const read = async (key, cmd) => {
        if (this.na.has(key)) return null;
        const v = await L.level(cmd);
        if (v == null) { this.naMiss = this.naMiss || {}; this.naMiss[key] = (this.naMiss[key] || 0) + 1; if (this.naMiss[key] >= 2) this.na.add(key); }
        return v;
      };
      while (!this.aborted && this.guard.on && Date.now() < end) {
        const po = await read("po", CMD.PO_METER), swr = await read("swr", CMD.SWR_METER), alc = await read("alc", CMD.ALC_METER);
        const s = { t: Date.now(), label,
                    po: po == null ? null : civ.poPercent(po), swr: swr == null ? null : civ.swrValue(swr), alc: alc == null ? null : civ.alcPercent(alc),
                    raw: { po, swr, alc } };
        out.push(s); this.samples.push(s);
        this.emit({ type: "meters", sample: s, maxW: this.model ? this.model.maxW : null, na: Array.from(this.na) });
        await this.wait(this.o.sample);
      }
      return out;
    }

    // Une émission d'essai : clé, mesures pendant `ms`, retour en réception relu. Rend {keyed, samples, rx}.
    async _emit(code, ms, info) {
      if (this.aborted) return null;
      this.step(code, "cur");
      this.emit({ type: "tx-info", code, ms, info: Object.assign({ hz: await this.link.readFreq() }, info) });
      const tKey = Date.now();
      const acked = await this.guard.key(code);
      const pttOn = await this.link.readPtt();
      const tOn = Date.now() - tKey;
      const samples = await this._sampleTx(Math.max(0, ms - (Date.now() - tKey)), code);
      const tOff0 = Date.now();
      const rx = await this.guard.unkey(this.aborted ? (this.stopReason || "stop") : "fin_essai");
      return { acked, pttOn, tOn, tOff: Date.now() - tOff0, samples, rx };
    }

    async _emissions() {
      const L = this.link, m0 = this.orig.mode;
      // E1 : émission par la CAT dans le mode d'origine.
      this.now("E1 : émission par la CAT, sans modulation…");
      const e1 = await this._emit("E1", this.o.e1, { what: "Émission par la CAT, sans modulation", mode: m0 && m0.name });
      if (!e1) return;
      if (!e1.rx) { this.result("E1", "echec", "Retour en réception NON relu : coupez le poste à la main."); this.aborted = true; return; }
      if (!e1.pttOn) this.result("E1", "echec", `Ordre d'émission ${e1.acked ? "accepté" : "refusé"} mais PTT relu en réception : émission par la CAT impossible ?`);
      else this.result("E1", "ok", `Émission relue en ${e1.tOn} ms, réception relue en ${e1.tOff} ms.`, { t_on_ms: e1.tOn, t_off_ms: e1.tOff });
      if (!e1.pttOn || this.aborted) return;

      // E2 / E3 : porteuse (FM, sinon RTTY, sinon AM).
      let carrier = null;
      for (const name of ["FM", "RTTY", "AM"]) { if (await L.setMode(MODE_CODES[name], 1)) { const rm = await L.readMode(); if (rm && rm.name === name) { carrier = name; break; } } }
      if (!carrier) { this.result("E2", "na", "Aucun mode à porteuse réglable par la CAT."); this.result("E3", "na", "Pas de porteuse."); }
      else {
        this.now(`E2 / E3 : porteuse en ${carrier}, lecture de la puissance et du TOS…`);
        const e2 = await this._emit("E2", this.o.e2, { what: `Porteuse en ${carrier}`, mode: carrier });
        if (!e2) return;
        if (!e2.rx) { this.result("E2", "echec", "Retour en réception NON relu : coupez le poste à la main."); this.aborted = true; return; }
        const pos = e2.samples.map(s => s.po).filter(v => v != null), swrs = e2.samples.map(s => s.swr).filter(v => v != null);
        const pct = Math.max(this.o.power, this.model && this.model.minPct || 0);
        if (!pos.length) this.result("E2", "na", "Puissance (Po) non lue par la CAT.");
        else {
          const po = pos.reduce((a, b) => a + b, 0) / pos.length, w = this.model ? po * this.model.maxW / 100 : null;
          const txt = `${po.toFixed(0)} %${w != null ? " (" + fr(w, 1) + " W)" : ""} pour ${pct} % demandés`;
          if (po < 1) this.result("E2", "echec", `Aucune puissance mesurée en ${carrier} : ${txt}.`, { po_pct: po });
          else if (po > pct * 2.5 || po < pct / 2.5) this.result("E2", "avert", `Puissance éloignée de la consigne : ${txt}.`, { po_pct: po });
          else this.result("E2", "ok", `${txt}.`, { po_pct: po, watts: w });
        }
        this.step("E3", "cur");
        if (!swrs.length) this.result("E3", "na", "TOS non lu par la CAT.");
        else { const sw = Math.max(...swrs); this.result("E3", sw > 2 ? "avert" : "ok", `TOS ${fr(sw, 2)}${sw > 2 ? " : vérifiez la charge fictive et son câble" : ""}.`, { swr: sw }); }
      }
      if (this.aborted) return;

      // E4 : tonalité par la carte son en mode données.
      this.step("E4", "cur");
      if (!this.audio || !this.audio.hasOutput()) this.result("E4", "na", "Sortie de la carte son du poste non choisie.");
      else {
        const okMode = await L.setMode(MODE_CODES.USB, (m0 && m0.filter) || 1);
        const okData = okMode && await L.setDataMode(1, (m0 && m0.filter) || 1);
        const rd = okData ? await L.readDataMode() : null;
        if (!okData || !rd || !rd.on) this.result("E4", "na", "Mode données non réglable par la CAT.");
        else {
          this.now("E4 : tonalité 1 kHz par la carte son, en USB-D…");
          let toneErr = null;
          try { await this.audio.startTone(); } catch (e) { toneErr = String(e && e.message || e); }
          const e4 = toneErr ? null : await this._emit("E4", this.o.e4, { what: "Tonalité 1 kHz par la carte son", mode: "USB-D" });
          if (toneErr) this.result("E4", "echec", "Sortie de la carte son impossible à ouvrir : " + toneErr + ".");
          try { this.audio.stopTone(); } catch (e) { /* rien */ }
          if (!e4 && !toneErr) return;
          if (e4 && !e4.rx) { this.result("E4", "echec", "Retour en réception NON relu : coupez le poste à la main."); this.aborted = true; return; }
          const pos = e4 ? e4.samples.map(s => s.po).filter(v => v != null) : [], alcs = e4 ? e4.samples.map(s => s.alc).filter(v => v != null) : [];
          const po = pos.length ? Math.max(...pos) : null, alc = alcs.length ? Math.max(...alcs) : null;
          if (toneErr) { /* déjà noté */ }
          else if (po == null) this.result("E4", "na", "Puissance non lue : modulation impossible à vérifier.");
          else if (po < 2) this.result("E4", "echec", "Tonalité envoyée mais aucune puissance : réglage « DATA MOD » du poste sur USB ? volume de la carte son à 100 dans l'ordinateur ?", { po_pct: po, alc_pct: alc });
          else this.result("E4", "ok", `Modulation par la carte son : Po ${po.toFixed(0)} %${alc != null ? ", ALC " + alc.toFixed(0) + " %" + (alc > 50 ? " (hors de la zone ALC : baissez le niveau USB MOD)" : "") : ""}.`, { po_pct: po, alc_pct: alc });
        }
      }
      if (this.aborted) return;

      // E6 : coupure par la page (même chemin que le bouton STOP).
      if (carrier) await L.setMode(MODE_CODES[carrier], 1);
      this.step("E6", "cur"); this.now("E6 : émission puis coupure par la page, comme le bouton STOP…");
      this.emit({ type: "tx-info", code: "E6", ms: this.o.e6, info: { hz: await L.readFreq(), what: "Coupure par la page", mode: carrier || (m0 && m0.name) } });
      await this.guard.key("E6");
      const on = await L.readPtt();
      await this._sampleTx(this.o.e6, "E6");
      const t0 = Date.now();
      const rx = await this.guard.unkey("E6");
      const ms = Date.now() - t0;
      if (!on) this.result("E6", "na", "Émission non relue.");
      else if (!rx) { this.result("E6", "echec", "Retour en réception NON relu : coupez le poste à la main."); this.aborted = true; }
      else this.result("E6", ms < 1000 ? "ok" : "avert", `Réception relue ${ms} ms après l'ordre de coupure.`, { ms });
    }

    async _restore() {
      const L = this.link, o = this.orig;
      this.step("RS", "cur"); this.now("Remise de l'état d'origine…");
      if (this.stopReason === "deja_en_emission") { this.result("RS", "na", "Rien n'a été changé (poste en émission par l'opérateur)."); return; }
      const lines = []; let status = "ok";
      try {
        if (o.mode) await L.setMode(o.mode.code, o.mode.filter);
        if (o.data) await L.setDataMode(o.data.on, o.data.filter);
        if (o.freq != null) await L.setFreq(o.freq);
        if (o.power != null) await L.setPower(o.power);
        const f = await L.readFreq(), m = await L.readMode(), d = o.data ? await L.readDataMode() : null, p = o.power != null ? await L.level(CMD.RF_POWER) : null;
        if (o.freq != null) { if (f === o.freq) lines.push(`fréquence ${fmtHz(f)}`); else { status = "avert"; lines.push(`fréquence relue ${fmtHz(f)} au lieu de ${fmtHz(o.freq)}`); } }
        if (o.mode) { if (m && m.code === o.mode.code) lines.push(`mode ${m.name}`); else { status = "avert"; lines.push(`mode relu ${m ? m.name : "—"} au lieu de ${o.mode.name}`); } }
        if (o.data) { if (d && d.on === o.data.on) lines.push(o.data.on ? "mode données remis" : "mode données coupé"); else { status = "avert"; lines.push("mode données à vérifier"); } }
        if (o.power != null) { if (p != null && Math.abs(p - o.power) <= 2) lines.push(`puissance ${Math.round(o.power / 2.55)} %`); else { status = "avert"; lines.push(`puissance à remettre à la main (${Math.round(o.power / 2.55)} %)`); } }
        const ptt = await L.readPtt();
        if (ptt === true) { status = "echec"; lines.push("POSTE EN ÉMISSION : coupez-le à la main"); }
      } catch (e) { status = "echec"; lines.push("remise interrompue : " + (e && e.message || e)); }
      this.result("RS", status, lines.length ? lines.join(", ") + "." : "Rien à remettre.");
    }
  }

  const api = { DEFAULTS, STEPS, FUNCS, TxGuard, Runner, detect, fmtHz };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtRunner = api;
})(typeof window !== "undefined" ? window : globalThis);
