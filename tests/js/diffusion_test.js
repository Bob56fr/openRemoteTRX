// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Diffusion en direct de la page (diffusion.js) : `node tests/js/diffusion_test.js`
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const dfx = require(path.join(__dirname, "../../trxstation/gateway/api/static/diffusion.js"));
const MESSAGES = JSON.parse(fs.readFileSync(path.join(__dirname, "../protocol/messages.json"), "utf-8"));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("indicateur : absent hors diffusion, toujours là pendant (auditeurs, temps restant)", () => {
  assert.equal(dfx.indicator(null), null);
  assert.equal(dfx.indicator({ active: false }), null);
  const ind = dfx.indicator(MESSAGES.state_diffusion.diffusion);
  assert.equal(ind.text, "DIFFUSION · 🎧 2 · 42 min");
  assert.equal(ind.level, "live");
  assert.match(ind.title, /privée/);
  assert.equal(dfx.indicator({ active: true, phase: "nouvel_essai", remaining_s: null }).level, "retry");
  assert.equal(dfx.indicator({ active: true, phase: "en_direct", remaining_s: null }).text, "DIFFUSION · sans limite");
});

test("temps restant lisible", () => {
  assert.equal(dfx.remaining(null), "sans limite");
  assert.equal(dfx.remaining(59), "1 min");
  assert.equal(dfx.remaining(3600), "1 h 00");
  assert.equal(dfx.remaining(3600 * 23 + 300), "23 h 05");
});

test("état de la rubrique : cause du dernier arrêt, voix émise dite clairement", () => {
  assert.match(dfx.status({ enabled: true, active: false, last_stop: { cause: "overload" } }), /surchargée/);
  assert.match(dfx.status({ enabled: false }), /hors service/);
  assert.match(dfx.status(MESSAGES.state_diffusion.diffusion), /voix émise NON diffusée/);
  assert.match(dfx.status(null), /indisponible/);
});

test("formulaire : privée, 1 h, pseudo seul et voix coupée par défaut ; limites de la station", () => {
  assert.deepEqual(dfx.startArgs({}).args, { access: "prive", hours: 1, voice: false, meta: ["pseudo"] });
  const a = dfx.startArgs({ access: "public", hours: "none", voice: true, meta: ["pseudo", "frequence_hz", "adresse_ip"],
                            pseudo: " BOB ", message: "" }).args;
  assert.deepEqual(a, { access: "public", hours: null, voice: true, meta: ["pseudo", "frequence_hz"], pseudo: "BOB" });
  assert.ok(dfx.startArgs({ hours: "25" }).error);
  assert.ok(dfx.startArgs({ hours: "0" }).error);
  assert.ok(dfx.startArgs({ pseudo: "x".repeat(33) }).error);
  assert.ok(dfx.startArgs({ message: "a\u0007b" }).error);
  assert.deepEqual(dfx.META.map(([k]) => k), ["pseudo", "indicatif", "frequence_hz", "mode", "bande", "tx", "s_metre", "message"]);
});

test("mot de passe des auditeurs : mêmes règles que la station", () => {
  assert.ok(dfx.passwordOk("Abcdef234567"));
  assert.ok(!dfx.passwordOk("court1"));
  assert.ok(!dfx.passwordOk("avec espace 12"));
  assert.ok(!JSON.stringify(MESSAGES.state_diffusion).includes("password"));   // jamais dans state
});

test("avertissement du cahier § 1.1", () => {
  assert.match(dfx.WARNING, /responsabilité/);
  assert.match(dfx.WARNING, /hors des bandes autorisées/);
  assert.match(dfx.status({ active: true, access: "public", phase: "en_direct", remaining_s: 60 }), /silence hors des bandes/);
  assert.match(dfx.status({ active: true, outside_bands: true, phase: "en_direct", remaining_s: 60 }), /hors bandes diffusé/);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); } catch (e) { failed++; console.log("ÉCHEC " + name + "\n" + e.stack); }
}
process.exit(failed ? 1 : 0);
