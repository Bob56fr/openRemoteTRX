// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Monitoring inter-stations dans la page (docs/cdc-monitoring.md § 17, lot R5 ; protocole : docs/protocole.md § 19) :
   calculs purs, testés sous Node (tests/js/monitoring_test.js), sans DOM. Le dessin est dans ui.js (rubrique
   « Monitoring »). Mêmes actions que le menu 6.5 de TRX Console ; le module « monlink » n'agit jamais sur le poste et
   la station qui aide ne peut que lire et DEMANDER. */
(function (root) {
  "use strict";   // i18n-ok

  const I18N = root.TrxI18n || (typeof require === "function" ? require("./i18n.js") : null);

  // Textes relus à l'affichage (catalogues chargés après ce script dans le navigateur).
  function roles() { return { receiver: I18N.t("monitoring.role_receiver"), emitter: I18N.t("monitoring.role_emitter") }; }
  function states() {
    return { confirm: I18N.t("monitoring.state_confirm"), active: I18N.t("monitoring.state_active"),
             paused: I18N.t("monitoring.state_paused") };
  }
  function profiles() {
    return {
      essentiel: { label: I18N.t("monitoring.profile_essential"), rig: false, events_min: "erreur" },
      diagnostic: { label: I18N.t("monitoring.profile_diagnostic"), rig: true, events_min: "avertissement" },
    };
  }
  const SEVERITIES = ["info", "avertissement", "erreur", "critique"];
  const HOURS = [1, 2, 4, 24];
  const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";          // Crockford, comme la station (monlink/invite.py)

  function normalizeCode(text) {
    /* Code tapé -> « ABCDE-FGHJK », ou null : casse libre, espaces et tirets ignorés, O = 0, I et L = 1. */
    if (typeof text !== "string" || text.length > 40) return null;
    const code = text.toUpperCase().replace(/[\s-]/g, "").replace(/O/g, "0").replace(/[IL]/g, "1");
    if (code.length !== 10 || [...code].some((c) => !ALPHABET.includes(c))) return null;
    return code.slice(0, 5) + "-" + code.slice(5);
  }

  function profile(choice, freqMode) {
    /* Profil envoyé au module : « essentiel » ou « diagnostic », fréquence et mode à part (masqués par défaut). */
    const all = profiles(), p = all[choice] || all.diagnostic;
    return { rig: p.rig, events_min: p.events_min, freq_mode: !!freqMode };
  }

  function minutes(seconds) { return Math.max(0, Math.floor((Number(seconds) || 0) / 60)); }

  function extra(link) {
    /* Détails d'une liaison, dans les mots de TRX Console (menu 6.5). */
    const out = [];
    if (link.state !== "confirm") {
      out.push(link.last_rx_age === null || link.last_rx_age === undefined ? I18N.t("monitoring.no_news")
               : I18N.t("monitoring.last_news", { min: minutes(link.last_rx_age) }));
    }
    if (link.request) out.push(I18N.t(link.request.snapshot ? "monitoring.report_pending" : "monitoring.assist_pending"));
    if (link.assist_left_s) out.push(I18N.t("monitoring.assist_left", { min: Math.max(1, minutes(link.assist_left_s)) }));
    if (link.paused) out.push(I18N.t("monitoring.paused"));
    if (link.silent) out.push(I18N.t("monitoring.silent"));
    if (link.report_due) out.push(I18N.t("monitoring.report_due"));
    if (link.reports) out.push(I18N.t("monitoring.reports_received", { reports: link.reports }));
    return out;
  }

  function level(link) {
    /* Couleur d'une carte : « warn » si l'opérateur doit agir ou si la station suivie se tait. */
    if (link.state === "confirm" || link.request || link.silent) return "warn";
    if (link.paused) return "dim";
    return "ok";
  }

  function actions(link) {
    /* Boutons d'une liaison, selon son rôle et son état (jamais de commande vers l'autre station). */
    if (link.state === "confirm") return ["fingerprint", "end"];
    if (link.role === "receiver") {
      const list = ["assist", "report"];
      if (link.reports) list.push("download");
      return list.concat(["end"]);
    }
    const list = [];
    if (link.request) list.push("answer");
    if (link.state === "paused") list.push("resume");
    else list.push("send_report", "profile", "pause");
    return list.concat(["end"]);
  }

  function linkView(link) {
    const title = I18N.t("monitoring.link_title", { pseudo: link.pseudo || "?", role: roles()[link.role] || "?",
                                                     state: states()[link.state] || "?" });
    return { peer: link.peer, title: title,
             details: extra(link), level: level(link), actions: actions(link), raw: link };
  }

  function stationLines(link) {
    /* Dernières nouvelles d'une station suivie (station qui aide), comme le choix 2 du menu 6.5. */
    const lines = [], hb = link.last_hb || {}, st = link.last_st || {};
    if (hb.v) {
      lines.push(I18N.t("monitoring.station_line", { version: hb.v, gateway: hb.gateway || "?",
                                                     safe: hb.safe || I18N.t("monitoring.safe_no") }));
    }
    const s = st.system || {};
    if (Object.keys(s).length) {
      const v = (x) => (x === null || x === undefined ? "--" : x);
      lines.push(I18N.t("monitoring.machine_line", { cpu: v(s.cpu), mem: v(s.mem), disk: v(s.disk),
                                                     temp: s.temp === null || s.temp === undefined ? "--" : s.temp + " °C" }));
    }
    const r = st.rig || {};
    if (Object.keys(r).length) {
      const freq = r.freq ? ", " + (r.freq / 1e6).toFixed(3) + " MHz " + (r.mode || "") : "";
      lines.push(I18N.t("monitoring.rig_line", { cat: r.cat ? "OK" : (r.cat_error || "?"), tx: r.tx || "?",
                                                 clients: r.clients || 0, freq: freq.trimEnd() }));
    }
    if (!lines.length) lines.push(I18N.t("monitoring.no_news_received"));
    return lines;
  }

  function eventLine(e) {
    /* Étape 338 : texte reçu (raison du mode sûr…) après le titre, répétitions regroupées par la station. */
    const c = (e && e.content) || {}, count = Number(e && e.count) || 1;
    const when = (t) => String(t || "").slice(0, 16).replace("T", " ");
    return [when(c.ts), c.code || "?", c.gravite || "?", c.titre || c.message || "",
            e && e.text ? "— " + e.text : "",
            count > 1 ? I18N.t("monitoring.repeat", { n: count, first: when(e.first) }) : ""]
      .filter(Boolean).join(" ");
  }

  function status(view) {
    if (!view) return I18N.t("monitoring.reading");
    return [view.pseudo ? I18N.t("monitoring.pseudo", { pseudo: view.pseudo }) : I18N.t("monitoring.no_pseudo"),
            I18N.t(view.registered ? "monitoring.registered" : "monitoring.not_registered"),
            view.problem ? I18N.t("monitoring.problem", { problem: view.problem }) : ""].filter(Boolean).join(" · ");
  }

  function decodeB64url(text) {
    /* base64url sans « = » -> Uint8Array ; null si illisible. */
    if (typeof text !== "string" || !/^[A-Za-z0-9_-]*$/.test(text)) return null;
    const b64 = text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4);
    try {
      if (typeof root.atob === "function") {
        const bin = root.atob(b64), out = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
        return out;
      }
      return new Uint8Array(Buffer.from(b64, "base64"));
    } catch (e) {
      return null;
    }
  }

  function joinParts(parts) {
    /* Morceaux du rapport (base64url) -> octets du zip ; null si un morceau manque ou est illisible. */
    const chunks = [];
    for (const p of parts) {
      const bytes = decodeB64url(p);
      if (!bytes) return null;
      chunks.push(bytes);
    }
    const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
    let at = 0;
    for (const c of chunks) { out.set(c, at); at += c.length; }
    return out;
  }

  const api = { get ROLES() { return roles(); }, get STATES() { return states(); }, SEVERITIES, HOURS,
                get PROFILES() { return profiles(); }, normalizeCode, profile, extra, level, actions, linkView,
                stationLines, eventLine, status, decodeB64url, joinParts };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxMonitoring = api; }
})(typeof window !== "undefined" ? window : globalThis);
