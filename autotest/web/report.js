// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, rapport (docs/prequalif-web-cahier-des-charges.md § 9) : ANONYME (ni nom de machine, ni
   adresse, ni numéro de série ; noms des cartes son nettoyés), trace brute jointe pour que le service du projet
   recalcule lui-même les résultats (§ 9.2), empreinte SHA-256 de la trace (rapport rejoué repéré). */
(function (root) {
  "use strict";

  const VERSION = "0.3.0";
  const SCHEMA = "openremotetrx-autotest/1";
  const STATUS_TEXT = { ok: "réussi", avert: "à vérifier", echec: "échec", na: "non disponible", saute: "sauté" };

  // « 2- USB Audio Device (08bb:2902) » -> « USB Audio Device »
  function cleanLabel(label) {
    if (!label) return null;
    return String(label).replace(/^\s*\d+\s*-\s*/, "").replace(/\s*\([0-9a-f]{4}:[0-9a-f]{4}\)\s*$/i, "").trim() || null;
  }

  function hexId(n) { return n == null ? null : n.toString(16).padStart(4, "0"); }

  async function sha256(text) {
    const c = (typeof crypto !== "undefined" && crypto.subtle) ? crypto : null;
    if (!c) return null;
    const buf = await c.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, "0")).join("");
  }

  async function build({ brand, model, chosenModel, detected, usb, audio, run, trace, startedAt, platform }) {
    const traceText = JSON.stringify(trace || []);
    return {
      schema: SCHEMA,
      outil: { nom: "openRemoteTRX-Autotest", version: VERSION, mode: "A" },
      niveau: "prequalification_navigateur",
      date: startedAt || new Date().toISOString(),
      systeme: platform || null,
      poste: {
        marque: brand ? brand.name : null,
        modele_choisi: chosenModel ? chosenModel.name : null,
        modele_reconnu: model ? model.name : null,
        modele_verifie: model ? !!model.verifie : false,
        hamlib_model: model && model.hamlib || null,
        adresse_civ: detected && detected.addr != null ? detected.addr.toString(16).toUpperCase().padStart(2, "0") : null,
        vitesse: detected ? detected.baud : null,
        usb: usb ? { vid: hexId(usb.usbVendorId), pid: hexId(usb.usbProductId) } : null,
      },
      carte_son: audio ? { entree: cleanLabel(audio.inputLabel), sortie: cleanLabel(audio.outputLabel) } : null,
      essais: (run && run.results || []).map(r => ({ code: r.code, statut: r.status, texte: r.text, valeurs: r.values })),
      arret: run && run.stop || null,
      mesures_emission: (run && run.samples || []).map(s => ({ essai: s.label, po: s.raw.po, swr: s.raw.swr, alc: s.raw.alc })),
      trace: trace || [],
      empreinte_trace: await sha256(traceText),
    };
  }

  // Résumé lisible : une ligne par essai, couleur par statut.
  function summary(report) {
    const n = { ok: 0, avert: 0, echec: 0, na: 0, saute: 0 };
    for (const e of report.essais) n[e.statut] = (n[e.statut] || 0) + 1;
    const verdict = n.echec ? "echec" : n.avert ? "avert" : "ok";
    return { verdict, counts: n, lines: report.essais.map(e => ({ code: e.code, statut: e.statut, label: STATUS_TEXT[e.statut] || e.statut, texte: e.texte })) };
  }

  function fileName(report) {
    const m = (report.poste.modele_reconnu || report.poste.modele_choisi || "poste").replace(/[^A-Za-z0-9-]+/g, "");
    return `autotest-${m}-${report.date.slice(0, 16).replace(/[-:T]/g, "")}.json`;
  }

  const api = { VERSION, SCHEMA, STATUS_TEXT, cleanLabel, sha256, build, summary, fileName };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtReport = api;
})(typeof window !== "undefined" ? window : globalThis);
