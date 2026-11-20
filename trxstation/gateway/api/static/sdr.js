// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Module SDR dans la page (docs/sdr-cahier-des-charges.md, lot S1a ; protocole : docs/protocole.md § 18) : calculs
   purs, testés sous Node (tests/js/sdr_test.js), sans DOM. Le dessin est dans ui.js (rubrique « SDR »).
   Le SDR est en RÉCEPTION SEULE ; « QSY du TRX » passe par la commande habituelle set_frequency du client. */
(function (root) {
  "use strict";   // i18n-ok

  const I18N = root.TrxI18n || (typeof require === "function" ? require("./i18n.js") : null);

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
  // Deuxième colonne : clé du nom affiché (relu par paletteName).
  const PALETTE_STOPS = [0, 0.2, 0.45, 0.7, 0.88, 1];
  const PALETTES = [
    ["theme", "sdr.palette_theme", null],
    ["classique", "sdr.palette_classique", ["#000000", "#000080", "#0060ff", "#00e0ff", "#ffff00", "#ff2000"]],
    ["chaud", "sdr.palette_chaud", ["#000000", "#3b0a45", "#8a1c4b", "#d94a1f", "#f9b233", "#ffffcc"]],
    ["vert", "sdr.palette_vert", ["#000000", "#002200", "#005a10", "#10a030", "#80ff60", "#f0fff0"]],
    ["gris", "sdr.palette_gris", ["#000000", "#202020", "#505050", "#909090", "#d0d0d0", "#ffffff"]],
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
    /* Mêmes limites que la station (trxstation/sdr/service.py) ; renvoie un message dans la langue de la page, ou "". */
    if (!args || typeof args !== "object") return I18N.t("sdr.check_invalid");
    const names = Object.keys(args);
    if (!names.length) return I18N.t("sdr.check_empty");
    for (const name of names) {
      if (BOOLS.includes(name)) { if (typeof args[name] !== "boolean") return I18N.t("sdr.check_bool", { name: name }); continue; }
      if (name === "mode") { if (!MODES.includes(args[name])) return I18N.t("sdr.check_choice", { name: name, choices: MODES.join(", ") }); continue; }
      if (name === "fs") { const v = args[name]; if (typeof v !== "number" || !Number.isInteger(v) || v < 0 || v > 10000000) return I18N.t("sdr.check_fs"); continue; }
      if (name === "ant") { if (!["", "A", "B"].includes(args[name])) return I18N.t("sdr.check_ant"); continue; }
      if (name === "zoom") { if (!ZOOMS.includes(args[name])) return I18N.t("sdr.check_choice", { name: name, choices: ZOOMS.join(", ") }); continue; }
      if (name === "zoom_off") {
        const v = args[name];
        if (typeof v !== "number" || !Number.isInteger(v) || Math.abs(v) > ZOOM_OFF_MAX) return I18N.t("sdr.check_range", { name: name, min: -ZOOM_OFF_MAX, max: ZOOM_OFF_MAX });
        continue;
      }
      const lim = LIMITS[name], v = args[name];
      if (!lim) return I18N.t("sdr.check_unknown", { name: name });
      if (typeof v !== "number" || !Number.isInteger(v) || v < lim[0] || v > lim[1]) return I18N.t("sdr.check_range", { name: name, min: lim[0], max: lim[1] });
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
    let t = I18N.t("sdr.gain_rf", { gain: rfFromLna(st.lna), max: LNA_MAX });
    if (st.agc) {
      t += Number.isFinite(st.gr_now) ? I18N.t("sdr.gain_if_auto_now", { gain: ifFromGr(st.gr_now), max: GR_MAX - GR_MIN })
        : I18N.t("sdr.gain_if_auto");
    } else t += I18N.t("sdr.gain_if", { gain: ifFromGr(st.gr), max: GR_MAX - GR_MIN });
    if (Number.isFinite(st.gain_db)) t += I18N.t("sdr.gain_total", { db: st.gain_db.toFixed(1) });
    if (st.overload) t += I18N.t("sdr.gain_overload");
    return t;
  }

  function markerLeft(f, center, span) {
    /* Position (%) du repère de la fréquence écoutée sur le waterfall, ou null hors de la largeur. */
    if (!Number.isFinite(f) || !(span > 0)) return null;
    const x = (f - (center - span / 2)) / span;
    return x < 0 || x > 1 ? null : Math.round(x * 10000) / 100;
  }

  function widthLabel(hz) { return hz >= 1000 ? I18N.decimal(hz / 1000, hz % 1000 ? 1 : 0) + " kHz" : hz + " Hz"; }

  // Curseur de volume 0-100 -> volume de l'élément audio : courbe au carré (l'oreille entend en décibels ;
  // un réglage linéaire semblait sans effet sur les trois quarts de sa course). 50 % = -12 dB, 10 % = -40 dB.
  function volumeOf(value) {
    const v = Math.min(100, Math.max(0, Number(value) || 0)) / 100;
    return v * v;
  }

  function listenText(st, listening) {
    /* Ligne de l'écoute : fréquence, mode, filtre, squelch, niveaux. */
    if (!st || !Number.isFinite(st.dfreq)) return "";
    let t = I18N.t(listening ? "sdr.listen_on" : "sdr.listen_off", { freq: formatMHz(st.dfreq, 4), mode: st.mode || "",
                                                                     width: widthLabel(st.dbw || 0) });
    t += st.sql ? I18N.t(st.sql_open ? "sdr.squelch_db_open" : "sdr.squelch_db_closed", { db: st.sql }) : I18N.t("sdr.squelch_off");
    if (listening && Number.isFinite(st.chan_db) && Number.isFinite(st.noise_db))
      t += I18N.t("sdr.levels", { chan: st.chan_db.toFixed(0), noise: st.noise_db.toFixed(0) });
    if (listening && st.audio === false) t += I18N.t("sdr.waiting_audio");
    return t;
  }

  const CODES = ["absent", "busy", "service", "core_missing", "config", "removed", "access", "duplicate", "exit"];
  function codeTexts() {
    /* Causes des pannes du SDR (relues à l'affichage). */
    const out = {};
    for (const c of CODES) out[c] = I18N.t("sdr.code_" + c);
    return out;
  }

  function viewWindow(st) {
    /* Fenêtre affichée par le waterfall : centre du récepteur + décalage du zoom, largeur / zoom ; null si inconnue. */
    if (!st || !Number.isFinite(st.center) || !(st.fs > 0)) return null;
    const z = st.zoom > 1 ? st.zoom : 1;
    return { center: st.center + (z > 1 && Number.isFinite(st.zoom_off) ? st.zoom_off : 0), span: st.fs / z };
  }

  function lineFreq(hz) {
    /* Fréquence de la ligne du SDR sous celle du TRX, même écriture : 7050000 -> « 7.050.00 » (MHz.kHz.dizaines de Hz). */
    if (!Number.isFinite(hz) || hz <= 0) return "";
    const d = Math.round(hz / 10);
    return Math.floor(d / 100000) + "." + String(Math.floor(d / 100) % 1000).padStart(3, "0") + "." + String(d % 100).padStart(2, "0");
  }

  // Niveaux du mélange (bargraphs verticaux) : 10 segments de 5,4 dB, de -54 dBFS (rien) à 0 dBFS (tout allumé).
  const MIX_SEGMENTS = 10, MIX_FLOOR_DB = -54;
  function mixSegments(rms, gain) {
    /* Nombre de segments allumés pour un niveau efficace (0..1) entendu après un gain (volume, balance, muet). */
    const v = (Number(rms) || 0) * (Number(gain) || 0);
    if (!(v > 0)) return 0;
    const db = 20 * Math.log10(v);
    return Math.max(0, Math.min(MIX_SEGMENTS, Math.round((db - MIX_FLOOR_DB) / (-MIX_FLOOR_DB / MIX_SEGMENTS))));
  }

  function mixShown(st) {
    /* Bargraphs, ligne du SDR et S-SDR : seulement quand le module SDR tourne vraiment sur la station. */
    return !!(st && st.state === "running");
  }

  function badgeText(st) {
    /* En-tête repliable de la rubrique : la fréquence ÉCOUTÉE (sinon le centre de la fenêtre affichée). */
    if (!st || st.state !== "running") return "";
    if (Number.isFinite(st.dfreq)) return formatMHz(st.dfreq, 4) + " MHz";
    const v = viewWindow(st);
    return v ? formatMHz(v.center, 3) + " MHz" : "";
  }

  function stateText(st) {
    /* Ligne d'état de la rubrique. */
    if (!st || typeof st !== "object") return I18N.t("sdr.state_waiting");
    if (st.state === "running") {
      let t = I18N.t("sdr.state_running", { serial: st.serial || "", center: formatMHz(st.center, 3), fs: formatMHz(st.fs, 0) });
      const v = viewWindow(st);                                // zoom : la fenêtre MONTRÉE n'est pas centrée sur le récepteur
      if (v && st.zoom > 1) t += I18N.t("sdr.state_view", { lo: formatMHz(v.center - v.span / 2, 3), hi: formatMHz(v.center + v.span / 2, 3) });
      if (st.overload) t += I18N.t("sdr.state_overload");
      if (st.drops || st.gaps) t += I18N.t("sdr.state_losses", { drops: st.drops || 0, gaps: st.gaps || 0 });
      if (Number.isFinite(st.cpu_total)) t += " — CPU " + st.cpu_total + " %";
      else if (Number.isFinite(st.cpu)) t += " — CPU " + st.cpu + " %";
      if (Number.isFinite(st.mem_mb)) t += I18N.t("sdr.state_mem", { mb: Math.round(st.mem_mb) });
      return t;
    }
    if (st.state === "suspended") {
      return I18N.t("sdr.state_suspended", { reason: st.load_reason || st.detail || I18N.t("sdr.load_default") });
    }
    if (st.state === "starting") return I18N.t("sdr.state_starting");
    if (st.state === "error" && st.code === "duplicate") return I18N.t("sdr.state_error", { cause: I18N.t("sdr.code_duplicate") });
    if (st.state === "error") return I18N.t("sdr.state_error", { cause: codeTexts()[st.code] || st.detail || st.code || I18N.t("sdr.cause_unknown") });
    return I18N.t("sdr.state_other", { state: String(st.state || I18N.t("sdr.state_stopped")) });
  }

  // Bridage du module (station 0.144.0+, trxstation/sdr/load.py) : niveau appliqué et sa cause, ou vide.
  function loadText(st) {
    if (!st || !(st.load > 0)) return "";
    const what = st.load >= 1 && st.load <= 5 && Number.isInteger(st.load) ? I18N.t("sdr.load_" + st.load) : "?";
    return I18N.t("sdr.load_text", { level: st.load, what: what, reason: st.load_reason ? " — " + st.load_reason : "" });
  }

  // Balance TRX / SDR (-100 = TRX seul, +100 = SDR seul) -> facteurs de volume des deux sources.
  function balanceGains(b) {
    const v = Math.min(100, Math.max(-100, Number(b) || 0)) / 100;
    return { trx: v > 0 ? 1 - v : 1, sdr: v < 0 ? 1 + v : 1 };
  }

  // Séparation gauche / droite : 0 = mélange (mono), 1 = TRX à gauche et SDR à droite, 2 = l'inverse.
  // Rend la position stéréo (-1 gauche, +1 droite) de chaque source.
  function splits() { return [0, 1, 2].map((n) => [n, I18N.t("sdr.split_" + n)]); }
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
    return I18N.t(entry ? entry[1] : PALETTES[0][1]);
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
    return Number.isFinite(hz) ? I18N.decimal(+(hz / 1e6).toFixed(3)) + " MHz" : "—";
  }

  function nextRange(current) {
    const i = RANGES.indexOf(current);
    return RANGES[(i + 1) % RANGES.length];
  }

  const api = { DB_MIN, DB_STEP, LIMITS, BOOLS, LNA_MAX, RANGES, DEFAULT_VIEW, decodeLine, levelDb, floorDb, colorIndex,
                binFreq, freqAt, ticks, tickDigits, formatMHz, parseMHz, checkSettings, stateText, viewWindow, badgeText, lineFreq, mixSegments, mixShown, MIX_SEGMENTS, nextRange, get CODE_TEXTS() { return codeTexts(); }, rfFromLna,
                lnaFromRf, ifFromGr, grFromIf, gainText, MODES, WIDTHS, ZOOMS, zoomStep, panArgs, zoomLabel,
                PALETTES, paletteLut, nextPalette, paletteName, rateLabel, spotListen, markerLeft, widthLabel, listenText, volumeOf, tuneArgs, loadText, balanceGains, get SPLITS() { return splits(); }, splitPans };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxSdr = api; }
})(typeof window !== "undefined" ? window : globalThis);
