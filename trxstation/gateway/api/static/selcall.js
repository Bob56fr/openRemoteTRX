// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* SELCALL dans la page (docs/selcall-cahier-des-charges.md) : calculs purs, testés sous Node (tests/js/selcall_test.js),
   sans DOM. Même protocole que la station (trxstation/selcall/protocol.py) : vérifié par tests/protocol/selcall_vectors.json.

   Fichier de test : la page fabrique elle-même la trame en WAV (aucune connexion à la station) pour qu'un correspondant
   la joue au micro de son poste : 2 s de silence (le temps de passer en émission), puis la trame 3 fois séparées de 0,5 s. */
(function (root) {
  "use strict";

  const F0_HZ = 1000, PILOT_S = 1.0, SYMBOL_S = 0.3, RAMP_S = 0.005, LEVEL_DBFS = -6;
  const CODE_MIN = 3, CODE_MAX = 8, REPEAT = "R";

  function validCode(code) {
    return typeof code === "string" && /^[0-9]+$/.test(code) && code.length >= CODE_MIN && code.length <= CODE_MAX;
  }

  function symbols(code) {
    /* Chiffres puis contrôle (somme modulo 10), chaque répétition remplacée par R : « 4477 » -> 4 R 7 R 2. */
    if (!validCode(code)) throw new Error("code SELCALL : " + CODE_MIN + " à " + CODE_MAX + " chiffres");
    const sum = [...code].reduce((s, c) => s + Number(c), 0) % 10;
    const raw = [...code, String(sum)];
    return raw.map((s, i) => (i > 0 && s === raw[i - 1] ? REPEAT : s));
  }

  function symbolHz(s) { return s === REPEAT ? F0_HZ + 1200 : F0_HZ + 200 + 100 * Number(s); }

  function tones(code) {
    /* [[Hz, s], ...] : pilote puis symboles. */
    return [[F0_HZ, PILOT_S], ...symbols(code).map((s) => [symbolHz(s), SYMBOL_S])];
  }

  function frameSamples(code, rate) {
    /* Trame en Float32Array : tons à phase continue, rampe en cosinus de 5 ms au début et à la fin de chaque ton. */
    const plan = tones(code);
    const total = plan.reduce((n, [, d]) => n + Math.round(d * rate), 0);
    const out = new Float32Array(total);
    const amp = Math.pow(10, LEVEL_DBFS / 20), rampN = Math.max(1, Math.round(RAMP_S * rate));
    let phase = 0, pos = 0;
    for (const [hz, d] of plan) {
      const n = Math.round(d * rate);
      for (let i = 0; i < n; i++) {
        phase += 2 * Math.PI * hz / rate;
        let env = 1;
        if (i < rampN) env = 0.5 - 0.5 * Math.cos(Math.PI * i / rampN);
        else if (i >= n - rampN) env = 0.5 - 0.5 * Math.cos(Math.PI * (n - 1 - i) / rampN);
        out[pos + i] = amp * env * Math.sin(phase);
      }
      phase %= 2 * Math.PI;
      pos += n;
    }
    return out;
  }

  function testSamples(code, opts) {
    /* Fichier de test : silence, puis la trame `repeat` fois séparées de `gapS`, puis 0,5 s de silence. */
    const o = Object.assign({ rate: 48000, leadS: 2, repeat: 3, gapS: 0.5 }, opts || {});
    const frame = frameSamples(code, o.rate);
    const lead = Math.round(o.leadS * o.rate), gap = Math.round(o.gapS * o.rate), tail = Math.round(0.5 * o.rate);
    const out = new Float32Array(lead + o.repeat * frame.length + (o.repeat - 1) * gap + tail);
    for (let k = 0; k < o.repeat; k++) out.set(frame, lead + k * (frame.length + gap));
    return out;
  }

  function wavBytes(samples, rate) {
    /* WAV mono 16 bits. */
    const n = samples.length, buf = new ArrayBuffer(44 + 2 * n), v = new DataView(buf);
    const text = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    text(0, "RIFF"); v.setUint32(4, 36 + 2 * n, true); text(8, "WAVE"); text(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); text(36, "data"); v.setUint32(40, 2 * n, true);
    for (let i = 0; i < n; i++) v.setInt16(44 + 2 * i, Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767), true);
    return new Uint8Array(buf);
  }

  function testWav(code, opts) {
    const rate = (opts && opts.rate) || 48000;
    return wavBytes(testSamples(code, Object.assign({}, opts, { rate })), rate);
  }

  function indicator(status) {
    /* Indicateur de l'en-tête : null (désactivé), « SEL 4721 » (veille) ou « SEL OUVERT » (appel reçu). */
    if (!status || status.state === "disabled") return null;
    return status.state === "open" ? { text: "SEL OUVERT", open: true } : { text: "SEL " + status.code, open: false };
  }

  const STATE_LABELS = { disabled: "désactivé : son reçu normal", standby: "VEILLE : son coupé jusqu'à l'appel du code",
                         open: "OUVERT : appel reçu, son transmis" };

  const api = { F0_HZ, PILOT_S, SYMBOL_S, validCode, symbols, tones, frameSamples, testSamples, wavBytes, testWav,
                indicator, STATE_LABELS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxSelcall = api; }
})(typeof window !== "undefined" ? window : globalThis);
