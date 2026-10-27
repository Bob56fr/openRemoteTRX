// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Tests des spots du Cluster DX dans la vue HF (calculs purs) : `node tests/js/spots_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const sp = require(path.join(__dirname, "../../trxstation/gateway/api/static/spots.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

const S = (id, f, dx, extra) => Object.assign({ id, f, dx, de: "F5XYZ", m: "SSB", k: "cluster", t: "1847", n: 1, age: 0 }, extra || {});

test("instantané puis changements ; un instantané remplace tout", () => {
  const book = new sp.SpotBook();
  assert.equal(book.apply({ kind: "spots", op: "snapshot", window: [14000, 14350], spots: [S(1, 14205, "K1ABC"), S(2, 14250, "VK2XYZ")] }, 0), true);
  assert.deepEqual(book.visible(14000000, 14350000).map((s) => s.dx), ["K1ABC", "VK2XYZ"]);
  book.apply({ kind: "spots", op: "delta", spots: [S(3, 14100, "JA1XXX"), S(1, 14206, "K1ABC", { n: 2 })], removed: [2] }, 1000);
  assert.deepEqual(book.all().map((s) => [s.id, s.khz, s.count]).sort(), [[1, 14206, 2], [3, 14100, 1]]);
  book.apply({ kind: "spots", op: "snapshot", window: [7000, 7200], spots: [S(9, 7150, "EA8AA")] }, 2000);
  assert.deepEqual(book.all().map((s) => s.id), [9]);
  assert.deepEqual(book.window, [7000, 7200]);
});

test("messages étrangers ou abîmés : ignorés sans erreur", () => {
  const book = new sp.SpotBook();
  assert.equal(book.apply({ kind: "module_state", text: "x" }, 0), false);
  assert.equal(book.apply({ kind: "spots", op: "zzz", spots: [] }, 0), false);
  assert.equal(book.apply(null, 0), false);
  book.apply({ kind: "spots", op: "delta", spots: [{ id: "x", f: 1 }, { id: 1, f: -3, dx: "A1A" }, { id: 2, f: 14000, dx: "" }, S(4, 14000, "K1‮ABC")] }, 0);
  assert.deepEqual(book.all().map((s) => s.dx), ["K1ABC"]);                       // caractères de direction retirés
});

test("visibles : seulement la plage du spectre, triés par fréquence", () => {
  const book = new sp.SpotBook();
  book.apply({ kind: "spots", op: "snapshot", spots: [S(1, 14300, "B"), S(2, 14010, "A"), S(3, 14400, "C")] }, 0);
  assert.deepEqual(book.visible(14000000, 14350000).map((s) => s.dx), ["A", "B"]);
});

test("âge : celui donné par la station plus le temps écoulé ; estompage après 2 min", () => {
  const s = sp.cleanSpot(S(1, 14000, "K1ABC", { age: 30 }), 1000);
  assert.equal(sp.ageSeconds(s, 61000), 90);
  assert.equal(sp.opacity(60, 900), 1); assert.equal(sp.opacity(120, 900), 1);
  assert.ok(sp.opacity(500, 900) < 1 && sp.opacity(500, 900) > 0.35);
  assert.equal(sp.opacity(900, 900), 0.35); assert.equal(sp.opacity(5000, 900), 0.35);
  assert.equal(sp.ageLabel(10), "à l'instant"); assert.equal(sp.ageLabel(185), "il y a 3 min"); assert.equal(sp.ageLabel(3900), "il y a 1 h 05");
});

test("étiquettes : rangées l'une sous l'autre puis regroupées en « +N »", () => {
  const book = new sp.SpotBook();
  const many = [];
  for (let i = 0; i < 12; i++) many.push(S(i + 1, 14100 + i * 0.2, "CALL" + i));
  many.push(S(100, 14300, "LOIN"));
  book.apply({ kind: "spots", op: "snapshot", spots: many }, 0);
  const tags = sp.layoutLabels(book.visible(14000000, 14350000), 14000000, 14350000, 600, { rows: 3 });
  const singles = tags.filter((t) => !t.group), groups = tags.filter((t) => t.group);
  assert.deepEqual([...new Set(singles.map((t) => t.row))].sort(), [0, 1, 2]);   // trois rangées utilisées
  assert.equal(groups.length, 1); assert.equal(groups[0].row, 3);
  assert.equal(groups[0].text, "+" + groups[0].ids.length);
  assert.equal(singles.length + groups[0].ids.length, 13);                        // aucun spot perdu
  assert.ok(singles.some((t) => t.text === "LOIN" && t.row === 0));
  assert.deepEqual(sp.layoutLabels([], 0, 1, 100), []); assert.deepEqual(sp.layoutLabels(book.all(), 10, 10, 100), []);
});

test("étiquettes sans chevauchement sur une même rangée", () => {
  const spots = [S(1, 14100, "AAAA"), S(2, 14100.5, "BBBB"), S(3, 14101, "CCCC")].map((r) => sp.cleanSpot(r, 0));
  const tags = sp.layoutLabels(spots, 14000000, 14350000, 700, { rows: 3, charPx: 7, padPx: 10, gapPx: 4 });
  for (const a of tags) for (const b of tags) {
    if (a === b || a.row !== b.row) continue;
    assert.ok(Math.abs(a.x - b.x) >= (a.text.length * 7 + 10) / 2 + (b.text.length * 7 + 10) / 2, "chevauchement");
  }
});

test("liste : par fréquence ou par âge", () => {
  const spots = [S(1, 14300, "B", { age: 10 }), S(2, 14010, "A", { age: 500 }), S(3, 14200, "C", { age: 100 })].map((r) => sp.cleanSpot(r, 0));
  assert.deepEqual(sp.sortList(spots, "freq", 0).map((s) => s.dx), ["A", "C", "B"]);
  assert.deepEqual(sp.sortList(spots, "age", 0).map((s) => s.dx), ["B", "C", "A"]);
});

test("QSY : fréquence en Hz, mode adapté au poste ou rien", () => {
  const s = sp.cleanSpot(S(1, 14205.5, "K1ABC", { q: "USB" }), 0);
  assert.deepEqual(sp.qsyTarget(s, (m) => m), { hz: 14205500, mode: "USB" });
  assert.deepEqual(sp.qsyTarget(s, () => "PKTUSB"), { hz: 14205500, mode: "PKTUSB" });   // poste qui n'émet qu'en données
  assert.deepEqual(sp.qsyTarget(s, () => null), { hz: 14205500, mode: null });          // mode inconnu du poste : on ne le change pas
  assert.deepEqual(sp.qsyTarget(sp.cleanSpot(S(2, 27555, "14LG56", { k: "cb" }), 0)), { hz: 27555000, mode: null });
  assert.equal(sp.qsyTarget(null), null);
});

test("libellés : source, mode supposé, pastille", () => {
  assert.equal(sp.kindLabel("rbn"), "RBN"); assert.equal(sp.kindLabel("cb"), "CB"); assert.equal(sp.kindLabel("autre"), "DX");
  assert.equal(sp.modeLabel(sp.cleanSpot(S(1, 14000, "A1A", { mg: 1 }), 0)), "BLU (supposé)");
  assert.equal(sp.modeLabel(sp.cleanSpot(S(1, 14000, "A1A", { m: "FREEDV" }), 0)), "FreeDV");
  assert.match(sp.healthLabel("red"), /aucune source/);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + err.stack); }
  }
  console.log(`${tests.length - failed}/${tests.length} tests des spots réussis`);
  process.exit(failed ? 1 : 0);
})();
