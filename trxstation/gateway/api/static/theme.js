// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Thème de couleurs : chargé dans <head>, AVANT la feuille de style, pour appliquer le thème mémorisé avant le
 * premier affichage (pas d'éclair de couleurs). Un thème = l'attribut data-theme de <html> ; ses couleurs sont dans
 * client.css (générées depuis docs/themes.json). Un nom inconnu ne correspond à aucun bloc : le thème par défaut
 * s'applique de lui-même. Mémorisation sur l'appareil seulement (localStorage), jamais indispensable. */
(function (root) {
  "use strict";
  const KEY = "trx.theme";
  const DEFAULT = "defaut";
  const valid = (id) => typeof id === "string" && /^[a-z][a-z0-9_-]{0,31}$/.test(id);

  function stored() {
    try { const id = root.localStorage.getItem(KEY); return valid(id) ? id : DEFAULT; } catch (e) { return DEFAULT; }
  }

  function apply(id) {
    const theme = valid(id) ? id : DEFAULT;
    try { root.document.documentElement.setAttribute("data-theme", theme); } catch (e) { /* pas de document : tests */ }
    return theme;
  }

  function choose(id) {           // choix de l'utilisateur : appliqué tout de suite et mémorisé
    const theme = apply(id);
    try { root.localStorage.setItem(KEY, theme); } catch (e) { /* stockage indisponible : choix non mémorisé */ }
    return theme;
  }

  const api = { KEY, DEFAULT, valid, stored, apply, choose };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxTheme = api; apply(stored()); }
})(typeof window !== "undefined" ? window : globalThis);
