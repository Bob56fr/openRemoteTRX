// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Monitoring inter-stations de la page (monitoring.js) : `node tests/js/monitoring_test.js`
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const mx = require(path.join(__dirname, "../../trxstation/gateway/api/static/monitoring.js"));
const VECTORS = JSON.parse(fs.readFileSync(path.join(__dirname, "../protocol/monlink_vectors.json"), "utf-8"));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("code tapé : même tolérance que la station (vecteurs partagés)", () => {
  const code = VECTORS.invite.code;
  for (const typed of VECTORS.invite.typed_variants) assert.equal(mx.normalizeCode(typed), code.slice(0, 5) + "-" + code.slice(5));
  assert.equal(mx.normalizeCode("o1il0-abcde"), "01110-ABCDE");
  for (const bad of ["ABCDE-FGHJ", "ABCDE-FGHJKM", "ABCDE-FGHJU", 12345, null]) assert.equal(mx.normalizeCode(bad), null);
});

test("profil : diagnostic par défaut, fréquence et mode masqués sauf demande", () => {
  assert.deepEqual(mx.profile("diagnostic", false), { rig: true, events_min: "avertissement", freq_mode: false });
  assert.deepEqual(mx.profile("essentiel", true), { rig: false, events_min: "erreur", freq_mode: true });
  assert.deepEqual(mx.profile("nimporte"), { rig: true, events_min: "avertissement", freq_mode: false });
});

test("actions d'une liaison selon le rôle et l'état ; jamais de commande vers l'autre station", () => {
  assert.deepEqual(mx.actions({ role: "receiver", state: "confirm" }), ["fingerprint", "end"]);
  assert.deepEqual(mx.actions({ role: "receiver", state: "active" }), ["assist", "report", "end"]);
  assert.deepEqual(mx.actions({ role: "receiver", state: "active", reports: 2 }), ["assist", "report", "download", "end"]);
  assert.deepEqual(mx.actions({ role: "emitter", state: "active", request: { assist: 3600 } }),
                   ["answer", "send_report", "profile", "pause", "end"]);
  assert.deepEqual(mx.actions({ role: "emitter", state: "paused" }), ["resume", "end"]);
  const all = new Set([].concat(...[{ role: "receiver", state: "active", reports: 1 }, { role: "emitter", state: "active", request: {} }]
    .map(mx.actions)));
  for (const forbidden of ["ptt", "toggle", "set_frequency", "restart", "shell"]) assert.ok(!all.has(forbidden));
});

test("carte d'une liaison : textes du menu 6.5, couleur « à voir » si l'opérateur doit agir", () => {
  const v = mx.linkView({ peer: "a", pseudo: "F4XYZ", role: "receiver", state: "active", last_rx_age: 125, silent: true, reports: 1 });
  assert.equal(v.title, "F4XYZ : vous aidez cette station, active");
  assert.deepEqual(v.details, ["dernières nouvelles il y a 2 min", "SANS NOUVELLES (alerte envoyée)", "1 rapport(s) reçu(s)"]);
  assert.equal(v.level, "warn");
  assert.equal(mx.level({ state: "active" }), "ok");
  assert.equal(mx.level({ state: "active", paused: true }), "dim");
  assert.ok(mx.extra({ state: "active", request: { snapshot: true } }).includes("DEMANDE DE RAPPORT en attente"));
});

test("dernières nouvelles et événements d'une station suivie", () => {
  const lines = mx.stationLines({ last_hb: { v: "0.164.0", gateway: "ok", safe: null },
                                  last_st: { system: { cpu: 7, mem: 30, disk: 20, temp: null }, rig: { cat: true, tx: "RX", clients: 1 } } });
  assert.deepEqual(lines, ["Station : version 0.164.0, passerelle ok, mode sûr : non",
                           "Machine : processeur 7 %, mémoire 30 %, disque 20 %, température --",
                           "Poste : CAT OK, émission RX, 1 connexion(s)"]);
  assert.deepEqual(mx.stationLines({}), ["Aucune nouvelle reçue pour l'instant."]);
  assert.equal(mx.eventLine({ content: { ts: "2026-11-21T10:00:00.000Z", code: "ORT-2104", gravite: "erreur", titre: "CAT lent" } }),
               "2026-11-21 10:00 ORT-2104 erreur CAT lent");
});

test("rapport : morceaux base64url recollés à l'identique ; morceau illisible = refus", () => {
  const data = Buffer.from(Array.from({ length: 70000 }, (_, i) => i % 251));
  const parts = [data.subarray(0, 30720), data.subarray(30720, 61440), data.subarray(61440)]
    .map((b) => b.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""));
  assert.deepEqual(Buffer.from(mx.joinParts(parts)), data);
  assert.equal(mx.joinParts(["abc$"]), null);
});

let passed = 0;
for (const [name, fn] of tests) {
  try { fn(); passed++; console.log("OK    " + name); } catch (e) { console.log("ÉCHEC " + name + "\n" + e.stack); process.exitCode = 1; }
}
console.log(passed + "/" + tests.length + " tests JavaScript réussis");
