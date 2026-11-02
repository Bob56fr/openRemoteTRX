// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Mesure de TOS (docs/tos-cahier-des-charges.md) : calculs purs de la page, MÊMES résultats que la station
   (trxstation/swr/plan.py) et l'application (logic/Swr.kt) ; exemples partagés tests/protocol/swr_plans.json.
   La table des bandes propose la plage par défaut et avertit hors radioamateur ; elle n'autorise JAMAIS une émission
   (c'est la station qui décide, comme pour toute émission). */
(function (root) {
  "use strict";

  const NICE_STEPS_HZ = [1000, 2000, 5000, 10000, 25000, 50000, 75000, 100000, 150000, 200000, 250000, 500000, 1000000];
  const MAX_POINTS = 50;
  const SCALE_KNEE = 0.7, SCALE_MAX = 5;
  const GRID = [1.2, 1.3, 1.4, 1.5, 1.8, 2.0];
  const band = (name, kind, low, high) => ({ name: name, kind: kind, low_hz: low, high_hz: high });
  const BANDS = [
    band("160m", "amateur", 1810000, 2000000), band("80m", "amateur", 3500000, 3800000), band("60m", "amateur", 5351500, 5366500),
    band("40m", "amateur", 7000000, 7200000), band("30m", "amateur", 10100000, 10150000), band("20m", "amateur", 14000000, 14350000),
    band("17m", "amateur", 18068000, 18168000), band("15m", "amateur", 21000000, 21450000), band("12m", "amateur", 24890000, 24990000),
    band("10m", "amateur", 28000000, 29700000), band("6m", "amateur", 50000000, 52000000), band("2m", "amateur", 144000000, 146000000),
    band("70cm", "amateur", 430000000, 440000000),
    band("CB", "cb", 26000000, 28000000), band("45m", "45m", 6620000, 6700000), band("85m", "45m", 3410000, 3490000),
    band("marine 4 MHz", "marine", 4063000, 4438000), band("marine 6 MHz", "marine", 6200000, 6525000),
    band("marine 8 MHz", "marine", 8195000, 8815000), band("marine 12 MHz", "marine", 12230000, 13200000),
    band("marine 16 MHz", "marine", 16360000, 17410000), band("marine 18 MHz", "marine", 18780000, 18900000),
    band("marine 19 MHz", "marine", 19680000, 19800000), band("marine 22 MHz", "marine", 22000000, 22855000),
    band("marine 25 MHz", "marine", 25070000, 25210000), band("marine 26 MHz", "marine", 26100000, 26175000),
  ];

  function bandAt(hz) {
    /* Bande de la table qui contient hz (radioamateur d'abord), ou null. */
    return BANDS.find((b) => b.low_hz <= hz && hz <= b.high_hz) || null;
  }

  function isAmateur(hz) {
    return BANDS.some((b) => b.kind === "amateur" && b.low_hz <= hz && hz <= b.high_hz);
  }

  function rangeFromCenter(centerHz, widthHz) {
    /* FreqBasse et FreqHaute d'une fréquence centrale et d'une largeur ; null si impossible. */
    if (!(centerHz > 0) || !(widthHz > 0)) return null;
    const half = Math.floor(widthHz / 2);
    return { lowHz: centerHz - half, highHz: centerHz + (widthHz - half) };
  }

  function niceStep(rawHz) {
    /* Valeur lisible la plus proche du pas brut (à égalité, la plus petite). */
    let best = NICE_STEPS_HZ[0];
    for (const s of NICE_STEPS_HZ) if (Math.abs(s - rawHz) < Math.abs(best - rawHz)) best = s;
    return best;
  }

  function plan(lowHz, highHz, points, maxPoints) {
    /* { stepHz, freqs, amateurOnly } ou { error } (motif du protocole swr_*). */
    const max = maxPoints || MAX_POINTS;
    if (!Number.isInteger(points) || points < 2) return { error: "swr_bad_range" };
    if (!(lowHz > 0) || !(highHz > lowHz)) return { error: "swr_bad_range" };
    let step = niceStep((highHz - lowHz) / (points - 1)), index = NICE_STEPS_HZ.indexOf(step), freqs;
    for (;;) {
      freqs = [];
      for (let f = Math.ceil(lowHz / step) * step; f <= highHz; f += step) freqs.push(f);
      if (freqs.length <= max) break;
      if (index + 1 >= NICE_STEPS_HZ.length) return { error: "swr_too_many_points" };
      step = NICE_STEPS_HZ[++index];
    }
    if (freqs.length < 2) return { error: "swr_bad_range" };
    return { lowHz: lowHz, highHz: highHz, stepHz: step, freqs: freqs, amateurOnly: freqs.every(isAmateur) };
  }

  function scaleY(swr) {
    /* Hauteur (0 à 1) d'un TOS sur l'axe non linéaire : 1 à 2 sur 70 % de la hauteur, 2 à 5 sur 30 %, plafond 5. */
    if (!Number.isFinite(swr) || swr <= 1) return 0;
    if (swr <= 2) return Math.round(SCALE_KNEE * (swr - 1) * 1e6) / 1e6;
    return Math.round(Math.min(1, SCALE_KNEE + (1 - SCALE_KNEE) * (swr - 2) / (SCALE_MAX - 2)) * 1e6) / 1e6;
  }

  function level(swr) {
    /* good jusqu'à 1,5 (vert), fair jusqu'à 2 (orange), bad au-dessus de 2 (rouge). */
    return swr <= 1.5 ? "good" : swr <= 2 ? "fair" : "bad";
  }

  const api = { NICE_STEPS_HZ, MAX_POINTS, GRID, BANDS, bandAt, isAmateur, rangeFromCenter, niceStep, plan, scaleY, level };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.TrxSwr = api;
})(typeof window !== "undefined" ? window : globalThis);
