// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Égaliseur paramétrique et effets de voix du client (docs/egaliseur-voix.md) : traitement du micro AVANT l'envoi à la
   station, sans rien changer au protocole. Chaîne imposée : coupe-bas, coupe-haut, égaliseur 10 bandes, chorus,
   réverbération, puis LIMITEUR TOUJOURS ACTIF (même éteint). Calculs purs testés sous Node (tests/js/voice_test.js) ;
   la chaîne WebAudio se construit sur un AudioContext fourni (faux contexte dans les tests).

   Sécurité :
   - la station reste maîtresse de l'émission : la piste envoyée n'est ouverte que par client.js en TX confirmé ;
     ici, en plus, la sortie vers la station est à zéro hors émission ;
   - au retour en réception, la traîne de réverbération et le chorus sont coupés net (réverbération recréée) ;
   - l'écoute de contrôle et la relecture ne vont JAMAIS vers la station ; interdites en émission, arrêtées par
     toute prise d'émission ;
   - une erreur dans la chaîne la fait passer en contournement (limiteur seul), jamais en silence. */
(function (root) {
  "use strict";

  const BANDS_HZ = [100, 160, 250, 370, 570, 880, 1350, 2100, 3250, 5000];
  const GAIN_MAX_DB = 12;
  const Q_MIN = 0.3, Q_MAX = 8;
  const LIMIT_DBFS = -3;                    // plafond des crêtes (à vérifier à l'ALC sur charge fictive)
  const CHORUS_TYPES = { classic: { label: "Classique", voices: 1, delayMs: 18 }, ensemble: { label: "Ensemble 3 voix", voices: 3, delayMs: 22 },
                         double: { label: "Doublage", voices: 1, delayMs: 32 } };
  const REVERB_TYPES = { room: { label: "Pièce", seconds: 0.5, bright: 0.5 }, hall: { label: "Salle", seconds: 1.8, bright: 0.35 },
                         plate: { label: "Plaque", seconds: 1.2, bright: 0.8 }, spring: { label: "Ressort", seconds: 0.9, bright: 0.6 } };
  const RECORD_MAX_S = 30;
  const GATE_HOLD_MS = 250, GATE_TICK_MS = 10, GATE_FLOOR = 0.03;     // porte de bruit : maintien, cadence, -30 dB fermée

  function defaults() {
    return {
      version: 1, enabled: false,
      highpassHz: 100, lowpassHz: 3000,
      bands: BANDS_HZ.map((hz, i) => ({ hz: hz, gainDb: 0, q: 1.4, shelf: i === 0 || i === BANDS_HZ.length - 1 })),
      chorus: { on: false, type: "classic", mix: 30, rateHz: 0.8, depthMs: 3 },
      reverb: { on: false, type: "room", mix: 20, seconds: 0.5 },
      // Micro, actif même égaliseur éteint : gain, porte de bruit réglable (coupée par défaut)
      mic: { gainDb: 0, gateOn: false, gateDb: -50 },
    };
  }

  const PRESETS = {
    neutre: { label: "Neutre", make: () => Object.assign(defaults(), { enabled: true }) },
    dx: { label: "DX (aigus présents)", make: () => {
      const s = Object.assign(defaults(), { enabled: true, highpassHz: 250, lowpassHz: 2800 });
      [-6, -4, -2, 0, 0, 1, 3, 5, 4, 0].forEach((g, i) => { s.bands[i].gainDb = g; });
      return s;
    } },
    ragchew: { label: "Ragchew (voix chaude)", make: () => {
      const s = Object.assign(defaults(), { enabled: true, highpassHz: 100, lowpassHz: 3000 });
      [2, 3, 2, 1, 0, 0, 1, 1, 0, -2].forEach((g, i) => { s.bands[i].gainDb = g; });
      return s;
    } },
  };

  const num = (v, lo, hi, dflt) => (typeof v === "number" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : dflt);

  function validate(raw) {
    /* Réglages lus (stockage, fichier importé) -> réglages sûrs, toujours complets ; jamais d'exception. */
    const d = defaults();
    if (!raw || typeof raw !== "object") return d;
    const s = { version: 1, enabled: raw.enabled === true };
    s.highpassHz = num(raw.highpassHz, 20, 1000, d.highpassHz);
    s.lowpassHz = num(raw.lowpassHz, 1500, 8000, d.lowpassHz);
    if (s.lowpassHz <= s.highpassHz + 300) s.lowpassHz = Math.min(8000, s.highpassHz + 300);
    const bands = Array.isArray(raw.bands) ? raw.bands : [];
    s.bands = d.bands.map((b, i) => {
      const r = bands[i] && typeof bands[i] === "object" ? bands[i] : {};
      return { hz: num(r.hz, b.hz / 1.5, b.hz * 1.5, b.hz), gainDb: num(r.gainDb, -GAIN_MAX_DB, GAIN_MAX_DB, 0),
               q: num(r.q, Q_MIN, Q_MAX, b.q), shelf: (i === 0 || i === BANDS_HZ.length - 1) ? r.shelf !== false : false };
    });
    const c = raw.chorus && typeof raw.chorus === "object" ? raw.chorus : {};
    s.chorus = { on: c.on === true, type: CHORUS_TYPES[c.type] ? c.type : d.chorus.type, mix: num(c.mix, 0, 100, d.chorus.mix),
                 rateHz: num(c.rateHz, 0.1, 5, d.chorus.rateHz), depthMs: num(c.depthMs, 0.5, 8, d.chorus.depthMs) };
    const r = raw.reverb && typeof raw.reverb === "object" ? raw.reverb : {};
    s.reverb = { on: r.on === true, type: REVERB_TYPES[r.type] ? r.type : d.reverb.type, mix: num(r.mix, 0, 100, d.reverb.mix),
                 seconds: num(r.seconds, 0.2, 4, d.reverb.seconds) };
    const m = raw.mic && typeof raw.mic === "object" ? raw.mic : {};
    s.mic = { gainDb: num(m.gainDb, -12, 20, 0), gateOn: m.gateOn === true, gateDb: num(m.gateDb, -80, -20, -50) };
    return s;
  }

  function exportJson(settings) {
    /* Format commun page / application (docs/egaliseur-voix.md § 6). */
    return JSON.stringify(Object.assign({ format: "openremotetrx-voice" }, validate(settings)), null, 1);
  }

  function importJson(text) {
    const raw = JSON.parse(text);
    if (!raw || raw.format !== "openremotetrx-voice") throw new Error("ce fichier n'est pas un réglage de voix openRemoteTRX");
    return validate(raw);
  }

  function biquad(type, f0, q, gainDb, fs) {
    /* Coefficients normalisés (a0 = 1) de l'« Audio EQ Cookbook » (R. Bristow-Johnson) : ce que calcule un BiquadFilterNode.
       Sert de référence commune page / application (tests/protocol/voice_vectors.json). */
    const A = Math.pow(10, gainDb / 40);
    const w0 = 2 * Math.PI * f0 / fs, cos = Math.cos(w0), sin = Math.sin(w0);
    const alpha = sin / (2 * q);
    let b0, b1, b2, a0, a1, a2;
    if (type === "peaking") {
      b0 = 1 + alpha * A; b1 = -2 * cos; b2 = 1 - alpha * A; a0 = 1 + alpha / A; a1 = -2 * cos; a2 = 1 - alpha / A;
    } else if (type === "lowshelf" || type === "highshelf") {
      const s = type === "lowshelf" ? 1 : -1, k = 2 * Math.sqrt(A) * alpha;
      b0 = A * ((A + 1) - s * (A - 1) * cos + k); b1 = s * 2 * A * ((A - 1) - s * (A + 1) * cos); b2 = A * ((A + 1) - s * (A - 1) * cos - k);
      a0 = (A + 1) + s * (A - 1) * cos + k; a1 = -s * 2 * ((A - 1) + s * (A + 1) * cos); a2 = (A + 1) + s * (A - 1) * cos - k;
    } else if (type === "highpass") {
      b0 = (1 + cos) / 2; b1 = -(1 + cos); b2 = (1 + cos) / 2; a0 = 1 + alpha; a1 = -2 * cos; a2 = 1 - alpha;
    } else if (type === "lowpass") {
      b0 = (1 - cos) / 2; b1 = 1 - cos; b2 = (1 - cos) / 2; a0 = 1 + alpha; a1 = -2 * cos; a2 = 1 - alpha;
    } else {
      throw new Error("filtre inconnu : " + type);
    }
    return [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0];
  }

  function responseDb(coefs, f, fs) {
    /* Gain (dB) d'un biquad à la fréquence f. */
    const [b0, b1, b2, a1, a2] = coefs, w = 2 * Math.PI * f / fs;
    const re = (c0, c1, c2) => c0 + c1 * Math.cos(w) + c2 * Math.cos(2 * w);
    const im = (c1, c2) => -(c1 * Math.sin(w) + c2 * Math.sin(2 * w));
    const nr = re(b0, b1, b2), ni = im(b1, b2), dr = re(1, a1, a2), di = im(a1, a2);
    return 10 * Math.log10((nr * nr + ni * ni) / (dr * dr + di * di));
  }

  function bandType(band) {
    if (!band.shelf) return "peaking";
    return band.hz <= BANDS_HZ[0] * 1.5 ? "lowshelf" : "highshelf";
  }

  function impulse(type, seconds, rate, random) {
    /* Réponse impulsionnelle générée (rien à télécharger) : bruit à décroissance exponentielle, deux canaux décorrélés ;
       « plaque » plus brillante, « ressort » avec un battement. */
    const t = REVERB_TYPES[type] || REVERB_TYPES.room;
    const rnd = random || Math.random;
    const n = Math.max(1, Math.round(seconds * rate));
    const channels = [new Float32Array(n), new Float32Array(n)];
    for (const data of channels) {
      let lp = 0;
      for (let i = 0; i < n; i++) {
        const env = Math.pow(1 - i / n, 2) * Math.exp(-6.9 * i / n);
        let x = rnd() * 2 - 1;
        lp += (x - lp) * t.bright;                                           // plus ou moins d'aigus
        x = lp;
        if (type === "spring") x *= 0.7 + 0.3 * Math.cos(2 * Math.PI * 9 * i / rate);
        data[i] = x * env;
      }
    }
    return channels;
  }

  function limiterCurve(points) {
    /* Écrêtage doux au plafond (filet de sécurité après le compresseur-limiteur). */
    const ceil = Math.pow(10, LIMIT_DBFS / 20), curve = new Float32Array(points);
    for (let i = 0; i < points; i++) {
      const x = (i / (points - 1)) * 2 - 1;
      curve[i] = ceil * Math.tanh(x / ceil);
    }
    return curve;
  }

  // ------------------------------------------------------------------ chaîne WebAudio

  class VoiceChain {
    /* ctx : AudioContext ; source : nœud du micro. `track` : piste à envoyer à la station (sortie de la chaîne). */
    constructor(ctx, source, settings, log, timers) {
      this.ctx = ctx;
      this.log = log || (() => {});
      // Fonctions du navigateur enveloppées : appelées détachées de window, elles lèvent « Illegal invocation »
      this.timers = timers || (typeof setInterval === "function"
        ? { setInterval: (f, ms) => setInterval(f, ms), clearInterval: (id) => clearInterval(id) } : null);
      this.settings = validate(settings);
      this.tx = false; this.monitoring = false; this.playing = null;
      this.failed = false;
      // Micro : gain, mesure du niveau (jamais envoyée), porte de bruit réglable
      this.pre = ctx.createGain();
      this.tap = ctx.createAnalyser(); this.tap.fftSize = 1024;
      this.gate = ctx.createGain();
      source.connect(this.pre); this.pre.connect(this.tap); this.pre.connect(this.gate);
      this._tapBuf = new Float32Array(this.tap.fftSize);
      this._gateOpenUntil = 0; this._gateTimer = null;
      this.input = ctx.createGain();                        // porte d'entrée : ouverte en émission et pendant l'écoute de contrôle
      this.input.gain.value = 0;
      this.gate.connect(this.input);
      this.playIn = ctx.createGain();                       // relecture d'un enregistrement (jamais vers la station)
      this.limiter = ctx.createDynamicsCompressor();
      this.limiter.threshold.value = LIMIT_DBFS - 3; this.limiter.knee.value = 0; this.limiter.ratio.value = 20;
      this.limiter.attack.value = 0.002; this.limiter.release.value = 0.08;
      this.clip = ctx.createWaveShaper();
      this.clip.curve = limiterCurve(1025);
      this.limiter.connect(this.clip);
      this.toStation = ctx.createGain(); this.toStation.gain.value = 0;      // à zéro hors émission
      this.dest = ctx.createMediaStreamDestination();
      this.clip.connect(this.toStation); this.toStation.connect(this.dest);
      this.monitor = ctx.createGain(); this.monitor.gain.value = 0;          // écoute de contrôle (casque)
      this.clip.connect(this.monitor); this.monitor.connect(ctx.destination);
      this.bypass = ctx.createGain();
      this.input.connect(this.bypass); this.playIn.connect(this.bypass);
      this.bypass.connect(this.limiter);
      this.processed = ctx.createGain();
      this.processed.connect(this.limiter);
      try {
        this._build();
      } catch (e) {
        this._fail(e);
      }
      this.apply(this.settings);
      this.stream = this.dest.stream;
      this.track = this.dest.stream.getAudioTracks()[0];
    }

    _build() {
      const ctx = this.ctx;
      this.head = ctx.createGain();
      this.input.connect(this.head); this.playIn.connect(this.head);
      this.hp = ctx.createBiquadFilter(); this.hp.type = "highpass";
      this.lp = ctx.createBiquadFilter(); this.lp.type = "lowpass";
      this.head.connect(this.hp); this.hp.connect(this.lp);
      let last = this.lp;
      this.eq = BANDS_HZ.map(() => { const f = ctx.createBiquadFilter(); last.connect(f); last = f; return f; });
      // chorus : sec + voix retardées modulées par des oscillateurs lents
      this.chorusDry = ctx.createGain(); this.chorusWet = ctx.createGain(); this.chorusSum = ctx.createGain();
      last.connect(this.chorusDry); this.chorusDry.connect(this.chorusSum); this.chorusWet.connect(this.chorusSum);
      this.voices = [0, 1, 2].map((i) => {
        const delay = ctx.createDelay(0.1), lfo = ctx.createOscillator(), depth = ctx.createGain(), level = ctx.createGain();
        lfo.connect(depth); depth.connect(delay.delayTime);
        last.connect(delay); delay.connect(level); level.connect(this.chorusWet);
        lfo.start();
        return { delay, lfo, depth, level, phase: i };
      });
      // réverbération : sec + convolution
      this.revDry = ctx.createGain(); this.revWet = ctx.createGain();
      this.chorusSum.connect(this.revDry); this.revDry.connect(this.processed);
      this.revWet.connect(this.processed);
      this._newConvolver();
    }

    _newConvolver() {
      /* Réverbération recréée : sa traîne disparaît (retour en réception, changement de type). */
      if (this.convolver) { try { this.chorusSum.disconnect(this.convolver); this.convolver.disconnect(); } catch (e) { /* déjà débranché */ } }
      const r = this.settings.reverb, rate = this.ctx.sampleRate || 48000;
      const data = impulse(r.type, r.seconds, rate);
      const buffer = this.ctx.createBuffer(2, data[0].length, rate);
      buffer.getChannelData(0).set(data[0]); buffer.getChannelData(1).set(data[1]);
      this.convolver = this.ctx.createConvolver();
      this.convolver.buffer = buffer;
      this.chorusSum.connect(this.convolver); this.convolver.connect(this.revWet);
      this._irKey = r.type + "/" + r.seconds;
    }

    _fail(err) {
      this.failed = true;
      this.log("Égaliseur en erreur (" + (err && err.message ? err.message : err) + ") : voix envoyée sans traitement (limiteur seul).", "warn");
      this.bypass.gain.value = 1; this.processed.gain.value = 0;
    }

    micLevelDb() {
      /* Niveau efficace du micro (dBFS) après le gain : pour régler gain et seuil de la porte. */
      this.tap.getFloatTimeDomainData(this._tapBuf);
      let sum = 0;
      for (const x of this._tapBuf) sum += x * x;
      const rms = Math.sqrt(sum / this._tapBuf.length);
      return rms > 1e-6 ? 20 * Math.log10(rms) : -120;
    }

    _gateTick(nowMs) {
      /* Porte de bruit : ouverte au-dessus du seuil, maintenue 250 ms, sinon atténuée de 30 dB (jamais muette). */
      const m = this.settings.mic;
      let target = 1;
      if (m.gateOn) {
        if (this.micLevelDb() >= m.gateDb) this._gateOpenUntil = nowMs + GATE_HOLD_MS;
        target = nowMs < this._gateOpenUntil ? 1 : GATE_FLOOR;
      }
      const g = this.gate.gain;
      if (g.setTargetAtTime) g.setTargetAtTime(target, this.ctx.currentTime || 0, target === 1 ? 0.003 : 0.05);
      else g.value = target;
      return target;
    }

    _syncGateTimer() {
      const want = this.settings.mic.gateOn && this.timers;
      if (want && this._gateTimer === null) {
        this._gateTimer = this.timers.setInterval(() => this._gateTick(Date.now()), GATE_TICK_MS);
      } else if (!want && this._gateTimer !== null) {
        this.timers.clearInterval(this._gateTimer);
        this._gateTimer = null;
      }
      if (!this.settings.mic.gateOn) {
        if (this.gate.gain.cancelScheduledValues) this.gate.gain.cancelScheduledValues(0);
        this.gate.gain.value = 1;
      }
    }

    apply(settings) {
      /* Réglages appliqués tout de suite (curseurs) ; éteint ou en erreur : contournement, limiteur seul. */
      this.settings = validate(settings);
      const s = this.settings;
      this.pre.gain.value = Math.pow(10, s.mic.gainDb / 20);
      this._syncGateTimer();
      const on = s.enabled && !this.failed;
      this.bypass.gain.value = on ? 0 : 1;
      this.processed.gain.value = on ? 1 : 0;
      if (this.failed) return;
      try {
        this.hp.frequency.value = s.highpassHz; this.hp.Q.value = 0.707;
        this.lp.frequency.value = s.lowpassHz; this.lp.Q.value = 0.707;
        s.bands.forEach((b, i) => {
          const f = this.eq[i];
          f.type = bandType(b); f.frequency.value = b.hz; f.Q.value = b.q; f.gain.value = b.gainDb;
        });
        const c = s.chorus, ct = CHORUS_TYPES[c.type], wet = c.on ? c.mix / 100 : 0;
        this.chorusDry.gain.value = 1 - wet / 2; this.chorusWet.gain.value = wet;
        this.voices.forEach((v, i) => {
          const used = i < ct.voices;
          v.level.gain.value = used ? 1 / ct.voices : 0;
          v.delay.delayTime.value = (ct.delayMs + i * 7) / 1000;
          v.lfo.frequency.value = c.rateHz * (1 + i * 0.27);
          v.depth.gain.value = used ? c.depthMs / 1000 : 0;
        });
        const r = s.reverb, rwet = r.on ? r.mix / 100 : 0;
        this.revDry.gain.value = 1 - rwet / 2; this.revWet.gain.value = rwet;
        if (this._irKey !== r.type + "/" + r.seconds) this._newConvolver();
      } catch (e) {
        this._fail(e);
      }
    }

    setTx(on) {
      /* Émission confirmée (client.js) ou non. Prise : écoute et relecture arrêtées. Fin : traîne coupée net. */
      on = !!on;
      if (on === this.tx) return;
      this.tx = on;
      if (on) { this.setMonitor(false); this.stopPlayback(); }
      this.input.gain.value = on || this.monitoring ? 1 : 0;
      this.toStation.gain.value = on ? 1 : 0;
      if (!on && !this.failed) { try { this._newConvolver(); } catch (e) { this._fail(e); } }
    }

    setMonitor(on) {
      /* Écoute de contrôle au casque : jamais pendant l'émission. */
      on = !!on && !this.tx;
      this.monitoring = on;
      this.monitor.gain.value = on || this.playing ? 1 : 0;
      this.input.gain.value = this.tx || on ? 1 : 0;
      return on;
    }

    playBuffer(buffer) {
      /* Relecture d'un enregistrement à travers la chaîne, vers le casque seulement ; refusée en émission. */
      if (this.tx || !buffer) return false;
      this.stopPlayback();
      const src = this.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.playIn);
      this.playing = src;
      this.monitor.gain.value = 1;
      src.onended = () => { if (this.playing === src) { this.playing = null; this.monitor.gain.value = this.monitoring ? 1 : 0; } };
      src.start();
      return true;
    }

    stopPlayback() {
      if (!this.playing) return;
      const src = this.playing;
      this.playing = null;
      try { src.stop(); src.disconnect(); } catch (e) { /* déjà arrêtée */ }
      this.monitor.gain.value = this.monitoring ? 1 : 0;
    }

    close() {
      this.stopPlayback();
      this.toStation.gain.value = 0; this.monitor.gain.value = 0; this.input.gain.value = 0;
      for (const v of this.voices || []) { try { v.lfo.stop(); } catch (e) { /* déjà arrêté */ } }
      if (this._gateTimer !== null && this.timers) { this.timers.clearInterval(this._gateTimer); this._gateTimer = null; }
      try { this.input.disconnect(); } catch (e) { /* déjà débranché */ }
    }
  }

  const api = { GATE_FLOOR, BANDS_HZ, GAIN_MAX_DB, LIMIT_DBFS, CHORUS_TYPES, REVERB_TYPES, PRESETS, RECORD_MAX_S, defaults, validate, exportJson,
                importJson, biquad, responseDb, bandType, impulse, limiterCurve, VoiceChain };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxVoice = api; }
})(typeof window !== "undefined" ? window : globalThis);
