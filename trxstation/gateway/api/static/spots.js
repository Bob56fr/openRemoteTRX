// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Spots du Cluster DX dans la vue HF : calculs purs (testés sous Node), AUCUNE couleur ni accès au DOM.
   Les spots arrivent du module « cluster » (trxstation/cluster/publish.py) : instantané de la bande courante,
   puis changements ; seulement pendant que la vue HF est ouverte. */
(function (root) {
  "use strict";

  const FRESH_S = 120;            // spot de moins de 2 min : mis en évidence
  const FADE_TO = 0.35;           // opacité d'un spot en fin de vie
  const DEFAULT_TTL_S = 900;      // 15 min (durée de vie par défaut côté station)
  const KINDS = { cluster: "DX", rbn: "RBN", cb: "CB" };
  const MODE_NAMES = { SSB: "BLU", AM: "AM", FM: "FM", FREEDV: "FreeDV", CW: "CW" };

  function cleanText(value, max) {
    return typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f‪-‮⁦-⁩]/g, "").slice(0, max) : "";
  }

  function cleanSpot(raw, nowMs) {
    /* Spot reçu (clés courtes) -> objet sûr ; null s'il est inutilisable. */
    if (!raw || typeof raw !== "object" || !Number.isInteger(raw.id) || !Number.isFinite(raw.f) || raw.f <= 0) return null;
    const dx = cleanText(raw.dx, 20);
    if (!dx) return null;
    return {
      id: raw.id, khz: raw.f, hz: Math.round(raw.f * 1000), dx: dx, de: cleanText(raw.de, 20),
      mode: cleanText(raw.m, 10), modeGuessed: !!raw.mg, kind: KINDS[raw.k] ? raw.k : "cluster",
      time: cleanText(raw.t, 4), count: Number.isInteger(raw.n) && raw.n > 0 ? raw.n : 1,
      comment: cleanText(raw.c, 80), country: cleanText(raw.co, 40), continent: cleanText(raw.ct, 2),
      qsyMode: cleanText(raw.q, 10), age0: Number.isFinite(raw.age) && raw.age >= 0 ? raw.age : 0, recv: nowMs,
    };
  }

  class SpotBook {
    constructor() { this.map = new Map(); this.window = null; this.version = 0; }

    clear() { this.map.clear(); this.window = null; this.version++; }

    apply(msg, nowMs) {
      /* Instantané ou changements ; vrai si quelque chose a changé. */
      if (!msg || msg.kind !== "spots" || !Array.isArray(msg.spots)) return false;
      if (msg.op === "snapshot") {
        this.map.clear();
        this.window = Array.isArray(msg.window) && msg.window.length === 2 ? [Number(msg.window[0]), Number(msg.window[1])] : null;
      } else if (msg.op !== "delta") {
        return false;
      }
      for (const raw of msg.spots.slice(0, 500)) {
        const s = cleanSpot(raw, nowMs);
        if (s) this.map.set(s.id, s);
      }
      if (Array.isArray(msg.removed)) for (const id of msg.removed) this.map.delete(id);
      this.version++;
      return true;
    }

    all() { return Array.from(this.map.values()); }

    get(id) { return this.map.get(id) || null; }

    visible(lowHz, highHz) {
      return this.all().filter((s) => s.hz >= lowHz && s.hz <= highHz).sort((a, b) => a.hz - b.hz);
    }
  }

  function ageSeconds(spot, nowMs) {
    return spot.age0 + Math.max(0, (nowMs - spot.recv) / 1000);
  }

  function opacity(ageS, ttlS) {
    const ttl = ttlS > FRESH_S ? ttlS : DEFAULT_TTL_S;
    if (ageS <= FRESH_S) return 1;
    const t = Math.min(1, (ageS - FRESH_S) / (ttl - FRESH_S));
    return Math.round((1 - t * (1 - FADE_TO)) * 100) / 100;
  }

  function ageLabel(ageS) {
    if (ageS < 60) return "à l'instant";
    const min = Math.floor(ageS / 60);
    return min < 60 ? "il y a " + min + " min" : "il y a " + Math.floor(min / 60) + " h " + String(min % 60).padStart(2, "0");
  }

  function layoutLabels(spots, lowHz, highHz, widthPx, opts) {
    /* Étiquettes des marqueurs : rangées l'une sous l'autre quand elles se chevauchent, puis regroupées en « +N ».
       spots : triés par fréquence. Retour : [{x, row, text, ids, group}] (x en px, centre de l'étiquette). */
    const o = Object.assign({ rows: 3, charPx: 7, padPx: 10, gapPx: 4 }, opts || {});
    const span = highHz - lowHz;
    if (!(span > 0) || !(widthPx > 0)) return [];
    const width = (text) => text.length * o.charPx + o.padPx;
    const right = new Array(o.rows).fill(-Infinity);
    const placed = [], left = [];
    for (const s of spots) {
      const x = ((s.hz - lowHz) / span) * widthPx, w = width(s.dx);
      let row = -1;
      for (let r = 0; r < o.rows; r++) {
        if (x - w / 2 >= right[r] + o.gapPx) { row = r; break; }
      }
      if (row < 0) { left.push({ spot: s, x: x }); continue; }
      right[row] = x + w / 2;
      placed.push({ x: x, row: row, text: s.dx, ids: [s.id], group: false });
    }
    // restes : regroupés par voisinage, sur une rangée de plus
    const groups = [];
    for (const item of left) {
      const last = groups[groups.length - 1];
      if (last && item.x - last.x1 <= width("+99")) { last.ids.push(item.spot.id); last.x1 = item.x; }
      else groups.push({ x0: item.x, x1: item.x, ids: [item.spot.id] });
    }
    let groupRight = -Infinity;
    for (const g of groups) {
      const x = (g.x0 + g.x1) / 2, text = "+" + g.ids.length, w = width(text);
      const prev = placed[placed.length - 1];
      if (x - w / 2 < groupRight + o.gapPx && prev && prev.group) {      // pas la place : fondu dans le groupe précédent
        prev.ids = prev.ids.concat(g.ids); prev.text = "+" + prev.ids.length;
        continue;
      }
      groupRight = x + w / 2;
      placed.push({ x: x, row: o.rows, text: text, ids: g.ids.slice(), group: true });
    }
    return placed;
  }

  function sortList(spots, by, nowMs) {
    const copy = spots.slice();
    if (by === "age") copy.sort((a, b) => ageSeconds(a, nowMs) - ageSeconds(b, nowMs) || a.hz - b.hz);
    else copy.sort((a, b) => a.hz - b.hz);
    return copy;
  }

  function modeLabel(spot) {
    const name = MODE_NAMES[spot.mode] || spot.mode || "?";
    return spot.modeGuessed ? name + " (supposé)" : name;
  }

  function kindLabel(kind) { return KINDS[kind] || "DX"; }

  function qsyTarget(spot, adapt) {
    /* {hz, mode|null} ; `adapt(mode)` = mode utilisable par ce poste (adaptMode de client.js) ou null. */
    if (!spot || !(spot.hz > 0)) return null;
    let mode = spot.qsyMode || null;
    if (mode && typeof adapt === "function") mode = adapt(mode);
    return { hz: spot.hz, mode: mode || null };
  }

  function arrivalMs(spot) {
    /* Heure d'arrivée (ms, horloge du navigateur) : réception moins l'âge qu'avait alors le spot. */
    return spot.recv - spot.age0 * 1000;
  }

  function recentList(msg, nowMs) {
    /* Message « recent » du module : les derniers spots TOUTES BANDES, le plus récent en tête (30 au plus). */
    if (!msg || msg.kind !== "recent" || !Array.isArray(msg.spots)) return [];
    const out = [];
    for (const raw of msg.spots.slice(0, 60)) { const s = cleanSpot(raw, nowMs); if (s) out.push(s); }
    out.sort((a, b) => arrivalMs(b) - arrivalMs(a));
    return out.slice(0, 30);
  }

  function sourceLabel(spot) {
    return kindLabel(spot.kind) + (spot.de ? " de " + spot.de : "");
  }

  function healthLabel(state) {
    return { green: "Cluster DX : toutes les sources connectées", orange: "Cluster DX : sources en partie connectées",
             red: "Cluster DX : aucune source connectée", off: "Cluster DX désactivé" }[state] || "";
  }

  const api = { SpotBook, cleanSpot, ageSeconds, opacity, ageLabel, layoutLabels, sortList, modeLabel, kindLabel,
                qsyTarget, healthLabel, arrivalMs, recentList, sourceLabel, FRESH_S };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxSpots = api; }
})(typeof window !== "undefined" ? window : globalThis);
