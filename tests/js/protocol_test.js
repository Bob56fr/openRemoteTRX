// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Exemples partagés du protocole (tests/protocol/, docs/protocole.md) lus par la page : `node tests/js/protocol_test.js`
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const web = require(path.join(__dirname, "../../trxstation/gateway/api/static/client.js"));
const messages = JSON.parse(fs.readFileSync(path.join(__dirname, "../protocol/messages.json"), "utf-8"));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("état d'exemple : aucun bandeau quand le poste est libre et froid", () => {
  const ptt = messages.state.ptt;
  assert.equal(web.localView(ptt).active, false);
  assert.equal(web.tempView(ptt).level, "");
});

test("poste utilisé sur place et température : lus dans state.ptt tel que la station l'envoie", () => {
  const ptt = Object.assign({}, messages.state.ptt, { local_remaining_s: 95.4, local_reason: "frequency", temp_alert: "warn", temp_c: 43 });
  const local = web.localView(ptt);
  assert.equal(local.active, true); assert.equal(local.transmitting, false);
  assert.match(local.text, /fréquence changée sur le poste/);
  assert.equal(web.tempView(ptt).level, "warn");
  assert.equal(web.localView(Object.assign({}, ptt, { local_tx: true })).transmitting, true);
});

test("version de la station affichée depuis hello", () => {
  assert.equal(web.versionLabel(messages.hello.version), "v" + messages.hello.version);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du protocole (page) réussis");
process.exit(failed ? 1 : 0);
