// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, langues (FR, EN ; lot PQ6). Textes du code : T("texte français {var}", { var }) ; le texte
   français EST la clé, sa traduction anglaise est dans EN (un test vérifie qu'il n'en manque aucune). Parties fixes de la
   page : attribut data-t="clé", traduction dans EN_PAGE. Langue : ?lang=fr|en dans l'adresse, sinon celle du
   navigateur ; rien n'est retenu dans le navigateur. */
(function (root) {
  "use strict";

  function pick() {
    try {
      const q = new URLSearchParams(root.location && root.location.search || "").get("lang");
      if (q === "fr" || q === "en") return q;
      const nav = (root.navigator && root.navigator.language) || "fr";
      return /^fr\b/i.test(nav) ? "fr" : "en";
    } catch (e) { return "fr"; }
  }
  const lang = (typeof window !== "undefined") ? pick() : "fr";

  const EN = {};        // rempli plus bas (textes du code)
  const EN_PAGE = {};   // rempli plus bas (parties fixes de la page, en HTML)

  function fill(text, vars) { return vars ? String(text).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : text; }
  function T(fr, vars) { return fill(lang === "en" && EN[fr] != null ? EN[fr] : fr, vars); }
  // Parties fixes : innerHTML remplacé par la traduction (texte du projet, jamais une donnée venue de l'extérieur).
  function apply(doc) {
    if (lang !== "en" || !doc || !doc.querySelectorAll) return;
    doc.documentElement.lang = "en";
    for (const el of doc.querySelectorAll("[data-t]")) { const v = EN_PAGE[el.getAttribute("data-t")]; if (v != null) el.innerHTML = v; }
  }

  const api = { lang, T, apply, EN, EN_PAGE, fill };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtI18n = api;
})(typeof window !== "undefined" ? window : globalThis);
