// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, marques et modèles (docs/prequalif-web-cahier-des-charges.md § 6). `verifie` = passé sur un
   VRAI poste avec cette page ; tout le reste vient de la documentation et reste « non vérifié » dans le rapport.
   `hamlib` n'est renseigné que pour les numéros relevés sur un vrai rigctld (liste complète au lot PQ4). */
(function (root) {
  "use strict";

  const BRANDS = [
    { id: "icom", name: "Icom", family: "civ", ready: true },
    { id: "yaesu", name: "Yaesu", family: "ascii", ready: false },
    { id: "kenwood", name: "Kenwood", family: "ascii", ready: false },
    { id: "elecraft", name: "Elecraft", family: "ascii", ready: false },
    { id: "xiegu", name: "Xiegu", family: "civ", ready: false },
    { id: "other", name: "Autre", family: null, ready: false },
  ];

  // addr : adresse CI-V par défaut ; maxW : puissance maximale ; bauds : vitesses essayées dans cet ordre.
  const ICOM = [
    { id: "ic7300mk2", name: "IC-7300MK2", addr: 0xB6, maxW: 100, verifie: false, hamlib: 3094, piloteIcom: true },
    { id: "ic7300", name: "IC-7300", addr: 0x94, maxW: 100, verifie: false },
    { id: "ic705", name: "IC-705", addr: 0xA4, maxW: 10, verifie: false, hamlib: 3085, piloteIcom: true },
    { id: "ic7610", name: "IC-7610", addr: 0x98, maxW: 100, verifie: false },
    { id: "ic9700", name: "IC-9700", addr: 0xA2, maxW: 100, verifie: false },
    { id: "ic905", name: "IC-905", addr: 0xAC, maxW: 10, verifie: false, piloteIcom: true },
    { id: "ic7100", name: "IC-7100", addr: 0x88, maxW: 100, verifie: false },
    { id: "ic7851", name: "IC-7851", addr: 0x8E, maxW: 200, verifie: false },
    { id: "ic7600", name: "IC-7600", addr: 0x7A, maxW: 100, verifie: false },
    { id: "ic7410", name: "IC-7410", addr: 0x80, maxW: 100, verifie: false },
    { id: "ic7200", name: "IC-7200", addr: 0x76, maxW: 100, verifie: false },
  ];
  const ICOM_BAUDS = [115200, 19200, 9600, 38400, 57600, 4800];

  function modelsOf(brand) { return brand === "icom" ? ICOM : []; }
  function byAddr(addr) { return ICOM.find(m => m.addr === addr) || null; }

  const api = { BRANDS, ICOM, ICOM_BAUDS, modelsOf, byAddr };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AtModels = api;
})(typeof window !== "undefined" ? window : globalThis);
