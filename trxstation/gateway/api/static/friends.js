// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Présence de groupe « Amis » (docs/presence-cahier-des-charges.md, docs/protocole.md § 16) : calculs purs de la page,
   testés sous Node (tests/js/friends_test.js) ; âges, pseudo et texte libre vérifiés sur les vecteurs de la station
   (tests/protocol/presence_vectors.json). Rien ici n'agit sur le poste : le QSY vers un ami est confirmé par
   l'opérateur, refusé pendant l'émission, et passe par les commandes habituelles (mode puis fréquence). */
(function (root) {
  "use strict";

  const OFFLINE_AFTER_S = 240;
  const ORDER = { Q: 0, R: 1, S: 2, A: 3, O: 4 };
  const CODES = {
    Q: { label: "En QSO", cls: "q" }, R: { label: "En RX", cls: "r" }, S: { label: "Au shack", cls: "s" },
    A: { label: "Absent", cls: "a" }, O: { label: "Hors ligne", cls: "o" },
  };
  const ROLES = { a: "administrateur", c: "co-administrateur", m: "membre" };
  const STATUS = { member: "", pending: "adhésion en attente de validation", removed: "exclu ou groupe supprimé" };
  const LEVELS = { f: "Fréquence et mode", o: "« On Air » seulement", x: "Un court texte" };
  const DISPLAY_MODES = ["section", "big", "pip"];
  const PSEUDO_RE = /^[A-Za-z0-9](?:[A-Za-z0-9 ./_-]{0,14}[A-Za-z0-9./_-])?$/;
  const TEXT_RE = /^[A-Za-z0-9./-](?:[A-Za-z0-9 ./-]{0,14}[A-Za-z0-9./-])?$/;
  const CONSENT = [
    "L'administrateur du groupe verra des statistiques d'activité AGRÉGÉES de votre station : jours actifs, temps approximatif en QSO et en réception par semaine, date d'adhésion, version de la station. Jamais un emploi du temps détaillé.",
    "Les membres du groupe verront votre statut (en QSO, en réception, au shack, absent, hors ligne) et ce que vous choisissez de partager ci-dessous ; vous pourrez le changer, ou devenir invisible, à tout moment.",
    "Le relais de présence ne voit que des états chiffrés : ni fréquence, ni mode, ni texte, ni statut.",
  ];

  /* Mêmes règles que trxstation/presence/wire.py (vecteurs « pseudo » et « text ») : null si refusé. */
  function squeeze(s) { return s.split(/\s+/).filter(Boolean).join(" "); }
  function cleanPseudo(s) { if (typeof s !== "string") return null; const t = squeeze(s); return PSEUDO_RE.test(t) ? t : null; }
  function cleanText(s) { if (typeof s !== "string") return null; const t = squeeze(s); return TEXT_RE.test(t) ? t : null; }

  /* Comme trxstation/presence/status.py format_age (vecteurs « format_age ») : « 3 min », « 2 h », « 4 j ». */
  function formatAge(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    if (s < 3600) return Math.max(1, Math.floor(s / 60)) + " min";
    if (s < 86400) return Math.floor(s / 3600) + " h";
    return Math.floor(s / 86400) + " j";
  }

  /* Âge court pour « mis à jour il y a … » : secondes sous la minute. */
  function freshness(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    return s < 60 ? s + " s" : formatAge(s);
  }

  function frequencyText(hz) {
    if (!Number.isFinite(hz)) return "";
    return (hz / 1e6).toFixed(3).replace(".", ",") + " MHz";
  }

  function clock(epochS) {
    const d = new Date(epochS * 1000);
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  /* Un membre tel qu'affiché. `elapsedS` : secondes depuis la lecture de la vue (les âges avancent sans redemander). */
  function memberView(m, nowS, elapsedS) {
    const e = Math.max(0, elapsedS || 0);
    let code = CODES[m.code] ? m.code : "O";
    if ((m.age || 0) + e > OFFLINE_AFTER_S) code = "O";                // plus de nouvelles : hors ligne, sans attendre la vue
    const c = CODES[code];
    let detail;
    if (code === "O") detail = "Hors ligne";
    else if (code === "S") detail = Number.isFinite(m.su) ? "Au shack jusqu'à " + clock(m.su) : "Au shack";
    else if (code === "A") detail = Number.isFinite(m.sd) ? "Absent depuis " + formatAge(nowS - m.sd) : "Absent";
    else if (m.lv === "f" && Number.isFinite(m.f)) detail = frequencyText(m.f) + (m.m ? " " + m.m : "");   // En QSO, En RX
    else if (m.lv === "x" && m.x) detail = "« " + m.x + " »";
    else detail = code === "Q" ? "On Air" : c.label;
    const lines = [];
    if (code !== "O") {
      if (Number.isFinite(m.sd)) lines.push(c.label + " depuis " + formatAge(nowS - m.sd));
      if (Number.isFinite(m.lt)) lines.push("Dernière émission il y a " + formatAge(nowS - m.lt));
      if (Number.isFinite(m.updated)) lines.push("Mis à jour il y a " + freshness(m.updated + e));
    } else {
      lines.push("Dernière nouvelle il y a " + formatAge((m.age || 0) + e));
    }
    return { id: m.id, pseudo: m.pseudo || "?", code: code, letter: code === "O" ? "" : code, cls: c.cls, label: c.label,
             detail: detail, lines: lines, qsy: code !== "O" && m.lv === "f" && Number.isFinite(m.f) && !!m.m,
             f: m.f, m: m.m, txOk: m.tx_ok, raw: m };
  }

  function sortMembers(list) {
    return list.slice().sort((a, b) => (ORDER[a.code] - ORDER[b.code]) || a.pseudo.localeCompare(b.pseudo, "fr", { sensitivity: "base" }));
  }

  /* Vue complète : par groupe (défaut) ou par membre (un membre de plusieurs groupes une seule fois, avec ses groupes). */
  function buildView(view, nowS, elapsedS, by) {
    const groups = (view && Array.isArray(view.groups) ? view.groups : []).map((g) => ({
      g: g.g, name: g.name, role: g.role, roleText: ROLES[g.role] || "", status: g.status, statusText: STATUS[g.status] || "",
      share: g.share || {}, admin: g.role === "a" || g.role === "c", count: g.count,
      members: sortMembers((g.members || []).map((m) => memberView(m, nowS, elapsedS))),
    }));
    if (by !== "member") return { by: "group", groups: groups };
    const seen = new Map();
    for (const g of groups) {
      for (const m of g.members) {
        const known = seen.get(m.id);
        if (!known || ORDER[m.code] < ORDER[known.code]) seen.set(m.id, Object.assign({}, m, { groups: known ? known.groups : [] }));
        seen.get(m.id).groups.push(g.name);
      }
    }
    return { by: "member", groups: groups, members: sortMembers(Array.from(seen.values())) };
  }

  /* Pastilles du bandeau : actifs d'abord, `max` au plus. */
  function badges(view, nowS, elapsedS, max) {
    const all = buildView(view, nowS, elapsedS, "member").members;
    return { list: all.filter((m) => m.code !== "O").slice(0, max || 8), active: all.filter((m) => m.code === "Q" || m.code === "R").length,
             total: all.length };
  }

  const BAND_EDGES_KHZ = [[1810, 2000], [3500, 3800], [5351, 5367], [7000, 7200], [10100, 10150], [14000, 14350],
                          [18068, 18168], [21000, 21450], [24890, 24990], [26960, 27410], [28000, 29700], [50000, 54000],
                          [144000, 146000], [430000, 440000]];
  function bandOf(hz) {
    const k = hz / 1000;
    const b = BAND_EDGES_KHZ.find(([lo, hi]) => k >= lo && k <= hi);
    return b ? b[0] : null;
  }

  /* Ce que demande le QSY vers un ami : refus, ou texte de confirmation et avertissements.
     ctx : { pttState, rigHz, selfCode, nowS }. */
  function qsyPlan(member, ctx) {
    const c = ctx || {};
    if (c.pttState && c.pttState !== "RX") return { ok: false, reason: "tx_active", text: "Émission en cours : pas de QSY." };
    if (!member || !member.qsy) return { ok: false, reason: "no_frequency", text: "Ce membre ne partage pas sa fréquence." };
    const warnings = [];
    if (c.selfCode === "Q") warnings.push({ level: "strong", text: "Vous êtes en QSO : votre correspondant ne vous entendra plus sur votre fréquence actuelle." });
    if (member.lines.length) warnings.push({ level: "info", text: member.lines.join(" · ") });
    if (Number.isFinite(c.rigHz) && bandOf(c.rigHz) !== bandOf(member.f)) {
      warnings.push({ level: "warn", text: "Changement de bande : vérifiez l'accord de l'antenne avant d'émettre." });
    }
    if (member.txOk === false) warnings.push({ level: "warn", text: "Hors des bandes d'émission de cette station : réception seulement." });
    return { ok: true, text: "Aller sur " + frequencyText(member.f) + " " + member.m + " ?", hz: member.f, mode: member.m,
             warnings: warnings };
  }

  /* Statistiques de l'administrateur (action « stats ») en lignes lisibles. */
  function statsRows(stats, pseudos) {
    return Object.keys(stats || {}).map((id) => {
      const s = stats[id] || {};
      const week = (s.weeks || [])[0] || { qso_min: 0, rx_min: 0 };
      return { id: id, pseudo: (pseudos && pseudos[id]) || id.slice(0, 8), lastActive: s.last_active || "—",
               days: s.active_days_month || 0, qsoMin: week.qso_min, rxMin: week.rx_min, weeks: s.weeks || [] };
    }).sort((a, b) => a.pseudo.localeCompare(b.pseudo, "fr", { sensitivity: "base" }));
  }

  /* Fenêtre détachée (Document Picture-in-Picture : Chrome, Edge) ; ailleurs le choix n'est pas proposé. */
  function pipSupported(win) {
    return !!(win && win.documentPictureInPicture && typeof win.documentPictureInPicture.requestWindow === "function");
  }

  function displayMode(stored, pip) {
    const mode = DISPLAY_MODES.includes(stored) ? stored : "section";
    return mode === "pip" && !pip ? "section" : mode;
  }

  /* Invitation collée : on garde l'URL entière (ou le seul code après #), sans espaces. */
  function cleanInvitation(text) {
    if (typeof text !== "string") return null;
    const t = text.trim().replace(/\s+/g, "");
    return t.length >= 20 && t.length <= 1000 ? t : null;
  }

  const api = { OFFLINE_AFTER_S, ORDER, CODES, ROLES, STATUS, LEVELS, DISPLAY_MODES, CONSENT, cleanPseudo, cleanText,
                formatAge, freshness, frequencyText, memberView, sortMembers, buildView, badges, bandOf, qsyPlan, statsRows,
                pipSupported, displayMode, cleanInvitation };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.TrxFriends = api;
})(typeof window !== "undefined" ? window : globalThis);
