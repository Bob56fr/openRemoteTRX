// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Spectre HF du poste (second port CI-V) : calculs purs de la vue plein écran. Le dessin est dans ui.js, les couleurs
   viennent du thème (variables CSS) ; aucune couleur ici. Trames reçues : voir parseSpectrumFrame (client.js). */
(function (root) {
  "use strict";

  const GAINS = [-12, -6, 0, 6, 12, 18];             // décalage de sensibilité des couleurs, en dB (2 niveaux du poste par dB)
  const LEVELS_PER_DB = 2;                           // Icom : 0..160 pour -80..0 dB
  const RANGES_DB = [80, 60, 40, 30, 20];            // plage de couleurs ; 80 = toute l'échelle du poste, sinon plancher de bruit automatique
  const DEFAULT_RANGE_DB = 40;
  const FLOOR_MARGIN_DB = 2;                         // le plancher de bruit apparaît juste au-dessus du noir
  const FLOOR_SMOOTHING = 0.2;                       // part du nouveau balayage dans le plancher (évite le scintillement)
  const TICK_STEPS = [1e3, 2e3, 2.5e3, 5e3, 1e4, 2e4, 2.5e4, 5e4, 1e5, 2e5, 2.5e5, 5e5, 1e6, 2e6, 5e6];
  const VIEWS = ["tx", "audio", "hf"];               // zone des graphiques : puissance -> spectre audio -> spectre HF

  function nextView(current, hfAvailable) {
    /* Bascule de la zone : le spectre HF n'est proposé que s'il est disponible ; HF -> retour aux graphiques. */
    if (current === "tx") return "audio";
    if (current === "audio") return hfAvailable ? "hf" : "tx";
    return "tx";
  }

  function available(hello, state) {
    /* Spectre HF annoncé par la station ET reçu en ce moment. */
    return !!(hello && hello.spectrum && state && state.spectrum && state.spectrum.state === "ok");
  }

  function configured(hello) {
    /* La station a un spectre configuré : la vue HF est TOUJOURS proposée (même s'il ne reçoit rien en ce moment :
       la vue dit pourquoi, et son ouverture relance un essai côté station). */
    return !!(hello && hello.spectrum);
  }

  function waitText(state) {
    /* Texte affiché à la place du spectre tant qu'aucun balayage n'arrive. */
    const sp = (state && state.spectrum) || {};
    if (sp.state === "ok") return "En attente du spectre du poste…";
    if (sp.state === "waiting" || sp.state === "starting") return "Mise en route du spectre du poste…";
    const why = typeof sp.message === "string" && sp.message ? sp.message.slice(0, 300) : (sp.code || "raison inconnue");
    return "Le poste n'envoie pas de spectre : " + why + " Nouvel essai à chaque ouverture de cette vue.";
  }

  function levelT(value, levelMax, gainDb) {
    const max = levelMax > 0 ? levelMax : 160;
    const v = Number.isFinite(value) ? value : 0;
    return Math.min(1, Math.max(0, (v + (gainDb || 0) * LEVELS_PER_DB) / max));
  }

  function noiseFloor(points) {
    /* Plancher de bruit d'un balayage : médiane des niveaux (la plupart des points sont du bruit). */
    if (!points || !points.length) return 0;
    const sorted = Array.from(points).sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length / 2)];
  }

  function colorWindow(points, levelMax, rangeDb, previousFloor) {
    /* Fenêtre de niveaux colorée du noir au blanc : { bottom, span, floor }. Pleine échelle (80 dB) : 0..level_max ;
       sinon elle part juste sous le plancher de bruit (lissé d'un balayage à l'autre) et couvre `rangeDb`. */
    const max = levelMax > 0 ? levelMax : 160;
    const span = Math.min(max, (RANGES_DB.includes(rangeDb) ? rangeDb : DEFAULT_RANGE_DB) * LEVELS_PER_DB);
    if (span >= max) return { bottom: 0, span: max, floor: null };
    const current = noiseFloor(points);
    const floor = Number.isFinite(previousFloor) ? previousFloor + (current - previousFloor) * FLOOR_SMOOTHING : current;
    const bottom = Math.min(max - span, Math.max(0, floor - FLOOR_MARGIN_DB * LEVELS_PER_DB));
    return { bottom: bottom, span: span, floor: floor };
  }

  function windowT(value, win, gainDb) {
    /* Niveau du poste -> 0..1 dans la fenêtre ; le gain (dB) éclaircit ou assombrit. */
    const v = Number.isFinite(value) ? value : 0;
    return Math.min(1, Math.max(0, (v + (gainDb || 0) * LEVELS_PER_DB - win.bottom) / win.span));
  }

  function interpolateRow(points, width, out) {
    /* `width` valeurs par interpolation linéaire entre les points du poste (dessin à la résolution de l'écran,
       sans marches d'escalier). Le poste ne fournit pas plus de détail : on lisse, on n'invente pas de signal. */
    const result = out && out.length === width ? out : new Float32Array(width);
    const n = points.length;
    if (n === 1) { result.fill(points[0]); return result; }
    const scale = width > 1 ? (n - 1) / (width - 1) : 0;
    for (let x = 0; x < width; x++) {
      const pos = x * scale, i = Math.min(n - 2, Math.floor(pos)), k = pos - i;
      result[x] = points[i] * (1 - k) + points[i + 1] * k;
    }
    return result;
  }

  function canvasSize(cssWidth, cssHeight, ratio, fallbackWidth, fallbackHeight) {
    /* Taille en pixels réels de l'écran (taille affichée × densité), bornée pour la mémoire. */
    const r = ratio > 0 ? Math.min(ratio, 4) : 1;
    const w = cssWidth > 0 ? cssWidth : fallbackWidth, h = cssHeight > 0 ? cssHeight : fallbackHeight;
    return { width: Math.max(1, Math.min(4096, Math.round(w * r))), height: Math.max(1, Math.min(4096, Math.round(h * r))) };
  }

  function lineHeight(ratio) {
    /* Hauteur d'une ligne du waterfall : environ 2 pixels CSS, en pixels réels. */
    return Math.max(1, Math.round(2 * (ratio > 0 ? Math.min(ratio, 4) : 1)));
  }

  function tickStep(spanHz, maxTicks) {
    const most = maxTicks || 8;
    for (const step of TICK_STEPS) if (spanHz / step <= most) return step;
    return TICK_STEPS[TICK_STEPS.length - 1];
  }

  function mhzLabel(hz, stepHz) {
    /* 14.050 pour un pas de 5 kHz, 14.0525 pour 2,5 kHz, 14.1 pour 100 kHz : juste assez de décimales. */
    let decimals = 0;
    while (decimals < 6 && Math.abs(Math.round(stepHz / 10 ** (6 - decimals)) * 10 ** (6 - decimals) - stepHz) > 1e-6) decimals++;
    return (hz / 1e6).toFixed(decimals);
  }

  function scopeTicks(lowHz, highHz, maxTicks) {
    /* Graduations « rondes » entre les deux bords : { hz, fraction (0..1), label en MHz }. */
    const span = highHz - lowHz;
    if (!(span > 0)) return [];
    const step = tickStep(span, maxTicks);
    const ticks = [];
    for (let hz = Math.ceil(lowHz / step) * step; hz <= highHz; hz += step) {
      ticks.push({ hz: hz, fraction: (hz - lowHz) / span, label: mhzLabel(hz, step) });
    }
    return ticks;
  }

  function markerFraction(hz, lowHz, highHz) {
    /* Position de la fréquence du poste sur l'échelle (0..1), null hors de l'écran. */
    if (!Number.isFinite(hz) || !(highHz > lowHz) || hz < lowHz || hz > highHz) return null;
    return (hz - lowHz) / (highHz - lowHz);
  }

  function sameScale(a, b) {
    /* Même échelle de fréquence et même nombre de points : l'historique du waterfall reste valable. */
    return !!(a && b && a.lowHz === b.lowHz && a.highHz === b.highHz && a.points.length === b.points.length);
  }

  function spanLabel(lowHz, highHz) {
    const span = highHz - lowHz;
    return span >= 1e6 ? (span / 1e6).toFixed(span % 1e6 ? 1 : 0) + " MHz" : (span / 1e3).toFixed(span % 1e3 ? 1 : 0) + " kHz";
  }

  const gainLabel = (v) => "GAIN " + (v > 0 ? "+" + v : v);
  const rangeLabel = (v) => (v >= 80 ? "PLAGE 80 dB" : "PLAGE " + v + " dB");

  function normalizeSettings(raw) {
    const r = raw && typeof raw === "object" ? raw : {};
    return { gain: GAINS.includes(r.gain) ? r.gain : 0, range: RANGES_DB.includes(r.range) ? r.range : DEFAULT_RANGE_DB };
  }

  function nextRange(range) {
    const i = RANGES_DB.indexOf(range);
    return RANGES_DB[(i + 1) % RANGES_DB.length];
  }

  // ---- réglages du spectre DU POSTE (envoyés à la station : spectrum_set ; mêmes listes fermées que spectrum/civ.py)
  const SPANS_HZ = [2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000];
  const MODE_LABELS = { center: "CENT", fixed: "FIX", scroll_center: "SCR-C", scroll_fixed: "SCR-F" };
  const SPEED_LABELS = { fast: "VIT RAP", mid: "VIT MOY", slow: "VIT LENT" };
  const SPEED_ORDER = ["fast", "mid", "slow"];
  const REF_MIN = -20, REF_MAX = 20, REF_UI_STEP = 1;

  const modeSettingLabel = (m) => MODE_LABELS[m] || "MODE ?";
  const nextMode = (m) => (m === "center" ? "fixed" : "center");          // défilement (lu seulement) -> centré
  function spanSettingLabel(hz) {
    if (!Number.isFinite(hz)) return "SPAN ?";
    return "±" + (hz >= 1000 ? (hz / 1000).toString().replace(".", ",") + "k" : hz);
  }
  function nextSpan(hz) {
    const i = SPANS_HZ.indexOf(hz);
    return SPANS_HZ[(i + 1) % SPANS_HZ.length];
  }
  const speedSettingLabel = (s) => SPEED_LABELS[s] || "VIT ?";
  function nextSpeed(s) {
    const i = SPEED_ORDER.indexOf(s);
    return SPEED_ORDER[(i + 1) % SPEED_ORDER.length];
  }
  function refLabel(db) {
    if (!Number.isFinite(db)) return "REF ?";
    return "REF " + (db > 0 ? "+" : "") + db.toFixed(1).replace(".", ",");
  }
  function stepRef(db, delta) {
    /* Pas de 1 dB, ramené sur la grille de 0,5 dB du poste et borné à ±20 dB ; null si la valeur actuelle est inconnue. */
    if (!Number.isFinite(db)) return null;
    const next = Math.round((db + delta) * 2) / 2;
    return Math.min(REF_MAX, Math.max(REF_MIN, next));
  }

  // ---- accord au doigt (bouton VFO allumé) : glisser le spectre comme on tourne le VFO
  const TUNE_STEPS = [10, 50, 100, 500, 1000];

  function tuneStep(spanHz) {
    /* Pas d'accord adapté à la largeur affichée : environ 400 pas sur l'écran (10 Hz à ±2,5 kHz, 500 Hz à ±100 kHz). */
    let step = TUNE_STEPS[0];
    for (const s of TUNE_STEPS) if (s <= spanHz / 400) step = s;
    return step;
  }

  function dragSteps(dxCss, plotWidthCss, spanHz, stepHz) {
    /* Nombre de pas pour un glissement : tirer le spectre vers la GAUCHE fait monter la fréquence (le signal vient
       vers le repère), comme un VFO. 0 si les dimensions sont inconnues. */
    if (!(plotWidthCss > 0) || !(spanHz > 0) || !(stepHz > 0) || !Number.isFinite(dxCss)) return 0;
    return Math.round((-dxCss * spanHz) / plotWidthCss / stepHz) || 0;
  }

  function nextGain(gain) {
    const i = GAINS.indexOf(gain);
    return GAINS[(i + 1) % GAINS.length];
  }

  // Waterfall HF intégré en permanence (en haut de la colonne de droite) : critère d'AFFICHAGE seulement (paysage assez
  // large, page d'usine), jamais la catégorie d'appareil. Les sécurités d'émission sont dans la station, quel que soit l'affichage.
  const DOCK_MIN_WIDTH = 1000;

  function canDock(layoutName, width, customLayout) {
    return layoutName === "landscape" && Number.isFinite(width) && width >= DOCK_MIN_WIDTH && !customLayout;
  }

  const api = { DOCK_MIN_WIDTH, canDock, configured, waitText, GAINS, VIEWS, LEVELS_PER_DB, RANGES_DB, DEFAULT_RANGE_DB, nextView, available, levelT, noiseFloor, colorWindow,
                windowT, interpolateRow, canvasSize, lineHeight, tickStep, mhzLabel, scopeTicks, markerFraction,
                sameScale, spanLabel, gainLabel, rangeLabel, normalizeSettings, nextGain, nextRange,
                SPANS_HZ, REF_UI_STEP, modeSettingLabel, nextMode, spanSettingLabel, nextSpan, speedSettingLabel, nextSpeed,
                refLabel, stepRef, tuneStep, dragSteps };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxHfScope = api; }
})(typeof window !== "undefined" ? window : globalThis);
