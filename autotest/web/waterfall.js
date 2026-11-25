// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, waterfall du poste (essai R10, étape 398) : les balayages « 27 00 » reçus pendant l'essai sont
   dessinés EN DIRECT (le plus récent en haut), puis une image PNG légendée (modèle, bornes, date, logiciel) est jointe au
   rapport. Dégradé = celui du waterfall de la station (client.css --waterfall-degrade). Calculs purs testés sous Node ;
   le dessin n'utilise que le canvas du navigateur. */
(function (root) {
  "use strict";
  const STOPS = [[0x06, 0x08, 0x0c], [0x1e, 0x24, 0x32], [0x34, 0x56, 0x98], [0x62, 0xa2, 0xec], [0xbe, 0xe2, 0xff], [0xff, 0xff, 0xff]];
  const MAX_ROWS = 240;                 // lignes gardées pour l'image (environ 10 s à 25 balayages par seconde)

  /* Couleur d'un niveau 0..max (spectre Icom : 0 à 160) : dégradé en 5 tronçons. */
  function colorAt(v, max) {
    const f = Math.max(0, Math.min(1, (Number(v) || 0) / (max || 160)));
    const pos = f * (STOPS.length - 1), i = Math.min(STOPS.length - 2, Math.floor(pos)), t = pos - i;
    return STOPS[i].map((c, k) => Math.round(c + (STOPS[i + 1][k] - c) * t));
  }

  /* Ramène un balayage à `width` colonnes (maximum des points couverts : un signal fin ne disparaît pas). */
  function resample(points, width) {
    const n = points.length, out = new Array(width);
    for (let x = 0; x < width; x++) {
      const a = Math.floor(x * n / width), b = Math.max(a + 1, Math.floor((x + 1) * n / width));
      let m = 0;
      for (let i = a; i < b && i < n; i++) if (points[i] > m) m = points[i];
      out[x] = m;
    }
    return out;
  }

  /* Lignes gardées pour l'image : les MAX_ROWS dernières, copiées (le tableau du balayage peut être réutilisé). */
  function keep(rows, points) {
    rows.push(Array.from(points));
    if (rows.length > MAX_ROWS) rows.shift();
    return rows;
  }

  function paintRow(ctx, y, values, max) {
    const img = ctx.createImageData(values.length, 1);
    values.forEach((v, x) => { const c = colorAt(v, max); img.data.set([c[0], c[1], c[2], 255], x * 4); });
    ctx.putImageData(img, 0, y);
  }

  /* Waterfall en direct : chaque balayage décale l'image d'une ligne vers le bas et se dessine en haut. */
  class Live {
    constructor(canvas, max) { this.canvas = canvas; this.ctx = canvas.getContext("2d"); this.max = max || 160; this.rows = 0; }
    clear() { this.ctx.fillStyle = "#06080c"; this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height); this.rows = 0; }
    push(points) {
      const c = this.canvas, w = c.width;
      if (this.rows) this.ctx.drawImage(c, 0, 0, w, c.height - 1, 0, 1, w, c.height - 1);
      paintRow(this.ctx, 0, resample(points, w), this.max);
      this.rows++;
    }
  }

  function mhz(hz) { return (hz / 1e6).toFixed(3).replace(".", ","); }

  /* Image PNG du rapport (data URL) : bandeau du haut (modèle, bornes), waterfall, graduations, pied (date, logiciel). */
  function exportPng(doc, rows, meta) {
    if (!rows || !rows.length) return null;
    const W = 960, rowH = 2, top = 48, bottom = 46, h = rows.length * rowH;
    const c = doc.createElement("canvas"); c.width = W; c.height = top + h + bottom;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#0b1118"; ctx.fillRect(0, 0, W, c.height);
    const strip = doc.createElement("canvas"); strip.width = W; strip.height = rows.length;
    const sctx = strip.getContext("2d");
    rows.slice().reverse().forEach((r, y) => paintRow(sctx, y, resample(r, W), meta.max || 160));   // le plus récent en haut
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(strip, 0, 0, W, rows.length, 0, top, W, h);
    ctx.fillStyle = "#e9f1fb"; ctx.font = "bold 20px sans-serif"; ctx.textBaseline = "middle";
    ctx.fillText(meta.title || "", 14, top / 2);
    if (meta.edges) {
      ctx.font = "14px sans-serif"; ctx.fillStyle = "#7cc0ff";
      const [a, b] = meta.edges, ticks = 5;
      for (let i = 0; i <= ticks; i++) {
        const x = Math.round(i * (W - 1) / ticks), f = a + (b - a) * i / ticks;
        ctx.fillRect(x, top + h, 1, 6);
        ctx.textAlign = i === 0 ? "left" : i === ticks ? "right" : "center";
        ctx.fillText(mhz(f), x + (i === 0 ? 4 : i === ticks ? -4 : 0), top + h + 16);
      }
      if (meta.freq && meta.freq >= a && meta.freq <= b) {                    // fréquence du poste : trait orange
        const x = Math.round((meta.freq - a) / (b - a) * (W - 1));
        ctx.fillStyle = "#f0a830"; ctx.fillRect(x, top, 1, h);
      }
    }
    ctx.textAlign = "left"; ctx.fillStyle = "#7f90a5"; ctx.font = "13px sans-serif";
    ctx.fillText(meta.footer || "", 14, top + h + bottom - 12);
    ctx.textAlign = "right"; ctx.fillText("openRemoteTRX-Autotest · www.rf-diy.com", W - 14, top + h + bottom - 12);   // i18n-ok
    return c.toDataURL("image/png");
  }

  const api = { STOPS, MAX_ROWS, colorAt, resample, keep, Live, exportPng };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AutotestWaterfall = api;
})(typeof window !== "undefined" ? window : globalThis);
