// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest (autotest/web/) : protocole CI-V, détection, essais et TESTS DE PANNE de la garde d'émission
   (aucune émission sans autorisation, durée maximale, STOP, erreur, PTT qui résiste, poste déjà en émission). */
"use strict";
const assert = require("assert");
const path = require("path");
const W = path.join(__dirname, "..", "..", "autotest", "web");
const civ = require(path.join(W, "civ.js"));
const models = require(path.join(W, "models.js"));
const { Runner, detect, TxGuard } = require(path.join(W, "runner.js"));
const report = require(path.join(W, "report.js"));
const { FakeIcom, fakeAudio } = require("./autotest_fake_icom.js");

const tests = [];
function test(name, fn) { tests.push([name, fn]); }
const FAST = { e1: 150, e2: 250, e4: 250, e6: 120, sample: 20, maxTx: 2000, settle: 10, scope: 250 };
const MK2 = models.ICOM.find(m => m.id === "ic7300mk2");

function ui(over) {
  const events = [];
  return Object.assign({ events, event: e => events.push(e), chooseAudio: async () => true, authorize: async () => true,
                         confirmManualPower: async () => true }, over || {});
}
async function setup(rigOpts, uiOver, opts, audioOpts) {
  const rig = new FakeIcom(rigOpts);
  const d = await detect({ openAt: async b => rig.transport(b), model: MK2, bauds: models.ICOM_BAUDS, byAddr: models.byAddr });
  assert.ok(!d.error, JSON.stringify(d));
  const u = ui(uiOver);
  const r = new Runner({ link: d.link, model: MK2, audio: fakeAudio(rig, audioOpts), ui: u, opts: Object.assign({}, FAST, opts), detected: d });
  return { rig, d, u, r };
}
const res = (out, code) => out.results.find(x => x.code === code);

test("CI-V : fréquence et niveaux en BCD, trames, liste fermée", () => {
  assert.deepEqual(civ.encodeFreq(14074000), [0x00, 0x40, 0x07, 0x14, 0x00]);
  assert.equal(civ.decodeFreq([0x00, 0x40, 0x07, 0x14, 0x00]), 14074000);
  assert.equal(civ.decodeFreq(civ.encodeFreq(432123450)), 432123450);
  assert.deepEqual(civ.encodeLevel(213), [0x02, 0x13]); assert.equal(civ.decodeLevel([0x02, 0x13]), 213);
  assert.equal(civ.hex(civ.frame(0xB6, civ.CMD.PTT, [1])), "FE FE B6 E0 1C 00 01 FD");
  assert.throws(() => civ.frame(0xB6, [0x1A, 0x05], [0x00, 0x01]), /liste fermée/);   // réglage de menu : jamais
  assert.throws(() => civ.frame(0xB6, [0x18], [0x00]), /liste fermée/);                  // extinction : jamais
});

test("CI-V : flux découpé, écho, collision et octets parasites", () => {
  const p = new civ.Parser();
  assert.deepEqual(p.push([0x13, 0xFE, 0xFE, 0xE0]), []);
  const out = p.push([0xB6, 0x03, 0x00, 0x40, 0x07, 0x14, 0x00, 0xFD, 0xFE, 0xFE, 0xE0, 0xB6, 0xFC, 0xFD, 0xFE, 0xFE, 0xFE, 0xE0, 0xB6, 0xFB, 0xFD]);
  assert.equal(out.length, 2);
  assert.equal(civ.decodeFreq(out[0].payload.slice(1)), 14074000);
  assert.deepEqual(out[1].payload, [0xFB]);
  assert.equal(civ.sText(120), "S9"); assert.equal(civ.sText(241), "S9+60 dB"); assert.equal(civ.sText(0), "S0");
  assert.equal(civ.poPercent(43), 10); assert.equal(civ.swrValue(80), 2); assert.equal(civ.alcPercent(120), 50);
});

test("détection : vitesse et adresse trouvées, identité absente, autre adresse", async () => {
  const rig = new FakeIcom({ baud: 19200, echo: true });
  const d = await detect({ openAt: async b => rig.transport(b), model: MK2, bauds: models.ICOM_BAUDS, byAddr: models.byAddr });
  assert.equal(d.baud, 19200); assert.equal(d.addr, 0xB6); assert.ok(d.idSupported);
  const rig2 = new FakeIcom({ idSupported: false });
  const d2 = await detect({ openAt: async b => rig2.transport(b), model: MK2, bauds: [115200], byAddr: models.byAddr });
  assert.equal(d2.addr, 0xB6); assert.equal(d2.idSupported, false);
  const rig3 = new FakeIcom({ addr: 0xA4 });
  const d3 = await detect({ openAt: async b => rig3.transport(b), model: MK2, bauds: [115200], byAddr: models.byAddr });
  assert.equal(d3.addr, 0xA4); assert.equal(d3.guess.name, "IC-705");
  const rig4 = new FakeIcom({ baud: 1200 });
  const d4 = await detect({ openAt: async b => rig4.transport(b), model: MK2, bauds: [115200, 9600], byAddr: models.byAddr });
  assert.equal(d4.error, "silence");
});

test("parcours complet : tout réussi, état d'origine remis, émissions courtes à 10 %", async () => {
  const { rig, r } = await setup({ echo: true });
  rig.st.mode = 0x01; rig.st.freq = 28074000; rig.st.power = 128;
  const out = await r.run();
  for (const c of ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "E1", "E2", "E3", "E4", "E6", "RS"]) assert.equal(res(out, c).status, "ok", c + " : " + res(out, c).text);
  assert.equal(rig.st.freq, 28074000); assert.equal(rig.st.mode, 0x01); assert.equal(rig.st.data, 0); assert.equal(rig.st.power, 128);
  assert.equal(rig.st.ptt, false);
  assert.equal(JSON.stringify(rig.fn), rig.initialFn);                  // fonctions remises (R9)
  assert.equal(rig.txLog.length, 4);
  assert.ok(rig.maxTx() < 1000, "émission trop longue : " + rig.maxTx());
  assert.ok(res(out, "E2").values.po_pct > 8 && res(out, "E2").values.po_pct < 12);
  assert.ok(out.samples.length > 0);
});

test("AUCUNE émission avant l'autorisation, ni si elle est refusée", async () => {
  let rigRef;
  const { rig, r } = await setup({}, { authorize: async () => { assert.equal(rigRef.txLog.length, 0); assert.ok(!rigRef.writes.some(w => w.cmd.startsWith("1C 00 01"))); return false; } });
  rigRef = rig;
  const out = await r.run();
  assert.equal(rig.txLog.length, 0); assert.equal(rig.st.ptt, false);
  assert.ok(!rig.writes.some(w => w.cmd.startsWith("1C 00 01")));
  for (const c of ["E1", "E2", "E3", "E4", "E6"]) assert.equal(res(out, c).status, "saute");
  assert.equal(res(out, "RS").status, "ok");
  // La garde refuse d'elle-même sans autorisation.
  const g = new TxGuard({ setPtt: async () => true, sendNow: async () => {}, readPtt: async () => false });
  await assert.rejects(() => g.key("x"), /pas d'autorisation/);
});

test("durée maximale : la garde coupe même si l'essai dure plus longtemps", async () => {
  const { rig, r } = await setup({}, {}, { e1: 1500, maxTx: 300 });
  const out = await r.run();
  assert.ok(rig.txLog[0] < 500, "première émission : " + rig.txLog[0]);
  assert.ok(rig.maxTx() < 500);
  assert.ok(out.results.length > 0);
});

test("STOP pendant la porteuse : réception tout de suite, plus d'émission, état remis", async () => {
  const { rig, r } = await setup({}, {}, { e2: 3000 });
  let t0 = null;
  r.ui.event = e => { if (e.type === "tx" && e.on && e.label === "E2") setTimeout(() => { t0 = Date.now(); r.stop("stop"); }, 60); };
  const out = await r.run();
  assert.equal(rig.st.ptt, false);
  assert.equal(rig.txLog.length, 2);                          // E1 puis E2 coupée
  assert.ok(rig.txLog[1] < 400, "E2 : " + rig.txLog[1]);
  assert.ok(Date.now() - t0 < 1500, "fin " + (Date.now() - t0) + " ms après le STOP");
  assert.equal(out.stop, "stop");
  assert.equal(rig.st.mode, 0x01); assert.equal(res(out, "RS").status, "ok");
});

test("erreur pendant une émission (lecture qui plante) : réception, état remis", async () => {
  const { rig, r } = await setup();
  const real = r.link.level.bind(r.link); let n = 0;
  r.link.level = async cmd => { if (cmd === civ.CMD.PO_METER && rig.st.ptt && ++n === 2) throw new Error("panne simulée"); return real(cmd); };
  const errors = []; const show = r.ui.event; r.ui.event = e => { if (e.type === "error") errors.push(e.text); show(e); };
  const out = await r.run();
  assert.deepEqual(errors, ["panne simulée"]);
  assert.equal(rig.st.ptt, false);
  assert.equal(rig.txLog.length, 1);                          // panne pendant E1 : coupure, plus aucune émission
  assert.equal(rig.st.freq, 14074000); assert.equal(rig.st.mode, 0x01);
  assert.equal(res(out, "RS").status, "ok");
});

test("PTT qui résiste à la première coupure : ordre répété, réception relue", async () => {
  const { rig, r } = await setup({ ignorePttOff: 1 });
  const out = await r.run();
  assert.equal(rig.st.ptt, false);
  assert.equal(res(out, "E1").status, "ok");
  assert.ok(rig.maxTx() < 1000);
});

test("poste déjà en émission (opérateur) : rien n'est écrit, essais arrêtés", async () => {
  const { rig, r } = await setup({ alreadyTx: true });
  const before = rig.writes.length;
  const out = await r.run();
  assert.equal(res(out, "R6").status, "echec");
  const isWrite = c => /^0[56] /.test(c) || /^(14 0A|1A 06|1C 00) ../.test(c);
  assert.deepEqual(rig.writes.slice(before).filter(w => isWrite(w.cmd)), []);
  assert.ok(rig.writes.slice(before).some(w => w.cmd === "1C 00"));          // le PTT a bien été lu
  assert.equal(rig.st.ptt, true);                               // la page ne touche pas à l'émission de l'opérateur
  assert.equal(res(out, "RS").status, "na");
});

test("affichage qui plante, mesures absentes, mode données refusé, PTT illisible", async () => {
  const a = await setup({ silent: ["15 12"], ng: ["1A 06"] }, { event: () => { throw new Error("écran"); } });
  const out = await a.r.run();
  assert.equal(res(out, "E3").status, "na"); assert.equal(res(out, "E4").status, "na");
  assert.equal(res(out, "E2").status, "ok"); assert.equal(a.rig.st.ptt, false);
  const b = await setup({ silent: ["1C 00"] });
  const out2 = await b.r.run();
  assert.equal(res(out2, "R6").status, "avert");
  assert.equal(b.rig.txLog.length, 0);                        // PTT illisible = aucune émission
  assert.equal(res(out2, "E1").status, "saute");
});

test("tonalité sans puissance : échec avec le conseil DATA MOD / volume", async () => {
  const { rig, r } = await setup();
  r.audio.startTone = async () => {};                         // son qui n'arrive pas au poste
  const out = await r.run();
  assert.equal(res(out, "E4").status, "echec"); assert.match(res(out, "E4").text, /DATA MOD/);
  assert.equal(rig.st.ptt, false);
});

test("sortie son impossible à ouvrir : E4 en échec SANS émission, E6 fait quand même", async () => {
  const { rig, r } = await setup();
  r.audio.startTone = async () => { throw new Error("setSinkId refusé"); };
  const out = await r.run();
  assert.equal(res(out, "E4").status, "echec"); assert.match(res(out, "E4").text, /setSinkId/);
  assert.equal(res(out, "E6").status, "ok"); assert.equal(rig.txLog.length, 3); assert.equal(rig.st.ptt, false);
});

test("puissance non réglable par la CAT : réglage à la main demandé, refus = aucune émission", async () => {
  let asked = 0;
  const { rig, r } = await setup({ ng: ["14 0A"] }, { confirmManualPower: async () => { asked++; return false; } });
  const out = await r.run();
  assert.equal(asked, 1); assert.equal(rig.txLog.length, 0); assert.equal(res(out, "E1").status, "saute");
});

test("R9 : chaque fonction lue, changée, relue, remise et relue, SANS émission", async () => {
  const { rig, r } = await setup({ echo: true });
  const before = JSON.stringify(rig.fn), f0 = rig.st.freq, o0 = rig.st.otherFreq;
  await r._r9();
  const r9 = r.results.find(x => x.code === "R9"), rows = r9.values.fonctions;
  assert.equal(r9.status, "ok", r9.text);
  assert.equal(rows.length, 14);                                        // coupleur : plus jamais écrit en R9
  for (const row of rows) assert.equal(row.statut, "ok", row.code);
  for (const code of ["ATT", "P.AMP", "IP+", "NB", "NR", "RIT", "SPLIT", "VFO A/B"]) assert.ok(r9.text.includes(code), code);
  assert.ok(!rig.writes.some(w => w.cmd.startsWith("1C 01 ")), "coupleur écrit en R9");
  assert.equal(JSON.stringify(rig.fn), before);
  assert.equal(rig.st.freq, f0); assert.equal(rig.st.otherFreq, o0);
  assert.equal(rig.txLog.length, 0);
  assert.ok(!rig.writes.some(w => /^(1C 00 01|1C 01 02|16 46)/.test(w.cmd)), "émission, accord ou VOX écrit");
  assert.equal(rows.find(x => x.code === "VFO A/B").relu, "7.100.000");
});

test("R9 : fonction absente, écriture refusée, relue fausse, fonction qui en coupe une autre", async () => {
  const { rig, r } = await setup({ silent: ["16 65"], ngWrite: ["16 22"], stuck: ["16 40"], pampClearsAtt: true, fn: { "11": [0x20] } });
  await r._r9();
  const r9 = r.results.find(x => x.code === "R9"), row = c => r9.values.fonctions.find(x => x.code === c);
  assert.equal(row("IP+").statut, "absent");
  assert.equal(row("NB").statut, "refus");
  assert.equal(row("NR").statut, "ecart");
  assert.equal(row("ATT").statut, "ok");
  assert.deepEqual(rig.fn["11"], [0x20]);                               // ATT remis par la seconde passe
  assert.equal(r9.status, "avert", r9.text);
  assert.ok(/absentes : IP\+/.test(r9.text) && /refusée : NB/.test(r9.text) && /fausses : NR/.test(r9.text), r9.text);
});

test("R9 : niveau arrondi au cran du poste = OK (pas « relu faux »), un vrai écart reste signalé", async () => {
  const { rig, r } = await setup({ quantize: { "14 06": 13, "14 0E": 25.5 }, stuck: ["14 12"],
                                   fn: { "14 06": [0x01, 0x04], "14 0E": [0x01, 0x02] } });   // valeurs de départ sur un cran
  await r._r9();
  const r9 = r.results.find(x => x.code === "R9"), row = c => r9.values.fonctions.find(x => x.code === c);
  assert.equal(row("NR niv.").statut, "ok"); assert.ok(/arrondi au cran/.test(row("NR niv.").note || ""), JSON.stringify(row("NR niv.")));
  assert.equal(row("COMP niv.").statut, "ok");
  assert.equal(row("NB niv.").statut, "ecart");                          // valeur jamais prise : vrai défaut
  assert.equal(JSON.stringify(rig.fn), rig.initialFn);
});

// ---- R10 : spectre du poste (trames 27 00), SANS émission
async function r10(rigOpts, opts) {
  const { rig, r, d } = await setup(rigOpts, null, opts);
  r.orig.freq = rig.st.freq;
  await r._r10();
  rig.stopScope();
  return { rig, r, d, r10: r.results.find(x => x.code === "R10") };
}

test("R10 : balayages complets comptés, bornes autour de la fréquence, spectre remis comme il était", async () => {
  const { rig, r, d, r10: x } = await r10({ scopeDisplay: 1, scopeOutput: 0 });
  assert.equal(x.status, "ok", x.text);
  assert.ok(x.values.balayages >= 3, JSON.stringify(x.values));
  assert.deepEqual(Object.keys(x.values.points), ["475"]);
  assert.deepEqual(x.values.bornes_hz, [14024000, 14124000]);
  assert.equal(x.values.apercu.length, 64); assert.equal(x.values.remis, true);
  assert.deepEqual(rig.scope, { display: 1, output: 0 });                     // sortie recoupée
  assert.ok(!rig.writes.some(w => w.ptt), "écriture pendant une émission");
  assert.ok(!rig.writes.some(w => w.cmd.startsWith("1C 00 01")), "émission pendant R10");
  // Trace limitée pendant la capture, le reste compté.
  assert.ok(x.values.octets_non_traces > 0, "octets non tracés non comptés");
  assert.ok(d.link.trace.every(t => /^[0-9A-F ]+$/.test(t.h)));
  assert.equal(r.orig.scope.output, 0);
});

test("R10 : affichage du spectre éteint au départ = allumé pour l'essai puis éteint de nouveau", async () => {
  const { rig, r10: x } = await r10({ scopeDisplay: 0, scopeOutput: 0 });
  assert.equal(x.status, "ok", x.text); assert.deepEqual(rig.scope, { display: 0, output: 0 });
});

test("R10 : poste sans spectre CI-V = non disponible, jamais un échec", async () => {
  const { r10: x } = await r10({ scope: false });
  assert.equal(x.status, "na", x.text);
});

test("R10 : trames adressées à un autre contrôleur (station en E1) comptées, jamais prises", async () => {
  const { r10: x } = await r10({ scopeTo: 0xE1 });
  assert.equal(x.status, "avert", x.text);
  assert.equal(x.values.trames, 0); assert.ok(x.values.autres > 0); assert.ok(/autre contrôleur/.test(x.text));
});

test("R10 : aucune trame reçue, fréquence hors du balayage, spectre non remis", async () => {
  const none = await r10({ scopeEvery: 100000 });
  assert.equal(none.r10.status, "avert"); assert.ok(/aucune donnée du spectre/.test(none.r10.text), none.r10.text);
  const off = await r10({ scopeCenter: 7100000 });
  assert.equal(off.r10.status, "avert"); assert.ok(/hors du balayage/.test(off.r10.text), off.r10.text);
  const stuck = await r10({ scopeOutput: 1, scopeDisplay: 1 });
  assert.equal(stuck.r10.status, "ok", stuck.r10.text); assert.deepEqual(stuck.rig.scope, { display: 1, output: 1 });   // en marche au départ : laissé en marche
  stuck.rig.stopScope();
});

test("R10 : STOP pendant la capture = essai sauté et spectre remis", async () => {
  const { rig, r } = await setup({}, null, { scope: 2000 });
  r.orig.freq = rig.st.freq;
  const p = r._r10();
  setTimeout(() => r.stop("stop"), 100);
  const t0 = Date.now(); await p; rig.stopScope();
  assert.ok(Date.now() - t0 < 1500, "STOP pas pris en compte");
  assert.equal(r.results.find(x => x.code === "R10").status, "saute");
  assert.deepEqual(rig.scope, { display: 1, output: 0 });
});

test("R10 : découpeur et assemblage d'un balayage coupé en blocs, liste fermée du spectre", () => {
  const rig = new FakeIcom(), bytes = [].concat(...rig.sweepFrames()), p = new civ.Parser(), asm = new civ.ScopeAssembler();
  let sweep = null;
  for (let i = 0; i < bytes.length; i += 5) for (const f of p.push(bytes.slice(i, i + 5))) sweep = asm.feed(f.payload.slice(2), 0) || sweep;
  assert.equal(sweep.points.length, 475); assert.equal(sweep.f1, 14074000); assert.equal(sweep.f2, 50000);
  assert.deepEqual(civ.scopeEdges(sweep), [14024000, 14124000]);
  assert.throws(() => civ.frame(0xB6, civ.CMD.SCOPE_OUT, [0x02]), /hors de la liste/);
  assert.throws(() => civ.frame(0xB6, [0x27, 0x00], []), /hors de la liste/);        // la page n'envoie jamais de données du spectre
});

// ---- Coupleur d'antenne : lu au début, accord SEULEMENT dans E7, sous la garde (15 s au plus)
const TUNE_UI = (type, texte) => ({ authorize: async () => ({ ok: true, tuner: { type, texte: texte || "" } }) });
const tuneWrites = rig => rig.writes.filter(w => w.cmd.startsWith("1C 01 "));

test("E7 : AH-4 en service = mis hors service puis remis (accord lancé par le poste), PTT relu, laissé en service", async () => {
  const { rig, r } = await setup({ tuner: "ah4", tuner0: 1, tuneMs: 150 }, TUNE_UI("AH-4"));
  const out = await r.run(); rig.stopScope();
  const e7 = res(out, "E7");
  assert.equal(e7.status, "ok", e7.text); assert.ok(/Accord réussi/.test(e7.text));
  assert.equal(rig.tunerState, 1); assert.equal(rig.tuning, false); assert.equal(rig.st.ptt, false);
  assert.deepEqual(tuneWrites(rig).map(w => w.cmd), ["1C 01 00", "1C 01 01"]);          // jamais 02 : le poste a accordé seul
  assert.equal(out.tuner, 1); assert.deepEqual(out.tunerDeclared, { type: "AH-4", texte: "" });
  for (const c of ["R9", "E1", "E2", "E3", "E4", "E6", "RS"]) assert.equal(res(out, c).status, "ok", c + " : " + res(out, c).text);
});

test("E7 : coupleur intégré hors service = accord lancé par la page (1C 01 02), remis hors service", async () => {
  const { rig, r } = await setup({ tuner: "interne", tuner0: 0, tuneMs: 120 }, TUNE_UI("interne"));
  const out = await r.run(); rig.stopScope();
  assert.equal(res(out, "E7").status, "ok", res(out, "E7").text);
  assert.deepEqual(tuneWrites(rig).map(w => w.cmd), ["1C 01 01", "1C 01 02", "1C 01 00"]);
  assert.equal(rig.tunerState, 0);
});

test("E7 : AUCUNE écriture du coupleur sans autorisation ni avant elle", async () => {
  const { rig, r } = await setup({ tuner: "ah4", tuner0: 1 }, { authorize: async () => false });
  const out = await r.run(); rig.stopScope();
  assert.equal(tuneWrites(rig).length, 0); assert.equal(rig.tunes.length, 0);
  assert.equal(res(out, "E7").status, "saute");
  const g = new TxGuard(new civ.CivLink(rig.transport(115200), 0xB6), { maxTx: 1000 });
  assert.throws(() => g.startTune("E7", 1000), /autorisation/);
  await assert.rejects(() => g.link.tunerStart(g), /garde/);                                 // accord hors de la garde : refusé
});

test("E7 : accord trop long = coupé à la durée maximale (coupleur hors service, réception relue)", async () => {
  const { rig, r } = await setup({ tuner: "ah4", tuner0: 0, tuneMs: 60000 }, TUNE_UI("AH-4"), { tune: 400 });
  const out = await r.run(); rig.stopScope();
  const e7 = res(out, "E7");
  assert.equal(e7.status, "echec", e7.text); assert.ok(/non terminé/.test(e7.text));
  assert.equal(rig.tuning, false); assert.ok(rig.maxTune() < 1200, "accord trop long : " + rig.maxTune());
  assert.equal(rig.st.ptt, false); assert.equal(rig.tunerState, 0);
});

test("E7 : STOP pendant l'accord = accord interrompu, coupleur hors service, essais arrêtés", async () => {
  const { rig, r } = await setup({ tuner: "ah4", tuner0: 0, tuneMs: 60000 }, TUNE_UI("AH-4"), { tune: 5000 });
  r.ui.event = e => { if (e.type === "tx" && e.on && e.label === "E7") setTimeout(() => r.stop("stop"), 150); };
  const out = await r.run(); rig.stopScope();
  assert.equal(res(out, "E7").status, "saute", res(out, "E7").text);
  assert.equal(rig.tuning, false); assert.ok(rig.maxTune() < 1000, "accord pas interrompu : " + rig.maxTune());
  assert.equal(rig.st.ptt, false);
});

test("E7 : « aucun coupleur » déclaré, accord impossible, poste sans coupleur", async () => {
  const a = await setup({ tuner: "ah4", tuner0: 1 }, TUNE_UI("aucun"));
  const oa = await a.r.run(); a.rig.stopScope();
  assert.equal(res(oa, "E7").status, "avert"); assert.equal(tuneWrites(a.rig).length, 0);
  const b = await setup({ tuner: "ah4", tuner0: 0, tuneMs: 100, tuneResult: 0 }, TUNE_UI("autre", "LDG IT-100"));
  const ob = await b.r.run(); b.rig.stopScope();
  assert.equal(res(ob, "E7").status, "avert"); assert.ok(/dérivation/.test(res(ob, "E7").text));
  assert.equal(ob.tunerDeclared.texte, "LDG IT-100");
  const c = await setup({ tuner: "aucun" });
  const oc = await c.r.run(); c.rig.stopScope();
  assert.equal(res(oc, "E7").status, "na"); assert.equal(oc.tuner, null);
});

test("R9 : atténuateur du modèle (IC-7100 : 12 dB), valeurs connues essayées pour un autre modèle", async () => {
  const ic7100 = models.ICOM.find(m => m.id === "ic7100");
  const rig = new FakeIcom({ addr: 0x88, att: [0x12] });
  const d = await detect({ openAt: async b => rig.transport(b), model: ic7100, bauds: [115200], byAddr: models.byAddr });
  const r = new Runner({ link: d.link, model: ic7100, audio: fakeAudio(rig), ui: ui(), opts: FAST, detected: d });
  await r._r9();
  const att = r.results.find(x => x.code === "R9").values.fonctions.find(x => x.code === "ATT");
  assert.equal(att.statut, "ok"); assert.equal(att.essai, "12");
  const { rig: rig2, r: r2 } = await setup({ att: [0x06, 0x12, 0x18] });     // modèle inconnu de la table : 20 refusé, 12 pris
  r2.link.attValues = null;
  await r2._r9();
  const att2 = r2.results.find(x => x.code === "R9").values.fonctions.find(x => x.code === "ATT");
  assert.equal(att2.statut, "ok", JSON.stringify(att2)); assert.equal(att2.essai, "12"); assert.deepEqual(rig2.fn["11"], [0x00]);
});

test("E4 : rampe à 50 % : coude et conseil sur le niveau USB MOD (trop fort, bien réglé, trop faible), puissance remise", async () => {
  const run = async knee => { const { rig, r } = await setup({ modKnee: knee }); const out = await r.run(); rig.stopScope(); return { rig, out, e4: res(out, "E4") }; };
  const strong = await run(-24);
  assert.equal(strong.e4.status, "avert", strong.e4.text); assert.ok(/trop fort, baissez-le d'environ \d+ dB/.test(strong.e4.text), strong.e4.text);
  assert.equal(strong.e4.values.puissance_pct, 50); assert.equal(strong.e4.values.rampe.length, 9);
  const good = await run(-6);
  assert.equal(good.e4.status, "ok", good.e4.text); assert.ok(/bien réglé/.test(good.e4.text)); assert.equal(good.e4.values.coude_dbfs, -4);
  const weak = await run(+6);
  assert.equal(weak.e4.status, "avert"); assert.ok(/trop faible/.test(weak.e4.text), weak.e4.text);
  // 50 % seulement pendant la rampe : puissance des essais (10 %) remise juste après, puis celle d'origine à la fin.
  assert.ok(good.rig.writes.some(w => w.cmd === "14 0A 01 28"), "50 % jamais réglé");
  assert.equal(good.rig.st.power, 255);
  const rep = await report.build({ brand: models.BRANDS[0], model: MK2, chosenModel: MK2, detected: {}, run: good.out, trace: [] });
  assert.ok(rep.mesures_emission.some(m => m.essai === "E4" && m.niveau_dbfs === -30));
});

test("E4 : STOP pendant la rampe = tonalité coupée, essai sauté, puissance des essais remise", async () => {
  const { rig, r } = await setup({}, null, { e4: 3000 });
  r.ui.event = e => { if (e.type === "tx" && e.on && e.label === "E4") setTimeout(() => r.stop("stop"), 200); };
  const out = await r.run(); rig.stopScope();
  assert.equal(res(out, "E4").status, "saute"); assert.equal(rig.toneOn, false); assert.equal(rig.st.ptt, false);
  assert.ok(rig.maxTx() < 1500, "rampe pas coupée : " + rig.maxTx());
});

test("liste fermée : commande exacte, jamais l'accord du coupleur, le VOX ni un préfixe", () => {
  assert.throws(() => civ.frame(0xB6, civ.CMD.TUNER, [0x02]), /hors de la liste/);   // 02 = lancer l'accord (émission)
  assert.throws(() => civ.frame(0xB6, [0x16, 0x46], [0x01]), /hors de la liste/);   // VOX
  assert.throws(() => civ.frame(0xB6, [0x36], []), /hors de la liste/);              // « 3 » n'accepte plus « 36 »
  assert.throws(() => civ.frame(0xB6, civ.CMD.VFO_FREQ, [0x00, 0x00, 0x40, 0x07, 0x14, 0x00]), /hors de la liste/);  // jamais d'écriture
  assert.throws(() => civ.frame(0xB6, civ.CMD.ATT, [0x99]), /hors de la liste/);
  assert.equal(civ.hex(civ.frame(0xB6, civ.CMD.TUNER, [0x01])), "FE FE B6 E0 1C 01 01 FD");
});

test("rapport : anonyme, trace et empreinte, résumé", async () => {
  const { r, d } = await setup();
  const out = await r.run();
  const rep = await report.build({ brand: models.BRANDS[0], model: MK2, chosenModel: MK2, detected: d, usb: { usbVendorId: 0x10c4, usbProductId: 0xea60 },
                                   audio: { inputLabel: "2- USB Audio Device (08bb:2902)", outputLabel: "Haut-parleurs (USB Audio CODEC )" }, run: out, trace: d.link.trace, startedAt: "2026-11-19T21:00:00.000Z" });
  assert.equal(rep.schema, "openremotetrx-autotest/1");
  assert.equal(rep.carte_son.entree, "USB Audio Device");
  assert.deepEqual(rep.poste.usb, { vid: "10c4", pid: "ea60" });
  assert.equal(rep.poste.adresse_civ, "B6");
  assert.match(rep.empreinte_trace, /^[0-9a-f]{64}$/);
  assert.ok(rep.trace.length > 20 && rep.trace.every(x => /^[0-9A-F ]+$/.test(x.h)));
  const s = report.summary(rep); assert.equal(s.verdict, "ok");
  assert.equal(report.fileName(rep), "autotest-IC-7300MK2-202611192100.json");
  const txt = JSON.stringify(rep);
  assert.ok(!/serial|hostname|COM\d/i.test(txt));
});

// ---------- Yaesu (CAT ASCII, FTDX10) ----------
const Y = require("./autotest_fake_yaesu.js");
const FTDX10 = models.YAESU.find(m => m.id === "ftdx10");
async function setupY(rigOpts, uiOver, opts, audioOpts) {
  const rig = new Y.FakeYaesu(rigOpts);
  const d = await Y.ya.detect({ openAt: async b => rig.transport(b), model: FTDX10, bauds: models.YAESU_BAUDS, byId: models.byIdent });
  assert.ok(!d.error, JSON.stringify(d));
  const u = ui(uiOver);
  const r = new Runner({ link: d.link, model: FTDX10, audio: Y.fakeAudio(rig, audioOpts), ui: u, opts: Object.assign({}, FAST, opts), detected: d });
  return { rig, d, u, r };
}

test("Yaesu : liste fermée (jamais VOX, menus, alimentation, MOX, accord du coupleur, split + 5 kHz)", () => {
  const f = Y.ya.frame;
  for (const [c, v] of [["VX", "1"], ["EX", "010101"], ["PS", "0"], ["MX", "1"], ["AC00", "2"], ["ST", "2"], ["TX", "2"], ["PC", "1000"]])
    assert.throws(() => f(c, v), /liste fermée/, c + v);
  assert.throws(() => f("EX"), /liste fermée/);
  assert.equal(f("TX", "0"), "TX0;"); assert.equal(f("FA"), "FA;"); assert.equal(f("AC00", "1"), "AC001;");
});

test("Yaesu : détection (vitesse, identité 0761 = FTDX10, autre vitesse du menu)", async () => {
  const rig = new Y.FakeYaesu({ baud: 9600 });
  const d = await Y.ya.detect({ openAt: async b => rig.transport(b), model: null, bauds: models.YAESU_BAUDS, byId: models.byIdent });
  assert.equal(d.baud, 9600); assert.equal(d.ident, "0761"); assert.equal(d.guess.name, "FTDX10");
});

test("Yaesu : parcours complet réussi, état d'origine remis, émissions courtes à 10 %", async () => {
  const { rig, r } = await setupY({});
  const out = await r.run();
  for (const c of ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "E1", "E2", "E3", "E4", "E6", "RS"]) assert.equal(res(out, c).status, "ok", c + " : " + res(out, c).text);
  assert.equal(rig.st.FA, "007074000"); assert.equal(rig.st.MD0, "1"); assert.equal(rig.st.PC, "100"); assert.equal(rig.st.TX, "0");
  assert.equal(JSON.stringify(rig.fn), rig.initialFn);
  assert.equal(rig.txLog.length, 4); assert.ok(rig.maxTx() < 1000);
  assert.ok(!rig.writes.some(w => /^(VX|EX|PS|MX|AC002|ST2)/.test(w.cmd)));
  assert.ok(res(out, "E4").text.includes("Po"));
  assert.equal(res(out, "R9").values.fonctions.find(x => x.code === "VFO A/B").relu, "14.074.000");
});

test("Yaesu : aucune émission sans autorisation ; STOP pendant la porteuse", async () => {
  const a = await setupY({}, { authorize: async () => false });
  await a.r.run(); assert.equal(a.rig.txLog.length, 0); assert.ok(!a.rig.writes.some(w => w.cmd === "TX1"));
  const b = await setupY({}, {}, { e2: 3000 });
  let t0 = null;
  b.r.ui.event = e => { if (e.type === "tx" && e.on && e.label === "E2") setTimeout(() => { t0 = Date.now(); b.r.stop("stop"); }, 60); };
  const out = await b.r.run();
  assert.equal(b.rig.st.TX, "0"); assert.equal(b.rig.txLog.length, 2); assert.ok(b.rig.txLog[1] < 400);
  assert.ok(Date.now() - t0 < 1500); assert.equal(res(out, "RS").status, "ok");
});

test("Yaesu : R9 fonction absente, écriture refusée « ?; », relue fausse ; poste déjà en émission", async () => {
  const { rig, r } = await setupY({ silent: ["PR0"], ngWrite: ["NB0"], stuck: ["RL0"] });
  await r._r9();
  const r9 = r.results.find(x => x.code === "R9"), row = c => r9.values.fonctions.find(x => x.code === c);
  assert.equal(row("COMP").statut, "absent"); assert.equal(row("NB").statut, "refus"); assert.equal(row("NR niv.").statut, "ecart");
  assert.equal(row("SPLIT").statut, "ok"); assert.equal(JSON.stringify(rig.fn), rig.initialFn);
  const busy = await setupY({ alreadyTx: true });
  const out = await busy.r.run();
  assert.equal(res(out, "R6").status, "echec"); assert.ok(!busy.rig.writes.some(w => /^(TX[01]|FA\d|MD0.)/.test(w.cmd)));
});

// ---------- Kenwood (commandes PC ASCII, TS-890S) ----------
const K = require("./autotest_fake_kenwood.js");
const TS890 = models.KENWOOD.find(m => m.id === "ts890s");
async function setupK(rigOpts, uiOver, opts, audioOpts) {
  const rig = new K.FakeKenwood(rigOpts);
  const d = await K.kw.detect({ openAt: async b => rig.transport(b), model: TS890, bauds: models.KENWOOD_BAUDS, byId: models.byKenwood });
  assert.ok(!d.error, JSON.stringify(d));
  const u = ui(uiOver);
  const r = new Runner({ link: d.link, model: TS890, audio: K.fakeAudio(rig, audioOpts), ui: u, opts: Object.assign({}, FAST, opts), detected: d });
  return { rig, d, u, r };
}

test("Kenwood : liste fermée (jamais TX TUNE, VOX, menus, alimentation, accord du coupleur, AI sauvegardée)", () => {
  const f = K.kw.frame;
  for (const [c, v] of [["TX", "2"], ["VX", "1"], ["EX", "00000001"], ["PS", "0"], ["AC", "111"], ["AC", "101"], ["AI", "4"], ["RT", "2"]])
    assert.throws(() => f(c, v), /liste fermée/, c + v);
  assert.equal(f("RX", ""), "RX;"); assert.equal(f("AC", "110"), "AC110;"); assert.equal(f("OM0"), "OM0;");
});

test("Kenwood : parcours complet réussi, AI et mesures remises, état d'origine remis", async () => {
  const { rig, r } = await setupK({});
  const out = await r.run();
  for (const c of ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "E1", "E2", "E3", "E4", "E6", "RS"]) assert.equal(res(out, c).status, "ok", c + " : " + res(out, c).text);
  assert.equal(rig.st.FA, "00007074000"); assert.equal(rig.st.OM0, "1"); assert.equal(rig.st.PC, "100"); assert.equal(rig.tx, false);
  assert.equal(JSON.stringify(rig.fn), rig.initialFn);
  assert.equal(rig.st.AI, "0"); assert.equal(rig.rm[1], false); assert.equal(rig.rm[2], false);   // AI et mesures remises
  assert.equal(rig.txLog.length, 4); assert.ok(rig.maxTx() < 1000);
  assert.ok(rig.writes.some(w => w.cmd === "TX1"), "tonalité en DATA SEND (TX1)");
  assert.ok(!rig.writes.some(w => /^(TX2|VX|EX|PS|AC1.1|AI4)/.test(w.cmd)));
  assert.ok(/annonces automatiques/.test(res(out, "R6").text));
});

test("Kenwood : sans annonces AI, PTT illisible = aucune émission ; STOP pendant la porteuse", async () => {
  const a = await setupK({ ng: ["AI"] });
  const outA = await a.r.run();
  assert.equal(res(outA, "R6").status, "avert"); assert.equal(a.rig.txLog.length, 0); assert.ok(!a.rig.writes.some(w => /^TX/.test(w.cmd)));
  const b = await setupK({}, {}, { e2: 3000 });
  let t0 = null;
  b.r.ui.event = e => { if (e.type === "tx" && e.on && e.label === "E2") setTimeout(() => { t0 = Date.now(); b.r.stop("stop"); }, 60); };
  const out = await b.r.run();
  assert.equal(b.rig.tx, false); assert.equal(b.rig.txLog.length, 2); assert.ok(b.rig.txLog[1] < 400);
  assert.ok(Date.now() - t0 < 1500); assert.equal(res(out, "RS").status, "ok");
});

// ---------- Mode B : Hamlib par le programme local ----------
const hamlib = require(path.join(W, "hamlib.js"));
const { FakeHamlib, PROFILE, allowed } = require("./autotest_fake_hamlib.js");
function setupH(rigOpts, uiOver, opts, profile) {
  const rig = new FakeHamlib(rigOpts);
  const link = new hamlib.HamlibLink(rig, profile || PROFILE);
  const d = { baud: null, link, transport: { close: async () => {} }, hamlib: { n: 3094, nom: PROFILE.nom, version: "4.7.2", statut: (profile || PROFILE).statut_backend } };
  const u = ui(uiOver);
  const r = new Runner({ link, model: MK2, audio: fakeAudio(rig), ui: u, opts: Object.assign({}, FAST, opts), detected: d });
  return { rig, link, d, u, r };
}

test("Hamlib : fonctions retenues d'après les capacités (jamais VOX, coupleur, XIT, split)", () => {
  const codes = hamlib.buildFuncs(PROFILE).map(f => f.code);
  assert.deepEqual(codes, ["ATT", "P.AMP", "NB", "NR", "ANF", "COMP", "MN", "RIT", "NR niv.", "NB niv."]);
  for (const bad of ["VOX", "TUNER", "XIT", "SPLIT"]) assert.ok(!codes.includes(bad), bad);
  assert.deepEqual(hamlib.buildFuncs({}), []);
  assert.equal(hamlib.scale.sText(0), "S9"); assert.equal(hamlib.scale.sText(-54), "S0"); assert.equal(hamlib.scale.sText(20), "S9+20 dB");
  assert.ok(!allowed("U VOX 1") && !allowed("U TUNER 1") && !allowed("S 1 VFOB") && !allowed("M USB 2400") && allowed("M USB 0"));
});

test("Hamlib : parcours complet réussi, état d'origine remis, émissions courtes à 10 %, aucune commande hors liste", async () => {
  const { rig, r } = setupH();
  const out = await r.run();
  for (const c of ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "E1", "E2", "E3", "E4", "E6", "RS"]) assert.equal(res(out, c).status, "ok", c + " : " + res(out, c).text);
  assert.deepEqual(rig.refused, []);
  assert.equal(rig.freq, 7074000); assert.equal(rig.mode, "USB"); assert.equal(rig.levels.RFPOWER, 1); assert.equal(rig.ptt, 0);
  assert.equal(rig.state(), rig.initial);
  assert.equal(rig.txLog.length, 4); assert.ok(rig.maxTx() < 1000);
  assert.ok(rig.lines.includes("L RFPOWER 0.1"), "puissance à 10 %");
  assert.ok(rig.lines.includes("M PKTUSB 0"), "tonalité en PKTUSB");
  assert.ok(rig.lines.every(l => !/^M \S+ [1-9]/.test(l)), "largeur toujours 0");
  assert.ok(/Hamlib/.test(res(out, "R1").text) && /IC-7300MK2/.test(res(out, "R2").text));
});

test("Hamlib : aucune émission sans autorisation ; STOP pendant la porteuse = coupure par le programme", async () => {
  const a = setupH({}, { authorize: async () => false });
  await a.r.run(); assert.equal(a.rig.txLog.length, 0); assert.ok(!a.rig.lines.includes("T 1"));
  const b = setupH({}, {}, { e2: 3000 });
  let t0 = null;
  b.r.ui.event = e => { if (e.type === "tx" && e.on && e.label === "E2") setTimeout(() => { t0 = Date.now(); b.r.stop("stop"); }, 60); };
  const out = await b.r.run();
  assert.equal(b.rig.ptt, 0); assert.equal(b.rig.txLog.length, 2); assert.ok(b.rig.txLog[1] < 400); assert.ok(b.rig.pttOffs >= 1);
  assert.ok(Date.now() - t0 < 1500); assert.equal(res(out, "RS").status, "ok");
  // le retour en réception d'urgence est dans la trace du rapport (étape 374) : ordre puis relecture
  const urg = b.link.trace.filter(x => x.c === "urgence");
  assert.deepEqual(urg.slice(0, 2).map(x => [x.h, x.r]), [["T 0", 0], ["t", 0]]);
  assert.deepEqual(urg[1].v, ["0"]);
  // connexion à part impossible : l'ordre repasse par la file normale, et la trace le dit
  const c = setupH();
  c.rig.pttOff = async () => { throw new Error("hors service"); };
  await c.link.pttOffNow();
  assert.deepEqual(c.link.trace.slice(-2).map(x => [x.h, x.c || null, x.e || null]), [["T 0", "urgence", "page"], ["T 0", null, null]]);
});

test("Hamlib : poste déjà en émission, fonction refusée, niveau figé, backend non stable", async () => {
  const busy = setupH({ alreadyTx: true });
  const o1 = await busy.r.run();
  assert.equal(res(o1, "R6").status, "echec"); assert.ok(!busy.rig.lines.some(l => /^[FMLUT] /.test(l)));
  const odd = setupH({ ng: ["U ANF"], stuck: ["NB"] }, {}, {}, Object.assign({}, PROFILE, { statut_backend: "Beta" }));
  const o2 = await odd.r.run();
  const rows = res(o2, "R9").values.fonctions, row = c => rows.find(x => x.code === c);
  assert.equal(row("ANF").statut, "refus"); assert.equal(row("NB niv.").statut, "ecart"); assert.equal(row("NR niv.").statut, "ok");
  assert.equal(res(o2, "R9").status, "avert"); assert.equal(res(o2, "R2").status, "avert");
  assert.equal(odd.rig.ptt, 0);
});

test("Hamlib : atténuateur déclaré 20 dB mais refusé (IC-7100) = 12 dB essayé ensuite, remis", async () => {
  const { rig, r } = setupH({ att: [12] });
  await r._r9();
  const att = res(r._finish(), "R9").values.fonctions.find(x => x.code === "ATT");
  assert.equal(att.statut, "ok", JSON.stringify(att)); assert.equal(att.essai, "12"); assert.equal(rig.levels.ATT, 0);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("OK    " + name); } catch (e) { failed++; console.log("ECHEC " + name + "\n      " + (e.stack || e)); }
  }
  console.log((tests.length - failed) + "/" + tests.length + " tests d'openRemoteTRX-Autotest réussis");
  if (failed) process.exit(1);
})();
