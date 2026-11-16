// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Module SDR dans la page (docs/sdr-cahier-des-charges.md, lot S1a ; protocole : docs/protocole.md § 18) : calculs
   purs, testés sous Node (tests/js/sdr_test.js), sans DOM. Le dessin est dans ui.js (rubrique « SDR »).
   Le SDR est en RÉCEPTION SEULE ; « QSY du TRX » passe par la commande habituelle set_frequency du client. */
(function (root) {
  "use strict";

  const DB_MIN = -150, DB_STEP = 0.5;                 // niveau d'une case : -150 dBFS + 0,5 dB × valeur (0 à 255)
  const LIMITS = { center_hz: [1000, 2000000000], lna: [0, 8], gr: [20, 59], rate: [1, 15] };
  const BOOLS = ["agc"];                               // AGC matériel de la FI (station 0.141.0+)
  // Écoute (station 0.142.0+) : fréquence écoutée, largeur du filtre, squelch (dB au-dessus du bruit, 0 = ouvert)
  Object.assign(LIMITS, { dfreq_hz: [1000, 2000000000], dbw: [100, 15000], sql: [0, 40] });
  const MODES = ["USB", "LSB", "AM", "NFM", "CW"];
  const WIDTHS = { AM: [6000, 8000, 10000], NFM: [8000, 12500], USB: [1800, 2400, 2700, 3000], LSB: [1800, 2400, 2700, 3000],
                   CW: [250, 500, 1000] };
  const LNA_MAX = 8, GR_MAX = 59, GR_MIN = 20;
  const RANGES = [30, 40, 50, 60, 80];                 // dynamique affichée (dB)
  const DEFAULT_VIEW = { range: 50, auto: true, floor: -110 };

  function decodeLine(b64) {
    /* Cases uint8 d'une ligne (base64) ; null si illisible. */
    if (typeof b64 !== "string" || !b64) return null;
    try {
      if (typeof root.atob === "function") {
        const bin = root.atob(b64), out = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
        return out;
      }
      return new Uint8Array(Buffer.from(b64, "base64"));
    } catch (e) { return null; }
  }

  const levelDb = (v) => DB_MIN + v * DB_STEP;

  function floorDb(values) {
    /* Plancher de bruit estimé : 20e centile des cases (les signaux ne le tirent pas vers le haut). */
    if (!values || !values.length) return null;
    const sorted = Array.from(values).sort((a, b) => a - b);
    return levelDb(sorted[Math.floor(sorted.length * 0.2)]);
  }

  function colorIndex(v, floor, range) {
    /* Index 0 à 255 de la palette du waterfall : du plancher (noir) au plancher + dynamique (blanc). */
    const t = (levelDb(v) - floor) / (range > 0 ? range : 50);
    return t <= 0 ? 0 : t >= 1 ? 255 : Math.round(t * 255);
  }

  function binFreq(i, n, center, span) {
    return center - span / 2 + (i + 0.5) * span / n;
  }

  function freqAt(x, width, center, span) {
    /* Fréquence (Hz, arrondie au Hz) sous l'abscisse x d'un dessin de largeur width. */
    if (!(width > 0) || !Number.isFinite(x)) return null;
    const f = center - span / 2 + Math.min(1, Math.max(0, x / width)) * span;
    return Math.round(f);
  }

  function ticks(center, span, count) {
    /* Graduations « rondes » (Hz) sur la largeur affichée : pas de 1, 2 ou 5 × 10^k. */
    const want = count || 6, raw = span / want, p = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) || 10 * p;
    const lo = center - span / 2, out = [];
    for (let k = Math.ceil(lo / step); k * step <= center + span / 2; k++) out.push(k * step);
    return out;
  }

  function formatMHz(hz, digits) {
    return Number.isFinite(hz) ? (hz / 1e6).toFixed(digits === undefined ? 4 : digits) : "—";
  }

  function parseMHz(text) {
    /* « 14.100 », « 14,1 » ou « 14100 » (kHz si plus de 1000) -> Hz entier, ou null. */
    const s = String(text || "").trim().replace(",", ".");
    if (!/^\d+(\.\d+)?$/.test(s)) return null;
    let v = Number(s);
    v = v >= 1000 ? v * 1e3 : v * 1e6;
    v = Math.round(v);
    return v >= LIMITS.center_hz[0] && v <= LIMITS.center_hz[1] ? v : null;
  }

  function checkSettings(args) {
    /* Mêmes limites que la station (trxstation/sdr/service.py) ; renvoie un message en français, ou "". */
    if (!args || typeof args !== "object") return "réglages invalides";
    const names = Object.keys(args);
    if (!names.length) return "aucun réglage";
    for (const name of names) {
      if (BOOLS.includes(name)) { if (typeof args[name] !== "boolean") return name + " : vrai ou faux"; continue; }
      if (name === "mode") { if (!MODES.includes(args[name])) return "mode : " + MODES.join(", "); continue; }
      const lim = LIMITS[name], v = args[name];
      if (!lim) return "réglage inconnu : " + name;
      if (typeof v !== "number" || !Number.isInteger(v) || v < lim[0] || v > lim[1]) return name + " : entier de " + lim[0] + " à " + lim[1];
    }
    return "";
  }

  // Curseurs « à l'endroit » : plus à droite = plus de gain (le SDR parle en atténuation : LNA 0 et GR 20 = maximum).
  const rfFromLna = (lna) => LNA_MAX - lna;
  const lnaFromRf = (rf) => LNA_MAX - rf;
  const ifFromGr = (gr) => GR_MAX - gr;
  const grFromIf = (v) => GR_MAX - v;

  function gainText(st) {
    /* Ligne de gain : ce que le SDR applique réellement (AGC de la FI compris). */
    if (!st || !Number.isFinite(st.lna)) return "";
    let t = "Gain RF " + rfFromLna(st.lna) + "/" + LNA_MAX;
    if (st.agc) t += " · FI auto" + (Number.isFinite(st.gr_now) ? " (gain FI " + ifFromGr(st.gr_now) + "/" + (GR_MAX - GR_MIN) + ")" : "");
    else t += " · gain FI " + ifFromGr(st.gr) + "/" + (GR_MAX - GR_MIN);
    if (Number.isFinite(st.gain_db)) t += " · gain total " + st.gain_db.toFixed(1) + " dB";
    if (st.overload) t += " — SURCHARGE : baisser le gain RF";
    return t;
  }

  function markerLeft(f, center, span) {
    /* Position (%) du repère de la fréquence écoutée sur le waterfall, ou null hors de la largeur. */
    if (!Number.isFinite(f) || !(span > 0)) return null;
    const x = (f - (center - span / 2)) / span;
    return x < 0 || x > 1 ? null : Math.round(x * 10000) / 100;
  }

  function widthLabel(hz) { return hz >= 1000 ? (hz / 1000).toFixed(hz % 1000 ? 1 : 0).replace(".", ",") + " kHz" : hz + " Hz"; }

  function listenText(st, listening) {
    /* Ligne de l'écoute : fréquence, mode, filtre, squelch, niveaux. */
    if (!st || !Number.isFinite(st.dfreq)) return "";
    let t = (listening ? "Écoute " : "Fréquence d'écoute ") + formatMHz(st.dfreq, 4) + " MHz " + (st.mode || "") + " " + widthLabel(st.dbw || 0);
    t += st.sql ? " · squelch " + st.sql + " dB (" + (st.sql_open ? "ouvert" : "fermé") + ")" : " · squelch ouvert";
    if (listening && Number.isFinite(st.chan_db) && Number.isFinite(st.noise_db))
      t += " · canal " + st.chan_db.toFixed(0) + " dBFS, bruit " + st.noise_db.toFixed(0) + " dBFS";
    if (listening && st.audio === false) t += " · en attente du son…";
    return t;
  }

  const CODE_TEXTS = {
    absent: "SDR introuvable (débranché, ou numéro de série faux dans [sdr] serial)",
    busy: "SDR déjà pris par une autre application",
    service: "service du fabricant injoignable (API SDRplay installée ? sdrplay.service ?)",
    core_missing: "programme sdr-core absent (relancer l'installation après l'API du fabricant)",
    config: "réglage refusé par sdr-core (voir [sdr] de station.toml)",
    removed: "SDR débranché pendant l'écoute",
    exit: "sdr-core s'est arrêté : relance automatique",
  };

  function stateText(st) {
    /* Ligne d'état de la rubrique. */
    if (!st || typeof st !== "object") return "SDR : en attente de l'état…";
    if (st.state === "running") {
      let t = "SDR " + (st.serial || "") + " : " + formatMHz(st.center, 3) + " MHz, largeur " + formatMHz(st.fs, 0) + " MHz";
      if (st.overload) t += " — SURCHARGE (baisser le gain)";
      if (st.drops || st.gaps) t += " — pertes : " + (st.drops || 0) + " / " + (st.gaps || 0);
      if (Number.isFinite(st.cpu)) t += " — CPU " + st.cpu + " %";
      return t;
    }
    if (st.state === "starting") return "SDR : démarrage…";
    if (st.state === "error") return "SDR en panne : " + (CODE_TEXTS[st.code] || st.detail || st.code || "cause inconnue");
    return "SDR : " + String(st.state || "arrêté");
  }

  function nextRange(current) {
    const i = RANGES.indexOf(current);
    return RANGES[(i + 1) % RANGES.length];
  }

  const api = { DB_MIN, DB_STEP, LIMITS, BOOLS, LNA_MAX, RANGES, DEFAULT_VIEW, decodeLine, levelDb, floorDb, colorIndex,
                binFreq, freqAt, ticks, formatMHz, parseMHz, checkSettings, stateText, nextRange, CODE_TEXTS, rfFromLna,
                lnaFromRf, ifFromGr, grFromIf, gainText, MODES, WIDTHS, markerLeft, widthLabel, listenText };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxSdr = api; }
})(typeof window !== "undefined" ? window : globalThis);
