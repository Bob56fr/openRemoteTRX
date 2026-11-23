// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, MODE B (lot PQ5, docs/prequalif-web-cahier-des-charges.md § 8) : le poste est piloté par
   Hamlib, au travers du programme local qui sert la page (`python -m trxstation.autotest`, API /api/…). Même
   interface que les liaisons du mode A (civ.js, yaesu.js, kenwood.js) : le déroulé des essais (runner.js) ne change
   pas. Le programme refuse toute commande hors de SA liste fermée (trxstation/autotest/rig.py) et coupe lui-même une
   émission trop longue ou une page muette.
   Hamlib : niveaux 0-1 (puissance, Po, ALC), S-mètre en dB par rapport à S9, modes par leur nom (USB, PKTUSB…). */
(function (root) {
  "use strict";

  const DATA_OF = { USB: "PKTUSB", LSB: "PKTLSB", FM: "PKTFM", AM: "PKTAM" };
  const BASE_OF = { PKTUSB: "USB", PKTLSB: "LSB", PKTFM: "FM", PKTAM: "AM" };

  const scale = {
    sText: raw => raw == null ? "—" : raw <= 0 ? "S" + Math.max(0, Math.round(9 + raw / 6)) : "S9+" + Math.round(raw) + " dB",
    poPercent: raw => Math.max(0, raw * 100),
    swrValue: raw => raw,
    alcPercent: raw => Math.min(100, Math.max(0, raw * 100)),
  };

  // Fonctions essayées en R9, retenues si Hamlib les déclare en lecture ET en écriture pour ce poste. Jamais : VOX,
  // TUNER (selon le poste, l'écriture lance un accord), split, XIT (refusés aussi par le programme).
  const FUNC_LABELS = { NB: "Noise blanker", NB2: "Noise blanker 2", NR: "Réduction de bruit", ANF: "Notch automatique",
                        COMP: "Processeur de parole", MN: "Notch manuel", APF: "Filtre audio de crête", RIT: "Clarifieur (RIT)" };
  const LEVEL_LABELS = { ATT: "Atténuateur", PREAMP: "Préampli", NR: "Niveau NR", NB: "Niveau NB", COMP: "Niveau du processeur" };
  const FUNC_ORDER = ["ATT", "PREAMP", "NB", "NB2", "NR", "ANF", "COMP", "MN", "APF", "RIT"];

  function buildFuncs(p) {
    if (!p) return [];
    const has = (a, x) => (a || []).includes(x);
    const out = [];
    for (const name of FUNC_ORDER) {
      if (name === "ATT" && (p.attenuateurs_db || []).length && has(p.niveaux_ecriture, "ATT"))
        out.push({ code: "ATT", label: LEVEL_LABELS.ATT, kind: "level", name, values: ["0"].concat(p.attenuateurs_db.map(String)) });
      else if (name === "PREAMP" && (p.preamplis_db || []).length && has(p.niveaux_ecriture, "PREAMP"))
        out.push({ code: "P.AMP", label: LEVEL_LABELS.PREAMP, kind: "level", name, values: ["0"].concat(p.preamplis_db.map(String)) });
      else if (FUNC_LABELS[name] && has(p.fonctions_lecture, name) && has(p.fonctions_ecriture, name))
        out.push({ code: name, label: FUNC_LABELS[name], kind: "func", name, values: ["0", "1"] });
    }
    for (const name of ["NR", "NB", "COMP"]) {                 // niveaux continus : plage déclarée par Hamlib
      const r = (p.plages || {})[name];
      if (r && has(p.niveaux_lecture, name) && has(p.niveaux_ecriture, name) && r.max > r.min)
        out.push({ code: name + " niv.", label: LEVEL_LABELS[name], kind: "level", name, range: [r.min, r.max], step: r.pas || 0 });
    }
    return out;
  }

  const num = v => { const x = Number(v); return Number.isFinite(x) ? x : null; };
  const show = v => { const x = num(v); return x == null ? String(v) : String(Math.round(x * 1000) / 1000); };

  class HamlibLink {
    /* api : { cmd(ligne) -> Promise<{rprt, valeurs, ms} | {erreur}>, pttOff() -> Promise } ; profile : capacités
       déclarées (`/api/connect`). */
    constructor(api, profile, clock) {
      this.api = api; this.profile = profile || {}; this.clock = clock || (() => Date.now());
      this.family = "hamlib"; this.dataLabel = "PKTUSB"; this.scale = scale; this.funcs = buildFuncs(this.profile);
      this.trace = []; this.t0 = this.clock();
      this.modes = new Set(this.profile.modes || []);
    }
    async q(line) {
      let r;
      try { r = await this.api.cmd(line); } catch (e) { r = { erreur: "page" }; }
      this.trace.push({ t: this.clock() - this.t0, d: "tx", h: line, r: r && r.rprt, v: r && r.valeurs, ms: r && r.ms, e: r && r.erreur });
      return r || {};
    }
    async get(line) { const r = await this.q(line); return r.rprt === 0 && r.valeurs && r.valeurs.length ? r.valeurs : null; }
    async put(line) { const r = await this.q(line); return { ok: r.rprt === 0, ng: r.rprt != null && r.rprt !== 0 }; }

    async readFreq() { const v = await this.get("f"); const f = v && num(v[0]); return f == null ? null : Math.round(f); }
    async setFreq(hz) { return (await this.put("F " + Math.round(hz))).ok; }
    async readMode() { const v = await this.get("m"); return v && v[0] ? { code: v[0], name: v[0], filter: 0 } : null; }
    async setMode(code) { return !!code && (await this.put("M " + code + " 0")).ok; }   // largeur 0 = préréglage du poste
    modeCode(name) {
      const alias = { RTTY: "RTTY", "RTTY-U": "RTTYR" }[name] || name;
      return !this.modes.size || this.modes.has(alias) ? alias : undefined;
    }
    async readDataMode() { const m = await this.readMode(); return m ? { on: BASE_OF[m.code] ? 1 : 0, filter: 0 } : null; }
    async setDataMode(on) {
      const m = await this.readMode(); if (!m) return false;
      if (on) { const d = DATA_OF[m.code] || (BASE_OF[m.code] ? m.code : null); return d ? (d === m.code || this.setMode(d)) : false; }
      const b = BASE_OF[m.code]; return b ? this.setMode(b) : true;
    }
    async meter(kind) {
      const name = { s: "STRENGTH", po: "RFPOWER_METER", swr: "SWR", alc: "ALC", power: "RFPOWER" }[kind];
      const v = name ? await this.get("l " + name) : null;
      return v ? num(v[0]) : null;
    }
    powerRaw(pct) { return Math.max(0.01, Math.min(1, Math.round(pct) / 100)); }
    powerPct(raw) { return raw * 100; }
    powerClose(a, b) { return a != null && b != null && Math.abs(a - b) <= 0.02; }
    async setPower(raw) { return (await this.put("L RFPOWER " + (Math.round(raw * 1000) / 1000))).ok; }
    async readPtt() { const v = await this.get("t"); return v ? (v[0] !== "0") : null; }
    async setPtt(on) { return (await this.put(on ? "T 1" : "T 0")).ok; }
    // Retour en réception d'urgence : connexion à part du programme (pas derrière une lecture en cours).
    // Les commandes de cette connexion à part entrent dans la trace (`c: "urgence"`) : sans elles, le rapport ne
    // prouvait pas le retour en réception (rapport de l'IC-7100 du 2026-11-23, étape 374).
    async pttOffNow() {
      let r;
      const t = this.clock() - this.t0;
      try { r = await this.api.pttOff(); } catch (e) {
        this.trace.push({ t, d: "tx", h: "T 0", c: "urgence", e: "page" });
        await this.put("T 0"); return;
      }
      const steps = (r && Array.isArray(r.trace)) ? r.trace : [];
      if (!steps.length) this.trace.push({ t, d: "tx", h: "T 0", c: "urgence", e: "sans_detail", rx: !!(r && r.rx) });
      for (const s of steps) this.trace.push({ t, d: "tx", h: s.h, r: s.rprt, v: s.valeurs, ms: s.ms, e: s.erreur, c: "urgence" });
    }

    async fnRead(f) {
      const v = await this.get((f.kind === "func" ? "u " : "l ") + f.name);
      if (!v) return null;
      if (f.range) { const x = num(v[0]); return x == null ? null : show(x); }
      const x = num(v[0]); return x == null ? v[0] : String(Math.round(x));
    }
    async fnWrite(f, v) {
      const line = x => (f.kind === "func" ? "U " : "L ") + f.name + " " + x;
      // Atténuateur : Hamlib peut déclarer une valeur que le poste refuse (IC-7100, Hamlib 4.7.2 : « Attenuator: 20dB »
      // mais plage ATT(0..12) ; le poste n'a que 12 dB) : refus = valeurs connues essayées ensuite.
      if (f.name === "ATT" && v !== "0") {
        const tries = Array.from(new Set([v].concat(f.values.slice(1), ["12", "20", "10", "6", "18"])));
        let last = null;
        for (const t of tries) {
          const r = await this.put(line(t));
          if (r && r.ok) return Object.assign({}, r, { written: t });
          last = r;
          if (!(r && r.ng)) break;
        }
        return last || { ok: false, ng: false };
      }
      return this.put(line(v));
    }
    fnOther(f, v0) {
      if (f.range) { const [lo, hi] = f.range, x = num(v0) == null ? lo : num(v0), mid = (lo + hi) / 2; const t = Math.abs(x - mid) > (hi - lo) / 8 ? mid : lo + (hi - lo) * 0.25; return show(t); }
      return f.values.find(x => x !== v0) || f.values[0];
    }
    // Niveau continu : le poste l'arrondit à son cran (Icom : 256 crans) ; écart toléré = le pas déclaré ou 5 %.
    fnNear(f, read, wrote) {
      if (!f.range) return false;
      const a = num(read), b = num(wrote); if (a == null || b == null) return false;
      return Math.abs(a - b) <= Math.max(f.step || 0, (f.range[1] - f.range[0]) * 0.05);
    }
    fnShow(v) { return show(v); }
    // VFO A / B : échange par l'opération XCHG si Hamlib la déclare ; l'autre VFO n'est pas lu.
    async vfoOther() { return null; }
    async vfoSwap() { return this.put("G XCHG"); }
  }

  // Accès au programme local (navigateur) : même origine, cookie de session.
  function httpApi(base) {
    const post = (path, body, keepalive) => fetch((base || "") + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}), credentials: "same-origin", keepalive: !!keepalive });
    return {
      async cmd(line) { const r = await post("api/cmd", { c: line }); return r.json(); },
      async pttOff(keepalive) { const r = await post("api/ptt_off", {}, keepalive); return r.json(); },
      async connect(model, port, speed) { const r = await post("api/connect", { modele: model, port, vitesse: speed || null }); return r.json(); },
      async disconnect() { try { await post("api/disconnect", {}); } catch (e) { /* rien */ } },
      async info() { const r = await fetch((base || "") + "api/info", { credentials: "same-origin" }); return r.json(); },
      async models() { const r = await fetch((base || "") + "api/models", { credentials: "same-origin" }); return (await r.json()).postes || []; },
      async ports() { const r = await fetch((base || "") + "api/ports", { credentials: "same-origin" }); return (await r.json()).ports || []; },
    };
  }

  const api = { HamlibLink, buildFuncs, scale, httpApi, DATA_OF, BASE_OF };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtHamlib = api;
})(typeof window !== "undefined" ? window : globalThis);
