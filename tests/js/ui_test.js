// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Essai de l'affichage (ui.js) avec un faux navigateur qui charge la VRAIE page : `node tests/js/ui_test.js`
// Il attrape les éléments manquants, les fautes de frappe et les erreurs d'exécution avant qu'on ne les voie sur un téléphone.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STATIC = path.join(__dirname, "../../trxstation/gateway/api/static");
const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf-8");

// ------------------------------------------------------------------ faux DOM
class FakeCtx {                                                   // contexte de dessin 2D qui enregistre les appels
  constructor() { this.calls = []; this.images = 0; }
  count(name) { return this.calls.filter((c) => c === name).length; }
  createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; }
}
for (const method of ["clearRect", "fillRect", "beginPath", "moveTo", "lineTo", "closePath", "stroke", "fill", "drawImage", "putImageData", "fillText", "save", "restore"]) {
  FakeCtx.prototype[method] = function () { this.calls.push(method); if (method === "putImageData") this.lastRow = arguments[0]; };
}

class FakeElement {
  constructor(tag, attrs) {
    this.tagName = (tag || "div").toLowerCase(); this.children = []; this.handlers = {}; this.attrs = {}; this.style = {};
    this.className = ""; this._text = ""; this.title = ""; this.value = ""; this.checked = false; this.disabled = false; this.hidden = false; this.open = false;
    this.parent = null; this.focused = false; this.rect = null; this.ctx = null; this.width = 300; this.height = 150;
    if (attrs) {
      this.hidden = /\shidden(\s|$)/.test(" " + attrs); this.disabled = /\sdisabled(\s|$)/.test(" " + attrs);
      this.checked = /\schecked(\s|$)/.test(" " + attrs); this.open = /\sopen(\s|$)/.test(" " + attrs);
      const value = /\svalue="([^"]*)"/.exec(" " + attrs); if (value) this.value = value[1];
      const cls = /\sclass="([^"]*)"/.exec(" " + attrs); if (cls) this.className = cls[1];
    }
  }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); if (this._text === "") this.children = []; }
  get options() { return this.children.filter((c) => c.tagName === "option"); }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  appendChild(node) { node.parent = this; this.children.push(node); return node; }
  removeChild(node) { this.children = this.children.filter((c) => c !== node); return node; }
  insertBefore(node, ref) { node.parent = this; const i = ref ? this.children.indexOf(ref) : -1; if (i < 0) this.children.push(node); else this.children.splice(i, 0, node); return node; }
  addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); }
  removeEventListener(type, fn) { this.handlers[type] = (this.handlers[type] || []).filter((f) => f !== fn); }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; } removeAttribute(k) { delete this.attrs[k]; }
  focus() { this.focused = true; }
  getBoundingClientRect() { return this.rect || { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0 }; }
  getContext() { return this.ctx || (this.ctx = new FakeCtx()); }
  scrollIntoView() { this.scrolled = true; }
  setPointerCapture(id) { this.captured = id; }
  async dispatch(type, extra) { await Promise.all((this.handlers[type] || []).map((fn) => fn(Object.assign({ type, target: this }, extra || {})))); }
  click() { return this.dispatch("click"); }
}

const byId = new Map();
for (const m of html.matchAll(/<(\w+)([^>]*?)>/g)) {
  const id = /\sid="([^"]+)"/.exec(m[2]);
  if (id) byId.set(id[1], new FakeElement(m[1], m[2]));
}
for (const m of html.matchAll(/<select id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {          // les options écrites dans la page existent aussi dans le faux navigateur
  const select = byId.get(m[1]);
  for (const o of m[2].matchAll(/<option value="([^"]*)"[^>]*>([^<]*)<\/option>/g)) {
    const option = new FakeElement("option"); option.value = o[1]; option.textContent = o[2]; select.appendChild(option);
  }
  if (select.children.length) select.value = select.children[0].value;
}
const documentHandlers = {};
global.document = {
  getElementById: (id) => byId.get(id) || null,
  createElement: (tag) => new FakeElement(tag),
  addEventListener: (type, fn) => { (documentHandlers[type] = documentHandlers[type] || []).push(fn); },
  documentElement: new FakeElement("html"), hidden: false,
};

// ------------------------------------------------------------------ faux navigateur
class FakeDC { constructor() { this.readyState = "open"; this.sent = []; this.onmessage = null; this.onclose = null; } send(t) { this.sent.push(JSON.parse(t)); } close() { this.readyState = "closed"; } }
class FakePC {
  constructor() { this.tracks = []; this.dc = null; this.iceGatheringState = "complete"; this.connectionState = "new"; pcs.push(this); }
  addTrack(t) { this.tracks.push(t); } addTransceiver() {}
  createDataChannel(label) { const ch = new FakeDC(); ch.label = label; (this.channels = this.channels || {})[label] = ch; if (label === "control") this.dc = ch; return ch; }
  async createOffer() { return { sdp: "v=0", type: "offer" }; }
  async setLocalDescription(d) { this.localDescription = d; } async setRemoteDescription() {}
  async getStats() { return { forEach() {} }; }
  addEventListener() {} removeEventListener() {} close() { this.connectionState = "closed"; }
}
let offerStatus = 200;
const offers = [];
const pcs = [], rafQueue = [], audioContexts = [], sources = [], analysers = [], clipboard = [], oscillators = [], vibrations = [];
let rigAudioList = [];
const storage = new Map();
let landscape = false;
const windowHandlers = {};
const mic = { enabled: true, label: "Microphone (Realtek)", stop() {} };
Object.assign(globalThis, {
  window: globalThis, isSecureContext: true, RTCPeerConnection: FakePC, innerWidth: 412, innerHeight: 860,
  matchMedia: () => ({ matches: landscape }),
  requestAnimationFrame: (fn) => { rafQueue.push(fn); return rafQueue.length; },
  cancelAnimationFrame: () => { rafQueue.length = 0; },
  AudioContext: class {
    constructor() { this.sampleRate = 48000; this.state = "running"; this.currentTime = 0; this.destination = { name: "sortie" }; audioContexts.push(this); }
    resume() { return Promise.resolve(); }
    createOscillator() {
      const osc = { type: "", frequency: { value: 0 }, connect(target) { this.target = target; }, start(t) { this.startAt = t; }, stop(t) { this.stopAt = t; } };
      oscillators.push(osc); return osc;
    }
    createGain() {
      const values = [];
      return { values, gain: { setValueAtTime(v) { values.push(v); }, linearRampToValueAtTime(v) { values.push(v); } }, connect(target) { this.target = target; } };
    }
    createMediaStreamSource(stream) { const node = { stream, disconnected: false, connect(target) { this.target = target; }, disconnect() { this.disconnected = true; } }; sources.push(node); return node; }
    createAnalyser() {
      const node = { fftSize: 2048, frequencyBinCount: 1024, get fftSize2() { return 0; }, smoothingTimeConstant: 0,
        getFloatFrequencyData(array) { array.fill(-100); array[Math.round(1500 / (48000 / node.fftSize))] = -25; node.reads += 1; }, reads: 0 };
      Object.defineProperty(node, "frequencyBinCount", { get: () => node.fftSize / 2 });
      analysers.push(node); return node;
    }
  },
  location: { origin: "https://station:8443" },
  localStorage: { getItem: (k) => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, String(v)) },
  MediaStream: class { constructor(tracks) { this.tracks = tracks; } },
  fetch: async (url, options) => {
    if (url === "config") return { ok: true, status: 200, json: async () => ({ ice_servers: [], rig_audio: rigAudioList }) };
    offers.push(JSON.parse(options.body));
    return { ok: offerStatus === 200, status: offerStatus, json: async () => ({ sdp: "v=0", type: "answer" }) };
  },
});
globalThis.addEventListener = (type, fn) => { (windowHandlers[type] = windowHandlers[type] || []).push(fn); };
Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
  mediaDevices: { getUserMedia: async () => ({ getAudioTracks: () => [mic] }), enumerateDevices: async () => [
    { kind: "audioinput", deviceId: "m1", label: "Microphone (Realtek)" }, { kind: "audiooutput", deviceId: "o1", label: "Haut-parleurs" }] },
  clipboard: { writeText: async (text) => { clipboard.push(text); } },
  wakeLock: { request: async () => ({ released: false, addEventListener() {}, release() { return Promise.resolve(); } }) },
  vibrate: (pattern) => { vibrations.push(pattern); return true; },
} });
byId.get("rx-audio").play = () => Promise.resolve();
byId.get("rx-audio").setSinkId = async () => {};

process.on("unhandledRejection", (err) => { console.error("ERREUR non gérée :", err); process.exit(1); });

global.TrxWeb = require(path.join(STATIC, "client.js"));
global.TrxWaterfall = require(path.join(STATIC, "waterfall.js"));
global.TrxLayout = require(path.join(STATIC, "layout.js"));
global.TrxTheme = require(path.join(STATIC, "theme.js"));
global.TrxHfScope = require(path.join(STATIC, "hfscope.js"));
global.TrxSpots = require(path.join(STATIC, "spots.js"));
const FACTORY = require("./factory_profile.json");                                     // copie du profil d'usine (vérifiée par pytest)
require(path.join(STATIC, "ui.js"));

const $ = (id) => byId.get(id);
const freqText = () => $("freq").children.map((c) => c.textContent).join("");
const answered = new Set();
const answerAll = () => { for (const m of dc().sent) if (m.id !== undefined && !answered.has(m.id)) { answered.add(m.id); send({ type: "result", id: m.id, ok: true }); } };
// horodatages d'animation sur UNE frise commune à tous les appels (ne dépend pas de la vitesse de la machine)
let frameBase = null;
const runFrames = (times) => { if (frameBase === null) frameBase = performance.now(); for (const dt of times) { const fn = rafQueue.shift(); if (!fn) return false; fn(frameBase + dt); } return true; };
const layoutDigits = () => $("freq").children.forEach((c, i) => { c.rect = { left: i * 20, right: i * 20 + 18, top: 0, bottom: 40, width: 18, height: 40 }; });
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms || 15));
const dc = () => pcs[pcs.length - 1].dc;
const send = (msg) => dc().onmessage({ data: JSON.stringify(msg) });
const sent = (cmd) => dc().sent.filter((m) => m.cmd === cmd);
const answer = (ok, extra, cmd) => {                    // répond à la dernière commande (ou à la dernière « cmd » donnée)
  const last = dc().sent.filter((m) => m.id !== undefined && (!cmd || m.cmd === cmd)).pop();
  send(Object.assign({ type: "result", id: last.id, ok }, extra || {}));
};
const MEMORIES = [
  { id: "m1", name: "Quatre-vingts", hz: 3700000, mode: "LSB", favorite: true },
  { id: "m2", name: "Vingt", hz: 14200000, mode: "USB", favorite: false },
  { id: "m3", name: "Quarante", hz: 7074000, mode: "PKTUSB", favorite: false },
];
const state = (ptt, rig) => send({ type: "state",
  ptt: Object.assign({ state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "" }, ptt || {}),
  rig: Object.assign({ connected: true, frequency_hz: 14200000, mode: "USB", passband_hz: 2400, strength_db: -12,
    functions: { NR: false, NB: true, AIP: false, COMP: false, TUNER: false }, levels: { PREAMP: 10, SQL: 0.25, RFPOWER: 0.5, RFPOWER_METER: 0, SWR: 1.2, ALC: 0, VD_METER: 13.8, TEMP_METER: 31, ATT: 0, AGC: 2 } }, rig || {}),
  audio: { rx_db: -23, tx_db: -90, gate_open: false }, clients: ["phone"] });

const steps = [];
const step = (name, fn) => steps.push([name, fn]);

step("démarrage : tout est en place avant la connexion", async () => {
  await Promise.all(documentHandlers.DOMContentLoaded.map((fn) => fn()));
  assert.equal($("splash").hidden, false); await $("splash").click();                                                    // l'image d'accueil : un appui la passe
  assert.equal($("splash").hidden, true);
  assert.equal($("reconnect-select").value, "15"); assert.equal($("reconnect").hidden, true); assert.equal($("freq").hidden, false);
  assert.deepEqual($("reconnect-select").options.map((o) => o.value), ["0", "15", "30", "60"]);
  assert.equal($("app").className, "portrait");                                   // portrait par défaut
  assert.equal($("ptt").disabled, true); assert.equal($("stop").disabled, true); assert.equal($("armed").disabled, true);
  assert.equal($("squelch").disabled, true); assert.equal($("mem-add-current").disabled, true);
  assert.equal($("sec-connect").open, true); assert.equal($("mem-empty").hidden, false); assert.equal($("instruments-empty").hidden, false);
  assert.equal($("insecure").hidden, true); assert.equal($("origin").textContent, "https://station:8443");
  assert.equal($("mem-form").hidden, true);
});

step("connexion : zone de connexion repliée, identifiant mémorisé, mot de passe effacé", async () => {
  $("client-id").value = "phone"; $("password").value = "mot de passe";
  await $("connect").click(); await wait();
  assert.equal(pcs.length, 1);
  assert.equal($("version").hidden, true);                                                    // pas de version tant qu'on n'est pas connecté
  send({ type: "hello", protocol: 1, client_id: "phone", version: "0.37.0", capabilities: { modes: ["USB", "LSB", "PKTUSB", "PKTLSB"], filters: { USB: [3000, 2400, 1800] }, preamps: [10, 20] }, tx_modes: [], max_power_w: 100, memories: MEMORIES });
  await wait(30);
  assert.equal($("version").hidden, false); assert.equal($("version").textContent, "v0.37.0");   // à droite de « Connecté »
  assert.equal($("password").value, "");
  assert.equal(storage.get("trx.client_id"), "phone"); assert.ok(![...storage.values()].includes("mot de passe"));
  assert.equal($("ptt").disabled, false); assert.equal($("sec-connect").open, false); assert.equal($("disconnect").disabled, false);
  assert.deepEqual($("mem-mode").options.map((o) => o.value), ["PKTUSB", "PKTLSB", "USB", "LSB"]);       // modes données d'abord
  assert.equal($("mem-mode").options[0].textContent, "USB-D (données)");
  assert.deepEqual($("mode-buttons").children.map((b) => b.textContent), ["USB-D", "LSB-D", "USB", "LSB"]);   // un bouton par mode, même ordre
});

step("afficheur : fréquence, mode, S-mètre, puissance, indicateurs, squelch", async () => {
  state();
  assert.equal(freqText(), "14.200.00"); assert.equal($("mode-pill").textContent, "USB");
  assert.equal($("ctl-pwr").hidden, false); assert.equal($("ctl-pwr").textContent, "PWR 50W");                     // puissance d'émission, en watts
  assert.equal($("smeter-text").textContent, "S7"); assert.equal($("smeter-mask").style.width, "63%");        // (−12+54)/114 = 37 % rempli
  assert.equal($("po-text").textContent, "0 %"); assert.equal($("po-mask").style.width, "100%");
  assert.equal($("ctl-nr").hidden, false); assert.equal($("ctl-nr").className, "chip");
  assert.equal($("ctl-nb").className, "chip on"); assert.equal($("ctl-preamp").textContent, "P.AMP 10"); assert.equal($("ctl-preamp").className, "chip on");
  assert.equal($("ctl-aip").hidden, false); assert.equal($("ctl-aip").className, "chip"); assert.equal($("ctl-agc").textContent, "AGC-F");
  assert.equal($("ctl-comp").hidden, false); assert.equal($("ctl-tuner").hidden, false); assert.equal($("ctl-fil").textContent, "FIL 2.4k");
  assert.ok(["nr", "nb", "preamp", "aip", "agc", "comp", "fil", "tuner"].every((k) => $("ctl-" + k).disabled === false));
  assert.equal($("ptt").textContent, "PTT");                                                                    // le bouton s'appelle PTT
  assert.equal($("sql-marker").hidden, false); assert.match($("sql-marker").style.left, /^\d+(\.\d)?%$/);           // repère du squelch (25 %)
  assert.equal($("swr-text").textContent, "1.2"); assert.equal($("alc-text").textContent, "0 %");
  assert.equal($("squelch").disabled, false); assert.equal($("squelch").value, "25"); assert.equal($("squelch-text").textContent, "25 %");
  assert.equal($("tx-flag").hidden, true); assert.equal($("ptt-state").textContent, "RÉCEPTION");
  assert.ok($("instruments").children.length >= 3 && $("instruments-empty").hidden === true);
  assert.equal($("mode-hint").hidden, false);                                                                  // USB : indice du mode données
  assert.match($("mode-hint").textContent, /USB-D/);
});

step("mémoires : liste triée (favorite d'abord), mémoire en cours repérée", async () => {
  const items = $("mem-list").children;
  assert.equal(items.length, 3); assert.equal($("mem-count").textContent, "(3)"); assert.equal($("mem-empty").hidden, true);
  const names = items.map((li) => li.children[1].children[0].textContent);
  assert.deepEqual(names, ["Quatre-vingts", "Quarante", "Vingt"]);              // ordre de la station : favorite, puis fréquence
  assert.match(items[0].className, /fav/); assert.equal(items[0].children[0].textContent, "★"); assert.equal(items[2].children[0].textContent, "☆");
  assert.equal(items[2].children[1].children[1].textContent, "14.200.00"); assert.equal(items[1].children[1].children[2].textContent, "USB-D");
  assert.match(items[2].className, /active/);                                    // 14.200.00 USB = l'état actuel du poste
  assert.doesNotMatch(items[1].className, /active/);
});

step("mémoires : rappel, favori, ajout, modification, suppression en deux temps", async () => {
  const items = () => $("mem-list").children;
  let pending = items()[1].children[1].click(); await wait();                      // rappeler « Quarante »
  assert.equal(sent("memory_recall").at(-1).memory_id, "m3"); answer(true); await pending;
  pending = items()[2].children[0].click(); await wait();                          // étoile de « Vingt »
  const fav = sent("memory_save").at(-1);
  assert.deepEqual([fav.memory_id, fav.name, fav.hz, fav.mode, fav.favorite], ["m2", "Vingt", 14200000, "USB", true]); answer(true); await pending;

  await $("mem-add-current").click();                                              // mémoriser la fréquence actuelle
  assert.equal($("mem-form").hidden, false); assert.equal($("mem-name").value, ""); assert.equal($("mem-khz").value, "14200");
  assert.equal($("mem-mode").value, "USB"); assert.equal($("mem-delete").hidden, true); assert.equal($("mem-name").focused, true);
  await $("mem-save").click();                                                     // sans nom : refusé côté page
  assert.equal(sent("memory_save").length, 1);
  $("mem-name").value = "Essai 20 m"; $("mem-khz").value = "14 205,5"; $("mem-fav").checked = true;
  const saving = $("mem-save").click(); await wait();
  const created = sent("memory_save").at(-1);
  assert.deepEqual([created.name, created.hz, created.mode, created.favorite, "memory_id" in created], ["Essai 20 m", 14205500, "USB", true, false]);
  answer(true); await saving; await wait();
  assert.equal($("mem-form").hidden, true);

  await items()[0].children[2].click();                                            // modifier la première
  assert.equal($("mem-form").hidden, false); assert.equal($("mem-name").value, "Quatre-vingts"); assert.equal($("mem-khz").value, "3700");
  assert.equal($("mem-fav").checked, true); assert.equal($("mem-delete").hidden, false);
  await $("mem-delete").click();                                                   // 1er appui : demande confirmation, rien n'est envoyé
  assert.equal($("mem-delete").textContent, "Confirmer la suppression"); assert.equal(sent("memory_delete").length, 0);
  const deleting = $("mem-delete").click(); await wait();                          // 2e appui : suppression
  assert.equal(sent("memory_delete").at(-1).memory_id, "m1"); answer(true); await deleting; await wait();
  assert.equal($("mem-form").hidden, true); assert.equal($("mem-delete").textContent, "Supprimer");
  await $("mem-add-current").click(); await $("mem-cancel").click();
  assert.equal($("mem-form").hidden, true);
});

step("mémoires : un refus de la station est expliqué dans le journal", async () => {
  send({ type: "memories", items: MEMORIES });
  const pending = $("mem-list").children[0].children[1].click(); await wait();
  answer(false, { reason: "tx_active" }); await pending; await wait();
  assert.match($("log").children[0].textContent, /pendant l'émission/); assert.match($("log").children[0].className, /warn/);
});

step("mémoires : la liste d'un autre appareil remplace l'affichage", async () => {
  send({ type: "memories", items: [{ id: "z9", name: "Autre", hz: 28400000, mode: "USB", favorite: false }] });
  assert.equal($("mem-list").children.length, 1); assert.equal($("mem-count").textContent, "(1)");
  send({ type: "memories", items: [] });
  assert.equal($("mem-list").children.length, 0); assert.equal($("mem-empty").hidden, false);
});

step("squelch : une seule commande à la fin du geste, jamais écrasé pendant le réglage", async () => {
  for (const v of ["30", "35", "40"]) { $("squelch").value = v; await $("squelch").dispatch("input"); }
  assert.equal($("squelch-text").textContent, "40 %"); assert.equal(sent("set_squelch").length, 0);
  await wait(250);
  assert.equal(sent("set_squelch").length, 1); assert.equal(sent("set_squelch")[0].value, 0.4); answer(true);
  state();                                                                         // la station annonce encore 25 % : pas de saut du curseur
  assert.equal($("squelch").value, "40");
  $("squelch").value = "0"; await $("squelch").dispatch("input");
  assert.equal($("squelch-text").textContent, "ouvert");
  await wait(250);                                                                 // la commande part à la fin du geste : on l'attend et on y répond
  assert.equal(sent("set_squelch").at(-1).value, 0); answer(true, {}, "set_squelch");
});

step("émission : la case reste cochée après la fin de l'émission", async () => {
  $("armed").checked = true; await $("armed").dispatch("change");
  const pressing = $("ptt").click(); await wait();
  assert.equal(sent("toggle").length, 1); answer(true); await pressing;
  state({ state: "TX", owner: "phone", tot_remaining_s: 80 }, { levels: { RFPOWER_METER: 0.5, SWR: 1.4, PREAMP: 10, SQL: 0.25 } });
  assert.equal($("tx-flag").hidden, false); assert.equal($("ptt").className, "ptt tx"); assert.equal($("ptt").textContent, "PTT — COUPER");
  assert.equal($("swr-text").textContent, "1.4"); assert.equal($("swr-mask").style.width, "80%");                 // ROS 1.4 : (1,4−1)/2 = 20 % rempli
  assert.ok(["nr", "nb", "preamp", "aip", "agc", "comp", "fil", "tuner", "pwr"].every((k) => $("ctl-" + k).disabled === true));   // verrouillés en émission
  assert.equal($("po-text").textContent, "50 %"); assert.equal($("po-mask").style.width, "50%");
  assert.equal($("ptt-state").className, "ptt-state tx"); assert.match($("tot").textContent, /80 s/);
  state({ state: "RX" });
  assert.equal($("tx-flag").hidden, true); assert.equal($("armed").checked, true);          // toujours cochée
  assert.equal($("ptt").disabled, false); assert.equal($("ptt").textContent, "PTT");
});

step("boutons de commande : un appui envoie la bonne commande, les cycles suivent le poste", async () => {
  let pending = $("ctl-nr").click(); await wait(320);                                                        // NR/NB : attente d'un éventuel double clic
  assert.deepEqual([sent("set_function").at(-1).name, sent("set_function").at(-1).on], ["NR", true]); answer(true); await pending;
  pending = $("ctl-nb").click(); await wait(320);
  assert.deepEqual([sent("set_function").at(-1).name, sent("set_function").at(-1).on], ["NB", false]); answer(true); await pending;
  pending = $("ctl-tuner").click(); await wait();
  assert.deepEqual([sent("set_function").at(-1).name, sent("set_function").at(-1).on], ["TUNER", true]); answer(true); await pending;
  pending = $("ctl-comp").click(); await wait(); assert.equal(sent("set_function").at(-1).name, "COMP"); answer(true); await pending;
  pending = $("ctl-aip").click(); await wait(); assert.equal(sent("set_function").at(-1).name, "AIP"); answer(true); await pending;
  pending = $("ctl-preamp").click(); await wait();                                                              // 10 dB -> 20 dB
  assert.deepEqual([sent("set_level").at(-1).name, sent("set_level").at(-1).value], ["PREAMP", 20]); answer(true); await pending;
  pending = $("ctl-agc").click(); await wait();                                                                 // RAPIDE -> MOYEN
  assert.deepEqual([sent("set_level").at(-1).name, sent("set_level").at(-1).value], ["AGC", 5]); answer(true); await pending;
  pending = $("ctl-fil").click(); await wait();                                                                 // 2.4k -> 1.8k
  assert.deepEqual([sent("set_mode").at(-1).mode, sent("set_mode").at(-1).passband], ["USB", 1800]); answer(true); await pending;
  pending = $("ctl-pwr").click(); await wait();                                                                 // 50 % -> 80 %
  assert.deepEqual([sent("set_level").at(-1).name, sent("set_level").at(-1).value], ["RFPOWER", 0.8]); answer(true); await pending;
  pending = $("ctl-nr").click(); await wait(320); answer(false, { reason: "tx_active" }); await pending; await wait();   // refus affiché en français
  assert.match($("log").children[0].textContent, /pendant l'émission/);
});

step("ATT, NOTCH et fenêtre de réglage (double clic ou appui long) de NR, NB et Notch", async () => {
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB"], attenuators: [20],
         level_ranges: { NR: [0, 1, 0.0667], NB: [0, 10, 1] } }, tx_modes: [], max_power_w: 100, memories: [] });
  state({}, { functions: { NR: true, NB: false, ANF: false, MN: false }, levels: { ATT: 0, NR: 0.4, NB: 5, PREAMP: 0, AGC: 2 } });
  assert.equal($("ctl-att").hidden, false); assert.equal($("ctl-att").textContent, "ATT");
  assert.equal($("ctl-notch").hidden, false); assert.equal($("ctl-notch").textContent, "NOTCH");
  await $("ctl-att").click(); await wait();
  assert.deepEqual([sent("set_level").at(-1).name, sent("set_level").at(-1).value], ["ATT", 20]); answer(true, {}, "set_level"); await wait();
  await $("ctl-notch").click(); await wait(320);                                                          // arrêt -> automatique
  assert.deepEqual([sent("set_function").at(-1).name, sent("set_function").at(-1).on], ["ANF", true]); answer(true, {}, "set_function"); await wait();
  state({}, { functions: { NR: true, NB: false, ANF: true, MN: false }, levels: { ATT: 20, NR: 0.4, NB: 5, PREAMP: 0, AGC: 2 } });
  assert.equal($("ctl-att").textContent, "ATT 20"); assert.equal($("ctl-notch").textContent, "NOTCH A");
  // double clic sur NR : fenêtre, sans bascule
  const toggles = sent("set_function").length;
  await $("ctl-nr").click(); await $("ctl-nr").click(); await wait(320);
  assert.equal($("ctl-dialog").hidden, false); assert.equal($("ctl-dialog-title").textContent, "Réducteur de bruit (NR)");
  assert.equal(sent("set_function").length, toggles);                                                     // pas de bascule
  assert.equal($("ctl-level-row").hidden, false); assert.equal($("ctl-level-text").textContent, "6 / 15");
  $("ctl-level").value = "0.8"; await $("ctl-level").dispatch("input"); await wait(220);
  assert.deepEqual([sent("set_level").at(-1).name, sent("set_level").at(-1).value], ["NR", 0.8]); answer(true, {}, "set_level"); await wait();
  await $("ctl-dialog-close").click(); assert.equal($("ctl-dialog").hidden, true);
  // appui long sur NOTCH : fenêtre ; « Manuel » éteint l'automatique puis allume le manuel
  await $("ctl-notch").dispatch("pointerdown"); await wait(600); await $("ctl-notch").dispatch("pointerup"); await $("ctl-notch").click(); await wait(320);
  assert.equal($("ctl-dialog").hidden, false); assert.equal($("ctl-notch-row").hidden, false); assert.equal($("ctl-notch-auto").className, "chip on");
  const before = sent("set_function").length;
  const manual = $("ctl-notch-manual").click(); await wait();
  assert.deepEqual([sent("set_function").at(-1).name, sent("set_function").at(-1).on], ["ANF", false]); answer(true, {}, "set_function"); await wait();
  assert.deepEqual([sent("set_function").at(-1).name, sent("set_function").at(-1).on], ["MN", true]); answer(true, {}, "set_function"); await manual;
  assert.equal(sent("set_function").length, before + 2);                                                  // l'appui long n'a rien basculé
  state({ state: "TX", owner: "phone" }, { functions: { NR: true, NB: false, ANF: false, MN: true }, levels: { ATT: 20, NR: 0.8, NB: 5 } });
  assert.equal($("ctl-notch-off").disabled, true); assert.match($("ctl-dialog-note").textContent, /verrouillés pendant l'émission/);
  state({}, { functions: { NR: true, NB: false, ANF: false, MN: true }, levels: { ATT: 20, NR: 0.8, NB: 5 } });
  await $("ctl-dialog-close").click();
});

step("repère de squelch : visible seulement si le squelch est activé, il suit le réglage", async () => {
  state({}, { levels: { SQL: 0, PREAMP: 10, AGC: 2 } });
  assert.equal($("sql-marker").hidden, true);                                                                    // squelch ouvert : pas de repère
  state({}, { levels: { SQL: 120 / 255, PREAMP: 10, AGC: 2 } });
  assert.equal($("sql-marker").hidden, false); assert.equal($("sql-marker").style.left, "47.4%");                 // S9
  state({}, { levels: { SQL: 0.9, PREAMP: 10, AGC: 2 } });
  assert.ok(parseFloat($("sql-marker").style.left) > 90);
  state({}, { levels: { PREAMP: 10, AGC: 2 } });                                                                 // poste sans squelch lisible
  assert.equal($("sql-marker").hidden, true); assert.equal($("squelch").disabled, true);
});

step("graphiques SWR et ALC : remplis en émission, vides en réception", async () => {
  state({ state: "TX", owner: "phone" }, { levels: { RFPOWER_METER: 0.5, SWR: 2, ALC: 0.35, PREAMP: 10, SQL: 0.25 } });
  assert.equal($("swr-text").textContent, "2.0"); assert.equal($("swr-mask").style.width, "50%");
  assert.equal($("alc-text").textContent, "35 %"); assert.equal($("alc-mask").style.width, "65%");
  state({ state: "RX" }, { levels: { PREAMP: 10, SQL: 0.25 } });                                                 // les mesures d'émission disparaissent du poste
  assert.equal($("swr-text").textContent, "—"); assert.equal($("swr-mask").style.width, "100%");
  assert.equal($("alc-text").textContent, "—"); assert.equal($("alc-mask").style.width, "100%");
  assert.equal($("po-text").textContent, "—");
});

step("restriction d'émission aux modes données : bouton bloqué avec explication", async () => {
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "PKTUSB"] }, tx_modes: ["PKTUSB"], memories: [] });
  state();
  assert.equal($("ptt").disabled, true); assert.match($("mode-hint").textContent, /Émission impossible en USB/);
  state({}, { mode: "PKTUSB" });
  assert.equal($("ptt").disabled, false); assert.equal($("mode-hint").hidden, true); assert.equal($("mode-pill").textContent, "USB-D");
});

step("affichage : taille du texte et disposition mémorisées, paysage proposé", async () => {
  $("layout-select").value = "landscape"; await $("layout-select").dispatch("change");
  assert.equal($("app").className, "landscape"); assert.equal(storage.get("trx.layout"), "landscape");
  $("layout-select").value = "auto"; await $("layout-select").dispatch("change");
  assert.equal($("app").className, "portrait");
  landscape = true; globalThis.innerWidth = 860;
  await Promise.all(windowHandlers.resize.map((fn) => fn()));                       // téléphone couché : paysage automatique
  assert.equal($("app").className, "landscape");
  landscape = false; await Promise.all(windowHandlers.orientationchange.map((fn) => fn()));
  assert.equal($("app").className, "portrait");
  $("text-size").value = "l"; await $("text-size").dispatch("change");
  assert.equal(document.documentElement.getAttribute("data-text"), "l"); assert.equal(storage.get("trx.text"), "l");
  $("text-size").value = "auto"; await $("text-size").dispatch("change");
  assert.equal(document.documentElement.getAttribute("data-text"), null);
});

step("fréquence : glisser un chiffre règle la fréquence, UNE seule commande part à la fin du geste", async () => {
  state({}, { frequency_hz: 7074000 });
  assert.equal(freqText(), "7.074.00"); layoutDigits();
  assert.deepEqual($("freq").children.map((c) => c.className), ["dig", "sep", "dig", "dig", "dig", "sep", "dig", "dig"]);
  await $("freq").dispatch("pointerdown", { clientX: 89, clientY: 300, pointerId: 1 });                                  // chiffre des kHz (le « 4 »)
  assert.equal($("freq").children[4].className, "dig active"); assert.equal($("freq").captured, 1);
  await $("freq").dispatch("pointermove", { clientX: 89, clientY: 255, pointerId: 1 });                                  // 45 px vers le haut : 2 crans
  assert.equal(freqText(), "7.076.00"); assert.match($("freq").className, /pending/);                                    // l'affichage suit tout de suite
  await $("freq").dispatch("pointermove", { clientX: 89, clientY: 300, pointerId: 1 });                                  // retour : on annule
  assert.equal(freqText(), "7.074.00");
  await $("freq").dispatch("pointermove", { clientX: 89, clientY: 255, pointerId: 1 });
  await $("freq").dispatch("pointermove", { clientX: 89, clientY: 233, pointerId: 1 });                                  // 67 px : 3 crans
  assert.equal(freqText(), "7.077.00"); assert.equal(sent("set_frequency").length, 0);                                    // rien n'est parti pendant le geste
  await $("freq").dispatch("pointerup", { pointerId: 1 });
  assert.equal($("freq").children[4].className, "dig"); assert.equal($("keypad").hidden, true);                         // un geste n'ouvre pas le clavier
  await wait(250);
  assert.equal(sent("set_frequency").length, 1); assert.equal(sent("set_frequency")[0].hz, 7077000); answerAll(); await wait();
  state({}, { frequency_hz: 7077000 });
  assert.doesNotMatch($("freq").className, /pending/); assert.equal(freqText(), "7.077.00");
  await $("freq").dispatch("pointerdown", { clientX: 2 * 20 + 9, clientY: 300, pointerId: 2 });                          // chiffre des centaines de kHz
  await $("freq").dispatch("pointermove", { clientX: 49, clientY: 340, pointerId: 2 });                                  // vers le bas : -1 cran
  assert.equal(freqText(), "6.977.00"); await $("freq").dispatch("pointerup", { pointerId: 2 });
  await wait(250); answerAll(); await wait(); state({}, { frequency_hz: 6977000 });
  await $("freq").dispatch("pointerdown", { clientX: 20 + 3, clientY: 300, pointerId: 3 });                              // sur le point : le chiffre voisin le plus proche
  assert.ok($("freq").children.some((c) => c.className === "dig active")); await $("freq").dispatch("pointercancel", { pointerId: 3 });
  assert.ok($("freq").children.every((c) => c.className !== "dig active"));
  await $("freq").dispatch("wheel", { clientX: 89, deltaY: -120 });                                                       // molette vers le haut : +1 kHz
  assert.equal(freqText(), "6.978.00");
  await wait(250); answerAll(); await wait(); state({}, { frequency_hz: 6978000 });
  await $("freq").dispatch("wheel", { clientX: 89, deltaY: 120 });
  assert.equal(freqText(), "6.977.00"); await wait(250); answerAll(); await wait(); state({}, { frequency_hz: 6977000 });
});

step("fréquence : un appui court ouvre le clavier, saisie, aperçu et validation", async () => {
  state({}, { frequency_hz: 7074000 }); layoutDigits();
  await $("freq").dispatch("pointerdown", { clientX: 89, clientY: 300, pointerId: 4 });
  await $("freq").dispatch("pointerup", { pointerId: 4 });                                                               // aucun mouvement : un appui
  assert.equal($("keypad").hidden, false); assert.equal($("kp-display").textContent, "—"); assert.equal($("kp-ok").disabled, true);
  await $("keypad").dispatch("click", { target: $("keypad") });                                                          // le « clic fantôme » du toucher ne referme pas le pavé
  await $("kp-keys").children[0].click(); await $("kp-cancel").click();
  assert.equal($("keypad").hidden, false); assert.equal($("kp-display").textContent, "—");                              // ni touche, ni annulation dans les premiers instants
  await wait(480);
  assert.equal($("kp-keys").children.length, 12); assert.deepEqual($("kp-keys").children.map((b) => b.textContent), ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"]);
  const key = (k) => $("kp-keys").children.find((b) => b.textContent === k).click();
  for (const k of ["7", "0", "7", "4"]) await key(k);
  assert.equal($("kp-display").textContent, "7074"); assert.match($("kp-preview").textContent, /^7\.074\.00 {2}= {2}7074 kHz$/); assert.equal($("kp-ok").disabled, false);
  await key("⌫"); await key("⌫"); await key("."); await key(".");
  assert.equal($("kp-display").textContent, "70.."); assert.equal($("kp-preview").textContent, "Valeur incorrecte"); assert.equal($("kp-ok").disabled, true);
  for (let i = 0; i < 4; i++) await key("⌫");                                                                            // « 70.. » -> vide
  assert.equal($("kp-display").textContent, "—");
  for (const k of ["1", "4", ".", "2", "0", "5"]) await key(k);                                                          // 14.205 : MHz
  assert.match($("kp-preview").textContent, /^14\.205\.00/);
  await documentHandlers.keydown[0]({ key: "Backspace" }); await documentHandlers.keydown[0]({ key: "," }); await documentHandlers.keydown[0]({ key: "5" });   // clavier physique
  assert.equal($("kp-display").textContent, "14.20.5"); assert.equal($("kp-ok").disabled, true);
  await documentHandlers.keydown[0]({ key: "Backspace" }); await documentHandlers.keydown[0]({ key: "Backspace" }); await documentHandlers.keydown[0]({ key: "5" });
  assert.equal($("kp-display").textContent, "14.205");
  const confirming = $("kp-ok").click(); await wait();
  assert.equal(sent("set_frequency").at(-1).hz, 14205000); answerAll(); await confirming; await wait();
  assert.equal($("keypad").hidden, true);
  await $("freq").dispatch("pointerdown", { clientX: 89, clientY: 300, pointerId: 5 }); await $("freq").dispatch("pointerup", { pointerId: 5 });
  assert.equal($("keypad").hidden, false); await wait(480);
  await $("keypad").dispatch("click", { target: $("keypad") });                                                          // un appui à côté du pavé le ferme
  assert.equal($("keypad").hidden, true);
  await $("freq").dispatch("pointerdown", { clientX: 89, clientY: 300, pointerId: 6 }); await $("freq").dispatch("pointerup", { pointerId: 6 });
  await documentHandlers.keydown[0]({ key: "Escape" }); assert.equal($("keypad").hidden, true);
  await $("freq").dispatch("pointerdown", { clientX: 89, clientY: 300, pointerId: 8 }); await $("freq").dispatch("pointerup", { pointerId: 8 });
  await wait(480); await $("kp-cancel").click(); assert.equal($("keypad").hidden, true);                                // le bouton Annuler ferme aussi le pavé
});

step("fréquence : verrouillée pendant l'émission (ni geste, ni clavier, ni molette)", async () => {
  state({ state: "TX", owner: "phone" }, { frequency_hz: 7074000 }); layoutDigits();
  assert.match($("freq").className, /locked/);
  await $("freq").dispatch("pointerdown", { clientX: 89, clientY: 300, pointerId: 7 });
  await $("freq").dispatch("pointermove", { clientX: 89, clientY: 255, pointerId: 7 });
  await $("freq").dispatch("pointerup", { pointerId: 7 });
  await $("freq").dispatch("wheel", { clientX: 89, deltaY: -120 });
  assert.equal($("keypad").hidden, true); assert.equal(freqText(), "7.074.00"); await wait(250);
  assert.equal(sent("set_frequency").filter((m) => m.hz === 7075000 || m.hz === 7076000).length, 0);
  assert.ok(["step-up", "step-down"].every((id) => $(id).disabled === false));                                          // boutons de pas : refusés par la page à l'appui
  assert.ok($("bands").children.every((b) => b.disabled === true));                                                      // boutons de bande grisés en émission
  assert.ok($("mode-buttons").children.every((b) => b.disabled === true));                                               // boutons de mode aussi
  state({ state: "RX" }, { frequency_hz: 7074000 });
});

step("cluster DX : section affichée dès que le module donne l'état de ses flux", async () => {
  assert.equal($("sec-cluster").hidden, true);                                                        // pas de module : rien
  send({ type: "module", module: "cluster", data: { kind: "cluster_status", health: "green",
         sources: [{ name: "RBN", type: "rbn", verdict: "ok", last_10min: 120, last_spot_age_s: 3 }] } });
  assert.equal($("sec-cluster").hidden, false); assert.equal($("cluster-dot").className, "cluster-dot green");
  assert.equal($("cluster-title").textContent, "Les flux arrivent");
  assert.equal($("cluster-sources").children.length, 1); assert.match($("cluster-sources").children[0].children[1].textContent, /12 spots\/min/);
  assert.ok(!$("log").children.some((li) => /cluster_status/.test(li.textContent)));                // jamais au journal
});

step("signaler un problème : rapport préparé, relu à l'écran, puis envoyé à la station", async () => {
  assert.equal($("bug-report").hidden, true); assert.equal($("bug-send").disabled, true);
  $("bug-text").value = "Le spectre se fige";
  await $("bug-prepare").click();
  assert.equal($("bug-report").hidden, false); assert.match($("bug-report").textContent, /Le spectre se fige/);
  assert.equal($("bug-send").disabled, false); assert.equal($("bug-share").disabled, false);
  const before = sent("bug_report").length;
  await $("bug-send").click(); await wait();
  assert.equal(sent("bug_report").length, before + 1); assert.equal(sent("bug_report").at(-1).text, $("bug-report").textContent);
  answer(true, { name: "page-1.txt" }, "bug_report"); await wait();
});

step("poste utilisé sur place : bandeau, reprise de la main en deux appuis, impossible pendant l'émission locale", async () => {
  assert.equal($("local-banner").hidden, true);
  state({ local_remaining_s: 120, local_reason: "tx", local_tx: true });
  assert.equal($("local-banner").hidden, false); assert.match($("local-text").textContent, /micro du poste/);
  assert.equal($("local-release").disabled, true);                                       // il parle : pas de reprise
  state({ local_remaining_s: 95, local_reason: "tx", local_tx: false });
  assert.equal($("local-release").disabled, false); assert.match($("local-text").textContent, /encore 1:35/);
  const before = sent("local_release").length;
  await $("local-release").click();
  assert.equal(sent("local_release").length, before); assert.equal($("local-release").textContent, "Confirmer : reprendre la main");
  await $("local-release").click(); await wait();
  assert.equal(sent("local_release").length, before + 1); assert.equal($("local-release").textContent, "Reprendre la main");
  answer(true, {}, "local_release"); await wait();
  state({});
  assert.equal($("local-banner").hidden, true);                                          // station : de nouveau libre
});

step("modes : un appui sur un bouton change le mode, le mode du poste est allumé", async () => {
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB", "PKTUSB", "PKTLSB"] }, tx_modes: [], max_power_w: 100, memories: [] });
  state({}, { frequency_hz: 7074000, mode: "PKTLSB" });
  assert.deepEqual($("mode-buttons").children.filter((b) => b.className === "chip on").map((b) => b.textContent), ["LSB-D"]);
  assert.ok($("mode-buttons").children.every((b) => b.disabled === false));
  const before = sent("set_mode").length;
  const change = $("mode-buttons").children.find((b) => b.textContent === "USB-D").click(); await wait();
  assert.equal(sent("set_mode").length, before + 1);
  assert.deepEqual([sent("set_mode").at(-1).mode, sent("set_mode").at(-1).passband], ["PKTUSB", 0]);
  answer(true, {}, "set_mode"); await change;
  state({}, { frequency_hz: 7074000, mode: "PKTUSB" });
  assert.deepEqual($("mode-buttons").children.filter((b) => b.className === "chip on").map((b) => b.textContent), ["USB-D"]);
});

step("bandes : quatorze boutons (dont 85, 45 et 11), bande en cours repérée, rappel du mode puis de la fréquence", async () => {
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB", "PKTUSB", "PKTLSB"] }, tx_modes: [], max_power_w: 100, memories: [] });   // modes libres
  assert.deepEqual($("bands").children.map((b) => b.textContent), ["160", "85", "80", "60", "45", "40", "30", "20", "17", "15", "12", "11", "10", "6"]);
  state({}, { frequency_hz: 14200000, mode: "USB" });
  assert.deepEqual($("bands").children.filter((b) => b.className === "chip on").map((b) => b.textContent), ["20"]);
  assert.ok($("bands").children.every((b) => b.disabled === false));
  state({}, { frequency_hz: 7500000, mode: "USB" });
  assert.equal($("bands").children.filter((b) => b.className === "chip on").length, 0);                               // hors bande amateur : aucune
  state({}, { frequency_hz: 7080000, mode: "USB" });                                                                   // on s'arrête sur 7,080 MHz USB...
  await wait(1700); state({}, { frequency_hz: 7080000, mode: "USB" });                                                // ... assez longtemps : la bande des 40 m s'en souvient
  assert.deepEqual(JSON.parse(storage.get("trx.bands"))["40"], { hz: 7080000, mode: "USB" });
  state({}, { frequency_hz: 14200000, mode: "USB" });
  const goto80 = $("bands").children.find((b) => b.textContent === "80").click(); await wait();                        // bande jamais visitée : point de départ usuel
  assert.deepEqual([sent("set_mode").at(-1).mode, sent("set_mode").at(-1).passband], ["LSB", 0]);                     // LSB en dessous de 10 MHz
  answerAll(); await wait();
  assert.equal(sent("set_frequency").at(-1).hz, 3700000); answerAll(); await goto80;
  state({}, { frequency_hz: 3700000, mode: "LSB" });
  assert.deepEqual($("bands").children.filter((b) => b.className === "chip on").map((b) => b.textContent), ["80"]);
  const goto40 = $("bands").children.find((b) => b.textContent === "40").click(); await wait();                        // bande déjà utilisée : sa dernière fréquence ET son dernier mode
  assert.deepEqual([sent("set_mode").at(-1).mode, sent("set_mode").at(-1).passband], ["USB", 0]);
  answerAll(); await wait(); assert.equal(sent("set_frequency").at(-1).hz, 7080000); answerAll(); await goto40;
  state({}, { frequency_hz: 7080000, mode: "USB" });
  assert.deepEqual($("bands").children.filter((b) => b.className === "chip on").map((b) => b.textContent), ["40"]);
  for (const [band, mode, hz] of [["85", "PKTLSB", 3450000], ["45", "PKTLSB", 6660000], ["11", "USB", 27430000]]) {                            // bandes ajoutées : point de départ demandé
    const go = $("bands").children.find((b) => b.textContent === band).click(); await wait();
    assert.equal(sent("set_mode").at(-1).mode, mode);
    answerAll(); await wait(); assert.equal(sent("set_frequency").at(-1).hz, hz); answerAll(); await go;
    state({}, { frequency_hz: hz, mode: mode });
    assert.deepEqual($("bands").children.filter((b) => b.className === "chip on").map((b) => b.textContent), [band]);
  }
});

step("pas de fréquence : un appui = un pas, maintenu = répétition, relâché = arrêt", async () => {
  state({}, { frequency_hz: 7074000, mode: "LSB" });
  assert.equal($("step-select").options.length, 9); assert.equal($("step-select").value, "1000");
  $("step-select").value = "5000"; await $("step-select").dispatch("change", { target: $("step-select") });
  assert.equal(storage.get("trx.step"), "5000");
  await $("step-up").dispatch("pointerdown"); await $("step-up").dispatch("pointerup");                                // un appui court
  await wait(250); assert.equal(sent("set_frequency").at(-1).hz, 7079000); answerAll(); await wait(); state({}, { frequency_hz: 7079000 });
  await $("step-down").dispatch("pointerdown"); await $("step-down").dispatch("pointerup");
  await wait(250); assert.equal(sent("set_frequency").at(-1).hz, 7074000); answerAll(); await wait(); state({}, { frequency_hz: 7074000 });
  const station = setInterval(answerAll, 25);                                                                           // la station répond aux commandes au fil de l'eau
  await $("step-up").dispatch("pointerdown");                                                                           // maintenu : après 400 ms, un pas toutes les 120 ms
  await wait(720); await $("step-up").dispatch("pointerleave");
  const held = sent("set_frequency").at(-1).hz;
  assert.ok(held >= 7074000 + 3 * 5000, "au moins 3 pas pendant l'appui : " + held);
  await wait(450); answerAll(); await wait(); clearInterval(station);
  const settled = sent("set_frequency").at(-1).hz; await wait(400);
  assert.equal(sent("set_frequency").at(-1).hz, settled);                                                               // relâché : plus aucun pas
  await $("step-up").dispatch("click", { detail: 0 });                                                                  // clavier : un pas
  await wait(250); answerAll(); await wait();
  assert.ok(sent("set_frequency").at(-1).hz > settled);
  state({}, { frequency_hz: sent("set_frequency").at(-1).hz }); $("step-select").value = "1000"; await $("step-select").dispatch("change", { target: $("step-select") });
});

step("waterfall : bascule par appui ou double appui, boutons, grille en kHz, pics, mesures d'émission en superposition", async () => {
  pcs.at(-1).ontrack({ track: {}, streams: [{}] });                                                                       // l'audio de la station arrive
  assert.equal(sources.length, 1); assert.equal(analysers.length, 1); assert.equal(analysers[0].fftSize, 4096); assert.equal(sources[0].target, analysers[0]);
  assert.equal($("waterfall").hidden, true); assert.equal($("txzone").hidden, false); assert.equal(rafQueue.length, 0);       // fermé : aucun calcul
  await $("txzone").dispatch("click"); await $("txzone").dispatch("click");                                              // un double appui ne bascule qu'UNE fois
  assert.equal($("waterfall").hidden, false); assert.equal($("txzone").hidden, true); assert.equal(rafQueue.length, 1);
  assert.deepEqual($("wf-axis").children.map((c) => c.textContent), ["0", "0.5", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5"]);
  assert.equal($("wf-axis").children[2].style.left, "20.00%"); assert.equal($("wf-axis").children[10].style.left, "100.00%");
  assert.deepEqual([$("wf-speed").textContent, $("wf-width").textContent, $("wf-gain").textContent, $("wf-peak").textContent], ["VIT 12", "LARG 5k", "GAIN 0", "PIC 2s"]);
  assert.ok($("wf-fall").ctx.count("putImageData") === 0);
  assert.ok(runFrames([100, 200, 300]));                                                                                  // trois images à 12 lignes par seconde
  assert.ok($("wf-fall").ctx.count("putImageData") >= 3 && $("wf-fall").ctx.count("drawImage") >= 3);
  const row = $("wf-fall").ctx.lastRow;
  assert.equal(row.width, 480); assert.ok(row.data.some((v, i) => i % 4 === 0 && v > 150));                              // la raie de 1 500 Hz est claire
  assert.match($("wf-peakinfo").textContent, /^pic 1\.(49|50|51)$/); assert.ok($("wf-spec").ctx.count("stroke") >= 6);
  assert.ok(rafQueue.length === 1);                                                                                       // la boucle continue
  assert.ok(analysers[0].reads >= 3);
  const lines = $("wf-fall").ctx.count("putImageData");
  runFrames([310]); assert.equal($("wf-fall").ctx.count("putImageData"), lines);                                          // image trop proche : pas de nouvelle ligne
  // vitesse : plus rapide = plus de lignes par image
  await $("wf-speed").click(); await $("wf-speed").click();
  assert.equal($("wf-speed").textContent, "VIT 50");
  const before = $("wf-fall").ctx.count("putImageData"); runFrames([1000, 1060]);
  assert.ok($("wf-fall").ctx.count("putImageData") - before >= 2);
  for (const [id, expected] of [["wf-speed", ["VIT 3", "VIT 6", "VIT 12"]], ["wf-gain", ["GAIN +6", "GAIN +12", "GAIN +18", "GAIN -12", "GAIN -6", "GAIN 0"]],
                                ["wf-peak", ["PIC 5s", "PIC MAX", "PIC OFF", "PIC 0.5s", "PIC 2s"]]]) {
    for (const label of expected) { await $(id).click(); assert.equal($(id).textContent, label); }
  }
  await $("wf-peak").click(); await $("wf-peak").click(); assert.equal($("wf-peak").textContent, "PIC MAX");                // maintien : le tracé des pics est conservé
  assert.deepEqual(JSON.parse(storage.get("trx.wf")), { speed: 12, width: 5000, gain: 0, peak: 4 });                      // réglages mémorisés (le maintien par son rang)
  const gridCalls = $("wf-grid").ctx.count("stroke");
  for (const [label, count, last] of [["LARG 3k", 7, "3"], ["LARG 2.5k", 6, "2.5"], ["LARG 2k", 5, "2"], ["LARG 1k", 3, "1"], ["LARG 5k", 11, "5"]]) {
    await $("wf-width").click(); assert.equal($("wf-width").textContent, label);
    assert.equal($("wf-axis").children.length, count); assert.equal($("wf-axis").children.at(-1).textContent, last);          // graduations tous les 500 Hz, sans unité
  }
  assert.ok($("wf-grid").ctx.count("stroke") > gridCalls);                                                                // la grille est redessinée à chaque changement
  assert.ok($("wf-axis").children.every((c) => !/[a-zA-Z]/.test(c.textContent)));
  await wait(400);
  state({ state: "TX", owner: "phone" }, { levels: { RFPOWER_METER: 0.5, SWR: 1.4, ALC: 0.2, PREAMP: 10, SQL: 0.25 } });
  assert.equal($("wf-tx").hidden, false); assert.equal($("wf-tx").textContent, "Po 50 % · SWR 1.4 · ALC 20 %");           // les mesures d'émission restent visibles
  state({ state: "RX" }); assert.equal($("wf-tx").hidden, true);
  await $("wf-plot").dispatch("click");                                                                                   // retour aux graphiques de puissance
  assert.equal($("waterfall").hidden, true); assert.equal($("txzone").hidden, false); assert.equal(rafQueue.length, 0);       // plus aucun calcul
  await wait(400);
  await $("txzone").dispatch("click");
  assert.equal($("waterfall").hidden, false); assert.equal(rafQueue.length, 1);
  await wait(400);
  await $("wf-plot").dispatch("click");
});

step("waterfall : sans audio reçu, un message ; l'analyse est coupée à la déconnexion", async () => {
  await wait(400);
  await $("disconnect").click(); await wait();                                                                           // on repart d'une page sans audio
  $("password").value = "mot de passe"; await $("connect").click(); await wait();
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB"] }, tx_modes: [], max_power_w: 100, memories: [] });
  await wait(30);
  await $("txzone").dispatch("click");
  assert.equal($("waterfall").hidden, false); assert.equal($("wf-peakinfo").textContent, "pas d'audio reçu"); assert.equal(rafQueue.length, 0);
  pcs.at(-1).ontrack({ track: {}, streams: [{}] });                                                                       // l'audio arrive pendant que le waterfall est ouvert
  assert.equal(rafQueue.length, 1); assert.equal(sources.at(-1).disconnected, false);
  pcs.at(-1).ontrack({ track: {}, streams: [{}] });                                                                       // nouvelle piste : l'ancienne source est détachée
  assert.equal(sources.at(-2).disconnected, true); assert.equal(analysers.length, analysers.length);
  await $("disconnect").click(); await wait();
  assert.equal(sources.at(-1).disconnected, true); assert.equal(rafQueue.length, 0);
  await wait(400);
  await $("wf-plot").dispatch("click");
  assert.equal($("waterfall").hidden, true);
});

step("spectre HF : 3e état de la zone, plein écran, échelle en MHz, repère de fréquence, STOP, fermeture si le spectre disparaît", async () => {
  await wait(400);
  $("password").value = "mot de passe"; await $("connect").click(); await wait();
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB"] }, tx_modes: [], max_power_w: 100, memories: [],
         spectrum: { source: "civ_port", level_max: 160, max_fps: 10 } });
  await wait(30);
  const hfState = (spectrum, ptt) => send({ type: "state",
    ptt: Object.assign({ state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "" }, ptt || {}),
    rig: { connected: true, frequency_hz: 14100000, mode: "USB", passband_hz: 2400, strength_db: -12, functions: {}, levels: {} },
    audio: {}, clients: ["phone"], spectrum });
  const frame = (seq, low, high) => {
    const points = 475, buf = new ArrayBuffer(16 + points), v = new DataView(buf), b = new Uint8Array(buf);
    b[0] = 1; b[1] = 1; v.setUint32(4, seq, true); v.setUint32(8, low, true); v.setUint32(12, high, true);
    for (let i = 0; i < points; i++) b[16 + i] = i === 237 ? 150 : 20;
    return buf;
  };
  const sc = () => pcs.at(-1).channels.spectrum;
  hfState({ state: "ok", code: "", message: "" });
  assert.equal($("hfscope").hidden, true);
  assert.equal(sent("spectrum_watch").length, 0);                                                // vue fermée : aucun balayage demandé
  await $("txzone").dispatch("click"); await wait(400);                                         // puissance -> audio
  assert.equal($("waterfall").hidden, false);
  assert.equal(sent("spectrum_watch").length, 0);
  await $("wf-plot").dispatch("click");                                                          // audio -> spectre HF
  assert.equal($("hfscope").hidden, false); assert.equal($("waterfall").hidden, true); assert.equal($("hf-wait").hidden, false);
  assert.equal(sent("spectrum_watch").at(-1).on, true);                                          // vue ouverte : balayages demandés
  assert.equal($("hf-freq").textContent.length > 0, true); assert.equal($("hf-tx").hidden, true);
  sc().onmessage({ data: frame(1, 14000000, 14200000) });
  assert.equal($("hf-wait").hidden, true);
  assert.equal($("hf-axis").children[0].textContent, "14.000"); assert.equal($("hf-axis").children.at(-1).textContent, "14.200");
  assert.equal($("hf-info").textContent, "largeur 200 kHz");
  assert.equal($("hf-marker").hidden, false); assert.equal($("hf-marker").style.left, "50.00%");   // fréquence du poste au milieu
  assert.equal($("hf-fall").ctx.lastRow.width, 475);                                              // élément sans taille (faux navigateur) : repli sur les points
  const lines = $("hf-fall").ctx.count("putImageData");
  sc().onmessage({ data: frame(2, 14000000, 14200000) });
  assert.equal($("hf-fall").ctx.count("putImageData"), lines + 1);                               // une ligne par balayage
  assert.equal($("hf-range").textContent, "PLAGE 40 dB");
  await $("hf-gain").click(); assert.equal($("hf-gain").textContent, "GAIN +6"); assert.deepEqual(JSON.parse(storage.get("trx.hf")), { gain: 6, range: 40 });
  await $("hf-range").click(); assert.equal($("hf-range").textContent, "PLAGE 30 dB"); assert.deepEqual(JSON.parse(storage.get("trx.hf")), { gain: 6, range: 30 });
  sc().onmessage({ data: frame(3, 14000000, 14200000) });
  const row = $("hf-fall").ctx.lastRow;                                                           // bande fine (2 px CSS), signal clair, bruit sombre
  assert.equal(row.height, 2);
  const lum = (x) => row.data[x * 4] + row.data[x * 4 + 1] + row.data[x * 4 + 2];
  const peakX = Math.round((237 / 474) * (row.width - 1));
  assert.ok(lum(peakX) > lum(10) + 200, "le signal doit ressortir nettement du bruit");
  assert.equal($("hf-set-span").textContent, "SPAN ?"); assert.equal($("hf-set-span").disabled, true);            // réglages pas encore relus
  const rigSettings = { mode: "center", span: 100000, ref: -14.5, speed: "fast" };
  hfState({ state: "ok", code: "", message: "", settings: rigSettings });
  assert.deepEqual([$("hf-set-mode").textContent, $("hf-set-span").textContent, $("hf-ref").textContent, $("hf-set-speed").textContent],
                   ["CENT", "±100k", "REF -14,5", "VIT RAP"]);
  assert.equal($("hf-set-span").disabled, false); assert.equal($("hf-ref-up").disabled, false);
  await $("hf-set-span").click(); await wait();
  assert.deepEqual(sent("spectrum_set").at(-1), Object.assign({ cmd: "spectrum_set", name: "span", value: 250000 }, { id: sent("spectrum_set").at(-1).id }));
  answer(true, { settings: Object.assign({}, rigSettings, { span: 250000 }) }, "spectrum_set"); await wait();
  assert.equal($("hf-set-span").textContent, "±250k");                                         // valeur RELUE sur le poste
  await $("hf-ref-up").click(); await wait();
  assert.equal(sent("spectrum_set").at(-1).name, "ref"); assert.equal(sent("spectrum_set").at(-1).value, -13.5);
  answer(false, { reason: "spectrum_refused" }, "spectrum_set"); await wait();
  hfState({ state: "ok", code: "", message: "", settings: Object.assign({}, rigSettings, { mode: "fixed" }) });
  assert.equal($("hf-set-span").disabled, true);                                               // en mode fixe, la largeur ne se règle pas
  // accord au doigt : seulement avec le bouton VFO allumé
  const drag = async (from, to) => {
    await $("hf-plot").dispatch("pointerdown", { clientX: from, pointerId: 7 });
    await $("hf-plot").dispatch("pointermove", { clientX: to, pointerId: 7 });
    await $("hf-plot").dispatch("pointerup", { pointerId: 7 });
  };
  const freqSets = sent("set_frequency").length;
  assert.equal($("hf-vfo").className, "chip"); assert.equal($("hf-vfo").disabled, false);
  await drag(200, 105); await wait(250);
  assert.equal(sent("set_frequency").length, freqSets);                                       // VFO éteint : glisser ne change rien
  await wait(400); await $("hf-plot").dispatch("click"); await wait(400);
  assert.equal($("hfscope").hidden, false);                                                   // un appui ne ferme jamais la vue : seul « Fermer »
  await $("hf-vfo").click();
  assert.equal($("hf-vfo").className, "chip on"); assert.equal($("hf-plot").className, "hf-plot tuning");
  await drag(200, 105); await wait(250);                                                       // 95 px à gauche sur 200 kHz : +40 kHz par pas de 500 Hz
  assert.equal(sent("set_frequency").length, freqSets + 1); assert.equal(sent("set_frequency").at(-1).hz, 14140000);
  answerAll();
  await $("hf-plot").dispatch("click"); assert.equal($("hfscope").hidden, false);            // VFO allumé : un appui ne ferme pas la vue
  hfState({ state: "ok", code: "", message: "", settings: rigSettings }, { state: "TX", owner: "phone", tot_remaining_s: 80 });
  assert.equal($("hf-vfo").className, "chip"); assert.equal($("hf-vfo").disabled, true);    // émission : VFO éteint et verrouillé
  const during = sent("set_frequency").length;
  await drag(200, 105); await wait(250); assert.equal(sent("set_frequency").length, during);
  for (const id of ["hf-set-mode", "hf-set-span", "hf-ref-down", "hf-ref-up", "hf-set-speed"]) assert.equal($(id).disabled, true, id);   // verrouillés en émission
  hfState({ state: "ok", code: "", message: "" }, { state: "TX", owner: "phone", tot_remaining_s: 80 });
  assert.equal($("hf-tx").hidden, false); assert.equal($("hf-tx").textContent, "ÉMISSION EN COURS");   // l'émission reste visible en plein écran
  const stops = sent("stop").length;
  await $("hf-stop").click(); await wait();
  assert.equal(sent("stop").length, stops + 1);                                                   // STOP toujours à portée de main
  answerAll(); hfState({ state: "ok", code: "", message: "" });
  hfState({ state: "error", code: "silent", message: "Plus aucune donnée du spectre (écran du poste sur un menu). Mode normal : un seul port, sans waterfall HF." });
  assert.equal($("hfscope").hidden, false);                                                      // spectre perdu : la vue reste et dit pourquoi
  assert.equal($("hf-wait").hidden, false); assert.match($("hf-wait").textContent, /n'envoie pas de spectre.*menu.*Nouvel essai/);
  await $("hf-close").click();
  assert.equal(sent("spectrum_watch").at(-1).on, false);
  await wait(400); await $("txzone").dispatch("click"); await wait(400); await $("wf-plot").dispatch("click");
  assert.equal($("hfscope").hidden, false); assert.equal(sent("spectrum_watch").at(-1).on, true);   // toujours proposée (portrait compris) : son ouverture relance un essai
  hfState({ state: "ok", code: "", message: "" });
  assert.match($("hf-wait").textContent, /En attente du spectre/);
  sc().onmessage({ data: frame(9, 14000000, 14200000) });
  assert.equal($("hf-wait").hidden, true);                                                       // balayages revenus
  const watches = sent("spectrum_watch").length;
  await $("hf-close").click();
  assert.equal($("hfscope").hidden, true); assert.equal($("txzone").hidden, false);
  assert.equal(sent("spectrum_watch").length, watches + 1); assert.equal(sent("spectrum_watch").at(-1).on, false);   // fermée : plus de balayages
  await wait(400); await $("txzone").dispatch("click"); await wait(400); await $("wf-plot").dispatch("click");
  assert.equal($("hfscope").hidden, false);
  await $("disconnect").click(); await wait();
  assert.equal($("hfscope").hidden, true);                                                        // déconnexion : vue fermée
});

step("spectre HF intégré (paysage large) : interrupteur sous RÉCEPTION, vue en haut à droite, bascule du mode au doigt", async () => {
  const turn = async (isLandscape, width) => {
    landscape = isLandscape; globalThis.innerWidth = width;
    await Promise.all(windowHandlers.resize.map((fn) => fn()));
  };
  await turn(true, 1280);
  assert.equal($("app").className, "landscape"); assert.equal($("blk-hfdock").hidden, true);         // pas connecté : rien à proposer
  await wait(400);
  $("password").value = "mot de passe"; await $("connect").click(); await wait();
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB", "CW", "PKTUSB", "PKTLSB"] }, tx_modes: [], max_power_w: 100, memories: [],
         spectrum: { source: "civ_port", level_max: 160, max_fps: 10 } });
  await wait(30);
  const st = (rig, ptt) => send({ type: "state",
    ptt: Object.assign({ state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "" }, ptt || {}),
    rig: Object.assign({ connected: true, frequency_hz: 14100000, mode: "USB", passband_hz: 2400, strength_db: -12, functions: {}, levels: {} }, rig || {}),
    audio: {}, clients: ["phone"], spectrum: { state: "ok", code: "", message: "" } });
  st();
  assert.equal($("blk-hfdock").hidden, false); assert.equal($("hf-dock-on").checked, false);         // proposé, éteint par défaut
  assert.equal($("hfscope").hidden, true);
  $("hf-dock-on").checked = true; await $("hf-dock-on").dispatch("change");
  assert.equal(storage.get("trx.hfdock"), "1");
  assert.equal($("hfscope").hidden, false); assert.equal($("hfscope").className, "hf docked");
  assert.equal($("hfscope").parent, $("hf-dock")); assert.equal($("hf-dock").hidden, false);
  assert.equal($("hf-close").hidden, true);                                                          // intégrée : retirée par l'interrupteur
  assert.equal(sent("spectrum_watch").at(-1).on, true);
  await wait(400); await $("txzone").dispatch("click");                                              // puissance -> audio...
  assert.equal($("waterfall").hidden, false); assert.equal($("hfscope").hidden, false);
  await wait(400); await $("wf-plot").dispatch("click");                                             // ... -> puissance : le spectre intégré reste
  assert.equal($("waterfall").hidden, true); assert.equal($("txzone").hidden, false); assert.equal($("hfscope").className, "hf docked");
  await $("hf-plot").dispatch("click"); assert.equal($("hfscope").hidden, false);                    // un appui sur le spectre ne le retire pas
  // bouton du mode en haut à gauche
  await $("mode-pill").click(); await wait();
  assert.equal(sent("set_mode").at(-1).mode, "PKTUSB"); answer(true, {}, "set_mode"); await wait();  // USB -> USB-D
  st({ mode: "PKTUSB" }); await $("mode-pill").click(); await wait();
  assert.equal(sent("set_mode").at(-1).mode, "PKTLSB"); answer(true, {}, "set_mode"); await wait();  // USB-D -> LSB-D
  st({ mode: "PKTLSB" }); await $("mode-pill").click(); await wait();
  assert.equal(sent("set_mode").at(-1).mode, "PKTUSB"); answer(true, {}, "set_mode"); await wait();  // LSB-D -> USB-D
  st({ mode: "CW" }); await $("mode-pill").click(); await wait();
  assert.equal(sent("set_mode").at(-1).mode, "PKTUSB"); answer(true, {}, "set_mode"); await wait();  // autre mode -> USB-D
  st({ mode: "PKTUSB" }, { state: "TX", owner: "phone", tot_remaining_s: 80 });
  const modes = sent("set_mode").length;
  await $("mode-pill").click(); await wait();
  assert.equal(sent("set_mode").length, modes);                                                      // émission : rien n'est envoyé
  assert.equal($("hfscope").hidden, false); assert.equal($("ptt").hidden, false);                    // PTT et STOP restent visibles à gauche
  st({ mode: "PKTUSB" });
  // portrait ou écran étroit : la vue intégrée se retire, et revient en paysage (interrupteur mémorisé)
  await turn(false, 412);
  assert.equal($("hfscope").hidden, true); assert.equal($("blk-hfdock").hidden, true); assert.equal(sent("spectrum_watch").at(-1).on, false);
  await turn(true, 900);
  assert.equal($("hfscope").hidden, true);                                                           // paysage, mais moins de 1000 px
  await turn(true, 1280);
  assert.equal($("hfscope").hidden, false); assert.equal($("hfscope").className, "hf docked"); assert.equal(sent("spectrum_watch").at(-1).on, true);
  send({ type: "state", ptt: { state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "" },
    rig: { connected: true, frequency_hz: 14100000, mode: "PKTUSB", passband_hz: 2400, strength_db: -12, functions: {}, levels: {} }, audio: {}, clients: ["phone"],
    spectrum: { state: "error", code: "silent", message: "Plus aucune donnée du spectre. Mode normal : un seul port, sans waterfall HF." } });
  assert.equal($("hfscope").hidden, false); assert.equal($("blk-hfdock").hidden, false);            // spectre perdu : la vue reste...
  assert.equal($("hf-wait").hidden, false); assert.match($("hf-wait").textContent, /n'envoie pas de spectre/);   // ... et dit pourquoi
  st({ mode: "PKTUSB" });
  assert.equal($("hfscope").hidden, false);                                                          // de retour avec le spectre
  $("hf-dock-on").checked = false; await $("hf-dock-on").dispatch("change");
  assert.equal($("hfscope").hidden, true); assert.equal(storage.get("trx.hfdock"), "0"); assert.equal(sent("spectrum_watch").at(-1).on, false);
  await $("disconnect").click(); await wait();
  await turn(false, 412);
});

step("cluster DX : pastille, marqueurs sur le spectre HF, fiche, QSY (refusé pendant l'émission), « +N », liste", async () => {
  await wait(400);
  $("password").value = "mot de passe"; await $("connect").click(); await wait();
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB", "CW"] }, tx_modes: [], max_power_w: 100, memories: [],
         spectrum: { source: "civ_port", level_max: 160, max_fps: 10 } });
  await wait(30);
  const st = (ptt) => send({ type: "state",
    ptt: Object.assign({ state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "" }, ptt || {}),
    rig: { connected: true, frequency_hz: 14100000, mode: "LSB", passband_hz: 2400, strength_db: -12, functions: {}, levels: {} },
    audio: {}, clients: ["phone"], spectrum: { state: "ok", code: "", message: "" } });
  const cluster = (data) => send({ type: "module", module: "cluster", data });
  st();
  assert.equal($("hf-cluster").hidden, true);
  cluster({ kind: "module_state", module: "cluster", health: "orange", text: "Cluster DX : sources en partie connectées" });
  assert.match($("log").children[0].textContent, /\[cluster\] Cluster DX : sources en partie/);            // texte des modules dans le journal
  assert.equal($("hf-cluster").hidden, false); assert.equal($("hf-cluster").className, "cluster-dot orange");
  assert.equal($("hf-spots").hidden, false); assert.equal($("hf-list").hidden, false);
  await $("txzone").dispatch("click"); await wait(400); await $("wf-plot").dispatch("click");
  assert.equal($("hfscope").hidden, false);
  const frame = (seq, low, high) => {
    const buf = new ArrayBuffer(16 + 475), v = new DataView(buf), b = new Uint8Array(buf);
    b[0] = 1; b[1] = 1; v.setUint32(4, seq, true); v.setUint32(8, low, true); v.setUint32(12, high, true);
    return buf;
  };
  pcs.at(-1).channels.spectrum.onmessage({ data: frame(1, 14000000, 14200000) });
  cluster({ kind: "spots", op: "snapshot", scope: "hf_view", retain: "snapshot", window: [14000, 14350], spots: [
    { id: 1, f: 14050, dx: "K1ABC", de: "F5XYZ", m: "SSB", k: "cluster", t: "1847", n: 2, age: 10, q: "USB", co: "United States", ct: "NA", c: "59 tnx" },
    { id: 2, f: 14300, dx: "HORS", de: "F5XYZ", m: "CW", k: "rbn", t: "1847", n: 1, age: 10, q: "CW" }] });
  const layer = $("hf-spot-layer");
  const tags = () => layer.children.filter((c) => c.className.startsWith("spot-tag"));
  const lines = () => layer.children.filter((c) => c.className.startsWith("spot-line"));
  assert.deepEqual(tags().map((t) => t.textContent), ["K1ABC"]);                                // hors de la plage visible : pas de marqueur
  assert.match(tags()[0].className, /k-cluster/); assert.match(tags()[0].className, /fresh/);   // moins de 2 min : mis en évidence
  assert.equal(lines().length, 1); assert.equal(lines()[0].style.left, "25.00%");
  await tags()[0].click();
  assert.equal($("spot-card").hidden, false); assert.equal($("spot-dx").textContent, "K1ABC");
  assert.equal($("spot-freq").textContent, "14050.0 kHz · BLU"); assert.match($("spot-kind").textContent, /2 spotteurs/);
  assert.match($("spot-info").textContent, /United States \(NA\) · de F5XYZ · 18:47 UTC · à l'instant/);
  assert.equal($("spot-comment").textContent, "59 tnx"); assert.equal($("spot-qsy").disabled, false);
  const qsy = $("spot-qsy").click(); await wait();
  assert.equal(sent("set_mode").at(-1).mode, "USB");                                            // le mode d'abord...
  answer(true, {}, "set_mode"); await wait();
  assert.equal(sent("set_frequency").at(-1).hz, 14050000);                                     // ... puis la fréquence
  answer(true, {}, "set_frequency"); await qsy; await wait();
  assert.equal($("spot-card").hidden, true); assert.match($("log").children[0].textContent, /QSY sur K1ABC/);
  await tags()[0].click();
  st({ state: "TX", owner: "phone", tot_remaining_s: 80 });
  assert.equal($("spot-qsy").disabled, true);                                                   // émission : QSY verrouillé
  const freqs = sent("set_frequency").length, modes = sent("set_mode").length;
  await $("spot-qsy").click(); await wait();
  assert.equal(sent("set_frequency").length, freqs); assert.equal(sent("set_mode").length, modes);
  st(); await $("spot-close").click(); assert.equal($("spot-card").hidden, true);
  const crowd = [];
  for (let i = 0; i < 9; i++) crowd.push({ id: 10 + i, f: 14100 + i * 0.3, dx: "DX" + i + "AB", de: "G4AAA", m: "CW", k: i % 2 ? "rbn" : "cb", t: "1850", n: 1, age: 400 });
  cluster({ kind: "spots", op: "delta", scope: "hf_view", retain: "delta", spots: crowd, removed: [1] });
  assert.ok(!tags().some((t) => t.textContent === "K1ABC"));                                    // retiré
  const group = tags().find((t) => /group/.test(t.className));
  assert.ok(group, "les étiquettes en trop sont regroupées");
  assert.match(group.textContent, /^\+\d+$/);
  assert.ok(tags().filter((t) => !/group/.test(t.className)).every((t) => !/fresh/.test(t.className)));   // vieux de plus de 2 min
  await group.click();
  assert.equal($("spot-list").hidden, false); assert.match($("spot-list-title").textContent, /^Spots proches \(\d+\)$/);
  assert.equal($("spot-items").children.length, Number(group.textContent.slice(1)));
  await $("spot-items").children[0].click();
  assert.equal($("spot-card").hidden, false); assert.equal($("spot-list").hidden, true);
  await $("spot-close").click();
  await $("hf-list").click();
  assert.equal($("spot-list").hidden, false); assert.equal($("spot-list-title").textContent, "Spots de la bande (10)");
  await $("spot-sort").click(); assert.equal($("spot-sort").textContent, "Tri : âge");
  await $("spot-list-close").click(); assert.equal($("spot-list").hidden, true);
  await $("hf-spots").click();
  assert.equal(layer.children.length, 0); assert.equal(storage.get("trx.spots"), "0");          // marqueurs masqués, choix mémorisé
  await $("hf-spots").click(); assert.ok(layer.children.length > 0);
  await $("hf-close").click();
  assert.equal(layer.children.length, 0);                                                       // vue fermée : rien n'est gardé (rejoué à l'ouverture)
  await $("disconnect").click(); await wait();
});

step("bips de fin d'émission : réglage de la station depuis l'onglet Audio, écoute locale, liaison perdue avertie", async () => {
  assert.equal($("roger-on").disabled, true);                                                   // hors liaison : rien à régler
  await wait(400);
  $("password").value = "mot de passe"; await $("connect").click(); await wait();
  const beeps = { roger_enabled: false, roger_tone: "1000", roger_pattern: 1, link_lost_enabled: false,
                  roger_sequence: [[1000, 100]], link_lost_sequence: [[1200, 120], [0, 40], [900, 120], [0, 40], [600, 120]],
                  tones: ["600", "800", "1000", "1500", "2000", "2500", "duo"], patterns: [1, 2, 3] };
  send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB"] }, tx_modes: [], max_power_w: 100, memories: [], beeps });
  await wait(30);
  assert.equal($("roger-on").disabled, false); assert.equal($("roger-on").checked, false);
  assert.deepEqual($("roger-tone").options.map((o) => o.value), beeps.tones);
  assert.equal($("roger-tone").options.at(-1).textContent, "deux tons montants");
  assert.deepEqual($("roger-pattern").options.map((o) => o.textContent), ["1 bip", "2 bips", "3 bips"]);
  $("roger-on").checked = true; await $("roger-on").dispatch("change", { target: $("roger-on") }); await wait();
  assert.deepEqual(sent("beeps_set").at(-1), { cmd: "beeps_set", id: sent("beeps_set").at(-1).id, roger_enabled: true });
  answer(true, { settings: Object.assign({}, beeps, { roger_enabled: true }) }, "beeps_set"); await wait();
  assert.equal($("roger-on").checked, true);
  $("roger-pattern").value = "3"; await $("roger-pattern").dispatch("change", { target: $("roger-pattern") }); await wait();
  assert.equal(sent("beeps_set").at(-1).roger_pattern, 3);                                      // nombre, pas texte
  answer(false, { reason: "beeps_storage_error" }, "beeps_set"); await wait();
  assert.match($("log").children[0].textContent, /pas pu enregistrer le réglage des bips/);
  $("lost-on").checked = true; await $("lost-on").dispatch("change", { target: $("lost-on") }); await wait();
  assert.equal(sent("beeps_set").at(-1).link_lost_enabled, true);
  answer(true, { settings: Object.assign({}, beeps, { roger_enabled: true, link_lost_enabled: true }) }, "beeps_set"); await wait();
  assert.match($("beeps-note").textContent, /ACTIF.*sous votre responsabilité/);
  send({ type: "beeps", settings: Object.assign({}, beeps, { roger_tone: "duo" }) });           // changé depuis un autre appareil
  assert.equal($("roger-tone").value, "duo"); assert.equal($("lost-on").checked, false); assert.equal($("beeps-note").textContent, "");
  await $("roger-preview").click(); await $("lost-preview").click();                            // écoute locale : aucune commande
  assert.equal(sent("beeps_set").length, 3);
  await $("disconnect").click(); await wait();
  assert.equal($("roger-on").disabled, true);
});

step("déconnexion : tout revient à l'état de départ", async () => {
  await $("disconnect").click(); await wait();
  assert.equal($("sec-connect").open, true); assert.equal($("ptt").disabled, true); assert.equal($("armed").checked, false);
  assert.ok(["nr", "nb", "preamp", "aip", "agc", "comp", "fil", "tuner"].every((k) => $("ctl-" + k).disabled === true));
  assert.equal($("mem-list").children.length, 0); assert.equal($("mem-form").hidden, true); assert.equal($("squelch").disabled, true);
});

step("pertes de connexion : dernière raison, historique des 10 dernières, rapport copiable, effacement", async () => {
  $("reconnect-select").value = "0"; await $("reconnect-select").dispatch("change", { target: $("reconnect-select") });   // ici, on teste la perte « classique »
  assert.equal(storage.get("trx.reconnect"), "0");
  const connect = async () => {
    $("client-id").value = "phone"; $("password").value = "mot de passe"; await $("connect").click(); await wait();
    send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB"] }, tx_modes: [], max_power_w: 100, memories: [] });
    await wait(30); state({});
  };
  await connect();
  assert.equal($("loss-last").hidden, true); assert.equal($("loss-open").hidden, true);                                  // aucune perte pour l'instant
  assert.deepEqual($("loss-select").options.map((o) => o.textContent), ["Aucune perte enregistrée"]);
  assert.equal($("loss-copy").disabled, true); assert.equal($("loss-clear").disabled, true);
  assert.equal($("loss-detail").textContent, "Aucune perte de connexion enregistrée.");
  pcs.at(-1).dc.onclose();                                                                                                // le canal se ferme tout seul
  assert.equal($("loss-last").hidden, false); assert.equal($("loss-open").hidden, false);
  assert.match($("loss-last").textContent, /^Dernière perte de connexion : Canal de contrôle fermé — /);
  assert.equal($("sec-connect").open, true);                                                                              // la zone de connexion se rouvre, avec la raison
  assert.equal($("loss-select").options.length, 1); assert.match($("loss-select").options[0].textContent, /Canal de contrôle fermé/);
  assert.match($("loss-detail").textContent, /^Perte de connexion — /); assert.match($("loss-detail").textContent, /Raison : Canal de contrôle fermé/);
  assert.match($("loss-detail").textContent, /Détails : .*session \d+ s/); assert.match($("loss-detail").textContent, /Dernières lignes du journal :/);
  assert.equal($("loss-copy").disabled, false); assert.equal($("loss-clear").disabled, false);
  await $("loss-copy").click();
  assert.equal(clipboard.at(-1), $("loss-detail").textContent);                                                          // le rapport complet est copié
  assert.deepEqual($("status").className, "badge bad");
  await connect();                                                                                                        // deuxième perte : liaison réseau
  pcs.at(-1).connectionState = "failed"; pcs.at(-1).onconnectionstatechange();
  assert.equal($("loss-select").options.length, 2);
  assert.match($("loss-select").options[0].textContent, /Liaison réseau échouée/); assert.match($("loss-select").options[1].textContent, /Canal de contrôle fermé/);   // la plus récente d'abord
  assert.match($("loss-detail").textContent, /Raison : Liaison réseau échouée/);
  $("loss-select").value = "1"; await $("loss-select").dispatch("change", { target: $("loss-select") });
  assert.match($("loss-detail").textContent, /Raison : Canal de contrôle fermé/);                                        // on revient sur la précédente
  $("sec-diag").open = false;
  await $("loss-open").click();
  assert.equal($("sec-diag").open, true); assert.equal($("sec-diag").scrolled, true);                                    // le bouton ouvre l'onglet journal
  assert.match($("loss-detail").textContent, /Raison : Liaison réseau échouée/);
  assert.equal(JSON.parse(storage.get("trx.losses")).length, 2);
  $("password").value = "mauvais"; offerStatus = 401;                                                                     // un échec de connexion est aussi consigné
  await $("connect").click(); await wait();
  assert.match($("loss-last").textContent, /^Dernier échec de connexion : Identifiants refusés — /);
  assert.equal($("loss-select").options.length, 3); assert.match($("loss-select").options[0].textContent, /\(échec de connexion\)$/);
  assert.match($("loss-detail").textContent, /^Échec de connexion — /);
  offerStatus = 200;
  await $("loss-clear").click();
  assert.deepEqual($("loss-select").options.map((o) => o.textContent), ["Aucune perte enregistrée"]);
  assert.equal($("loss-last").hidden, true); assert.equal($("loss-open").hidden, true); assert.equal($("loss-copy").disabled, true);
  assert.equal($("loss-detail").textContent, "Aucune perte de connexion enregistrée."); assert.equal(storage.get("trx.losses"), "[]");
});

step("reconnexion automatique : grand texte à la place de la fréquence, sans redemander le mot de passe, annulation, échec, reprise", async () => {
  $("reconnect-select").value = "15"; await $("reconnect-select").dispatch("change", { target: $("reconnect-select") });
  assert.equal(storage.get("trx.reconnect"), "15");
  offerStatus = 200;
  $("client-id").value = "phone"; $("password").value = "mot de passe"; await $("connect").click(); await wait();
  const hello = () => send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB"] }, tx_modes: [], max_power_w: 100, memories: [] });
  hello(); await wait(30); state({});
  assert.equal($("password").value, ""); assert.equal($("reconnect").hidden, true); assert.equal($("freq").hidden, false);
  $("armed").checked = true; await $("armed").dispatch("change");
  const before = pcs.length, postsBefore = offers.length;
  pcs.at(-1).dc.onclose();                                                                                                // micro-coupure du réseau mobile
  assert.equal($("freq").hidden, true); assert.equal($("reconnect").hidden, false); assert.equal($("reconnect").className, "reconnect");
  assert.equal($("reconnect-text").textContent, "RECONNEXION… 15 s"); assert.equal($("reconnect-sub").textContent, "préparation");
  assert.equal($("reconnect-cancel").hidden, false); assert.deepEqual([$("status").textContent, $("status").className], ["Reconnexion…", "badge busy"]);
  assert.equal($("ptt").disabled, true); assert.equal($("armed").checked, false); assert.ok($("bands").children.every((b) => b.disabled === true));
  await $("freq").dispatch("pointerdown", { clientX: 5, clientY: 5, pointerId: 11 }); await $("freq").dispatch("pointerup", { pointerId: 11 });
  assert.equal($("keypad").hidden, true);                                                                                 // rien ne se commande pendant la reconnexion
  await wait(900);                                                                                                        // la boucle bat toutes les 500 ms : un essai est parti
  assert.equal(pcs.length, before + 1); assert.equal(offers.length, postsBefore + 1);
  assert.deepEqual([offers.at(-1).client_id, offers.at(-1).password], ["phone", "mot de passe"]);                       // mêmes identifiants, rien n'a été redemandé
  assert.equal($("password").value, ""); assert.match($("reconnect-sub").textContent, /^essai 1/);
  assert.match($("reconnect-text").textContent, /^RECONNEXION… 1[45] s$/);
  hello(); await wait(30); state({});                                                                                    // la station répond
  assert.equal($("reconnect").hidden, true); assert.equal($("freq").hidden, false); assert.equal($("ptt").disabled, false);
  assert.equal($("armed").checked, false);                                                                                // jamais réarmé tout seul
  assert.ok($("log").children.some((li) => /Reconnecté après \d+ s/.test(li.textContent)));
  assert.equal($("sec-connect").open, false);
  // annulation par l'utilisateur
  pcs.at(-1).dc.onclose(); assert.equal($("reconnect").hidden, false);
  await $("reconnect-cancel").click();
  assert.equal($("reconnect").hidden, true); assert.equal($("freq").hidden, false); assert.deepEqual([$("status").textContent, $("status").className], ["Déconnecté", "badge"]);
  const afterCancel = pcs.length; await wait(1100); assert.equal(pcs.length, afterCancel);                              // plus aucun essai
  // identifiants refusés pendant la reconnexion : texte rouge fixe
  $("password").value = "mot de passe"; await $("connect").click(); await wait(); hello(); await wait(30); state({});
  offerStatus = 401; pcs.at(-1).dc.onclose();
  await wait(900);
  assert.equal($("reconnect").hidden, false); assert.equal($("reconnect").className, "reconnect lost"); assert.equal($("freq").hidden, true);
  assert.equal($("reconnect-text").textContent, "CONNEXION PERDUE"); assert.equal($("reconnect-sub").textContent, "identifiants refusés"); assert.equal($("reconnect-cancel").hidden, true);
  assert.equal($("sec-connect").open, true); assert.match($("loss-detail").textContent, /reconnexion automatique abandonnée \(identifiants refusés\)/);
  const posts = offers.length; await wait(1100); assert.equal(offers.length, posts);                                       // on n'insiste pas
  offerStatus = 200;                                                                                                      // nouvelle connexion manuelle : le bandeau disparaît
  $("password").value = "mot de passe"; await $("connect").click(); await wait();
  assert.equal($("reconnect").hidden, true); assert.equal($("freq").hidden, false);
  hello(); await wait(30);
  await $("reconnect-select").dispatch("change", { target: Object.assign($("reconnect-select"), { value: "60" }) });
  assert.equal(storage.get("trx.reconnect"), "60");
  await $("disconnect").click(); await wait();
});

step("mise en page personnalisée : profil du compte, grille, calques, éléments masqués, écran de sécurité, retour à l'usine", async () => {
  landscape = false; globalThis.innerWidth = 412; storage.set("trx.layout", "auto");      // téléphone tenu en portrait
  const copy = (o) => JSON.parse(JSON.stringify(o));
  const connectWith = async (profile, layouts) => {
    $("password").value = "mot de passe"; await $("connect").click(); await wait();
    send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB", "LSB"] }, tx_modes: [], max_power_w: 100, memories: [], layouts: layouts !== false });
    await wait(30);
    if (layouts === false) return;
    assert.equal(sent("layout_get").length, 1);                                           // demandé une fois, à la connexion
    answer(true, { profile: profile, source: "user", warnings: [] }, "layout_get"); await wait();
  };
  // une station sans mises en page : rien n'est demandé, la page reste celle d'usine
  await connectWith(null, false);
  assert.equal(sent("layout_get").length, 0); assert.equal($("app").getAttribute("data-layout"), null);
  assert.equal($("layout-info").textContent, "Interface d'usine."); assert.equal($("layout-factory").disabled, true);
  await $("disconnect").click(); await wait();
  // profil d'usine servi comme profil du compte : tout trouve sa place dans la grille
  const mine = copy(FACTORY); mine.name = "Mon écran";
  await connectWith(mine);
  assert.equal($("app").getAttribute("data-layout"), "profile");
  assert.equal($("ptt").parent.id, "lay-top"); assert.equal($("ptt").style.gridColumn, "1 / span 3"); assert.equal($("ptt").style.gridRow, "9 / span 2");
  assert.equal($("ptt").parent.style.gridTemplateColumns, "repeat(4, minmax(0, 1fr))"); assert.equal($("top").children[0].id, "lay-top");
  assert.equal($("blk-memories").parent.parent.className, "laysec");                       // l'accordéon va dans la partie qui défile
  assert.match($("layout-info").textContent, /Profil « Mon écran » — variante smartphone portrait\./); assert.equal($("layout-factory").disabled, false);
  // zone à calques : un appui passe au waterfall (l'analyse démarre), un double appui ne bascule qu'une fois
  const box = $("blk-po").parent.parent;
  assert.match(box.className, /laylayers/);
  pcs.at(-1).ontrack({ track: {}, streams: [{}] });
  assert.equal(rafQueue.length, 0);
  await box.dispatch("click"); await box.dispatch("click");
  assert.equal($("waterfall").parent.getAttribute("data-lay"), "on"); assert.equal($("blk-po").parent.getAttribute("data-lay"), "off");
  assert.equal(rafQueue.length, 1); assert.equal(storage.get("trx.lay.txzone"), "[0,1]"); assert.equal($("waterfall").hidden, false);
  await wait(400);
  await box.dispatch("click", { target: $("wf-speed") });                                  // un bouton du calque garde ses appuis
  assert.equal($("waterfall").parent.getAttribute("data-lay"), "on");
  await box.dispatch("click");
  assert.equal($("blk-po").parent.getAttribute("data-lay"), "on"); assert.equal(rafQueue.length, 0); assert.equal($("waterfall").hidden, true);   // retour : plus de calcul
  await $("disconnect").click(); await wait();
  // élément absent du profil : masqué ; widget non pris en charge : ignoré et signalé
  const fewer = copy(FACTORY);
  const widgets = fewer.variants.phone.portrait.widgets;
  widgets.splice(widgets.findIndex((w) => w.id === "nb"), 1);
  widgets.push({ id: "dw", type: "switch", x: 1, y: 7, w: 1, h: 1, bind: "DUAL_WATCH" });
  await connectWith(fewer);
  assert.equal($("ctl-nb").getAttribute("data-lay"), "off"); assert.equal($("ctl-nr").getAttribute("data-lay"), null);
  assert.ok($("log").children.some((li) => /pas encore pris en charge.*dw/.test(li.textContent)));
  await $("disconnect").click(); await wait();
  // aucune variante pour un smartphone : écran de sécurité, STOP et état restent utilisables
  const tabletOnly = { format: 1, name: "Tablette", variants: { tablet: copy(FACTORY.variants.phone) } };
  await connectWith(tabletOnly);
  assert.equal($("app").getAttribute("data-layout"), "safe"); assert.equal($("safe-screen").hidden, false);
  assert.match($("safe-text").textContent, /pas d'interface pour un smartphone/);
  assert.equal($("stop").parent, $("safe-body")); assert.equal($("ptt-state").parent, $("safe-body")); assert.equal($("fault").parent, $("safe-body"));
  state({}); await wait();
  assert.equal($("stop").disabled, false);
  const stopping = $("stop").click(); await wait(); assert.equal(sent("stop").length, 1); answer(true, { ptt: {} }, "stop"); await stopping;
  // retour à l'interface d'usine : la page redevient celle qui est écrite
  const resetting = $("layout-factory").click(); await wait();
  assert.equal(sent("layout_reset").length, 1); answer(true, { profile: FACTORY, source: "factory", warnings: [] }, "layout_reset"); await resetting; await wait();
  assert.equal($("app").getAttribute("data-layout"), null); assert.equal($("safe-screen").hidden, true);
  assert.equal($("stop").parent, null); assert.equal($("ptt").parent, null); assert.ok(!$("top").children.some((c) => c.id === "lay-top"));
  assert.equal($("layout-info").textContent, "Interface d'usine.");
  await $("disconnect").click(); await wait();
});

step("sons de la liaison : réglage mémorisé, essai des trois sons, coupés, JAMAIS sur la sortie du poste", async () => {
  assert.deepEqual($("alert-select").options.map((o) => o.value), ["high", "normal", "low", "off"]);
  assert.equal($("alert-select").value, "normal"); assert.equal($("alert-test").disabled, true);    // pas d'essai avant de savoir quelle sortie est le poste
  const login = async () => {
    $("client-id").value = "phone"; $("password").value = "mot de passe"; await $("connect").click(); await wait();
    send({ type: "hello", protocol: 1, client_id: "phone", capabilities: { modes: ["USB"] }, tx_modes: [], memories: [] }); await wait(30); state({});
  };
  $("reconnect-select").value = "0"; await $("reconnect-select").dispatch("change", { target: $("reconnect-select") });
  await login();
  assert.equal($("alert-test").disabled, false);
  const notes = oscillators.length, buzz = vibrations.length;
  await $("alert-test").click(); await wait(2900);                                  // les trois sons à la suite
  const played = oscillators.slice(notes).map((o) => o.frequency.value);
  assert.deepEqual(played, TrxWeb.LINK_ALERTS.lost.notes.concat(TrxWeb.LINK_ALERTS.restored.notes, TrxWeb.LINK_ALERTS.failed.notes).map(([hz]) => hz));
  assert.ok(oscillators.slice(notes).every((o) => o.target && o.target.target && o.target.target.name === "sortie" && o.stopAt > o.startAt));
  assert.equal(Math.max(...oscillators.slice(notes).map((o) => Math.max(...o.target.values))), TrxWeb.alertVolume("normal"));
  assert.deepEqual(vibrations.slice(buzz), [TrxWeb.LINK_ALERTS.lost.vibrate, TrxWeb.LINK_ALERTS.restored.vibrate, TrxWeb.LINK_ALERTS.failed.vibrate]);
  $("alert-select").value = "off"; await $("alert-select").dispatch("change", { target: $("alert-select") });
  assert.equal(storage.get("trx.alerts"), "off");
  const offNotes = oscillators.length, offBuzz = vibrations.length;
  await $("alert-test").click(); await wait(50);
  assert.deepEqual([oscillators.length, vibrations.length], [offNotes, offBuzz]);   // coupés : ni son ni vibration
  $("alert-select").value = "normal"; await $("alert-select").dispatch("change", { target: $("alert-select") });
  await $("disconnect").click(); await wait();
  rigAudioList = ["Haut-parleurs"];                                                 // la sortie choisie est la carte son du poste
  await login();
  $("out-select").value = "o1"; await $("out-select").dispatch("change"); await wait();
  assert.equal($("rx-audio").muted, true);
  const rigNotes = oscillators.length, rigBuzz = vibrations.length;
  await $("alert-test").click(); await wait(50);
  assert.equal(oscillators.length, rigNotes);                                       // aucun son injecté dans l'émetteur...
  assert.equal(vibrations.length, rigBuzz + 1);                                     // ... mais le téléphone vibre quand même
  rigAudioList = []; $("out-select").value = ""; await $("out-select").dispatch("change"); await wait();
  await $("disconnect").click(); await wait();
  assert.equal($("alert-test").disabled, true);
});

step("thème des couleurs : choix appliqué tout de suite à la page et mémorisé sur l'appareil", async () => {
  assert.deepEqual($("theme-select").options.map((o) => o.value), ["defaut", "icom", "yaesu", "kenwood"]);
  assert.equal($("theme-select").value, "defaut");
  $("theme-select").value = "kenwood"; await $("theme-select").dispatch("change", { target: $("theme-select") });
  assert.equal(document.documentElement.getAttribute("data-theme"), "kenwood");
  assert.equal(storage.get("trx.theme"), "kenwood");
  $("theme-select").value = "defaut"; await $("theme-select").dispatch("change", { target: $("theme-select") });
  assert.equal(document.documentElement.getAttribute("data-theme"), "defaut"); assert.equal(storage.get("trx.theme"), "defaut");
});

(async () => {
  let failed = 0;
  for (const [name, fn] of steps) {
    try { await fn(); console.log("OK    " + name); }
    catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
  }
  console.log((steps.length - failed) + "/" + steps.length + " étapes de l'affichage réussies");
  process.exit(failed ? 1 : 0);
})();
