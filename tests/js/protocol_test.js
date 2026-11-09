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

test("santé de la machine de la station : bargraph, niveau, rien pour un visiteur ou une station ancienne", () => {
  const v = web.hostView(messages.state.host);
  assert.equal(v.fraction, 0.487); assert.equal(v.level, "ok");
  assert.match(v.title, /processeur 12 %, mémoire 41 %, disque 37 %, 46 °C/);
  assert.equal(web.hostView({ load: 1.4, level: "bad", throttled: true }).fraction, 1);
  assert.match(web.hostView({ load: 1, level: "bad", throttled: true }).title, /Pi RALENTI/);
  assert.equal(web.hostView({ load: 0.2, level: "rouge" }).level, "ok");
  assert.equal(web.hostView(null), null); assert.equal(web.hostView({ cpu_pct: 3 }), null);
});

test("voyant du VFO actif : en tête, seulement si la station le lit (Yaesu FTDX10/101 oui, IC-7300MK2 non)", () => {
  const rig = messages.state.rig;
  assert.deepEqual(web.indicatorsView({}, {}, rig, {})[0], { label: "VFO A", on: true });
  assert.equal(web.vfoLabel("VFOB"), "VFO B");
  assert.equal(web.vfoLabel("Sub"), "SUB");
  assert.equal(web.vfoLabel("MEM"), "MEM");
  for (const nothing of [null, undefined, "", "currVFO", "<b>x</b>", 3]) assert.equal(web.vfoLabel(nothing), "");
  assert.deepEqual(web.indicatorsView({}, {}, { vfo: null }, {}), []);
});

test("profils du micro : contrôle automatique de gain toujours coupé ; casque à réduction de bruit = rien du navigateur", () => {
  for (const key of Object.keys(web.MIC_PROFILES)) assert.equal(web.micConstraints(key, {}).autoGainControl, false);
  assert.deepEqual(web.micConstraints("headset_nr"), { echoCancellation: false, noiseSuppression: false, autoGainControl: false });
  assert.deepEqual(web.micConstraints("noisy"), { echoCancellation: true, noiseSuppression: true, autoGainControl: false });
  assert.equal(web.micConstraints("inconnu").noiseSuppression, false);                       // défaut : pièce calme
  assert.deepEqual(web.micConstraints("custom", { echo: false, noise: true }), { echoCancellation: false, noiseSuppression: true, autoGainControl: false });
});

test("refus du micro expliqué : micro bloqué par son pilote (AT2020USB-XP), accès refusé, micro disparu", () => {
  const busy = web.micErrorText({ name: "NotReadableError" });
  assert.match(busy, /NotReadableError/); assert.match(busy, /exclusif/); assert.match(busy, /débranchez/); assert.match(busy, /Réception seule\.$/);
  assert.match(web.micErrorText({ name: "NotAllowedError" }), /Confidentialité > Microphone/);
  assert.match(web.micErrorText({ name: "OverconstrainedError" }), /dans la liste/);
  assert.equal(web.micErrorText({ name: "Bizarre" }), "Micro refusé ou absent (Bizarre). Réception seule.");
  assert.equal(web.micErrorText("texte"), "Micro refusé ou absent (texte). Réception seule.");
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
  assert.equal(web.clarifierView({ RIT: true }, Object.assign({}, rig, { offsets: { RIT: 50000 } }), caps).hz, 500);
  // RIT limité à ±500 Hz (étape 97), même face à une station plus ancienne qui annonce la plage du poste
  assert.equal(web.clarifierView({ RIT: true }, rig, Object.assign({}, caps, { max_rit_hz: 9999 })).max, 500);
  assert.equal(web.clarifierView({ RIT: true }, rig, {}).max, 500);
  assert.equal(web.clarifierView({ XIT: true }, rig, {}).max, 9999);
  assert.equal(web.clarifierText(-1234), "-1230 Hz");
  assert.equal(web.clarifierText(0), "+0 Hz");
});

test("sonde réseau : state.net d'exemple -> indicateur, détail, avertissement de profil VPN", () => {
  const v = web.netView(messages.state_net.net);
  assert.equal(v.level, "orange"); assert.equal(v.bars, 2); assert.equal(v.weak, false); assert.equal(v.outage, false);
  assert.match(v.title, /liaison moyenne, aller-retour 180 ms, perte 3,3 %/);
  assert.deepEqual(v.rows[0], ["Perte (60 s / 10 s)", "3,3 % / 0 %"]);
  assert.match(v.rows.at(-1)[1], /il y a 1 min 15 s — tronçon probable : téléphone, réseau mobile ou tunnel/);
  assert.match(v.vpn[0].text, /page Windows \/ android 0\.53\.0\) arrivent en même temps par la même adresse 192\.168\.27\.2/);
  assert.match(v.thresholds, /orange à 250 ms ou 2 %, rouge à 600 ms ou 10 %/);
  assert.equal(web.netView(null), null); assert.equal(web.netView({ level: "violet" }), null);
  const out = web.netView({ level: "red", outage: true, outage_s: 7, probes: { lan: { method: "icmp", ok: false, loss_pct: 50, rtt_ms: null } } });
  assert.equal(out.weak, true); assert.deepEqual(out.rows[0], ["COUPURE EN COURS", "depuis 7 s"]);
  assert.deepEqual(out.probes[0], ["Box (ping)", "NE RÉPOND PAS · perte 50 % · —"]);
  assert.match(web.vpnText({ kind: "pattern", period_ms: 28000, agents: ["android"] }), /toutes les ~28 s/);
  const ev = messages.net_event[0];
  assert.equal(web.NET_DIAGNOSES[ev.outage.diagnosis], "profil VPN probablement partagé par un autre appareil");
});

test("sonde réseau : statistiques 30 jours -> vue", () => {
  const stats = { days: 30, summary: { outages: 3, outage_s: 75, longest_s: 40, connected_s: 7200, availability_pct: 99, loss_pct: 0.4 },
    per_day: [{ date: "2026-11-08", outages: 1, outage_s: 40, by_diagnosis: { lan: 1 }, hours: Array(24).fill(0).map((_, h) => (h === 8 ? 1 : 0)), loss_pct: 0.2, rtt_p95_ms: 90 },
              { date: "2026-11-09", outages: 2, outage_s: 35, by_diagnosis: { vpn_shared: 2 }, hours: Array(24).fill(0).map((_, h) => (h === 18 ? 2 : 0)), loss_pct: null, rtt_p95_ms: null }],
    by_diagnosis: { vpn_shared: 2, lan: 1 }, by_net_type: { "4g": { windows: 360, outages: 2, loss_pct: 0.5 } },
    thresholds: { "4g": { in_force: { rtt_warn: 250, rtt_alert: 600, loss_warn: 2, loss_alert: 10 }, chosen: false, days: 2,
                          rtt_hist: [[10, 0], [5, 1]], loss_hist: [[15, 1]], proposed: { rtt: null, loss: null } } },
    edges: { rtt_ms: [50], loss_pct: [0.5] },
    outages_list: [{ start_ms: 1762700000000, duration_ms: 6000, diagnosis: "vpn_shared", basis: ["backlog", "regular_pattern"], agent: "android", net_type: "4g", kind: "in_session" }],
    devices: [{ device: "a".repeat(32), agent: "android", last_ms: 1 }] };
  const m = web.netStatsModel(stats);
  assert.deepEqual(m.summary[0], ["Coupures", "3"]); assert.deepEqual(m.summary[1], ["Durée cumulée", "1 min 15 s"]);
  assert.equal(m.days[1].fraction, 1); assert.equal(m.days[0].fraction, 0.5);
  assert.equal(m.days[1].hours[18].fraction, 1); assert.equal(m.days[0].hours[8].fraction, 0.5);
  assert.equal(m.diagnoses[0].code, "vpn_shared"); assert.ok(Math.abs(m.diagnoses[0].fraction - 2 / 3) < 1e-9);
  assert.deepEqual(m.types[0], ["4G", "1 h 00 mesurés · 2 coupure(s) · perte 0,5 %"]);
  assert.equal(m.outages[0].basis, "mesures du client, coupures régulières"); assert.equal(m.outages[0].kind, "liaison ouverte");
  assert.equal(m.thresholds[0].label, "4G"); assert.deepEqual(m.thresholds[0].rttHist[1], { n: 5, degraded: 1 });
  assert.equal(web.netStatsModel(null), null); assert.equal(web.netStatsModel({}), null);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du protocole (page) réussis");
process.exit(failed ? 1 : 0);
