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

test("voyants comme l'application : ATT ou P.AMP n, RIT, ΔTX, SPLIT, NOTCH, NB, NR", () => {
  const caps = { preamps: [10, 20] };
  const v = web.indicatorsView({ RIT: false, XIT: true, ANF: false, MN: true, NB: true, NR: false }, { PREAMP: 20, ATT: 0 }, { split: false }, caps);
  assert.deepEqual(v.map((i) => i.label + (i.on ? "+" : "-")), ["P.AMP 2+", "RIT-", "ΔTX+", "SPLIT-", "NOTCH+", "NB+", "NR-"]);
  assert.equal(web.indicatorsView({}, { ATT: 12, PREAMP: 1 }, {}, caps)[0].label, "ATT");
  assert.equal(web.indicatorsView({}, { PREAMP: 1 }, {}, {})[0].label, "P.AMP 1");      // valeur déjà en rang (IC-7300MK2)
  assert.deepEqual(web.indicatorsView({}, {}, {}, {}), []);                              // rien de publié : aucun voyant
});

test("profils du micro : contrôle automatique de gain toujours coupé ; casque à réduction de bruit = rien du navigateur", () => {
  for (const key of Object.keys(web.MIC_PROFILES)) assert.equal(web.micConstraints(key, {}).autoGainControl, false);
  assert.deepEqual(web.micConstraints("headset_nr"), { echoCancellation: false, noiseSuppression: false, autoGainControl: false });
  assert.deepEqual(web.micConstraints("noisy"), { echoCancellation: true, noiseSuppression: true, autoGainControl: false });
  assert.equal(web.micConstraints("inconnu").noiseSuppression, false);                       // défaut : pièce calme
  assert.deepEqual(web.micConstraints("custom", { echo: false, noise: true }), { echoCancellation: false, noiseSuppression: true, autoGainControl: false });
});

test("voyant OVERLOAD ALC : à partir du seuil commun, pendant toute émission", () => {
  assert.equal(web.ALC_OVERLOAD, 0.5);
  const over = web.indicatorsView({}, { ALC: 0.6 }, {}, {});
  assert.deepEqual(over, [{ label: "OVERLOAD ALC", on: true, alert: true }]);
  assert.deepEqual(web.indicatorsView({}, { ALC: 0.3 }, {}, {}), []);
});

test("bandes préférées : ordre du plan, inconnues ignorées, aucune = toutes", () => {
  assert.deepEqual(web.favoriteBands("20, 11,99,40").map((b) => b.key), ["40", "20", "11"]);
  assert.equal(web.favoriteBands("").length, web.BANDS.length);
});

test("clarifieur : ΔTX prioritaire, décalage borné, absent sans RIT ni XIT", () => {
  const rig = messages.state.rig, caps = messages.hello.capabilities;
  assert.equal(web.clarifierView({}, rig, caps), null);
  const x = web.clarifierView({ XIT: true, RIT: true }, Object.assign({}, rig, { offsets: { XIT: 250, RIT: 20 } }), caps);
  assert.deepEqual(x, { name: "XIT", label: "ΔTX", hz: 250, max: 9999 });
  assert.equal(web.clarifierView({ RIT: true }, Object.assign({}, rig, { offsets: { RIT: 50000 } }), caps).hz, 9999);
  assert.equal(web.clarifierText(-1234), "-1230 Hz");
  assert.equal(web.clarifierText(0), "+0 Hz");
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du protocole (page) réussis");
process.exit(failed ? 1 : 0);
