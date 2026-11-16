// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Monitoring inter-stations dans la page (docs/cdc-monitoring.md § 17, lot R5 ; protocole : docs/protocole.md § 19) :
   calculs purs, testés sous Node (tests/js/monitoring_test.js), sans DOM. Le dessin est dans ui.js (rubrique
   « Monitoring »). Mêmes actions que le menu 5.5 de TRX Console ; le module « monlink » n'agit jamais sur le poste et
   la station qui aide ne peut que lire et DEMANDER. */
(function (root) {
  "use strict";

  const ROLES = { receiver: "vous aidez cette station", emitter: "cette station vous aide" };
  const STATES = { confirm: "empreinte à comparer", active: "active", paused: "en pause" };
  const SEVERITIES = ["info", "avertissement", "erreur", "critique"];
  const HOURS = [1, 2, 4, 24];
  const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";          // Crockford, comme la station (monlink/invite.py)
  const PROFILES = {
    essentiel: { label: "Essentiel : santé de la machine et erreurs", rig: false, events_min: "erreur" },
    diagnostic: { label: "Diagnostic : en plus, état du poste et avertissements (conseillé)", rig: true,
                  events_min: "avertissement" },
  };

  function normalizeCode(text) {
    /* Code tapé -> « ABCDE-FGHJK », ou null : casse libre, espaces et tirets ignorés, O = 0, I et L = 1. */
    if (typeof text !== "string" || text.length > 40) return null;
    const code = text.toUpperCase().replace(/[\s-]/g, "").replace(/O/g, "0").replace(/[IL]/g, "1");
    if (code.length !== 10 || [...code].some((c) => !ALPHABET.includes(c))) return null;
    return code.slice(0, 5) + "-" + code.slice(5);
  }

  function profile(choice, freqMode) {
    /* Profil envoyé au module : « essentiel » ou « diagnostic », fréquence et mode à part (masqués par défaut). */
    const p = PROFILES[choice] || PROFILES.diagnostic;
    return { rig: p.rig, events_min: p.events_min, freq_mode: !!freqMode };
  }

  function minutes(seconds) { return Math.max(0, Math.floor((Number(seconds) || 0) / 60)); }

  function extra(link) {
    /* Détails d'une liaison, dans les mots de TRX Console (menu 5.5). */
    const out = [];
    if (link.state !== "confirm") {
      out.push(link.last_rx_age === null || link.last_rx_age === undefined ? "aucune nouvelle encore"
               : "dernières nouvelles il y a " + minutes(link.last_rx_age) + " min");
    }
    if (link.request) out.push(link.request.snapshot ? "DEMANDE DE RAPPORT en attente" : "DEMANDE D'ASSISTANCE en attente");
    if (link.assist_left_s) out.push("assistance encore " + Math.max(1, minutes(link.assist_left_s)) + " min");
    if (link.paused) out.push("en pause");
    if (link.silent) out.push("SANS NOUVELLES (alerte envoyée)");
    if (link.report_due) out.push("rapport de dépannage en préparation");
    if (link.reports) out.push(link.reports + " rapport(s) reçu(s)");
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
    return { peer: link.peer, title: (link.pseudo || "?") + " : " + (ROLES[link.role] || "?") + ", " + (STATES[link.state] || "?"),
             details: extra(link), level: level(link), actions: actions(link), raw: link };
  }

  function stationLines(link) {
    /* Dernières nouvelles d'une station suivie (station qui aide), comme le choix 2 du menu 5.5. */
    const lines = [], hb = link.last_hb || {}, st = link.last_st || {};
    if (hb.v) lines.push("Station : version " + hb.v + ", passerelle " + (hb.gateway || "?") + ", mode sûr : " + (hb.safe || "non"));
    const s = st.system || {};
    if (Object.keys(s).length) {
      const v = (x) => (x === null || x === undefined ? "--" : x);
      lines.push("Machine : processeur " + v(s.cpu) + " %, mémoire " + v(s.mem) + " %, disque " + v(s.disk) + " %, température "
                 + (s.temp === null || s.temp === undefined ? "--" : s.temp + " °C"));
    }
    const r = st.rig || {};
    if (Object.keys(r).length) {
      const freq = r.freq ? ", " + (r.freq / 1e6).toFixed(3) + " MHz " + (r.mode || "") : "";
      lines.push("Poste : CAT " + (r.cat ? "OK" : (r.cat_error || "?")) + ", émission " + (r.tx || "?") + ", "
                 + (r.clients || 0) + " connexion(s)" + freq.trimEnd());
    }
    if (!lines.length) lines.push("Aucune nouvelle reçue pour l'instant.");
    return lines;
  }

  function eventLine(e) {
    const c = (e && e.content) || {};
    return [String(c.ts || "").slice(0, 16).replace("T", " "), c.code || "?", c.gravite || "?", c.titre || c.message || ""]
      .filter(Boolean).join(" ");
  }

  function status(view) {
    if (!view) return "Lecture…";
    return [view.pseudo ? "Pseudo " + view.pseudo : "Pas encore de pseudo (ci-dessous)",
            view.registered ? "station enregistrée auprès du relais" : "pas encore enregistrée auprès du relais",
            view.problem ? "problème : " + view.problem : ""].filter(Boolean).join(" · ");
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

  const api = { ROLES, STATES, SEVERITIES, HOURS, PROFILES, normalizeCode, profile, extra, level, actions, linkView,
                stationLines, eventLine, status, decodeB64url, joinParts };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxMonitoring = api; }
})(typeof window !== "undefined" ? window : globalThis);
