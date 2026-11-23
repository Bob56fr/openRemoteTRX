// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Faux programme local du mode B (API de trxstation/autotest/server.py) devant un faux rigctld : réponses du
   protocole étendu déjà découpées comme le fait le programme ({rprt, valeurs, ms}). Liste fermée REPRISE de
   trxstation/autotest/rig.py (check_command) : une commande hors liste est refusée et retenue dans `refused`. */
"use strict";

const READ_LEVELS = ["STRENGTH", "RFPOWER_METER", "RFPOWER_METER_WATTS", "SWR", "ALC", "RFPOWER", "ATT", "PREAMP", "NR", "NB", "COMP", "AGC"];
const WRITE_LEVELS = ["RFPOWER", "ATT", "PREAMP", "NR", "NB", "COMP"];
const READ_FUNCS = ["NB", "NB2", "NR", "ANF", "COMP", "MN", "APF", "RIT", "XIT", "TUNER", "VOX", "LOCK"];
const WRITE_FUNCS = ["NB", "NB2", "NR", "ANF", "COMP", "MN", "APF", "RIT"];
function allowed(line) {
  const [k, ...a] = line.split(" ");
  if (["f", "m", "t", "s", "j"].includes(k)) return a.length === 0;
  if (k === "l") return a.length === 1 && READ_LEVELS.includes(a[0]);
  if (k === "u") return a.length === 1 && READ_FUNCS.includes(a[0]);
  if (k === "F") return a.length === 1 && /^\d+$/.test(a[0]);
  if (k === "M") return a.length === 2 && /^[A-Z]{2,8}$/.test(a[0]) && a[1] === "0";
  if (k === "T") return a.length === 1 && /^[01]$/.test(a[0]);
  if (k === "U") return a.length === 2 && WRITE_FUNCS.includes(a[0]) && /^[01]$/.test(a[1]);
  if (k === "L") return a.length === 2 && WRITE_LEVELS.includes(a[0]) && Number.isFinite(Number(a[1]));
  if (k === "G") return a.length === 1 && a[0] === "XCHG";
  return false;
}

const PROFILE = {
  modele: 3094, nom: "Icom IC-7300MK2", statut_backend: "Stable", hamlib: "4.7.2",
  modes: ["AM", "CW", "USB", "LSB", "RTTY", "FM", "CWR", "RTTYR", "PKTLSB", "PKTUSB", "PKTFM"],
  fonctions_lecture: ["NB", "NR", "ANF", "COMP", "MN", "VOX", "TUNER", "RIT", "XIT"], fonctions_ecriture: ["NB", "NR", "ANF", "COMP", "MN", "VOX", "TUNER", "RIT", "XIT"],
  niveaux_lecture: ["PREAMP", "ATT", "NR", "NB", "RFPOWER", "STRENGTH", "RFPOWER_METER", "SWR", "ALC"],
  niveaux_ecriture: ["PREAMP", "ATT", "NR", "NB", "RFPOWER"],
  plages: { NR: { min: 0, max: 1, pas: 0.0667 }, NB: { min: 0, max: 1, pas: 0.1 }, RFPOWER: { min: 0, max: 1, pas: 0.0039 } },
  preamplis_db: [10, 20], attenuateurs_db: [20],
};

class FakeHamlib {
  constructor(opts) {
    // att : valeurs d'atténuateur acceptées par le poste (IC-7100 : 12 alors que Hamlib déclare 20).
    this.o = Object.assign({ ptt: 0, noSwap: false, alreadyTx: false, quantum: 1 / 255, ng: [], stuck: [], att: null }, opts || {});
    this.freq = 7074000; this.other = 7100000; this.mode = "USB"; this.ptt = this.o.alreadyTx ? 1 : 0;
    this.levels = { RFPOWER: 1.0, ATT: 0, PREAMP: 0, NR: 0.4, NB: 0.6, STRENGTH: -42, SWR: 1.1, ALC: 0, RFPOWER_METER: 0 };
    this.funcs = { NB: 0, NR: 0, ANF: 0, COMP: 0, MN: 0, RIT: 0, VOX: 0, TUNER: 0 };
    this.initial = JSON.stringify({ l: this.levels, f: this.funcs });
    this.lines = []; this.refused = []; this.txLog = []; this.txSince = this.o.alreadyTx ? Date.now() : null; this.toneOn = false;
    this.pttOffs = 0;
  }
  _ptt(v) {
    const now = Date.now();
    if (v && !this.ptt) this.txSince = now;
    if (!v && this.ptt) { this.txLog.push(now - this.txSince); this.txSince = null; }
    this.ptt = v;
  }
  maxTx() { return Math.max(0, ...this.txLog, this.ptt ? Date.now() - this.txSince : 0); }
  ok(v) { return { rprt: 0, valeurs: v || [], ms: 3 }; }
  async cmd(line) {
    this.lines.push(line);
    if (!allowed(line)) { this.refused.push(line); return { erreur: "hors_liste" }; }
    const [k, a, b] = line.split(" ");
    if (this.o.ng.includes(k + (a ? " " + a : ""))) return { rprt: -11, valeurs: [], ms: 3 };
    switch (k) {
      case "f": return this.ok([String(this.freq)]);
      case "F": this.freq = Number(a); return this.ok();
      case "m": return this.ok([this.mode, "2400"]);
      case "M": if (!PROFILE.modes.includes(a)) return { rprt: -1, valeurs: [], ms: 2 }; this.mode = a; return this.ok();
      case "t": return this.ok([String(this.ptt)]);
      case "T": this._ptt(Number(a)); return this.ok();
      case "l": {
        if (a === "RFPOWER_METER") return this.ok([String(this.ptt ? (this.mode.startsWith("PKT") && !this.toneOn ? 0 : this.levels.RFPOWER) : 0)]);
        if (a === "ALC") return this.ok([String(this.ptt && this.toneOn ? 0.2 : 0)]);
        if (!(a in this.levels)) return { rprt: -11, valeurs: [], ms: 2 };
        return this.ok([String(this.levels[a])]);
      }
      case "L": {
        if (!PROFILE.niveaux_ecriture.includes(a)) return { rprt: -11, valeurs: [], ms: 2 };
        if (this.o.stuck.includes(a)) return this.ok();
        const v = Number(b);
        if (a === "ATT" && v && this.o.att && !this.o.att.includes(v)) return { rprt: -9, valeurs: [], ms: 2 };
        this.levels[a] = ["ATT", "PREAMP"].includes(a) ? v : Math.round(v / this.o.quantum) * this.o.quantum;
        if (a === "PREAMP" && v) this.levels.ATT = 0;                   // comme l'Icom : le préampli coupe l'atténuateur
        return this.ok();
      }
      case "u": return a in this.funcs ? this.ok([String(this.funcs[a])]) : { rprt: -11, valeurs: [], ms: 2 };
      case "U": if (!(a in this.funcs)) return { rprt: -11, valeurs: [], ms: 2 }; this.funcs[a] = Number(b); return this.ok();
      case "G": if (this.o.noSwap) return { rprt: -11, valeurs: [], ms: 2 }; [this.freq, this.other] = [this.other, this.freq]; return this.ok();
      default: return { rprt: -4, valeurs: [], ms: 2 };
    }
  }
  async pttOff() {
    this.pttOffs++; this._ptt(0);
    return { rx: true, trace: [{ h: "T 0", rprt: 0, valeurs: [], ms: 1 }, { h: "t", rprt: 0, valeurs: ["0"], ms: 1 }] };
  }
  state() { return JSON.stringify({ l: this.levels, f: this.funcs }); }
}

module.exports = { FakeHamlib, PROFILE, allowed };
