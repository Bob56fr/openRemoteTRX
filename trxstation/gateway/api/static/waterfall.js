/* Waterfall de l'audio reçu : calculs purs (palette, rééchantillonnage, pics, graduations). Le dessin et l'analyse audio sont dans ui.js. */
(function (root) {
  "use strict";

  const SPEEDS = [3, 6, 12, 25, 50];                 // lignes par seconde
  const WIDTHS = [5000, 3000, 2500, 2000, 1000];     // bande audio affichée : de 0 Hz à N Hz
  const GAINS = [-12, -6, 0, 6, 12, 18];             // décalage de sensibilité des couleurs, en dB
  const PEAK_TIMES = [0, 0.5, 2, 5, Infinity];       // constante de temps des pics en secondes ; 0 = pas de pics ; Infinity = maintien
  const DEFAULTS = { speed: 12, width: 5000, gain: 0, peak: 2 };
  const FLOOR_DB = -85, RANGE_DB = 55;               // sans gain : de -85 dBFS (noir) à -30 dBFS (blanc)
  const GRID_HZ = 500;

  function cycle(list, value) {
    const i = list.indexOf(value);
    return list[(i + 1) % list.length];              // valeur inconnue : retour au début de la liste
  }

  const speedLabel = (v) => "VIT " + v;
  const widthLabel = (v) => "LARG " + (v / 1000) + "k";
  const gainLabel = (v) => "GAIN " + (v > 0 ? "+" + v : v);
  const peakLabel = (v) => (v === 0 ? "PIC OFF" : v === Infinity ? "PIC MAX" : "PIC " + v + "s");

  // ---- palette : gris sombre, gris-bleu, bleu, bleu clair, blanc
  const STOPS = [[0, 6, 8, 12], [0.2, 30, 36, 50], [0.45, 52, 86, 152], [0.7, 98, 162, 236], [0.88, 190, 226, 255], [1, 255, 255, 255]];

  function paletteRGB(t) {
    const x = Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0;
    for (let i = 1; i < STOPS.length; i++) {
      if (x <= STOPS[i][0]) {
        const [t0, r0, g0, b0] = STOPS[i - 1], [t1, r1, g1, b1] = STOPS[i], k = (x - t0) / (t1 - t0);
        return [Math.round(r0 + (r1 - r0) * k), Math.round(g0 + (g1 - g0) * k), Math.round(b0 + (b1 - b0) * k)];
      }
    }
    return [255, 255, 255];
  }

  const LUT = new Uint8Array(256 * 3);
  for (let i = 0; i < 256; i++) { const [r, g, b] = paletteRGB(i / 255); LUT[i * 3] = r; LUT[i * 3 + 1] = g; LUT[i * 3 + 2] = b; }

  function levelToT(db, gain) {
    const floor = FLOOR_DB - (gain || 0);
    return Math.min(1, Math.max(0, ((Number.isFinite(db) ? db : -200) - floor) / RANGE_DB));
  }

  // ---- spectre -> une valeur en dB par pixel, de 0 Hz à spanHz
  function resample(db, sampleRate, fftSize, spanHz, width, out) {
    const result = out && out.length === width ? out : new Float32Array(width);
    const binHz = sampleRate / fftSize, last = db.length - 1;
    const value = (i) => { const v = db[Math.min(last, Math.max(0, i))]; return Number.isFinite(v) ? v : -200; };
    for (let x = 0; x < width; x++) {
      const f0 = (x / width) * spanHz, f1 = ((x + 1) / width) * spanHz;
      // la raie i est centrée sur la fréquence i × binHz : le pixel [f0, f1[ contient les raies dont le centre y tombe
      const b0 = Math.ceil(f0 / binHz), b1 = Math.ceil(f1 / binHz) - 1;
      if (b1 >= b0) {                                 // au moins une raie dans le pixel : on garde la plus forte (une raie fine garde son niveau)
        let peak = -200;
        for (let b = b0; b <= b1; b++) peak = Math.max(peak, value(b));
        result[x] = peak;
      } else {                                        // aucune raie dans le pixel (bande étroite) : interpolation au centre du pixel pour un tracé lisse
        const pos = ((f0 + f1) / 2) / binHz, i = Math.floor(pos), k = pos - i;
        result[x] = value(i) * (1 - k) + value(i + 1) * k;
      }
    }
    return result;
  }

  function fillRow(row, values, gain) {
    for (let x = 0; x < values.length; x++) {
      const i = Math.round(levelToT(values[x], gain) * 255) * 3;
      row[x * 4] = LUT[i]; row[x * 4 + 1] = LUT[i + 1]; row[x * 4 + 2] = LUT[i + 2]; row[x * 4 + 3] = 255;
    }
    return row;
  }

  // ---- pics : maintien avec décroissance réglable
  class PeakTracker {
    constructor() { this.peaks = null; }
    reset() { this.peaks = null; }
    update(values, dtSeconds, tau) {
      if (!(tau > 0)) { this.peaks = null; return null; }                   // 0 : pics désactivés
      if (!this.peaks || this.peaks.length !== values.length) this.peaks = Float32Array.from(values);
      const decay = tau === Infinity ? 0 : (RANGE_DB / tau) * Math.max(0, dtSeconds);
      for (let i = 0; i < values.length; i++) this.peaks[i] = Math.max(values[i], this.peaks[i] - decay);
      return this.peaks;
    }
  }

  function strongest(values, spanHz, minDb) {
    /* La raie la plus forte (au-dessus de minDb) : { hz, db } ou null. */
    const threshold = minDb === undefined ? FLOOR_DB + 20 : minDb;
    let best = -1, top = -Infinity;
    for (let i = 0; i < values.length; i++) if (values[i] > top) { top = values[i]; best = i; }
    return best < 0 || !(top > threshold) ? null : { hz: Math.round(((best + 0.5) / values.length) * spanHz), db: top };
  }

  // ---- graduations : une tous les 500 Hz, en kHz sans unité
  function axisTicks(spanHz) {
    const ticks = [];
    for (let hz = 0; hz <= spanHz + 1e-6; hz += GRID_HZ) ticks.push({ hz: hz, fraction: hz / spanHz, label: String(hz / 1000) });
    return ticks;
  }

  // ---- réglages (mémorisés dans le navigateur)
  function normalizeSettings(raw) {
    const r = raw && typeof raw === "object" ? raw : {};
    const peak = Number.isInteger(r.peak) && r.peak >= 0 && r.peak < PEAK_TIMES.length ? PEAK_TIMES[r.peak] : DEFAULTS.peak;   // le maintien est stocké par son rang
    return {
      speed: SPEEDS.includes(r.speed) ? r.speed : DEFAULTS.speed,
      width: WIDTHS.includes(r.width) ? r.width : DEFAULTS.width,
      gain: GAINS.includes(r.gain) ? r.gain : DEFAULTS.gain,
      peak: peak,
    };
  }

  function serializeSettings(s) {
    return JSON.stringify({ speed: s.speed, width: s.width, gain: s.gain, peak: PEAK_TIMES.indexOf(s.peak) });
  }

  function nextSetting(settings, name) {
    const list = { speed: SPEEDS, width: WIDTHS, gain: GAINS, peak: PEAK_TIMES }[name];
    return list ? Object.assign({}, settings, { [name]: cycle(list, settings[name]) }) : settings;
  }

  const api = { SPEEDS, WIDTHS, GAINS, PEAK_TIMES, DEFAULTS, FLOOR_DB, RANGE_DB, GRID_HZ, cycle, speedLabel, widthLabel, gainLabel, peakLabel,
                paletteRGB, LUT, levelToT, resample, fillRow, PeakTracker, strongest, axisTicks, normalizeSettings, serializeSettings, nextSetting };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxWaterfall = api; }
})(typeof window !== "undefined" ? window : globalThis);
