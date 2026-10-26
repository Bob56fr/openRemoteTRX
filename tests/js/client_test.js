// Tests de la logique du client web (TrxClient) avec un faux navigateur : `node tests/js/client_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const web = require(path.join(__dirname, "../../trxstation/gateway/api/static/client.js"));

class FakeDC {
  constructor() { this.readyState = "open"; this.sent = []; this.onmessage = null; this.onclose = null; }
  send(text) { this.sent.push(JSON.parse(text)); }
  close() { this.readyState = "closed"; }
}
class FakePC {
  constructor() { this.tracks = []; this.transceivers = []; this.dc = null; this.connectionState = "new";
                  this.localDescription = null; this.remote = null; this.closed = false; }
  addTrack(track) { this.tracks.push(track); }
  addTransceiver(kind, opts) { this.transceivers.push({ kind, opts }); }
  createDataChannel(label) { this.dc = new FakeDC(); this.dc.label = label; return this.dc; }
  async createOffer() { return { sdp: "v=0 offre", type: "offer" }; }
  async setLocalDescription(d) { this.localDescription = d; }
  async setRemoteDescription(d) { this.remote = d; }
  close() { this.closed = true; this.connectionState = "closed"; }
}

function makeWorld(overrides) {
  const mic = { enabled: true, stopped: false, label: "Microphone (Realtek HD Audio Mic input)", stop() { this.stopped = true; } };
  const intervals = [], timeouts = [];
  let clock = 1000;
  const locks = [];
  const store = new Map();
  const env = Object.assign({
    store, online: true, visible: true,
    storage: { get: (k) => (store.has(k) ? store.get(k) : null), set: (k, v) => { store.set(k, String(v)); } },
    epoch: () => 1700000000000 + (clock - 1000), isOnline: () => env.online, isVisible: () => env.visible,
    pcs: [], offers: [], offerStatus: 200, mic, isSecureContext: true, locks,
    requestWakeLock: async () => {
      const lock = { released: false, listeners: [], addEventListener(type, fn) { this.listeners.push(fn); },
        release() { this.released = true; this.listeners.forEach((f) => f()); return Promise.resolve(); } };
      locks.push(lock); return lock;
    },
    RTCPeerConnection: function (config) { const pc = new FakePC(); pc.config = config; env.pcs.push(pc); return pc; },
    getUserMedia: async (constraints) => { env.constraints = constraints; return { getAudioTracks: () => [mic] }; },
    now: () => clock, advance: (ms) => { clock += ms; },
    tickAll: () => { for (const i of intervals.filter((x) => x.active)) i.f(); },
    setInterval: (f) => { intervals.push({ f, active: true }); return intervals.length - 1; },
    clearInterval: (id) => { intervals[id].active = false; },
    setTimeout: (f) => { timeouts.push({ f, active: true }); return timeouts.length - 1; },
    clearTimeout: (id) => { if (timeouts[id]) timeouts[id].active = false; },
    configs: [], getConfig: async () => ({ ice_servers: ["stun:stun.example.org:3478"], rig_audio: ["Microphone (USB Audio Device)", "Haut-parleurs (USB Audio Device)"] }),
    waitIceComplete: async () => {},
    postOffer: async (body) => { env.offers.push(body); return { status: env.offerStatus, body: { sdp: "v=0 réponse", type: "answer" } }; },
  }, overrides || {});
  env.tick = () => intervals.filter((t) => t.active).forEach((t) => t.f());
  env.activeIntervals = () => intervals.filter((t) => t.active).length;
  env.fireTimeouts = () => timeouts.filter((t) => t.active).forEach((t) => t.f());
  const ui = { statuses: [], logs: [], views: [], armedCalls: [], connectedCalls: [], modeLists: [], rtts: [], streams: [],
    status(text, kind) { this.statuses.push([text, kind]); }, state(v) { this.views.push(v); },
    log(text, level) { this.logs.push([text, level]); }, remoteStream(s, t) { this.streams.push([s, t]); },
    memoryLists: [], memories(list) { this.memoryLists.push(list); },
    lossEvents: [], lossLists: [], lossRecorded(e) { this.lossEvents.push(e); }, losses(l) { this.lossLists.push(l); },
    reconnects: [], reconnecting(info) { this.reconnects.push(info); },
    alerts: [], linkAlert(kind) { this.alerts.push(kind); },
    diags: [], stats() {}, diag(t) { this.diags.push(t); }, rtt(ms) { this.rtts.push(ms); }, modes(l) { this.modeLists.push(l); },
    armed(v) { this.armedCalls.push(v); }, connected(v) { this.connectedCalls.push(v); } };
  const client = new web.TrxClient(env, ui);
  const pc = () => env.pcs[env.pcs.length - 1];
  const dc = () => pc().dc;
  const hello = (extra) => dc().onmessage({ data: JSON.stringify(Object.assign({ type: "hello", protocol: 1, client_id: "phone",
    capabilities: { modes: ["USB", "LSB", "PKTUSB"] }, tx_modes: [] }, extra || {})) });
  const state = (ptt, rig) => dc().onmessage({ data: JSON.stringify({ type: "state",
    ptt: Object.assign({ state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "" }, ptt || {}),
    rig: Object.assign({ connected: true, frequency_hz: 14200000, mode: "USB", passband_hz: 2400, strength_db: -12 }, rig || {}),
    audio: { rx_db: -23, tx_db: -90, gate_open: false }, clients: ["phone"] }) });
  const sentCommands = (name) => dc().sent.filter((m) => m.cmd === name);
  const answer = (ok, extra) => { const last = dc().sent.filter((m) => m.id !== undefined).pop();
    dc().onmessage({ data: JSON.stringify(Object.assign({ type: "result", id: last.id, ok }, extra || {})) }); };
  const connected = async (opts) => { await client.connect(Object.assign({ clientId: "phone", password: "mot de passe de test", useMic: true }, opts || {})); hello(); };
  return { env, ui, client, pc, dc, hello, state, sentCommands, answer, connected, mic };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("fonctions pures", () => {
  assert.equal(web.formatFrequency(14200000), "14 200 000 Hz");
  assert.equal(web.formatFrequency(null), "—");
  assert.deepEqual([null, 0, 20, -6, -48, -54, -100].map(web.sMeterText), ["—", "S9", "S9+20 dB", "S8", "S1", "S0", "S0"]);
  assert.equal(web.sMeterFraction(60), 1); assert.equal(web.sMeterFraction(-90), 0); assert.equal(web.sMeterFraction(null), 0);
  assert.equal(web.parseKilohertz("14 200,5"), 14200500); assert.equal(web.parseKilohertz("abc"), null);
  assert.equal(web.parseKilohertz("0"), null); assert.equal(web.parseKilohertz("99999999999"), null);
  assert.match(web.reasonText("out_of_band"), /hors des bandes/);
  assert.match(web.reasonText("code_inconnu", "x"), /code_inconnu/);
  assert.equal(web.cutText("tot"), "durée maximale d'émission atteinte"); assert.equal(web.cutText(""), "");
});

test("reconnaissance des périphériques du poste", () => {
  const rig = ["Microphone (USB Audio Device)", "Haut-parleurs (USB Audio Device)"];
  assert.equal(web.matchesRigDevice("Microphone (USB Audio Device)", rig), true);
  assert.equal(web.matchesRigDevice("Par défaut - Microphone (USB Audio Device)", rig), true);      // préfixe de Chrome
  assert.equal(web.matchesRigDevice("Default - Haut-parleurs (USB Audio Device)", rig), true);
  assert.equal(web.matchesRigDevice("MICROPHONE (usb audio device)", rig), true);                    // sans casse
  assert.equal(web.matchesRigDevice("Microphone (Realtek HD Audio Mic input)", rig), false);
  assert.equal(web.matchesRigDevice("Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)", rig), false);
  assert.equal(web.matchesRigDevice("Microphone (USB Audio Device) #2", ["usb audio"]), true);       // réglage partiel côté station
  assert.equal(web.matchesRigDevice("", rig), false); assert.equal(web.matchesRigDevice("x", []), false);
  assert.equal(web.matchesRigDevice("usb", ["Microphone (USB Audio Device)"]), false);               // libellé trop court : pas d'inférence
  assert.equal(web.matchesRigDevice("Micro", null), false);
});

test("noms lisibles des modes et message bloquant quand la station restreint l'émission", () => {
  assert.equal(web.modeLabel("PKTUSB"), "USB-D (données)"); assert.equal(web.modeLabel("USB"), "USB"); assert.equal(web.modeLabel(undefined), "—");
  const allowed = ["PKTUSB", "PKTLSB"], modes = ["USB", "LSB", "PKTUSB", "PKTLSB"];
  assert.match(web.txModeHint("USB", allowed, modes), /Émission impossible en USB.*Passe en USB-D \(données\)/);
  assert.match(web.txModeHint("LSB", allowed, modes), /Passe en LSB-D/);                   // le mode données correspondant
  assert.match(web.txModeHint("CW", allowed, modes), /Passe en USB-D/);                     // sinon le premier autorisé
  assert.equal(web.txModeHint("PKTUSB", allowed, modes), "");                                // déjà autorisé
  assert.equal(web.txModeHint("USB", [], modes), ""); assert.equal(web.txModeHint("USB", undefined, modes), "");   // pas de restriction
  assert.equal(web.txModeHint(undefined, allowed, modes), "");
  assert.match(web.reasonText("mode_not_allowed"), /mode données/); assert.match(web.cutText("mode_changed"), /mode modifié/);
});

test("restriction d'émission : vue bloquée en USB, libre en USB-D, mode affiché lisiblement", async () => {
  const w = makeWorld();
  await w.connected(); w.hello({ tx_modes: ["PKTUSB", "PKTLSB"] }); w.state();
  let v = w.ui.views.at(-1);
  assert.equal(v.txBlocked, true); assert.match(v.dataModeHint, /Passe en USB-D/); assert.equal(v.mode, "USB");
  w.state({}, { mode: "PKTUSB" });
  v = w.ui.views.at(-1);
  assert.equal(v.txBlocked, false); assert.equal(v.dataModeHint, ""); assert.equal(v.mode, "USB-D (données)");
  const free = makeWorld();
  await free.connected(); free.state();                                                       // sans restriction : seul l'indice doux
  assert.equal(free.ui.views.at(-1).txBlocked, false); assert.match(free.ui.views.at(-1).dataModeHint, /USB-D/);
});

test("indice du mode données", () => {
  const modes = ["USB", "LSB", "PKTUSB", "PKTLSB"];
  assert.match(web.dataModeHint("USB", modes), /USB-D \(données\)/);
  assert.equal(web.dataModeHint("PKTUSB", modes), "");                       // déjà en mode données
  assert.equal(web.dataModeHint("FM", modes), "");                           // PKTFM non proposé par ce poste
  assert.equal(web.dataModeHint("USB", []), ""); assert.equal(web.dataModeHint(undefined, modes), "");
});

test("modes données selon la version de Hamlib (4.7 : FM-D, AM-D)", () => {
  const modes = ["AM", "CW", "USB", "LSB", "FM", "PKTLSB", "PKTUSB", "FM-D", "AM-D"];      // IC-7300MK2, Hamlib 4.7.2
  assert.equal(web.dataModeFor("FM", modes), "FM-D"); assert.equal(web.dataModeFor("AM", modes), "AM-D");
  assert.equal(web.dataModeFor("FM", ["PKTFM"]), "PKTFM"); assert.equal(web.dataModeFor("CW", modes), null);
  assert.match(web.dataModeHint("FM", modes), /FM-D \(données\)/);
  assert.equal(web.modeLabel ? web.modeLabel("FM-D") : web.MODE_LABELS["FM-D"], "FM-D (données)");
  assert.equal(web.adaptMode("FM", ["PKTUSB", "PKTLSB", "FM-D", "AM-D"], modes), "FM-D");
  assert.equal(web.adaptMode("FM", ["PKTUSB", "PKTLSB", "PKTFM", "PKTAM"], modes), null);     // ancien réglage : refus, pas d'erreur
});

test("micro choisi : identifiant exact demandé, nom affiché dans le journal", async () => {
  const w = makeWorld();
  await w.connected({ micDeviceId: "abc123" });
  assert.deepEqual(w.env.constraints.audio.deviceId, { exact: "abc123" });
  assert.ok(w.ui.logs.some(([t]) => /Micro utilisé : Microphone \(Realtek HD Audio Mic input\)/.test(t)));
  const free = makeWorld();
  await free.connected();
  assert.equal(free.env.constraints.audio.deviceId, undefined);               // périphérique par défaut
});

test("micro = entrée/sortie audio du poste : REFUSÉ (la réception serait renvoyée dans l'émission)", async () => {
  const w = makeWorld();
  w.mic.label = "Par défaut - Microphone (USB Audio Device)";
  await w.connected();
  assert.equal(w.pc().tracks.length, 0); assert.equal(w.pc().transceivers[0].opts.direction, "recvonly");
  assert.equal(w.mic.stopped, true); assert.equal(w.client.micTrack, null);
  assert.ok(w.ui.logs.some(([t, l]) => /Micro REFUSÉ/.test(t) && l === "bad"));
  const before = w.mic.enabled;
  w.state({ state: "TX", owner: "phone" });                                   // même en émission : la piste refusée n'est jamais rouverte
  assert.equal(w.mic.enabled, before); assert.equal(w.pc().tracks.length, 0);
  const forced = makeWorld();
  forced.mic.label = "Microphone (USB Audio Device)";
  await forced.connected({ ignoreRigWarning: true });                         // l'utilisateur affirme que ce n'est pas le poste
  assert.equal(forced.pc().tracks.length, 1); assert.equal(forced.mic.stopped, false);
});

test("sans liste de périphériques du poste (config indisponible ou fichiers de test) : aucun refus", async () => {
  const w = makeWorld({ getConfig: async () => ({ ice_servers: [] }) });
  w.mic.label = "Microphone (USB Audio Device)";
  await w.connected();
  assert.equal(w.pc().tracks.length, 1);
});

test("écran maintenu allumé : verrou pris à la connexion, repris au retour au premier plan, relâché à la déconnexion", async () => {
  const w = makeWorld();
  await w.connected();
  await new Promise((r) => setImmediate(r));
  assert.equal(w.env.locks.length, 1); assert.equal(w.client.wakeLock, w.env.locks[0]);
  assert.ok(w.ui.logs.some(([t]) => /Écran maintenu allumé/.test(t)));
  w.env.locks[0].release();                                                  // le navigateur relâche le verrou quand la page est masquée
  assert.equal(w.client.wakeLock, null);
  w.client.onVisibility(false);                                              // retour au premier plan : un nouveau verrou
  await new Promise((r) => setImmediate(r));
  assert.equal(w.env.locks.length, 2); assert.equal(w.client.wakeLock, w.env.locks[1]);
  assert.equal(w.ui.logs.filter(([t]) => /Écran maintenu allumé/.test(t)).length, 1);   // annoncé une seule fois
  w.client.disconnect();
  assert.equal(w.env.locks[1].released, true); assert.equal(w.client.wakeLock, null);
});

test("écran maintenu allumé : désactivé, indisponible ou refusé n'empêche jamais la connexion", async () => {
  const off = makeWorld();
  await off.connected({ keepAwake: false });
  await new Promise((r) => setImmediate(r));
  assert.equal(off.env.locks.length, 0);
  const unsupported = makeWorld({ requestWakeLock: null });
  await unsupported.connected();
  unsupported.client.onVisibility(false); unsupported.client.onVisibility(false);
  assert.equal(unsupported.ui.logs.filter(([t, l]) => /indisponible/.test(t) && l === "warn").length, 1);   // un seul avertissement
  assert.equal(unsupported.client.connected, true);
  const denied = makeWorld({ requestWakeLock: async () => { const e = new Error("non"); e.name = "NotAllowedError"; throw e; } });
  await denied.connected();
  await new Promise((r) => setImmediate(r));
  assert.ok(denied.ui.logs.some(([t, l]) => /NotAllowedError/.test(t) && l === "warn")); assert.equal(denied.client.connected, true);
  const lateLock = makeWorld();
  await lateLock.connected();
  await new Promise((r) => setImmediate(r));
  lateLock.client.disconnect();
  lateLock.client.onVisibility(false);                                       // déconnecté : aucun nouveau verrou
  await new Promise((r) => setImmediate(r));
  assert.equal(lateLock.env.locks.length, 1);
});

test("l'indice du mode données est dans la vue", async () => {
  const w = makeWorld();
  await w.connected(); w.state();
  assert.match(w.ui.views.at(-1).dataModeHint, /USB-D/);
  w.state({}, { mode: "PKTUSB" });
  assert.equal(w.ui.views.at(-1).dataModeHint, "");
});

test("diagnostic audio : statistiques transmises à l'interface", async () => {
  const w = makeWorld({ collectStats: async () => ({ net: "RTT réseau 3 ms", diag: "son reçu : 120 paquets, niveau 12 %" }) });
  await w.connected();
  w.env.advance(3000); w.env.tick();
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(w.ui.diags, ["son reçu : 120 paquets, niveau 12 %"]);
});

test("connexion avec micro : micro fermé, mot de passe envoyé une seule fois", async () => {
  const w = makeWorld();
  await w.connected();
  assert.equal(w.env.offers.length, 1);
  assert.deepEqual(Object.keys(w.env.offers[0]).sort(), ["client_id", "password", "sdp", "type"]);
  assert.equal(w.env.offers[0].password, "mot de passe de test"); assert.equal(JSON.stringify(w.env.offers[0]).includes("token"), false);
  assert.equal(w.pc().dc.label, "control"); assert.equal(w.pc().tracks.length, 1);
  assert.equal(w.mic.enabled, false);                                       // fermé tant que l'émission n'est pas confirmée
  assert.equal(w.env.constraints.audio.autoGainControl, false);
  assert.equal(w.client.connected, true); assert.deepEqual(w.ui.modeLists.at(-1), ["USB", "LSB", "PKTUSB"]);
  assert.equal(w.env.activeIntervals(), 1);
});

test("page non sécurisée : réception seule, avertissement, pas de micro demandé", async () => {
  const w = makeWorld({ isSecureContext: false });
  await w.connected();
  assert.equal(w.pc().tracks.length, 0); assert.equal(w.pc().transceivers[0].opts.direction, "recvonly");
  assert.ok(w.ui.logs.some(([t, l]) => /HTTPS/.test(t) && l === "warn"));
  assert.equal(w.env.constraints, undefined);
});

test("micro refusé : réception seule, la connexion continue", async () => {
  const w = makeWorld({ getUserMedia: async () => { const e = new Error("non"); e.name = "NotAllowedError"; throw e; } });
  await w.connected();
  assert.equal(w.pc().transceivers[0].opts.direction, "recvonly"); assert.equal(w.client.connected, true);
  assert.ok(w.ui.logs.some(([t]) => /NotAllowedError/.test(t)));
});

test("serveurs ICE : ceux de la station, ou aucun si la configuration est indisponible", async () => {
  const w = makeWorld();
  await w.connected();
  assert.deepEqual(w.pc().config, { iceServers: [{ urls: "stun:stun.example.org:3478" }] });
  const vpn = makeWorld({ getConfig: async () => ({ ice_servers: [] }) });
  await vpn.connected();
  assert.deepEqual(vpn.pc().config, { iceServers: [] });
  const down = makeWorld({ getConfig: async () => { throw new Error("config 500"); } });
  await down.connected();
  assert.deepEqual(down.pc().config, { iceServers: [] });
  assert.ok(down.ui.logs.some(([t, l]) => /sans serveur STUN/.test(t) && l === "warn"));
});

test("identifiants refusés (401) : erreur claire, connexion nettoyée", async () => {
  const w = makeWorld({ offerStatus: 401 });
  await assert.rejects(() => w.client.connect({ clientId: "phone", password: "faux", useMic: false }), /mot de passe refusé/);
  assert.equal(w.env.pcs[0].closed, true);
  assert.equal(w.client.connected, false); assert.deepEqual(w.ui.statuses.at(-1), ["Erreur", "bad"]);
  const busy = makeWorld({ offerStatus: 503 });
  await assert.rejects(() => busy.client.connect({ clientId: "a", password: "b", useMic: false }), /occupée/);
});

test("l'état met l'affichage à jour (fréquence, S-mètre, mode, niveaux)", async () => {
  const w = makeWorld();
  await w.connected();
  w.state();
  const v = w.ui.views.at(-1);
  assert.equal(v.frequency, "14 200 000 Hz"); assert.equal(v.mode, "USB"); assert.equal(v.passband, "2400 Hz");
  assert.equal(v.sText, "S7"); assert.equal(v.pttLabel, "RÉCEPTION"); assert.equal(v.mine, false); assert.equal(v.rxLevel, "-23 dBFS");
});

test("PTT refusé tant que l'émission n'est pas autorisée", async () => {
  const w = makeWorld();
  await w.connected(); w.state();
  assert.equal(await w.client.pressPtt(), null);
  assert.equal(w.sentCommands("toggle").length, 0);
  assert.ok(w.ui.logs.some(([t, l]) => /Émission autorisée/.test(t) && l === "warn"));
});

test("PTT autorisé : toggle envoyé, micro ouvert seulement en TX confirmé et propriétaire, heartbeats pendant l'émission", async () => {
  const w = makeWorld();
  await w.connected(); w.state(); w.client.setArmed(true);
  const pending = w.client.pressPtt();
  assert.equal(w.sentCommands("toggle").length, 1);
  w.answer(true, { ptt: { state: "TX" } });
  assert.equal((await pending).ok, true);
  w.env.tick();                                                              // heartbeats dès la demande (période de grâce)
  assert.ok(w.sentCommands("heartbeat").length >= 1);
  assert.equal(w.mic.enabled, false);                                        // pas encore confirmé par l'état
  w.state({ state: "TX", owner: "phone", tot_remaining_s: 80 });
  assert.equal(w.mic.enabled, true);
  const before = w.sentCommands("heartbeat").length;
  for (let i = 0; i < 20; i++) { w.env.advance(500); w.state({ state: "TX", owner: "phone", tot_remaining_s: 80 }); w.env.tick(); }   // 10 s : la station parle sans cesse
  assert.ok(w.sentCommands("heartbeat").length >= before + 2);               // continue bien après la période de grâce
  assert.equal(w.ui.views.at(-1).mine, true); assert.equal(w.ui.views.at(-1).tot, 80);
});

test("pas de heartbeat tant qu'on n'émet pas ; micro fermé si l'émission appartient à un autre", async () => {
  const w = makeWorld();
  await w.connected(); w.state();
  for (let i = 0; i < 5; i++) { w.env.advance(500); w.env.tick(); }
  assert.equal(w.sentCommands("heartbeat").length, 0);
  w.state({ state: "TX", owner: "car" });
  assert.equal(w.mic.enabled, false);
  assert.equal(w.ui.views.at(-1).other, true);
  assert.equal(await w.client.pressPtt(), null);                             // non propriétaire : pas de toggle
  assert.equal(w.sentCommands("toggle").length, 0);
});

test("fin d'émission : le micro se ferme, la case « Émission autorisée » RESTE cochée", async () => {
  const w = makeWorld();
  await w.connected(); w.state(); w.client.setArmed(true);
  const callsBefore = w.ui.armedCalls.length;
  w.state({ state: "TX", owner: "phone" });
  assert.equal(w.mic.enabled, true); assert.equal(w.client.armed, true);
  w.state({ state: "RX", owner: null, last_cut_reason: "tot" });
  assert.equal(w.mic.enabled, false);                                         // le micro, lui, se ferme toujours
  assert.equal(w.client.armed, true); assert.equal(w.ui.armedCalls.length, callsBefore);   // aucun désarmement automatique
  assert.ok(w.ui.logs.some(([t]) => /durée maximale/.test(t)));
  const again = w.client.pressPtt(); w.answer(true); await again;             // l'émission suivante n'exige pas de recocher
  assert.equal(w.sentCommands("toggle").length, 1);
  w.client.disconnect();
  assert.equal(w.client.armed, false);                                        // mais une déconnexion remet tout à zéro
});

test("refus de la station : message en français, plus de heartbeats", async () => {
  const w = makeWorld();
  await w.connected(); w.state(); w.client.setArmed(true);
  const pending = w.client.pressPtt();
  w.answer(false, { reason: "out_of_band", detail: "27.495 MHz" });
  assert.equal((await pending).ok, false);
  assert.ok(w.ui.logs.some(([t, l]) => /hors des bandes/.test(t) && l === "warn"));
  const before = w.sentCommands("heartbeat").length;
  w.env.advance(5000); w.env.tick();
  assert.equal(w.sentCommands("heartbeat").length, before);
});

test("STOP : toujours possible, même sans autorisation ni propriété", async () => {
  const w = makeWorld();
  await w.connected(); w.state({ state: "TX", owner: "car" });
  const pending = w.client.stop();
  assert.equal(w.sentCommands("stop").length, 1);
  w.answer(true); await pending;
});

test("page masquée pendant l'émission : STOP envoyé", async () => {
  const w = makeWorld();
  await w.connected(); w.state({ state: "TX", owner: "phone" });
  w.client.onVisibility(true);
  assert.equal(w.sentCommands("stop").length, 1);
  assert.ok(w.ui.logs.some(([t]) => /masquée/.test(t)));
  const idle = makeWorld();
  await idle.connected(); idle.state();
  idle.client.onVisibility(true);
  assert.equal(idle.sentCommands("stop").length, 0);                         // rien à couper
});

test("accord : validation côté client et envoi de set_frequency / set_mode", async () => {
  const w = makeWorld();
  await w.connected(); w.state();
  const f = w.client.setFrequency(7074000);
  assert.deepEqual(w.sentCommands("set_frequency").at(-1).hz, 7074000); w.answer(true); await f;
  const m = w.client.setMode("LSB", 2400);
  assert.equal(w.sentCommands("set_mode").at(-1).mode, "LSB"); w.answer(false, { reason: "tx_active" }); await m;
  assert.ok(w.ui.logs.some(([t]) => /verrouillés/.test(t)));
});

test("commande sans réponse : échec après le délai, sans bloquer", async () => {
  const w = makeWorld();
  await w.connected(); w.state();
  const p = w.client.setFrequency(7074000);
  w.env.fireTimeouts();
  await assert.rejects(p, /pas de réponse/);
});

test("ping : mesure le temps de réponse de la station", async () => {
  const w = makeWorld();
  await w.connected();
  w.env.advance(3000); w.env.tick();
  w.env.advance(42); w.answer(true, { state: {} });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(w.ui.rtts, [42]);
});

test("déconnexion et perte de connexion : micro arrêté, minuterie stoppée, rien ne reste actif", async () => {
  const w = makeWorld();
  await w.connected(); w.state({ state: "TX", owner: "phone" });
  w.pc().connectionState = "failed"; w.pc().onconnectionstatechange();
  assert.equal(w.client.connected, false); assert.equal(w.mic.stopped, true);
  assert.equal(w.env.activeIntervals(), 0); assert.equal(w.env.pcs[0].closed, true);
  assert.ok(w.ui.logs.some(([t, l]) => /coupée par la station/.test(t) && l === "bad"));
  const before = w.sentCommands("heartbeat").length;
  w.env.tick();
  assert.equal(w.sentCommands("heartbeat").length, before);
  const d = makeWorld();
  await d.connected(); d.client.disconnect();
  assert.equal(d.client.connected, false); assert.equal(d.ui.connectedCalls.at(-1), false);
});

test("reconnexion : l'ancienne connexion est fermée et une seule minuterie reste active", async () => {
  const w = makeWorld();
  await w.connected();
  await w.client.connect({ clientId: "phone", password: "autre mot de passe", useMic: true }); w.hello();
  assert.equal(w.env.pcs.length, 2); assert.equal(w.env.pcs[0].closed, true); assert.equal(w.env.activeIntervals(), 1);
});

test("messages mal formés ou inconnus : ignorés sans exception", async () => {
  const w = makeWorld();
  await w.connected();
  w.dc().onmessage({ data: "pas du json" });
  w.dc().onmessage({ data: JSON.stringify({ type: "inconnu" }) });
  w.dc().onmessage({ data: JSON.stringify({ type: "error", code: "rate_limited" }) });
  assert.ok(w.ui.logs.some(([t]) => /rate_limited/.test(t)));
});


test("spectre HF : la page prévient du retour au mode normal, une seule fois, puis du rétablissement", async () => {
  const w = makeWorld();
  await w.connected();
  const send = (spectrum) => w.dc().onmessage({ data: JSON.stringify({ type: "state",
    ptt: { state: "RX", owner: null, tot_remaining_s: null, tot_warning: false, last_cut_reason: "", fault: "" },
    rig: { connected: true, frequency_hz: 14200000, mode: "USB", passband_hz: 2400, strength_db: -12 },
    audio: {}, clients: ["phone"], spectrum }) });
  const spectrumLogs = () => w.ui.logs.filter(([text]) => text.startsWith("Spectre HF"));
  send({ state: "waiting", code: "", message: "" }); send({ state: "ok", code: "", message: "" });
  assert.equal(spectrumLogs().length, 0);                                  // démarrage normal : rien à signaler
  const problem = { state: "error", code: "no_answer", message: "Aucune réponse CI-V sur COM7. Mode normal : un seul port, sans waterfall HF." };
  send(problem); send(problem); send(problem);
  assert.equal(spectrumLogs().length, 1);
  assert.match(spectrumLogs()[0][0], /problème de configuration.*Mode normal/); assert.equal(spectrumLogs()[0][1], "warn");
  send({ state: "ok", code: "", message: "" });
  assert.match(spectrumLogs().at(-1)[0], /de nouveau disponible/);
  w.state();                                                               // station sans spectre : aucun message
  assert.equal(spectrumLogs().length, 2);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("OK    " + name); }
    catch (err) { failed++; console.log("ECHEC " + name + "\n      " + (err && err.stack ? err.stack.split("\n").slice(0, 4).join("\n      ") : err)); }
  }
  console.log(`${tests.length - failed}/${tests.length} tests JavaScript réussis`);
  process.exit(failed ? 1 : 0);
})();


// --------------------------------------------------------------------------- afficheur, mémoires, squelch, indicateurs

test("fréquence au format des postes : MHz.kHz.10 Hz", () => {
  assert.equal(web.formatIcomFrequency(3822500), "3.822.50");
  assert.equal(web.formatIcomFrequency(14200000), "14.200.00");
  assert.equal(web.formatIcomFrequency(144300000), "144.300.00");
  assert.equal(web.formatIcomFrequency(7074000), "7.074.00");
  assert.equal(web.formatIcomFrequency(500000), "0.500.00");
  assert.equal(web.formatIcomFrequency(28074010), "28.074.01");
  assert.equal(web.formatIcomFrequency(null), "—"); assert.equal(web.formatIcomFrequency(undefined), "—"); assert.equal(web.formatIcomFrequency(NaN), "—");
});

test("noms courts des modes, étiquettes AGC et préampli", () => {
  assert.equal(web.shortMode("PKTUSB"), "USB-D"); assert.equal(web.shortMode("LSB"), "LSB"); assert.equal(web.shortMode(null), "—");
  assert.equal(web.AGC_LABELS[2], "AGC-F"); assert.equal(web.AGC_LABELS[6], "AGC-A");
  assert.equal(web.preampText(0), "P.AMP"); assert.equal(web.preampText(10), "P.AMP 10"); assert.equal(web.preampText(20), "P.AMP 20");
});

test("mémoires : favorites d'abord, puis par fréquence, le tri ne modifie pas la liste d'origine", () => {
  const list = [
    { id: "a", name: "Quarante", hz: 7100000, mode: "LSB", favorite: false },
    { id: "b", name: "Vingt", hz: 14200000, mode: "PKTUSB", favorite: false },
    { id: "c", name: "Dix", hz: 28400000, mode: "USB", favorite: true },
    { id: "d", name: "Quatre-vingts", hz: 3650000, mode: "LSB", favorite: true },
    { id: "e", name: "Bis", hz: 7100000, mode: "LSB", favorite: false },
  ];
  assert.deepEqual(web.sortMemories(list).map((m) => m.id), ["d", "c", "e", "a", "b"]);       // favorites, puis fréquence, puis nom
  assert.deepEqual(list.map((m) => m.id), ["a", "b", "c", "d", "e"]);
  assert.deepEqual(web.sortMemories(null), []); assert.deepEqual(web.sortMemories(undefined), []); assert.deepEqual(web.sortMemories("texte"), []);
  assert.deepEqual(web.sortMemories([null, 5, "x", { id: "a" }, { id: "b", name: "ok", hz: "14" }, list[0]]).map((m) => m.id), ["a"]);   // éléments mal formés écartés
});

test("disposition : portrait par défaut, paysage proposé (automatique seulement si l'écran est assez large)", () => {
  assert.equal(web.chooseLayout("portrait", true, 1200), "portrait");
  assert.equal(web.chooseLayout("landscape", false, 360), "landscape");
  assert.equal(web.chooseLayout("auto", false, 900), "portrait");              // écran large mais tenu en portrait
  assert.equal(web.chooseLayout("auto", true, 800), "landscape");
  assert.equal(web.chooseLayout("auto", true, 500), "portrait");               // petit téléphone couché : trop étroit pour deux colonnes
  assert.equal(web.chooseLayout(undefined, true, 800), "landscape"); assert.equal(web.chooseLayout("n'importe quoi", false, 800), "portrait");
});

test("mémoires : liste reçue à la connexion, mise à jour par la station, vidée à la déconnexion", async () => {
  const w = makeWorld();
  await w.connected();
  w.hello({ memories: [{ id: "a", name: "Vingt", hz: 14200000, mode: "USB", favorite: false },
                       { id: "b", name: "Quatre-vingts", hz: 3700000, mode: "LSB", favorite: true }] });
  assert.deepEqual(w.ui.memoryLists.at(-1).map((m) => m.id), ["b", "a"]);      // favorite en tête
  assert.deepEqual(w.client.memories.map((m) => m.id), ["b", "a"]);
  w.dc().onmessage({ data: JSON.stringify({ type: "memories", items: [{ id: "c", name: "Dix", hz: 28400000, mode: "USB", favorite: false }] }) });
  assert.deepEqual(w.ui.memoryLists.at(-1).map((m) => m.id), ["c"]);
  w.dc().onmessage({ data: JSON.stringify({ type: "memories", items: "n'importe quoi" }) });     // message mal formé : liste vide, pas d'exception
  assert.deepEqual(w.ui.memoryLists.at(-1), []);
  w.client.disconnect();
  assert.deepEqual(w.ui.memoryLists.at(-1), []); assert.deepEqual(w.client.memories, []);
});

test("mémoires : enregistrer, modifier, supprimer, rappeler envoient les bonnes commandes", async () => {
  const w = makeWorld();
  await w.connected(); w.state();
  let pending = w.client.saveMemory({ name: "Réseau 40 m", hz: 7100000, mode: "LSB", favorite: true });
  w.answer(true, { memory: { id: "x1" } });
  assert.equal((await pending).ok, true);
  const first = w.sentCommands("memory_save")[0];
  assert.deepEqual([first.name, first.hz, first.mode, first.favorite, "memory_id" in first], ["Réseau 40 m", 7100000, "LSB", true, false]);   // création : pas de memory_id
  pending = w.client.saveMemory({ memoryId: "x1", name: "Renommée", hz: 7105000, mode: "LSB", favorite: false });
  w.answer(true);
  await pending;
  assert.equal(w.sentCommands("memory_save").at(-1).memory_id, "x1");
  pending = w.client.recallMemory("x1"); w.answer(true); await pending;
  assert.equal(w.sentCommands("memory_recall").at(-1).memory_id, "x1");
  pending = w.client.deleteMemory("x1"); w.answer(true); await pending;
  assert.equal(w.sentCommands("memory_delete").at(-1).memory_id, "x1");
});

test("mémoires : refus de la station affichés en français (rappel pendant l'émission, mémoire disparue)", async () => {
  const w = makeWorld();
  await w.connected(); w.state();
  let pending = w.client.recallMemory("x1");
  w.answer(false, { reason: "tx_active" });
  assert.equal((await pending).ok, false);
  assert.ok(w.ui.logs.some(([t, l]) => /pendant l'émission/.test(t) && l === "warn"));
  pending = w.client.recallMemory("zz"); w.answer(false, { reason: "unknown_memory" }); await pending;
  assert.ok(w.ui.logs.some(([t]) => /n'existe plus/.test(t)));
  pending = w.client.saveMemory({ name: "x", hz: 1, mode: "USB" }); w.answer(false, { reason: "storage_error", detail: "disque plein" }); await pending;
  assert.ok(w.ui.logs.some(([t]) => /pas pu enregistrer/.test(t)));
});

test("squelch : commande set_squelch avec une valeur de 0 à 1", async () => {
  const w = makeWorld();
  await w.connected(); w.state();
  const pending = w.client.setSquelch(0.35);
  w.answer(true);
  assert.equal((await pending).ok, true);
  assert.equal(w.sentCommands("set_squelch").at(-1).value, 0.35);
  const refused = w.client.setSquelch(0.9); w.answer(false, { reason: "rig_error", detail: "RPRT -11" }); await refused;
  assert.ok(w.ui.logs.some(([, l]) => l === "warn"));
});

test("boutons de commande : NR, NB, préampli, IP+, AGC, compresseur, filtre, tuner — seulement ceux que le poste fournit", async () => {
  const w = makeWorld();
  await w.connected(); w.hello({ capabilities: { modes: ["USB"], filters: { USB: [3000, 2400, 1800] }, preamps: [10, 20] } });
  w.state({}, { functions: { NR: false, NB: true, AIP: true, COMP: false, TUNER: false }, levels: { PREAMP: 10, AGC: 2, SQL: 0.25 } });
  const v = w.ui.views.at(-1);
  assert.deepEqual(v.controls.map((c) => [c.key, c.label, c.on]), [["NR", "NR", false], ["NB", "NB", true], ["PREAMP", "P.AMP 10", true], ["AIP", "IP+", true],
    ["AGC", "AGC-F", true], ["COMP", "COMP", false], ["FIL", "FIL 2.4k", true], ["TUNER", "TUNER", false]]);
  assert.equal(v.squelch, 0.25);
  w.state({}, { functions: { NB: false }, levels: { PREAMP: 0 } });          // un poste qui ne fournit presque rien : pas de bouton inventé
  const v2 = w.ui.views.at(-1);
  assert.deepEqual(v2.controls.map((c) => [c.key, c.on]), [["NB", false], ["PREAMP", false], ["FIL", true]]);
  assert.equal(v2.squelch, null);
  w.state({}, {});
  assert.deepEqual(w.ui.views.at(-1).controls.map((c) => c.key), ["FIL"]);   // seule la largeur du filtre est connue (passband), rien d'autre
  w.state({}, { passband_hz: 0 });
  assert.deepEqual(w.ui.views.at(-1).controls, []);                           // largeur inconnue : pas de bouton de filtre
});

test("boutons de commande : verrouillés pendant l'émission", async () => {
  const w = makeWorld();
  await w.connected(); w.state({}, { functions: { NR: false } });
  assert.equal(w.ui.views.at(-1).controlsLocked, false);
  w.state({ state: "TX", owner: "phone" }, { functions: { NR: false } });
  assert.equal(w.ui.views.at(-1).controlsLocked, true);
  const before = w.sentCommands("set_function").length;
  const res = await w.client.pressControl("NR");                              // refusé sans même interroger la station
  assert.equal(res.ok, false); assert.equal(w.sentCommands("set_function").length, before);
  assert.ok(w.ui.logs.some(([t, l]) => /pendant l'émission/.test(t) && l === "warn"));
});

test("NR, NB, IP+, compresseur, tuner : bascule vers l'état inverse de celui du poste", async () => {
  const w = makeWorld();
  await w.connected(); w.state({}, { functions: { NR: false, NB: true, COMP: false, TUNER: true } });
  for (const [key, expected] of [["NR", true], ["NB", false], ["COMP", true], ["TUNER", false]]) {
    const pending = w.client.pressControl(key); w.answer(true); await pending;
    const sent = w.sentCommands("set_function").at(-1);
    assert.deepEqual([sent.name, sent.on], [key, expected]);
  }
  const unknown = w.client.pressControl("AIP"); w.answer(true); await unknown;      // état inconnu : on le met en service
  assert.equal(w.sentCommands("set_function").at(-1).on, true);
});

test("préampli : cycle arrêt puis les valeurs du poste puis arrêt ; sans liste, 10 dB", async () => {
  const w = makeWorld();
  await w.connected(); w.hello({ capabilities: { modes: ["USB"], preamps: [10, 20] } });
  const seen = [];
  for (const level of [0, 10, 20, 7]) {
    w.state({}, { levels: { PREAMP: level } });
    const pending = w.client.pressControl("PREAMP"); w.answer(true); await pending;
    seen.push(w.sentCommands("set_level").at(-1).value);
  }
  assert.deepEqual(seen, [10, 20, 0, 0]);                                     // une valeur inconnue (7) : on revient à l'arrêt, le plus sûr
  const bare = makeWorld();
  await bare.connected(); bare.state({}, { levels: { PREAMP: 0 } });
  const p = bare.client.pressControl("PREAMP"); bare.answer(true); await p;
  assert.equal(bare.sentCommands("set_level").at(-1).value, 10);
  assert.equal(bare.sentCommands("set_level").at(-1).name, "PREAMP");
});

test("AGC : rapide, moyen, lent puis retour", async () => {
  const w = makeWorld();
  await w.connected();
  const seen = [];
  for (const level of [2, 5, 3, 1, 0]) {
    w.state({}, { levels: { AGC: level } });
    const pending = w.client.pressControl("AGC"); w.answer(true); await pending;
    seen.push(w.sentCommands("set_level").at(-1).value);
  }
  assert.deepEqual(seen, [5, 3, 2, 2, 2]);                                    // hors cycle (superrapide, arrêt) : on repart de RAPIDE
  assert.equal(w.sentCommands("set_level").at(-1).name, "AGC");
  assert.deepEqual(web.AGC_CYCLE, [2, 5, 3]);
});

test("filtre de réception : passe à la largeur suivante du mode, par set_mode", async () => {
  const w = makeWorld();
  await w.connected(); w.hello({ capabilities: { modes: ["USB", "CW"], filters: { USB: [3000, 2400, 1800], CW: [1200, 500, 250] } } });
  const seen = [];
  for (const passband of [3000, 2400, 1800]) {
    w.state({}, { mode: "USB", passband_hz: passband });
    const pending = w.client.pressControl("FIL"); w.answer(true); await pending;
    const sent = w.sentCommands("set_mode").at(-1);
    seen.push([sent.mode, sent.passband]);
  }
  assert.deepEqual(seen, [["USB", 2400], ["USB", 1800], ["USB", 3000]]);
  w.state({}, { mode: "CW", passband_hz: 480 });                              // largeur réelle proche de 500 Hz : suivante = 250
  const cw = w.client.pressControl("FIL"); w.answer(true); await cw;
  assert.deepEqual([w.sentCommands("set_mode").at(-1).mode, w.sentCommands("set_mode").at(-1).passband], ["CW", 250]);
  w.state({}, { mode: "FM", passband_hz: 12000 });                            // mode sans liste de largeurs : rien n'est envoyé
  const before = w.sentCommands("set_mode").length;
  assert.equal((await w.client.pressControl("FIL")).ok, false); assert.equal(w.sentCommands("set_mode").length, before);
});

test("étiquette du filtre et repère de squelch sur l'échelle du S-mètre", () => {
  assert.equal(web.formatWidth(2400), "2.4k"); assert.equal(web.formatWidth(3000), "3k"); assert.equal(web.formatWidth(500), "500");
  assert.equal(web.filterLabel([3000, 2400, 1800], 2400), "FIL 2.4k"); assert.equal(web.filterLabel([3000, 2400, 1800], 2450), "FIL 2.4k");
  assert.equal(web.filterLabel([3000, 2400, 1800], 1000), "FIL 1k");                                  // largeur personnalisée : affichée telle quelle
  assert.equal(web.nearestIndex([3000, 2400, 1800], 1900), 2); assert.equal(web.nearestIndex([], 1), -1);
  assert.equal(web.squelchMarkerFraction(0), null); assert.equal(web.squelchMarkerFraction(null), null); assert.equal(web.squelchMarkerFraction(undefined), null);
  assert.ok(Math.abs(web.squelchMarkerFraction(120 / 255) - 54 / 114) < 1e-9);                          // 120/255 = S9
  assert.ok(Math.abs(web.squelchMarkerFraction(241 / 255) - 1) < 1e-9); assert.equal(web.squelchMarkerFraction(1), 1);
  assert.ok(web.squelchMarkerFraction(0.1) < web.squelchMarkerFraction(0.3) && web.squelchMarkerFraction(0.3) < web.squelchMarkerFraction(0.6));
  assert.equal(web.squelchMarkerFraction(-0.5), null); assert.equal(web.squelchMarkerFraction(2), 1);
});

test("repère de squelch : seulement quand le squelch est activé", async () => {
  const w = makeWorld();
  await w.connected();
  w.state({}, { levels: { SQL: 0 } });
  assert.equal(w.ui.views.at(-1).squelchMark, null);
  w.state({}, { levels: { SQL: 0.47 } });
  assert.ok(Math.abs(w.ui.views.at(-1).squelchMark - web.squelchMarkerFraction(0.47)) < 1e-9 && w.ui.views.at(-1).squelchMark > 0.4);
  w.state({}, {});
  assert.equal(w.ui.views.at(-1).squelchMark, null);
});

test("puissance, ROS et ALC : graphiques bornés à l'échelle, et seulement quand le poste les fournit", async () => {
  const w = makeWorld();
  await w.connected();
  w.state({ state: "TX", owner: "phone" }, { levels: { RFPOWER_METER: 0.42, SWR: 1.3, ALC: 0.1, COMP_METER: 6, VD_METER: 13.8, TEMP_METER: 31, ATT: 0, AGC: 3 } });
  const v = w.ui.views.at(-1);
  assert.equal(v.power, 0.42); assert.equal(v.powerText, "42 %");
  assert.equal(v.swr.text, "1.3"); assert.ok(Math.abs(v.swr.fraction - 0.15) < 1e-9);
  assert.equal(v.alc.text, "10 %"); assert.ok(Math.abs(v.alc.fraction - 0.1) < 1e-9);
  const byKey = Object.fromEntries(v.instruments.map((i) => [i.key, i]));
  assert.ok(!("SWR" in byKey) && !("ALC" in byKey) && !("AGC" in byKey));                              // plus en doublon dans la partie défilante
  assert.equal(byKey.VD_METER.text, "13.8 V"); assert.equal(byKey.TEMP_METER.text, "31 °C"); assert.equal(byKey.ATT.text, "off"); assert.equal(byKey.COMP_METER.text, "6.0 dB");
  w.state({}, { levels: { RFPOWER_METER: 7, SWR: 99, ALC: -3 } });                                      // valeurs aberrantes : l'échelle ne déborde jamais
  const wild = w.ui.views.at(-1);
  assert.equal(wild.power, 1); assert.equal(wild.swr.fraction, 1); assert.equal(wild.alc.fraction, 0);
  w.state({}, {});
  const none = w.ui.views.at(-1);
  assert.equal(none.power, null); assert.equal(none.powerText, "—"); assert.equal(none.swr, null); assert.equal(none.alc, null);
  assert.deepEqual(none.instruments, []);
});

test("l'afficheur reçoit la fréquence au format du poste et le mode court", async () => {
  const w = makeWorld();
  await w.connected(); w.state({}, { frequency_hz: 3822500, mode: "PKTLSB" });
  const v = w.ui.views.at(-1);
  assert.equal(v.frequencyIcom, "3.822.50"); assert.equal(v.modeShort, "LSB-D");
});



// --------------------------------------------------------------------------- puissance d'émission

test("puissance : étiquette en watts quand le maximum est connu, sinon en pourcentage", () => {
  assert.equal(web.powerLabel(0.25, 100), "PWR 25W"); assert.equal(web.powerLabel(0.05, 100), "PWR 5W"); assert.equal(web.powerLabel(1, 100), "PWR 100W");
  assert.equal(web.powerLabel(0.05, 50), "PWR 2.5W"); assert.equal(web.powerLabel(0.8, 100), "PWR 80W");
  assert.equal(web.powerLabel(0.5, 0), "PWR 50%"); assert.equal(web.powerLabel(0.05, undefined), "PWR 5%"); assert.equal(web.powerLabel(1, null), "PWR 100%");
  assert.equal(web.powerLabel(undefined, 100), "PWR"); assert.equal(web.powerLabel(-1, 100), "PWR");
  assert.equal(web.powerLabel(0.502, 100), "PWR 50W"); assert.equal(web.powerLabel(0.051, 100), "PWR 5W"); assert.equal(web.powerLabel(0.996, 100), "PWR 100W");   // arrondis du poste
  assert.equal(web.powerLabel(0.37, 100), "PWR 37W"); assert.equal(web.powerLabel(0.37, 0), "PWR 37%");                                                         // valeur hors palier : telle quelle
  assert.deepEqual(web.POWER_STEPS, [0.05, 0.1, 0.25, 0.5, 0.8, 1]);
});

test("puissance : un appui passe à la valeur supérieure puis reboucle au début", () => {
  const loop = [0.05, 0.1, 0.25, 0.5, 0.8, 1, 0.05];
  for (let i = 0; i < loop.length - 1; i++) assert.equal(web.nextPower(loop[i]), loop[i + 1], "depuis " + loop[i]);
  assert.equal(web.nextPower(0.3), 0.5); assert.equal(web.nextPower(0), 0.05); assert.equal(web.nextPower(0.78), 0.8);   // entre deux paliers : le palier supérieur
  assert.equal(web.nextPower(0.051), 0.1); assert.equal(web.nextPower(0.047), 0.1); assert.equal(web.nextPower(0.502), 0.8);   // valeurs relues, arrondies par le poste : même palier
  assert.equal(web.nextPower(0.996), 0.05); assert.equal(web.nextPower(0.999), 0.05);                                           // ~100 % : retour au début
  assert.equal(web.nextPower(undefined), 0.05); assert.equal(web.nextPower(null), 0.05); assert.equal(web.nextPower(7), 0.05);   // inconnue : la plus faible
});

test("puissance : bouton PWR, cycle, verrouillé en émission, absent si le poste ne la fournit pas", async () => {
  const w = makeWorld();
  await w.connected(); w.hello({ max_power_w: 100 });
  w.state({}, { levels: { RFPOWER: 1 } });
  let v = w.ui.views.at(-1);
  assert.deepEqual(v.controls.at(-1), { key: "PWR", label: "PWR 100W", on: true });
  const seen = [];
  for (const level of [1, 0.05, 0.1, 0.25, 0.5, 0.8]) {
    w.state({}, { levels: { RFPOWER: level } });
    const pending = w.client.pressControl("PWR"); w.answer(true); await pending;
    const sent = w.sentCommands("set_level").at(-1);
    assert.equal(sent.name, "RFPOWER"); seen.push(sent.value);
  }
  assert.deepEqual(seen, [0.05, 0.1, 0.25, 0.5, 0.8, 1]);
  w.state({}, { levels: { RFPOWER: 0.5 } });
  assert.equal(w.ui.views.at(-1).controls.at(-1).label, "PWR 50W");
  w.hello({ max_power_w: 0 }); w.state({}, { levels: { RFPOWER: 0.5 } });
  assert.equal(w.ui.views.at(-1).controls.at(-1).label, "PWR 50%");           // maximum inconnu : pourcentage
  w.state({ state: "TX", owner: "phone" }, { levels: { RFPOWER: 0.5 } });
  assert.equal(w.ui.views.at(-1).controlsLocked, true);
  const before = w.sentCommands("set_level").length;
  assert.equal((await w.client.pressControl("PWR")).ok, false); assert.equal(w.sentCommands("set_level").length, before);
  w.state({}, {});
  assert.ok(!w.ui.views.at(-1).controls.some((c) => c.key === "PWR"));
});

// --------------------------------------------------------------------------- saisie de fréquence, chiffres, bandes

test("saisie de fréquence : kHz, MHz ou format du poste, refus de tout le reste", () => {
  const ok = [["7074", 7074000], ["7 074,5", 7074500], ["14205.5", 14205500], ["14.205", 14205000], ["7,074", 7074000], ["145", 145000000],
              ["7.074.00", 7074000], ["14.205.50", 14205500], ["144.300.00", 144300000], ["3.822.5", 3822500], ["0.5", 500000], ["1000", 1000000], [" 28 400 ", 28400000]];
  for (const [text, hz] of ok) assert.equal(web.parseFrequencyEntry(text), hz, text);
  for (const bad of ["", "   ", ".", "abc", "7074abc", "7..074", "7.074.000", "-7074", "1e3", null, undefined, "0", "0.0005", "9999999", "7074 kHz", "7.07.4"])
    assert.equal(web.parseFrequencyEntry(bad), null, String(bad));
});

test("chiffres de l'afficheur : le poids en Hz de chacun, y compris au-delà de 100 MHz", () => {
  const show = (hz) => web.frequencyDigits(hz).map((d) => d.char + (d.weight === null ? "" : ":" + d.weight)).join(" ");
  assert.equal(show(7074000), "7:1000000 . 0:100000 7:10000 4:1000 . 0:100 0:10");
  assert.equal(show(3822500), "3:1000000 . 8:100000 2:10000 2:1000 . 5:100 0:10");
  assert.equal(show(144300000), "1:100000000 4:10000000 4:1000000 . 3:100000 0:10000 0:1000 . 0:100 0:10");
  assert.equal(show(28074010), "2:10000000 8:1000000 . 0:100000 7:10000 4:1000 . 0:100 1:10");
  assert.deepEqual(web.frequencyDigits(null), []); assert.deepEqual(web.frequencyDigits(NaN), []);
  assert.equal(web.frequencyDigits(14200000).map((d) => d.char).join(""), web.formatIcomFrequency(14200000));
});

test("crans de fréquence : retenue entre chiffres, bornes", () => {
  assert.equal(web.nudgedFrequency(7074000, 1000, 1), 7075000); assert.equal(web.nudgedFrequency(7074000, 1000, -1), 7073000);
  assert.equal(web.nudgedFrequency(7099000, 1000, 1), 7100000);                // la retenue passe sur le chiffre voisin
  assert.equal(web.nudgedFrequency(14000000, 10, -1), 13999990); assert.equal(web.nudgedFrequency(29999990, 100, 3), 30000290);
  assert.equal(web.nudgedFrequency(1500, 1000, -5), 1000); assert.equal(web.nudgedFrequency(5999999000, 1e6, 10), 6000000000);   // bornes
  assert.deepEqual(web.STEPS_HZ.slice(0, 4), [10, 100, 500, 1000]);
});

test("crans de fréquence : l'affichage suit tout de suite, UNE seule commande part, la confirmation du poste libère l'affichage", async () => {
  const w = makeWorld();
  await w.connected(); w.state({}, { frequency_hz: 7074000 });
  assert.equal(w.client.nudgeFrequency(1000, 1), true); assert.equal(w.client.nudgeFrequency(1000, 1), true); assert.equal(w.client.nudgeFrequency(100, -2), true);
  const view = w.ui.views.at(-1);
  assert.equal(view.frequencyIcom, "7.075.80"); assert.equal(view.frequencyPending, true);       // 7074000 + 2000 - 200
  assert.equal(w.sentCommands("set_frequency").length, 0);                                          // regroupés : rien n'est parti
  w.env.fireTimeouts(); await new Promise((r) => setImmediate(r));
  assert.equal(w.sentCommands("set_frequency").length, 1); assert.equal(w.sentCommands("set_frequency")[0].hz, 7075800);
  w.answer(true); await new Promise((r) => setImmediate(r));
  w.state({}, { frequency_hz: 7074000 });                                                           // état en retard : on garde la valeur demandée
  assert.equal(w.ui.views.at(-1).frequencyIcom, "7.075.80");
  w.state({}, { frequency_hz: 7075800 });                                                           // le poste confirme
  assert.equal(w.ui.views.at(-1).frequencyPending, false); assert.equal(w.ui.views.at(-1).frequencyIcom, "7.075.80");
});

test("crans de fréquence : refusé en émission, valeur oubliée si le poste refuse ou ne répond pas", async () => {
  const w = makeWorld();
  await w.connected(); w.state({ state: "TX", owner: "phone" }, { frequency_hz: 7074000 });
  assert.equal(w.client.nudgeFrequency(1000, 1), false); assert.equal(w.sentCommands("set_frequency").length, 0);
  assert.ok(w.ui.logs.some(([t, l]) => /pendant l'émission/.test(t) && l === "warn"));
  w.state({}, { frequency_hz: 7074000 });
  w.client.nudgeFrequency(1000, 1);
  w.env.fireTimeouts(); await new Promise((r) => setImmediate(r));
  w.answer(false, { reason: "rig_error" }); await new Promise((r) => setImmediate(r));
  assert.equal(w.ui.views.at(-1).frequencyPending, false); assert.equal(w.ui.views.at(-1).frequencyIcom, "7.074.00");   // retour à la vraie fréquence
  w.client.nudgeFrequency(1000, 1);                                                                   // sans confirmation : abandon après le délai
  w.env.advance(3000); w.state({}, { frequency_hz: 7074000 });
  assert.equal(w.ui.views.at(-1).frequencyPending, false);
  const idle = makeWorld();
  assert.equal(idle.client.nudgeFrequency(1000, 1), false);                                           // non connecté
  await idle.connected(); idle.state({}, { frequency_hz: null });
  assert.equal(idle.client.nudgeFrequency(1000, 1), false);                                           // fréquence inconnue : rien d'inventé
  assert.equal(idle.client.nudgeFrequency(1000, 0), false);
});

test("bandes : repérage, point de départ, mémoire, respect des modes d'émission", () => {
  assert.equal(web.bandOf(14200000).key, "20"); assert.equal(web.bandOf(7100000).key, "40"); assert.equal(web.bandOf(50313000).key, "6");
  assert.equal(web.bandOf(14350000).key, "20"); assert.equal(web.bandOf(14350001), null); assert.equal(web.bandOf(7500000), null); assert.equal(web.bandOf(null), null);
  assert.deepEqual(web.BANDS.map((b) => b.key), ["160", "80", "60", "40", "30", "20", "17", "15", "12", "10", "6"]);
  assert.deepEqual(web.bandTarget({}, "20", [], []), { hz: 14200000, mode: "USB" });
  assert.deepEqual(web.bandTarget({}, "40", [], []), { hz: 7100000, mode: "LSB" });
  assert.deepEqual(web.bandTarget({ 20: { hz: 14074000, mode: "PKTUSB" } }, "20", [], []), { hz: 14074000, mode: "PKTUSB" });          // la dernière utilisée
  assert.deepEqual(web.bandTarget({}, "40", ["PKTUSB", "PKTLSB"], ["LSB", "PKTLSB", "PKTUSB"]), { hz: 7100000, mode: "PKTLSB" });       // LSB -> LSB-D si l'émission est limitée aux modes données
  assert.deepEqual(web.bandTarget({}, "40", [], ["USB", "FM"]), { hz: 7100000, mode: null });                                           // mode absent du poste : on ne le change pas
  assert.equal(web.bandTarget({}, "99", [], []), null);
  const m1 = web.rememberBand({}, 14074000, "PKTUSB");
  assert.deepEqual(m1, { 20: { hz: 14074000, mode: "PKTUSB" } }); assert.equal(web.rememberBand(m1, 14074000, "PKTUSB"), null);
  assert.equal(web.rememberBand({}, 7500000, "USB"), null); assert.equal(web.rememberBand({}, 14200000, null), null);
  assert.deepEqual(web.rememberBand(m1, 7074000, "PKTUSB"), { 20: { hz: 14074000, mode: "PKTUSB" }, 40: { hz: 7074000, mode: "PKTUSB" } });
  const store = { get: () => JSON.stringify({ 20: { hz: 14074000, mode: "PKTUSB" }, 40: { hz: 14074000, mode: "USB" }, 15: { hz: 21100000, mode: "US\nB" }, 99: { hz: 1, mode: "USB" }, 10: "x" }) };
  assert.deepEqual(web.loadBandMemory(store), { 20: { hz: 14074000, mode: "PKTUSB" } });                                              // entrées hors bande ou mal formées écartées
  assert.deepEqual(web.loadBandMemory({ get: () => "{ pas du json" }), {}); assert.deepEqual(web.loadBandMemory({ get: () => null }), {});
});

test("bandes : la dernière fréquence stable est mémorisée, puis rappelée (mode d'abord, puis fréquence)", async () => {
  const w = makeWorld();
  await w.connected(); w.hello({ capabilities: { modes: ["USB", "LSB", "PKTUSB", "PKTLSB"] }, tx_modes: [] });
  w.state({}, { frequency_hz: 14074000, mode: "PKTUSB" });
  w.env.advance(800); w.state({}, { frequency_hz: 14074000, mode: "PKTUSB" });
  assert.equal(w.env.store.get("trx.bands"), undefined);                                              // pas encore stable
  w.env.advance(1000); w.state({}, { frequency_hz: 14074000, mode: "PKTUSB" });
  assert.deepEqual(JSON.parse(w.env.store.get("trx.bands")), { 20: { hz: 14074000, mode: "PKTUSB" } });
  w.state({}, { frequency_hz: 7100000, mode: "LSB" });                                                  // on part sur 40 m
  let pending = w.client.goBand("20");
  await new Promise((r) => setImmediate(r)); w.answer(true);
  await new Promise((r) => setImmediate(r)); w.answer(true); await pending;
  assert.deepEqual([w.sentCommands("set_mode").at(-1).mode, w.sentCommands("set_mode").at(-1).passband], ["PKTUSB", 0]);
  assert.equal(w.sentCommands("set_frequency").at(-1).hz, 14074000);
  assert.ok(w.dc().sent.findIndex((m) => m.cmd === "set_mode") < w.dc().sent.findIndex((m) => m.cmd === "set_frequency"));
  w.state({}, { frequency_hz: 14074000, mode: "PKTUSB" });                                             // déjà dans le bon mode : pas de set_mode
  const modes = w.sentCommands("set_mode").length;
  pending = w.client.goBand("20"); await new Promise((r) => setImmediate(r)); w.answer(true); await pending;
  assert.equal(w.sentCommands("set_mode").length, modes);
  pending = w.client.goBand("10"); await new Promise((r) => setImmediate(r)); w.answer(true);        // bande jamais utilisée : point de départ usuel
  await new Promise((r) => setImmediate(r)); w.answer(true); await pending;
  assert.deepEqual([w.sentCommands("set_mode").at(-1).mode, w.sentCommands("set_frequency").at(-1).hz], ["USB", 28400000]);
  w.state({ state: "TX", owner: "phone" }, { frequency_hz: 14074000, mode: "PKTUSB" });
  const frequencies = w.sentCommands("set_frequency").length;
  assert.equal((await w.client.goBand("40")).ok, false); assert.equal(w.sentCommands("set_frequency").length, frequencies);    // refusé en émission
  w.state({ state: "TX", owner: "phone" }, { frequency_hz: 7074000, mode: "LSB" });
  w.env.advance(5000); w.state({ state: "TX", owner: "phone" }, { frequency_hz: 7074000, mode: "LSB" });
  assert.equal(JSON.parse(w.env.store.get("trx.bands"))["40"], undefined);                              // rien n'est mémorisé pendant l'émission
  assert.equal(w.ui.views.at(-1).band, "40");
});

test("bandes : les modes d'émission autorisés sont respectés au rappel", async () => {
  const w = makeWorld();
  await w.connected(); w.hello({ capabilities: { modes: ["USB", "LSB", "PKTUSB", "PKTLSB"] }, tx_modes: ["PKTUSB", "PKTLSB"] });
  w.state({}, { frequency_hz: 14200000, mode: "PKTUSB" });
  const pending = w.client.goBand("80"); await new Promise((r) => setImmediate(r)); w.answer(true);
  await new Promise((r) => setImmediate(r)); w.answer(true); await pending;
  assert.equal(w.sentCommands("set_mode").at(-1).mode, "PKTLSB"); assert.equal(w.sentCommands("set_frequency").at(-1).hz, 3700000);
});

// --------------------------------------------------------------------------- journal des pertes de connexion

const lossOpts = { clientId: "phone", password: "mot de passe de test", useMic: false };

test("perte de connexion : rapport complet, enregistré, signalé à l'écran", async () => {
  const w = makeWorld();
  await w.connected(); w.state({ state: "RX" });
  w.env.advance(65000); w.state({});                                           // 65 s de session
  w.client.lastRttMs = 85; w.client.pingFailures = 2;
  w.client.ui.log("Une ligne avant la coupure", "");
  w.dc().onclose();
  const e = w.ui.lossEvents.at(-1);
  assert.deepEqual([e.kind, e.code, e.title], ["lost", "datachannel_closed", "Canal de contrôle fermé"]);
  assert.equal(e.details.sessionS, 65); assert.equal(e.details.lastRttMs, 85); assert.equal(e.details.pingFailures, 2); assert.equal(e.details.online, true);
  assert.equal(e.details.visible, true); assert.equal(e.details.ptt, "RX"); assert.equal(e.details.txMine, false);
  assert.ok(e.logs.some((l) => /Une ligne avant la coupure/.test(l.text)) && e.logs.length <= 8);
  assert.equal(w.client.connected, false); assert.deepEqual(w.ui.statuses.at(-1), ["Déconnecté", "bad"]);
  assert.ok(w.ui.logs.some(([t, l]) => /Connexion perdue : Canal de contrôle fermé/.test(t) && l === "bad"));
  assert.equal(JSON.parse(w.env.store.get("trx.losses")).length, 1);            // survit au rechargement de la page
  assert.equal(w.ui.lossLists.at(-1).length, 1);
});

test("perte de connexion : les 10 dernières seulement, la plus récente d'abord, rechargées après redémarrage de la page", async () => {
  const w = makeWorld();
  const codes = ["datachannel_closed", "connection_failed", "ice_failed", "connection_closed", "silence"];
  for (let i = 0; i < 12; i++) {
    await w.connected(); w.state({});
    w.env.advance(1000);
    const pc = w.pc();
    if (i % 5 === 0) w.dc().onclose();
    else if (i % 5 === 1) { pc.connectionState = "failed"; pc.onconnectionstatechange(); }
    else if (i % 5 === 2) { pc.iceConnectionState = "failed"; pc.oniceconnectionstatechange(); }
    else if (i % 5 === 3) { pc.connectionState = "closed"; pc.onconnectionstatechange(); }
    else { w.env.advance(6000); w.env.tick(); }
  }
  const list = w.client.losses;
  assert.equal(list.length, web.MAX_LOSSES); assert.equal(list.length, 10);
  assert.deepEqual(list.slice(0, 5).map((e) => e.code), ["connection_failed", "datachannel_closed", "silence", "connection_closed", "ice_failed"]);   // i = 11, 10, 9, 8, 7
  assert.ok(list[0].t >= list[9].t);                                             // ordre : la plus récente en tête
  assert.deepEqual([...new Set(list.map((e) => e.code))].sort(), [...codes].sort());
  const again = makeWorld({ storage: w.env.storage });                           // page rechargée : l'historique est toujours là
  assert.equal(again.client.losses.length, 10); assert.equal(again.client.losses[0].code, list[0].code);
  again.client.clearLosses();
  assert.equal(again.client.losses.length, 0); assert.equal(JSON.parse(w.env.store.get("trx.losses")).length, 0);
});

test("perte de connexion : « disconnected » seul n'est qu'un avertissement, la déconnexion voulue n'est jamais une perte", async () => {
  const w = makeWorld();
  await w.connected(); w.state({});
  w.pc().connectionState = "disconnected"; w.pc().onconnectionstatechange();
  assert.equal(w.client.connected, true); assert.equal(w.ui.lossEvents.length, 0);
  assert.ok(w.ui.logs.some(([t, l]) => /instable/.test(t) && l === "warn"));
  w.client.disconnect();                                                         // l'utilisateur se déconnecte
  assert.equal(w.ui.lossEvents.length, 0); assert.equal(w.client.losses.length, 0);
  const closed = w.pc(); closed.connectionState = "closed";
  assert.equal(closed.onconnectionstatechange, null);                            // plus aucun rappel après une déconnexion voulue
});

test("perte de connexion : silence de la station détecté, avec le contexte (hors ligne, page masquée, émission en cours)", async () => {
  const w = makeWorld();
  await w.connected(); w.state({});
  w.env.advance(4000); w.env.tick();
  assert.equal(w.client.connected, true);                                        // 4 s sans nouvelle : encore toléré
  w.state({});                                                                   // une nouvelle arrive : le compteur repart
  w.env.advance(4000); w.env.tick();
  assert.equal(w.client.connected, true);
  w.env.online = false; w.env.visible = false;
  w.env.advance(2000); w.env.tick();                                             // 6 s de silence cette fois
  const e = w.ui.lossEvents.at(-1);
  assert.deepEqual([e.code, e.kind], ["silence", "lost"]); assert.equal(e.details.lastMsgAgoS, 6);
  assert.equal(e.details.online, false); assert.equal(e.details.visible, false);
  const text = web.describeLoss(e);
  assert.match(text, /PLUS de réseau/); assert.match(text, /MASQUÉE/); assert.match(text, /dernier message il y a 6 s/);
  const tx = makeWorld();
  await tx.connected(); tx.state({ state: "TX", owner: "phone" });
  tx.env.advance(6000); tx.env.tick();
  assert.equal(tx.ui.lossEvents.at(-1).details.txMine, true); assert.match(web.describeLoss(tx.ui.lossEvents.at(-1)), /ton émission : coupée par la station/);
});

test("échecs de connexion : identifiants, station occupée, réponse inattendue, station injoignable", async () => {
  const cases = [[401, "auth", /mot de passe refusé/], [503, "busy", /occupée/], [500, "http", /répondu 500/]];
  for (const [status, code, message] of cases) {
    const w = makeWorld({ offerStatus: status });
    await assert.rejects(() => w.client.connect(lossOpts), message);
    const e = w.ui.lossEvents.at(-1);
    assert.deepEqual([e.kind, e.code], ["failed", code]); assert.equal(w.client.connected, false); assert.deepEqual(w.ui.statuses.at(-1), ["Erreur", "bad"]);
    assert.equal(w.client.losses.length, 1);
  }
  const down = makeWorld({ postOffer: async () => { throw new TypeError("Failed to fetch"); } });
  await assert.rejects(() => down.client.connect(lossOpts), /injoignable/);
  const e = down.ui.lossEvents.at(-1);
  assert.deepEqual([e.kind, e.code], ["failed", "network"]); assert.match(e.details.detail, /Failed to fetch/);
  const broken = makeWorld({ RTCPeerConnection: function () { throw new Error("WebRTC indisponible"); } });
  await assert.rejects(() => broken.client.connect(lossOpts), /WebRTC indisponible/);
  assert.equal(broken.ui.lossEvents.at(-1).code, "client_error"); assert.match(broken.ui.lossEvents.at(-1).details.detail, /WebRTC indisponible/);
});

test("échec de connexion : le canal de contrôle ne s'ouvre jamais (UDP bloqué) : délai, rapport et nettoyage", async () => {
  const w = makeWorld();
  await w.client.connect(lossOpts);                                              // la station répond, mais « hello » n'arrive jamais
  assert.equal(w.client.connected, false); assert.equal(w.ui.lossEvents.length, 0);
  w.env.fireTimeouts();
  const e = w.ui.lossEvents.at(-1);
  assert.deepEqual([e.kind, e.code], ["failed", "no_hello"]); assert.match(e.explain, /UDP/);
  assert.equal(w.client.closed, true); assert.deepEqual(w.ui.statuses.at(-1), ["Erreur", "bad"]); assert.equal(w.pc().closed, true);
  assert.ok(w.ui.logs.some(([t, l]) => /jamais ouvert/.test(t) && l === "bad"));
  const ok = makeWorld();
  await ok.client.connect(lossOpts); ok.hello();                                // hello à temps : le délai est annulé
  ok.env.fireTimeouts();
  assert.equal(ok.client.connected, true); assert.equal(ok.ui.lossEvents.length, 0);
});

test("rapport de perte : texte lisible, résumé, historique corrompu ignoré", async () => {
  const w = makeWorld();
  await w.connected(); w.state({ state: "RX" });
  w.env.advance(125000); w.state({}); w.client.lastRttMs = 40;
  w.pc().connectionState = "failed"; w.pc().iceConnectionState = "disconnected"; w.pc().onconnectionstatechange();
  const e = w.ui.lossEvents.at(-1);
  const fmt = (t) => "01/01/2026 12:00:" + String(Math.floor(t / 1000) % 60).padStart(2, "0");
  const text = web.describeLoss(e, fmt);
  for (const part of ["Perte de connexion — 01/01/2026", "Raison : Liaison réseau échouée", "Explication :", "Piste :", "session 2 min 5 s", "dernier temps de réponse 40 ms",
                      "PTT RX", "ICE : disconnected", "Dernières lignes du journal :"]) assert.ok(text.includes(part), part);
  assert.match(web.lossSummary(e, fmt), /^01\/01\/2026 12:00:\d\d · Liaison réseau échouée$/);
  const failed = Object.assign({}, e, { kind: "failed" });
  assert.match(web.describeLoss(failed, fmt), /^Échec de connexion/); assert.match(web.lossSummary(failed, fmt), /\(échec de connexion\)$/);
  assert.deepEqual(web.loadLosses({ get: () => "{ pas du json" }), []); assert.deepEqual(web.loadLosses({ get: () => '{"a":1}' }), []);
  assert.deepEqual(web.loadLosses({ get: () => JSON.stringify([null, 5, { title: "x" }, { title: "ok", t: 1 }]) }).map((x) => x.title), ["ok"]);
  assert.equal(web.loadLosses({ get: () => JSON.stringify(Array.from({ length: 30 }, (_, i) => ({ title: "t" + i, t: i }))) }).length, 10);
  for (const code of Object.keys(web.LOSS_REASONS)) {
    const r = web.LOSS_REASONS[code];
    assert.ok(["lost", "failed"].includes(r.kind) && r.title && r.explain && r.hint, code);
  }
});


// --------------------------------------------------------------------------- reconnexion automatique

const PASSWORD = "s3cret-mdp-de-test";
const nextTick = () => new Promise((r) => setImmediate(r));
async function up(w, extra) {
  await w.client.connect(Object.assign({ clientId: "phone", password: PASSWORD, useMic: false, reconnectWindowS: 15 }, extra || {}));
  w.hello(); w.state({});
}
async function ticks(w, count, ms) {                                              // le temps passe par pas de 500 ms, la boucle de reconnexion bat
  for (let i = 0; i < count; i++) { w.env.advance(ms || 500); w.env.tickAll(); await nextTick(); await nextTick(); await nextTick(); }
}
const lastReconnect = (w) => w.ui.reconnects.at(-1);
function flaky() {                                                                 // une station dont on peut couper l'accès
  const state = { down: false, offers: [] };
  state.postOffer = async (body) => {
    state.offers.push(body);
    if (state.down) throw new TypeError("Failed to fetch");
    return { status: 200, body: { sdp: "v=0 réponse", type: "answer" } };
  };
  return state;
}

test("reconnexion : une micro-coupure est rattrapée sans redemander le mot de passe, rien n'est réarmé", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  await up(w, { useMic: true }); w.client.setArmed(true);
  assert.equal(net.offers.length, 1);
  w.dc().onclose();                                                                // micro-coupure 4G
  assert.deepEqual([lastReconnect(w).active, lastReconnect(w).remainingS, lastReconnect(w).windowS], [true, 15, 15]);
  assert.deepEqual(w.ui.statuses.at(-1), ["Reconnexion…", "busy"]);
  assert.equal(w.client.connected, false); assert.equal(w.client.armed, false);       // « Émission autorisée » est décochée : il faudra la recocher
  assert.ok(w.ui.logs.some(([t, l]) => /Reconnexion automatique pendant 15 s/.test(t) && l === "bad"));
  assert.equal(w.client.losses.length, 1);                                         // la perte est consignée une fois
  await ticks(w, 2);
  assert.equal(net.offers.length, 2);                                              // un essai est parti
  assert.deepEqual([net.offers[1].client_id, net.offers[1].password], ["phone", PASSWORD]);   // avec les mêmes identifiants, sans rien demander
  assert.deepEqual(w.ui.statuses.at(-1), ["Reconnexion…", "busy"]);
  w.hello(); w.state({});                                                          // la station répond
  assert.deepEqual([lastReconnect(w).active, lastReconnect(w).outcome], [false, "ok"]);
  assert.equal(w.client.connected, true); assert.equal(w.client.armed, false); assert.equal(w.mic.enabled, false);   // jamais d'émission reprise toute seule
  assert.ok(w.ui.logs.some(([t]) => /Reconnecté après \d+ s \(1 essai\)\. Recoche « Émission autorisée »/.test(t)));
  assert.equal(w.client.losses.length, 1);
  assert.deepEqual([w.client.losses[0].details.reconnect.outcome, w.client.losses[0].details.reconnect.attempts], ["ok", 1]);
  assert.match(web.lossSummary(w.client.losses[0]), /· reconnecté en \d+ s$/); assert.match(web.describeLoss(w.client.losses[0]), /reconnexion automatique réussie après \d+ s, 1 essai\(s\)/);
  assert.ok([...w.env.store.values()].every((v) => !v.includes(PASSWORD)));          // le mot de passe n'est JAMAIS enregistré
  assert.equal(JSON.parse(w.env.store.get("trx.losses"))[0].details.reconnect.outcome, "ok");
  await ticks(w, 6); assert.equal(net.offers.length, 2);                           // plus aucun essai une fois reconnecté
});

test("reconnexion : essais répétés jusqu'à la fin du délai, UNE seule entrée dans l'historique, puis abandon définitif", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  await up(w);
  net.down = true;
  w.dc().onclose();
  const seen = [];
  for (let i = 0; i < 40; i++) { await ticks(w, 1); seen.push(lastReconnect(w).remainingS); if (!lastReconnect(w).active) break; }
  assert.equal(seen[0], 15);                                                       // le décompte part de 15 s
  assert.ok(seen.includes(10) && seen.includes(5));                                // et descend seconde après seconde
  const attempts = net.offers.length - 1;
  assert.ok(attempts >= 4 && attempts <= 6, "essais : " + attempts);                // espacés 1,5 s puis 3 s puis 4,5 s
  assert.deepEqual([lastReconnect(w).active, lastReconnect(w).outcome], [false, "timeout"]);
  assert.deepEqual(w.ui.statuses.at(-1), ["Déconnecté", "bad"]);
  assert.ok(w.ui.logs.some(([t, l]) => /Reconnexion abandonnée : plus de liaison après 15 s/.test(t) && l === "bad"));
  assert.equal(w.client.losses.length, 1);                                         // les essais ratés n'encombrent pas l'historique
  assert.deepEqual([w.client.losses[0].details.reconnect.outcome, w.client.losses[0].details.reconnect.attempts], ["timeout", attempts]);
  assert.match(web.describeLoss(w.client.losses[0]), /abandonnée \(délai écoulé\) après 1[5-9] s/);
  assert.equal(w.client.reconnecting, null); assert.equal(w.client._credentials, null);   // le mot de passe est oublié
  const sent = net.offers.length;
  await ticks(w, 20); assert.equal(net.offers.length, sent);                       // plus aucun essai, ni aucune minuterie qui tourne
});

test("reconnexion : identifiants refusés = arrêt immédiat, un seul essai (la station bloque après 5 échecs)", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  await up(w);
  const bodies = [];
  w.env.postOffer = async (body) => { bodies.push(body); return { status: 401, body: null }; };
  w.dc().onclose();
  await ticks(w, 3);
  assert.equal(bodies.length, 1);
  assert.deepEqual([lastReconnect(w).active, lastReconnect(w).outcome], [false, "auth"]);
  assert.deepEqual(w.ui.statuses.at(-1), ["Déconnecté", "bad"]); assert.ok(w.ui.logs.some(([t]) => /identifiants refusés par la station/.test(t)));
  await ticks(w, 12); assert.equal(bodies.length, 1);
  assert.equal(w.client.losses[0].details.reconnect.outcome, "auth"); assert.equal(w.client._credentials, null);
});

test("reconnexion : déconnexion voulue ou annulation = aucun essai ; une connexion manuelle reprend la main", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  await up(w); w.client.disconnect();                                               // l'utilisateur se déconnecte
  assert.ok(!w.ui.reconnects.some((r) => r.active)); assert.equal(w.client._credentials, null);
  await ticks(w, 8); assert.equal(net.offers.length, 1);
  const c = makeWorld({ postOffer: net.postOffer });
  await up(c); c.dc().onclose();
  assert.equal(lastReconnect(c).active, true);
  c.client.cancelReconnect();                                                       // bouton « Annuler »
  assert.deepEqual([lastReconnect(c).active, lastReconnect(c).outcome], [false, "cancelled"]); assert.deepEqual(c.ui.statuses.at(-1), ["Déconnecté", ""]);
  const before = net.offers.length;
  await ticks(c, 8); assert.equal(net.offers.length, before);
  const d = makeWorld({ postOffer: net.postOffer });
  await up(d); d.dc().onclose();
  d.client.disconnect();                                                            // « Déconnecter » pendant la reconnexion
  assert.equal(lastReconnect(d).outcome, "cancelled"); const n = net.offers.length; await ticks(d, 8); assert.equal(net.offers.length, n);
  const e = makeWorld({ postOffer: net.postOffer });
  await up(e); e.dc().onclose();
  await e.client.connect({ clientId: "phone", password: "nouveau", useMic: false, reconnectWindowS: 0 });   // connexion manuelle pendant la reconnexion
  assert.equal(e.client.reconnecting, null); e.hello();
  assert.equal(net.offers.at(-1).password, "nouveau");
  const m = net.offers.length; await ticks(e, 8); assert.equal(net.offers.length, m);
});

test("reconnexion : sans réseau on attend (pas d'essai inutile), au retour du réseau on retente aussitôt", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  await up(w);
  w.env.online = false;
  w.dc().onclose();
  await ticks(w, 6);                                                                // 3 s hors ligne
  assert.equal(net.offers.length, 1); assert.equal(lastReconnect(w).remainingS, 12); assert.equal(lastReconnect(w).attempt, 0);
  w.env.online = true; w.client.onNetworkOnline();                                  // événement « online » du navigateur
  await ticks(w, 1);
  assert.equal(net.offers.length, 2); w.hello();
  assert.equal(lastReconnect(w).outcome, "ok");
  const v = makeWorld({ postOffer: net.postOffer });
  await up(v); v.env.online = false; v.dc().onclose();
  await ticks(v, 2); const base = net.offers.length;
  v.env.online = true; v.client.onVisibility(false);                                // retour de la page au premier plan : même effet
  await ticks(v, 1); assert.equal(net.offers.length, base + 1);
});

test("reconnexion : durée réglable (15, 30, 60 s), valeurs hors limites ramenées, 0 = désactivée comme avant", async () => {
  for (const [window, wanted] of [[30, 30], [60, 60], [500, 300], [-5, 0], ["abc", 0], [undefined, 0], [14.6, 15]]) {
    const w = makeWorld(); await up(w, { reconnectWindowS: window });
    assert.equal(w.client.autoWindowS, wanted, String(window));
  }
  const net = flaky(), long = makeWorld({ postOffer: net.postOffer });
  await up(long, { reconnectWindowS: 30 }); net.down = true; long.dc().onclose();
  assert.equal(lastReconnect(long).remainingS, 30);
  await ticks(long, 58);                                                            // 29 s : toujours en reconnexion
  assert.equal(lastReconnect(long).active, true); assert.ok(lastReconnect(long).remainingS <= 2);
  await ticks(long, 4);                                                             // 31 s : abandon
  assert.deepEqual([lastReconnect(long).active, lastReconnect(long).outcome], [false, "timeout"]);
  assert.match(long.ui.logs.map(([t]) => t).join("\n"), /plus de liaison après 30 s/);
  const off = makeWorld({ postOffer: net.postOffer }); net.down = false;
  await up(off, { reconnectWindowS: 0 }); off.dc().onclose();                       // désactivée : comportement d'origine
  assert.equal(off.ui.reconnects.filter((r) => r.active).length, 0); assert.deepEqual(off.ui.statuses.at(-1), ["Déconnecté", "bad"]);
  assert.equal(off.client.losses.length, 1); assert.equal(off.client._credentials, null);
});

test("reconnexion : un canal qui ne s'ouvre pas est abandonné au bout de 6 s pour réessayer", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  await up(w, { reconnectWindowS: 60 });
  w.dc().onclose();
  await ticks(w, 2);
  assert.equal(net.offers.length, 2); assert.equal(lastReconnect(w).attempt, 1);    // essai 1 parti, mais « hello » n'arrive pas
  w.env.fireTimeouts();                                                             // le délai de 6 s s'écoule
  assert.equal(w.client.reconnecting.busy, false); assert.equal(w.pc().closed, true);
  assert.equal(w.client.losses.length, 1);                                          // pas d'entrée supplémentaire pour cet essai raté
  await ticks(w, 6);                                                                // après une attente, nouvel essai
  assert.equal(net.offers.length, 3); w.hello();
  assert.deepEqual([lastReconnect(w).outcome, w.client.losses[0].details.reconnect.attempts], ["ok", 2]);
});

test("reconnexion : seulement après une VRAIE coupure ; un premier échec de connexion n'en déclenche pas ; une nouvelle perte relance le cycle", async () => {
  const w = makeWorld({ offerStatus: 500 });
  await assert.rejects(() => w.client.connect({ clientId: "phone", password: PASSWORD, useMic: false, reconnectWindowS: 15 }), /répondu 500/);
  assert.equal(w.client._credentials, null); assert.equal(w.client.reconnecting, null); assert.equal(w.ui.reconnects.filter((r) => r.active).length, 0);
  const n = makeWorld();
  await n.client.connect({ clientId: "phone", password: PASSWORD, useMic: false, reconnectWindowS: 15 });   // jamais de « hello »
  n.env.fireTimeouts();
  assert.equal(n.client.reconnecting, null); assert.equal(n.ui.reconnects.filter((r) => r.active).length, 0);
  const net = flaky(), s = makeWorld({ postOffer: net.postOffer });
  await up(s); s.env.advance(7000); s.env.tickAll();                                // silence de la station : c'est aussi une vraie coupure
  assert.equal(s.ui.lossEvents.at(-1).code, "silence"); assert.equal(lastReconnect(s).active, true);
  await ticks(s, 2); s.hello();
  assert.equal(lastReconnect(s).outcome, "ok");
  s.state({}); s.dc().onclose();                                                    // nouvelle coupure : nouveau cycle complet
  assert.deepEqual([lastReconnect(s).active, lastReconnect(s).remainingS], [true, 15]); assert.equal(s.client.losses.length, 2);
  await ticks(s, 2); s.hello();
  assert.deepEqual([s.client.losses[0].details.reconnect.outcome, s.client.losses[1].details.reconnect.outcome], ["ok", "ok"]);
});

// --------------------------------------------------------------------------- sons d'alerte de la liaison

test("sons de liaison : trois motifs distincts (descendant, montant, grave), volumes, durées", () => {
  const { LINK_ALERTS, alertVolume, alertDurationMs } = web;
  const pitches = (kind) => LINK_ALERTS[kind].notes.map(([hz]) => hz);
  assert.ok(pitches("lost")[0] > pitches("lost")[1], "perdue : notes descendantes");
  assert.ok(pitches("restored")[0] < pitches("restored")[1], "rétablie : notes montantes");
  assert.ok(Math.max(...pitches("failed")) < Math.min(...pitches("lost"), ...pitches("restored")), "échec : plus grave que les deux autres");
  assert.equal(LINK_ALERTS.failed.notes.length, 3);
  for (const kind of ["lost", "restored", "failed"]) {
    assert.ok(alertDurationMs(kind) > 200 && alertDurationMs(kind) < 3000);
    assert.ok(LINK_ALERTS[kind].vibrate.every((ms) => ms > 0));
  }
  assert.ok(alertDurationMs("lost") < 3000, "plus court que son intervalle de répétition");
  assert.equal(alertVolume("off"), 0); assert.equal(alertVolume("inconnu"), alertVolume("normal"));
  assert.ok(alertVolume("low") < alertVolume("normal") && alertVolume("normal") < alertVolume("high") && alertVolume("high") <= 0.5);
  assert.equal(alertDurationMs("autre"), 0);
});

test("sons de liaison : micro-coupure = « perdue » répété pendant la reconnexion, puis « rétablie »", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  await up(w);
  assert.deepEqual(w.ui.alerts, []);                                                // connexion normale : aucun son
  net.down = true; w.dc().onclose();
  assert.deepEqual(w.ui.alerts, ["lost"]);
  await ticks(w, 7);                                                                // 3,5 s : un rappel
  assert.deepEqual(w.ui.alerts, ["lost", "lost"]);
  net.down = false; await ticks(w, 6); w.hello();
  assert.equal(w.ui.alerts.at(-1), "restored"); assert.ok(!w.ui.alerts.includes("failed"));
  assert.equal(w.client.armed, false);                                              // rien ne reprend tout seul : il faut réarmer
});

test("sons de liaison : reconnexion abandonnée (délai écoulé ou identifiants refusés) = « échec »", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  await up(w);
  net.down = true; w.dc().onclose();
  await ticks(w, 34);                                                               // 17 s > 15 s
  assert.equal(lastReconnect(w).outcome, "timeout");
  assert.equal(w.ui.alerts.at(-1), "failed"); assert.equal(w.ui.alerts.filter((k) => k === "failed").length, 1);
  assert.ok(w.ui.alerts.filter((k) => k === "lost").length >= 4);
  const a = makeWorld();
  await up(a);
  a.env.offerStatus = 401; a.dc().onclose();
  await ticks(a, 3);
  assert.equal(lastReconnect(a).outcome, "auth"); assert.deepEqual(a.ui.alerts, ["lost", "failed"]);
});

test("sons de liaison : sans reconnexion automatique, une perte = « échec » tout de suite", async () => {
  const w = makeWorld();
  await up(w, { reconnectWindowS: 0 });
  w.dc().onclose();
  assert.deepEqual(w.ui.alerts, ["failed"]);
});

test("sons de liaison : déconnexion voulue, annulation, premier échec de connexion = aucun son", async () => {
  const w = makeWorld();
  await up(w); w.client.disconnect();
  assert.deepEqual(w.ui.alerts, []);
  const net = flaky(), c = makeWorld({ postOffer: net.postOffer });
  await up(c); net.down = true; c.dc().onclose(); c.client.cancelReconnect();
  assert.deepEqual(c.ui.alerts, ["lost"]);                                          // le « perdue » initial seulement
  await ticks(c, 10);
  assert.deepEqual(c.ui.alerts, ["lost"]);
  const f = makeWorld({ offerStatus: 500 });
  await assert.rejects(() => f.client.connect({ clientId: "phone", password: PASSWORD, useMic: false, reconnectWindowS: 15 }));
  assert.deepEqual(f.ui.alerts, []);
});

test("sons de liaison : pendant SON émission, 1,5 s de silence de la station = alerte immédiate, puis « rétablie » si elle répond", async () => {
  const w = makeWorld();
  await up(w);
  w.state({ state: "TX", owner: "phone", tot_remaining_s: 80 });
  w.env.advance(1000); w.env.tick();
  assert.deepEqual(w.ui.alerts, []);
  w.env.advance(600); w.env.tick();                                                 // 1,6 s sans message
  assert.deepEqual(w.ui.alerts, ["lost"]);
  assert.ok(w.ui.logs.some(([t, l]) => /arrête de parler/.test(t) && l === "bad"));
  w.env.advance(500); w.env.tick();
  assert.deepEqual(w.ui.alerts, ["lost"]);                                          // une seule alerte par silence
  assert.ok(w.sentCommands("heartbeat").length > 0);                                // les battements continuent : la station décide de la coupure
  w.state({ state: "TX", owner: "phone", tot_remaining_s: 77 });
  assert.deepEqual(w.ui.alerts, ["lost", "restored"]);
  const rx = makeWorld();                                                           // en réception, un silence court ne sonne pas
  await up(rx); rx.env.advance(1600); rx.env.tick();
  assert.deepEqual(rx.ui.alerts, []);
  const other = makeWorld();                                                        // l'émission d'un autre : pas d'alerte pour moi
  await up(other); other.state({ state: "TX", owner: "autre" }); other.env.advance(1600); other.env.tick();
  assert.deepEqual(other.ui.alerts, []);
});

test("sons de liaison : une interface dont le son plante ne gêne jamais la liaison", async () => {
  const net = flaky(), w = makeWorld({ postOffer: net.postOffer });
  w.ui.linkAlert = () => { throw new Error("AudioContext cassé"); };
  await up(w);
  w.dc().onclose();
  await ticks(w, 2); w.hello();
  assert.equal(lastReconnect(w).outcome, "ok"); assert.equal(w.client.connected, true);
});
