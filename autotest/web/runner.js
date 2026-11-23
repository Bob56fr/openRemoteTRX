// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, enchaînement des essais (docs/prequalif-web-cahier-des-charges.md § 4 à § 6) : détection,
   réception R1 à R10, autorisation unique, émissions E1 à E4 et E6, remise de l'état d'origine.
   Sécurités gardées (§ 5) : AUCUNE émission avant l'autorisation ; chaque émission coupée par la garde au plus tard à
   `maxTx` (10 s), même si l'essai ou la page se bloque ; STOP, erreur, onglet caché = retour en réception ; PTT relu
   après chaque retour ; état d'origine remis dans tous les cas. Indépendant de la page : testé sous Node. */
(function (root) {
  "use strict";
  const civ = (typeof module !== "undefined" && module.exports) ? require("./civ.js") : root.AtCiv;
  const { T } = (typeof module !== "undefined" && module.exports) ? require("./i18n.js") : root.AtI18n;

  const DEFAULTS = { e1: 3000, e2: 5000, e4: 8000, e6: 2000, sample: 200, maxTx: 10000, settle: 150, power: 10, scope: 3000, tune: 15000, rampPower: 50 };
  // E4 : paliers de la tonalité (dBFS crête), de faible à fort. Coude conseillé : -10 à -4 dBFS (la voix de la station
  // a ses crêtes à -1 dBFS par son limiteur : elle atteint alors la pleine puissance sans trop pousser l'ALC).
  const RAMP = [-30, -26, -22, -18, -14, -10, -7, -4, -1];
  const KNEE_LOW = -10, KNEE_HIGH = -4, KNEE_TARGET = -6;

  const STEPS = [
    ["R1", "Port et vitesse"], ["R2", "Modèle identifié"], ["R3", "Fréquence et mode lus"], ["R4", "S-mètre"],
    ["R5", "Temps de réponse"], ["R6", "PTT lu"], ["R7", "Carte son du poste"], ["R8", "Écriture de fréquence et de mode"],
    ["R9", "Fonctions du poste (ATT, P.AMP, NB, NR, RIT, split, VFO…)"], ["R10", "Spectre (waterfall du poste)"],
    ["E1", "Émission par la CAT"], ["E2", "Puissance lue"], ["E3", "TOS lu"], ["E4", "Tonalité 1 kHz"],
    ["E6", "STOP de la page"], ["E7", "Accord du coupleur d'antenne"], ["RS", "Remise de l'état d'origine"],
  ];

  const FUNCS = civ.FUNCS;                                  // compatibilité (fonctions Icom)
  const STATUS_FN = { ok: "OK", absent: "absente", refus: "écriture refusée", ecart: "relue fausse", remise: "NON REMISE", plante: "lecture qui fait tomber rigctld" };

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
    /* Accord du coupleur (essai E7) : émission lancée par le POSTE, pas par le PTT. Même garde : autorisation exigée,
       coupure armée AVANT, au plus `maxMs` (15 s, décision de l'utilisateur du 2026-11-23) ; une coupure met d'abord
       le coupleur hors service (arrêt de l'accord) puis renvoie la réception, relue. */
    startTune(label, maxMs) {
      if (!this.armed) throw new Error("accord refusé : pas d'autorisation");
      if (this.on) throw new Error("accord refusé : émission en cours");
      this.on = true; this.tuning = true; this.since = Date.now(); this.label = label;
      this.timer = setTimeout(() => { this.unkey("duree_max"); }, maxMs);
      this.onChange({ on: true, label, maxTx: maxMs });
    }
    // Fin normale d'un accord : le coupleur reste dans l'état choisi par le poste (pas d'arrêt d'urgence).
    endTune() { this.tuning = false; }
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
      const wasOn = this.on, wasTuning = !!this.tuning;
      this.tuning = false;
      clearTimeout(this.timer); this.timer = null;
      if (this.audio) { try { this.audio.stopTone(); } catch (e) { /* rien */ } }
      this.unkeying = (async () => {
        let rx = null;
        if (wasTuning && this.link.tunerAbortNow) { try { await this.link.tunerAbortNow(); } catch (e) { /* port perdu */ } }
        for (let i = 0; i < 3; i++) {
          try { await this.link.pttOffNow(); } catch (e) { /* port perdu : rien d'autre à faire */ }
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
      if (model && model.att) link.attValues = model.att;
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
      if (d.hamlib) this.result("R1", "ok", d.baud ? T("Le poste répond par Hamlib à {baud} bauds.", { baud: d.baud }) : T("Le poste répond par Hamlib (vitesse par défaut du modèle)."), { baud: d.baud || null });
      else this.result("R1", "ok", T("Le poste répond à {baud} bauds.", { baud: d.baud }), { baud: d.baud });
      this._r2();
      try {
        await this._reception();
        if (this.aborted) return this._finish();
        const go = await this._authorize();
        if (go && !this.aborted) await this._emissions();
        else for (const c of ["E1", "E2", "E3", "E4", "E6", "E7"]) if (!this.results.find(r => r.code === c)) this.result(c, "saute", go ? T("Essais arrêtés.") : T("Émissions non autorisées."));
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
    _finish() { this.emit({ type: "done", results: this.results }); return { results: this.results, samples: this.samples, orig: this.orig, stop: this.stopReason || null,
                                                                      tuner: this.orig.tuner == null ? null : this.orig.tuner, tunerDeclared: this.tunerDeclared || null }; }

    _r2() {
      const d = this.detected, m = this.model, hexA = a => a.toString(16).toUpperCase().padStart(2, "0") + "h";
      if (d.hamlib) {                                               // mode B : modèle choisi dans la liste de Hamlib
        // Statut du pilote dans Hamlib : « Beta » est le cas de la plupart des postes récents (IC-7300MK2, validé par
        // openRemoteTRX) : simple information, les essais suivants disent ce qui marche. Alpha, Untested, Buggy : à vérifier.
        const h = d.hamlib, stable = !h.statut || /^stable$/i.test(h.statut), beta = /^beta$/i.test(h.statut || "");
        this.result("R2", stable || beta ? "ok" : "avert", stable ? T("Hamlib : {name} (modèle {n}, Hamlib {v}).", { name: h.nom, n: h.n, v: h.version || "?" })
          : beta ? T("Hamlib : {name} (modèle {n}, Hamlib {v}), pilote au statut « {s} » (courant dans Hamlib) : les essais suivants disent ce qui marche.", { name: h.nom, n: h.n, v: h.version || "?", s: h.statut })
          : T("Hamlib : {name} (modèle {n}, Hamlib {v}), pilote Hamlib au statut « {s} » : des fonctions peuvent manquer.", { name: h.nom, n: h.n, v: h.version || "?", s: h.statut }), { hamlib_model: h.n });
        return;
      }
      if (d.ident != null) {                                         // Yaesu : identité « ID; »
        if (m && m.ident === d.ident) this.result("R2", "ok", T("{name} reconnu (identité {id}).", { name: m.name, id: d.ident }), { ident: d.ident });
        else if (d.guess) this.result("R2", "ok", T("Poste reconnu : {name} (identité {id}).", { name: d.guess.name, id: d.ident }), { ident: d.ident });
        else this.result("R2", "avert", m ? T("Identité {id} : modèle inconnu de la table, pas celle du {name}.", { id: d.ident, name: m.name }) : T("Identité {id} : modèle inconnu de la table.", { id: d.ident }), { ident: d.ident });
        return;
      }
      if (!m) this.result("R2", d.guess ? "ok" : "avert", d.guess ? T("Poste reconnu : {name} (adresse {addr}).", { name: d.guess.name, addr: hexA(d.addr) }) : T("Poste à l'adresse {addr}, modèle inconnu de la table.", { addr: hexA(d.addr) }), { addr: d.addr });
      else if (d.addr === m.addr) this.result("R2", "ok", d.idSupported ? T("{name} reconnu à son adresse {addr}.", { name: m.name, addr: hexA(d.addr) }) : T("{name} reconnu à son adresse {addr} (identité non gérée par le poste, fréquence lue).", { name: m.name, addr: hexA(d.addr) }), { addr: d.addr });
      else this.result("R2", "avert", T("Le poste répond à l'adresse {addr}{guess}, pas à celle du {name} ({maddr}) : adresse CI-V changée dans le poste, ou autre modèle.", { addr: hexA(d.addr), guess: d.guess ? " (" + d.guess.name + " ?)" : "", name: m.name, maddr: hexA(m.addr) }), { addr: d.addr });
    }

    async _timed(fn) { const t = Date.now(); const v = await fn(); this.timings.push(Date.now() - t); return v; }

    async _reception() {
      const L = this.link;
      // R3
      this.step("R3", "cur"); this.now(T("Lecture de la fréquence et du mode…"));
      const f1 = await this._timed(() => L.readFreq()), m1 = await this._timed(() => L.readMode());
      const f2 = await this._timed(() => L.readFreq()), m2 = await this._timed(() => L.readMode());
      this.orig.freq = f1; this.orig.mode = m1;
      if (f1 == null || m1 == null) this.result("R3", "echec", T("Fréquence ou mode illisible."));
      else if (f1 !== f2 || m1.code !== m2.code) this.result("R3", "avert", T("Deux lectures différentes : quelqu'un touche le poste ?"), { f1, f2 });
      else this.result("R3", "ok", T("{f} MHz, {mode}.", { f: fmtHz(f1), mode: m1.name }), { hz: f1, mode: m1.name, filter: m1.filter });
      this.orig.data = await L.readDataMode();
      this.orig.power = await L.meter("power");
      if (this.aborted) return;
      // R4
      this.step("R4", "cur"); this.now(T("Lecture du S-mètre…"));
      const s = [];
      for (let i = 0; i < 8 && !this.aborted; i++) { s.push(await this._timed(() => L.meter("s"))); await this.wait(150); }
      const got = s.filter(v => v != null);
      if (!got.length) this.result("R4", "na", T("S-mètre non lu par la CAT."));
      else this.result("R4", "ok", T("De {a} à {b}.", { a: L.scale.sText(Math.min(...got)), b: L.scale.sText(Math.max(...got)) }), { raw: got });
      // R5
      this.step("R5", "cur"); this.now(T("Mesure du temps de réponse…"));
      const t = this.timings.slice().sort((a, b) => a - b);
      const med = t.length ? t[Math.floor(t.length / 2)] : null, max = t.length ? t[t.length - 1] : null;
      if (med == null) this.result("R5", "na", T("Aucune mesure."));
      else this.result("R5", med > 200 ? "avert" : "ok", T("Médiane {med} ms, pire {max} ms sur {n} lectures.", { med, max, n: t.length }), { median_ms: med, max_ms: max, n: t.length });
      // R6
      this.step("R6", "cur"); this.now(T("Lecture du PTT…"));
      const ptt = await L.readPtt();
      this.pttReadable = ptt !== null;
      // Coupleur d'antenne : LU seulement (0 / 1 ; 2 = accord en cours, compté comme en service) ; null = pas vu.
      this.orig.tuner = null;
      if (L.tunerRead) { const tn = await L.tunerRead(); this.orig.tuner = tn == null ? null : (tn ? 1 : 0); }
      if (ptt === true) { this.result("R6", "echec", T("Le poste est DÉJÀ en émission : essais arrêtés (la page ne touche pas à une émission de l'opérateur).")); this.aborted = true; this.stopReason = "deja_en_emission"; return; }
      if (ptt === null) this.result("R6", "avert", T("PTT illisible par la CAT : les émissions d'essai ne seront pas faites (retour en réception impossible à vérifier)."));
      else this.result("R6", "ok", L.pttTracked ? T("Réception (ce poste ne se lit pas en émission par la CAT : état suivi par ses annonces automatiques AI, mises en marche pour l'essai).") : T("Réception."));
      // R7
      this.step("R7", "cur"); this.now(T("Carte son du poste…"));
      await this._audio();
      if (this.aborted) return;
      // R8
      this.step("R8", "cur"); this.now(T("Écriture de la fréquence (+1 kHz) puis du mode…"));
      await this._r8();
      if (this.aborted) return;
      // R9
      this.step("R9", "cur"); this.now(T("Fonctions du poste : lecture, changement, relecture, remise…"));
      await this._r9();
      if (this.aborted) return;
      // R10
      this.step("R10", "cur"); this.now(T("Spectre du poste : sortie des données mise en marche, balayages comptés…"));
      await this._r10();
    }

    /* R10, SANS émission : affichage et sortie du spectre lus, mis en marche, trames 27 00 écoutées `scope` ms, puis
       remis comme ils étaient (et revérifiés dans la remise finale). Icom (mode A) seulement. */
    async _r10() {
      const L = this.link;
      if (!L.scopeCapture) {
        this.result("R10", "na", this.detected.hamlib ? T("Spectre non lu par Hamlib (mode B) : essai du mode A, postes Icom.") : T("Spectre non essayé pour cette marque (postes Icom seulement)."));
        return;
      }
      const s0 = await L.scopeRead();
      if (s0.display == null || s0.output == null) { this.result("R10", "na", T("Spectre non géré par ce poste en CI-V (commandes 27 10 / 27 11 refusées ou sans réponse).")); return; }
      this.orig.scope = s0;
      let st = null, on = false;
      try {
        on = await L.scopeSet(1, 1);
        if (on && !this.aborted) st = await L.scopeCapture(this.o.scope, ms => this.wait(ms));
      } finally {
        await L.scopeSet(s0.display, s0.output);
      }
      if (this.aborted) { this.result("R10", "saute", T("Essais arrêtés.")); return; }
      if (!on) { this.result("R10", "avert", T("Mise en marche du spectre refusée par le poste.")); return; }
      const back = await L.scopeRead();
      const restored = back.display === s0.display && back.output === s0.output;
      const vals = { trames: st.frames, autres: st.other, balayages: st.sweeps, incomplets: st.incomplete, illisibles: st.unreadable,
                     points: st.lengths, formes: st.layouts, niveau_min: st.levelMin, niveau_max: st.levelMax, remis: restored,
                     octets_non_traces: st.untraced };
      const parts = []; let status = "ok";
      if (!st.frames) {
        status = "avert";
        parts.push(st.other ? T("{n} trames du spectre reçues pour un autre contrôleur, aucune pour la page : station ou autre logiciel ouvert ?", { n: st.other })
                            : T("aucune donnée du spectre reçue : sortie du spectre réservée à un autre port USB sur ce modèle, ou vitesse CI-V USB à régler sur « Auto » ?"));
      } else if (!st.sweeps) {
        status = "avert";
        parts.push(T("{n} trames reçues mais aucun balayage complet (vitesse trop basse ?)", { n: st.frames }));
      } else {
        const dur = st.lastT - st.firstT, rate = st.sweeps > 1 && dur > 0 ? (st.sweeps - 1) / dur : null;
        const lens = Object.keys(st.lengths).map(Number), main = lens.sort((a, b) => st.lengths[b] - st.lengths[a])[0];
        const edges = civ.scopeEdges(st.last), hz = this.orig.freq;
        vals.par_seconde = rate == null ? null : Math.round(rate * 10) / 10;
        vals.bornes_hz = edges; vals.mode = st.last.mode; vals.hors_plage = st.last.outOfRange;
        vals.apercu = civ.scopePreview(st.last.points, 64);
        parts.push(T("{n} balayages de {p} points{r}", { n: st.sweeps, p: main, r: rate != null ? T(" ({r} par seconde)", { r: fr(rate, 1) }) : "" }));
        if (lens.length > 1) { status = "avert"; parts.push(T("longueurs différentes : {l}", { l: lens.join(", ") })); }
        if (st.levelMax > civ.LEVEL_MAX) { status = "avert"; parts.push(T("niveaux hors de l'échelle (jusqu'à {v})", { v: st.levelMax })); }
        else if (st.levelMax === 0) { status = "avert"; parts.push(T("spectre plat à zéro : niveau de référence ou antenne ?")); }
        if (!edges) { status = "avert"; parts.push(T("fréquences du balayage illisibles")); }
        else if (hz != null && (hz < edges[0] || hz > edges[1])) { status = "avert"; parts.push(T("fréquence du poste {f} hors du balayage ({a} à {b})", { f: fmtHz(hz), a: fmtHz(edges[0]), b: fmtHz(edges[1]) })); }
        else parts.push(T("de {a} à {b} MHz", { a: fmtHz(edges[0]), b: fmtHz(edges[1]) }));
        if (st.incomplete || st.unreadable) parts.push(T("{n} balayage(s) incomplet(s) ou illisible(s)", { n: st.incomplete + st.unreadable }));
        if (st.other) parts.push(T("{n} trames pour un autre contrôleur", { n: st.other }));
      }
      if (!restored) { status = "echec"; parts.push(T("affichage ou sortie du spectre NON REMIS (à remettre à la main)")); }
      this.result("R10", status, parts.join(" ; ") + ".", vals);
    }

    async _r9() {
      const L = this.link, same = (a, b) => a != null && b != null && String(a) === String(b);
      const out = [], changed = [];
      try {
        for (const f of L.funcs) {
          if (this.aborted) break;
          this.now(T("Fonction {code} : lecture, changement, relecture, remise…", { code: f.code }));
          const row = { code: f.code, label: f.label };
          // Mode B : une lecture peut faire tomber rigctld (IC-7300MK2 + Hamlib 4.7.2, « l ATT », 2026-11-23) : relancé par
          // le programme, lecture refaite UNE fois ; un second plantage = défaut de Hamlib signalé, jamais « absente ».
          let v0 = await L.fnRead(f);
          if (v0 == null && L.lastErr === "rigctld_tombe") v0 = await L.fnRead(f);
          if (v0 == null) { row.statut = L.lastErr === "rigctld_tombe" ? "plante" : "absent"; out.push(row); continue; }
          row.avant = v0;
          let v1 = L.fnOther(f, v0); row.essai = v1;
          const w = await L.fnWrite(f, v1);
          if (!w.ok) { row.statut = w.ng ? "refus" : "absent"; out.push(row); continue; }
          if (w.written) { v1 = w.written; row.essai = v1; }
          changed.push({ f, v0 });
          // Une lecture perdue (mode B : rigctld tombé puis relancé, IC-7300MK2 + Hamlib 4.7.2 sur « l ATT » le
          // 2026-11-23) n'est pas un poste mal remis : relue une seconde fois avant de conclure.
          let relost = false;
          const reread = async () => { const v = await L.fnRead(f); if (v != null) return v; relost = true; return L.fnRead(f); };
          const r1 = await reread(); row.relu = r1;
          await L.fnWrite(f, v0);
          const r2 = await reread(); row.remis = r2;
          if (relost) row.note = T("lecture perdue puis refaite (liaison avec le poste reprise)");
          const near = L.fnNear(f, r1, v1);                    // niveau arrondi au cran du poste (voir civ.js)
          if (near && !same(r1, v1)) row.note = (row.note ? row.note + " ; " : "") + T("arrondi au cran du poste (écrit {w}, relu {r})", { w: L.fnShow(v1), r: L.fnShow(r1) });
          const back = same(r2, v0) || L.fnNear(f, r2, v0);
          if (back && !same(r2, v0)) row.note = (row.note ? row.note + " ; " : "") + T("remis au cran du poste (avant {a}, relu {b})", { a: L.fnShow(v0), b: L.fnShow(r2) });
          row.statut = !back ? "remise" : !(same(r1, v1) || near) ? "ecart" : "ok";
          out.push(row);
        }
        out.push(await this._vfo());
      } finally {
        // Seconde passe : une fonction peut en changer une autre (P.AMP coupe l'ATT…) : tout est relu et remis.
        for (const { f, v0 } of changed) {
          const now = await L.fnRead(f);
          if (same(now, v0) || L.fnNear(f, now, v0)) {
            // Remise qu'on n'avait pas pu relire (lecture perdue deux fois) : le poste est bien revenu.
            const row = out.find(x => x.code === f.code);
            if (row && row.statut === "remise") { row.remis = now; row.repasse = true; row.statut = (same(row.relu, row.essai) || L.fnNear(f, row.relu, row.essai)) ? "ok" : "ecart"; }
            continue;
          }
          await L.fnWrite(f, v0);
          const back = await L.fnRead(f);
          const row = out.find(x => x.code === f.code);
          if (row) { row.remis = back; row.statut = (same(back, v0) || L.fnNear(f, back, v0)) ? (row.statut === "remise" ? "ecart" : row.statut) : "remise"; row.repasse = true; }
        }
      }
      const by = s => out.filter(x => x.statut === s).map(x => x.code);
      const ok = by("ok"), abs = by("absent"), ref = by("refus"), ec = by("ecart"), bad = by("remise"), crash = by("plante");
      const parts = [];
      if (ok.length) parts.push(T("{n} OK : {list}", { n: ok.length, list: ok.join(", ") }));
      if (ec.length) parts.push(T("relues fausses : {list}", { list: ec.join(", ") }));
      if (ref.length) parts.push(T("écriture refusée : {list}", { list: ref.join(", ") }));
      if (abs.length) parts.push(T("absentes : {list}", { list: abs.join(", ") }));
      if (crash.length) parts.push(T("lecture qui fait tomber rigctld (défaut de Hamlib, fonction non touchée) : {list}", { list: crash.join(", ") }));
      if (bad.length) parts.push(T("NON REMISES (à remettre à la main) : {list}", { list: bad.join(", ") }));
      const status = bad.length ? "echec" : (ec.length || ref.length || crash.length) ? "avert" : ok.length ? "ok" : "na";
      const tn = this.orig.tuner;
      if (tn != null) parts.push(tn ? T("coupleur en service (lu, essayé en émission : E7)") : T("coupleur hors service (lu, essayé en émission : E7)"));
      this.result("R9", status, parts.join(" ; ") + ".", { fonctions: out, coupleur_lu: tn == null ? null : tn });
    }

    // VFO A / B : échange, relecture, échange de nouveau, relecture (on ne sait pas lire QUEL VFO est choisi).
    async _vfo() {
      const L = this.link, row = { code: "VFO A/B", label: T("Échange des VFO A et B") };
      const f0 = await L.readFreq(), o0 = await L.vfoOther();
      if (f0 == null) { row.statut = "absent"; return row; }
      const w = await L.vfoSwap();
      if (!w.ok) { row.statut = w.ng ? "refus" : "absent"; return row; }
      const f1 = await L.readFreq();
      await L.vfoSwap();
      const f2 = await L.readFreq();
      row.avant = fmtHz(f0); row.autre = o0 == null ? null : fmtHz(o0); row.relu = fmtHz(f1); row.remis = fmtHz(f2);
      if (f2 !== f0) row.statut = "remise";
      else if (o0 != null) row.statut = f1 === o0 ? "ok" : "ecart";
      else { row.statut = "ok"; if (f1 === f0) row.note = T("fréquences A et B peut-être identiques : échange non vérifiable"); }
      return row;
    }

    async _audio() {
      const a = this.audio;
      const chosen = a ? await this.ui.chooseAudio() : null;
      if (!chosen || !a.hasInput()) { this.result("R7", "na", T("Carte son du poste non choisie.")); return; }
      const db = await a.measureInput(1500);
      if (db == null) this.result("R7", "echec", T("Entrée de la carte son illisible."));
      else if (!isFinite(db) || db < -100) this.result("R7", "avert", T("Entrée de la carte son muette (silence numérique) : réglages du son du poste ou de l'ordinateur."), { dbfs: null });
      else this.result("R7", "ok", a.hasOutput() ? T("Entrée trouvée, bruit de réception {db} dBFS, sortie choisie pour la tonalité.", { db: db.toFixed(0) }) : T("Entrée trouvée, bruit de réception {db} dBFS.", { db: db.toFixed(0) }), { dbfs: Math.round(db) });
    }

    async _r8() {
      const L = this.link, f0 = this.orig.freq, m0 = this.orig.mode;
      if (f0 == null || m0 == null) { this.result("R8", "na", T("Fréquence d'origine inconnue.")); return; }
      const lines = []; let status = "ok";
      let target = f0 + 1000, okF = await L.setFreq(target);
      if (!okF) { target = f0 - 1000; okF = await L.setFreq(target); }
      const rf = okF ? await L.readFreq() : null;
      if (!okF) { status = "avert"; lines.push(T("fréquence non réglable par la CAT")); }
      else if (rf !== target) { status = "avert"; lines.push(T("fréquence écrite {w}, relue {r}", { w: fmtHz(target), r: fmtHz(rf) })); }
      else lines.push(T("fréquence {f} écrite et relue", { f: fmtHz(target) }));
      if (okF) await L.setFreq(f0);
      const other = m0.name === "USB" ? "LSB" : "USB";
      const okM = await L.setMode(L.modeCode(other), m0.filter);
      const rm = okM ? await L.readMode() : null;
      if (!okM) { status = "avert"; lines.push(T("mode non réglable par la CAT")); }
      else if (!rm || rm.name !== other) { status = "avert"; lines.push(T("mode {w} écrit, relu {r}", { w: other, r: rm ? rm.name : "—" })); }
      else lines.push(T("mode {m} écrit et relu", { m: other }));
      if (okM) await L.setMode(m0.code, m0.filter);
      const back = await L.readFreq(), bm = await L.readMode();
      if (back !== f0 || !bm || bm.code !== m0.code) { status = "avert"; lines.push(T("état d'origine pas encore relu (remis à la fin)")); }
      this.result("R8", status, lines.join(" ; ") + ".", { written_hz: target });
    }

    async _authorize() {
      this.step("AU", "cur");
      if (!this.pttReadable) { this.now(T("Émissions sautées : PTT illisible.")); return false; }
      const pct = Math.max(this.o.power, this.model && this.model.minPct || 0);
      const maxW = this.model ? this.model.maxW : null;
      const info = { hz: this.orig.freq, mode: this.orig.mode && this.orig.mode.name, pct, watts: maxW ? maxW * pct / 100 : null, maxW,
                     emissions: [["E1", T("émission par la CAT, sans modulation"), this.o.e1], ["E2", T("porteuse en FM : puissance et TOS"), this.o.e2],
                                 ["E4", T("tonalité 1 kHz en mode données, montée par paliers de -30 à -1 dBFS, à {r} % de la puissance{w}", { r: this.o.rampPower, w: maxW ? T(" ({w} W)", { w: Math.round(maxW * this.o.rampPower / 100) }) : "" }), this.o.e4],
                                 ["E6", T("coupure par la page (STOP)"), this.o.e6]] };
      if (this.orig.tuner != null) {
        info.tuner = this.orig.tuner;
        info.emissions.push(["E7", T("accord du coupleur d'antenne (le poste choisit le mode et la puissance : CW, environ 10 W avec un AH-4)"), this.o.tune]);
      }
      this.now(T("En attente de l'autorisation d'émettre…"));
      const a = await this.ui.authorize(info);
      const ok = a === true || !!(a && a.ok);
      // Modèle du coupleur DÉCLARÉ par l'opérateur : gardé tel quel dans le rapport, jamais une preuve.
      this.tunerDeclared = a && a.tuner ? { type: String(a.tuner.type || "").slice(0, 20), texte: String(a.tuner.texte || "").slice(0, 40) } : null;
      if (!ok || this.aborted) return false;
      // Puissance : 10 % (ou le minimum du poste), relue.
      this.testPct = pct;
      const raw = this.link.powerRaw(pct);
      const set = this.orig.power != null && await this.link.setPower(raw);
      const back = set ? await this.link.meter("power") : null;
      this.powerSet = this.link.powerClose(back, raw);
      if (!this.powerSet) {
        const manual = await this.ui.confirmManualPower(info);
        if (!manual || this.aborted) return false;
      }
      this.guard.arm();
      return true;
    }

    /* E4 : rampe de la tonalité 1 kHz (décision de l'utilisateur du 2026-11-23 : poste à 50 % pendant la rampe), une
       seule émission (garde de 10 s). Palier par palier : Po et ALC lus une fois le palier établi. Le « coude » = premier
       palier où la puissance atteint 90 % de son maximum ; il dit si le niveau USB MOD du poste est trop fort ou trop
       faible pour la voix de la station. Puissance des essais remise juste après. */
    async _rampE4() {
      const L = this.link;
      const rampPct = this.powerSet ? Math.max(this.o.rampPower, this.model && this.model.minPct || 0) : null;
      const target = rampPct != null ? rampPct : this.testPct;
      this.now(T("E4 : tonalité 1 kHz montée par paliers ({p} % de la puissance), en {m}…", { p: target, m: L.dataLabel }));
      if (rampPct != null) await L.setPower(L.powerRaw(rampPct));
      let toneErr = null, steps = [], rx = true;
      try { await this.audio.startTone(RAMP[0]); } catch (e) { toneErr = String(e && e.message || e); }
      try {
        if (!toneErr && !this.aborted) {
          this.emit({ type: "tx-info", code: "E4", ms: this.o.e4, info: { hz: await L.readFreq(), what: T("Tonalité 1 kHz montée par paliers"), mode: L.dataLabel } });
          await this.guard.key("E4");
          const per = this.o.e4 / RAMP.length;
          for (const db of RAMP) {
            if (this.aborted || !this.guard.on) break;
            try { this.audio.setToneLevel(db); } catch (e) { /* sortie perdue : vu par la puissance */ }
            const smp = await this._sampleTx(per, "E4");
            for (const s of smp) s.dbfs = db;
            const late = smp.slice(Math.floor(smp.length / 2));                 // palier établi
            const pos = late.map(s => s.po).filter(v => v != null), alcs = late.map(s => s.alc).filter(v => v != null);
            steps.push({ dbfs: db, po: pos.length ? Math.max(...pos) : null, alc: alcs.length ? Math.max(...alcs) : null });
          }
          rx = await this.guard.unkey(this.aborted ? (this.stopReason || "stop") : "fin_essai");
        }
      } finally {
        try { this.audio.stopTone(); } catch (e) { /* rien */ }
        if (rampPct != null) await L.setPower(L.powerRaw(this.testPct));
      }
      if (toneErr) { this.result("E4", "echec", T("Sortie de la carte son impossible à ouvrir : {e}.", { e: toneErr })); return; }
      if (!rx) { this.result("E4", "echec", T("Retour en réception NON relu : coupez le poste à la main.")); this.aborted = true; return; }
      if (this.aborted) { this.result("E4", "saute", T("Essais arrêtés.")); return; }
      const vals = { puissance_pct: target, rampe: steps };
      const pos = steps.map(s => s.po).filter(v => v != null);
      if (!pos.length) { this.result("E4", "na", T("Puissance non lue : modulation impossible à vérifier."), vals); return; }
      const pmax = Math.max(...pos); vals.po_pct = pmax;
      if (pmax < 2) { this.result("E4", "echec", T("Tonalité envoyée mais aucune puissance : réglage « DATA MOD » du poste sur USB ? volume de la carte son à 100 dans l'ordinateur ?"), vals); return; }
      const knee = steps.find(s => s.po != null && s.po >= 0.9 * pmax);
      vals.coude_dbfs = knee.dbfs; vals.alc_pct = knee.alc;
      const alc = knee.alc != null ? T(", ALC {a} % au coude", { a: knee.alc.toFixed(0) }) : "";
      const head = T("Rampe de -30 à -1 dBFS à {t} % : Po maximale {p} %{alc}", { t: target, p: pmax.toFixed(0), alc });
      let status = "ok", advice;
      if (pmax < 0.8 * target) { status = "avert"; advice = T("même à -1 dBFS, la puissance réglée n'est pas atteinte : niveau USB MOD du poste trop faible, montez-le (volume de la sortie de l'ordinateur à 100)"); }
      else if (knee.dbfs < KNEE_LOW) { status = "avert"; advice = T("pleine puissance dès {k} dBFS : niveau USB MOD du poste trop fort, baissez-le d'environ {d} dB", { k: knee.dbfs, d: KNEE_TARGET - knee.dbfs }); }
      else if (knee.dbfs > KNEE_HIGH) { status = "avert"; advice = T("pleine puissance seulement vers {k} dBFS : niveau USB MOD du poste un peu faible, montez-le d'environ {d} dB", { k: knee.dbfs, d: knee.dbfs - KNEE_TARGET }); }
      else advice = T("pleine puissance vers {k} dBFS : niveau USB MOD du poste bien réglé", { k: knee.dbfs });
      this.result("E4", status, head + " ; " + advice + ".", vals);
    }

    async _sampleTx(ms, label) {
      const L = this.link, out = [], end = Date.now() + ms;
      const read = async key => {
        if (this.na.has(key)) return null;
        const v = await L.meter(key);
        if (v == null) { this.naMiss = this.naMiss || {}; this.naMiss[key] = (this.naMiss[key] || 0) + 1; if (this.naMiss[key] >= 2) this.na.add(key); }
        return v;
      };
      while (!this.aborted && this.guard.on && Date.now() < end) {
        const po = await read("po"), swr = await read("swr"), alc = await read("alc"), sc = L.scale;
        const s = { t: Date.now(), label,
                    po: po == null ? null : sc.poPercent(po), swr: swr == null ? null : sc.swrValue(swr), alc: alc == null ? null : sc.alcPercent(alc),
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
      this.now(T("E1 : émission par la CAT, sans modulation…"));
      const e1 = await this._emit("E1", this.o.e1, { what: T("Émission par la CAT, sans modulation"), mode: m0 && m0.name });
      if (!e1) return;
      if (!e1.rx) { this.result("E1", "echec", T("Retour en réception NON relu : coupez le poste à la main.")); this.aborted = true; return; }
      if (!e1.pttOn) this.result("E1", "echec", (e1.acked ? T("Ordre d'émission accepté mais PTT relu en réception : émission par la CAT impossible ?") : T("Ordre d'émission refusé et PTT relu en réception : émission par la CAT impossible ?")));
      else this.result("E1", "ok", T("Émission relue en {on} ms, réception relue en {off} ms.", { on: e1.tOn, off: e1.tOff }), { t_on_ms: e1.tOn, t_off_ms: e1.tOff });
      if (!e1.pttOn || this.aborted) return;

      // E2 / E3 : porteuse (FM, sinon RTTY, sinon AM).
      let carrier = null;
      for (const name of ["FM", "RTTY", "RTTY-U", "AM"]) { if (L.modeCode(name) != null && await L.setMode(L.modeCode(name), 1)) { const rm = await L.readMode(); if (rm && rm.name === name) { carrier = name; break; } } }
      if (!carrier) { this.result("E2", "na", T("Aucun mode à porteuse réglable par la CAT.")); this.result("E3", "na", T("Pas de porteuse.")); }
      else {
        this.now(T("E2 / E3 : porteuse en {m}, lecture de la puissance et du TOS…", { m: carrier }));
        const e2 = await this._emit("E2", this.o.e2, { what: T("Porteuse en {m}", { m: carrier }), mode: carrier });
        if (!e2) return;
        if (!e2.rx) { this.result("E2", "echec", T("Retour en réception NON relu : coupez le poste à la main.")); this.aborted = true; return; }
        const pos = e2.samples.map(s => s.po).filter(v => v != null), swrs = e2.samples.map(s => s.swr).filter(v => v != null);
        // ALC sur la porteuse SANS modulation : chez Icom, une puissance réduite est tenue par l'ALC (IC-7100 : ~130 sur
        // 120 à 10 %) ; sert de référence pour juger l'ALC de la tonalité (E4).
        const alcs2 = e2.samples.map(s => s.alc).filter(v => v != null);
        this.alcCarrier = alcs2.length ? Math.max(...alcs2) : null;
        const pct = Math.max(this.o.power, this.model && this.model.minPct || 0);
        if (!pos.length) this.result("E2", "na", T("Puissance (Po) non lue par la CAT."));
        else {
          const po = pos.reduce((a, b) => a + b, 0) / pos.length, w = this.model ? po * this.model.maxW / 100 : null;
          const txt = T("{po} %{w} pour {pct} % demandés", { po: po.toFixed(0), w: w != null ? " (" + fr(w, 1) + " W)" : "", pct });
          if (po < 1) this.result("E2", "echec", T("Aucune puissance mesurée en {m} : {txt}.", { m: carrier, txt }), { po_pct: po });
          else if (po > pct * 2.5 || po < pct / 2.5) this.result("E2", "avert", T("Puissance éloignée de la consigne : {txt}.", { txt }), { po_pct: po });
          else this.result("E2", "ok", txt + ".", { po_pct: po, watts: w });
        }
        this.step("E3", "cur");
        if (!swrs.length) this.result("E3", "na", T("TOS non lu par la CAT."));
        else { const sw = Math.max(...swrs); this.result("E3", sw > 2 ? "avert" : "ok", (sw > 2 ? T("TOS {s} : vérifiez la charge fictive et son câble.", { s: fr(sw, 2) }) : T("TOS {s}.", { s: fr(sw, 2) })), { swr: sw }); }
      }
      if (this.aborted) return;

      // E4 : tonalité par la carte son en mode données.
      this.step("E4", "cur");
      if (!this.audio || !this.audio.hasOutput()) this.result("E4", "na", T("Sortie de la carte son du poste non choisie."));
      else {
        const okMode = await L.setMode(L.modeCode("USB"), (m0 && m0.filter) || 1);
        const okData = okMode && await L.setDataMode(1, (m0 && m0.filter) || 1);
        const rd = okData ? await L.readDataMode() : null;
        if (!okData || !rd || !rd.on) this.result("E4", "na", T("Mode données non réglable par la CAT."));
        else {
          await this._rampE4();
        }
      }
      if (this.aborted) return;

      // E6 : coupure par la page (même chemin que le bouton STOP).
      if (carrier) await L.setMode(L.modeCode(carrier), 1);
      this.step("E6", "cur"); this.now(T("E6 : émission puis coupure par la page, comme le bouton STOP…"));
      this.emit({ type: "tx-info", code: "E6", ms: this.o.e6, info: { hz: await L.readFreq(), what: T("Coupure par la page"), mode: carrier || (m0 && m0.name) } });
      await this.guard.key("E6");
      const on = await L.readPtt();
      await this._sampleTx(this.o.e6, "E6");
      const t0 = Date.now();
      const rx = await this.guard.unkey("E6");
      const ms = Date.now() - t0;
      if (!on) this.result("E6", "na", T("Émission non relue."));
      else if (!rx) { this.result("E6", "echec", T("Retour en réception NON relu : coupez le poste à la main.")); this.aborted = true; }
      else this.result("E6", ms < 1000 ? "ok" : "avert", T("Réception relue {ms} ms après l'ordre de coupure.", { ms }), { ms });
      if (this.aborted) return;
      await this._e7();
    }

    /* E7 : accord du coupleur, sous la garde (au plus `tune` ms). En service au départ : mis hors service puis remis en
       service. La remise en service lance l'accord sur certains coupleurs (AH-4) ; sinon la page le lance (1C 01 02).
       Fin : 01 = accord réussi, 00 = accord impossible (coupleur en dérivation). État d'origine : hors service remis
       hors service ; en service laissé en service (le remettre lancerait un nouvel accord). */
    async _e7() {
      const L = this.link, t0 = this.orig.tuner, dec = this.tunerDeclared;
      this.step("E7", "cur");
      if (!L.tunerRead) { this.result("E7", "na", T("Essai du coupleur pas encore écrit pour cette marque (postes Icom seulement).")); return; }
      if (t0 == null) { this.result("E7", "na", T("Aucun coupleur d'antenne vu par la CAT.")); return; }
      if (dec && dec.type === "aucun") {
        this.result("E7", t0 ? "avert" : "na", t0 ? T("Coupleur en service alors que « aucun coupleur » a été déclaré : essai sauté.") : T("Aucun coupleur déclaré : essai sauté."), { declare: dec });
        return;
      }
      this.now(T("E7 : accord du coupleur d'antenne…"));
      await L.setMode(L.modeCode((this.orig.mode && this.orig.mode.name) || "USB") ?? L.modeCode("USB"), (this.orig.mode && this.orig.mode.filter) || 1);
      this.emit({ type: "tx-info", code: "E7", ms: this.o.tune, info: { hz: await L.readFreq(), what: T("Accord du coupleur d'antenne"), mode: "CW" } });
      const g = this.guard, t = Date.now(), seen = [];
      let started = false, last = null, startRefused = false, swr = null, po = null;
      g.startTune("E7", this.o.tune);
      try {
        if (t0 === 1) { await L.tunerSet(0); seen.push(await L.tunerRead()); }
        await L.tunerSet(1);
        for (let i = 0; i < 5 && g.on && !this.aborted; i++) {           // accord lancé par le poste lui-même ?
          last = await L.tunerRead(); seen.push(last);
          if (last === 2) { started = true; break; }
          await this.wait(150);
        }
        if (!started && g.on && !this.aborted) {
          const w = await L.tunerStart(g);
          if (w.ok) started = true; else startRefused = true;
        }
        while (started && g.on && !this.aborted) {
          await this.wait(200);
          if (!g.on) break;
          last = await L.tunerRead(); seen.push(last);
          const p = await L.meter("po"), s = await L.meter("swr");
          if (p != null) po = Math.max(po || 0, L.scale.poPercent(p));
          if (s != null && p) swr = L.scale.swrValue(s);
          if (last !== 2) break;
        }
      } finally {
        if (g.on && g.tuning && !this.aborted && last !== 2) g.endTune();
      }
      const timedOut = g.lastStop && g.lastStop.reason === "duree_max" && !g.on;
      const rx = g.on ? await g.unkey("fin_essai") : (g.unkeying ? await g.unkeying : !!(g.lastStop && g.lastStop.rx));
      const secs = fr((Date.now() - t) / 1000, 1), vals = { avant: t0, lu: seen, declare: dec, duree_s: Number(secs.replace(",", ".")), po_pct: po, swr };
      if (!rx) { this.result("E7", "echec", T("Retour en réception NON relu : coupez le poste à la main."), vals); this.aborted = true; return; }
      if (this.aborted && !timedOut) { this.result("E7", "saute", T("Essais arrêtés (accord interrompu, coupleur hors service)."), vals); return; }
      if (timedOut || last === 2) { this.result("E7", "echec", T("Accord non terminé en {s} s : coupleur mis hors service, réception relue.", { s: this.o.tune / 1000 }), vals); return; }
      if (startRefused && !started) { this.result("E7", "avert", T("Coupleur mis en service mais accord refusé par le poste (1C 01 02)."), vals); }
      else if (last === 1) this.result("E7", "ok", T("Accord réussi en {s} s{swr}.", { s: secs, swr: swr != null ? T(", TOS {v} pendant l'accord", { v: fr(swr, 2) }) : "" }), vals);
      else if (last === 0) this.result("E7", "avert", T("Accord impossible : le coupleur s'est mis en dérivation (antenne hors de sa plage, demi-onde ?)."), vals);
      else this.result("E7", "avert", T("État du coupleur illisible après l'accord."), vals);
      if (t0 === 0) { await L.tunerSet(0); }                             // hors service au départ : remis hors service
    }

    async _restore() {
      const L = this.link, o = this.orig;
      this.step("RS", "cur"); this.now(T("Remise de l'état d'origine…"));
      if (this.stopReason === "deja_en_emission") { this.result("RS", "na", T("Rien n'a été changé (poste en émission par l'opérateur).")); return; }
      const lines = []; let status = "ok";
      try {
        if (o.mode) await L.setMode(o.mode.code, o.mode.filter);
        if (o.data) await L.setDataMode(o.data.on, o.data.filter);
        if (o.freq != null) await L.setFreq(o.freq);
        if (o.power != null) await L.setPower(o.power);
        if (o.tuner != null && L.tunerRead) {
          let tn = await L.tunerRead();
          if (o.tuner === 0 && tn) { await L.tunerSet(0); tn = await L.tunerRead(); }
          if (o.tuner === 0 && tn) { status = "avert"; lines.push(T("coupleur à mettre hors service à la main")); }
          if (o.tuner === 1 && tn === 0) { status = "avert"; lines.push(T("coupleur hors service : remettez-le en service à la main (un accord sera lancé)")); }
        }
        if (o.scope && L.scopeRead) {                                // spectre (R10) : déjà remis, revérifié ici
          let sc = await L.scopeRead();
          if (sc.display !== o.scope.display || sc.output !== o.scope.output) { await L.scopeSet(o.scope.display, o.scope.output); sc = await L.scopeRead(); }
          if (sc.display !== o.scope.display || sc.output !== o.scope.output) { status = "avert"; lines.push(T("spectre à remettre à la main")); }
        }
        const f = await L.readFreq(), m = await L.readMode(), d = o.data ? await L.readDataMode() : null, p = o.power != null ? await L.meter("power") : null;
        if (o.freq != null) { if (f === o.freq) lines.push(T("fréquence {f}", { f: fmtHz(f) })); else { status = "avert"; lines.push(T("fréquence relue {r} au lieu de {o}", { r: fmtHz(f), o: fmtHz(o.freq) })); } }
        if (o.mode) { if (m && m.code === o.mode.code) lines.push(T("mode {m}", { m: m.name })); else { status = "avert"; lines.push(T("mode relu {r} au lieu de {o}", { r: m ? m.name : "—", o: o.mode.name })); } }
        if (o.data) { if (d && d.on === o.data.on) lines.push(o.data.on ? T("mode données remis") : T("mode données coupé")); else { status = "avert"; lines.push(T("mode données à vérifier")); } }
        if (o.power != null) { if (L.powerClose(p, o.power)) lines.push(T("puissance {p} %", { p: Math.round(L.powerPct(o.power)) })); else { status = "avert"; lines.push(T("puissance à remettre à la main ({p} %)", { p: Math.round(L.powerPct(o.power)) })); } }
        const ptt = await L.readPtt();
        if (ptt === true) { status = "echec"; lines.push(T("POSTE EN ÉMISSION : coupez-le à la main")); }
        if (L.finish) await L.finish();                              // Kenwood : AI et lecture des mesures remises
      } catch (e) { status = "echec"; lines.push(T("remise interrompue : {e}", { e: e && e.message || e })); }
      this.result("RS", status, lines.length ? lines.join(", ") + "." : T("Rien à remettre."));
    }
  }

  const api = { DEFAULTS, STEPS, FUNCS, TxGuard, Runner, detect, fmtHz };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtRunner = api;
})(typeof window !== "undefined" ? window : globalThis);
