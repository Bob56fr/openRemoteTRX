// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Textes de la page dans la langue de l'opérateur (cahier docs/application-traduction-cahier-des-charges.md).
 *
 * Catalogues : trxstation/i18n/<domaine>.<langue>.json, objets {clé: texte} avec des champs {nom} ; le TRONC COMMUN
 * (domaine « client » : refus, coupures) est lu aussi par la station et copié dans l'application Android ; le domaine
 * « shared » porte les autres textes communs à la page et à l'application (même clé des deux côtés, copié aussi dans
 * l'application ; lot T4) ; le domaine « page » les textes propres à la page. Le français
 * est la référence : une clé absente d'une langue retombe sur le français, une clé absente partout s'affiche telle
 * quelle (jamais d'exception : la page doit toujours s'afficher).
 *
 * Navigateur : catalogues servis par la station (/i18n/<domaine>.<langue>.json, liste fermée), chargés au démarrage
 * (`ready`) ; Node (tests) : lus sur le disque, prêts tout de suite. AUCUN texte ne se lit avant `ready` (la page
 * attend avant d'afficher quoi que ce soit) : une table de textes se relit à l'affichage, jamais au chargement du
 * script.
 *
 * index.html garde le texte français dans l'élément (affiché tel quel si le catalogue manque) et porte sa clé :
 * `data-t="clé"` (contenu, élément sans enfant), `data-t-title`, `data-t-placeholder`, `data-t-aria-label`,
 * `data-t-alt`, `data-t-label` (attributs) ; `apply(élément)` les remplit dans la langue choisie.
 */
(function (root) {
  "use strict";   // i18n-ok

  const LANGS = ["fr", "en", "de", "es"];
  const DOMAINS = ["client", "shared", "page"];
  // Langues PROPOSÉES par la page : une langue n'y entre que lorsque ses trois catalogues sont complets (lot T5 :
  // anglais ; allemand et espagnol au lot T6) — tests/test_i18n_page.py le vérifie.
  const OFFERED = ["fr", "en", "de", "es"];
  const STORE_KEY = "trx.lang";

  const catalogs = {};                  // langue -> {clé: texte}
  let current = "fr";
  let loaded = false;

  function chooseLang(stored, wanted, offered) {
    /* Langue retenue : celle enregistrée par l'opérateur, sinon la première du navigateur proposée, sinon l'anglais
     * (décision de l'utilisateur du 2026-11-20), sinon le français. */
    const ok = (l) => typeof l === "string" && offered.indexOf(l) >= 0;
    if (ok(stored)) return stored;
    for (const raw of wanted || []) {
      const l = typeof raw === "string" ? raw.toLowerCase().split(/[-_]/)[0] : "";
      if (ok(l)) return l;
    }
    return ok("en") ? "en" : "fr";
  }

  function merge(lang, data) {
    if (!data || typeof data !== "object") return;
    const into = catalogs[lang] || (catalogs[lang] = {});
    for (const [k, v] of Object.entries(data)) if (typeof v === "string") into[k] = v;
  }

  function fill(text, fields) {
    if (!fields) return text;
    return text.replace(/\{([a-z_]+)\}/g, (all, name) => (name in fields && fields[name] !== undefined && fields[name] !== null ? String(fields[name]) : all));
  }

  // Pseudo-langue d'essai (cahier § 7, lot T6) : page ouverte avec « ?lang=xx » : le français aux lettres accentuées,
  // allongé de 40 % et entre crochets, pour voir les débordements et les textes qui ne passent pas par t().
  const PSEUDO = "xx";
  const PLAIN = "AaCcEeIiNnOoUuYy", ACCENTED = "ÅåÇçÉéÎîÑñÖöÛûÝý";   // i18n-ok : lettres de la pseudo-langue
  function pseudo(text) {
    const body = text.split(/(\{[a-z_]+\})/).map((part, i) => (i % 2 ? part
      : part.replace(/[AaCcEeIiNnOoUuYy]/g, (c) => ACCENTED[PLAIN.indexOf(c)]))).join("");
    return "[" + body + "·".repeat(Math.ceil(text.length * 0.4)) + "]";
  }

  function lookup(key) {
    if (current === PSEUDO) {
      const fr = catalogs.fr && catalogs.fr[key];
      return typeof fr === "string" ? pseudo(fr) : null;
    }
    const own = catalogs[current] && catalogs[current][key];
    if (typeof own === "string") return own;
    const fr = catalogs.fr && catalogs.fr[key];
    return typeof fr === "string" ? fr : null;
  }

  function t(key, fields) { const text = lookup(key); return fill(text === null ? key : text, fields); }
  function has(key) { return lookup(key) !== null; }
  function plural(key, n, fields) {
    /* Clés `<clé>_one` / `<clé>_other` ; {n} rempli d'office. Français : 0 et 1 au singulier ; autres langues : ±1. */
    const one = current === "fr" || current === PSEUDO ? Math.abs(n) < 2 : Math.abs(n) === 1;
    return t(key + (one ? "_one" : "_other"), Object.assign({ n: n }, fields || {}));
  }

  const ATTRS = ["title", "placeholder", "aria-label", "alt", "label"];

  function apply(el) {
    /* Remplit les textes marqués de `el` et de ses descendants (index.html, fragments clonés d'un modèle). */
    if (!el || typeof el.querySelectorAll !== "function") return;
    const nodes = [el, ...el.querySelectorAll("[data-t],[data-t-title],[data-t-placeholder],[data-t-aria-label],[data-t-alt],[data-t-label]")];
    for (const node of nodes) {
      if (!node.getAttribute) continue;
      const key = node.getAttribute("data-t");
      if (key && has(key)) node.textContent = t(key);
      for (const attr of ATTRS) {
        const k = node.getAttribute("data-t-" + attr);
        if (k && has(k)) node.setAttribute(attr, t(k));
      }
    }
    if (el.documentElement && el.documentElement.setAttribute) el.documentElement.setAttribute("lang", current);
  }

  function choose(lang) {
    /* Choix de l'opérateur (null = langue du navigateur), gardé par le navigateur ; la page se recharge ensuite
     * (seulement hors connexion : ui.js). */
    try {
      if (root.localStorage) {
        if (lang && OFFERED.indexOf(lang) >= 0) root.localStorage.setItem(STORE_KEY, lang);
        else root.localStorage.removeItem(STORE_KEY);
      }
    } catch (e) { /* navigateur sans stockage : choix perdu au rechargement */ }
  }

  function stored() {
    try { return (root.localStorage && root.localStorage.getItem(STORE_KEY)) || null; } catch (e) { return null; }
  }

  function use(lang, data) {
    /* Tests : remplace les catalogues d'une langue et la rend courante. */
    catalogs[lang] = {}; merge(lang, data); current = lang; loaded = true;
  }

  let ready;
  if (typeof module !== "undefined" && module.exports && typeof require === "function") {
    const fs = require("node:fs"), path = require("node:path");
    const folder = path.join(__dirname, "..", "..", "..", "i18n");
    for (const lang of LANGS) for (const domain of DOMAINS) {
      try { merge(lang, JSON.parse(fs.readFileSync(path.join(folder, domain + "." + lang + ".json"), "utf-8"))); } catch (e) { /* langue absente */ }
    }
    loaded = true;
    ready = Promise.resolve();
  } else {
    let stored = null;
    try { stored = root.localStorage && root.localStorage.getItem(STORE_KEY); } catch (e) { stored = null; }
    const nav = root.navigator ? (root.navigator.languages || [root.navigator.language]) : [];
    current = chooseLang(stored, nav, OFFERED);
    try { if (new URLSearchParams(root.location.search).get("lang") === PSEUDO) current = PSEUDO; } catch (e) { /* sans URL */ }
    const wanted = current === "fr" || current === PSEUDO ? ["fr"] : ["fr", current];
    const fetchOne = (lang, domain) => root.fetch("i18n/" + domain + "." + lang + ".json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null)).then((data) => merge(lang, data)).catch(() => {});
    ready = typeof root.fetch === "function"
      ? Promise.all(wanted.flatMap((lang) => DOMAINS.map((domain) => fetchOne(lang, domain)))).then(() => { loaded = true; })
      : Promise.resolve().then(() => { loaded = true; });
  }

  const api = { LANGS, OFFERED, PSEUDO, chooseLang, t, has, plural, pseudo, use, apply, choose, stored, ready,
                get lang() { return current; }, get loaded() { return loaded; } };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxI18n = api; }
})(typeof window !== "undefined" ? window : globalThis);
