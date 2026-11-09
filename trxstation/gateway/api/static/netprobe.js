// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Sonde de qualité réseau (docs/netprobe-cahier-des-charges.md § 4.4, 4.5, 7, 8.3, 9.1, 9.6) : calculs purs de la page,
   MÊMES résultats que la station (trxstation/netprobe/calc.py) et l'application (logic/NetProbe.kt) ; exemples
   partagés tests/protocol/netprobe_vectors.json. Durées en ms entières sur l'horloge MONOTONE de celui qui envoie le
   battement. Rien ici n'agit sur le poste : la sonde mesure et affiche. */
(function (root) {
  "use strict";

  const LATE_MS = 5000, WINDOWS_MS = [10000, 60000], MIN_MEASURED_MS = 10000, RECENT_OUTAGE_MS = 120000;
  const RTT_EDGES_MS = [50, 100, 150, 200, 250, 300, 400, 600, 800, 1000];
  const LOSS_EDGES_PCT = [0.5, 1, 2, 5, 10, 20];
  const PROPOSE = { minWindows: 2000, minDays: 7, minBucket: 20, warnRatio: 0.05, alertRatio: 0.25 };
  const PATTERN = { windowMs: 600000, minOutages: 4, minPeriodMs: 10000, maxPeriodMs: 150000, maxPeriodCv: 0.25, maxDurationCv: 0.5 };
  const DIAGNOSES = ["app_station", "lan", "box_internet", "webrtc", "phone_radio", "vpn_shared", "mobile_or_tunnel", "unknown"];

  /* Arrondi au dixième, moitié vers le haut (comme la station et l'application). */
  function round1(v) { return Math.floor(v * 10 + 0.5) / 10; }

  /* Indicateurs d'une fenêtre glissante. beats : [{seq, sentMs, pongMs|null}]. Voir calc.window_stats. */
  function windowStats(beats, nowMs, windowMs) {
    const inside = beats.filter((b) => nowMs - windowMs < b.sentMs && b.sentMs <= nowMs);
    const received = [];
    let lost = 0, late = 0;
    for (const b of inside) {
      if (b.pongMs !== null && b.pongMs !== undefined && b.pongMs <= nowMs) {
        if (b.pongMs - b.sentMs >= LATE_MS) { lost++; late++; } else received.push(b);
      } else if (nowMs - b.sentMs >= LATE_MS) lost++;
    }
    const expected = received.length + lost;
    const rtts = received.slice().sort((a, b) => a.seq - b.seq).map((b) => b.pongMs - b.sentMs);
    let jitter = 0;
    for (let i = 1; i < rtts.length; i++) jitter += (Math.abs(rtts[i] - rtts[i - 1]) - jitter) / 16;
    let outOfOrder = 0, highest = null;
    for (const b of received.slice().sort((a, b) => (a.pongMs - b.pongMs) || (a.seq - b.seq))) {
      if (highest !== null && b.seq < highest) outOfOrder++;
      highest = highest === null ? b.seq : Math.max(highest, b.seq);
    }
    const ordered = rtts.slice().sort((a, b) => a - b);
    let sum = 0;
    for (const r of rtts) sum += r;
    return {
      expected: expected, received: received.length, lost: lost, late: late,
      loss_pct: expected ? round1(100 * lost / expected) : null,
      rtt_mean_ms: rtts.length ? round1(sum / rtts.length) : null,
      rtt_p95_ms: ordered.length ? ordered[Math.floor((95 * ordered.length + 99) / 100) - 1] : null,
      rtt_max_ms: ordered.length ? ordered[ordered.length - 1] : null,
      jitter_ms: rtts.length > 1 ? round1(jitter) : null,
      out_of_order: outOfOrder,
    };
  }

  /* Coupures : voir calc.OutageDetector (début à l'envoi du premier battement manqué, fin au premier écho reçu). */
  function OutageDetector(missed, intervalMs) {
    this.missed = missed === undefined ? 3 : missed;
    this.intervalMs = intervalMs === undefined ? 1000 : intervalMs;
    this.pending = new Map();
    this.startMs = null;
  }
  OutageDetector.prototype.ping = function (seq, nowMs) {
    const events = this.tick(nowMs);
    this.pending.set(seq, nowMs);
    return events;
  };
  OutageDetector.prototype.pong = function (seq, nowMs) {
    this.pending.clear();
    if (this.startMs === null) return [];
    const start = this.startMs;
    this.startMs = null;
    return [{ type: "end", start_ms: start, end_ms: nowMs, duration_ms: nowMs - start }];
  };
  OutageDetector.prototype.tick = function (nowMs) {
    if (this.startMs !== null) return [];
    const missed = [];
    for (const t of this.pending.values()) if (nowMs - t >= this.intervalMs) missed.push(t);
    if (missed.length < this.missed) return [];
    missed.sort((a, b) => a - b);
    this.startMs = missed[0];
    return [{ type: "start", start_ms: missed[0], detected_ms: nowMs }];
  };

  const has = (v) => v !== null && v !== undefined;

  /* Niveau de l'indicateur : gray, green, orange ou red. Voir calc.level. */
  function level(i, th) {
    if (i.outageActive) return "red";
    if (i.measuredMs < MIN_MEASURED_MS) return "gray";
    if ((has(i.lossPct) && i.lossPct >= th.loss_alert) || (has(i.rttP95Ms) && i.rttP95Ms >= th.rtt_alert)
        || (has(i.rsrpDbm) && i.rsrpDbm < th.rsrp_alert) || (has(i.sinrDb) && i.sinrDb < th.sinr_alert)) return "red";
    if ((has(i.sinceOutageEndMs) && i.sinceOutageEndMs < RECENT_OUTAGE_MS)
        || (has(i.lossPct) && i.lossPct >= th.loss_warn) || (has(i.rttP95Ms) && i.rttP95Ms >= th.rtt_warn)
        || (has(i.rsrpDbm) && i.rsrpDbm < th.rsrp_warn) || (has(i.sinrDb) && i.sinrDb < th.sinr_warn)) return "orange";
    return "green";
  }

  /* Tronçon probable d'une coupure : voir calc.diagnose (mêmes faits, mêmes codes). */
  function diagnose(f) {
    if (f.station_restarted) return "app_station";
    if (f.lan_probe_down) return "lan";
    if (f.internet_probe_down) return "box_internet";
    if (!f.backlog) return "unknown";
    if (f.health_ok) return "webrtc";
    if (f.radio_weak || f.cell_changed || f.network_switched) return "phone_radio";
    if (f.regular_pattern) return "vpn_shared";
    if (f.health_ok === false) return "mobile_or_tunnel";
    return "unknown";
  }

  function cv(values) {
    let sum = 0;
    for (const v of values) sum += v;
    const mean = sum / values.length;
    if (mean <= 0) return Infinity;
    let sq = 0;
    for (const v of values) sq += (v - mean) ** 2;
    return Math.sqrt(sq / values.length) / mean;
  }

  /* Motif régulier des coupures (profil VPN partagé) : voir calc.regular_pattern. outages : [{start_ms, duration_ms}]. */
  function regularPattern(outages, nowMs) {
    const recent = outages.filter((o) => nowMs - PATTERN.windowMs < o.start_ms && o.start_ms <= nowMs)
      .sort((a, b) => a.start_ms - b.start_ms);
    if (recent.length < PATTERN.minOutages) return { regular: false, period_ms: null };
    const gaps = [];
    for (let i = 1; i < recent.length; i++) gaps.push(recent[i].start_ms - recent[i - 1].start_ms);
    let sum = 0;
    for (const g of gaps) sum += g;
    const period = sum / gaps.length;
    const regular = PATTERN.minPeriodMs <= period && period <= PATTERN.maxPeriodMs && cv(gaps) < PATTERN.maxPeriodCv
      && cv(recent.map((o) => o.duration_ms)) < PATTERN.maxDurationCv;
    return { regular: regular, period_ms: regular ? Math.floor(period + 0.5) : null };
  }

  function bucket(value, edges) {
    for (let i = 0; i < edges.length; i++) if (value < edges[i]) return i;
    return edges.length;
  }
  function lowerEdge(index, edges) { return index === 0 ? 0 : edges[index - 1]; }

  /* Seuils proposés pour un type de réseau et une mesure : voir calc.propose. hist : [{n, degraded}]. */
  function propose(hist, edges, days) {
    let total = 0;
    for (const h of hist) total += h.n;
    if (total < PROPOSE.minWindows || days < PROPOSE.minDays) return null;
    let seen = 0, p75 = hist.length - 1;
    for (let i = 0; i < hist.length; i++) {
      seen += hist[i].n;
      if (seen >= 0.75 * total) { p75 = i; break; }
    }
    const floorValue = Math.max(lowerEdge(p75, edges), edges[0]);
    const first = (ratio) => {
      for (let i = 0; i < hist.length; i++) {
        if (hist[i].n >= PROPOSE.minBucket && hist[i].degraded > ratio * hist[i].n) return Math.max(lowerEdge(i, edges), floorValue);
      }
      return null;
    };
    const warn = first(PROPOSE.warnRatio);
    let alert = first(PROPOSE.alertRatio);
    if (warn === null) return null;
    if (alert === null || alert <= warn) {
      const above = edges.filter((e) => e > warn);
      alert = above.length ? above[0] : null;
    }
    return { warn: warn, alert: alert };
  }

  /* Ce qu'auraient donné des seuils sur l'historique (curseurs) : voir calc.simulate. */
  function simulate(hist, edges, warn, alert) {
    let total = 0;
    const counts = { green: [0, 0], orange: [0, 0], red: [0, 0] };
    hist.forEach((h, i) => {
      total += h.n;
      const low = lowerEdge(i, edges);
      const color = low >= alert ? "red" : low >= warn ? "orange" : "green";
      counts[color][0] += h.n;
      counts[color][1] += h.degraded;
    });
    const pct = (part, whole) => (whole ? round1(100 * part / whole) : null);
    return {
      orange_pct: pct(counts.orange[0], total), red_pct: pct(counts.red[0], total),
      degraded_red_pct: pct(counts.red[1], counts.red[0]), degraded_green_pct: pct(counts.green[1], counts.green[0]),
    };
  }

  const api = { LATE_MS, WINDOWS_MS, MIN_MEASURED_MS, RECENT_OUTAGE_MS, RTT_EDGES_MS, LOSS_EDGES_PCT, DIAGNOSES,
                round1, windowStats, OutageDetector, level, diagnose, regularPattern, bucket, propose, simulate };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.TrxNetProbe = api;
})(typeof window !== "undefined" ? window : globalThis);
