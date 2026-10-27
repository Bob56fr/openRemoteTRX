// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Logique des mises en page côté navigateur (layout.js), sans DOM : `node tests/js/layout_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const L = require(path.join(__dirname, "../../trxstation/gateway/api/static/layout.js"));
const FACTORY = require("./factory_profile.json");
const CASES = require("./layout_cases.json");                         // mêmes cas que tests/test_layout.py (cascade Python)

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const copy = (o) => JSON.parse(JSON.stringify(o));
const variantsOf = (list) => {
  const variants = {};
  for (const item of list) { const [device, orientation] = item.split("/"); (variants[device] = variants[device] || {})[orientation] = { widgets: [] }; }
  return variants;
};

test("cascade : mêmes résultats que la station pour chaque cas partagé", () => {
  for (const c of CASES) {
    const got = L.selectVariant(variantsOf(c.variants), c.device, c.orientation, c.forced);
    assert.deepEqual(got && [got.device, got.orientation, got.display], c.expect, JSON.stringify(c));
  }
  assert.throws(() => L.selectVariant({}, "watch", "portrait"));
});

test("catégorie d'appareil d'après l'écran", () => {
  assert.equal(L.detectDevice(412, 860, true), "phone");
  assert.equal(L.detectDevice(860, 412, true), "phone");                // un téléphone tourné reste un téléphone
  assert.equal(L.detectDevice(800, 1280, true), "tablet");
  assert.equal(L.detectDevice(1280, 800, false), "tablet");
  assert.equal(L.detectDevice(1920, 1080, false), "desktop");
});

test("profil d'usine : chaque widget trouve son élément, sécurité complète", () => {
  const plan = L.buildPlan(FACTORY, "phone", "portrait", null);
  assert.equal(plan.safe, true); assert.deepEqual(plan.unsupported, []); assert.equal(plan.cols, 4);
  assert.deepEqual(new Set(plan.blocks), new Set(L.ALL_BLOCKS));         // la page actuelle est entièrement décrite
  assert.equal(plan.bottom.length, 1); assert.deepEqual(plan.bottom[0].sections.map((s) => s.title), ["Accord", "Mémoires"]);
  const layers = plan.top.find((n) => n.kind === "layers");
  assert.deepEqual(layers.groups[0].map((l) => l.items.map((n) => n.block)), [["blk-po", "blk-swr", "blk-alc"], ["waterfall"]]);
  assert.equal(L.buildPlan(FACTORY, "desktop", "landscape", null).maxWidth, "44rem");     // variante smartphone centrée, jamais étirée
});

test("liaison des widgets : fonctions connues, cibles, apparences", () => {
  assert.equal(L.blockFor({ type: "switch", bind: "NR" }), "ctl-nr");
  assert.equal(L.blockFor({ type: "switch", bind: "NR", target: "main" }), "ctl-nr");
  assert.equal(L.blockFor({ type: "switch", bind: "NR", target: "sub" }), null);          // un seul récepteur affiché pour l'instant
  assert.equal(L.blockFor({ type: "switch", bind: "DUAL_WATCH" }), null);
  assert.equal(L.blockFor({ type: "frequency", appearance: "field" }), "blk-freqinput");
  assert.equal(L.blockFor({ type: "mode", appearance: "select" }), "blk-modeset");
  assert.equal(L.blockFor({ type: "scope" }), null);
});

test("sécurité : sans PTT, état, liaison ou case d'émission au premier niveau, écran de sécurité", () => {
  for (const id of ["ptt", "tx", "link", "armed"]) {
    const profile = copy(FACTORY);
    const widgets = profile.variants.phone.portrait.widgets;
    widgets.splice(widgets.findIndex((w) => w.id === id), 1);
    const plan = L.buildPlan(profile, "phone", "portrait", null);
    assert.equal(plan.safe, false, id); assert.equal(plan.reason, "locked_missing", id);
  }
  const hidden = copy(FACTORY);
  hidden.variants.phone.portrait.widgets.find((w) => w.id === "ptt").hidden = true;
  assert.equal(L.buildPlan(hidden, "phone", "portrait", null).safe, false);
  const rotate = { variants: { phone: { landscape: copy(FACTORY.variants.phone.portrait) } } };
  const plan = L.buildPlan(rotate, "phone", "portrait", null);
  assert.equal(plan.reason, "rotate"); assert.match(L.safeText(plan), /Tourne l'appareil/);
  assert.equal(L.buildPlan({ variants: {} }, "phone", "portrait", null).reason, "no_variant");
});

test("un même élément ne s'affiche qu'une fois ; masqué = absent", () => {
  const profile = copy(FACTORY);
  const widgets = profile.variants.phone.portrait.widgets;
  widgets.push({ id: "nr2", type: "switch", x: 1, y: 7, w: 1, h: 1, bind: "NR" });
  widgets.find((w) => w.id === "nb").hidden = true;
  const plan = L.buildPlan(profile, "phone", "portrait", null);
  assert.deepEqual(plan.unsupported, ["nr2"]); assert.ok(!plan.blocks.includes("ctl-nb")); assert.equal(plan.safe, true);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 5).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests des mises en page réussis");
process.exit(failed ? 1 : 0);
