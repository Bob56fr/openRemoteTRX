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
  // Zoom du waterfall (station 0.154.0+, étape 203) : la ligne couvre fs / zoom autour de centre + zoom_off (Hz) ;
  // la station garde la fenêtre dans la largeur du SDR et la recentre sur l'écoute quand celle-ci en sort.
  const ZOOMS = [1, 2, 4, 8, 16], ZOOM_OFF_MAX = 5000000;
  // Palettes du waterfall du SDR (étape 204, choix gardé dans le navigateur) : « theme » = celle du thème de la page.
  const PALETTE_STOPS = [0, 0.2, 0.45, 0.7, 0.88, 1];
  const PALETTES = [
    ["theme", "Thème", null],
    ["classique", "Classique", ["#000000", "#000080", "#0060ff", "#00e0ff", "#ffff00", "#ff2000"]],
    ["chaud", "Chaud", ["#000000", "#3b0a45", "#8a1c4b", "#d94a1f", "#f9b233", "#ffffcc"]],
    ["vert", "Vert", ["#000000", "#002200", "#005a10", "#10a030", "#80ff60", "#f0fff0"]],
    ["gris", "Gris", ["#000000", "#202020", "#505050", "#909090", "#d0d0d0", "#ffffff"]],
  ];
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
    const step = [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw * 0.8) || 10 * p;   // pas rond le plus proche
    const lo = center - span / 2, out = [];
    for (let k = Math.ceil(lo / step); k * step <= center + span / 2; k++) out.push(k * step);
    return out;
  }

  function tickDigits(marks) {
    /* Décimales (en MHz) qui distinguent des graduations voisines : pas de 100 kHz = 1, 10 kHz = 2, 1 kHz = 3… */
    if (!marks || marks.length < 2) return 3;
    const step = Math.abs(marks[1] - marks[0]);
    return Math.max(1, Math.min(4, Math.ceil(6 - Math.log10(step) - 1e-9)));
  }

  function formatMHz(hz, digits) {
    return Number.isFinite(hz) ? (hz / 1e6).toFixed(digits === undefined ? 4 : digits) : "—";
  }

  function tuneArgs(hz, center, span) {
    /* Réglages pour écouter hz : la fréquence écoutée seule si elle est dans la fenêtre affichée (95 %), sinon le
       centre aussi (le waterfall suit). center / span inconnus : on centre. */
    if (Number.isFinite(center) && span > 0 && Math.abs(hz - center) <= span * 0.475) return { dfreq_hz: hz };
    return { center_hz: hz, dfreq_hz: hz };
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
      if (name === "fs") { const v = args[name]; if (typeof v !== "number" || !Number.isInteger(v) || v < 0 || v > 10000000) return "fs : largeur en Hz"; continue; }
      if (name === "ant") { if (!["", "A", "B"].includes(args[name])) return "ant : A ou B"; continue; }
      if (name === "zoom") { if (!ZOOMS.includes(args[name])) return "zoom : " + ZOOMS.join(", "); continue; }
      if (name === "zoom_off") {
        const v = args[name];
        if (typeof v !== "number" || !Number.isInteger(v) || Math.abs(v) > ZOOM_OFF_MAX) return "zoom_off : entier de -" + ZOOM_OFF_MAX + " à " + ZOOM_OFF_MAX;
        continue;
      }
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

  // Curseur de volume 0-100 -> volume de l'élément audio : courbe au carré (l'oreille entend en décibels ;
  // un réglage linéaire semblait sans effet sur les trois quarts de sa course). 50 % = -12 dB, 10 % = -40 dB.
  function volumeOf(value) {
    const v = Math.min(100, Math.max(0, Number(value) || 0)) / 100;
    return v * v;
  }

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
    access: "clé RTL-SDR illisible par la station (droits USB : relancer l'installation de la station)",
    duplicate: "numéro de série en double (deux clés RTL-SDR identiques : en réécrire un)",
    exit: "sdr-core s'est arrêté : relance automatique",
  };

  function stateText(st) {
    /* Ligne d'état de la rubrique. */
    if (!st || typeof st !== "object") return "SDR : en attente de l'état…";
    if (st.state === "running") {
      let t = "SDR " + (st.serial || "") + " : " + formatMHz(st.center, 3) + " MHz, largeur " + formatMHz(st.fs, 0) + " MHz";
      if (st.overload) t += " — SURCHARGE (baisser le gain)";
      if (st.drops || st.gaps) t += " — pertes : " + (st.drops || 0) + " / " + (st.gaps || 0);
      if (Number.isFinite(st.cpu_total)) t += " — CPU " + st.cpu_total + " %";
      else if (Number.isFinite(st.cpu)) t += " — CPU " + st.cpu + " %";
      if (Number.isFinite(st.mem_mb)) t += ", " + Math.round(st.mem_mb) + " Mo";
      return t;
    }
    if (st.state === "suspended") return "SDR SUSPENDU par la station : " + (st.load_reason || st.detail || "station chargée") + " (reprise automatique au calme)";
    if (st.state === "starting") return "SDR : démarrage…";
    if (st.state === "error" && st.code === "duplicate") return "SDR en panne : numéro de série en double (deux clés RTL-SDR identiques : en réécrire un)";
    if (st.state === "error") return "SDR en panne : " + (CODE_TEXTS[st.code] || st.detail || st.code || "cause inconnue");
    return "SDR : " + String(st.state || "arrêté");
  }

  // Bridage du module (station 0.144.0+, trxstation/sdr/load.py) : niveau appliqué et sa cause, ou vide.
  const LOAD_TEXTS = { 1: "son du SDR coupé", 2: "waterfall ralenti", 3: "waterfall à 1 ligne/s",
                       4: "échantillonnage à 2 MHz", 5: "module suspendu" };
  function loadText(st) {
    if (!st || !(st.load > 0)) return "";
    return "Bridé (niveau " + st.load + " : " + (LOAD_TEXTS[st.load] || "?") + ")" + (st.load_reason ? " — " + st.load_reason : "")
      + ". Un cran est rendu après 5 minutes au calme.";
  }

  // Balance TRX / SDR (-100 = TRX seul, +100 = SDR seul) -> facteurs de volume des deux sources.
  function balanceGains(b) {
    const v = Math.min(100, Math.max(-100, Number(b) || 0)) / 100;
    return { trx: v > 0 ? 1 - v : 1, sdr: v < 0 ? 1 + v : 1 };
  }

  // Séparation gauche / droite : 0 = mélange (mono), 1 = TRX à gauche et SDR à droite, 2 = l'inverse.
  // Rend la position stéréo (-1 gauche, +1 droite) de chaque source.
  const SPLITS = [[0, "Mélange (mono)"], [1, "TRX à gauche, SDR à droite"], [2, "SDR à gauche, TRX à droite"]];
  function splitPans(split) {
    if (split === 1) return { trx: -1, sdr: 1 };
    if (split === 2) return { trx: 1, sdr: -1 };
    return null;
  }

  function zoomStep(current, dir) {
    /* Zoom voisin (dir +1 = plus serré, -1 = plus large), ou null au bout de l'échelle. */
    const i = ZOOMS.indexOf(current > 0 ? current : 1), j = (i < 0 ? 0 : i) + (dir > 0 ? 1 : -1);
    return j < 0 || j >= ZOOMS.length ? null : ZOOMS[j];
  }

  function panArgs(st, dir) {
    /* Déplacer la fenêtre zoomée d'une demi-largeur (dir -1 vers le bas, +1 vers le haut) ; null sans zoom. La
       station borne le décalage à la largeur du SDR. */
    if (!st || !(st.zoom > 1) || !(st.fs > 0)) return null;
    const off = Math.round((Number(st.zoom_off) || 0) + dir * st.fs / st.zoom / 2);
    return { zoom_off: Math.max(-ZOOM_OFF_MAX, Math.min(ZOOM_OFF_MAX, off)) };
  }

  function zoomLabel(st) {
    /* Libellé du zoom : « ×4 · 500 kHz » (largeur montrée). */
    const z = st && st.zoom > 0 ? st.zoom : 1;
    return "×" + z + (st && st.fs > 0 ? " · " + widthLabel(Math.round(st.fs / z)) : "");
  }

  function paletteLut(name) {
    /* Table de 256 couleurs (r, g, b à la suite) de la palette nommée ; null pour « theme » ou un nom inconnu. */
    const entry = PALETTES.find((p) => p[0] === name);
    if (!entry || !entry[2]) return null;
    const stops = entry[2].map((c, i) => [PALETTE_STOPS[i], parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]);
    const lut = new Uint8Array(256 * 3);
    for (let i = 0; i < 256; i++) {
      const x = i / 255;
      let j = 1;
      while (j < stops.length - 1 && x > stops[j][0]) j++;
      const [t0, r0, g0, b0] = stops[j - 1], [t1, r1, g1, b1] = stops[j], k = Math.min(1, Math.max(0, (x - t0) / (t1 - t0)));
      lut[3 * i] = Math.round(r0 + (r1 - r0) * k); lut[3 * i + 1] = Math.round(g0 + (g1 - g0) * k); lut[3 * i + 2] = Math.round(b0 + (b1 - b0) * k);
    }
    return lut;
  }

  function nextPalette(name) {
    const i = PALETTES.findIndex((p) => p[0] === name);
    return PALETTES[(i + 1) % PALETTES.length][0];
  }

  function paletteName(name) {
    const entry = PALETTES.find((p) => p[0] === name);
    return entry ? entry[1] : PALETTES[0][1];
  }

  // Spots du Cluster DX sur le SDR (étape 205) : mode du spot (mode Hamlib proposé par la station) -> mode du SDR.
  const SPOT_MODES = { USB: "USB", LSB: "LSB", AM: "AM", CW: "CW", CWR: "CW", FM: "NFM", PKTFM: "NFM", PKTUSB: "USB",
                       PKTLSB: "LSB", RTTY: "USB", RTTYR: "LSB" };
  function spotListen(spot, center, fs) {
    /* Réglages pour que le SDR écoute un spot : fréquence (le centre suit s'il le faut), mode si on le sait. */
    if (!spot || !(spot.hz > 0)) return null;
    const args = tuneArgs(Math.round(spot.hz), center, fs);
    const mode = SPOT_MODES[String(spot.qsyMode || "").toUpperCase()];
    if (mode) args.mode = mode;
    return args;
  }

  function rateLabel(hz) {
    /* Largeur du SDR : « 2 MHz », « 2,048 MHz ». */
    return Number.isFinite(hz) ? String(+(hz / 1e6).toFixed(3)).replace(".", ",") + " MHz" : "—";
  }

  function nextRange(current) {
    const i = RANGES.indexOf(current);
    return RANGES[(i + 1) % RANGES.length];
  }

  const api = { DB_MIN, DB_STEP, LIMITS, BOOLS, LNA_MAX, RANGES, DEFAULT_VIEW, decodeLine, levelDb, floorDb, colorIndex,
                binFreq, freqAt, ticks, tickDigits, formatMHz, parseMHz, checkSettings, stateText, nextRange, CODE_TEXTS, rfFromLna,
                lnaFromRf, ifFromGr, grFromIf, gainText, MODES, WIDTHS, ZOOMS, zoomStep, panArgs, zoomLabel,
                PALETTES, paletteLut, nextPalette, paletteName, rateLabel, spotListen, markerLeft, widthLabel, listenText, volumeOf, tuneArgs, loadText, balanceGains, SPLITS, splitPans };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxSdr = api; }
})(typeof window !== "undefined" ? window : globalThis);
