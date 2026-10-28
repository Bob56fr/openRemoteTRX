// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Indicateur GNOME de la barre du haut (debian/gnome-extension/status.js) : `node tests/js/indicator_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
let failed = 0;

// Fichier d'état relevé sur la station (minix-bzh, 0.45.0), heure figée.
const NOW = 1793175457.5;
const status = (ptt, rig, extra) => Object.assign({
  pid: 1, seq: 1019, written_at: NOW - 0.3, schema: 1, clients: [],
  ptt: Object.assign({ state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "",
                       event: "", local_remaining_s: null, local_reason: "", local_tx: false, temp_alert: "", temp_c: null }, ptt || {}),
  rig: Object.assign({ connected: true, frequency_hz: 7195000, mode: "PKTLSB", passband_hz: 3000, strength_db: -54, ptt: false,
                       last_error: "", levels: { VD_METER: 14.447 } }, rig || {}),
  spectrum: { state: "ok", fps: 4.2 },
}, extra || {});

async function main() {
  const ind = await import(pathToFileURL(path.join(__dirname, "../../debian/gnome-extension/status.js")).href);
  const line = (view, key) => view.lines.find((l) => l.key === key);

  test("réception normale : voyant vert, fréquence et mode dans la barre", () => {
    const v = ind.summarize({ status: status(), nowS: NOW, version: "0.48.0", stationId: "46bf1040-41ed-419d-8344-e3b6e2c08a51\n" });
    assert.equal(v.level, "ok"); assert.equal(v.label, "7.195 LSB-D");
    assert.equal(line(v, "Émission").text, "réception");
    assert.equal(line(v, "Fréquence").text, "7.195.000 MHz LSB-D, filtre 3 kHz");
    assert.equal(line(v, "Clients web").text, "aucun");
    assert.equal(line(v, "Alimentation").text, "14.4 V"); assert.equal(line(v, "Spectre HF").text, "reçu (4.2 /s)");
    assert.equal(line(v, "Identifiant").text, "46bf1040-41ed-419d-8344-e3b6e2c08a51");
  });

  test("émission : voyant rouge, compte à rebours du TOT dans la barre, propriétaire", () => {
    const v = ind.summarize({ status: status({ state: "TX", owner: "phone", tot_remaining_s: 72.4 }, {}, { clients: ["phone"] }), nowS: NOW });
    assert.equal(v.level, "tx"); assert.equal(v.label, "TX 1:12");
    assert.match(line(v, "Émission").text, /ÉMISSION par phone, coupure automatique dans 1:12/);
    assert.equal(line(v, "Clients web").text, "phone");
    assert.equal(ind.summarize({ status: status({ state: "UNKEYING" }), nowS: NOW }).label, "TX");
  });

  test("station arrêtée, passerelle muette, mode sûr", () => {
    const off = ind.summarize({ status: null, nowS: NOW });
    assert.equal(off.level, "off"); assert.equal(off.label, "TRX arrêtée");
    const stale = ind.summarize({ status: status(), nowS: NOW + 30 });
    assert.equal(stale.level, "stale"); assert.match(line(stale, "Station").text, /ne répond plus depuis 30 s/);
    assert.equal(ind.summarize({ status: status(), nowS: NOW + 600 }).level, "off");     // vieux fichier : station arrêtée
    const safe = ind.summarize({ status: status({ state: "TX", owner: "phone", tot_remaining_s: 10 }), nowS: NOW, safeMode: "pannes répétées\n" });
    assert.equal(safe.level, "safe"); assert.equal(safe.label, "MODE SÛR");               // prioritaire même sur l'émission
    assert.match(line(safe, "Station").text, /MODE SÛR : pannes répétées/);
  });

  test("anomalies : voyant orange (liaison perdue, sur place, chaleur, défaut, cluster, mise à jour)", () => {
    const cases = [
      [{}, { connected: false, last_error: "connexion refusée" }, "Poste", /liaison perdue \(connexion refusée\)/],
      [{ local_remaining_s: 95, local_reason: "frequency" }, {}, "Sur place", /fréquence changée sur le poste : PTT à distance bloqué encore 1:35/],
      [{ temp_alert: "warn", temp_c: 44.2 }, {}, "Température", /poste chaud \(44 °C\)/],
      [{ temp_alert: "hot", temp_c: 52 }, {}, "Température", /POSTE TROP CHAUD/],
      [{ fault: "unkey_failed" }, {}, "Défaut", /unkey_failed/],
    ];
    for (const [ptt, rig, key, re] of cases) {
      const v = ind.summarize({ status: status(ptt, rig), nowS: NOW });
      assert.equal(v.level, "warn", key); assert.match(line(v, key).text, re);
    }
    const cl = ind.summarize({ status: status(), nowS: NOW, cluster: { enabled: true, health: "red" } });
    assert.equal(cl.level, "warn"); assert.equal(line(cl, "Cluster DX").text, "aucune source connectée");
    const up = ind.summarize({ status: status(), nowS: NOW, update: { release: { version: "0.49.0" } } });
    assert.match(line(up, "Mise à jour").text, /0\.49\.0 disponible/);
    assert.equal(ind.summarize({ status: status(), nowS: NOW, cluster: { enabled: true, health: "green" } }).level, "ok");
  });

  test("contenu des fichiers jamais affiché tel quel (contrôles, longueur)", () => {
    const v = ind.summarize({ status: status({ state: "TX", owner: "a\u001b[31m" + "x".repeat(200) }), nowS: NOW });
    assert.ok(!/\u001b/.test(JSON.stringify(v))); assert.ok(line(v, "Émission").text.length <= 120);
    assert.equal(ind.summarize({ status: "pas un objet", nowS: NOW }).level, "off");
    assert.equal(ind.summarize(null).level, "off");
  });

  test("dernière coupure traduite", () => {
    assert.equal(line(ind.summarize({ status: status({ last_cut_reason: "tot" }), nowS: NOW }), "Dernière coupure").text,
                 "durée maximale d'émission atteinte");
  });

  for (const [name, fn] of tests) {
    try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
  }
  console.log((tests.length - failed) + "/" + tests.length + " tests de l'indicateur réussis");
  process.exit(failed ? 1 : 0);
}

main();
