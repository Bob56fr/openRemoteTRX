// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Exemples communs des deux indicateurs (GNOME : status.js ; Windows : trxstation/tray/status.py), produits par status.js :
//   node scripts/build_indicator_vectors.mjs debian/gnome-extension/status.js tests/protocol/indicator_vectors.json
// À relancer après tout changement de status.js, puis adapter trxstation/tray/status.py jusqu'à ce que tests/test_tray.py passe.
import { pathToFileURL } from "node:url";
import { writeFileSync } from "node:fs";
const [, , statusJs, out] = process.argv;
const ind = await import(pathToFileURL(statusJs).href);
const NOW = 1793175457.5;
const status = (ptt, rig, extra) => Object.assign({
  pid: 1, seq: 1019, written_at: NOW - 0.3, schema: 1, clients: [],
  ptt: Object.assign({ state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "",
                       event: "", local_remaining_s: null, local_reason: "", local_tx: false, temp_alert: "", temp_c: null }, ptt || {}),
  rig: Object.assign({ connected: true, frequency_hz: 7195000, mode: "PKTLSB", passband_hz: 3000, strength_db: -54, ptt: false,
                       last_error: "", levels: { VD_METER: 14.447 } }, rig || {}),
  spectrum: { state: "ok", fps: 4.2 },
}, extra || {});
const cases = [
  ["réception normale", { status: status(), nowS: NOW, version: "0.113.0", stationId: "46bf1040-41ed-419d-8344-e3b6e2c08a51\n" }],
  ["émission avec TOT", { status: status({ state: "TX", owner: "phone", tot_remaining_s: 72.4 }, {}, { clients: ["phone"] }), nowS: NOW }],
  ["émission, TOT à un demi", { status: status({ state: "TX", owner: "phone", tot_remaining_s: 72.5 }), nowS: NOW }],
  ["émission sans TOT", { status: status({ state: "TX", owner: "pc" }), nowS: NOW }],
  ["prise d'émission", { status: status({ state: "KEYING" }), nowS: NOW }],
  ["coupure en cours", { status: status({ state: "UNKEYING" }), nowS: NOW }],
  ["station arrêtée", { status: null, nowS: NOW }],
  ["passerelle muette", { status: status(), nowS: NOW + 30 }],
  ["vieux fichier", { status: status(), nowS: NOW + 600 }],
  ["mode sûr prioritaire", { status: status({ state: "TX", owner: "phone", tot_remaining_s: 10 }), nowS: NOW, safeMode: "pannes répétées\n" }],
  ["mode sûr, station arrêtée", { status: null, nowS: NOW, safeMode: "pannes" }],
  ["liaison perdue", { status: status({}, { connected: false, last_error: "connexion refusée" }), nowS: NOW }],
  ["sur place", { status: status({ local_remaining_s: 95, local_reason: "frequency" }), nowS: NOW }],
  ["sur place, émission locale", { status: status({ local_remaining_s: 0, local_reason: "tx", local_tx: true }), nowS: NOW }],
  ["poste chaud", { status: status({ temp_alert: "warn", temp_c: 44.5 }), nowS: NOW }],
  ["poste trop chaud", { status: status({ temp_alert: "hot", temp_c: 52 }), nowS: NOW }],
  ["température normale", { status: status({ temp_c: 31.5 }), nowS: NOW }],
  ["défaut", { status: status({ fault: "unkey_failed" }), nowS: NOW }],
  ["dernière coupure", { status: status({ last_cut_reason: "tot" }), nowS: NOW }],
  ["coupure inconnue", { status: status({ last_cut_reason: "autre_raison" }), nowS: NOW }],
  ["filtre 2,25 kHz et tension 12,25 V", { status: status({}, { passband_hz: 2250, levels: { VD_METER: 12.25 } }), nowS: NOW }],
  ["filtre 500 Hz, tension basse", { status: status({}, { passband_hz: 500, mode: "CW", levels: { VD_METER: 11.95 } }), nowS: NOW }],
  ["spectre entier, en panne, en attente", { status: status({}, {}, { spectrum: { state: "error", message: "port COM7 absent" } }), nowS: NOW }],
  ["spectre fps entier", { status: status({}, {}, { spectrum: { state: "ok", fps: 4 } }), nowS: NOW }],
  ["spectre en attente", { status: status({}, {}, { spectrum: { state: "waiting" } }), nowS: NOW }],
  ["cluster rouge", { status: status(), nowS: NOW, cluster: { enabled: true, health: "red" } }],
  ["cluster vert", { status: status(), nowS: NOW, cluster: { enabled: true, health: "green" } }],
  ["cluster désactivé", { status: status(), nowS: NOW, cluster: { enabled: false, health: "red" } }],
  ["mise à jour", { status: status(), nowS: NOW, update: { release: { version: "0.114.0" } } }],
  ["fréquence 145,6 MHz FM", { status: status({}, { frequency_hz: 145600000, mode: "FM", passband_hz: 15000 }), nowS: NOW }],
  ["contenu hostile", { status: status({ state: "TX", owner: "a\u001b[31m" + "x".repeat(200) }), nowS: NOW }],
  ["état non objet", { status: "pas un objet", nowS: NOW }],
  ["entrée nulle", null],
];
writeFileSync(out, JSON.stringify(cases.map(([name, input]) => ({ name, input, expect: ind.summarize(input) })), null, 1) + "\n");
console.log(cases.length + " exemples");
