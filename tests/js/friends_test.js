// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Présence de groupe « Amis » de la page (friends.js) : `node tests/js/friends_test.js`
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const fx = require(path.join(__dirname, "../../trxstation/gateway/api/static/friends.js"));
const VECTORS = JSON.parse(fs.readFileSync(path.join(__dirname, "../protocol/presence_vectors.json"), "utf-8"));

let passed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const NOW = 1794000000;
const member = (extra) => Object.assign({ id: "1".repeat(32), pseudo: "F5XYZ", code: "R", age: 40, sd: NOW - 120, lt: NOW - 900,
                                          lv: "f", f: 14205000, m: "USB", updated: 40, role: "m" }, extra || {});

test("mêmes âges, pseudos et textes libres que la station (vecteurs partagés)", () => {
  for (const c of VECTORS.format_age) assert.equal(fx.formatAge(c.s), c.out, "âge " + c.s);
  for (const c of VECTORS.pseudo) assert.equal(fx.cleanPseudo(c.in), c.out, "pseudo « " + c.in + " »");
  for (const c of VECTORS.text) assert.equal(fx.cleanText(c.in), c.out, "texte « " + c.in + " »");
  assert.equal(fx.freshness(42), "42 s"); assert.equal(fx.freshness(125), "2 min");
});

test("un membre : pastille couleur ET lettre, détail selon le statut et le partage", () => {
  const r = fx.memberView(member(), NOW, 0);
  assert.deepEqual([r.code, r.letter, r.cls, r.detail, r.qsy], ["R", "R", "r", "14,205 MHz USB", true]);
  assert.ok(r.lines.includes("Dernière émission il y a 15 min"));
  assert.equal(fx.memberView(member({ code: "Q", lv: "o", f: undefined, m: undefined }), NOW, 0).detail, "On Air");
  assert.equal(fx.memberView(member({ code: "Q", lv: "x", x: "Test antenne" }), NOW, 0).detail, "« Test antenne »");
  assert.equal(fx.memberView(member({ code: "A", sd: NOW - 7200 }), NOW, 0).detail, "Absent depuis 2 h");
  assert.equal(fx.memberView(member({ code: "A", sd: undefined }), NOW, 0).detail, "Absent");      // durée masquée par le membre
  assert.match(fx.memberView(member({ code: "S", su: NOW + 3600 }), NOW, 0).detail, /^Au shack jusqu'à \d\d:\d\d$/);
  const off = fx.memberView(member({ code: "O", age: 900 }), NOW, 0);
  assert.deepEqual([off.letter, off.cls, off.detail, off.qsy], ["", "o", "Hors ligne", false]);
  const stale = fx.memberView(member({ age: 230 }), NOW, 20);       // la vue vieillit : hors ligne sans la redemander
  assert.equal(stale.code, "O");
  assert.equal(fx.memberView(member({ lv: "o", f: undefined }), NOW, 0).qsy, false);
});

test("vue par groupe triée, vue par membre sans doublon, pastilles du titre", () => {
  const view = { groups: [
    { g: "a".repeat(32), name: "Club", role: "a", status: "member", members: [
      member({ id: "1".repeat(32), pseudo: "zed", code: "A" }), member({ id: "2".repeat(32), pseudo: "Bob", code: "Q" }),
      member({ id: "3".repeat(32), pseudo: "amy", code: "O", age: 999 })] },
    { g: "b".repeat(32), name: "Mobiles", role: "m", status: "member", members: [member({ id: "2".repeat(32), pseudo: "Bob", code: "R" })] }] };
  const byGroup = fx.buildView(view, NOW, 0, "group");
  assert.deepEqual(byGroup.groups[0].members.map((m) => m.pseudo), ["Bob", "zed", "amy"]);
  assert.equal(byGroup.groups[0].admin, true); assert.equal(byGroup.groups[1].admin, false);
  const byMember = fx.buildView(view, NOW, 0, "member");
  assert.equal(byMember.members.length, 3);
  const bob = byMember.members.find((m) => m.pseudo === "Bob");
  assert.deepEqual([bob.code, bob.groups], ["Q", ["Club", "Mobiles"]]);
  const b = fx.badges(view, NOW, 0, 8);
  assert.deepEqual([b.list.length, b.active, b.total], [2, 1, 3]);
  assert.deepEqual(fx.buildView(null, NOW, 0, "group").groups, []);
});

test("QSY : refusé en émission, confirmation avec l'âge, changement de bande, hors bandes de la station", () => {
  const m = fx.memberView(member(), NOW, 0);
  assert.deepEqual(fx.qsyPlan(m, { pttState: "TX" }), { ok: false, reason: "tx_active", text: "Émission en cours : pas de QSY." });
  assert.deepEqual(fx.qsyPlan(m, { pttState: "KEYING" }).reason, "tx_active");
  assert.equal(fx.qsyPlan(fx.memberView(member({ lv: "o" }), NOW, 0), {}).reason, "no_frequency");
  const same = fx.qsyPlan(m, { pttState: "RX", rigHz: 14074000 });
  assert.equal(same.text, "Aller sur 14,205 MHz USB ?");
  assert.equal(same.warnings.filter((w) => w.level === "warn").length, 0);
  assert.ok(same.warnings.some((w) => w.level === "info" && /Mis à jour il y a 40 s/.test(w.text)));
  const other = fx.qsyPlan(m, { pttState: "RX", rigHz: 7074000 });
  assert.ok(other.warnings.some((w) => /Changement de bande/.test(w.text)));
  const outside = fx.qsyPlan(fx.memberView(member({ tx_ok: false }), NOW, 0), { pttState: "RX", rigHz: 14074000 });
  assert.ok(outside.warnings.some((w) => /réception seulement/.test(w.text)));
  assert.ok(fx.qsyPlan(m, { pttState: "RX", selfCode: "Q" }).warnings.some((w) => w.level === "strong"));
});

test("affichage choisi, fenêtre détachée seulement si le navigateur la permet, invitation collée, statistiques", () => {
  assert.equal(fx.pipSupported({}), false);
  assert.equal(fx.pipSupported({ documentPictureInPicture: { requestWindow() {} } }), true);
  assert.equal(fx.displayMode("pip", false), "section"); assert.equal(fx.displayMode("pip", true), "pip");
  assert.equal(fx.displayMode("big", false), "big"); assert.equal(fx.displayMode("n'importe", true), "section");
  assert.equal(fx.cleanInvitation("  https://api.rf-diy.com/i#eyJ2\n  IjoxfQ  "), "https://api.rf-diy.com/i#eyJ2IjoxfQ");
  assert.equal(fx.cleanInvitation("court"), null); assert.equal(fx.cleanInvitation(12), null);
  const rows = fx.statsRows({ ["1".repeat(32)]: { last_active: "2026-11-10", active_days_month: 3,
    weeks: [{ week: "2026-11-09", qso_min: 12, rx_min: 40 }] }, ["2".repeat(32)]: {} }, { ["1".repeat(32)]: "F5XYZ" });
  assert.deepEqual(rows.map((r) => [r.pseudo, r.days, r.qsoMin, r.rxMin]), [["22222222", 0, 0, 0], ["F5XYZ", 3, 12, 40]]);
  assert.equal(fx.CONSENT.length, 3);
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); passed += 1; console.log("OK    " + name); } catch (e) { console.log("ÉCHEC " + name + "\n" + (e.stack || e)); }
  }
  console.log(passed + "/" + tests.length + " tests de friends.js réussis");
  process.exit(passed === tests.length ? 0 : 1);
})();
