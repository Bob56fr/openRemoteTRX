// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Formats de la langue CHOISIE (i18n.js, cahier de la traduction § 3.5, lot T7) : `node tests/js/i18n_test.js`
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STATIC = path.join(__dirname, "../../trxstation/gateway/api/static");
const I18N = require(path.join(STATIC, "i18n.js"));
const client = require(path.join(STATIC, "client.js"));
const swr = require(path.join(STATIC, "swr.js"));
const hfscope = require(path.join(STATIC, "hfscope.js"));
const FOLDER = path.join(__dirname, "../../trxstation/i18n");

function catalog(lang) {
  const out = {};
  for (const domain of ["client", "shared", "page"]) {
    try { Object.assign(out, JSON.parse(fs.readFileSync(path.join(FOLDER, domain + "." + lang + ".json"), "utf-8"))); } catch (e) { /* absent */ }
  }
  return out;
}
const CATALOGS = Object.fromEntries(I18N.LANGS.map((l) => [l, catalog(l)]));

function inLang(lang, fn) {
  I18N.use(lang, CATALOGS[lang]);
  try { return fn(); } finally { I18N.use("fr", CATALOGS.fr); }
}

let passed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("decimal : virgule en fr / de / es, point en en", () => {
  assert.equal(inLang("fr", () => I18N.decimal(3.456, 2)), "3,46");
  assert.equal(inLang("en", () => I18N.decimal(3.456, 2)), "3.46");
  assert.equal(inLang("de", () => I18N.decimal(3.456, 2)), "3,46");
  assert.equal(inLang("es", () => I18N.decimal(3.456, 2)), "3,46");
  assert.equal(inLang("en", () => I18N.decimal(-2.5)), "-2.5");
  assert.equal(inLang("de", () => I18N.decimal(-2.5)), "-2,5");
  assert.equal(inLang("de", () => I18N.decimal(6)), "6");
  assert.equal(inLang("fr", () => I18N.decimal("4.4")), "4,4");
});

test("textes affichés : TOS, dB, kHz suivent la langue", () => {
  assert.equal(swr.swrText(1.35), "1,35");
  assert.equal(inLang("en", () => swr.swrText(1.35)), "1.35");
  assert.equal(inLang("de", () => hfscope.refLabel(2.5)), "REF +2,5");
  assert.equal(inLang("en", () => hfscope.refLabel(2.5)), "REF +2.5");
});

test("fréquences au format radio : inchangées dans toutes les langues", () => {
  for (const lang of I18N.LANGS) inLang(lang, () => assert.equal(client.formatFrequency(14074000), "14 074 000 Hz"));
});

test("dates : locale de la langue choisie, jamais celle du navigateur", () => {
  const at = Date.UTC(2026, 10, 20, 14, 3, 5);
  assert.equal(inLang("fr", () => I18N.locale), "fr-FR");
  assert.equal(inLang("en", () => I18N.locale), "en-GB");
  assert.equal(inLang("de", () => I18N.locale), "de-DE");
  assert.equal(inLang("es", () => I18N.locale), "es-ES");
  assert.equal(inLang(I18N.PSEUDO, () => I18N.locale), "fr-FR");
  for (const [lang, loc] of [["fr", "fr-FR"], ["en", "en-GB"], ["de", "de-DE"], ["es", "es-ES"]]) {
    assert.equal(inLang(lang, () => I18N.dateTime(at)), new Date(at).toLocaleString(loc));
    assert.equal(inLang(lang, () => I18N.time(at)), new Date(at).toLocaleTimeString(loc));
  }
  // l'allemand écrit la date avec des points, le français avec des barres
  assert.match(inLang("de", () => I18N.dateTime(at)), /\d+\.\d+\.2026/);
  assert.match(inLang("fr", () => I18N.dateTime(at)), /\d+\/\d+\/2026/);
});

for (const [name, fn] of tests) {
  try { fn(); passed += 1; } catch (e) { console.error("ÉCHEC : " + name + "\n" + (e && e.stack)); process.exitCode = 1; }
}
console.log(passed + "/" + tests.length + " tests réussis");
