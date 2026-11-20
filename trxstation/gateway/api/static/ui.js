// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Affichage : relie TrxClient (client.js, logique testée sous Node) à la page. Aucune logique de protocole ici. */
(function (root) {
  "use strict";  // i18n-ok
  const web = root.TrxWeb;
  if (typeof document === "undefined" || !web) return;
  const { TrxClient, modeLabel, shortMode, matchesRigDevice, parseKilohertz, chooseLayout, formatIcomFrequency, frequencyDigits, parseFrequencyEntry,
          BANDS, STEPS_HZ, describeLoss, lossSummary, LINK_ALERTS, alertVolume, alertDurationMs, orderModes, versionLabel } = web;
  const wf = root.TrxWaterfall;
  if (!wf) return;
  const hfx = root.TrxHfScope || null;              // spectre HF du poste (hfscope.js) ; sans lui, la zone ne propose que puissance et audio
  const sp = root.TrxSpots || null;                 // spots du Cluster DX sur le spectre HF (spots.js) ; sans lui, pas de marqueurs
  const lay = root.TrxLayout || null;                // mises en page personnalisées (layout.js) ; sans lui, la page reste celle d'usine

  const $ = (id) => document.getElementById(id);
  const store = {
    get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* stockage indisponible : réglage non mémorisé */ } },
  };
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const CONTROLS = [["NR", "ctl-nr"], ["NB", "ctl-nb"], ["PREAMP", "ctl-preamp"], ["ATT", "ctl-att"], ["AIP", "ctl-aip"],
                    ["NOTCH", "ctl-notch"], ["AGC", "ctl-agc"], ["COMP", "ctl-comp"], ["FIL", "ctl-fil"], ["TUNER", "ctl-tuner"],
                    ["PWR", "ctl-pwr"]];
  const DIALOG_KEYS = ["NR", "NB", "NOTCH"];          // appui long (téléphone) ou double clic (PC) : fenêtre de réglage
  // un appui sur NR/NB/NOTCH attend ce délai : un second appui = double clic
  const DOUBLE_CLICK_MS = 260;
  const percentLeft = (fraction) => (100 - Math.round(fraction * 100)) + "%";                    // largeur du masque : la partie VIDE de la barre

  function browserEnv() {
    return {
      RTCPeerConnection: window.RTCPeerConnection,
      isSecureContext: window.isSecureContext,
      requestWakeLock: window.isSecureContext && navigator.wakeLock && navigator.wakeLock.request
        ? () => navigator.wakeLock.request("screen") : null,
      getUserMedia: navigator.mediaDevices && navigator.mediaDevices.getUserMedia
        ? (c) => navigator.mediaDevices.getUserMedia(c) : null,
      now: () => performance.now(),
      storage: {
        get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
        set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* stockage indisponible */ } },
      },
      epoch: () => Date.now(),
      // sonde réseau : appareil tiré au hasard, nom affiché à l'opérateur, type de réseau quand le navigateur le dit
      randomBytes: (n) => crypto.getRandomValues(new Uint8Array(n)),
      agent: "page " + (/Android/i.test(navigator.userAgent) ? "Android" : /iPhone|iPad/i.test(navigator.userAgent) ? "iOS"  // i18n-ok (envoyé à la station)
        : /Windows/i.test(navigator.userAgent) ? "Windows" : /Mac/i.test(navigator.userAgent) ? "Mac"  // i18n-ok
        : /Linux/i.test(navigator.userAgent) ? "Linux" : "navigateur"),  // i18n-ok
      netType: () => {
        const c = navigator.connection;
        return c && typeof c.type === "string" ? ({ wifi: "wifi", cellular: "mobile", ethernet: "lan" }[c.type] || null) : null;
      },
      isOnline: () => (typeof navigator.onLine === "boolean" ? navigator.onLine : null),
      isVisible: () => !document.hidden,
      setInterval: (f, ms) => window.setInterval(f, ms), clearInterval: (id) => window.clearInterval(id),
      setTimeout: (f, ms) => window.setTimeout(f, ms), clearTimeout: (id) => window.clearTimeout(id),
      waitIceComplete: (pc, ms) => new Promise((resolve) => {
        if (pc.iceGatheringState === "complete") { resolve(); return; }
        const done = () => { pc.removeEventListener("icegatheringstatechange", check); window.clearTimeout(timer); resolve(); };
        const check = () => { if (pc.iceGatheringState === "complete") done(); };
        const timer = window.setTimeout(done, ms);
        pc.addEventListener("icegatheringstatechange", check);
      }),
      getConfig: async () => {
        const response = await fetch("config", { cache: "no-store" });
        if (!response.ok) throw new Error("config " + response.status);
        return response.json();
      },
      postOffer: async (body) => {
        const response = await fetch("offer", { method: "POST", cache: "no-store",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        let parsed = null;
        try { parsed = await response.json(); } catch (e) { /* corps vide */ }
        return { status: response.status, body: parsed };
      },
      collectStats: async (pc) => {
        const stats = await pc.getStats();
        let jitter = null, lost = null, received = null, rtt = null, rxLevel = null, micLevel = null, sent = null, conceal = null;
        stats.forEach((r) => {
          if (r.type === "inbound-rtp" && r.kind === "audio") {
            jitter = r.jitter; lost = r.packetsLost; received = r.packetsReceived;
            if (typeof r.audioLevel === "number") rxLevel = r.audioLevel;
            if (typeof r.concealedSamples === "number" && typeof r.totalSamplesReceived === "number") {
              conceal = { concealed: r.concealedSamples, total: r.totalSamplesReceived };   // sonde réseau : trous audibles
            }
          }
          if (r.type === "outbound-rtp" && r.kind === "audio") sent = r.packetsSent;
          if (r.type === "media-source" && r.kind === "audio" && typeof r.audioLevel === "number") micLevel = r.audioLevel;
          if (r.type === "candidate-pair" && r.nominated && r.state === "succeeded") rtt = r.currentRoundTripTime;
        });
        const net = [];
        if (rtt !== null) net.push(I18N.t("ui.stats_rtt", { ms: Math.round(rtt * 1000) }));
        if (jitter !== null) net.push(I18N.t("ui.stats_jitter", { ms: Math.round(jitter * 1000) }));
        if (lost !== null && received !== null) net.push(I18N.t("ui.stats_lost", { lost: lost, total: received + lost }));
        const pct = (v) => Math.round(v * 100) + " %";
        const diag = [];
        if (received !== null) diag.push(rxLevel !== null ? I18N.t("ui.stats_rx_level", { packets: received, level: pct(rxLevel) })
          : I18N.t("ui.stats_rx", { packets: received }));
        if (sent !== null) diag.push(micLevel !== null ? I18N.t("ui.stats_mic_level", { packets: sent, level: pct(micLevel) })
          : I18N.t("ui.stats_mic", { packets: sent }));
        return { net: net.join(" · "), diag: diag.join(" · "), conceal: conceal };
      },
      health: async () => {                                  // sonde réseau : second chemin (HTTPS, hors WebRTC)
        try {
          const response = await fetch("health", { cache: "no-store", signal: AbortSignal.timeout(3000) });
          return response.ok;
        } catch (e) { return false; }
      },
    };
  }

  function initUi() {
    if (I18N) I18N.apply(document);                      // textes d'index.html dans la langue choisie (lot T4)
    const audio = $("rx-audio");
    const logList = $("log");
    let rttText = "", statsText = "", rigAudio = [];
    let lastView = null, editingId = null, connectedFlag = false;
    let squelchTouched = -1e9, squelchTimer = null, deleteArmed = false, deleteTimer = null;
    const rows = new Map();                         // identifiant de mémoire -> { li, memory }
    let instrumentKeys = null, instrumentEls = new Map();
    const fail = (e) => ui.log(e && e.message ? e.message : String(e), "bad");
    const safeJson = (text) => { try { return JSON.parse(text); } catch (e) { return null; } };
    let rxMedia = null;                                                            // flux reçu (débrouillage du scrambler)
    // son du SDR (station 0.142.0+) : son propre élément, sur la MÊME sortie que le son reçu, coupé avec lui
    const sdrSound = typeof Audio === "function" ? new Audio() : null;
    function sdrMirrorOutput() { if (sdrSound) sdrSound.muted = audio.muted; }
    function audioContext48(Ctx) { try { return new Ctx({ sampleRate: 48000 }); } catch (e) { return new Ctx(); } }
    let freqEls = [], drag = null, kpText = "";
    const bandButtons = new Map();
    const modeButtons = new Map();                                                    // mode Hamlib -> bouton (onglet Accord)
    const bandDots = new Map();                                                       // bande -> pastille des spots actifs
    let releaseArmed = false, releaseTimer = null;                                    // « Reprendre la main » : second appui pour confirmer
    function resetRelease() {
      releaseArmed = false;
      if (releaseTimer !== null) { window.clearTimeout(releaseTimer); releaseTimer = null; }
      $("local-release").textContent = I18N.t("rigparts.release_local");
    }
    let wfSettings = wf.normalizeSettings(safeJson(store.get("trx.wf", "null")));
    let wfVisible = false, audioCtx = null, analyser = null, wfSource = null, spectrumBuf = null, wfValues = null;
    let wfRaf = null, lastLine = 0, lastFrame = 0, lastToggle = -1e9;
    const tracker = new wf.PeakTracker();
    const WF_W = 480, SPEC_H = 40, FALL_H = 80, STEP_PX = 22;
    const specCanvas = $("wf-spec"), fallCanvas = $("wf-fall"), gridCanvas = $("wf-grid");
    specCanvas.width = WF_W; specCanvas.height = SPEC_H; fallCanvas.width = WF_W; fallCanvas.height = FALL_H;
    gridCanvas.width = WF_W; gridCanvas.height = SPEC_H + FALL_H;
    const specCtx = specCanvas.getContext("2d"), fallCtx = fallCanvas.getContext("2d"), gridCtx = gridCanvas.getContext("2d");
    let rowImage = null;
    let hfVfo = false, hfDrag = null;                // accord au doigt (bouton VFO), éteint à chaque ouverture
    let hfVisible = false, hfLast = null, hfRow = null, hfFreqHz = null, hfFull = false, hfFloor = null, hfLine = 2, hfValues = null;
    let hfDocked = false;                                                              // vue HF intégrée (colonne de droite) plutôt que plein écran
    let hfDockWanted = store.get("trx.hfdock", "0") === "1";                           // interrupteur « Waterfall HF permanent », mémorisé par appareil
    const hfHome = $("hfscope").parentNode || null;                                    // emplacement d'origine de la vue (plein écran)
    let audioDocked = false;                                                           // spectre audio permanent (paysage large)
    let audioDockWanted = store.get("trx.audiodock", "1") !== "0";                     // allumé par défaut, mémorisé par appareil
    const wfHome = $("waterfall").parentNode || null, wfNext = $("waterfall").nextSibling || null;
    let hfSettings = hfx ? hfx.normalizeSettings(safeJson(store.get("trx.hf", "null"))) : { gain: 0, range: 40 };
    const hfSpec = $("hf-spec"), hfFall = $("hf-fall"), hfGrid = $("hf-grid");
    const spotBook = sp ? new sp.SpotBook() : null;
    let spotsOn = store.get("trx.spots", "1") !== "0", spotTimer = null, spotCardId = null, spotListIds = null, spotSort = "freq";
    const hfSpecCtx = hfSpec.getContext("2d"), hfFallCtx = hfFall.getContext("2d"), hfGridCtx = hfGrid.getContext("2d");
    const miniFall = $("mini-fall"), miniCtx = miniFall.getContext("2d");
    let hfSOffset = null;                             // recalage des niveaux du poste sur le S-mètre (couleurs chaudes)
    let miniFloor = null, miniLast = null, miniRow = null, miniValues = null, miniWasActive = false;
    let layout = null, profile = null, profileSource = "factory", profileVersion = 0, planKey = "";

    // ---- affichage : taille du texte et disposition (portrait par défaut, paysage proposé)
    function applyDisplay() {
      const text = store.get("trx.text", "auto");
      if (text === "auto") document.documentElement.removeAttribute("data-text");
      else document.documentElement.setAttribute("data-text", text);
      const landscape = window.matchMedia ? window.matchMedia("(orientation: landscape)").matches : window.innerWidth > window.innerHeight;  // i18n-ok
      $("app").className = chooseLayout(store.get("trx.layout", "auto"), landscape, window.innerWidth);
      renderLayout(false);
      syncDock();                                                                    // paysage étroit ou portrait : le spectre intégré se retire
    }

    // ---- mise en page personnalisée : profil du compte, servi par la station (layout_get)
    function currentDevice() {
      const coarse = window.matchMedia ? window.matchMedia("(pointer: coarse)").matches : false;  // i18n-ok
      return lay.detectDevice(window.innerWidth, window.innerHeight, coarse);
    }
    function currentOrientation() {
      const chosen = store.get("trx.layout", "auto");
      if (chosen === "portrait" || chosen === "landscape") return chosen;
      const landscape = window.matchMedia ? window.matchMedia("(orientation: landscape)").matches : window.innerWidth > window.innerHeight;  // i18n-ok
      return landscape ? "landscape" : "portrait";
    }
    function layoutInfo(plan) {
      const labels = { phone: "ui.device_phone", tablet: "ui.device_tablet", desktop: "ui.device_desktop" };
      let text = I18N.t("ui.layout_factory");
      if (profile && profileSource === "user") {
        text = I18N.t("ui.layout_profile", { name: profile.name });
        if (plan && plan.safe) {
          const fields = { name: profile.name, device: labels[plan.choice.device] ? I18N.t(labels[plan.choice.device]) : String(labels[plan.choice.device]),
            orientation: plan.choice.orientation === "portrait" ? I18N.t("ui.orientation_portrait") : I18N.t("ui.orientation_landscape") };
          text = plan.choice.display === "centered" ? I18N.t("ui.layout_variant_centered", fields) : I18N.t("ui.layout_variant", fields);
        } else if (plan) text = I18N.t("ui.layout_safe", { name: profile.name, reason: lay.safeText(plan) });
      }
      $("layout-info").textContent = text;
      $("layout-factory").disabled = !(connectedFlag && profile && profileSource === "user");
    }
    function renderLayout(force) {
      if (!layout) return;
      if (!profile || profileSource !== "user") {                                     // profil d'usine : la page telle qu'elle est écrite  // i18n-ok
        if (layout.active) layout.restore();
        planKey = ""; layoutInfo(null);
        return;
      }
      const forced = store.get("trx.device", "auto");
      const plan = lay.buildPlan(profile, currentDevice(), currentOrientation(), forced === "auto" ? null : forced);
      const key = JSON.stringify([profileVersion, plan.choice, plan.safe, plan.reason]);
      if (!force && key === planKey) return;                                          // rien n'a changé (redimensionnement mineur)
      planKey = key;
      layout.apply(plan);
      layoutInfo(plan);
      if (plan.unsupported.length) ui.log(I18N.t("ui.layout_unsupported", { widgets: plan.unsupported.join(", ") }), "warn");
    }
    async function loadLayout() {
      try {
        const res = await client.getLayout();
        if (!res || !res.ok || !res.profile) return;
        profile = res.profile; profileSource = res.source === "user" ? "user" : "factory"; profileVersion += 1;
        if (Array.isArray(res.warnings) && res.warnings.length) ui.log(I18N.t("ui.layout_hidden", { n: res.warnings.length }), "");
        renderLayout(true);
      } catch (err) { ui.log(I18N.t("ui.layout_not_loaded", { error: err && err.message ? err.message : err }), "warn"); }
    }

    // ---- périphériques audio du navigateur
    const deviceLabel = (kind, id) => {
      const select = $(kind === "audioinput" ? "mic-select" : "out-select");
      const option = Array.from(select.options).find((o) => o.value === id);
      return option ? option.textContent : "";
    };
    const fillDevices = (select, devices, saved) => {
      select.textContent = "";
      select.appendChild(Object.assign(el("option", "", I18N.t("ui.device_default")), { value: "" }));
      for (const d of devices) {
        select.appendChild(Object.assign(el("option", "", d.label || I18N.t("ui.device_hidden_name")), { value: d.deviceId }));
      }
      select.value = Array.from(select.options).some((o) => o.value === saved) ? saved : "";
    };
    async function refreshDevices() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        fillDevices($("mic-select"), devices.filter((d) => d.kind === "audioinput"), store.get("trx.mic", ""));
        fillDevices($("out-select"), devices.filter((d) => d.kind === "audiooutput"), store.get("trx.out", ""));
      } catch (err) { /* liste indisponible : le périphérique par défaut sera utilisé */ }
    }
    async function applyOutput() {
      const id = $("out-select").value;
      if (audio.setSinkId) { try { await audio.setSinkId(id); } catch (err) { ui.log(I18N.t("ui.output_not_applied", { error: err.message }), "warn"); } }
      if (sdrSound && sdrSound.setSinkId) { try { await sdrSound.setSinkId(id); } catch (err) { /* sortie par défaut */ } }
      if (audioCtx && audioCtx.setSinkId) { try { await audioCtx.setSinkId(id); } catch (err) { /* les alertes restent sur la sortie par défaut */ } }
      const label = id ? deviceLabel("audiooutput", id)
        : (Array.from($("out-select").options).slice(1).map((o) => o.textContent).find((t) => /^(par défaut|default)/i.test(t)) || "");
      outputIsRig = !$("ignore-rig-warning").checked && matchesRigDevice(label, rigAudio);
      if (outputIsRig) {
        audio.muted = true;
        ui.log(I18N.t("ui.output_is_rig", { device: label }), "bad");
      } else { audio.muted = $("mute").checked; }
      sdrMirrorOutput();                                                             // le son du SDR suit (jamais vers le poste)
    }
    if (!audio.setSinkId) $("out-label").hidden = true;

    // ---- sons d'alerte de la liaison : produits ici (Web Audio, aucun fichier), sur la même sortie que le son reçu
    let outputIsRig = false, alertLevel = store.get("trx.alerts", "normal");
    function alertContext() {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) return null;
      try { if (!audioCtx) { audioCtx = new Context(); applyOutput(); } } catch (e) { return null; }
      if (audioCtx.state === "suspended" && audioCtx.resume) audioCtx.resume().catch(() => {});
      return audioCtx;
    }
    function playLinkAlert(kind) {
      const alert = LINK_ALERTS[kind], gain = alertVolume(alertLevel);
      if (!alert || gain === 0) return;
      if (navigator.vibrate) { try { navigator.vibrate(alert.vibrate); } catch (e) { /* vibreur indisponible */ } }
      if (outputIsRig) return;                                                        // JAMAIS de son injecté dans l'émetteur
      const ctx = alertContext();
      if (!ctx || !ctx.createOscillator) return;
      let t = ctx.currentTime + 0.02;
      for (const [hz, ms, gap] of alert.notes) {
        const osc = ctx.createOscillator(), env = ctx.createGain(), end = t + ms / 1000;
        osc.type = "sine"; osc.frequency.value = hz;
        env.gain.setValueAtTime(0, t);                                                // montée et descente douces : pas de claquement
        env.gain.linearRampToValueAtTime(gain, t + 0.015);
        env.gain.setValueAtTime(gain, end - 0.03);
        env.gain.linearRampToValueAtTime(0, end);
        osc.connect(env); env.connect(ctx.destination);
        osc.start(t); osc.stop(end + 0.02);
        t = end + gap / 1000;
      }
    }
    // Langue de la page (lot T5) : choisie HORS connexion (la page se recharge dans la nouvelle langue)
    const LANG_NAMES = { fr: "Français", en: "English", de: "Deutsch", es: "Español" };   // i18n-ok : noms des langues
    function langControl() {
      const offered = I18N ? I18N.OFFERED : [];
      $("lang-label").hidden = offered.length < 2;
      $("lang-select").disabled = connectedFlag;
      $("lang-hint").hidden = offered.length < 2 || !connectedFlag;
    }
    if (I18N && I18N.OFFERED.length > 1) {
      const sel = $("lang-select");
      for (const code of [""].concat(I18N.OFFERED)) {
        const o = document.createElement("option");
        o.value = code;
        o.textContent = code ? LANG_NAMES[code] || code : I18N.t("index.lang_auto");
        sel.appendChild(o);
      }
      sel.value = I18N.stored() || "";
      sel.addEventListener("change", () => {
        if (connectedFlag) { sel.value = I18N.stored() || ""; return; }
        I18N.choose(sel.value || null);
        root.location.reload();
      });
    }
    langControl();
    $("alert-select").value = ["off", "low", "normal", "high"].includes(alertLevel) ? alertLevel : "normal";
    $("alert-select").addEventListener("change", (ev) => { alertLevel = ev.target.value; store.set("trx.alerts", alertLevel); });
    $("alert-test").addEventListener("click", () => {                                 // les trois sons à la suite, pour les reconnaître
      let delay = 0;
      for (const [kind, text] of [["lost", "ui.alert_lost"], ["restored", "ui.alert_restored"], ["failed", "ui.alert_failed"]]) {
        window.setTimeout(() => { ui.log(I18N.t("ui.alert_sound", { name: I18N.t(text) }), ""); playLinkAlert(kind); }, delay);
        delay += alertDurationMs(kind) + 900;
      }
    });
    // ---- bips de fin d'émission (réglage de la STATION ; l'écoute ici n'émet rien)
    const TONE_LABELS = { duo: "beeps.tone_duo" };                                   // clés des textes
    let beepSettings = null;
    function playSequence(seq) {
      /* Segments [Hz, ms] (0 Hz = silence), sur le haut-parleur du téléphone ; jamais sur la sortie du poste. */
      if (outputIsRig || !Array.isArray(seq)) return;
      const ctx = alertContext();
      if (!ctx || !ctx.createOscillator) return;
      let t = ctx.currentTime + 0.02;
      for (const [hz, ms] of seq) {
        const end = t + ms / 1000;
        if (hz > 0) {
          const osc = ctx.createOscillator(), env = ctx.createGain();
          osc.type = "sine"; osc.frequency.value = hz;
          env.gain.setValueAtTime(0, t); env.gain.linearRampToValueAtTime(0.35, t + 0.005);
          env.gain.setValueAtTime(0.35, Math.max(t + 0.005, end - 0.005)); env.gain.linearRampToValueAtTime(0, end);
          osc.connect(env); env.connect(ctx.destination);
          osc.start(t); osc.stop(end + 0.02);
        }
        t = end;
      }
    }
    function renderBeeps(settings) {
      beepSettings = settings;
      const ok = !!settings && connectedFlag;
      for (const id of ["roger-on", "roger-tone", "roger-pattern", "roger-preview", "lost-on", "lost-preview"]) $(id).disabled = !ok;
      if (!settings) {
        $("beeps-note").textContent = connectedFlag ? I18N.t("clusterandbeeps.no_beeps") : "";
        return;
      }
      const tone = $("roger-tone"), pattern = $("roger-pattern");
      if (tone.options.length !== (settings.tones || []).length) {
        tone.textContent = "";
        for (const t of settings.tones || []) tone.appendChild(Object.assign(el("option", "", TONE_LABELS[t] ? I18N.t(TONE_LABELS[t]) : t + " Hz"), { value: t }));
      }
      if (pattern.options.length !== (settings.patterns || []).length) {
        pattern.textContent = "";
        for (const n of settings.patterns || []) pattern.appendChild(Object.assign(el("option", "", I18N.plural("beeps.pattern", n)), { value: String(n) }));
      }
      $("roger-on").checked = !!settings.roger_enabled; $("lost-on").checked = !!settings.link_lost_enabled;
      tone.value = settings.roger_tone; pattern.value = String(settings.roger_pattern);
      $("beeps-note").textContent = settings.link_lost_enabled
        ? I18N.t("clusterandbeeps.link_lost_active")
        : "";
    }
    function setBeeps(changes) { client.setBeeps(changes).catch(fail).finally(() => renderBeeps(client.beeps || beepSettings)); }
    $("roger-on").addEventListener("change", (ev) => setBeeps({ roger_enabled: !!ev.target.checked }));
    $("roger-tone").addEventListener("change", (ev) => setBeeps({ roger_tone: ev.target.value }));
    $("roger-pattern").addEventListener("change", (ev) => setBeeps({ roger_pattern: Number(ev.target.value) }));
    $("lost-on").addEventListener("change", (ev) => {
      const on = !!ev.target.checked;
      const ask = typeof window.confirm === "function" ? window.confirm : () => true;
      if (on && !ask(I18N.t("clusterandbeeps.link_lost_confirm"))) { ev.target.checked = false; return; }
      setBeeps({ link_lost_enabled: on });
    });
    $("roger-preview").addEventListener("click", () => { if (beepSettings) playSequence(beepSettings.roger_sequence); });
    $("lost-preview").addEventListener("click", () => { if (beepSettings) playSequence(beepSettings.link_lost_sequence); });

    const showNet = () => { $("net").textContent = [rttText, statsText].filter(Boolean).join(" · ") || "—"; };

    // ---- mémoires
    const khzText = (hz) => (hz ? String(Math.round(hz / 10) / 100) : "");
    function setSelect(select, value) {
      if (value && !Array.from(select.options).some((o) => o.value === value)) {
        select.appendChild(Object.assign(el("option", "", modeLabel(value)), { value: value }));
      }
      select.value = value || (select.options.length ? select.options[0].value : "");
    }
    function openForm(memory) {
      const rig = lastView && lastView.rig ? lastView.rig : {};
      editingId = memory ? memory.id : null;
      $("mem-form").hidden = false;
      $("mem-name").value = memory ? memory.name : "";
      $("mem-khz").value = khzText(memory ? memory.hz : rig.frequency_hz);
      setSelect($("mem-mode"), memory ? memory.mode : rig.mode);
      $("mem-fav").checked = memory ? memory.favorite : false;
      $("mem-delete").hidden = !memory;
      resetDelete();
      $("mem-name").focus();
    }
    function closeForm() { editingId = null; $("mem-form").hidden = true; resetDelete(); }
    function resetDelete() {
      deleteArmed = false;
      if (deleteTimer !== null) { window.clearTimeout(deleteTimer); deleteTimer = null; }
      $("mem-delete").textContent = I18N.t("common.delete");
    }
    function markActive(v) {
      const rig = v && v.rig ? v.rig : {};
      for (const { li, memory } of rows.values()) {
        const next = "mem" + (memory.favorite ? " fav" : "") + (memory.hz === rig.frequency_hz && memory.mode === rig.mode ? " active" : "");
        if (li.className !== next) li.className = next;
      }
    }
    function renderMemories(list) {
      $("mem-count").textContent = list.length ? "(" + list.length + ")" : "";
      $("mem-empty").hidden = list.length > 0;
      const ul = $("mem-list");
      ul.textContent = "";
      rows.clear();
      for (const m of list) {
        const li = el("li", "mem");
        const star = el("button", "star", m.favorite ? "★" : "☆");
        star.title = m.favorite ? I18N.t("ui.mem_unfavorite") : I18N.t("ui.mem_favorite");
        const recall = el("button", "recall");
        recall.title = I18N.t("ui.mem_recall");
        recall.appendChild(el("span", "mname", m.name));
        recall.appendChild(el("span", "mfreq", formatIcomFrequency(m.hz)));
        recall.appendChild(el("span", "mmode", shortMode(m.mode)));
        const edit = el("button", "edit", "✎");
        edit.title = I18N.t("ui.mem_edit");
        star.disabled = recall.disabled = edit.disabled = !connectedFlag;
        star.addEventListener("click", () => client.saveMemory({ memoryId: m.id, name: m.name, hz: m.hz, mode: m.mode, favorite: !m.favorite }).catch(fail));
        recall.addEventListener("click", () => client.recallMemory(m.id).catch(fail));
        edit.addEventListener("click", () => openForm(m));
        li.appendChild(star); li.appendChild(recall); li.appendChild(edit);
        ul.appendChild(li);
        rows.set(m.id, { li: li, memory: m });
      }
      markActive(lastView);
    }

    // ---- mesures du poste (partie défilante)
    function renderInstruments(list) {
      const keys = list.map((i) => i.key).join(",");
      const box = $("instruments");
      if (keys !== instrumentKeys) {
        instrumentKeys = keys;
        box.textContent = "";
        instrumentEls = new Map();
        for (const item of list) {
          const wrap = el("div", "inst"), val = el("span", "ival"), track = el("div", "itrack"), mask = el("div", "imask");
          track.appendChild(mask);
          wrap.appendChild(el("span", "ilabel", item.label)); wrap.appendChild(val); wrap.appendChild(track);
          box.appendChild(wrap);
          instrumentEls.set(item.key, { val: val, mask: mask, track: track });
        }
      }
      for (const item of list) {
        const node = instrumentEls.get(item.key);
        node.val.textContent = item.text;
        node.mask.style.width = (100 - Math.round(item.fraction * 100)) + "%";
        node.track.hidden = item.key === "ATT" || item.key === "AGC";
      }
      $("instruments-empty").hidden = list.length > 0;
    }

    // ---- fréquence : chiffres glissables, saisie au clavier
    function renderFrequency(hz) {
      const digits = frequencyDigits(hz), box = $("freq");
      if (!digits.length) { if (freqEls.length || box.textContent !== "—") { box.textContent = "—"; freqEls = []; } return; }
      if (digits.length !== freqEls.length) {                                      // la structure ne change presque jamais : les chiffres sont mis à jour sur place
        box.textContent = ""; freqEls = [];
        for (const d of digits) { const span = el("span", d.weight === null ? "sep" : "dig"); box.appendChild(span); freqEls.push(span); }
      }
      digits.forEach((d, i) => { if (freqEls[i].textContent !== d.char) freqEls[i].textContent = d.char; freqEls[i].weight = d.weight; });
    }
    function digitAt(x) {
      let best = null, gap = Infinity;
      for (const span of freqEls) {
        if (span.weight === null || span.weight === undefined) continue;
        const r = span.getBoundingClientRect(), distance = Math.abs(x - (r.left + r.right) / 2);
        if (distance < gap) { gap = distance; best = span; }
      }
      return best;
    }
    const frequencyLocked = () => !connectedFlag || !lastView || lastView.controlsLocked;
    function endDrag(ev, canTap) {
      if (!drag) return;
      const tap = canTap && !drag.moved && performance.now() - drag.t0 < 600;
      drag.el.className = "dig";
      drag = null;
      if (tap) openKeypad();
    }
    $("freq").addEventListener("pointerdown", (ev) => {
      if (frequencyLocked()) return;
      const digit = digitAt(ev.clientX);
      if (!digit) return;
      drag = { el: digit, weight: digit.weight, startY: ev.clientY, applied: 0, moved: false, t0: performance.now(), id: ev.pointerId };
      digit.className = "dig active";  // i18n-ok (classes CSS)
      if ($("freq").setPointerCapture) { try { $("freq").setPointerCapture(ev.pointerId); } catch (e) { /* capture indisponible */ } }
      if (ev.preventDefault) ev.preventDefault();
    });
    $("freq").addEventListener("pointermove", (ev) => {
      if (!drag || ev.pointerId !== drag.id) return;
      const dy = drag.startY - ev.clientY, steps = Math.trunc(dy / STEP_PX);
      if (Math.abs(dy) > 6) drag.moved = true;
      if (steps !== drag.applied) {
        client.nudgeFrequency(drag.weight, steps - drag.applied);
        if (navigator.vibrate) navigator.vibrate(4);
        drag.applied = steps;
      }
    });
    $("freq").addEventListener("pointerup", (ev) => endDrag(ev, true));
    $("freq").addEventListener("pointercancel", (ev) => endDrag(ev, false));
    $("freq").addEventListener("wheel", (ev) => {                                  // molette de la souris sur un chiffre
      if (frequencyLocked()) return;
      const digit = digitAt(ev.clientX);
      if (!digit) return;
      if (ev.preventDefault) ev.preventDefault();
      client.nudgeFrequency(digit.weight, ev.deltaY < 0 ? 1 : -1);
    }, { passive: false });

    function refreshKeypad() {
      const hz = parseFrequencyEntry(kpText);
      $("kp-display").textContent = kpText || "—";
      $("kp-preview").textContent = hz !== null ? formatIcomFrequency(hz) + "  =  " + khzText(hz) + " kHz"
        : kpText ? I18N.t("ui.keypad_invalid") : I18N.t("ui.keypad_hint");
      $("kp-ok").disabled = hz === null;
    }
    let keypadOpenedAt = -1e9;
    const keypadReady = () => performance.now() - keypadOpenedAt > 450;            // au toucher, Android envoie un « clic fantôme » à l'endroit du doigt : il tomberait sur le pavé qui vient de s'ouvrir  // i18n-ok
    function openKeypad() {
      if (frequencyLocked()) return;
      kpText = "";
      refreshKeypad();
      keypadOpenedAt = performance.now();
      $("keypad").hidden = false;
    }
    function closeKeypad() { $("keypad").hidden = true; }
    function keypadPress(key) {
      if (!keypadReady()) return;
      if (key === "⌫") kpText = kpText.slice(0, -1);
      else if (kpText.length < 12) kpText += key;
      refreshKeypad();
    }
    for (const key of ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"]) {
      const button = el("button", "", key);
      button.addEventListener("click", () => keypadPress(key));
      $("kp-keys").appendChild(button);
    }
    $("kp-cancel").addEventListener("click", () => { if (keypadReady()) closeKeypad(); });
    $("keypad").addEventListener("click", (ev) => { if (ev.target === $("keypad") && keypadReady()) closeKeypad(); });
    $("kp-ok").addEventListener("click", async () => {
      const hz = parseFrequencyEntry(kpText);
      if (hz === null || !keypadReady()) return;
      try { const res = await client.setFrequency(hz); if (res.ok) closeKeypad(); } catch (err) { fail(err); }
    });
    document.addEventListener("keydown", (ev) => {                                // clavier physique quand le pavé est ouvert
      if ($("keypad").hidden) return;
      if (/^[0-9.]$/.test(ev.key)) keypadPress(ev.key);
      else if (ev.key === ",") keypadPress(".");
      else if (ev.key === "Backspace") keypadPress("⌫");  // i18n-ok (touches du clavier)
      else if (ev.key === "Enter") $("kp-ok").click();  // i18n-ok
      else if (ev.key === "Escape") closeKeypad();  // i18n-ok
    });

    // ---- bandes (dernière fréquence et dernier mode par bande) et pas
    for (const band of BANDS) {
      const button = el("button", "chip", band.label);
      button.title = I18N.t("ui.band_title", { band: band.key });
      button.disabled = true;
      button.addEventListener("click", () => client.goBand(band.key).catch(fail));
      const dot = el("span", "banddot");                                             // spots actifs du Cluster DX sur la bande
      dot.hidden = true;
      button.appendChild(dot);
      $("bands").appendChild(button);
      bandButtons.set(band.key, button);
      bandDots.set(band.key, { dot: dot, title: button.title });
    }
    function applyFavBands() {
      /* Bandes préférées (réglage de ce navigateur) : les autres boutons sont masqués. */
      const shown = new Set(web.favoriteBands(store.get("trx.favbands", "")).map((b) => b.key));
      for (const [key, button] of bandButtons) button.hidden = !shown.has(key);
    }
    const favBoxes = new Map();
    for (const band of BANDS) {
      const label = el("label", "check");
      const box = el("input", "");
      box.type = "checkbox";
      box.checked = String(store.get("trx.favbands", "")).split(",").includes(band.key);
      box.addEventListener("change", () => {
        const keys = [];
        for (const [key, input] of favBoxes) if (input.checked) keys.push(key);
        store.set("trx.favbands", keys.join(","));
        applyFavBands();
      });
      favBoxes.set(band.key, box);
      label.appendChild(box);
      label.appendChild(el("span", "", band.label));
      $("fav-bands").appendChild(label);
    }
    applyFavBands();
    function paintBandDots(bands) {
      /* Couleur du gris au rouge selon le nombre de spots actifs ; nombre exact dans la bulle d'aide. */
      const levels = web.bandSpotLevels(bands);
      for (const [key, item] of bandDots) {
        const level = levels[key];
        item.dot.hidden = !level;
        if (level) item.dot.className = ["", "banddot lvl1", "banddot lvl2", "banddot lvl3"][level.level];  // i18n-ok (classes CSS)
        bandButtons.get(key).title = level ? I18N.plural("ui.band_title_spots", level.count, { title: item.title }) : item.title;
      }
    }
    let voyantsKey = "";
    function paintVoyants(v) {
      const list = v.connected ? v.indicators || [] : [];
      const key = list.map((i) => i.label + (i.on ? "1" : "0")).join("|");
      if (key === voyantsKey) return;
      voyantsKey = key;
      const box = $("voyants");
      box.textContent = "";
      for (const item of list) box.appendChild(el("span", "voyant" + (item.on ? " on" : "") + (item.alert ? " alert" : ""), item.label));
    }
    function paintModes(v) {                                                          // mode actuel allumé ; verrouillés pendant l'émission
      const current = v.rig ? v.rig.mode : null;
      for (const [m, button] of modeButtons) {
        button.className = "chip" + (m === current ? " on" : "");
        button.disabled = !v.connected || v.controlsLocked;
      }
    }
    const stepLabel = (hz) => (hz >= 1000 ? String(hz / 1000) + " kHz" : hz + " Hz");
    for (const hz of STEPS_HZ) $("step-select").appendChild(Object.assign(el("option", "", stepLabel(hz)), { value: String(hz) }));
    $("step-select").value = STEPS_HZ.includes(Number(store.get("trx.step", "1000"))) ? store.get("trx.step", "1000") : "1000";
    $("step-select").addEventListener("change", (ev) => store.set("trx.step", ev.target.value));
    function bindRepeat(button, direction) {                                       // un appui = un pas ; maintenu = répétition
      let delay = null, repeat = null;
      const stop = () => { if (delay !== null) { window.clearTimeout(delay); delay = null; } if (repeat !== null) { window.clearInterval(repeat); repeat = null; } };
      const nudge = () => client.nudgeFrequency(Number($("step-select").value), direction);
      button.addEventListener("pointerdown", () => { stop(); nudge(); delay = window.setTimeout(() => { delay = null; repeat = window.setInterval(nudge, 120); }, 400); });
      for (const type of ["pointerup", "pointercancel", "pointerleave"]) button.addEventListener(type, stop);
      button.addEventListener("click", (ev) => { if (ev.detail === 0) nudge(); });   // clavier : un pas
    }
    bindRepeat($("step-down"), -1);
    bindRepeat($("step-up"), 1);

    // ---- pertes de connexion : dernière raison et historique des 10 dernières
    function showLoss(index) {
      const entry = client.losses[index];
      $("loss-detail").textContent = entry ? describeLoss(entry) : I18N.t("ui.loss_none_detail");
    }
    function renderLosses(list) {
      const select = $("loss-select");
      select.textContent = "";
      $("loss-copy").disabled = $("loss-clear").disabled = list.length === 0;
      if (!list.length) {
        select.appendChild(Object.assign(el("option", "", I18N.t("ui.loss_none")), { value: "" }));
        $("loss-last").hidden = true; $("loss-open").hidden = true;
        showLoss(-1);
        return;
      }
      list.forEach((entry, i) => select.appendChild(Object.assign(el("option", "", lossSummary(entry)), { value: String(i) })));
      select.value = "0";
      showLoss(0);
      const last = list[0];
      $("loss-last").textContent = I18N.t(last.kind === "failed" ? "ui.loss_last_failed" : "ui.loss_last_lost", { title: last.title, explain: last.explain });
      $("loss-last").hidden = false; $("loss-open").hidden = false;
    }
    $("loss-select").addEventListener("change", (ev) => showLoss(Number(ev.target.value)));
    $("loss-open").addEventListener("click", () => {
      $("sec-diag").open = true; $("loss-select").value = "0"; showLoss(0);
      if ($("sec-diag").scrollIntoView) $("sec-diag").scrollIntoView();
    });
    $("loss-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText($("loss-detail").textContent); ui.log(I18N.t("ui.loss_copied"), ""); }
      catch (err) { ui.log(I18N.t("ui.loss_copy_failed"), "warn"); }
    });
    $("loss-clear").addEventListener("click", () => client.clearLosses());

    // ---- waterfall de l'audio reçu : analyse spectrale de 0 à 5 kHz
    const wfTexts = () => {
      $("wf-speed").textContent = wf.speedLabel(wfSettings.speed); $("wf-width").textContent = wf.widthLabel(wfSettings.width);
      $("wf-gain").textContent = wf.gainLabel(wfSettings.gain); $("wf-peak").textContent = wf.peakLabel(wfSettings.peak);
    };
    // Couleurs des dessins sur canvas : lues dans les variables CSS du thème (client.css), relues à chaque
    // changement de thème. Valeur de secours = thème par défaut (variable absente, vieux navigateur).
    const CANVAS_DEFAULTS = { "--fond": "#04070b", "--mesure": "#7cc0ff", "--alerte": "#f0a830",
                              "--spectre-remplissage": "rgba(98, 162, 236, .35)", "--spectre-grille": "rgba(255, 255, 255, .11)",
                              "--spectre-grille-forte": "rgba(255, 255, 255, .24)" };
    let canvasColors = Object.assign({}, CANVAS_DEFAULTS);
    function cssVar(name) {
      try {
        const value = window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return value || null;
      } catch (e) { return null; }
    }
    function loadThemeColors() {
      for (const name of Object.keys(CANVAS_DEFAULTS)) canvasColors[name] = cssVar(name) || CANVAS_DEFAULTS[name];
      wf.setGradient(wf.parseGradient(cssVar("--waterfall-degrade")) || wf.DEFAULT_GRADIENT);
    }
    loadThemeColors();
    function drawGrid() {
      gridCtx.clearRect(0, 0, WF_W, SPEC_H + FALL_H);
      const axis = $("wf-axis");
      axis.textContent = "";
      for (const tick of wf.axisTicks(wfSettings.width)) {
        const x = Math.round(tick.fraction * (WF_W - 1)) + 0.5;
        gridCtx.strokeStyle = tick.hz % 1000 === 0 ? canvasColors["--spectre-grille-forte"] : canvasColors["--spectre-grille"];
        gridCtx.lineWidth = 1; gridCtx.beginPath(); gridCtx.moveTo(x, 0); gridCtx.lineTo(x, SPEC_H + FALL_H); gridCtx.stroke();
        const label = el("span", "", tick.label);
        label.style.left = (tick.fraction * 100).toFixed(2) + "%";
        axis.appendChild(label);
      }
    }
    function resetFall() {
      fallCtx.fillStyle = canvasColors["--fond"]; fallCtx.fillRect(0, 0, WF_W, FALL_H);
      tracker.reset();
    }
    function drawSpectrum(values, peaks) {
      specCtx.fillStyle = canvasColors["--fond"]; specCtx.fillRect(0, 0, WF_W, SPEC_H);
      const y = (db) => SPEC_H - 1 - wf.levelToT(db, wfSettings.gain) * (SPEC_H - 2);
      specCtx.beginPath(); specCtx.moveTo(0, SPEC_H);
      for (let x = 0; x < WF_W; x++) specCtx.lineTo(x, y(values[x]));
      specCtx.lineTo(WF_W - 1, SPEC_H); specCtx.closePath(); specCtx.fillStyle = canvasColors["--spectre-remplissage"]; specCtx.fill();
      specCtx.beginPath();
      for (let x = 0; x < WF_W; x++) { if (x === 0) specCtx.moveTo(x, y(values[x])); else specCtx.lineTo(x, y(values[x])); }
      specCtx.strokeStyle = canvasColors["--mesure"]; specCtx.lineWidth = 1; specCtx.stroke();
      if (peaks) {
        specCtx.beginPath();
        for (let x = 0; x < WF_W; x++) { if (x === 0) specCtx.moveTo(x, y(peaks[x])); else specCtx.lineTo(x, y(peaks[x])); }
        specCtx.strokeStyle = canvasColors["--alerte"]; specCtx.lineWidth = 1; specCtx.stroke();
      }
      const top = wf.strongest(peaks || values, wfSettings.width);
      $("wf-peakinfo").textContent = top ? I18N.t("audiowaterfallview.peak", { khz: (top.hz / 1000).toFixed(2) }) : "";
    }
    function pushLine(values) {
      fallCtx.drawImage(fallCanvas, 0, 0, WF_W, FALL_H - 1, 0, 1, WF_W, FALL_H - 1);     // tout descend d'une ligne, la nouvelle arrive en haut
      if (!rowImage) rowImage = fallCtx.createImageData(WF_W, 1);
      wf.fillRow(rowImage.data, values, wfSettings.gain);
      fallCtx.putImageData(rowImage, 0, 0);
    }
    function frame(now) {
      wfRaf = null;
      if (!wfVisible || !analyser) return;
      analyser.getFloatFrequencyData(spectrumBuf);
      wfValues = wf.resample(spectrumBuf, audioCtx.sampleRate, analyser.fftSize, wfSettings.width, WF_W, wfValues);
      const interval = 1000 / wfSettings.speed;
      if (lastFrame === 0) { lastFrame = now; lastLine = now - interval; }   // 1re image : l'horloge part de l'horodatage de l'animation (pas de performance.now()), une ligne tout de suite  // i18n-ok
      const dt = (now - lastFrame) / 1000;
      lastFrame = now;
      drawSpectrum(wfValues, tracker.update(wfValues, dt, wfSettings.peak));
      for (let n = 0; n < 3 && now - lastLine >= interval; n++) { pushLine(wfValues); lastLine += interval; }
      if (now - lastLine > 1000) lastLine = now;                                         // retard important (onglet gelé) : on repart sans rafale
      wfRaf = window.requestAnimationFrame(frame);
    }
    function startWf() {
      if (wfRaf !== null || !analyser) { if (!analyser) $("wf-peakinfo").textContent = I18N.t("ui.wf_no_audio"); return; }
      if (audioCtx && audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
      lastLine = lastFrame = 0;                                                       // initialisés par la première image
      wfRaf = window.requestAnimationFrame(frame);
    }
    function stopWf() {
      if (wfRaf !== null) { window.cancelAnimationFrame(wfRaf); wfRaf = null; }
    }
    function setWaterfallShown(on) {                                                  // piloté par la mise en page personnalisée
      $("waterfall").hidden = !on;
      if (on === wfVisible) return;
      wfVisible = on;
      if (on) { drawGrid(); resetFall(); wfTexts(); startWf(); } else stopWf();
    }
    function layoutShown(visible) {
      if (visible === null) {                                                         // retour à la page d'origine : graphiques de puissance
        setWaterfallShown(false); $("txzone").hidden = false;
        return;
      }
      setWaterfallShown(visible.has("waterfall"));
    }
    function toggleWaterfall() {
      if (layout && layout.active) return;                                            // une zone à calques du profil s'en charge
      const now = performance.now();
      if (now - lastToggle < 350) return;                                               // double appui = UNE seule bascule
      lastToggle = now;
      if (audioDocked) {                                                              // puissance ET audio déjà affichés : seul le spectre HF bascule
        if (!hfDocked && hfx && hfx.configured(client.hello)) showZone(hfVisible ? "tx" : "hf");
        return;
      }
      if (hfDocked) { showZone(wfVisible ? "tx" : "audio", true); return; }          // spectre HF déjà affiché à droite : puissance <-> audio
      const current = hfVisible ? "hf" : wfVisible ? "audio" : "tx";
      const hfOk = !!hfx && hfx.configured(client.hello);                            // proposée même sans spectre reçu : la vue dit pourquoi
      showZone(hfx ? hfx.nextView(current, hfOk) : (current === "tx" ? "audio" : "tx"));
    }
    function showZone(next, keepDock) {
      /* Zone des graphiques : « tx » (puissance), « audio » (waterfall de l'audio reçu) ou « hf » (spectre du poste, plein écran).
         `keepDock` : la bascule puissance/audio ne referme pas le spectre HF intégré. */
      if (!audioDocked) {                                                             // spectre audio permanent : puissance et audio restent
        const audio = next === "audio";
        if (audio !== wfVisible) {
          wfVisible = audio;
          $("waterfall").hidden = !audio;
          if (audio) { drawGrid(); resetFall(); wfTexts(); startWf(); } else stopWf();
        }
        $("txzone").hidden = audio;
      }
      if (!(keepDock && hfDocked)) setHf(next === "hf");
    }
    function setAudioDock(on) {
      /* Paysage large : le spectre audio (calculé par le navigateur) reste affiché sous les réglages de la colonne de
         gauche, en plus des graphiques de puissance. Aucune donnée réseau en plus. */
      if (on === audioDocked) return;
      audioDocked = on;
      const box = $("waterfall");
      if (on) $("audio-dock").appendChild(box);
      else if (wfHome) wfHome.insertBefore(box, wfNext);
      $("audio-dock").hidden = !on;
      $("txzone").hidden = false;
      box.hidden = !on;
      wfVisible = on;
      if (on) { drawGrid(); resetFall(); wfTexts(); startWf(); } else stopWf();
    }
    function syncDock() {
      /* Spectre HF intégré : interrupteur allumé, paysage assez large, page d'usine, liaison établie et spectre disponible.
         Sinon la vue intégrée se referme (et l'interrupteur disparaît s'il ne peut pas servir). */  // i18n-ok
      if (!hfx) return;
      const allowed = hfx.canDock($("app").className, window.innerWidth, !!(layout && layout.active));
      const audioUsable = allowed && connectedFlag;                                   // spectre audio : pas besoin du spectre HF
      $("blk-audiodock").hidden = !audioUsable;
      $("audio-dock-on").checked = audioDockWanted;
      setAudioDock(audioUsable && audioDockWanted);
      const usable = allowed && connectedFlag && hfx.configured(client.hello);
      $("blk-hfdock").hidden = !usable;
      $("hf-dock-on").checked = hfDockWanted;
      const want = usable && hfDockWanted;
      if (want && !(hfVisible && hfDocked)) setHf(true, true);
      else if (!want && hfDocked) setHf(false);
    }
    // ---- spectre HF du poste : vue plein écran, dessinée à l'arrivée de chaque balayage (pas d'animation continue)
    const hfTexts = () => {
      if (!hfx) return;
      $("hf-gain").textContent = hfx.gainLabel(hfSettings.gain); $("hf-range").textContent = hfx.rangeLabel(hfSettings.range);
    };
    function hfLevelMax() {
      const sp = client.hello && client.hello.spectrum;
      return sp && sp.level_max > 0 ? sp.level_max : 160;
    }
    function hfResize(points) {
      /* Canvas à la résolution RÉELLE de l'écran (taille affichée × densité) ; renvoie true si la taille a changé. */
      const ratio = window.devicePixelRatio || 1;
      const spec = hfx.canvasSize(hfSpec.clientWidth, hfSpec.clientHeight, ratio, points, 120);
      const fall = hfx.canvasSize(hfFall.clientWidth, hfFall.clientHeight, ratio, points, 240);
      const grid = hfx.canvasSize(hfGrid.clientWidth, hfGrid.clientHeight, ratio, points, 360);
      hfLine = hfx.lineHeight(ratio);
      if (hfSpec.width === spec.width && hfSpec.height === spec.height && hfFall.width === fall.width && hfFall.height === fall.height
          && hfGrid.width === grid.width && hfGrid.height === grid.height) return false;
      hfSpec.width = spec.width; hfSpec.height = spec.height; hfFall.width = fall.width; hfFall.height = fall.height;
      hfGrid.width = grid.width; hfGrid.height = grid.height; hfRow = null; hfValues = null;
      return true;
    }
    function hfDrawGrid(frame) {
      const w = hfGrid.width, h = hfGrid.height;
      hfGridCtx.clearRect(0, 0, w, h);
      const axis = $("hf-axis");
      axis.textContent = "";
      for (const tick of hfx.scopeTicks(frame.lowHz, frame.highHz, 8)) {
        const x = Math.round(tick.fraction * (w - 1)) + 0.5;
        hfGridCtx.strokeStyle = canvasColors["--spectre-grille"];
        hfGridCtx.lineWidth = Math.max(1, Math.round(window.devicePixelRatio || 1)); hfGridCtx.beginPath(); hfGridCtx.moveTo(x, 0); hfGridCtx.lineTo(x, h); hfGridCtx.stroke();
        const label = el("span", "", tick.label);
        label.style.left = (tick.fraction * 100).toFixed(2) + "%";
        axis.appendChild(label);
      }
      $("hf-info").textContent = I18N.t(frame.outOfRange ? "ui.hf_width_out" : "ui.hf_width", { span: hfx.spanLabel(frame.lowHz, frame.highHz) });
    }
    function hfResetFall() {
      hfFallCtx.fillStyle = canvasColors["--fond"]; hfFallCtx.fillRect(0, 0, hfFall.width, hfFall.height);
      hfFloor = null;
    }
    function hfMarker() {
      const f = hfLast ? hfx.markerFraction(hfFreqHz, hfLast.lowHz, hfLast.highHz) : null;
      const marker = $("hf-marker");
      marker.hidden = f === null;
      if (f !== null) marker.style.left = (f * 100).toFixed(2) + "%";
    }
    function hfDraw(frame) {
      if (!hfx || !frame || !frame.points || !frame.points.length) return;
      const n = frame.points.length, gain = hfSettings.gain;
      const resized = hfResize(n);
      const rescaled = resized || !hfx.sameScale(hfLast, frame);
      if (rescaled) { hfDrawGrid(frame); hfResetFall(); }   // autre taille, largeur ou bande : historique effacé
      hfLast = frame;
      if (rescaled) drawSpots();
      $("hf-wait").hidden = true;
      const win = hfx.colorWindow(frame.points, hfLevelMax(), hfSettings.range, hfFloor);
      hfFloor = win.floor;
      // spectre : tracé vectoriel à la résolution de l'écran
      const W = hfSpec.width, H = hfSpec.height, ratio = window.devicePixelRatio || 1;
      const xOf = (i) => (n > 1 ? (i * (W - 1)) / (n - 1) : 0);
      const y = (v) => H - 1 - hfx.windowT(v, win, gain) * (H - 2);
      hfSpecCtx.fillStyle = canvasColors["--fond"]; hfSpecCtx.fillRect(0, 0, W, H);
      hfSpecCtx.beginPath(); hfSpecCtx.moveTo(0, H);
      for (let i = 0; i < n; i++) hfSpecCtx.lineTo(xOf(i), y(frame.points[i]));
      hfSpecCtx.lineTo(W - 1, H); hfSpecCtx.closePath(); hfSpecCtx.fillStyle = canvasColors["--spectre-remplissage"]; hfSpecCtx.fill();
      hfSpecCtx.beginPath();
      for (let i = 0; i < n; i++) { if (i === 0) hfSpecCtx.moveTo(xOf(i), y(frame.points[i])); else hfSpecCtx.lineTo(xOf(i), y(frame.points[i])); }
      hfSpecCtx.strokeStyle = canvasColors["--mesure"]; hfSpecCtx.lineWidth = Math.max(1, ratio); hfSpecCtx.lineJoin = "round"; hfSpecCtx.stroke();
      // waterfall : une bande fine par balayage, lissée entre les points du poste
      const FW = hfFall.width, FH = hfFall.height, L = Math.min(hfLine, FH);
      if (FH > L) hfFallCtx.drawImage(hfFall, 0, 0, FW, FH - L, 0, L, FW, FH - L);    // tout descend, le nouveau balayage arrive en haut
      if (!hfRow || hfRow.width !== FW || hfRow.height !== L) hfRow = hfFallCtx.createImageData(FW, L);
      hfValues = hfx.interpolateRow(frame.points, FW, hfValues);
      const d = hfRow.data;
      const hot = hfSettings.hot ? hfSOffset : null;
      for (let x = 0; x < FW; x++) {
        const c = hfx.hotColor(hfValues[x], hot);                                    // au-dessus de S7 : jaune, orange, rouge
        if (c) { d[x * 4] = c[0]; d[x * 4 + 1] = c[1]; d[x * 4 + 2] = c[2]; d[x * 4 + 3] = 255; continue; }
        const i = Math.round(hfx.windowT(hfValues[x], win, gain) * 255) * 3;
        d[x * 4] = wf.LUT[i]; d[x * 4 + 1] = wf.LUT[i + 1]; d[x * 4 + 2] = wf.LUT[i + 2]; d[x * 4 + 3] = 255;
      }
      for (let line = 1; line < L; line++) d.copyWithin(line * FW * 4, 0, FW * 4);
      hfFallCtx.putImageData(hfRow, 0, 0);
      hfMarker();
    }
    function enterFullscreen() {
      /* Plein écran puis paysage (Chrome Android) ; refusé ou absent : la vue occupe quand même toute la page. */
      const box = $("hfscope");
      try {
        const pending = box.requestFullscreen ? box.requestFullscreen({ navigationUI: "hide" }) : null;
        if (pending && pending.then) {
          pending.then(() => {
            try { const o = window.screen && window.screen.orientation; if (o && o.lock) o.lock("landscape").catch(() => {}); } catch (e) { /* verrou refusé */ }
          }).catch(() => {});
        }
      } catch (e) { /* plein écran refusé */ }
    }
    function leaveFullscreen() {
      try { const o = window.screen && window.screen.orientation; if (o && o.unlock) o.unlock(); } catch (e) { /* rien à relâcher */ }
      try { if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {}); } catch (e) { /* déjà sorti */ }
    }
    function setHf(on, docked) {
      /* Ouvre la vue HF en plein écran (docked faux) ou intégrée en haut de la colonne de droite (docked vrai) ; la ferme sinon. */
      on = on && !!hfx;
      docked = on && !!docked;
      if (on === hfVisible && docked === hfDocked) return;
      if (on && hfVisible) setHf(false);                                         // changement plein écran <-> intégré : on referme d'abord
      hfVisible = on;
      hfDocked = docked;
      const box = $("hfscope");
      box.className = "hf" + (docked ? " docked" : "");
      if (docked) $("hf-dock").appendChild(box);
      else if (hfHome && box.parentNode !== hfHome) hfHome.appendChild(box);
      $("hf-dock").hidden = !docked;
      $("hf-close").hidden = docked;                                             // intégrée : on la retire avec l'interrupteur
      box.hidden = !on;
      setVfo(false);
      syncWatch();                                                               // balayages reçus seulement vue ouverte (ou liste des spots, petit waterfall)
      if (spotBook) spotBook.clear();                                            // la station rejoue les spots à l'ouverture
      closeSpotCard(); closeSpotList(); drawSpots();
      if (spotTimer !== null) { clearInterval(spotTimer); spotTimer = null; }
      if (on && sp) spotTimer = setInterval(() => { drawSpots(); refreshSpotCard(); }, 15000);   // âges et estompage
      if (on) {
        hfLast = null; $("hf-wait").hidden = false; $("hf-marker").hidden = true; $("hf-axis").textContent = ""; $("hf-info").textContent = "";
        hfTexts();
        if (!docked) enterFullscreen();
        if (lastView) hfState(lastView, lastView.pttState !== "RX");
        if (client.spectrumFrame) hfDraw(client.spectrumFrame);
      } else {
        leaveFullscreen();
      }
    }
    function hfState(v, transmitting) {
      if (!hfVisible) return;
      if (!hfx.configured(client.hello)) { showZone("tx"); return; }               // station sans spectre : retour aux graphiques
      const receiving = hfx.available(client.hello, client.state);
      $("hf-wait").textContent = hfx.waitText(client.state);                       // pourquoi rien n'arrive (écran du poste, port...)
      if (!receiving) $("hf-wait").hidden = false;
      else if (hfLast) $("hf-wait").hidden = true;
      hfFreqHz = v.frequencyHz;
      $("hf-freq").textContent = v.frequency;
      $("hf-mode").textContent = v.modeShort;
      $("hf-tx").hidden = !transmitting;
      $("hf-tx").textContent = v.mine ? I18N.t("stationtab.tx_in_progress") : I18N.t("ui.tx_other", { owner: v.owner || "?" });
      $("hf-stop").disabled = !v.connected;
      if (transmitting || !v.connected) setVfo(false);                            // jamais d'accord pendant l'émission  // i18n-ok
      $("hf-vfo").disabled = !v.connected || transmitting || !!v.controlsLocked;
      hfRigSettings(v.connected && !transmitting);
      hfMarker();
      refreshSpotCard();
    }
    function setVfo(on) {
      hfVfo = !!on;
      hfDrag = null;
      $("hf-vfo").className = "chip" + (hfVfo ? " on" : "");
      $("hf-plot").className = "hf-plot" + (hfVfo ? " tuning" : "");
    }
    function hfRigSettings(enabled) {
      /* Réglages du poste, tels que relus par la station ; verrouillés pendant l'émission ou s'ils sont inconnus. */
      const sp = (client.state && client.state.spectrum && client.state.spectrum.settings) || {};
      $("hf-set-mode").textContent = hfx.modeSettingLabel(sp.mode);
      $("hf-set-span").textContent = hfx.spanSettingLabel(sp.span);
      $("hf-ref").textContent = hfx.refLabel(sp.ref);
      $("hf-set-speed").textContent = hfx.speedSettingLabel(sp.speed);
      $("hf-set-mode").disabled = !enabled || !sp.mode;
      $("hf-set-span").disabled = !enabled || sp.mode !== "center" || !Number.isFinite(sp.span);   // la largeur ne vaut qu'en mode centré
      $("hf-ref-down").disabled = $("hf-ref-up").disabled = !enabled || !Number.isFinite(sp.ref);
      $("hf-set-speed").disabled = !enabled || !sp.speed;
    }
    function hfSet(name, value) {
      if (value === null || value === undefined) return;
      client.setSpectrum(name, value).then(() => { if (lastView) hfState(lastView, lastView.pttState !== "RX"); }).catch(fail);
    }

    // ---- spots du Cluster DX : marqueurs, fiche, QSY, liste (la station n'envoie que la bande courante, vue ouverte)
    function spotsKnown() { $("hf-spots").hidden = $("hf-list").hidden = !sp; }
    function spotTexts() { $("hf-spots").className = "chip" + (spotsOn ? " on" : ""); }
    function drawSpots() {
      const layer = $("hf-spot-layer");
      layer.textContent = "";
      if (!sp || !spotBook || !hfVisible || !hfLast || !spotsOn) return;
      const now = Date.now(), visible = spotBook.visible(hfLast.lowHz, hfLast.highHz);
      const width = layer.clientWidth || $("hf-plot").clientWidth || hfGrid.width / (window.devicePixelRatio || 1) || 0;
      const span = hfLast.highHz - hfLast.lowHz;
      for (const s of visible) {
        const line = el("div", "spot-line k-" + s.kind);  // i18n-ok (classe CSS)
        line.style.left = (((s.hz - hfLast.lowHz) / span) * 100).toFixed(2) + "%";
        line.style.opacity = String(sp.opacity(sp.ageSeconds(s, now)) * 0.7);
        layer.appendChild(line);
      }
      const rowPx = 18;
      for (const tag of sp.layoutLabels(visible, hfLast.lowHz, hfLast.highHz, width, { rows: 3, charPx: 7, padPx: 12 })) {
        const first = spotBook.get(tag.ids[0]);
        const age = first ? sp.ageSeconds(first, now) : 0;
        const button = el("button", "spot-tag k-" + (first ? first.kind : "cluster") + (tag.group ? " group" : "")  // i18n-ok (classe CSS)
                                    + (!tag.group && age <= sp.FRESH_S ? " fresh" : ""), tag.text);
        button.style.left = tag.x.toFixed(1) + "px";
        button.style.top = (2 + tag.row * rowPx) + "px";
        if (!tag.group) button.style.opacity = String(sp.opacity(age));
        button.title = tag.group ? I18N.t("ui.near_spots_title", { count: tag.ids.length }) : (first ? first.dx + " " + first.khz.toFixed(1) + " kHz" : "");
        const ids = tag.ids.slice();
        button.addEventListener("pointerdown", (ev) => { if (ev.stopPropagation) ev.stopPropagation(); });   // ni accord au doigt, ni fermeture de la vue
        button.addEventListener("click", (ev) => { if (ev.stopPropagation) ev.stopPropagation(); if (ids.length > 1) openSpotList(ids); else openSpotCard(ids[0]); });
        layer.appendChild(button);
      }
    }
    function openSpotCard(id) {
      spotCardId = id; $("spot-list").hidden = true; $("spot-card").hidden = false; $("spot-note").textContent = "";
      refreshSpotCard();
    }
    function closeSpotCard() { spotCardId = null; $("spot-card").hidden = true; }
    function refreshSpotCard() {
      if (!sp || spotCardId === null || $("spot-card").hidden) return;
      const s = spotBook.get(spotCardId);
      const locked = frequencyLocked();
      if (!s) { $("spot-qsy").disabled = true; $("spot-note").textContent = I18N.t("hfscopeview.spot_gone"); return; }
      $("spot-dx").textContent = s.dx;
      $("spot-kind").textContent = s.count > 1 ? I18N.t("hfscopeview.kind_spotters", { kind: sp.kindLabel(s.kind), count: s.count }) : sp.kindLabel(s.kind);
      $("spot-freq").textContent = s.khz.toFixed(1) + " kHz · " + sp.modeLabel(s);
      $("spot-info").textContent = [s.country ? s.country + (s.continent ? " (" + s.continent + ")" : "") : "",
                                    I18N.t("hfscopeview.from", { call: s.de || "?" }), (s.time ? s.time.slice(0, 2) + ":" + s.time.slice(2) + " UTC" : ""),
                                    sp.ageLabel(sp.ageSeconds(s, Date.now()))].filter(Boolean).join(" · ");
      $("spot-comment").textContent = s.comment;
      $("spot-qsy").disabled = locked;
      $("spot-qsy").title = locked ? I18N.t("ui.spot_qsy_locked") : I18N.t("ui.spot_qsy");
    }
    function spotQsy() {
      const s = spotCardId === null ? null : spotBook.get(spotCardId);
      if (!s || frequencyLocked()) return;
      const target = sp.qsyTarget(s, (mode) => client.adaptSpotMode(mode));
      $("spot-qsy").disabled = true; $("spot-note").textContent = I18N.t("ui.qsy_pending");
      client.qsy(target.hz, target.mode).then((res) => {
        if (res && res.ok) { ui.log(I18N.t("ui.qsy_done", { dx: s.dx, khz: s.khz.toFixed(1) }), ""); closeSpotCard(); }
        else { $("spot-note").textContent = res && res.reason ? I18N.t("ui.qsy_refused_reason", { reason: web.reasonText(res.reason, res.detail, res.ort) }) : I18N.t("ui.qsy_refused"); refreshSpotCard(); }
      }).catch((err) => { $("spot-note").textContent = I18N.t("ui.qsy_failed", { error: err.message }); refreshSpotCard(); });
    }
    function openSpotList(ids) {
      spotListIds = ids || null; closeSpotCard(); $("spot-list").hidden = false;
      renderSpotList();
    }
    function closeSpotList() { spotListIds = null; $("spot-list").hidden = true; }
    function renderSpotList() {
      if (!sp || $("spot-list").hidden) return;
      const now = Date.now();
      const all = spotListIds ? spotListIds.map((id) => spotBook.get(id)).filter(Boolean) : spotBook.all();
      $("spot-sort").textContent = spotSort === "age" ? I18N.t("hfscopeview.sort_age") : I18N.t("hfscopeview.sort_freq");
      $("spot-list-title").textContent = spotListIds ? I18N.t("ui.near_spots_list", { count: all.length }) : I18N.t("hfscopeview.band_spots", { count: all.length });
      const box = $("spot-items");
      box.textContent = "";
      if (!all.length) { box.appendChild(el("div", "hf-info", I18N.t("hfscopeview.no_spot"))); return; }
      for (const s of sp.sortList(all, spotSort, now)) {
        const item = el("button", "", s.khz.toFixed(1) + "  " + s.dx + "  " + (s.mode || "?") + "  " + sp.ageLabel(sp.ageSeconds(s, now))
                                      + (s.kind !== "cluster" ? "  [" + sp.kindLabel(s.kind) + "]" : ""));
        item.addEventListener("click", () => openSpotCard(s.id));
        box.appendChild(item);
      }
    }
    function onSpots(data) {
      if (!sp || !spotBook) return;
      spotsKnown();
      if (!spotBook.apply(data, Date.now())) return;
      drawSpots(); refreshSpotCard(); renderSpotList();
    }
    function onClusterHealth(state) {
      const dot = $("hf-cluster");
      dot.hidden = false;
      dot.className = "cluster-dot " + (["green", "orange", "red"].includes(state) ? state : "");
      dot.title = sp ? sp.healthLabel(state) : "Cluster DX";  // i18n-ok (nom propre)
      spotsKnown();
    }
    $("hf-spots").addEventListener("click", () => { spotsOn = !spotsOn; store.set("trx.spots", spotsOn ? "1" : "0"); spotTexts(); drawSpots(); });
    $("hf-list").addEventListener("click", () => { if ($("spot-list").hidden) openSpotList(null); else closeSpotList(); });
    $("spot-close").addEventListener("click", closeSpotCard);
    $("spot-qsy").addEventListener("click", spotQsy);
    $("spot-list-close").addEventListener("click", closeSpotList);
    $("spot-sort").addEventListener("click", () => { spotSort = spotSort === "age" ? "freq" : "age"; renderSpotList(); });
    spotTexts();

    function setupAnalysis(stream) {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context || !stream) return;
      try {
        if (!audioCtx) audioCtx = new Context();
        teardownAnalysis();
        wfSource = audioCtx.createMediaStreamSource(stream);
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 4096; analyser.smoothingTimeConstant = 0.35;
        wfSource.connect(analyser);                                                     // jamais relié à la sortie : le son part par l'élément <audio>
        spectrumBuf = new Float32Array(analyser.frequencyBinCount);
        if (wfVisible) startWf();
      } catch (err) { ui.log(I18N.t("ui.analysis_unavailable", { error: err.message }), "warn"); }
    }
    function teardownAnalysis() {
      stopWf();
      if (wfSource) { try { wfSource.disconnect(); } catch (e) { /* déjà détaché */ } wfSource = null; }
      analyser = null; spectrumBuf = null;
    }
    $("txzone").addEventListener("click", toggleWaterfall);
    $("wf-plot").addEventListener("click", toggleWaterfall);
    // un appui sur le spectre ne ferme JAMAIS la vue HF : seulement le bouton « Fermer » (ou la sortie du plein écran)
    $("hf-vfo").addEventListener("click", () => setVfo(!hfVfo));
    let hfDragged = false;                                                        // glissement VFO : pas d'accord au relâcher
    $("hf-plot").addEventListener("pointerdown", (ev) => {
      hfDragged = false;
      if (!hfVfo || frequencyLocked() || !hfLast) return;
      const span = hfLast.highHz - hfLast.lowHz;
      hfDrag = { id: ev.pointerId, startX: ev.clientX, applied: 0, span: span, step: hfx.tuneStep(span),
                 width: $("hf-plot").clientWidth || hfSpec.width };
      if ($("hf-plot").setPointerCapture) { try { $("hf-plot").setPointerCapture(ev.pointerId); } catch (e) { /* capture indisponible */ } }
      if (ev.preventDefault) ev.preventDefault();
    });
    $("hf-plot").addEventListener("pointermove", (ev) => {
      if (!hfDrag || ev.pointerId !== hfDrag.id) return;
      if (frequencyLocked()) { hfDrag = null; return; }                           // l'émission a commencé pendant le geste
      const steps = hfx.dragSteps(ev.clientX - hfDrag.startX, hfDrag.width, hfDrag.span, hfDrag.step);
      if (steps !== hfDrag.applied) {
        client.nudgeFrequency(hfDrag.step, steps - hfDrag.applied);               // affichage immédiat, UNE commande après le geste
        hfDrag.applied = steps; hfDragged = true;
      }
    });
    // toucher le spectre = accorder (comme l'application), fréquence arrondie au kHz ; les étiquettes de spots arrêtent le clic
    $("hf-plot").addEventListener("click", (ev) => {
      if (hfDragged || frequencyLocked() || !hfLast || !$("hf-plot").getBoundingClientRect) return;
      const box = $("hf-plot").getBoundingClientRect();
      const hz = box.width > 0 ? hfx.frequencyAt((ev.clientX - box.left) / box.width, hfLast.lowHz, hfLast.highHz) : null;
      if (hz === null) return;
      client.qsy(hz).then((res) => {
        if (!(res && res.ok)) ui.log(res && res.reason ? I18N.t("ui.qsy_refused_reason", { reason: web.reasonText(res.reason, res.detail, res.ort) }) : I18N.t("ui.qsy_refused"), "warn");
      }).catch(fail);
    });
    for (const type of ["pointerup", "pointercancel"]) $("hf-plot").addEventListener(type, () => { hfDrag = null; });
    $("hf-close").addEventListener("click", () => showZone("tx"));
    const hfSettingsNow = () => (client.state && client.state.spectrum && client.state.spectrum.settings) || {};
    $("hf-set-mode").addEventListener("click", () => hfSet("mode", hfx.nextMode(hfSettingsNow().mode)));
    $("hf-set-span").addEventListener("click", () => hfSet("span", hfx.nextSpan(hfSettingsNow().span)));
    $("hf-set-speed").addEventListener("click", () => hfSet("speed", hfx.nextSpeed(hfSettingsNow().speed)));
    $("hf-ref-down").addEventListener("click", () => hfSet("ref", hfx.stepRef(hfSettingsNow().ref, -hfx.REF_UI_STEP)));
    $("hf-ref-up").addEventListener("click", () => hfSet("ref", hfx.stepRef(hfSettingsNow().ref, hfx.REF_UI_STEP)));
    $("hf-stop").addEventListener("click", () => client.stop().catch(fail));          // STOP toujours possible, même en plein écran
    $("hf-range").addEventListener("click", () => {
      if (!hfx) return;
      hfSettings = Object.assign({}, hfSettings, { range: hfx.nextRange(hfSettings.range) });
      store.set("trx.hf", JSON.stringify(hfSettings));
      hfTexts();
      if (hfLast) { const again = hfLast; hfLast = null; hfDraw(again); }           // nouvelle échelle de couleurs : historique effacé
    });
    function hotTexts() {
      $("hf-hot").className = "chip" + (hfSettings.hot ? " on" : ""); $("mini-hot").className = $("hf-hot").className;
    }
    function toggleHot() {
      hfSettings = Object.assign({}, hfSettings, { hot: !hfSettings.hot });
      store.set("trx.hf", JSON.stringify(hfSettings));
      hotTexts();
    }
    hotTexts();
    $("hf-hot").addEventListener("click", toggleHot);
    $("hf-gain").addEventListener("click", () => {
      if (!hfx) return;
      hfSettings = Object.assign({}, hfSettings, { gain: hfx.nextGain(hfSettings.gain) });
      store.set("trx.hf", JSON.stringify(hfSettings));
      hfTexts();
      if (hfLast) { const again = hfLast; hfLast = null; hfDraw(again); }           // nouvelle échelle de couleurs : historique effacé
    });
    if (document.addEventListener) {
      document.addEventListener("fullscreenchange", () => {                           // geste « retour » : quitter le plein écran ferme la vue
        if (document.fullscreenElement && document.fullscreenElement === $("hfscope")) { hfFull = true; return; }
        if (hfFull) { hfFull = false; if (hfVisible) showZone("tx"); }
      });
    }
    for (const [id, name] of [["wf-speed", "speed"], ["wf-width", "width"], ["wf-gain", "gain"], ["wf-peak", "peak"]]) {
      $(id).addEventListener("click", () => {
        wfSettings = wf.nextSetting(wfSettings, name);
        store.set("trx.wf", wf.serializeSettings(wfSettings));
        wfTexts();
        if (name === "width") { drawGrid(); resetFall(); }                              // l'échelle change : l'ancien historique n'a plus de sens  // i18n-ok
        if (name === "peak") tracker.reset();
      });
    }

    const squelchLabel = (percent) => (percent === 0 ? I18N.t("stationtab.squelch_open") : percent + " %");

    // ---- visiteurs (docs/visiteurs-cahier-des-charges.md) : 🎧 N, liste, bandeaux, mode visiteur
    let presenceOpen = false, lastPresence = null;
    function renderPresenceList() {
      const list = $("presence-list"), pv = lastPresence;
      list.textContent = "";
      if (!pv) return;
      for (const person of pv.people) {
        const li = el("li", "");
        li.appendChild(el("span", "grow", person.text)); li.appendChild(el("span", "dim", person.role + " · " + person.since));
        list.appendChild(li);
      }
      for (const visitor of pv.kick) {                                          // opérateur : « Déconnecter » par visiteur
        const li = el("li", "");
        const button = el("button", "chip", I18N.t("common.disconnect"));
        button.addEventListener("click", () => {
          if (!window.confirm(I18N.t("ui.kick_confirm", { name: visitor.text }))) return;
          client.kickListener(visitor.account).catch(fail);
        });
        li.appendChild(el("span", "grow", visitor.text)); li.appendChild(el("span", "dim", visitor.detail)); li.appendChild(button);
        list.appendChild(li);
      }
      $("presence-note").textContent = pv.suspended || pv.grace || (pv.people.length ? "" : I18N.t("presenceviews.nobody"));
      $("presence-reopen").hidden = !pv.canReopen;
    }
    function renderPresence(v) {
      const pv = v.presence;
      lastPresence = pv;
      if (v.listener) document.documentElement.setAttribute("data-role", "listener");   // commandes inertes, réglages masqués (client.css)
      else document.documentElement.removeAttribute("data-role");
      $("listener-badge").hidden = !v.listener;
      const pill = $("presence");
      pill.hidden = !pv || !pv.label;
      if (pv && pv.label) pill.textContent = pv.label;
      const banner = $("presence-banner");
      const text = pv ? (pv.suspended || pv.grace) : "";
      banner.hidden = !text;
      banner.textContent = text;
      if (presenceOpen) renderPresenceList();
      const box = $("blk-listeners");                                            // commutateur de l'opérateur
      box.hidden = !pv || !pv.switchShown;
      if (pv && pv.switchShown) {
        $("listeners-open").checked = pv.switchOn;
        $("listeners-open").disabled = !pv.switchAvailable && !pv.switchOn;
        $("listeners-note").textContent = pv.switchNote;
      }
    }
    $("listeners-open").addEventListener("change", (event) => {
      const on = !!event.target.checked;
      if (!on && lastPresence && lastPresence.count > 0
          && !window.confirm(I18N.t("ui.listeners_close_confirm", { count: lastPresence.count }))) {
        event.target.checked = true;
        return;
      }
      client.setListenersOpen(on).catch(fail);
    });
    // ---- couleurs chaudes et petit waterfall HF avant les bandes (étape 100)
    function hfCalibrate(frame) {
      /* Recalage des niveaux du poste sur le S-mètre, au repère de la fréquence, en réception (hfscope.sCalibrate). */
      if (!hfx || !frame || !frame.points) return;
      const st = client.state || {}, rig = st.rig || {}, ptt = st.ptt || {};
      hfSOffset = hfx.sCalibrate(hfSOffset, frame.points, hfx.markerFraction(rig.frequency_hz, frame.lowHz, frame.highHz),
                                 rig.strength_db, ptt.state === "RX");
    }
    function miniActive() {
      return !!(hfx && hfSettings.mini && connectedFlag && hfx.configured(client.hello));
    }
    function syncWatch() {
      /* Balayages demandés à la station tant qu'une vue en a besoin : grand spectre, liste des spots ou petit waterfall. */
      const want = !!(hfVisible || recentOpen || miniActive());
      if (want !== !!client._spectrumWatch) client.watchSpectrum(want);
    }
    function miniDraw(frame) {
      if (!frame || !frame.points || !frame.points.length) return;
      const ratio = window.devicePixelRatio || 1;
      const size = hfx.canvasSize(miniFall.clientWidth, miniFall.clientHeight, ratio, frame.points.length, 56);
      if (miniFall.width !== size.width || miniFall.height !== size.height || !hfx.sameScale(miniLast, frame)) {
        miniFall.width = size.width; miniFall.height = size.height; miniRow = null; miniValues = null; miniFloor = null;
        miniCtx.fillStyle = canvasColors["--fond"]; miniCtx.fillRect(0, 0, miniFall.width, miniFall.height);
        const axis = $("mini-axis");                                                 // échelle : seulement quand elle change
        axis.textContent = "";
        for (const tick of hfx.scopeTicks(frame.lowHz, frame.highHz, 5)) {
          if (tick.fraction < 0.06 || tick.fraction > 0.94) continue;                 // pas de libellé coupé au bord
          const label = el("span", "", tick.label);
          label.style.left = (tick.fraction * 100).toFixed(2) + "%";
          axis.appendChild(label);
        }
      }
      miniLast = frame;
      $("mini-wait").hidden = true;
      const win = hfx.colorWindow(frame.points, hfLevelMax(), hfSettings.range, miniFloor);
      miniFloor = win.floor;
      const W = miniFall.width, H = miniFall.height, L = Math.min(hfx.lineHeight(ratio), H);
      if (H > L) miniCtx.drawImage(miniFall, 0, 0, W, H - L, 0, L, W, H - L);
      if (!miniRow || miniRow.width !== W || miniRow.height !== L) miniRow = miniCtx.createImageData(W, L);
      miniValues = hfx.interpolateRow(frame.points, W, miniValues);
      const d = miniRow.data, hot = hfSettings.hot ? hfSOffset : null;
      for (let x = 0; x < W; x++) {
        const c = hfx.hotColor(miniValues[x], hot);
        if (c) { d[x * 4] = c[0]; d[x * 4 + 1] = c[1]; d[x * 4 + 2] = c[2]; d[x * 4 + 3] = 255; continue; }
        const i = Math.round(hfx.windowT(miniValues[x], win, hfSettings.gain) * 255) * 3;
        d[x * 4] = wf.LUT[i]; d[x * 4 + 1] = wf.LUT[i + 1]; d[x * 4 + 2] = wf.LUT[i + 2]; d[x * 4 + 3] = 255;
      }
      for (let line = 1; line < L; line++) d.copyWithin(line * W * 4, 0, W * 4);
      miniCtx.putImageData(miniRow, 0, 0);
      const rig = (client.state && client.state.rig) || {};
      const f = hfx.markerFraction(rig.frequency_hz, frame.lowHz, frame.highHz);
      $("mini-marker").hidden = f === null;
      if (f !== null) $("mini-marker").style.left = (f * 100).toFixed(2) + "%";
    }
    function paintMini(v) {
      const offered = !!(hfx && v.connected && hfx.configured(client.hello));
      $("mini-wf-on").hidden = !offered;
      $("mini-wf-on").className = "chip" + (hfSettings.mini ? " on" : "");
      const active = miniActive();
      $("blk-miniwf").hidden = !active;
      if (active && !miniWasActive) {
        miniLast = null; $("mini-wait").hidden = false; $("mini-wait").textContent = hfx.waitText(client.state);
        // Curseur au centre : une seule demande à l'apparition, par un opérateur et en réception (refusé sinon par la station)
        const sp = (client.state && client.state.spectrum && client.state.spectrum.settings) || {};
        if (!v.listener && v.pttState === "RX" && sp.mode && sp.mode !== "center") client.setSpectrum("mode", "center").catch(() => {});
      }
      miniWasActive = active;
      syncWatch();
      if (!$("mini-dialog").hidden) miniTexts(v);
    }
    function miniTexts(v) {
      const sp = (client.state && client.state.spectrum && client.state.spectrum.settings) || {};
      const enabled = !!(v && v.connected && v.pttState === "RX" && !v.listener);
      $("mini-span-info").textContent = miniLast ? I18N.t("hfscopeview.width_shown", { span: hfx.spanLabel(miniLast.lowHz, miniLast.highHz) }) : "";
      $("mini-set-span").textContent = hfx.spanSettingLabel(sp.span); $("mini-set-mode").textContent = hfx.modeSettingLabel(sp.mode);
      $("mini-set-speed").textContent = hfx.speedSettingLabel(sp.speed); $("mini-ref").textContent = hfx.refLabel(sp.ref);
      for (const id of ["mini-set-span", "mini-set-mode", "mini-set-speed", "mini-ref-down", "mini-ref-up"]) $(id).disabled = !enabled;
      $("mini-gain").textContent = hfx.gainLabel(hfSettings.gain); $("mini-range").textContent = hfx.rangeLabel(hfSettings.range);
      hotTexts();
    }
    function setMini(on) {
      hfSettings = Object.assign({}, hfSettings, { mini: !!on });
      store.set("trx.hf", JSON.stringify(hfSettings));
      if (lastView) paintMini(lastView);
    }
    const miniSettingsNow = () => (client.state && client.state.spectrum && client.state.spectrum.settings) || {};
    $("mini-wf-on").addEventListener("click", () => setMini(!hfSettings.mini));
    $("blk-miniwf").addEventListener("click", () => { $("mini-dialog").hidden = false; miniTexts(lastView); });
    $("mini-close").addEventListener("click", () => { $("mini-dialog").hidden = true; });
    $("mini-hide").addEventListener("click", () => { $("mini-dialog").hidden = true; setMini(false); });
    $("mini-hot").addEventListener("click", toggleHot);
    $("mini-set-span").addEventListener("click", () => hfSet("span", hfx.nextSpan(miniSettingsNow().span)));
    $("mini-set-mode").addEventListener("click", () => hfSet("mode", hfx.nextMode(miniSettingsNow().mode)));
    $("mini-set-speed").addEventListener("click", () => hfSet("speed", hfx.nextSpeed(miniSettingsNow().speed)));
    $("mini-ref-down").addEventListener("click", () => hfSet("ref", hfx.stepRef(miniSettingsNow().ref, -hfx.REF_UI_STEP)));
    $("mini-ref-up").addEventListener("click", () => hfSet("ref", hfx.stepRef(miniSettingsNow().ref, hfx.REF_UI_STEP)));
    $("mini-gain").addEventListener("click", () => {
      hfSettings = Object.assign({}, hfSettings, { gain: hfx.nextGain(hfSettings.gain) });
      store.set("trx.hf", JSON.stringify(hfSettings)); hfTexts(); miniTexts(lastView);
    });
    $("mini-range").addEventListener("click", () => {
      hfSettings = Object.assign({}, hfSettings, { range: hfx.nextRange(hfSettings.range) });
      store.set("trx.hf", JSON.stringify(hfSettings)); hfTexts(); miniTexts(lastView); miniLast = null;
    });

    // ---- mesure de TOS (docs/tos-cahier-des-charges.md) : chaque point est une prise d'émission NORMALE de cette page
    const sw = root.TrxSwr || null;
    let swrResult = null, swrRunning = false, swrPlanTimer = null, swrSeenFor = null, swrDialogShownFor = null, swrName = "";
    function swrOffered() {
      return !!(sw && client.connected && client.hello && Array.isArray(client.hello.features) && client.hello.features.includes("swr"));
    }
    function swrRange() {
      /* Plage choisie : bande du poste (table de swr.js) ou centre ± largeur/2 ; null si incomplète. */
      const rig = (client.state && client.state.rig) || {};
      if ($("swr-use-band").checked) {
        const b = Number.isFinite(rig.frequency_hz) ? sw.bandAt(rig.frequency_hz) : null;
        return b ? { lowHz: b.low_hz, highHz: b.high_hz, name: b.name } : null;
      }
      const center = Math.round(parseFloat(String($("swr-center").value).replace(",", ".")) * 1000);
      const width = Math.round(parseFloat(String($("swr-width").value).replace(",", ".")) * 1000);
      const r = sw.rangeFromCenter(center, width);
      return r ? Object.assign(r, { name: "" }) : null;
    }
    function swrPlanText() {
      /* Calcul affiché tout de suite (swr.js), complété par le plan de la station (hors bande, watts, durée). */
      const rig = (client.state && client.state.rig) || {};
      const b = Number.isFinite(rig.frequency_hz) ? sw.bandAt(rig.frequency_hz) : null;
      $("swr-band").textContent = b ? I18N.t("ui.swr_band", { name: b.name, low: sw.freqLabel(b.low_hz), high: sw.freqLabel(b.high_hz) }) : I18N.t("ui.swr_band_none");
      $("swr-center-row").hidden = $("swr-use-band").checked;
      if (!$("swr-center").value && Number.isFinite(rig.frequency_hz)) $("swr-center").value = String(Math.round(rig.frequency_hz / 1000));
      $("swr-power-text").textContent = " " + $("swr-power").value + " %";
      const range = swrRange(), points = parseInt($("swr-points").value, 10);
      if (!range) { $("swr-plan").textContent = I18N.t("swrscreen.choose_range"); $("swr-start").disabled = true; return null; }
      const p = sw.plan(range.lowHz, range.highHz, points, Number($("swr-points").max) || sw.MAX_POINTS);
      if (p.error) { $("swr-plan").textContent = web.reasonText(p.error); $("swr-start").disabled = true; return null; }
      const planFields = { center: $("swr-center").value, half: Number(String($("swr-width").value).replace(",", ".")) / 2,
        low: sw.freqLabel(p.lowHz), high: sw.freqLabel(p.highHz), step: p.stepHz / 1000, count: p.freqs.length };
      $("swr-plan").textContent = I18N.t($("swr-use-center").checked ? "swrscreen.plan_center" : "swrscreen.plan", planFields)
        + (p.amateurOnly ? "" : I18N.t("swrscreen.plan_outside"));
      $("swr-start").disabled = swrRunning || !(lastView && lastView.armed && lastView.connected);
      if (swrPlanTimer !== null) window.clearTimeout(swrPlanTimer);
      swrPlanTimer = window.setTimeout(() => {                                       // plan de la station (rien n'est émis)
        client.swrPlan(range.lowHz, range.highHz, points, Number($("swr-power").value)).then((res) => {
          if (!res || !res.ok || !res.plan) return;
          const pl = res.plan, skipped = pl.points.filter((x) => x.status === "out_of_band").length;
          const mode = web.modeLabel(pl.fm_mode || "FM");
          $("swr-plan").textContent += (pl.power_w ? " ; " + I18N.t("swrui.plan_power_mode", { power: pl.power_w + " W", mode: mode }) : " " + I18N.t("swrui.plan_mode", { mode: mode })) +
            (skipped ? " ; " + I18N.t("swrui.plan_skipped", { n: skipped }) : "") +
            " ; " + I18N.t("swrui.plan_duration", { s: Math.round(pl.estimated_s) }) + (pl.calibration_needed ? " " + I18N.t("swrui.plan_calibration") : "");
          $("swr-power").max = String(pl.max_power_pct);
        }).catch(() => {});
      }, 300);
      return { range: range, plan: p, points: points };
    }
    function drawSwrChart(ctx, x0, y0, w, h, points, ratio) {
      /* Barres verticales : vert <= 1,5, orange <= 2, rouge au-dessus ; échelle non linéaire plafonnée à 5 ; lignes 1,2 à 2. */
      const axis = 34 * ratio, bottom = 18 * ratio, top = 10 * ratio;
      const plotX = x0 + axis, plotW = w - axis, plotH = h - bottom - top, baseY = y0 + top + plotH;
      const yOf = (swr) => baseY - sw.scaleY(swr) * plotH;
      ctx.font = Math.round(10 * ratio) + "px sans-serif";  // i18n-ok (police)
      for (const g of sw.GRID.concat([3, 5])) {
        ctx.strokeStyle = g === 2 || g === 5 ? sw.COLORS.gridStrong : sw.COLORS.grid; ctx.lineWidth = Math.max(1, ratio);
        ctx.beginPath(); ctx.moveTo(plotX, yOf(g)); ctx.lineTo(x0 + w, yOf(g)); ctx.stroke();
        ctx.fillStyle = sw.COLORS.text; ctx.fillText(sw.swrText(g).replace(",00", ""), x0 + 2 * ratio, yOf(g) + 3 * ratio);
      }
      const n = points.length || 1, slot = plotW / n, bar = Math.max(2 * ratio, slot * 0.7);
      const measured = points.filter((p) => p.swr !== null && p.swr !== undefined);
      const best = measured.length ? measured.reduce((a, b) => (b.swr < a.swr ? b : a)) : null;
      const every = Math.max(1, Math.ceil(n * 52 * ratio / plotW));
      points.forEach((p, i) => {
        const x = plotX + i * slot + (slot - bar) / 2;
        const hasValue = p.swr !== null && p.swr !== undefined;
        const yTop = hasValue ? Math.min(baseY - 2 * ratio, yOf(p.swr)) : baseY - 4 * ratio;
        ctx.globalAlpha = p.status === "reduced" ? 0.5 : 1;
        ctx.fillStyle = sw.pointColor(p); ctx.fillRect(x, yTop, bar, baseY - yTop);
        ctx.globalAlpha = 1;
        if (best && p === best) { ctx.strokeStyle = sw.COLORS.accent; ctx.lineWidth = 2 * ratio; ctx.strokeRect(x, yTop, bar, baseY - yTop); }
        if (hasValue && n <= 24) { ctx.fillStyle = sw.COLORS.text; ctx.fillText(sw.swrText(p.swr), x, yTop - 3 * ratio); }
        if (i % every === 0) { ctx.fillStyle = sw.COLORS.text; ctx.fillText(sw.freqLabel(p.hz), x, baseY + 13 * ratio); }
      });
    }
    function paintSwrChart(points) {
      const cv = $("swr-chart");
      if (!cv.getContext) return;
      const ratio = window.devicePixelRatio || 1;
      cv.width = Math.max(1, Math.round((cv.clientWidth || 600) * ratio)); cv.height = Math.max(1, Math.round((cv.clientHeight || 224) * ratio));
      const ctx = cv.getContext("2d");
      ctx.fillStyle = sw.COLORS.background; ctx.fillRect(0, 0, cv.width, cv.height);
      drawSwrChart(ctx, 0, 0, cv.width, cv.height, points || [], ratio);
    }
    function showSwrRestored(result) {
      const r = sw.restoredLines(result, web.modeLabel);
      $("swr-restored").textContent = ""; $("swr-differences").textContent = "";
      for (const line of r.lines) $("swr-restored").appendChild(el("li", "", line));
      for (const line of r.differences) $("swr-differences").appendChild(el("li", "", line));
      $("swr-dialog").hidden = false;
    }
    function swrSummary(result) {
      const best = result && result.best;
      const why = result && result.reason !== "done" ? " " + I18N.t("swrui.summary_cut", { why: web.cutText(result.detail) }) : "";
      return (best ? I18N.t("swrui.summary_best", { swr: sw.swrText(best.swr), mhz: sw.freqLabel(best.hz) }) : I18N.t("swrui.summary_none")) + why +
        (result && result.warning === "swr_unstable" ? " " + I18N.t("swrui.summary_unstable") : "");
    }
    function onSwr(msg) {
      swrRunning = !["done", "cut", "failed", "cancelled"].includes(msg.state);
      $("swr-cancel").hidden = !swrRunning;
      const names = { preparing: "swrscreen.preparing", calibrating: "swrscreen.calibrating", restoring: "swrscreen.restoring" };
      $("swr-progress").textContent = names[msg.state] ? I18N.t(names[msg.state]) :
        (msg.state === "measuring" ? I18N.t("swrscreen.measuring", { done: (msg.points || []).filter((p) => p.swr !== null && p.swr !== undefined).length, total: msg.total }) : "");
      paintSwrChart(msg.points);
      if (msg.result) {
        swrResult = msg.result;
        $("swr-summary").textContent = swrSummary(msg.result);
        $("swr-export").hidden = false;
        swrDialogShownFor = msg.result;
        showSwrRestored(msg.result);                                                  // l'opérateur voit ce qui a été remis
      }
      if (lastView) swrPlanText();
    }
    function paintSwr(v) {
      const offered = swrOffered() && !v.listener;
      $("sec-swr").hidden = !offered;
      if (!offered) return;
      if (swrSeenFor !== client.hello) {                                               // une fois par connexion : derniers choix et dernière mesure
        swrSeenFor = client.hello;
        client.swrLast().then((res) => {
          if (!res || !res.ok) return;
          if (res.choices) { $("swr-points").value = String(res.choices.points); $("swr-power").value = String(res.choices.power_pct); }
          if (res.last && !swrResult) { swrResult = res.last; paintSwrChart(res.last.points); $("swr-summary").textContent = swrSummary(res.last); $("swr-export").hidden = false; }
          swrPlanText();
        }).catch(() => {});
      }
      if ($("sec-swr").open) swrPlanText();
    }
    async function swrImage() {
      /* Image ANONYME à partager : graphique, nom de la mesure, date, puissance, mode ; logo et www.rf-diy.com. */
      if (!swrResult) return null;
      if (!swrName) swrName = (window.prompt(I18N.t("ui.swr_name_prompt"), "") || "").trim();
      const W = 1200, H = 760, cv = document.createElement("canvas");
      cv.width = W; cv.height = H;
      const ctx = cv.getContext("2d");
      ctx.fillStyle = sw.COLORS.background; ctx.fillRect(0, 0, W, H);
      const legend = sw.legendLines(swrResult, swrName, web.modeLabel, new Date(swrResult.at ? swrResult.at * 1000 : Date.now()).toLocaleString());
      ctx.fillStyle = sw.COLORS.title; ctx.font = "bold 34px sans-serif"; ctx.fillText(legend[0], 40, 56);  // i18n-ok (police)
      drawSwrChart(ctx, 30, 80, W - 60, 520, swrResult.points || [], 2);
      ctx.fillStyle = sw.COLORS.text; ctx.font = "22px sans-serif";  // i18n-ok (police)
      if (legend[1]) ctx.fillText(legend[1], 40, 650);
      const logo = await new Promise((resolve) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = () => resolve(null); img.src = "logo-96.png"; });
      if (logo) ctx.drawImage(logo, 40, 676, 64, 64);
      ctx.fillStyle = sw.COLORS.accent; ctx.font = "bold 24px sans-serif"; ctx.fillText("www.rf-diy.com", 118, 718);  // i18n-ok (police)
      return await new Promise((resolve) => cv.toBlob(resolve, "image/png"));
    }
    const swrFileName = () => "tos-" + (swrName || "mesure").replace(/[^\w.-]+/g, "_").slice(0, 40) + ".png";
    $("swr-use-band").addEventListener("change", swrPlanText);
    $("swr-use-center").addEventListener("change", swrPlanText);
    for (const id of ["swr-center", "swr-width", "swr-points", "swr-power"]) $(id).addEventListener("input", swrPlanText);
    $("sec-swr").addEventListener("toggle", () => {
      if ($("sec-swr").open) { swrPlanText(); if (swrResult) paintSwrChart(swrResult.points); }
      else if (swrResult && swrDialogShownFor !== swrResult) { swrDialogShownFor = swrResult; showSwrRestored(swrResult); }   // en quittant la mesure
    });
    $("swr-start").addEventListener("click", () => {
      const p = swrPlanText();
      if (!p) return;
      if (!p.plan.amateurOnly && !window.confirm(I18N.t("ui.swr_outside_confirm"))) return;
      swrName = ""; swrResult = null; $("swr-export").hidden = true; $("swr-summary").textContent = "";
      swrRunning = true; $("swr-start").disabled = true;
      client.swrStart(p.range.lowHz, p.range.highHz, p.points, Number($("swr-power").value)).then((res) => {
        if (!res || !res.ok) { swrRunning = false; swrPlanText(); }
      }).catch((e) => { swrRunning = false; fail(e); });
    });
    $("swr-cancel").addEventListener("click", () => client.swrCancel().catch(fail));
    $("swr-dialog-close").addEventListener("click", () => { $("swr-dialog").hidden = true; });
    $("swr-restored-open").addEventListener("click", () => { if (swrResult) showSwrRestored(swrResult); });
    $("swr-save").addEventListener("click", async () => {
      try {
        const blob = await swrImage();
        if (!blob) return;
        if (window.showSaveFilePicker) {                                               // Chrome, Edge : choix du dossier et du nom
          const handle = await window.showSaveFilePicker({ suggestedName: swrFileName(), types: [{ description: I18N.t("ui.png_image"), accept: { "image/png": [".png"] } }] });
          const out = await handle.createWritable(); await out.write(blob); await out.close();
        } else {
          const link = el("a", ""); link.href = URL.createObjectURL(blob); link.download = swrFileName(); link.click();
          window.setTimeout(() => URL.revokeObjectURL(link.href), 5000);
        }
        ui.log(I18N.t("ui.swr_image_saved"), "");
      } catch (e) { if (!(e && e.name === "AbortError")) fail(e); }
    });
    $("swr-share").addEventListener("click", async () => {
      try {
        const blob = await swrImage();
        if (blob) await navigator.share({ files: [new File([blob], swrFileName(), { type: "image/png" })], title: swrName || I18N.t("swrscreen.title") });
      } catch (e) { if (!(e && e.name === "AbortError")) fail(e); }
    });
    $("swr-copy").addEventListener("click", async () => {
      try {
        const blob = await swrImage();
        if (blob) { await navigator.clipboard.write([new window.ClipboardItem({ "image/png": blob })]); ui.log(I18N.t("ui.image_copied"), ""); }
      } catch (e) { fail(e); }
    });
    try {                                                                              // boutons selon ce que sait le navigateur
      const probe = typeof File !== "undefined" ? new File([""], "x.png", { type: "image/png" }) : null;
      $("swr-share").hidden = !(probe && navigator.canShare && navigator.canShare({ files: [probe] }));
      $("swr-copy").hidden = !(navigator.clipboard && navigator.clipboard.write && window.ClipboardItem);
    } catch (e) { /* navigateur sans partage ni presse-papiers d'images */ }

    // ---- rediffusion d'un enregistrement de l'audio reçu (accordée par la station : hello.replay ; comme l'application)
    let replayBuf = null, replayRec = null, replayTimer = null, replayPending = 0, replayPlaying = false;
    function replayMax() {
      const r = client.hello && client.hello.replay;
      return r && r.max_s > 0 && !(lastView && lastView.listener) ? r.max_s : 0;
    }
    function replayRender() {
      const max = replayMax();
      $("sec-replay").hidden = !max || !vx;
      $("replay-banner").hidden = !(replayPlaying || replayPending);
      $("replay-banner").textContent = replayPlaying ? I18N.t("ui.replay_playing") : I18N.t("rigparts.replay_pending");
      if (!max) return;
      const tx = !!(lastView && lastView.pttState && lastView.pttState !== "RX");
      const armed = !!(lastView && lastView.armed && lastView.connected);
      $("replay-max").textContent = String(max);
      $("replay-record").textContent = replayRec ? I18N.t("common.stop") : I18N.t("voicescreen.record");
      $("replay-record").disabled = tx || replayPlaying || !!replayPending || !rxMedia || typeof MediaRecorder === "undefined";
      $("replay-send").disabled = !replayBuf || !!replayRec || tx || replayPlaying || !!replayPending || !armed || !voiceChain;
      $("replay-hint").hidden = armed;
      $("replay-status").textContent = replayRec ? I18N.t("ui.replay_recording", { max: max })
        : replayPlaying ? I18N.t("ui.replay_sending") : replayPending ? I18N.t("voicescreen.replay_pending")
        : replayBuf ? I18N.t("voicescreen.replay_recorded", { seconds: replayBuf.duration.toFixed(1).replace(".", ",") }) : I18N.t("voicescreen.replay_empty");
    }
    function replayOnTx(on) {
      /* Émission confirmée de CETTE page (client.js -> chaîne de voix) : la diffusion demandée commence ; fin = arrêt net. */
      if (on) {
        if (replayRec) replayRec.stop();
        if (replayPending && Date.now() - replayPending <= 5000 && replayBuf && voiceChain) {
          replayPending = 0;
          replayPlaying = voiceChain.replayBuffer(replayBuf, () => {        // fin de l'enregistrement : fin d'émission (STOP)  // i18n-ok
            replayPlaying = false; replayRender();
            client.stop().catch(fail);
          });
        }
      } else {
        replayPending = 0; replayPlaying = false;
      }
      replayRender();
    }
    $("replay-record").addEventListener("click", () => {
      if (replayRec) { replayRec.stop(); return; }
      if (!rxMedia || typeof MediaRecorder === "undefined" || !replayMax()) return;
      const chunks = [];
      try { replayRec = new MediaRecorder(new MediaStream(rxMedia.getAudioTracks())); } catch (e) { replayRec = null; fail(e); return; }
      replayRec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      replayRec.onstop = () => {
        replayRec = null;
        if (replayTimer !== null) { window.clearTimeout(replayTimer); replayTimer = null; }
        const ctx = voiceCtx;
        if (ctx && chunks.length) {
          new Blob(chunks).arrayBuffer().then((data) => ctx.decodeAudioData(data))
            .then((buffer) => { replayBuf = buffer; replayRender(); })
            .catch((e) => ui.log(I18N.t("ui.recording_unreadable", { error: e.message }), "warn"));
        }
        replayRender();
      };
      replayRec.start();
      replayTimer = window.setTimeout(() => { if (replayRec) replayRec.stop(); }, replayMax() * 1000);   // TOT - 5 s au plus
      replayRender();
    });
    $("replay-send").addEventListener("click", () => {
      if (!replayBuf || !voiceChain) return;
      replayPending = Date.now();
      replayRender();
      window.setTimeout(() => { if (replayPending && !replayPlaying) { replayPending = 0; replayRender(); } }, 5000);
      client.pressPtt().catch(fail);                                       // émission NORMALE (mêmes règles que le PTT)
      try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) { /* défilement indisponible */ }   // retour au poste
    });

    // ---- santé de la machine de la station (state.host) et synthèse du matériel (host_info), opérateurs seulement
    function paintHost(v) {
      const h = v.connected ? v.host : null;
      $("host-bar").hidden = $("host-open").hidden = !h;
      if (!h) return;
      $("host-bar").className = "hostbar listener-hide" + (h.level !== "ok" ? " " + h.level : "");  // i18n-ok (classes CSS)
      $("host-fill").style.height = Math.round(h.fraction * 100) + "%";
      $("host-bar").title = h.title;
    }
    function showHostInfo() {
      const box = $("host-sections");
      box.textContent = I18N.t("hostviews.reading");
      $("host-dialog").hidden = false;
      client.hostInfo().then((sections) => {
        box.textContent = "";
        if (!sections) { box.textContent = I18N.t("hostviews.unavailable"); return; }
        for (const section of sections) {
          box.appendChild(el("h4", "", String(section.title || "")));
          const table = el("table", "");
          for (const row of Array.isArray(section.rows) ? section.rows : []) {
            const tr = el("tr", "");
            tr.appendChild(el("td", "", String(row[0]))); tr.appendChild(el("td", "", String(row[1])));
            table.appendChild(tr);
          }
          box.appendChild(table);
        }
      }).catch((err) => { box.textContent = I18N.t("ui.host_failed", { error: err.message }); });
    }
    $("host-bar").addEventListener("click", showHostInfo);
    $("host-open").addEventListener("click", showHostInfo);
    $("host-refresh").addEventListener("click", showHostInfo);
    $("host-close").addEventListener("click", () => { $("host-dialog").hidden = true; });
    $("presence").addEventListener("click", () => { presenceOpen = true; renderPresenceList(); $("presence-dialog").hidden = false; });
    $("presence-close").addEventListener("click", () => { presenceOpen = false; $("presence-dialog").hidden = true; });
    $("presence-reopen").addEventListener("click", () => client.reopenListeners().catch(fail));

    // ---- sonde de qualité réseau : indicateur de l'en-tête, détail (accordéon), statistiques et seuils (opérateurs)
    const np = root.TrxNetProbe || null;
    let netOpen = store.get("trx.netOpen", "0") === "1";
    let netLast = null, netKey = "", netModel = null;
    function netRows(table, rows, badFirst) {
      table.textContent = "";
      rows.forEach((row, i) => {
        const tr = el("tr", badFirst && i === 0 ? "bad" : "");
        tr.appendChild(el("td", "", String(row[0]))); tr.appendChild(el("td", "", String(row[1])));
        table.appendChild(tr);
      });
    }
    function paintNetDetail(n) {
      $("net-detail").hidden = !(n && netOpen);
      if (!n || !netOpen) return;
      const key = JSON.stringify([n.rows, n.probes, n.vpn, n.thresholds]);
      if (key === netKey) return;                                          // rien de changé : boutons gardés sous le doigt
      netKey = key;
      netRows($("net-rows"), n.probes.length ? n.rows.concat([[I18N.t("netviews.station_probes"), ""]], n.probes) : n.rows, n.outage);
      const box = $("net-vpn");
      box.textContent = "";
      for (const w of n.vpn) {
        const div = el("div", "alert warn", w.text + " ");  // i18n-ok (classes CSS)
        const skip = el("button", "chip", I18N.t("netviews.ignore_address"));
        skip.addEventListener("click", () => client.netVpnIgnore(w.address).catch(fail));
        div.appendChild(skip);
        box.appendChild(div);
      }
      $("net-thresholds").textContent = n.thresholds;
    }
    function paintNet(v) {
      const n = v.connected ? v.net : null;
      netLast = n;
      const bar = $("net-bar");
      bar.hidden = !n;
      $("sec-net").hidden = !n || client.isListener();
      if (!n) { $("net-detail").hidden = true; netKey = ""; return; }
      bar.className = "netbar " + n.level + (n.outage ? " outage" : "");
      Array.from(bar.children).forEach((b, i) => { b.className = i < n.bars ? "on" : ""; });
      bar.title = n.title;
      paintNetDetail(n);
    }
    function setNetOpen(on) {
      netOpen = on;
      store.set("trx.netOpen", on ? "1" : "0");
      netKey = "";
      paintNetDetail(netLast);
    }
    for (let i = 0; i < 3; i++) $("net-bar").appendChild(el("i", ""));      // trois barres : niveau lisible sans la couleur
    $("net-bar").addEventListener("click", () => setNetOpen(!netOpen));
    $("net-detail-close").addEventListener("click", () => setNetOpen(false));
    $("net-stats-open").addEventListener("click", () => {
      $("sec-net").open = true;
      $("sec-net").scrollIntoView({ block: "start" });
      loadNetStats();
    });

    function netBarRow(box, label, fraction, value, title) {
      const row = el("div", "nb-row");
      row.title = title || "";
      row.appendChild(el("span", "nb-label", label));
      const track = el("div", "nb-track"), fill = el("div", "nb-fill");
      fill.style.width = Math.round(Math.max(0, Math.min(1, fraction)) * 100) + "%";
      track.appendChild(fill);
      const right = el("div", "");
      right.appendChild(track);
      right.appendChild(el("span", "nb-value", value));
      row.appendChild(right);
      box.appendChild(row);
    }
    function renderNetStats(m) {
      $("net-view").hidden = !m;
      if (!m) return;
      netRows($("net-summary"), m.summary);
      const days = $("net-days-chart");
      days.textContent = "";
      if (!m.days.length) days.appendChild(el("p", "note", I18N.t("netviews.no_measure_period")));
      for (const d of m.days) netBarRow(days, d.date, d.fraction, d.short, I18N.t("ui.net_day_title", { date: d.date, outages: d.outages, detail: d.detail }));
      const heat = $("net-heat");
      heat.textContent = "";
      heat.appendChild(el("b", "", ""));
      for (let h = 0; h < 24; h++) heat.appendChild(el("b", "", h % 6 === 0 ? String(h) : ""));
      for (const d of m.days) {
        heat.appendChild(el("b", "", d.date.slice(5)));
        d.hours.forEach((cell, h) => {
          const c = el("span", cell.n ? "" : "zero");
          if (cell.n) c.style.opacity = String(0.25 + 0.75 * cell.fraction);
          c.title = I18N.t("ui.net_hour_title", { date: d.date, hour: h, n: cell.n });
          heat.appendChild(c);
        });
      }
      const diag = $("net-diag");
      diag.textContent = "";
      if (!m.diagnoses.length) diag.appendChild(el("p", "note", I18N.t("netviews.no_outage")));
      for (const d of m.diagnoses) netBarRow(diag, d.label, d.fraction, d.count + " (" + Math.round(d.fraction * 100) + " %)", d.label);
      netRows($("net-types"), m.types.length ? m.types : [["—", I18N.t("netviews.no_measure")]]);
      const list = $("net-outages");
      list.textContent = "";
      for (const o of m.outages) {
        list.appendChild(el("li", "", new Date(o.when).toLocaleString() + " — " + o.duration + " — " + o.diagnosis +
          (o.agent ? " — " + o.agent : "") + (o.net ? " (" + o.net + ")" : "") + " — " + o.kind + (o.basis ? I18N.t("netviews.based_on", { basis: o.basis }) : "")));
      }
      if (!m.outages.length) list.appendChild(el("li", "", I18N.t("netviews.no_outage_period")));
      const select = $("net-device"), keep = select.value;
      select.textContent = "";
      select.appendChild(el("option", "", I18N.t("ui.net_all_devices")));
      select.firstChild.value = "";
      for (const d of m.devices) {
        const o = el("option", "", (d.agent || I18N.t("ui.net_device")) + " (" + String(d.device).slice(0, 4) + ")");
        o.value = d.device;
        select.appendChild(o);
      }
      select.value = keep;
      renderNetThresholds(m);
    }
    function renderNetThresholds(m) {
      const box = $("net-thr");
      box.textContent = "";
      if (!m.thresholds.length) { box.appendChild(el("p", "note", I18N.t("netviews.no_thresholds"))); return; }
      for (const t of m.thresholds) {
        const card = el("div", "net-thr-type");
        card.appendChild(el("strong", "", I18N.t(t.chosen ? "netviews.chosen" : "netviews.from_toml", { label: t.label })));
        const p = t.proposed || {};
        const proposal = p.rtt || p.loss
          ? I18N.t("netviews.proposed", { list: (p.rtt ? I18N.t("netviews.proposed_rtt", { warn: p.rtt.warn, alert: p.rtt.alert }) : "") +
            (p.rtt && p.loss ? ", " : "") + (p.loss ? I18N.t("netviews.proposed_loss", { warn: p.loss.warn, alert: p.loss.alert + " %" }) : "") })
          : I18N.t("netviews.no_proposal", { days: t.days });
        card.appendChild(el("p", "note", proposal));
        const values = { rtt_warn: t.inForce.rtt_warn, rtt_alert: t.inForce.rtt_alert, loss_warn: t.inForce.loss_warn, loss_alert: t.inForce.loss_alert };
        const result = el("p", "note", "");
        const simulate = () => {
          if (!np) return;
          const r = np.simulate(t.rttHist, m.edges.rtt_ms, values.rtt_warn, values.rtt_alert);
          const l = np.simulate(t.lossHist, m.edges.loss_pct, values.loss_warn, values.loss_alert);
          const pct = (x) => (x === null ? "—" : String(x).replace(".", ",") + " %");
          result.textContent = I18N.t("netui.simulation", { rtt_orange: pct(r.orange_pct), rtt_red: pct(r.red_pct), degraded_red: pct(r.degraded_red_pct),
            degraded_green: pct(r.degraded_green_pct), loss_orange: pct(l.orange_pct), loss_red: pct(l.red_pct) });
        };
        const inputs = {};
        const slider = (key, label, min, max, step, unit) => {
          const row = el("label", "");
          row.appendChild(el("span", "", label));
          const input = document.createElement("input");
          input.type = "range"; input.min = min; input.max = max; input.step = step; input.value = values[key];
          const out = el("span", "", values[key] + " " + unit);
          input.addEventListener("input", () => { values[key] = Number(input.value); out.textContent = input.value + " " + unit; simulate(); });
          inputs[key] = { input: input, out: out, unit: unit };
          row.appendChild(input); row.appendChild(out);
          card.appendChild(row);
        };
        slider("rtt_warn", I18N.t("netviews.rtt_orange"), 50, 1500, 50, "ms");
        slider("rtt_alert", I18N.t("netviews.rtt_red"), 100, 3000, 50, "ms");
        slider("loss_warn", I18N.t("netviews.loss_orange"), 0.5, 20, 0.5, "%");
        slider("loss_alert", I18N.t("netviews.loss_red"), 1, 50, 1, "%");
        card.appendChild(result);
        simulate();
        const row = el("div", "row");
        if (p.rtt || p.loss) {
          const take = el("button", "chip", I18N.t("netviews.take_proposal"));
          take.addEventListener("click", () => {
            const pick = { rtt_warn: p.rtt && p.rtt.warn, rtt_alert: p.rtt && p.rtt.alert, loss_warn: p.loss && p.loss.warn, loss_alert: p.loss && p.loss.alert };
            for (const [key, value] of Object.entries(pick)) {
              if (!Number.isFinite(value) || !inputs[key]) continue;
              values[key] = value; inputs[key].input.value = value; inputs[key].out.textContent = value + " " + inputs[key].unit;
            }
            simulate();
          });
          row.appendChild(take);
        }
        const apply = el("button", "chip", I18N.t("netviews.apply"));
        apply.addEventListener("click", () => {
          if (values.rtt_warn >= values.rtt_alert || values.loss_warn >= values.loss_alert) {
            ui.log(I18N.t("ui.net_thresholds_order"), "warn");
            return;
          }
          client.netThresholds(Object.assign({ net_type: t.netType }, values)).then((res) => {
            ui.log(res && res.ok ? I18N.t("ui.net_thresholds_saved", { label: t.label }) : I18N.t("ui.net_thresholds_refused", { reason: web.reasonText(res && res.reason, res && res.detail, res && res.ort) }), res && res.ok ? "" : "warn");
            loadNetStats();
          }).catch(fail);
        });
        row.appendChild(apply);
        if (t.chosen) {
          const reset = el("button", "chip", I18N.t("ui.net_thresholds_reset"));
          reset.addEventListener("click", () => client.netThresholds({ net_type: t.netType, reset: true }).then(loadNetStats).catch(fail));
          row.appendChild(reset);
        }
        card.appendChild(row);
        box.appendChild(card);
      }
    }
    function loadNetStats() {
      $("net-status").textContent = I18N.t("rigsession.net_reading");
      client.netStats(Number($("net-days").value), $("net-device").value).then((res) => {
        if (!res || !res.ok) {
          $("net-status").textContent = I18N.t("rigsession.net_stats_refused", { detail: web.reasonText(res && res.reason, res && res.detail, res && res.ort) });
          return;
        }
        netModel = web.netStatsModel(res.stats);
        $("net-status").textContent = netModel ? ($("net-device").value ? I18N.t("ui.net_stats_device") : I18N.t("rigsession.net_stats_ok")) : I18N.t("rigsession.net_stats_unreadable");
        renderNetStats(netModel);
      }).catch((err) => { $("net-status").textContent = I18N.t("ui.read_failed", { error: err.message }); });
    }
    $("net-days").value = "30";                                            // 30 jours par défaut
    $("net-refresh").addEventListener("click", loadNetStats);
    $("net-days").addEventListener("change", loadNetStats);
    $("net-device").addEventListener("change", loadNetStats);
    $("sec-net").addEventListener("toggle", () => { if ($("sec-net").open) loadNetStats(); });
    $("net-clear").addEventListener("click", () => { $("net-clear-confirm").hidden = !$("net-clear-confirm").hidden; });
    $("net-export").addEventListener("click", () => {
      $("net-status").textContent = I18N.t("rigsession.net_exporting");
      client.netExport().then((res) => {
        if (res.error) { $("net-status").textContent = I18N.t("rigsession.net_export_refused", { detail: res.error }); return; }
        const link = el("a", "");
        link.href = URL.createObjectURL(new Blob([res.bytes], { type: "application/zip" }));
        link.download = res.name;
        link.click();
        $("net-status").textContent = I18N.t("ui.net_export_saved", { name: res.name });
      }).catch((err) => { $("net-status").textContent = I18N.t("rigsession.net_export_refused", { detail: err.message }); });
    });
    $("net-clear-confirm").addEventListener("click", () => {
      $("net-clear-confirm").hidden = true;
      client.netClear().then((res) => {
        ui.log(res && res.ok ? I18N.t("rigsession.net_cleared") : I18N.t("ui.net_clear_refused", { reason: web.reasonText(res && res.reason, res && res.detail, res && res.ort) }), res && res.ok ? "" : "warn");
        loadNetStats();
      }).catch(fail);
    });

    const ui = {
      status(text, kind) { const b = $("status"); b.textContent = text; b.className = "badge" + (kind ? " " + kind : ""); },
      log(text, level) {
        const li = el("li", level || "", new Date().toLocaleTimeString() + "  " + text);
        logList.insertBefore(li, logList.firstChild);
        while (logList.children.length > 50) logList.removeChild(logList.lastChild);
      },
      power(view) {
        renderPower(view);
      },
      swr(msg) {
        onSwr(msg);
      },
      netEvent(msg) {                                          // sonde réseau : coupure diagnostiquée, profil VPN partagé
        if (msg.event === "outage" && msg.outage) {
          const o = msg.outage;
          const outage = { duration: web.netDuration((o.duration_ms || 0) / 1000), agent: o.agent,
                           diagnosis: web.NET_DIAGNOSES[o.diagnosis] || I18N.t("rigsession.net_diagnosis_unknown") };
          ui.log(I18N.t(o.agent ? "rigsession.net_outage_agent" : "rigsession.net_outage", outage), "warn");
        } else if (msg.event === "vpn_shared" && msg.warning) {
          ui.log(web.vpnText(msg.warning), "bad");
        }
        if (netModel && $("sec-net").open) loadNetStats();
      },
      spectrum(frame) {
        hfCalibrate(frame);
        if (hfVisible) hfDraw(frame);
        if (miniActive()) miniDraw(frame);
      },
      remoteStream(stream, track) {
        const media = stream || new MediaStream([track]);
        rxMedia = media;
        audio.srcObject = rxStream(media);                                          // débrouillage et spatialisation éventuels
        setupAnalysis(media);
        applyOutput().finally(() => audio.play().catch(() => ui.log(I18N.t("ui.audio_blocked"), "warn")));
      },
      stats(text) { statsText = text; showNet(); },
      diag(text) { $("diag").textContent = text + (audio.paused ? " · " + I18N.t("ui.diag_paused") : "") + (audio.muted ? " · " + I18N.t("ui.diag_muted") : ""); },
      rtt(ms) { rttText = I18N.t("ui.rtt_command", { ms: ms }); showNet(); },
      modes(list) {
        const ordered = orderModes(list);                                            // USB-D, LSB-D, FM-D, AM-D d'abord
        const select = $("mem-mode");
        select.textContent = "";
        for (const m of ordered) select.appendChild(Object.assign(el("option", "", modeLabel(m)), { value: m }));
        const box = $("mode-buttons");                                                // un bouton par mode : un appui change le mode
        box.textContent = ""; modeButtons.clear();
        for (const m of ordered) {
          const button = el("button", "chip", shortMode(m));
          button.title = modeLabel(m);
          button.disabled = true;
          button.addEventListener("click", () => client.setMode(m, 0).catch(fail));
          box.appendChild(button);
          modeButtons.set(m, button);
        }
        if (lastView) paintModes(lastView);
      },
      reconnecting(info) {                                                          // la zone de la fréquence cède la place à un grand texte coloré
        const banner = $("reconnect");
        const lost = !info.active && (info.outcome === "timeout" || info.outcome === "auth");
        banner.hidden = !(info.active || lost);
        $("freq").hidden = !banner.hidden;
        banner.className = "reconnect" + (lost ? " lost" : "");
        $("reconnect-cancel").hidden = !info.active;
        if (info.active) {
          $("reconnect-text").textContent = I18N.t("ui.reconnecting", { seconds: info.remainingS });
          $("reconnect-sub").textContent = (info.attempt ? I18N.t("ui.reconnect_attempt", { n: info.attempt }) : I18N.t("ui.reconnect_preparing")) + (info.lastError ? " · " + info.lastError : "");
        } else if (lost) {
          $("reconnect-text").textContent = I18N.t("ui.connection_lost");
          $("reconnect-sub").textContent = info.outcome === "auth" ? I18N.t("ui.credentials_refused") : I18N.t("rigsession.giveup_timeout", { seconds: info.seconds });
        }
      },
      memories(list) { renderMemories(list); },
      losses(list) { renderLosses(list); },
      lossRecorded() { /* l'écran se met à jour via losses(list) */ },
      linkAlert(kind) { playLinkAlert(kind); },
      spots(data) { onSpots(data); },
      beeps(settings) { renderBeeps(settings); },
      selcall(status, call) { renderSelcall(status); if (call) playSequence([[880, 120], [0, 40], [1320, 160]]); },
      rigNotice(event, text, level) {                // VOX coupé, coupleur, TOS élevé : bandeau fermé d'un toucher
        const box = $("rig-alert");
        box.textContent = text;
        box.className = "alert " + (level === "bad" || event === "swr_high" ? "bad" : "warn");
        box.hidden = false;
        box.onclick = () => { box.hidden = true; };
        if (event === "swr_high") playSequence([[880, 150], [0, 80], [880, 150], [0, 80], [880, 150]]);
      },
      breizhEvent(entry, alarm) { bzhLogRender(); if (alarm) playSequence([[660, 120], [0, 60], [440, 200]]); },   // repli pendant MON émission
      friends(view) { frRender(view); },                                       // présence de groupe : vue relue
      monitoring(view) { moRender(view); },                                    // monitoring inter-stations : vue relue
      sdrState(st) { sdrRender(st); },                                         // module SDR : état (opérateurs)
      sdrLine(data) { sdrDraw(data); },
      sdrSpots(data) { sdrOnSpots(data); },                                    // module Cluster : spots de la fenêtre du SDR                                        // module SDR : ligne de waterfall
      sdrStream(stream, track) { sdrAttach(stream, track); },                  // module SDR : son (seconde piste)
      freedvActivity() { fdvaRender(); },                                      // activité FreeDV (toutes les 10 s)
      recentSpots(data) { recentData = data; recentAt = Date.now(); renderRecent(); },
      clusterHealth(state) { onClusterHealth(state); },
      clusterStatus(data) { clusterData = data; clusterAt = performance.now(); renderCluster(); },
      armed(value) { $("armed").checked = value; },
      connected(value) {
        connectedFlag = value;
        langControl();
        if (!value) {                                                            // déconnecté : plus de mode visiteur ni de 🎧
          renderPresence({ listener: false, presence: null });
          bzhRender(null);                                                       // plus de rubrique ni de voyant Breizh
          difRender(null);                                                       // plus de rubrique ni d'indicateur DIFFUSION
          fdvRender(null);                                                       // plus de rubrique ni de voyant FreeDV
          fdvaRender();                                                          // plus de liste « Activité FreeDV »
          frRender(null);                                                        // plus de rubrique « Amis »
          sdrRender(null);                                                       // plus de rubrique « SDR »
          paintNet({ connected: false });                                        // plus d'indicateur de liaison
          presenceOpen = false; $("presence-dialog").hidden = true;
        }
        renderSelcall(value ? client.selcall : null);
        rcRender();                                                              // lien vers TRX Console (administrateurs)
        const version = value && client.hello ? versionLabel(client.hello.version) : "";
        $("version").textContent = version; $("version").hidden = !version;        // version de la station, à droite de « Connecté »
        if ($("bug-report") && !$("bug-report").hidden) $("bug-send").disabled = !value;   // « Envoyer à la station » : connecté seulement
        for (const id of ["armed", "ptt", "stop", "freq-set", "disconnect", "mem-add-current", "step-down", "step-up",
                          "alert-test"]) $(id).disabled = !value;     // essai des sons : une fois connecté, quand la page sait quelle sortie est le poste
        $("connect").disabled = value;
        if (value) { $("reconnect").hidden = true; $("freq").hidden = false; }      // reconnecté : la fréquence reprend sa place
        $("sec-connect").open = !value;                     // une fois connecté : la zone de connexion se replie
        if (value && lay && client.hello && client.hello.layouts) loadLayout();    // la station propose les mises en page personnalisées
        else if (value) { profile = null; renderLayout(true); }
        if (lay) layoutInfo(null);
        if (value) $("bottom").scrollTop = 0;               // et on repart du haut de la partie défilante
        if (!value) {
          closeForm(); $("squelch").disabled = true;
          for (const [, id] of CONTROLS) $(id).disabled = true;                          // plus de commande sans liaison
          for (const button of bandButtons.values()) button.disabled = true;
          for (const button of modeButtons.values()) button.disabled = true;
          $("local-banner").hidden = true; $("temp-banner").hidden = true; resetRelease(); closeControlDialog();
          $("power-banner").hidden = true; closeStopHold(); $("power-dialog").hidden = true;
          clusterData = null; renderCluster();                                        // plus de liaison : plus d'état des flux
          $("hf-cluster").hidden = $("hf-spots").hidden = $("hf-list").hidden = true;   // reviendront quand le module reparlera
          teardownAnalysis(); closeKeypad(); $("wf-tx").hidden = true;
          if (hfVisible) showZone("tx");
          if (spotBook) { spotBook.clear(); closeSpotCard(); closeSpotList(); drawSpots(); }
          renderBeeps(null);
        }
        syncDock();
      },
      state(v) {
        lastView = v;
        renderFrequency(v.frequencyHz);
        $("freq").className = "freq" + (v.frequencyPending ? " pending" : "") + (v.controlsLocked ? " locked" : "");
        for (const [key, button] of bandButtons) {
          button.className = "chip" + (v.band === key ? " on" : "");
          button.disabled = !v.connected || v.controlsLocked;
        }
        paintModes(v);
        paintVoyants(v);
        if (selStatus) paintSelcallSend();
        const local = v.local || { active: false };                                   // poste utilisé sur place
        $("local-banner").hidden = !local.active;
        if (local.active) {
          $("local-text").textContent = local.text;
          $("local-release").disabled = !v.connected || local.transmitting;          // jamais pendant l'émission au micro du poste
        } else if (releaseArmed) resetRelease();
        const temp = v.temp || { level: "" };                                        // température du poste
        $("temp-banner").hidden = !temp.level;
        $("temp-banner").className = "alert" + (temp.level === "hot" ? "" : " warn");
        $("temp-banner").textContent = temp.text;
        const rigPower = v.rigPower || { shown: false };                             // poste éteint (fonction « power »)
        $("power-banner").hidden = !rigPower.shown;
        if (rigPower.shown) {
          $("power-banner-text").textContent = rigPower.text;
          $("power-on").hidden = !rigPower.canPowerOn && rigPower.text !== I18N.t("power.banner_running");
          $("power-on").disabled = !rigPower.canPowerOn;
        }
        if (!String($("stop").className || "").includes("holding")) $("stop-sub").textContent = v.powerOffered ? I18N.t("powerviews.hold_power") : I18N.t("powerviews.hold_disconnect");
        const transmitting = v.pttState !== "RX";
        $("wf-tx").hidden = !(wfVisible && transmitting);
        hfState(v, transmitting);
        syncDock();
        $("wf-tx").textContent = "Po " + v.powerText + " · SWR " + (v.swr ? v.swr.text : "—") + " · ALC " + (v.alc ? v.alc.text : "—");
        $("mode-pill").textContent = v.modeShort;
        $("passband").textContent = v.passband;
        $("smeter-text").textContent = v.sText;
        $("smeter-mask").style.width = (100 - Math.round(v.sFraction * 100)) + "%";
        $("po-text").textContent = v.powerText;
        $("po-mask").style.width = (100 - Math.round((v.power || 0) * 100)) + "%";
        for (const [key, id] of CONTROLS) {
          const item = v.controls.find((c) => c.key === key), button = $(id);
          button.hidden = !item;
          button.disabled = !item || !v.connected || v.controlsLocked;                          // verrouillés pendant l'émission
          if (item) {
            button.textContent = item.label;
            button.className = "chip" + (item.on ? " on" : "");
          }
        }
        renderControlDialog(v);                                                      // fenêtre NR/NB/Notch : valeurs relues, verrou en émission
        const mark = $("sql-marker");
        mark.hidden = v.squelchMark === null;
        if (v.squelchMark !== null) mark.style.left = (v.squelchMark * 100).toFixed(1) + "%";   // repère du squelch sur l'échelle du S-mètre
        $("swr-text").textContent = v.swr ? v.swr.text : "—"; $("swr-mask").style.width = percentLeft(v.swr ? v.swr.fraction : 0);
        $("alc-text").textContent = v.alc ? v.alc.text : "—"; $("alc-mask").style.width = percentLeft(v.alc ? v.alc.fraction : 0);
        const squelch = $("squelch");
        squelch.disabled = !v.connected || v.squelch === null;
        if (v.squelch !== null && performance.now() - squelchTouched > 1500) {          // pas de saut pendant que le doigt règle
          squelch.value = String(Math.round(v.squelch * 100));
          $("squelch-text").textContent = squelchLabel(Math.round(v.squelch * 100));
        }
        if (v.squelch === null) $("squelch-text").textContent = "—";
        const clar = v.clarifier;                                                       // ΔTX ou RIT en service : curseur du décalage
        $("blk-clar").hidden = !clar;
        if (clar) {
          $("clar").disabled = !v.connected || v.pttState !== "RX";
          $("clar").min = String(-clar.max); $("clar").max = String(clar.max);
          $("clar").dataset.name = clar.name; $("clar-name").textContent = clar.label;
          if (performance.now() - clarTouched > 1500) {
            $("clar").value = String(clar.hz);
            $("clar-text").textContent = web.clarifierText(clar.hz);
          }
        }
        renderInstruments(v.instruments);
        markActive(v);
        $("rx-level").textContent = v.rxLevel; $("tx-level").textContent = v.txLevel;
        $("tx-holes").textContent = v.txHoles === null ? "—" : String(v.txHoles);
        $("tx-flag").hidden = v.pttState === "RX";
        const badge = $("ptt-state");
        badge.textContent = v.pttLabel + (v.mine || !v.owner ? "" : " (" + v.owner + ")");
        badge.className = "ptt-state " + (v.pttState === "RX" ? "rx" : v.mine ? "tx" : "other");
        $("tot").textContent = v.tot === null ? (v.lastCut ? I18N.t("rigparts.last_cut", { cut: v.lastCut }) : "")
          : I18N.t(v.totWarning ? "ui.tot_remaining_warning" : "ui.tot_remaining", { seconds: v.tot });
        $("owner").textContent = v.clients.length ? I18N.t("ui.clients_connected", { clients: v.clients.join(", ") }) : "";
        const faultBox = $("fault");
        faultBox.hidden = !v.fault;
        faultBox.textContent = v.fault ? I18N.t("ui.station_fault", { fault: v.fault }) : "";
        const ptt = $("ptt");
        ptt.textContent = v.mine ? I18N.t("ui.ptt_cut") : v.other ? I18N.t("ui.ptt_other", { owner: v.owner }) : "PTT";
        ptt.className = "ptt" + (v.mine ? " tx" : "");
        ptt.disabled = !v.connected || v.other || !!v.fault || (v.txBlocked && !v.mine);
        const hint = $("mode-hint");
        hint.hidden = !v.dataModeHint;
        hint.textContent = v.dataModeHint;
        renderPresence(v);
        paintHost(v);
        paintNet(v);
        bzhRender(v);
        difRender(v);
        fdvRender(v);
        fdvaRender();
        paintMini(v);
        voiceProfilesSync();
        paintSwr(v);
        replayRender();
      },
    };

    const client = new TrxClient(browserEnv(), ui);

    // ---- SELCALL (selcall.js) : squelch numérique de la station ; panneau seulement si la station l'offre
    const scx = root.TrxSelcall || null;
    let selStatus = null;
    function renderSelcall(status) {
      selStatus = status;
      const offered = !!scx && !!status && connectedFlag;
      $("sec-selcall").hidden = !offered;
      const ind = scx ? scx.indicator(offered ? status : null) : null;
      $("sel-ind").hidden = !ind;
      if (ind) { $("sel-ind").textContent = ind.text; $("sel-ind").className = "chip sel-ind" + (ind.open ? " open" : ""); }  // i18n-ok (classes CSS)
      if (!offered) return;
      const selState = scx.STATE_LABELS[status.state] || status.state;
      $("sel-state").textContent = status.code && status.state !== "disabled" ? I18N.t("selcallpanel.state_code", { state: selState, code: status.code })
        : I18N.t("selcallpanel.state", { state: selState });
      if (document.activeElement !== $("sel-code") && !$("sel-code").value) $("sel-code").value = status.code || "";
      if (document.activeElement !== $("sel-test-code") && !$("sel-test-code").value) $("sel-test-code").value = status.code || "";
      $("sel-tail").checked = !!status.send_on_tx_end;
      const calOffered = !!(client.hello && Array.isArray(client.hello.features) && client.hello.features.includes("selcall_calibrate"));
      $("sel-level-box").hidden = !calOffered;
      if (calOffered) {
        if (document.activeElement !== $("sel-level")) $("sel-level").value = status.tx_level_dbfs;
        $("sel-level-text").textContent = " " + String(status.tx_level_dbfs).replace(".", ",") + " dBFS";
        $("sel-calibration").textContent = status.calibration ? I18N.t("ui.sel_last_calibration", { calibration: status.calibration }) : "";
        $("sel-calibrate").disabled = !connectedFlag || !!status.sending || !(lastView && lastView.armed) || (lastView && lastView.pttState !== "RX");
      }
      paintSelcallSend();
      $("sel-rearm").disabled = status.state === "disabled";
      $("sel-deactivate").disabled = status.state === "disabled";
      $("sel-filter").value = status.filter_mode;
      $("sel-att").value = status.attenuation_db; $("sel-att-text").textContent = " " + status.attenuation_db + " dB";
      $("sel-att").disabled = status.filter_mode !== "attenuate";
      const box = $("sel-history");
      box.textContent = "";
      for (const code of status.history || []) {
        const chip = el("button", "chip" + (code === status.code && status.state !== "disabled" ? " on" : ""), code);
        chip.title = I18N.t("ui.sel_arm_on", { code: code });
        chip.addEventListener("click", () => client.selcallActivate(code).catch(fail));
        box.appendChild(chip);
      }
      const c = status.last_call;
      $("sel-last").textContent = c ? I18N.t("selcallpanel.last_call", { code: c.code, time: new Date(c.at * 1000).toLocaleTimeString("fr-FR"),
        delta: (c.delta_hz > 0 ? "+" : "") + c.delta_hz, snr: c.snr_db }) : I18N.t("selcallpanel.no_call");
    }
    function paintSelcallSend() {
      /* « Envoyer SELCALL » : devient « Annuler » pendant l'appel (progression 1/3...) ; une émission de ce client. */
      const st = selStatus, v = lastView;
      const sending = !!(st && st.sending) || !!(v && v.mine && v.pttState && v.pttState !== "RX" && selSendAsked);
      const button = $("sel-send");
      const offered = !!(client.hello && Array.isArray(client.hello.features) && client.hello.features.includes("selcall_send"));
      button.hidden = !offered; $("sel-tail-row").hidden = !offered;
      if (!offered) { $("sel-send-note").textContent = I18N.t("ui.sel_update_station"); return; }
      button.textContent = sending ? (st && st.sending ? I18N.t("selcallpanel.cancel_sending", { sending: st.sending }) : I18N.t("common.cancel")) : I18N.t("selcallpanel.send");
      button.className = sending ? "stop" : "primary";
      button.disabled = !connectedFlag || !st || (!sending && (st.state === "disabled" || !(v && v.armed) || (v && v.pttState !== "RX")));
      $("sel-send-note").textContent = !st || st.state === "disabled" ? I18N.t("ui.sel_arm_first")
        : !(v && v.armed) && !sending ? I18N.t("ui.sel_check_armed") : "";
      if (!sending && v && v.pttState === "RX") selSendAsked = false;
    }
    let selSendAsked = false;
    if (scx) {
      $("sel-send").addEventListener("click", () => {
        if ($("sel-send").className === "stop") { client.stop().catch(fail); return; }   // annuler = STOP, toujours permis
        selSendAsked = true;
        client.selcallSend().then((res) => { if (!res || !res.ok) selSendAsked = false; paintSelcallSend(); }).catch(fail);
      });
      $("sel-tail").addEventListener("change", (ev) => client.selcallOptions({ send_on_tx_end: ev.target.checked }).catch(fail));
      $("sel-level").addEventListener("change", (ev) => client.selcallOptions({ tx_level_dbfs: Number(ev.target.value) }).catch(fail));
      $("sel-calibrate").addEventListener("click", () => {
        selSendAsked = true;                                                      // même bouton « Annuler » pendant le réglage
        client.selcallCalibrate().then((res) => { if (!res || !res.ok) selSendAsked = false; paintSelcallSend(); }).catch(fail);
      });
      $("sel-ind").addEventListener("click", () => { $("sec-selcall").open = true; $("sec-selcall").scrollIntoView({ behavior: "smooth" }); });
      $("sel-activate").addEventListener("click", () => {
        const code = $("sel-code").value.trim();
        if (!scx.validCode(code)) { ui.log(I18N.t("rigsession.selcall_code_invalid"), "warn"); return; }
        client.selcallActivate(code).catch(fail);
      });
      $("sel-rearm").addEventListener("click", () => client.selcallRearm().catch(fail));
      $("sel-deactivate").addEventListener("click", () => client.selcallDeactivate().catch(fail));
      $("sel-filter").addEventListener("change", (ev) => client.selcallOptions({ filter_mode: ev.target.value }).catch(fail));
      $("sel-att").addEventListener("change", (ev) => client.selcallOptions({ attenuation_db: Number(ev.target.value) }).catch(fail));
      const testCode = () => {
        const code = $("sel-test-code").value.trim();
        if (!scx.validCode(code)) { ui.log(I18N.t("ui.sel_test_code_invalid"), "warn"); return null; }
        return code;
      };
      $("sel-test-save").addEventListener("click", () => {
        const code = testCode();
        if (!code) return;
        const link = el("a", "");
        link.href = URL.createObjectURL(new Blob([scx.testWav(code)], { type: "audio/wav" }));
        link.download = "selcall-" + code + ".wav";
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(link.href), 5000);
      });
      let testPlayer = null;
      $("sel-test-play").addEventListener("click", () => {
        const code = testCode();
        if (!code) return;
        if (testPlayer) { testPlayer.pause(); testPlayer = null; $("sel-test-play").textContent = I18N.t("selcallpanel.listen"); return; }
        testPlayer = new Audio(URL.createObjectURL(new Blob([scx.testWav(code)], { type: "audio/wav" })));   // ici seulement, jamais émis
        testPlayer.onended = () => { testPlayer = null; $("sel-test-play").textContent = I18N.t("selcallpanel.listen"); };
        $("sel-test-play").textContent = I18N.t("common.stop");
        testPlayer.play().catch(fail);
      });
    }

    // ---- profil du micro (traitements du navigateur) : mémorisé ; appliqué tout de suite si possible
    for (const [key, p] of Object.entries(web.MIC_PROFILES)) $("mic-profile").appendChild(Object.assign(el("option", "", p.label), { value: key }));
    $("mic-profile").value = web.MIC_PROFILES[store.get("trx.micprofile", "quiet")] ? store.get("trx.micprofile", "quiet") : "quiet";
    $("mic-echo").checked = store.get("trx.micecho", "1") !== "0";
    $("mic-noise").checked = store.get("trx.micnoise", "0") === "1";
    function micProfileChanged() {
      store.set("trx.micprofile", $("mic-profile").value);
      store.set("trx.micecho", $("mic-echo").checked ? "1" : "0");
      store.set("trx.micnoise", $("mic-noise").checked ? "1" : "0");
      $("mic-custom").hidden = $("mic-profile").value !== "custom";
      client.applyMicProfile($("mic-profile").value, { echo: $("mic-echo").checked, noise: $("mic-noise").checked });
    }
    $("mic-custom").hidden = $("mic-profile").value !== "custom";
    for (const id of ["mic-profile", "mic-echo", "mic-noise"]) $(id).addEventListener("change", micProfileChanged);

    // ---- égaliseur paramétrique et effets de voix (voice.js) : chaîne branchée sur le micro à la connexion
    const vx = root.TrxVoice || null;
    let voiceSettings = vx ? vx.validate(safeJson(store.get("trx.voice", "null"))) : null;
    let voiceChain = null, voiceCtx = null, voiceRaw = null, recorder = null, recordTimer = null, recordBuffer = null;
    function voiceSave() { store.set("trx.voice", JSON.stringify(voiceSettings)); if (voiceChain) voiceChain.apply(voiceSettings); voiceRender(); }
    function voiceTx() { return !!(lastView && lastView.mine && lastView.pttState && lastView.pttState !== "RX"); }
    const VOICE_FX_IDS = ["voice-on", "voice-preset", "voice-apply", "voice-hp", "voice-lp", "voice-chorus-on", "voice-chorus-type",
                          "voice-chorus-mix", "voice-chorus-rate", "voice-chorus-depth", "voice-reverb-on", "voice-reverb-type",
                          "voice-reverb-mix", "voice-reverb-time"];
    let voiceBzh = false;                                                   // dernier état rendu (Breizh coupe les effets)
    function voiceRender() {
      if (!vx) return;
      const s = voiceSettings;
      $("voice-gain").value = s.mic.gainDb; $("voice-gain-text").textContent = " " + (s.mic.gainDb > 0 ? "+" : "") + s.mic.gainDb + " dB";
      $("voice-gate-on").checked = s.mic.gateOn;
      $("voice-gate-db").value = s.mic.gateDb; $("voice-gate-db-text").textContent = " " + s.mic.gateDb + " dBFS";
      $("voice-gate-db").disabled = !s.mic.gateOn;
      const mark = $("voice-gate-mark");
      mark.hidden = !s.mic.gateOn;
      mark.style.left = Math.round((s.mic.gateDb + 80) / 80 * 100) + "%";
      // Voix par Breizh Audio Box : égaliseur et effets contournés => leurs commandes grisées (réglages gardés pour le
      // retour en direct : « Direct » ou repli) ; gain du micro et porte de bruit restent actifs
      const bzh = client.breizhEffectsOff(), on = s.enabled && !bzh;
      $("voice-direct").className = "chip voice-direct" + (on ? " on" : "");  // i18n-ok (classes CSS)
      $("voice-direct").textContent = on ? "EQ ON" : "EQ";
      $("voice-direct").disabled = bzh;
      $("voice-on").checked = on;
      for (const id of VOICE_FX_IDS) $(id).disabled = bzh;
      for (const row of bandRows) row.gain.disabled = row.hz.disabled = row.q.disabled = bzh;
      $("voice-hp").value = s.highpassHz; $("voice-hp-text").textContent = " " + s.highpassHz + " Hz";
      $("voice-lp").value = s.lowpassHz; $("voice-lp-text").textContent = " " + s.lowpassHz + " Hz";
      s.bands.forEach((b, i) => {
        const row = bandRows[i];
        row.gain.value = b.gainDb; row.gainText.textContent = (b.gainDb > 0 ? "+" : "") + b.gainDb + " dB";
        if (document.activeElement !== row.hz) row.hz.value = Math.round(b.hz);
        if (document.activeElement !== row.q) row.q.value = b.q;
      });
      $("voice-chorus-on").checked = s.chorus.on; $("voice-chorus-type").value = s.chorus.type;
      $("voice-chorus-mix").value = s.chorus.mix; $("voice-chorus-mix-text").textContent = " " + s.chorus.mix + " %";
      $("voice-chorus-rate").value = s.chorus.rateHz; $("voice-chorus-depth").value = s.chorus.depthMs;
      $("voice-reverb-on").checked = s.reverb.on; $("voice-reverb-type").value = s.reverb.type;
      $("voice-reverb-mix").value = s.reverb.mix; $("voice-reverb-mix-text").textContent = " " + s.reverb.mix + " %";
      $("voice-reverb-time").value = s.reverb.seconds; $("voice-reverb-time-text").textContent = " " + s.reverb.seconds + " s";
      const ready = !!voiceChain && !voiceTx();
      $("voice-monitor").disabled = !ready;
      if (!voiceChain || voiceTx()) $("voice-monitor").checked = false;
      $("voice-record").disabled = !ready || !voiceRaw || typeof MediaRecorder === "undefined";
      $("voice-play").disabled = !ready || !recordBuffer;
      $("voice-record").textContent = recorder ? I18N.t("ui.record_stop") : I18N.t("voicescreen.record");
      drawVoiceGraph();
      const hintBox = $("voice-hints");
      hintBox.textContent = "";
      for (const hint of vx.hints(s)) hintBox.appendChild(el("li", "", hint));
    }
    // ---- graphique « fun » de l'égaliseur (étape 102) : courbe de toute la chaîne, chaud = renforcé, froid = atténué
    function drawVoiceGraph() {
      const cv = $("voice-graph");
      if (!cv || !cv.getContext || !vx) return;
      const ratio = window.devicePixelRatio || 1;
      const W = Math.max(1, Math.round((cv.clientWidth || 320) * ratio)), H = Math.max(1, Math.round((cv.clientHeight || 150) * ratio));
      if (cv.width !== W) cv.width = W;
      if (cv.height !== H) cv.height = H;
      const g = cv.getContext("2d"), s = voiceSettings;
      const yOf = (db) => H * (vx.CURVE_MAX_DB - db) / (vx.CURVE_MAX_DB - vx.CURVE_MIN_DB);
      const xOf = (hz) => vx.curveX(hz) * (W - 1);
      g.fillStyle = canvasColors["--fond"]; g.fillRect(0, 0, W, H);
      g.fillStyle = vx.GRAPH.speech; g.fillRect(xOf(300), 0, xOf(3000) - xOf(300), H);                    // la parole
      g.fillStyle = vx.GRAPH.cut;                                                                          // coupé par les filtres
      g.fillRect(0, 0, xOf(s.highpassHz), H); g.fillRect(xOf(s.lowpassHz), 0, W - xOf(s.lowpassHz), H);
      g.strokeStyle = canvasColors["--spectre-grille"]; g.lineWidth = Math.max(1, ratio);
      for (const db of [12, 6, -6, -12, -18]) { g.beginPath(); g.moveTo(0, yOf(db)); g.lineTo(W, yOf(db)); g.stroke(); }
      for (const hz of [100, 300, 1000, 3000]) { g.beginPath(); g.moveTo(xOf(hz), 0); g.lineTo(xOf(hz), H); g.stroke(); }
      const points = vx.curve(s, Math.min(240, Math.max(60, Math.round(W / 3))));
      const zero = yOf(0), step = W / points.length + 1;
      for (const p of points) {                                                                          // remplissage coloré
        g.fillStyle = vx.fillColor(p.db);
        const y = yOf(p.db);
        g.fillRect(xOf(p.hz), Math.min(y, zero), step, Math.max(1, Math.abs(zero - y)));
      }
      g.strokeStyle = vx.GRAPH.line; g.lineWidth = 2 * ratio; g.beginPath();
      points.forEach((p, i) => { if (i === 0) g.moveTo(xOf(p.hz), yOf(p.db)); else g.lineTo(xOf(p.hz), yOf(p.db)); });
      g.stroke();
      s.bands.forEach((b, i) => {                                                                        // une pastille par bande
        const near = points.reduce((best, p) => (Math.abs(p.hz - b.hz) < Math.abs(best.hz - b.hz) ? p : best));
        g.fillStyle = vx.bandColor(i); g.beginPath(); g.arc(xOf(b.hz), yOf(near.db), 4.5 * ratio, 0, 2 * Math.PI); g.fill();
      });
      g.font = Math.round(11 * ratio) + "px sans-serif"; g.fillStyle = cssVar("--texte-secondaire") || vx.GRAPH.label;  // i18n-ok (police)
      for (const [hz, label] of [[100, "100"], [300, "300"], [1000, "1 k"], [3000, "3 k Hz"]]) g.fillText(label, xOf(hz) + 3 * ratio, H - 4 * ratio);  // i18n-ok (police, unités)
      for (const db of [12, -12]) g.fillText((db > 0 ? "+" : "") + db + " dB", 3 * ratio, yOf(db) - 3 * ratio);
      const badges = (s.chorus.on ? [I18N.t("voicescreen.graph_chorus")] : []).concat(s.reverb.on ? [I18N.t("voicescreen.graph_reverb")] : []);
      g.fillStyle = vx.GRAPH.badge;
      badges.forEach((text, i) => g.fillText(text, W - 80 * ratio, (16 + 15 * i) * ratio));
      if (!s.enabled) { g.fillStyle = vx.GRAPH.off; g.fillRect(0, 0, W, H); g.fillStyle = vx.GRAPH.offText; g.fillText(I18N.t("voicescreen.graph_off"), W / 2 - 22 * ratio, H / 2); }
    }
    // ---- profils de l'opérateur rangés sur la station (après Neutre, DX, Ragchew)
    let voiceProfilesFor = null;
    function voicePresetOptions() {
      const select = $("voice-preset"), keep = select.value;
      select.textContent = "";
      for (const [key, preset] of Object.entries(vx.PRESETS)) select.appendChild(Object.assign(el("option", "", preset.label), { value: key }));
      const mine = client.voiceProfileList || [];
      if (mine.length) select.appendChild(Object.assign(el("option", "", I18N.t("ui.voice_my_profiles")), { value: "", disabled: true }));
      mine.forEach((p) => select.appendChild(Object.assign(el("option", "", "★ " + p.name), { value: "user:" + p.name })));
      select.value = [...select.options].some((o) => o.value === keep) ? keep : Object.keys(vx.PRESETS)[0];
      voiceProfileButtons();
    }
    function voiceProfilesOffered() {
      return !!(client.hello && Array.isArray(client.hello.features) && client.hello.features.includes("voice_profiles") && client.connected);
    }
    function voiceProfileButtons() {
      const offered = voiceProfilesOffered();
      $("voice-profile-save").hidden = !offered;
      $("voice-profile-delete").hidden = !offered || !$("voice-preset").value.startsWith("user:");
    }
    function voiceProfilesSync() {
      /* Liste relue une fois par connexion (nouveau « hello »), si la station range des profils. */
      if (!vx) return;
      if (!voiceProfilesOffered()) { if (voiceProfilesFor !== null) { voiceProfilesFor = null; client.voiceProfileList = []; voicePresetOptions(); } return; }
      if (voiceProfilesFor === client.hello) return;
      voiceProfilesFor = client.hello;
      client.voiceProfiles().then(() => voicePresetOptions()).catch(() => {});
    }
    const bandRows = [];
    if (vx) {
      voicePresetOptions();
      for (const [key, t] of Object.entries(vx.CHORUS_TYPES)) $("voice-chorus-type").appendChild(Object.assign(el("option", "", t.label), { value: key }));
      for (const [key, t] of Object.entries(vx.REVERB_TYPES)) $("voice-reverb-type").appendChild(Object.assign(el("option", "", t.label), { value: key }));
      vx.BANDS_HZ.forEach((hz, i) => {
        const label = el("span", "", (hz >= 1000 ? (hz / 1000).toFixed(hz % 1000 ? 2 : 0).replace(".", ",") + " k" : hz + " Hz"));
        const gain = Object.assign(el("input", ""), { type: "range", min: String(-vx.GAIN_MAX_DB), max: String(vx.GAIN_MAX_DB), step: "1" });
        const gainText = el("span", "mono", "");
        const fz = Object.assign(el("input", ""), { type: "number", min: String(Math.round(hz / 1.5)), max: String(Math.round(hz * 1.5)), step: "10", title: I18N.t("ui.voice_band_hz") });
        const q = Object.assign(el("input", ""), { type: "number", min: "0.3", max: "8", step: "0.1", title: I18N.t("ui.voice_band_q") });
        gain.addEventListener("input", () => { voiceSettings.bands[i].gainDb = Number(gain.value); voiceSave(); });
        fz.addEventListener("change", () => { voiceSettings.bands[i].hz = Number(fz.value); voiceSettings = vx.validate(voiceSettings); voiceSave(); });
        q.addEventListener("change", () => { voiceSettings.bands[i].q = Number(q.value); voiceSettings = vx.validate(voiceSettings); voiceSave(); });
        for (const node of [label, gain, gainText, fz, q]) $("voice-bands").appendChild(node);
        bandRows.push({ gain, gainText, hz: fz, q });
      });
      const bind = (id, apply) => $(id).addEventListener("input", (ev) => { apply(ev.target); voiceSettings = vx.validate(voiceSettings); voiceSave(); });
      bind("voice-on", (t) => { voiceSettings.enabled = t.checked; });
      bind("voice-gain", (t) => { voiceSettings.mic.gainDb = Number(t.value); });
      bind("voice-gate-on", (t) => { voiceSettings.mic.gateOn = t.checked; });
      bind("voice-gate-db", (t) => { voiceSettings.mic.gateDb = Number(t.value); });
      // Niveau du micro (échelle -80..0 dBFS), seulement rubrique ouverte et micro branché
      window.setInterval(() => {
        if (!voiceChain || !$("sec-voice").open) { $("voice-level-text").textContent = "—"; $("voice-level-mask").style.width = "100%"; return; }
        const db = Math.max(-80, Math.min(0, voiceChain.micLevelDb()));
        $("voice-level-mask").style.width = percentLeft((db + 80) / 80);
        $("voice-level-text").textContent = Math.round(db) + " dB";
      }, 120);
      bind("voice-hp", (t) => { voiceSettings.highpassHz = Number(t.value); });
      bind("voice-lp", (t) => { voiceSettings.lowpassHz = Number(t.value); });
      bind("voice-chorus-on", (t) => { voiceSettings.chorus.on = t.checked; });
      bind("voice-chorus-type", (t) => { voiceSettings.chorus.type = t.value; });
      bind("voice-chorus-mix", (t) => { voiceSettings.chorus.mix = Number(t.value); });
      bind("voice-chorus-rate", (t) => { voiceSettings.chorus.rateHz = Number(t.value); });
      bind("voice-chorus-depth", (t) => { voiceSettings.chorus.depthMs = Number(t.value); });
      bind("voice-reverb-on", (t) => { voiceSettings.reverb.on = t.checked; });
      bind("voice-reverb-type", (t) => { voiceSettings.reverb.type = t.value; });
      bind("voice-reverb-mix", (t) => { voiceSettings.reverb.mix = Number(t.value); });
      bind("voice-reverb-time", (t) => { voiceSettings.reverb.seconds = Number(t.value); });
      $("voice-direct").addEventListener("click", () => { voiceSettings.enabled = !voiceSettings.enabled; voiceSave(); });
      $("voice-apply").addEventListener("click", () => {
        const choice = $("voice-preset").value;
        if (choice.startsWith("user:")) {
          const p = (client.voiceProfileList || []).find((x) => "user:" + x.name === choice);
          if (!p) return;
          voiceSettings = vx.validate(p.settings);
          ui.log(I18N.t("voicescreen.profile_applied", { name: p.name }), "");
        } else if (vx.PRESETS[choice]) {
          voiceSettings = vx.PRESETS[choice].make();
        }
        voiceSave();
      });
      $("voice-preset").addEventListener("change", voiceProfileButtons);
      $("voice-profile-save").addEventListener("click", () => {
        const current = $("voice-preset").value.startsWith("user:") ? $("voice-preset").value.slice(5) : "";
        const name = (window.prompt(I18N.t("ui.voice_profile_prompt"), current) || "").trim();
        if (!name) return;
        client.saveVoiceProfile(name, vx.validate(voiceSettings)).then((list) => {
          if (!list) return;
          voicePresetOptions(); $("voice-preset").value = "user:" + (list.find((p) => p.name.toLowerCase() === name.toLowerCase()) || { name }).name;
          voiceProfileButtons(); ui.log(I18N.t("ui.voice_profile_saved", { name: name }), "");
        }).catch(fail);
      });
      $("voice-profile-delete").addEventListener("click", () => {
        const name = $("voice-preset").value.slice(5);
        if (!name || !window.confirm(I18N.t("ui.voice_profile_delete_confirm", { name: name }))) return;
        client.deleteVoiceProfile(name).then((list) => {
          if (list) { voicePresetOptions(); ui.log(I18N.t("ui.voice_profile_deleted", { name: name }), ""); }
        }).catch(fail);
      });
      $("voice-export").addEventListener("click", () => {
        const link = el("a", "");
        link.href = URL.createObjectURL(new Blob([vx.exportJson(voiceSettings)], { type: "application/json" }));
        link.download = "voix-openremotetrx.json";
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(link.href), 5000);
      });
      $("voice-import").addEventListener("change", (ev) => {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;
        file.text().then((text) => { voiceSettings = vx.importJson(text); voiceSave(); ui.log(I18N.t("ui.voice_imported"), ""); })
          .catch((e) => ui.log(I18N.t("ui.voice_import_failed", { error: e.message }), "warn"))
          .finally(() => { ev.target.value = ""; });
      });
      $("voice-monitor").addEventListener("change", (ev) => {
        if (!voiceChain) { ev.target.checked = false; return; }
        ev.target.checked = voiceChain.setMonitor(ev.target.checked && !voiceTx());
      });
      $("voice-record").addEventListener("click", () => {
        if (recorder) { recorder.stop(); return; }
        if (!voiceRaw || voiceTx()) return;
        const chunks = [];
        try { recorder = new MediaRecorder(new MediaStream([voiceRaw])); } catch (e) { ui.log(I18N.t("ui.record_failed", { error: e.message }), "warn"); return; }
        recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
        recorder.onstop = () => {
          recorder = null;
          if (recordTimer !== null) { window.clearTimeout(recordTimer); recordTimer = null; }
          new Blob(chunks).arrayBuffer().then((data) => voiceCtx.decodeAudioData(data)).then((buffer) => {
            recordBuffer = buffer;
            $("voice-rec-text").textContent = I18N.t("ui.voice_take", { seconds: buffer.duration.toFixed(1).replace(".", ",") });
            voiceRender();
          }).catch((e) => { ui.log(I18N.t("ui.recording_unreadable", { error: e.message }), "warn"); voiceRender(); });
        };
        recorder.start();
        $("voice-rec-text").textContent = I18N.t("ui.voice_recording", { max: vx.RECORD_MAX_S });
        recordTimer = window.setTimeout(() => { if (recorder) recorder.stop(); }, vx.RECORD_MAX_S * 1000);
        voiceRender();
      });
      $("voice-play").addEventListener("click", () => { if (voiceChain && recordBuffer && !voiceTx()) voiceChain.playBuffer(recordBuffer); });
      client.env.voiceChain = (stream) => {
        /* Appelée par client.js à la connexion, avec le micro choisi ; la piste envoyée sort de la chaîne. */
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return null;
        const ctx = audioContext48(Ctx);
        if (ctx.resume) ctx.resume().catch(() => {});
        const chain = new vx.VoiceChain(ctx, ctx.createMediaStreamSource(stream), voiceSettings, (text, level) => ui.log(text, level));
        voiceChain = chain; voiceCtx = ctx; voiceRaw = stream.getAudioTracks()[0] || null;
        voiceRender();
        scrApplyTx();                                                  // scrambler d'émission en service : inséré tout de suite
        // Micro muet malgré l'ouverture (pilote USB bloqué, micro coupé dans Windows) : silence NUMÉRIQUE (que des zéros)
        // pendant 3 s de contexte audio en marche => un seul avertissement (même contrôle que Breizh Audio Box)
        let zeroMs = 0, watchMs = 0;
        const silenceWatch = window.setInterval(() => {
          if (voiceChain !== chain) { window.clearInterval(silenceWatch); return; }
          if (ctx.state !== "running") return;
          watchMs += 500;
          zeroMs = chain.micLevelDb() <= -120 ? zeroMs + 500 : 0;
          if (zeroMs >= 3000) {
            window.clearInterval(silenceWatch);
            ui.log(I18N.t("ui.mic_digital_silence"), "warn");
          } else if (watchMs >= 10000) window.clearInterval(silenceWatch);
        }, 500);
        if (voiceRaw) voiceRaw.addEventListener("ended", () => {
          if (voiceChain === chain) ui.log(I18N.t("ui.mic_ended"), "bad");
        });
        return {
          track: chain.track, stream: chain.stream,
          setTx(on) {
            if (on) chain.setExternal(client.breizhEffectsOff());        // voix par Breizh : égaliseur et effets coupés (limiteur gardé)
            chain.setTx(on);
            if (on && recorder) recorder.stop();                       // toute prise d'émission arrête l'enregistrement  // i18n-ok
            replayOnTx(on);
            voiceRender();
          },
          close() {
            if (recorder) { try { recorder.stop(); } catch (e) { /* déjà arrêté */ } }
            chain.close();
            if (ctx.close) ctx.close().catch(() => {});
            if (voiceChain === chain) { voiceChain = null; voiceCtx = null; voiceRaw = null; scrTxNode = null; }
            voiceRender(); scrRender();
          },
        };
      };
      voiceRender();
    } else {
      $("sec-voice").hidden = true; $("voice-direct").hidden = true;
    }

    // ---- scrambler (scrambler.js) : émission brouillée juste avant le limiteur de la voix, réception débrouillée avant le
    // haut-parleur (même élément audio : volume, sourdine et sortie inchangés). Décision de l'utilisateur du 2026-10-29 :
    // désactivé par défaut, message clair et confirmation à chaque mise en service, jamais réactivé seul (seuls le mode
    // et le décalage sont gardés par le navigateur).
    const sx = root.TrxScrambler || null;
    let scr = sx ? sx.validate(safeJson(store.get("trx.scrambler", "null"))) : null;
    let scrTxNode = null, rxGraph = null;
    const SCR_WARNING = "ui.scrambler_warning";                                    // clé du texte (lu à l'affichage)
    function scrMsg() { return { mode: scr.mode, offsetHz: scr.offsetHz }; }
    function scrSave() { store.set("trx.scrambler", JSON.stringify(scrMsg())); }
    function scrWorklet(ctx) {
      if (!ctx.audioWorklet || typeof AudioWorkletNode === "undefined") return Promise.reject(new Error(I18N.t("ui.no_audioworklet")));
      if (!ctx.trxScrambler) ctx.trxScrambler = ctx.audioWorklet.addModule("scrambler.js");
      return ctx.trxScrambler;
    }
    async function scrApplyTx() {
      if (!sx) return;
      const chain = voiceChain, ctx = voiceCtx;
      if (!scr.tx || !chain || !ctx) {
        if (chain) chain.setScrambler(null);
        scrTxNode = null;
        scrRender();
        return;
      }
      try {
        await scrWorklet(ctx);
        if (voiceChain !== chain || !scr.tx) return;
        if (!scrTxNode) scrTxNode = new AudioWorkletNode(ctx, "trx-scrambler", { processorOptions: Object.assign({ direction: "tx" }, scrMsg()) });
        else scrTxNode.port.postMessage(scrMsg());
        chain.setScrambler(scrTxNode);
        if (ctx.sampleRate !== 48000) ui.log(I18N.t("ui.scr_rate", { rate: ctx.sampleRate }), "warn");
      } catch (err) {
        scr.tx = false;
        if (chain) chain.setScrambler(null);
        ui.log(I18N.t("ui.scr_tx_failed", { error: err && err.message ? err.message : err }), "bad");
      }
      scrRender();
    }
    // ---- chaîne de la réception (Web Audio) : débrouillage du scrambler puis spatialisation (spatial.js), seulement si
    // l'un des deux est en service ; sinon le flux reçu va tel quel à l'élément audio (comme avant).
    function rxStop() {
      if (!rxGraph) return;
      try { rxGraph.raw.pause(); rxGraph.raw.srcObject = null; } catch (e) { /* déjà arrêté */ }
      if (rxGraph.rawSdr) { try { rxGraph.rawSdr.pause(); rxGraph.rawSdr.srcObject = null; } catch (e) { /* déjà arrêté */ } }
      if (rxGraph.ctx.close) rxGraph.ctx.close().catch(() => {});
      rxGraph = null;
    }
    function rxStream(media) {
      /* Flux à jouer : le flux reçu tel quel, ou traité (AudioWorklet) si le débrouillage ou la spatialisation est en service. */
      rxStop();
      const wantScr = !!(sx && scr.rx), wantSt = stActive();
      const pans = !wantSt && typeof sdrSplitActive === "function" && sdrSplitActive() ? sdrx.splitPans(sdrSplit) : null;
      if (!media || (!wantScr && !wantSt && !pans)) return media;
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        const ctx = audioContext48(Ctx);
        // Chrome : un flux WebRTC distant n'arrive à Web Audio que s'il est aussi lu par un élément (ici muet)
        const raw = new Audio(); raw.muted = true; raw.srcObject = media; raw.play().catch(() => {});
        const dest = ctx.createMediaStreamDestination();
        const state = { ctx, raw, dest, node: null, st: null, trxGain: null, sdrGain: null, rawSdr: null };
        rxGraph = state;
        if (pans && sdrMedia) {                                                       // son du SDR : même chaîne, autre oreille
          state.rawSdr = new Audio(); state.rawSdr.muted = true; state.rawSdr.srcObject = sdrMedia; state.rawSdr.play().catch(() => {});
        }
        Promise.all([wantScr ? scrWorklet(ctx) : null, wantSt ? stWorklet(ctx) : null]).then(() => {
          if (rxGraph !== state) return;
          let head = ctx.createMediaStreamSource(media);
          if (wantScr) {
            state.node = new AudioWorkletNode(ctx, "trx-scrambler", { processorOptions: Object.assign({ direction: "rx" }, scrMsg()) });
            head.connect(state.node); head = state.node;
          }
          if (wantSt) {
            state.st = new AudioWorkletNode(ctx, "trx-spatial", { outputChannelCount: [2], processorOptions: stParams() });
            state.st.port.onmessage = (ev) => stStats(ev.data || {});
            head.connect(state.st); head = state.st;
          }
          if (pans) {                                                                   // séparation TRX / SDR (module SDR)
            state.trxGain = ctx.createGain(); state.trxGain.gain.value = trxLevel();
            const pan = ctx.createStereoPanner(); pan.pan.value = pans.trx;
            head.connect(state.trxGain); state.trxGain.connect(pan); head = pan;
            if (state.rawSdr) {
              state.sdrGain = ctx.createGain(); state.sdrGain.gain.value = sdrLevel();
              const panSdr = ctx.createStereoPanner(); panSdr.pan.value = pans.sdr;
              ctx.createMediaStreamSource(sdrMedia).connect(state.sdrGain); state.sdrGain.connect(panSdr); panSdr.connect(dest);
            }
            audio.volume = 1;                                                           // volumes : gains de la chaîne
          }
          head.connect(dest);
          scrRender(); stRender();
        }).catch((err) => {
          if (rxGraph !== state) return;
          if (wantScr) scr.rx = false;
          if (wantSt) stFailed = true;
          rxStop(); audio.srcObject = media;
          ui.log(I18N.t("ui.rx_chain_failed", { error: err && err.message ? err.message : err }), "warn");
          scrRender(); stRender();
        });
        if (ctx.resume) ctx.resume().catch(() => {});
        window.setTimeout(() => {                                                   // contexte gardé en pause par le navigateur
          if (rxGraph !== state || ctx.state !== "suspended") return;
          ui.log(I18N.t("ui.rx_audio_waiting"), "warn");
          document.addEventListener("pointerdown", () => { if (rxGraph === state && ctx.resume) ctx.resume().catch(() => {}); }, { once: true });
        }, 1000);
        return dest.stream;
      } catch (err) {
        if (wantScr) scr.rx = false;
        if (wantSt) stFailed = true;
        ui.log(I18N.t("ui.rx_chain_failed", { error: err && err.message ? err.message : err }), "warn");
        return media;
      }
    }
    function rxApply() {
      if (rxMedia) {
        audio.srcObject = rxStream(rxMedia);
        audio.play().catch(() => {});
        trxVolume();                                                                // gain de chaîne ou volume de l'élément
      }
      scrRender(); stRender();
    }
    function scrRender() {
      if (!sx) return;
      $("scr-tx").checked = scr.tx; $("scr-rx").checked = scr.rx;
      $("scr-mode").value = scr.mode;
      $("scr-offset").value = scr.offsetHz;
      $("scr-offset-text").textContent = " " + (scr.offsetHz > 0 ? "+" : "") + scr.offsetHz + " Hz";
      const ind = $("scr-ind");
      ind.hidden = !(scr.tx || scr.rx);
      ind.textContent = scr.tx ? "SCRAMBLER" : I18N.t("ui.scr_ind_rx");
      const txState = !scr.tx ? I18N.t("ui.scr_tx_clear") : (voiceChain && scrTxNode && voiceChain.scrambler === scrTxNode) ? I18N.t("ui.scr_tx_on")
        : voiceChain ? I18N.t("ui.scr_tx_starting") : I18N.t("ui.scr_tx_pending");
      const rxState = !scr.rx ? I18N.t("ui.scr_rx_clear") : rxGraph && rxGraph.node ? I18N.t("ui.scr_rx_on") : I18N.t("ui.scr_rx_pending");
      $("scr-state").textContent = I18N.t("ui.scr_state", { tx: txState, rx: rxState, mode: sx.MODES[scr.mode].label });
    }
    if (sx) {
      for (const [key, m] of Object.entries(sx.MODES)) $("scr-mode").appendChild(Object.assign(el("option", "", m.label), { value: key }));
      const confirmOn = (what) => window.confirm(I18N.t(SCR_WARNING) + "\n\n" + what);
      $("scr-tx").addEventListener("change", (ev) => {
        if (ev.target.checked && client.breizhEffectsOff()) {                      // Breizh et scrambler d'émission exclusifs
          ev.target.checked = false;
          ui.log(I18N.t("ui.scr_breizh_refused"), "warn");
          return;
        }
        if (ev.target.checked && !confirmOn(I18N.t("ui.scr_confirm_tx"))) { ev.target.checked = false; return; }
        scr.tx = ev.target.checked;
        ui.log(scr.tx ? I18N.t("ui.scr_log_tx_on", { mode: sx.MODES[scr.mode].label }) : I18N.t("ui.scr_log_tx_off"), scr.tx ? "warn" : "");
        scrApplyTx();
      });
      $("scr-rx").addEventListener("change", (ev) => {
        if (ev.target.checked && !confirmOn(I18N.t("ui.scr_confirm_rx"))) { ev.target.checked = false; return; }
        scr.rx = ev.target.checked;
        ui.log(scr.rx ? I18N.t("ui.scr_log_rx_on") : I18N.t("ui.scr_log_rx_off"), "");
        if (scr.rx && spx && stSet.on) {                                            // débrouillage et ST exclusifs (2026-11-03)
          stSet = spx.validate(Object.assign({}, stSet, { on: false })); stSave(); stRender();
          ui.log(I18N.t("voicehub.spatial_off"), "");
        }
        rxApply();
      });
      $("scr-mode").addEventListener("change", (ev) => {
        scr.mode = sx.MODES[ev.target.value] ? ev.target.value : scr.mode;
        scrSave();
        if (scrTxNode) scrTxNode.port.postMessage(scrMsg());
        if (rxGraph && rxGraph.node) rxGraph.node.port.postMessage(scrMsg());
        scrRender();
      });
      $("scr-offset").addEventListener("input", (ev) => {
        scr.offsetHz = sx.validate({ mode: scr.mode, offsetHz: parseFloat(ev.target.value) }).offsetHz;
        scrSave();
        if (rxGraph && rxGraph.node) rxGraph.node.port.postMessage(scrMsg());
        scrRender();
      });
      $("scr-ind").addEventListener("click", () => { $("sec-scrambler").open = true; $("sec-scrambler").scrollIntoView({ block: "start" }); });
      scrRender();
    } else {
      $("sec-scrambler").hidden = true;
    }

    // ---- Breizh Audio Box (station 0.100.0+, fonction « breizh », opérateurs) : la voix passe par Breizh sur le réseau local
    // de la station ; état, volume retour, « Direct », réactivation après un repli, journal. Réglages pris à la PROCHAINE
    // émission. Égaliseur, chorus, réverbération et scrambler d'émission de cette page coupés quand la voix part par Breizh.
    let bzhLogLoaded = false;
    const BZH_WARN_EVENTS = ["fallback", "lost", "refused"];
    function bzhOffered() {
      return !!(client.connected && client.hello && Array.isArray(client.hello.features) && client.hello.features.includes("breizh"));
    }
    function bzhLogRender() {
      const list = $("bzh-log");
      list.textContent = "";
      for (const e of (client.breizhEvents || []).slice().reverse()) {             // le plus récent en tête
        const when = e.t ? e.t.replace("T", " ").replace("Z", " UTC") + " : " : "";
        list.appendChild(el("li", BZH_WARN_EVENTS.includes(e.event) ? "warn" : "", when + e.detail));
      }
    }
    function bzhLoadLog() { client.breizhLog().then(bzhLogRender).catch(fail); }
    function bzhRender(v) {
      const b = v && v.connected && bzhOffered() ? v.breizh : null;
      $("sec-breizh").hidden = !b; $("bzh-ind").hidden = !b;
      if (!b) { bzhLogLoaded = false; $("voice-breizh").hidden = true; bzhControls(false); return; }
      $("bzh-ind").className = "chip bzh-ind listener-hide" + (b.level !== "off" ? " " + b.level : "");  // i18n-ok (classes CSS)
      $("bzh-ind").title = I18N.t("ui.bzh_title", { text: b.text });
      $("bzh-state").className = "bzh-state" + (b.level !== "off" ? " " + b.level : "");
      $("bzh-state").textContent = b.text;
      $("bzh-details").textContent = b.details;
      if (document.activeElement !== $("bzh-gain")) $("bzh-gain").value = String(b.returnGainDb);
      $("bzh-gain-text").textContent = " " + b.returnGainText;
      $("bzh-bypass").checked = b.bypass;
      $("bzh-reactivate").hidden = !b.canReactivate;
      $("voice-breizh").hidden = !b.effectsOff;
      if (voiceChain && !voiceTx()) voiceChain.setExternal(b.effectsOff);         // écoute de contrôle = ce qui partira
      bzhControls(b.effectsOff);
      if (b.effectsOff && sx && scr.tx) {                                          // Breizh et scrambler d'émission exclusifs
        scr.tx = false;
        ui.log(I18N.t("voicehub.breizh_scrambler_off"), "warn");
        scrApplyTx();
      }
      if (!bzhLogLoaded) { bzhLogLoaded = true; bzhLoadLog(); }
    }
    function bzhControls(effectsOff) {
      /* Commandes de l'égaliseur, des effets et du scrambler d'émission grisées tant que la voix passe par Breizh. */
      if (sx) $("scr-tx").disabled = effectsOff;
      if (effectsOff !== voiceBzh) { voiceBzh = effectsOff; voiceRender(); }
    }
    function bzhSet(changes) {
      client.breizhSet(changes).then((res) => {
        if (res && !res.ok) ui.log(I18N.t("rigsession.breizh_refused", { detail: web.reasonText(res.reason, res.detail, res.ort) }), "warn");
      }).catch(fail);
    }
    $("bzh-gain").addEventListener("input", (ev) => {
      const g = Number(ev.target.value);
      $("bzh-gain-text").textContent = " " + (g > 0 ? "+" : g < 0 ? "−" : "") + String(Math.abs(g)).replace(".", ",") + " dB";
    });
    $("bzh-gain").addEventListener("change", (ev) => bzhSet({ return_gain_db: Number(ev.target.value) }));
    $("bzh-bypass").addEventListener("change", (ev) => bzhSet({ bypass: !!ev.target.checked }));
    $("bzh-reactivate").addEventListener("click", () => {
      client.breizhReactivate().then((res) => {
        if (!res || !res.ok) { ui.log(I18N.t("rigsession.breizh_refused", { detail: web.reasonText(res && res.reason, res && res.detail, res && res.ort) }), "warn"); return; }
        ui.log(res.pending ? I18N.t("rigsession.breizh_pending") : I18N.t("rigsession.breizh_resumed"), "");
      }).catch(fail);
    });
    $("bzh-log-refresh").addEventListener("click", bzhLoadLog);
    $("bzh-ind").addEventListener("click", () => { $("sec-breizh").open = true; $("sec-breizh").scrollIntoView({ block: "start" }); });

    // ---- FreeDV RADE V1 en réception (station 0.122.0+, fonction « freedv », docs/protocole.md § 17) : la station décode,
    // la page affiche. Voyant FDV et rubrique pour TOUS (visiteurs compris) ; le bouton du mode est réservé aux opérateurs
    // et grisé pendant une émission (la station le refuserait aussi).
    let fdvOn = false;
    function fdvOffered() {
      return !!(client.connected && client.hello && Array.isArray(client.hello.features) && client.hello.features.includes("freedv"));
    }
    function fdvRender(v) {
      const f = v && v.connected && fdvOffered() ? v.freedv : null;
      $("sec-freedv").hidden = !f; $("fdv-ind").hidden = !f;
      if (!f) return;
      fdvOn = f.on;
      const lvl = f.level !== "off" ? " " + f.level : "";
      $("fdv-ind").className = "chip fdv-ind" + lvl;  // i18n-ok (classes CSS)
      $("fdv-ind").title = f.lastCall ? I18N.t("ui.fdv_title_call", { text: f.text, callsign: f.lastCall.callsign }) : I18N.t("ui.fdv_title", { text: f.text });
      $("fdv-state").className = "fdv-state" + lvl;
      $("fdv-state").textContent = f.text;
      const details = [];
      if (f.lastCall) details.push(I18N.t("freedv.last_call", { callsign: f.lastCall.callsign, snr: f.lastCall.snrText ? " (" + f.lastCall.snrText + ")" : "",
        when: f.lastCall.when ? ", " + f.lastCall.when : "" }));
      if (f.restarts) details.push(I18N.t("freedv.restarts", { restarts: f.restarts }));
      if (f.cause) details.push(I18N.t("freedv.last_fault", { cause: f.cause }));
      $("fdv-details").textContent = details.join(" · ");
      $("fdv-toggle").textContent = f.on ? I18N.t("freedvdialog.back_to_rig") : I18N.t("freedvdialog.switch_on");
      $("fdv-toggle").disabled = v.pttState !== "RX";
      const calls = $("fdv-calls");
      calls.textContent = "";
      for (const c of f.calls) calls.appendChild(el("li", "", c.callsign + (c.snrText ? " · " + c.snrText : "") + (c.when ? " · " + c.when : "")));
      if (!f.calls.length) calls.appendChild(el("li", "note", I18N.t("freedvdialog.calls_none")));
      const seqs = $("fdv-seqs");
      seqs.textContent = "";
      for (const s of f.sequences) {
        const li = el("li", "");
        const stars = el("span", "stars" + (s.note >= 4 ? " good" : ""), s.stars);
        stars.title = s.detail;
        li.appendChild(stars);
        li.appendChild(el("span", "", " " + s.duration + (s.callsigns ? " · " + s.callsigns : "") + (s.when ? " · " + s.when : "")));
        seqs.appendChild(li);
      }
      if (!f.sequences.length) seqs.appendChild(el("li", "note", I18N.t("freedvdialog.sequences_none")));
    }
    $("fdv-toggle").addEventListener("click", () => {
      const want = !fdvOn;
      $("fdv-toggle").disabled = true;
      client.freedvSet(want).then((res) => {
        if (res && res.ok) ui.log(want ? I18N.t("rigsession.freedv_on") : I18N.t("rigsession.freedv_off"), "");
      }).catch(fail);
    });
    $("fdv-ind").addEventListener("click", () => { $("sec-freedv").open = true; $("sec-freedv").scrollIntoView({ block: "start" }); });

    // ---- Activité FreeDV (module « freedv_activity ») : stations actives par fréquence, d'après FreeDV Reporter.
    // Un clic d'un OPÉRATEUR sur une ligne = QSY immédiat (refusé pendant l'émission, ici et par la station).
    function fdvaRender() {
      const rig = client.state && client.state.rig ? client.state.rig : {};
      const a = client.connected ? web.freedvActivityView(client.freedvActivity, rig.frequency_hz, Date.now() / 1000) : null;
      $("fdva").hidden = !a;
      if (!a) return;
      $("fdva-state").textContent = a.text;
      const body = $("fdva-rows");
      body.textContent = "";
      const operator = !client.isListener();
      for (const r of a.rows) {
        const tr = el("tr", (operator ? "go" : "") + (r.here ? " here" : ""));
        if (operator) { tr.title = I18N.t("ui.fdva_go", { freq: r.freqText }); tr.addEventListener("click", () => fdvaQsy(r.hz)); }
        tr.appendChild(el("td", "f", r.freqText + (r.here ? I18N.t("freedvactivity.here") : "")));
        tr.appendChild(el("td", "", String(r.note).replace(".", ",")));
        const tx = el("td", "");
        r.tx.forEach((t, i) => { tx.appendChild(el("span", t.on ? "on" : "", (i ? ", " : "") + t.text)); });
        if (!r.tx.length) tx.appendChild(el("span", "", "—"));
        tr.appendChild(tx);
        tr.appendChild(el("td", "", r.rx.join(", ") || "—"));
        body.appendChild(tr);
      }
      if (!a.rows.length) {
        const tr = el("tr", "");
        tr.appendChild(el("td", "note", a.status === "ok" ? I18N.t("freedvactivity.empty") : "—"));
        body.appendChild(tr);
      }
    }
    function fdvaQsy(hz) {
      if (client.isListener()) return;
      client.freedvQsy(hz).then((res) => {
        if (res && res.ok) ui.log(I18N.t("rigsession.freedv_qsy", { freq: web.freedvFreqText(hz) }), "");
        else if (res) ui.log(web.reasonText(res.reason, res.detail, res.ort), "warn");
      }).catch(fail);
    }

    // ---- module SDR (sdr.js, docs/sdr-cahier-des-charges.md, fonction « sdr », OPÉRATEURS) : waterfall du SDR
    // Lignes reçues seulement rubrique ouverte (« watch ») ; réglages du SDR relayés au module ; QSY du TRX = commande
    // habituelle de fréquence (refusée pendant l'émission). Le SDR n'agit jamais sur le poste.
    const sdrx = root.TrxSdr || null;
    let sdrView = { range: sdrx ? sdrx.DEFAULT_VIEW.range : 50, floor: null }, sdrPicked = null, sdrLast = null;
    const sdrSpotBook = sp ? new sp.SpotBook() : null;                            // spots du Cluster DX dans la fenêtre du SDR
    let sdrSpotsOn = true, sdrSpotsDrawn = { c: null, s: null, at: 0, version: -1 };
    try { sdrSpotsOn = store.get("trx.sdr.spots", "1") !== "0"; } catch (e) { sdrSpotsOn = true; }
    let sdrPalette = "theme", sdrLut = null;                                         // palette du waterfall du SDR (ce navigateur)
    try { sdrPalette = store.get("trx.sdr.palette", "theme") || "theme"; } catch (e) { sdrPalette = "theme"; }
    if (sdrx) sdrLut = sdrx.paletteLut(sdrPalette);
    function sdrOffered() { return !!(sdrx && client.sdrOffered && client.connected && !client.isListener()); }
    function sdrRender(st) {
      const on = sdrOffered();
      $("sec-sdr").hidden = !on;
      if (!on) {
        sdrPicked = null; $("sdr-here").hidden = true;
        if (sdrSound) { try { sdrSound.pause(); } catch (e) { /* rien */ } }
        return;
      }
      const state = st || client.sdrState;
      $("sdr-status").textContent = sdrx.stateText(state);
      const loadLine = state && state.state !== "suspended" ? sdrx.loadText(state) : "";
      $("sdr-load").hidden = !loadLine;
      $("sdr-load").textContent = loadLine;
      $("sdr-badge").textContent = state && state.state === "running" ? sdrx.formatMHz(state.center, 3) + " MHz"
        : state && state.state === "error" ? I18N.t("ui.sdr_fault") : "";
      if (state && state.state) {
        if (document.activeElement !== $("sdr-center") && Number.isFinite(state.center)) $("sdr-center").value = sdrx.formatMHz(state.center, 4);
        if (document.activeElement !== $("sdr-dfreq") && Number.isFinite(state.dfreq)) $("sdr-dfreq").value = sdrx.formatMHz(state.dfreq, 4);
        if (!sdrDragging("sdr-rf") && Number.isFinite(state.lna)) $("sdr-rf").value = String(sdrx.rfFromLna(state.lna));
        if (!sdrDragging("sdr-if") && Number.isFinite(state.gr)) $("sdr-if").value = String(sdrx.ifFromGr(state.gr));
        $("sdr-agc").checked = state.agc !== false;
        $("sdr-if-box").hidden = state.agc !== false || state.driver === "rtlsdr";   // clé RTL-SDR : pas de gain FI
        if (Number.isFinite(state.rate)) $("sdr-rate").value = String(state.rate);
        sdrSliderLabels();
      }
      $("sdr-range").textContent = "DYN " + sdrView.range + " dB";
      $("sdr-palette").textContent = I18N.t("ui.sdr_colors", { palette: sdrx.paletteName(sdrPalette) });
      const hwOk = !!(state && Array.isArray(state.fs_choices));                    // station 0.155.0+ : largeur et antenne
      $("sdr-hw-box").hidden = !hwOk;
      if (hwOk) {
        const sel = $("sdr-fs"), want = state.fs_choices.map(String).join(",");
        if (sel.dataset.choices !== want) {
          sel.textContent = "";
          for (const hz of state.fs_choices) sel.appendChild(Object.assign(el("option", "", sdrx.rateLabel(hz)), { value: String(hz) }));
          sel.dataset.choices = want;
        }
        if (Number.isFinite(state.fs_set)) sel.value = String(state.fs_set);
        sel.disabled = state.fs_choices.length < 2;
        const ants = Array.isArray(state.ant_choices) ? state.ant_choices : [];
        $("sdr-ant-box").hidden = ants.length < 2;
        if (state.ant) $("sdr-ant").value = state.ant;
      }
      const zoomOk = !!(state && Number.isFinite(state.zoom));                       // station 0.154.0+ : zoom du waterfall
      $("sdr-zoom-box").hidden = !zoomOk;
      if (zoomOk) {
        $("sdr-zoom").textContent = sdrx.zoomLabel(state);
        $("sdr-zoom-in").disabled = sdrx.zoomStep(state.zoom, 1) === null;
        $("sdr-zoom-out").disabled = sdrx.zoomStep(state.zoom, -1) === null;
        $("sdr-pan-down").disabled = $("sdr-pan-up").disabled = !(state.zoom > 1);
      }
      $("sdr-gain").textContent = sdrx.gainText(state);
      sdrListenRender(state);
    }
    // ---- écoute du SDR (station 0.142.0+) : seconde piste, lue par son propre élément audio (sdrSound, plus haut) ;
    // en séparation gauche / droite, elle entre dans la chaîne Web Audio du TRX (rxStream) et l'élément se tait
    let sdrMedia = null;
    let sdrSplit = 0;                                    // 0 mélange, 1 TRX à gauche / SDR à droite, 2 l'inverse
    try { sdrSplit = Number(store.get("trx.sdr.split", "0")) || 0; } catch (e) { sdrSplit = 0; }
    function sdrBalance() { return sdrx ? sdrx.balanceGains(client.sdrListening ? $("sdr-bal").value : 0) : { trx: 1, sdr: 1 }; }
    function sdrSplitActive() { return !!(sdrx && sdrSplit && client.sdrListening && !stActive()); }
    function trxLevel() { return Math.max(0, Math.min(1, parseFloat($("volume").value) * sdrBalance().trx)); }
    function sdrLevel() { return sdrx ? sdrx.volumeOf($("sdr-vol").value) * sdrBalance().sdr : 1; }
    function trxVolume() {
      if (rxGraph && rxGraph.trxGain) { rxGraph.trxGain.gain.value = trxLevel(); audio.volume = 1; }
      else audio.volume = trxLevel();
    }
    function sdrVolume() {
      if (rxGraph && rxGraph.sdrGain) rxGraph.sdrGain.gain.value = sdrLevel();
      if (sdrSound) sdrSound.volume = sdrLevel();
    }
    function sdrRoute() {
      /* Son du SDR : lu par son élément (mélange), ou dans la chaîne du TRX (séparation : rxStream) et l'élément se tait. */
      if (!sdrSound || !sdrMedia) return;
      try {
        if (sdrSplitActive()) { sdrSound.pause(); sdrSound.srcObject = null; return; }
        if (sdrSound.srcObject !== sdrMedia) sdrSound.srcObject = sdrMedia;
        sdrVolume(); sdrMirrorOutput();
        if (client.sdrListening) sdrSound.play().catch(() => {});
      } catch (e) { /* navigateur sans seconde piste : le waterfall reste */ }
    }
    function sdrAttach(stream, track) {
      if (!sdrSound) return;
      try { sdrMedia = stream || new MediaStream([track]); } catch (e) { return; }
      sdrRoute();
      if (sdrSplitActive()) rxApply();                                            // séparation déjà choisie : chaîne refaite avec le SDR
    }
    function sdrEarsChanged() {
      /* Écoute ou séparation changée : chaîne du TRX refaite (avec ou sans le SDR), puis volumes. */
      sdrRoute(); rxApply(); trxVolume(); sdrVolume();
    }
    function sdrModeOptions(mode) {
      const sel = $("sdr-mode");
      if (!sel.options || sel.options.length !== sdrx.MODES.length) {
        sel.textContent = "";
        for (const m of sdrx.MODES) sel.appendChild(Object.assign(el("option", "", m), { value: m }));
      }
      const widths = sdrx.WIDTHS[mode] || [];
      const dbw = $("sdr-dbw");
      if (dbw.dataset.mode !== mode) {
        dbw.textContent = "";
        for (const w of widths) dbw.appendChild(Object.assign(el("option", "", sdrx.widthLabel(w)), { value: String(w) }));
        dbw.dataset.mode = mode;
      }
    }
    function sdrListenRender(state) {
      const offered = !!client.sdrAudioOffered;
      $("sdr-listen-box").hidden = !offered;
      if (!offered) return;
      const listening = !!client.sdrListening;
      $("sdr-listen").setAttribute("aria-pressed", listening ? "true" : "false");
      $("sdr-listen").textContent = listening ? I18N.t("ui.sdr_listening") : I18N.t("ui.sdr_listen");
      if (state && state.mode) {
        sdrModeOptions(state.mode);
        $("sdr-mode").value = state.mode;
        $("sdr-dbw").value = String(state.dbw);
        if (!sdrDragging("sdr-sql")) $("sdr-sql").value = String(state.sql || 0);
      }
      $("sdr-sql-val").textContent = Number($("sdr-sql").value) ? $("sdr-sql").value + " dB" : I18N.t("stationtab.squelch_open");
      $("sdr-listen-info").textContent = sdrx.listenText(state, listening);
      const left = state && sdrLast ? sdrx.markerLeft(state.dfreq, sdrLast.c, sdrLast.s) : null;
      $("sdr-marker").hidden = left === null;
      if (left !== null) $("sdr-marker").style.left = left + "%";
    }
    // curseurs de gain : appliqués PENDANT le glissement, au plus un envoi toutes les 0,3 s (le dernier part toujours)
    const SDR_SLIDE_MS = 300;
    const sdrSlide = { busy: false, pending: null, held: {} };
    function sdrDragging(id) { return !!sdrSlide.held[id]; }
    function sdrSliderLabels() {
      $("sdr-rf-val").textContent = $("sdr-rf").value + "/" + sdrx.LNA_MAX;
      $("sdr-if-val").textContent = $("sdr-if").value + "/39";
    }
    function sdrSlideSend(args) {
      sdrSlide.pending = Object.assign(sdrSlide.pending || {}, args);
      if (sdrSlide.busy) return;
      sdrSlide.busy = true;
      const next = sdrSlide.pending; sdrSlide.pending = null;
      sdrSend(next).finally(() => setTimeout(() => {
        sdrSlide.busy = false;
        if (sdrSlide.pending) sdrSlideSend({});
      }, SDR_SLIDE_MS));
    }
    let sdrAxisWidth = -1;
    function sdrAxis(center, span) {
      const box = $("sdr-axis");
      const width = box.clientWidth || 0;
      if (sdrLast && sdrLast.c === center && sdrLast.s === span && sdrAxisWidth === width) return;
      sdrAxisWidth = width;                                                          // fenêtre redimensionnée : graduations refaites
      box.textContent = "";
      const count = Math.max(6, Math.min(40, Math.floor((box.clientWidth || 600) / 55)));   // une étiquette tous les ~55 px
      const marks = sdrx.ticks(center, span, count);
      const digits = sdrx.tickDigits(marks);
      for (const f of marks) {
        const tick = el("span", "", sdrx.formatMHz(f, digits));
        tick.style.left = (100 * (f - (center - span / 2)) / span).toFixed(2) + "%";
        box.appendChild(tick);
      }
    }
    function sdrDraw(data) {
      if (!sdrOffered() || !$("sec-sdr").open || !wf) return;
      const values = sdrx.decodeLine(data.d);
      if (!values || !values.length) return;
      const cv = $("sdr-wf"), n = values.length;
      if (!cv.getContext) return;
      const g = cv.getContext("2d");
      if (!g) return;
      if (cv.width !== n || cv.height !== 200) { cv.width = n; cv.height = 200; }
      const floor = sdrx.floorDb(values);
      sdrView.floor = sdrView.floor === null ? floor : sdrView.floor * 0.9 + floor * 0.1;     // plancher lissé
      g.drawImage(cv, 0, 0, n, cv.height - 1, 0, 1, n, cv.height - 1);                       // la plus récente en haut
      const row = g.createImageData(n, 1);
      for (let i = 0; i < n; i++) {
        const k = sdrx.colorIndex(values[i], sdrView.floor - 3, sdrView.range) * 3, lut = sdrLut || wf.LUT;
        row.data[4 * i] = lut[k]; row.data[4 * i + 1] = lut[k + 1]; row.data[4 * i + 2] = lut[k + 2]; row.data[4 * i + 3] = 255;
      }
      g.putImageData(row, 0, 0);
      sdrAxis(data.c, data.s);
      sdrLast = { c: data.c, s: data.s };
      // étiquettes refaites quand la fenêtre change, et toutes les 10 s (les spots pâlissent avec l'âge)
      if (sdrSpotsDrawn.c !== data.c || sdrSpotsDrawn.s !== data.s || Date.now() - sdrSpotsDrawn.at > 10000) sdrDrawSpots();
    }
    function sdrDrawSpots() {
      const layer = $("sdr-spot-layer");
      layer.textContent = "";
      sdrSpotsDrawn = { c: sdrLast ? sdrLast.c : null, s: sdrLast ? sdrLast.s : null, at: Date.now() };
      $("sdr-spots").className = "chip" + (sdrSpotsOn ? " on" : "");
      if (!sp || !sdrSpotBook || !sdrSpotsOn || !sdrLast || !(sdrLast.s > 0)) return;
      const low = sdrLast.c - sdrLast.s / 2, high = sdrLast.c + sdrLast.s / 2, now = Date.now();
      const visible = sdrSpotBook.visible(low, high);
      const width = layer.clientWidth || $("sdr-wf").clientWidth || 0;
      for (const s of visible) {
        const line = el("div", "spot-line k-" + s.kind);  // i18n-ok (classe CSS)
        line.style.left = (((s.hz - low) / sdrLast.s) * 100).toFixed(2) + "%";
        line.style.opacity = String(sp.opacity(sp.ageSeconds(s, now)) * 0.7);
        layer.appendChild(line);
      }
      for (const tag of sp.layoutLabels(visible, low, high, width, { rows: 2, charPx: 7, padPx: 12 })) {
        const first = sdrSpotBook.get(tag.ids[0]);
        const age = first ? sp.ageSeconds(first, now) : 0;
        const button = el("button", "spot-tag k-" + (first ? first.kind : "cluster") + (tag.group ? " group" : "")  // i18n-ok (classe CSS)
                                    + (!tag.group && age <= sp.FRESH_S ? " fresh" : ""), tag.text);
        button.style.left = tag.x.toFixed(1) + "px";
        button.style.top = (2 + tag.row * 18) + "px";
        if (!tag.group) button.style.opacity = String(sp.opacity(age));
        const spots = tag.ids.map((id) => sdrSpotBook.get(id)).filter(Boolean);
        button.title = spots.map((s) => s.dx + " " + s.khz.toFixed(1) + " kHz " + sp.modeLabel(s)).join("\n")
                       + "\n" + I18N.t(spots.length > 1 ? "ui.sdr_spot_touch_first" : "ui.sdr_spot_touch");
        button.addEventListener("pointerdown", (ev) => { if (ev.stopPropagation) ev.stopPropagation(); });
        button.addEventListener("dblclick", (ev) => { if (ev.stopPropagation) ev.stopPropagation(); });
        button.addEventListener("click", (ev) => {
          if (ev.stopPropagation) ev.stopPropagation();
          const s = spots[0], st = client.sdrState || {};
          const args = s ? sdrx.spotListen(s, st.center, st.fs) : null;
          if (!args) return;
          sdrSend(args);
          ui.log(I18N.t("ui.sdr_on_spot", { dx: s.dx, khz: s.khz.toFixed(1), mode: args.mode ? " " + args.mode : "" }), "");
        });
        layer.appendChild(button);
      }
    }
    function sdrOnSpots(data) {
      if (!sp || !sdrSpotBook) return;
      if (!sdrSpotBook.apply(Object.assign({}, data, { kind: "spots" }), Date.now())) return;
      if ($("sec-sdr").open) sdrDrawSpots();
    }
    function sdrTune(hz) {
      /* Réglages pour écouter hz : le centre ne bouge que si hz sort de la largeur ENTIÈRE du SDR (avec le zoom, la
         fenêtre montrée est plus étroite et la station la fait suivre l'écoute). */
      const st = client.sdrState || {};
      if (Number.isFinite(st.center) && st.fs > 0) return sdrx.tuneArgs(hz, st.center, st.fs);
      return sdrx.tuneArgs(hz, sdrLast ? sdrLast.c : st.center, sdrLast ? sdrLast.s : 0);
    }
    async function sdrSend(args) {
      try {
        const res = await client.sdrSet(args);
        if (!res.ok) ui.log(web.reasonText(res.reason, res.detail, res.ort), "warn");
      } catch (e) { ui.log(I18N.t("ui.sdr_not_sent"), "warn"); }
    }
    if (sdrx) {
      $("sec-sdr").addEventListener("toggle", () => {
        if (!sdrOffered()) return;
        if (sdrSpotBook && $("sec-sdr").open) sdrSpotBook.clear();                  // la station rejoue les spots à l'ouverture
        client.sdrWatch($("sec-sdr").open).then((res) => { if (res && !res.ok) ui.log(web.reasonText(res.reason, res.detail, res.ort), "warn"); }).catch(() => {});
      });
      const sdrCenterSet = () => {
        const hz = sdrx.parseMHz($("sdr-center").value);
        if (hz === null) { ui.log(I18N.t("ui.sdr_center_invalid"), "warn"); return; }
        sdrSend({ center_hz: hz });
      };
      const sdrDfreqSet = () => {                  // fréquence à écouter ; le centre suit si elle sort de la fenêtre
        const hz = sdrx.parseMHz($("sdr-dfreq").value);
        if (hz === null) { ui.log(I18N.t("ui.sdr_dfreq_invalid"), "warn"); return; }
        sdrSend(sdrTune(hz));
      };
      $("sdr-center-set").addEventListener("click", sdrCenterSet);
      $("sdr-dfreq-set").addEventListener("click", sdrDfreqSet);
      $("sdr-center").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); sdrCenterSet(); } });  // i18n-ok (touche)
      $("sdr-dfreq").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); sdrDfreqSet(); } });  // i18n-ok (touche)
      for (const id of ["sdr-rf", "sdr-if"]) {
        const send = () => {
          sdrSliderLabels();
          sdrSlideSend(id === "sdr-rf" ? { lna: sdrx.lnaFromRf(Number($(id).value)) } : { gr: sdrx.grFromIf(Number($(id).value)) });
        };
        $(id).addEventListener("input", () => { sdrSlide.held[id] = true; send(); });
        $(id).addEventListener("change", () => { sdrSlide.held[id] = false; send(); });
      }
      $("sdr-agc").addEventListener("change", () => {
        $("sdr-if-box").hidden = $("sdr-agc").checked || (client.sdrState || {}).driver === "rtlsdr";
        sdrSend({ agc: $("sdr-agc").checked });
      });
      $("sdr-rate").addEventListener("change", () => sdrSend({ rate: Number($("sdr-rate").value) }));
      $("sdr-range").addEventListener("click", () => { sdrView.range = sdrx.nextRange(sdrView.range); sdrRender(null); });
      $("sdr-spots").addEventListener("click", () => {
        sdrSpotsOn = !sdrSpotsOn;
        try { store.set("trx.sdr.spots", sdrSpotsOn ? "1" : "0"); } catch (e) { /* sans stockage */ }
        sdrDrawSpots();
      });
      $("sdr-palette").addEventListener("click", () => {
        sdrPalette = sdrx.nextPalette(sdrPalette);
        sdrLut = sdrx.paletteLut(sdrPalette);
        try { store.set("trx.sdr.palette", sdrPalette); } catch (e) { /* sans stockage */ }
        sdrRender(null);
      });
      $("sdr-fs").addEventListener("change", () => { sdrView.floor = null; sdrSend({ fs: Number($("sdr-fs").value) }); });
      $("sdr-ant").addEventListener("change", () => sdrSend({ ant: $("sdr-ant").value }));
      for (const [id, dir] of [["sdr-zoom-in", 1], ["sdr-zoom-out", -1]]) {
        $(id).addEventListener("click", () => {
          const z = sdrx.zoomStep((client.sdrState || {}).zoom, dir);
          if (z !== null) { sdrView.floor = null; sdrSend({ zoom: z }); }          // plancher réestimé : les cases changent
        });
      }
      for (const [id, dir] of [["sdr-pan-down", -1], ["sdr-pan-up", 1]]) {
        $(id).addEventListener("click", () => { const a = sdrx.panArgs(client.sdrState, dir); if (a) sdrSend(a); });
      }
      $("sdr-wf").addEventListener("click", (ev) => {
        if (!sdrLast) return;
        const cv = $("sdr-wf"), width = cv.clientWidth || cv.width;
        sdrPicked = sdrx.freqAt(ev.offsetX, width, sdrLast.c, sdrLast.s);
        $("sdr-pick").textContent = sdrPicked ? I18N.t("ui.sdr_picked", { mhz: sdrx.formatMHz(sdrPicked, 4) }) : "";
        $("sdr-here").hidden = !sdrPicked || !client.sdrAudioOffered;
      });
      $("sdr-here").addEventListener("click", () => { if (sdrPicked) sdrSend({ dfreq_hz: sdrPicked }); });
      $("sdr-wf").addEventListener("dblclick", (ev) => {                 // double clic : le SDR écoute cette fréquence
        if (!sdrLast) return;
        const cv = $("sdr-wf"), width = cv.clientWidth || cv.width;
        const hz = sdrx.freqAt(ev.offsetX, width, sdrLast.c, sdrLast.s);
        if (hz) sdrSend({ dfreq_hz: hz });
      });
      $("sdr-listen").addEventListener("click", () => {
        const on = !client.sdrListening;
        client.sdrListen(on).then((res) => {
          if (!res.ok) { ui.log(web.reasonText(res.reason, res.detail, res.ort), "warn"); return; }
          if (sdrSound) { if (on) sdrSound.play().catch(() => ui.log(I18N.t("ui.sdr_audio_blocked"), "warn")); else sdrSound.pause(); }
          sdrEarsChanged();
          sdrRender(null);
        }).catch(() => {});
      });
      $("sdr-mode").addEventListener("change", () => sdrSend({ mode: $("sdr-mode").value }));
      $("sdr-dbw").addEventListener("change", () => sdrSend({ dbw: Number($("sdr-dbw").value) }));
      $("sdr-sql").addEventListener("input", () => { sdrSlide.held["sdr-sql"] = true; $("sdr-sql-val").textContent = Number($("sdr-sql").value) ? $("sdr-sql").value + " dB" : I18N.t("stationtab.squelch_open"); sdrSlideSend({ sql: Number($("sdr-sql").value) }); });
      $("sdr-sql").addEventListener("change", () => { sdrSlide.held["sdr-sql"] = false; sdrSlideSend({ sql: Number($("sdr-sql").value) }); });
      $("sdr-vol").addEventListener("input", () => { sdrVolume(); });
      for (const [value, label] of sdrx.SPLITS) $("sdr-split").appendChild(Object.assign(el("option", "", label), { value: String(value) }));
      $("sdr-split").value = String(sdrSplit);
      try { $("sdr-bal").value = store.get("trx.sdr.balance", "0"); } catch (e) { /* valeur par défaut */ }
      $("sdr-bal").addEventListener("input", () => {
        try { store.set("trx.sdr.balance", $("sdr-bal").value); } catch (e) { /* sans stockage */ }
        trxVolume(); sdrVolume();
      });
      $("sdr-bal").addEventListener("dblclick", () => { $("sdr-bal").value = "0"; trxVolume(); sdrVolume(); });
      $("sdr-split").addEventListener("change", () => {
        sdrSplit = Number($("sdr-split").value) || 0;
        try { store.set("trx.sdr.split", String(sdrSplit)); } catch (e) { /* sans stockage */ }
        if (sdrSplit && stSet && stSet.on) {                                          // séparation et spatialisation ST exclusives
          ui.log(I18N.t("ui.sdr_split_st_off"), "");
          stChange(Object.assign({}, stSet, { on: false }));
        }
        sdrEarsChanged();
      });
      $("sdr-qsy").addEventListener("click", () => {                     // QSY SDR -> TRX : la fréquence ÉCOUTÉE sur le SDR
        const st = client.sdrState || {};
        const hz = Number.isFinite(st.dfreq) ? st.dfreq : null;
        if (!hz) { ui.log(I18N.t("ui.sdr_qsy_unknown"), "warn"); return; }
        client.qsy(hz).then((res) => {
          if (res && res.ok) ui.log(I18N.t("ui.sdr_qsy_done", { mhz: sdrx.formatMHz(hz, 4) }), "");
          else if (res) ui.log(web.reasonText(res.reason, res.detail, res.ort), "warn");
        }).catch(() => {});
      });
      $("sdr-qsy-rev").addEventListener("click", () => {                 // QSY TRX -> SDR : le SDR écoute la fréquence du TRX
        const rig = (client.state && client.state.rig) || {};
        const hz = rig.frequency_hz;
        if (!Number.isFinite(hz)) { ui.log(I18N.t("ui.sdr_qsy_rev_unknown"), "warn"); return; }
        sdrSend(sdrTune(hz));
        ui.log(I18N.t("ui.sdr_qsy_rev_done", { mhz: sdrx.formatMHz(hz, 4) }), "");
      });
    }

    // ---- présence de groupe « Amis » (friends.js, docs/presence-cahier-des-charges.md, fonction « friends », OPÉRATEURS)
    // Lecture de la vue préparée par la station (états déjà déchiffrés), actions relayées au module « presence ».
    // Affichage choisi par l'opérateur : dans les rubriques, en grand (en tête, les autres rubriques repliées ; fréquence,
    // PTT et STOP restent à leur place), ou dans une fenêtre détachée (Document Picture-in-Picture, là où elle existe).
    // QSY vers un ami : confirmé, refusé pendant l'émission, commandes habituelles (client.friendsQsy) ; jamais d'émission.
    const fx = root.TrxFriends || null;
    const FR_REFRESH_MS = 30000;
    let frView = null, frTimer = null, frPip = null, frHome = null;
    let frBy = store.get("trx.friends.by", "group") === "member" ? "member" : "group";
    let frMode = fx ? fx.displayMode(store.get("trx.friends.display", "section"), fx.pipSupported(root)) : "section";
    function frOffered() { return !!(fx && client.friendsOffered && client.connected && !client.isListener()); }
    function frNowS() { return Date.now() / 1000; }
    function frElapsed() { return client.friendsAt ? Math.max(0, (client.env.now() - client.friendsAt) / 1000) : 0; }
    function frPtt() { return typeof client._ptt === "function" && client._ptt() ? client._ptt().state : "RX"; }
    function frRigHz() { return client.state && client.state.rig ? client.state.rig.frequency_hz : NaN; }
    function frFail(res) { if (res && !res.ok) ui.log(I18N.t("rigsession.friends_refused", { detail: web.reasonText(res.reason, res.detail, res.ort) }), "warn"); return res; }

    function frChip(label, fn, doc, cls) {
      const b = (doc || document).createElement("button");
      b.className = cls || "chip";
      b.textContent = label;
      b.addEventListener("click", fn);
      return b;
    }
    function frMemberButton(m, g, doc) {
      const d = doc || document;
      const b = d.createElement("button");
      b.className = "fr-member" + (m.code === "O" ? " off" : "");
      const dot = d.createElement("span"); dot.className = "fr-dot " + m.cls; dot.textContent = m.letter; dot.title = m.label;
      const name = d.createElement("span"); name.className = "grow";
      name.textContent = m.pseudo + (m.groups && m.groups.length > 1 ? " (" + m.groups.join(", ") + ")" : "");
      const det = d.createElement("span"); det.className = "dim"; det.textContent = m.detail;
      b.appendChild(dot); b.appendChild(name); b.appendChild(det);
      b.addEventListener("click", () => { if (frPip && d !== document) root.focus(); frOpenMember(m, g); });
      return b;
    }
    function frList(box, v, compact, doc) {
      const d = doc || document;
      box.textContent = "";
      const note = (text) => { const p = d.createElement("p"); p.className = "note"; p.textContent = text; box.appendChild(p); };
      if (!v.groups.length) { note(I18N.t("friendsviews.no_groups")); return; }
      if (v.by === "member") {
        for (const m of v.members) box.appendChild(frMemberButton(m, null, d));
        if (!v.members.length) note(I18N.t("friendsviews.nobody_in_groups"));
        return;
      }
      for (const g of v.groups) {
        const sec = d.createElement("details"); sec.className = "fr-group"; sec.open = true;
        const sum = d.createElement("summary");
        sum.textContent = g.name + (g.role !== "m" && g.roleText ? " · " + g.roleText : "") + (g.statusText ? " · " + g.statusText : "");
        sec.appendChild(sum);
        if (!compact) {
          const row = d.createElement("div"); row.className = "row";
          if (g.status === "member") row.appendChild(frChip(I18N.t("friendsviews.share"), () => frShare(g), d));
          if (g.admin && g.status === "member") { row.appendChild(frChip(I18N.t("friendsviews.invite"), () => frInvite(g), d)); row.appendChild(frChip(I18N.t("friendsviews.stats"), () => frStats(g), d)); }
          row.appendChild(frChip(g.role === "a" ? I18N.t("friendsviews.leave_or_delete") : I18N.t("friendsviews.leave"), () => frLeave(g), d));
          sec.appendChild(row);
        }
        for (const m of g.members) sec.appendChild(frMemberButton(m, g, d));
        if (!g.members.length && g.status === "member") { const p = d.createElement("p"); p.className = "note"; p.textContent = I18N.t("friendsviews.nobody_yet"); sec.appendChild(p); }
        box.appendChild(sec);
      }
    }
    function frBadges(view) {
      const box = $("fr-badges");
      box.textContent = "";
      if (!view) return;
      const b = fx.badges(view, frNowS(), frElapsed(), 6);
      for (const m of b.list) { const dot = el("span", "fr-dot " + m.cls, m.letter); dot.title = m.pseudo + " : " + m.detail; box.appendChild(dot); }
      if (b.total) box.appendChild(el("span", "note", " " + b.active + "/" + b.total));
    }
    function frRender(view) {
      frView = view;
      const on = frOffered();
      $("sec-friends").hidden = !on;
      if (!on) { frStopTimer(); frClosePip(); frApplyMode("section", false); $("fr-badges").textContent = ""; frCloseDialog(); return; }
      const v = fx.buildView(view || {}, frNowS(), frElapsed(), frBy);
      const st = view ? [view.pseudo ? I18N.t("friendsviews.pseudo_is", { pseudo: view.pseudo }) : I18N.t("monitoring.no_pseudo"),
                         view.registered ? I18N.t("monitoring.registered") : I18N.t("monitoring.not_registered"),
                         view.problem ? I18N.t("friendsviews.problem", { problem: view.problem }) : ""].filter(Boolean).join(" · ") : I18N.t("friendsviews.reading");
      $("fr-status").textContent = st;
      // Mon statut (étape 297) : sans lui, « Au shack 1 h » ne montrait rien ; null sur une station sans le champ `me`
      const me = view ? fx.myStatus(view.me, frNowS()) : null;
      // Choix unique (étape 299) : le bouton en cours allumé, une phrase qui dit ce que voient les amis
      $("fr-me").textContent = me ? me.text : "";
      for (const [id, c] of [["fr-shack-cancel", "auto"], ["fr-shack-60", "60"], ["fr-shack-120", "120"]]) {
        const on = !!me && me.choice === c;
        $(id).className = "chip" + (on ? " on" : "");
        $(id).setAttribute("aria-checked", on ? "true" : "false");
      }
      if (view && document.activeElement !== $("fr-pseudo")) $("fr-pseudo").value = view.pseudo || "";
      $("fr-back").hidden = !client.friendsBackPoint;
      frBadges(view);
      frList($("fr-list"), v, false);
      $("fr-updated").textContent = client.friendsAt ? I18N.t("friends.updated", { age: fx.freshness(frElapsed()) }) : "";
      if (frPip) frPipRender();
      if (!frTimer) frTimer = setInterval(() => { if (frOffered()) client.friendsRefresh().catch(() => {}); }, FR_REFRESH_MS);
    }
    function frStopTimer() { if (frTimer) { clearInterval(frTimer); frTimer = null; } }

    // -- affichage : rubrique, en grand, fenêtre détachée
    function frApplyMode(mode, remember) {
      const sec = $("sec-friends");
      if (mode !== "pip") frClosePip();
      if (mode === "big") {
        const parent = sec.parentNode;
        if (parent && !frHome) {
          frHome = { parent: parent, next: sec.nextSibling };
          for (const other of parent.children || []) if (other !== sec && other.tagName && other.tagName.toLowerCase() === "details") other.open = false;
          parent.insertBefore(sec, parent.firstChild);
        }
        sec.open = true;
        sec.className = "listener-hide fr-big";  // i18n-ok (classes CSS)
      } else {
        if (frHome) { frHome.parent.insertBefore(sec, frHome.next || null); frHome = null; }
        sec.className = "listener-hide";
        if (mode === "pip") frOpenPip();
      }
      frMode = mode;
      $("fr-display").value = mode;
      if (remember) store.set("trx.friends.display", mode);
    }
    async function frOpenPip() {
      if (frPip || !fx.pipSupported(root)) return;
      try {
        const win = await root.documentPictureInPicture.requestWindow({ width: 340, height: 460 });
        const link = win.document.createElement("link");
        link.rel = "stylesheet"; link.href = new URL("client.css", location.href).href;
        win.document.head.appendChild(link);
        const theme = document.documentElement.getAttribute("data-theme");
        if (theme) win.document.documentElement.setAttribute("data-theme", theme);
        win.document.title = I18N.t("friendsviews.friends");
        const box = win.document.createElement("div"); box.className = "fr-list"; box.id = "fr-pip-list";
        win.document.body.appendChild(box);
        win.addEventListener("pagehide", () => { frPip = null; if (frMode === "pip") frApplyMode("section", true); });
        frPip = { win: win, box: box };
        frPipRender();
      } catch (e) {
        ui.log(I18N.t("ui.fr_pip_refused"), "warn");
        frApplyMode("section", true);
      }
    }
    function frPipRender() {
      if (!frPip) return;
      frList(frPip.box, fx.buildView(frView || {}, frNowS(), frElapsed(), frBy), true, frPip.win.document);
    }
    function frClosePip() { if (frPip) { const w = frPip.win; frPip = null; try { w.close(); } catch (e) { /* déjà fermée */ } } }

    // -- fenêtres
    function frDialog(title, nodes, buttons) {
      $("fr-dialog-title").textContent = title;
      const body = $("fr-dialog-body");
      body.textContent = "";
      for (const n of nodes) body.appendChild(typeof n === "string" ? el("p", "", n) : n);
      const row = $("fr-dialog-buttons");
      row.textContent = "";
      for (const [label, cls, fn] of buttons) {
        row.appendChild(frChip(label, async () => {
          let keep = false;
          try { keep = fn ? await fn() : false; } catch (e) { fail(e); }
          if (!keep) frCloseDialog();
        }, document, cls));
      }
      $("fr-dialog").hidden = false;
    }
    function frCloseDialog() { $("fr-dialog").hidden = true; }
    function frField(label, input) { const l = el("label", "grow", label + " "); l.appendChild(input); return l; }
    function frInput(value, max) { const i = document.createElement("input"); i.type = "text"; i.value = value || ""; if (max) i.maxLength = max; return i; }
    function frLevelSelect(level) {
      const s = document.createElement("select");
      for (const key of Object.keys(fx.LEVELS)) { const o = el("option", "", fx.LEVELS[key]); o.value = key; s.appendChild(o); }
      s.value = level || "o";
      return s;
    }
    function frCheck(label, checked) {
      const l = el("label", "check"), c = document.createElement("input");
      c.type = "checkbox"; c.checked = !!checked; l.appendChild(c); l.appendChild(el("span", "", " " + label));
      return { label: l, input: c };
    }

    function frOpenMember(m, g) {
      const plan = fx.qsyPlan(m, { pttState: frPtt(), rigHz: frRigHz() });
      const nodes = [el("p", "", m.label + " · " + m.detail)].concat(m.lines.map((l) => el("p", "note", l)));
      const buttons = [];
      if (m.qsy) {
        if (!plan.ok) nodes.push(el("p", "fr-warn", plan.text));
        else {
          nodes.push(el("p", "", plan.text));
          for (const w of plan.warnings.filter((x) => x.level !== "info")) nodes.push(el("p", w.level === "strong" ? "fr-strong" : "fr-warn", w.text));
          buttons.push([I18N.t("friendsviews.go_to_frequency"), "primary", async () => {
            const res = await client.friendsQsy(m);
            frFail(res);
          }]);
        }
      }
      if (g && g.admin && g.status === "member" && m.raw && m.raw.role !== "a") {
        buttons.push([m.raw.role === "c" ? I18N.t("friendsviews.remove_coadmin") : I18N.t("friendsviews.name_coadmin"), "chip", async () => {
          frFail(await client.friendsAction("role", { g: g.g, member: m.id, role: m.raw.role === "c" ? "m" : "c" }));
        }]);
        buttons.push([I18N.t("friendsviews.exclude_ask"), "chip", async () => { frConfirmExclude(g, m); return true; }]);
      }
      buttons.push([I18N.t("common.close"), "chip", null]);
      frDialog(m.pseudo + (g ? " · " + g.name : ""), nodes, buttons);
    }
    function frConfirmExclude(g, m) {
      frDialog(I18N.t("ui.fr_exclude_title", { pseudo: m.pseudo }), [I18N.t("ui.fr_exclude_confirm", { pseudo: m.pseudo, group: g.name })], [
        [I18N.t("friendsviews.exclude"), "danger", async () => { frFail(await client.friendsAction("exclude", { g: g.g, member: m.id })); }],
        [I18N.t("common.cancel"), "chip", null]]);
    }
    function frShare(g) {
      const share = g.share || {};
      const level = frLevelSelect(share.level);
      const text = frInput(share.text || "", 16);
      const presets = (frView && frView.texts) || [];
      const invisible = frCheck(I18N.t("friendsviews.invisible"), share.invisible);
      const hide = frCheck(I18N.t("friendsviews.hide_absence"), share.hide_absence);
      const nodes = [frField(I18N.t("friendsviews.i_share"), level), frField(I18N.t("ui.fr_text_field"), text)];
      if (presets.length) nodes.push(el("p", "note", I18N.t("ui.fr_saved_texts", { texts: presets.join(", ") })));
      nodes.push(invisible.label, hide.label, el("p", "note", I18N.t("friendsviews.next_request")));
      frDialog(I18N.t("friendsviews.share_title", { name: g.name }), nodes, [
        [I18N.t("common.save"), "primary", async () => {
          const args = { g: g.g, level: level.value, invisible: invisible.input.checked, hide_absence: hide.input.checked };
          if (level.value === "x") {
            const t = fx.cleanText(text.value);
            if (!t) { ui.log(I18N.t("ui.fr_text_refused"), "warn"); return true; }
            args.text = t;
          }
          frFail(await client.friendsAction("share", args));
        }],
        [I18N.t("common.cancel"), "chip", null]]);
    }
    async function frInvite(g) {
      const res = frFail(await client.friendsAction("invite", { g: g.g, days: 7 }));
      if (!res || !res.ok) return;
      const url = res.data.url;
      const buttons = [[I18N.t("common.copy"), "primary", async () => {
        try { await navigator.clipboard.writeText(url); ui.log(I18N.t("ui.fr_invite_copied"), ""); } catch (e) { ui.log(I18N.t("ui.fr_copy_refused"), "warn"); }
        return true;
      }]];
      if (navigator.share) buttons.push([I18N.t("common.share"), "chip", async () => { try { await navigator.share({ title: I18N.t("friendsviews.invite_subject"), url: url }); } catch (e) { /* annulé */ } return true; }]);
      buttons.push([I18N.t("common.close"), "chip", null]);
      frDialog(I18N.t("ui.fr_invite_title", { name: g.name }), [
        I18N.t("ui.fr_invite_valid", { days: res.data.days }),
        el("p", "fr-url", url),
        el("p", "note", I18N.t("friendsviews.invite_auto"))], buttons);
    }
    function frJoin() {
      const url = document.createElement("textarea"); url.rows = 3;
      const name = frInput("", 24);
      const level = frLevelSelect("o");
      const nodes = [frField(I18N.t("friendsviews.invitation_received"), url), frField(I18N.t("friendsviews.group_name_local"), name)]
        .concat(fx.CONSENT.map((c) => el("p", "note", c)), [frField(I18N.t("friendsviews.i_share"), level)]);
      frDialog(I18N.t("friendsviews.join_title"), nodes, [
        [I18N.t("friendsviews.accept_join"), "primary", async () => {
          const link = fx.cleanInvitation(url.value);
          if (!link) { ui.log(I18N.t("ui.fr_paste_invitation"), "warn"); return true; }
          const res = frFail(await client.friendsAction("join", { url: link, name: name.value.trim() }));
          if (!res || !res.ok) return true;
          if (level.value !== "o") frFail(await client.friendsAction("share", { g: res.data.g, level: level.value }));
          ui.log(I18N.t("rigsession.friends_join_sent"), "");
        }],
        [I18N.t("common.cancel"), "chip", null]]);
    }
    function frCreate() {
      const name = frInput("", 24);
      frDialog(I18N.t("friendsviews.create_group"), [frField(I18N.t("friendsviews.group_name"), name), el("p", "note", I18N.t("ui.fr_create_note"))], [
        [I18N.t("friendsviews.create"), "primary", async () => {
          if (!name.value.trim()) return true;
          frFail(await client.friendsAction("create", { name: name.value.trim() }));
        }],
        [I18N.t("common.cancel"), "chip", null]]);
    }
    function frLeave(g) {
      const buttons = [[I18N.t("friendsviews.leave_group"), "chip", async () => { frFail(await client.friendsAction("leave", { g: g.g })); }]];
      if (g.role === "a") buttons.unshift([I18N.t("ui.fr_delete_all"), "danger", async () => { frFail(await client.friendsAction("delete", { g: g.g })); }]);
      buttons.push([I18N.t("common.cancel"), "chip", null]);
      frDialog(g.name, [g.role === "a" ? I18N.t("friendsviews.leave_admin") : I18N.t("friendsviews.leave_question")], buttons);
    }
    async function frStats(g) {
      const res = await client.friends("stats", { g: g.g });
      if (!frFail(res) || !res.ok) return;
      const pseudos = {};
      for (const m of g.members) pseudos[m.id] = m.pseudo;
      const rows = fx.statsRows(res.data.stats, pseudos);
      const nodes = rows.length ? rows.map((r) => el("p", "", I18N.t("friendsviews.stats_row", { pseudo: r.pseudo, last_active: r.lastActive, days: r.days,
        qso_min: r.qsoMin, rx_min: r.rxMin })))
        : [el("p", "note", I18N.t("friendsviews.no_stats"))];
      nodes.push(el("p", "note", I18N.t("friendsviews.stats_note")));
      frDialog(I18N.t("ui.fr_stats_title", { name: g.name }), nodes, [[I18N.t("common.close"), "chip", null]]);
    }

    if (fx) {
      if (!fx.pipSupported(root)) {                                          // pas de fenêtre détachée : le choix n'est pas proposé
        const select = $("fr-display");
        for (const o of select.options || []) if (o.value === "pip") select.removeChild(o);
      }
      $("fr-display").value = frMode;
      $("fr-by").value = frBy;
      $("fr-display").addEventListener("change", (ev) => frApplyMode(fx.displayMode(ev.target.value, fx.pipSupported(root)), true));
      $("fr-by").addEventListener("change", (ev) => { frBy = ev.target.value === "member" ? "member" : "group"; store.set("trx.friends.by", frBy); frRender(frView); });
      $("fr-refresh").addEventListener("click", () => client.friendsRefresh().catch(fail));
      $("fr-back").addEventListener("click", () => client.friendsBack().then(frFail).catch(fail));
      $("fr-shack-60").addEventListener("click", () => client.friendsAction("shack_for", { minutes: 60 }).catch(fail));
      $("fr-shack-120").addEventListener("click", () => client.friendsAction("shack_for", { minutes: 120 }).catch(fail));
      $("fr-shack-cancel").addEventListener("click", () => client.friendsAction("shack_cancel", {}).catch(fail));
      $("fr-pseudo-save").addEventListener("click", () => {
        const p = fx.cleanPseudo($("fr-pseudo").value);
        if (!p) { ui.log(I18N.t("ui.pseudo_refused"), "warn"); return; }
        client.friendsAction("pseudo", { pseudo: p }).catch(fail);
      });
      $("fr-create").addEventListener("click", frCreate);
      $("fr-join").addEventListener("click", frJoin);
      $("sec-friends").addEventListener("toggle", () => { if ($("sec-friends").open && frOffered()) client.friendsRefresh().catch(() => {}); });
    }

    // ---- monitoring inter-stations (monitoring.js, docs/cdc-monitoring.md § 17, fonction « monitoring », OPÉRATEURS) :
    // aider un opérateur en difficulté ou être aidé ; mêmes actions que le menu 6.5 de TRX Console. Le module n'agit
    // jamais sur le poste ; la station qui aide ne peut que lire et DEMANDER. Fenêtres : celles de la rubrique « Amis ».
    // TRX Console sur le réseau (étape 233) : lien pour les opérateurs ADMINISTRATEURS (hello.remote_console)
    function rcRender() {
      const rc = client.connected && !client.isListener() && client.hello ? client.hello.remote_console : null;
      const port = rc && Number.isInteger(rc.port) && rc.port >= 1024 && rc.port <= 65535 ? rc.port : null;
      const host = String(window.location.hostname || "");
      $("sec-console").hidden = !port || !host;
      // toujours en HTTPS (même certificat), sur l'adresse par laquelle cet appareil joint déjà la station
      if (port && host) $("rc-open").href = "https:" + "//" + (host.includes(":") ? "[" + host + "]" : host) + ":" + port + "/";
    }

    const mx = root.TrxMonitoring || null;
    const MO_REFRESH_MS = 15000;
    let moView = null, moTimer = null;
    function moOffered() { return !!(mx && client.monitoringOffered && client.connected && !client.isListener()); }
    function moDo(action, args) { return client.monitoringAction(action, args || {}); }
    function moStopTimer() { if (moTimer) { clearInterval(moTimer); moTimer = null; } }

    function moRender(view) {
      moView = view;
      const on = moOffered();
      $("sec-monitoring").hidden = !on;
      if (!on) { moStopTimer(); return; }
      $("mo-status").textContent = mx.status(view);
      if (view && document.activeElement !== $("mo-pseudo")) $("mo-pseudo").value = view.pseudo || "";
      const box = $("mo-list");
      box.textContent = "";
      const links = (view && view.links) || [];
      const waiting = links.filter((l) => mx.level(l) === "warn").length;
      $("mo-badge").textContent = links.length ? " " + links.length + (waiting ? " · " + I18N.t("ui.mo_to_see", { n: waiting }) : "") : "";
      if (view && !links.length) box.appendChild(el("p", "note", I18N.t("monitoringscreen.no_link")));
      for (const l of links) box.appendChild(moCard(mx.linkView(l)));
      if (!moTimer) moTimer = setInterval(() => { if (moOffered() && $("sec-monitoring").open) client.monitoringRefresh().catch(() => {}); }, MO_REFRESH_MS);
    }

    function moCard(v) {
      const card = el("div", "mo-card mo-" + v.level);  // i18n-ok (classes CSS)
      card.appendChild(el("p", "mo-title", v.title));
      if (v.details.length) card.appendChild(el("p", "note", v.details.join(" · ")));
      if (v.raw.role === "receiver" && v.raw.state !== "confirm") for (const line of mx.stationLines(v.raw)) card.appendChild(el("p", "note", line));
      const row = el("div", "row");
      const LABELS = { fingerprint: "monitoringscreen.action_fingerprint", assist: "monitoringscreen.action_assist",       // clés des textes
                       report: "monitoringscreen.action_report", download: "monitoringscreen.action_download",
                       answer: "monitoringscreen.action_answer", send_report: "monitoringscreen.action_send_report",
                       profile: "monitoringscreen.action_profile", pause: "monitoringscreen.action_pause",
                       resume: "monitoringscreen.action_resume", end: "common.finish", events: "monitoringscreen.action_events" };
      const acts = v.raw.role === "receiver" && v.raw.state !== "confirm" ? ["events"].concat(v.actions) : v.actions;
      for (const a of acts) row.appendChild(frChip(LABELS[a] ? I18N.t(LABELS[a]) : a, () => moAct(a, v.raw).catch(fail), document, a === "end" ? "danger" : "chip"));
      card.appendChild(row);
      return card;
    }

    function moProfileNodes() {
      const sel = document.createElement("select");
      for (const key of Object.keys(mx.PROFILES)) { const o = el("option", "", mx.PROFILES[key].label); o.value = key; sel.appendChild(o); }
      sel.value = "diagnostic";
      const fm = frCheck(I18N.t("monitoringscreen.send_frequency"), false);
      return { nodes: [frField(I18N.t("ui.mo_what_you_send"), sel), fm.label], get: () => mx.profile(sel.value, fm.input.checked) };
    }

    function moFingerprint(link) {
      /* Les 6 chiffres comparés de vive voix ; différents = liaison refusée et effacée. Station aidée : profil ensuite. */
      const nodes = [el("p", "mo-fp", link.fingerprint || "?"),
                     I18N.t("monitoringscreen.compare_digits")];
      let prof = null;
      if (link.role === "emitter") {
        prof = moProfileNodes();
        nodes.push(I18N.t("monitoringscreen.choose_profile"));
        nodes.push(...prof.nodes);
      }
      frDialog(I18N.t("monitoringscreen.fingerprint_title", { pseudo: link.pseudo || "?" }), nodes, [
        [I18N.t("monitoringscreen.same_digits"), "chip", async () => {
          const args = { peer: link.peer };
          if (prof) args.profile = prof.get();
          const res = await moDo("confirm", args);
          if (res && res.ok) ui.log(I18N.t("ui.mo_link_active", { pseudo: link.pseudo || "?" }), "");
        }],
        [I18N.t("monitoringscreen.different_digits"), "danger", async () => {
          await moDo("end", { peer: link.peer });
          ui.log(I18N.t("ui.mo_digits_differ"), "warn");
        }],
        [I18N.t("ui.mo_later"), "chip", null]]);
    }

    async function moAct(action, link) {
      if (action === "fingerprint") { moFingerprint(link); return; }
      if (action === "events") {
        const res = await client.monitoring("received", { peer: link.peer, limit: 20 });
        const list = res && res.ok && Array.isArray(res.data) ? res.data : [];
        frDialog(I18N.t("ui.mo_events_title", { pseudo: link.pseudo || "?" }),
                 list.length ? list.map((e) => el("p", "note", mx.eventLine(e))) : [I18N.t("monitoringscreen.no_events")], [[I18N.t("common.close"), "chip", null]]);
        return;
      }
      if (action === "assist") {
        const sel = document.createElement("select");
        for (const h of mx.HOURS) { const o = el("option", "", I18N.plural("ui.hours", h)); o.value = String(h); sel.appendChild(o); }
        sel.value = "2";
        frDialog(I18N.t("monitoringscreen.assist_title"), [I18N.t("monitoringscreen.assist_text"), frField(I18N.t("diffusiondialog.duration"), sel)],
                 [[I18N.t("monitoringscreen.request"), "chip", async () => { await moDo("request_assist", { peer: link.peer, duration_s: Number(sel.value) * 3600 }); }], [I18N.t("common.cancel"), "chip", null]]);
        return;
      }
      if (action === "report") { await moDo("request_report", { peer: link.peer }); ui.log(I18N.t("ui.mo_report_requested"), ""); return; }
      if (action === "download") {
        const res = await client.monitoringReport(link.peer);
        if (!res || !res.ok) { ui.log(I18N.t("rigsession.monitoring_refused", { detail: web.reasonText(res && res.reason, res && res.detail, res && res.ort) }), "warn"); return; }
        const url = URL.createObjectURL(new Blob([res.bytes], { type: "application/zip" }));
        const a = el("a"); a.href = url; a.download = res.name; document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        return;
      }
      if (action === "answer") {
        const req = link.request || {};
        const text = req.snapshot
          ? I18N.t("monitoring.request_report", { pseudo: link.pseudo || "?" })
          : I18N.t("monitoring.request_assist", { pseudo: link.pseudo || "?", hours: Math.round((req.assist || 0) / 360) / 10 });
        frDialog(I18N.t("monitoringscreen.request_from", { pseudo: link.pseudo || "?" }), [text],
                 [[I18N.t("monitoringscreen.accept"), "chip", async () => { await moDo("answer", { peer: link.peer, accept: true }); }],
                  [I18N.t("monitoringscreen.refuse"), "danger", async () => { await moDo("answer", { peer: link.peer, accept: false }); }]]);
        return;
      }
      if (action === "send_report") { await moDo("send_report", { peer: link.peer }); ui.log(I18N.t("ui.mo_report_preparing"), ""); return; }
      if (action === "profile") {
        const prof = moProfileNodes();
        frDialog(I18N.t("monitoringscreen.profile_title", { pseudo: link.pseudo || "?" }), prof.nodes,
                 [[I18N.t("common.save"), "chip", async () => { await moDo("profile", { peer: link.peer, profile: prof.get() }); }], [I18N.t("common.cancel"), "chip", null]]);
        return;
      }
      if (action === "pause" || action === "resume") { await moDo("pause", { peer: link.peer, paused: action === "pause" }); return; }
      if (action === "end") {
        const purge = frCheck(I18N.t("monitoringscreen.purge"), true);
        const nodes = [I18N.t("monitoringscreen.end_text", { pseudo: link.pseudo || "?" })];
        if (link.role === "receiver") nodes.push(purge.label);
        frDialog(I18N.t("monitoringscreen.end_title"), nodes,
                 [[I18N.t("common.finish"), "danger", async () => { await moDo("end", { peer: link.peer, purge: link.role === "receiver" && purge.input.checked }); }], [I18N.t("common.cancel"), "chip", null]]);
      }
    }

    function moInvite() {
      moDo("invite").then((res) => {
        if (!res || !res.ok || !res.data) return;
        frDialog(I18N.t("monitoringscreen.help_someone"), [el("p", "mo-fp", res.data.code), I18N.t("monitoringscreen.dictate_code")],
                 [[I18N.t("common.close"), "chip", null]]);
      }).catch(fail);
    }

    function moJoin() {
      const code = frInput("", 16);
      frDialog(I18N.t("monitoringscreen.be_helped"), [I18N.t("monitoringscreen.join_text"), frField(I18N.t("monitoringscreen.code_label"), code)],
               [[I18N.t("monitoringscreen.join"), "chip", async () => {
                 const c = mx.normalizeCode(code.value);
                 if (!c) { ui.log(I18N.t("ui.mo_code_invalid"), "warn"); return true; }
                 const res = await moDo("join", { code: c });
                 if (res && res.ok && res.data) setTimeout(() => moFingerprint({ peer: res.data.peer, pseudo: res.data.pseudo, role: "emitter", fingerprint: res.data.fingerprint }), 0);
               }], [I18N.t("common.cancel"), "chip", null]]);
    }

    if (mx) {
      $("mo-refresh").addEventListener("click", () => client.monitoringRefresh().catch(fail));
      $("mo-invite").addEventListener("click", moInvite);
      $("mo-join").addEventListener("click", moJoin);
      $("mo-pseudo-save").addEventListener("click", () => {
        const p = fx ? fx.cleanPseudo($("mo-pseudo").value) : $("mo-pseudo").value.trim();
        if (!p) { ui.log(I18N.t("ui.pseudo_refused"), "warn"); return; }
        moDo("pseudo", { pseudo: p }).catch(fail);
      });
      $("sec-monitoring").addEventListener("toggle", () => { if ($("sec-monitoring").open && moOffered()) client.monitoringRefresh().catch(() => {}); });
    }

    // ---- diffusion en direct (diffusion.js, docs/diffusion-cahier-des-charges.md, lot D2) : opérateurs seulement ;
    // l'état vient de state.diffusion à chaque message state ; indicateur « DIFFUSION » toujours visible pendant une
    // diffusion ; l'avertissement de responsabilité est confirmé une fois (la station s'en souvient).
    const dfx = root.TrxDiffusion || null;
    let difFormReady = false;
    const difMetaBoxes = [];

    function difBuildForm() {
      difFormReady = true;
      const sel = $("dif-hours");
      sel.replaceChildren();
      for (const h of dfx.HOURS) {
        const o = document.createElement("option");
        o.value = h === null ? "none" : String(h);
        o.textContent = dfx.hoursLabel(h);
        if (h === dfx.DEFAULT_HOURS) o.selected = true;
        sel.appendChild(o);
      }
      const box = $("dif-meta");
      box.replaceChildren(el("span", "note", I18N.t("ui.dif_meta_title")));
      difMetaBoxes.length = 0;
      for (const [key, label] of dfx.META) {
        const lab = el("label", "check", "");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = key;
        cb.checked = dfx.DEFAULT_META.includes(key);
        difMetaBoxes.push(cb);
        lab.appendChild(cb);
        lab.appendChild(el("span", "", " " + label));
        box.appendChild(lab);
      }
    }

    function difRender(v) {
      const d = dfx && v && v.connected ? v.diffusion : null;
      $("sec-diffusion").hidden = !d;
      const ind = d ? dfx.indicator(d) : null;
      $("dif-ind").hidden = !ind;
      if (ind) {
        $("dif-ind").textContent = ind.text;
        $("dif-ind").className = "chip dif-ind listener-hide " + ind.level;  // i18n-ok (classes CSS)
        $("dif-ind").title = ind.title;
      }
      if (!d) return;
      if (!difFormReady) difBuildForm();
      $("dif-status").textContent = dfx.status(d);
      $("dif-badge").textContent = d.active ? I18N.t("ui.dif_live") : "";
      $("dif-form").hidden = !!d.active || d.enabled === false || !!d.problem;
      $("dif-stop").hidden = !d.active;
      $("dif-page").textContent = d.listen_page || "—";
      if (d.listen_page) $("dif-page").href = d.listen_page;
      if (d.listener_user) $("dif-user").textContent = d.listener_user;
    }

    function difReport(res, okText) {
      if (res && res.ok) { if (okText) ui.log(okText, ""); return true; }
      ui.log(I18N.t("rigsession.diffusion_refused", { detail: web.reasonText(res && res.reason, res && res.detail, res && res.ort) }), "warn");
      return false;
    }

    async function difStart() {
      const form = { access: $("dif-public").checked ? "public" : "prive", hours: $("dif-hours").value,
                     voice: $("dif-voice").checked, meta: difMetaBoxes.filter((b) => b.checked).map((b) => b.value),
                     pseudo: $("dif-pseudo").value, indicatif: $("dif-indicatif").value, message: $("dif-message").value };
      const r = dfx.startArgs(form);
      if (r.error) { ui.log(I18N.t("rigsession.diffusion_refused", { detail: r.error }), "warn"); return; }
      let res = await client.diffusion("start", r.args);
      if (res && !res.ok && res.reason === "diffusion_confirm_required") {
        if (!window.confirm(dfx.WARNING)) return;
        res = await client.diffusion("start", Object.assign({}, r.args, { confirm: true }));
      }
      difReport(res, I18N.t("rigsession.diffusion_started"));
    }

    function difShowPassword(data) {
      if (!data) return;
      $("dif-user").textContent = data.listener_user || "—";
      $("dif-password").textContent = data.listener_password || I18N.t("diffusiondialog.password_none");
    }

    if (dfx) {
      $("dif-ind").addEventListener("click", () => { $("sec-diffusion").open = true; $("sec-diffusion").scrollIntoView({ block: "start" }); });
      $("dif-start").addEventListener("click", () => { difStart().catch(fail); });
      $("dif-stop").addEventListener("click", () => {
        if (!window.confirm(I18N.t("diffusiondialog.stop_question"))) return;
        client.diffusion("stop").then((res) => difReport(res, I18N.t("rigsession.diffusion_stopped"))).catch(fail);
      });
      $("dif-reveal").addEventListener("click", () => {
        client.diffusion("reveal").then((res) => { if (difReport(res, "")) difShowPassword(res.data); }).catch(fail);
      });
      $("dif-generate").addEventListener("click", () => {
        if (!window.confirm(I18N.t("diffusiondialog.new_question"))) return;
        client.diffusion("listener", { generate: true })
          .then((res) => { if (difReport(res, I18N.t("rigsession.diffusion_new_password"))) difShowPassword(res.data); }).catch(fail);
      });
      $("dif-copy").addEventListener("click", async () => {
        const a = $("dif-page").textContent;
        try { await navigator.clipboard.writeText(a); ui.log(I18N.t("ui.dif_page_copied"), ""); } catch (e) { fail(e); }
      });
    }

    // ---- spatialisation stéréo de la réception (spatial.js, docs/spatialisation-cahier-des-charges.md) : traitement de cet
    // appareil seulement, visiteurs compris ; la station n'en sait rien. Réglages gardés par le navigateur.
    const spx = root.TrxSpatial || null;
    let stSet = spx ? spx.validate(safeJson(store.get("trx.spatial", "null"))) : null;
    let stAb = false, stFailed = false, stCorr = null, stOffTimer = null;
    function stActive() { return !!(spx && stSet.on && !stSet.monoOut && !stFailed); }
    function stParams() { return spx.params(stSet, stAb); }
    function stWorklet(ctx) {
      if (!ctx.audioWorklet || typeof AudioWorkletNode === "undefined") return Promise.reject(new Error(I18N.t("ui.no_audioworklet")));
      if (!ctx.trxSpatial) ctx.trxSpatial = ctx.audioWorklet.addModule("spatial.js");
      return ctx.trxSpatial;
    }
    function stStats(d) {
      if (typeof d.corr === "number" && Number.isFinite(d.corr)) stCorr = d.corr;
      stRenderMeter();
    }
    function stPost() { if (rxGraph && rxGraph.st) rxGraph.st.port.postMessage(stParams()); }
    function stSave() { store.set("trx.spatial", JSON.stringify(stSet)); }
    function stChange(next) {
      /* Nouveaux réglages : fondu dans le traitement en place ; chaîne refaite seulement si ST entre ou sort. */
      const before = stActive();
      if (next.on && !stSet.on) {
        stFailed = false;                                                           // nouvel essai à chaque mise en service
        if (typeof sdrSplit !== "undefined" && sdrSplit) {                        // séparation TRX / SDR et ST exclusives
          sdrSplit = 0;
          try { store.set("trx.sdr.split", "0"); $("sdr-split").value = "0"; } catch (e) { /* sans stockage */ }
          ui.log(I18N.t("ui.st_split_off"), "");
          if (typeof sdrRoute === "function") sdrRoute();
        }
        if (sx && scr.rx) {                                                         // débrouillage et ST exclusifs (2026-11-03)
          scr.rx = false; scrRender();
          ui.log(I18N.t("spatialhub.descrambler_off"), "");
          if (!before) { stSet = spx.validate(next); stSave(); rxApply(); return; }  // chaîne refaite sans le débrouillage
        }
      }
      stSet = spx.validate(next);
      stSave();
      const after = stActive();
      if (stOffTimer !== null) { window.clearTimeout(stOffTimer); stOffTimer = null; }
      if (before === after) stPost();
      else if (after) rxApply();
      else { stPost(); stOffTimer = window.setTimeout(() => { stOffTimer = null; if (!stActive()) rxApply(); }, 80); }   // fondu vers le mono d'abord
      stRender();
    }
    function stRenderMeter() {
      const live = !!(rxGraph && rxGraph.st) && stCorr !== null;
      $("st-corr-text").textContent = live ? stCorr.toFixed(2) : "—";
      $("st-corr-mask").style.width = percentLeft(live ? Math.max(0, Math.min(1, 1 - stCorr)) : 0);
    }
    function stRender() {
      if (!spx) return;
      const chip = $("st-direct");
      chip.className = "chip st-direct" + (stActive() ? " on" : "") + (stSet.monoOut ? " dim" : "");  // i18n-ok (classes CSS)
      chip.textContent = stSet.on && !stSet.monoOut ? "ST ON" : "ST";
      $("st-on").checked = stSet.on; $("st-mono").checked = stSet.monoOut;
      for (const b of $("st-presets").children) b.className = "chip" + (b.value === stSet.preset ? " on" : "");
      $("st-width").value = stSet.width; $("st-width-text").textContent = " " + stSet.width + " %";
      $("st-presence").value = stSet.presence; $("st-presence-text").textContent = " " + stSet.presence + " %";
      $("st-balance").value = stSet.balance;
      $("st-balance-text").textContent = " " + (stSet.balance === 0 ? I18N.t("spatialdialog.balance_center")
        : I18N.t(stSet.balance < 0 ? "spatialdialog.balance_left" : "spatialdialog.balance_right", { amount: Math.abs(stSet.balance) }));
      const preset = { preset: stFailed || !stSet.on ? "" : spx.label(stSet) };
      const state = stFailed ? I18N.t("ui.st_unavailable") : !stSet.on ? I18N.t("spatialdialog.state_off")
        : stSet.monoOut ? I18N.t("ui.st_mono_out") : stSet.preset === "mono" ? I18N.t("spatialdialog.state_mono")
        : !rxMedia ? I18N.t("ui.st_waiting", preset) : rxGraph && rxGraph.st ? I18N.t(stAb ? "spatialdialog.state_playing_ab" : "spatialdialog.state_playing", preset)
        : I18N.t("ui.st_starting", preset);
      $("st-state").textContent = I18N.t("spatialdialog.state", { state: state });
      stRenderMeter();
    }
    if (spx) {
      for (const [key, preset] of Object.entries(spx.PRESETS)) {
        const b = el("button", "chip", preset.label); b.value = key;
        b.addEventListener("click", () => stChange(Object.assign(spx.choose(stSet, key), { on: true })));
        $("st-presets").appendChild(b);
      }
      $("st-on").addEventListener("change", (ev) => stChange(Object.assign({}, stSet, { on: ev.target.checked })));
      $("st-mono").addEventListener("change", (ev) => stChange(Object.assign({}, stSet, { monoOut: ev.target.checked })));
      for (const key of ["width", "presence", "balance"]) {
        $("st-" + key).addEventListener("input", (ev) => stChange(Object.assign({}, stSet, { [key]: parseFloat(ev.target.value) })));
        $("st-" + key).addEventListener("dblclick", () => {                                  // double appui : valeur du préréglage
          const p = spx.PRESETS[stSet.preset];
          stChange(Object.assign({}, stSet, { [key]: key === "balance" || !p ? 0 : p[key] }));
        });
      }
      const ab = $("st-ab");
      ab.addEventListener("pointerdown", () => { stAb = true; stPost(); stRender(); });
      for (const type of ["pointerup", "pointercancel", "pointerleave"]) ab.addEventListener(type, () => { if (stAb) { stAb = false; stPost(); stRender(); } });
      ab.addEventListener("contextmenu", (ev) => { if (ev && ev.preventDefault) ev.preventDefault(); });
      // Bouton ST : appui = marche / arrêt ; appui long = rubrique
      const chip = $("st-direct");
      let pressTimer = null, longDone = false;
      const openSection = () => { $("sec-spatial").open = true; $("sec-spatial").scrollIntoView({ block: "start" }); };
      chip.addEventListener("pointerdown", () => {
        longDone = false;
        if (pressTimer !== null) window.clearTimeout(pressTimer);
        pressTimer = window.setTimeout(() => { pressTimer = null; longDone = true; openSection(); }, 550);
      });
      for (const type of ["pointerup", "pointercancel", "pointerleave"]) {
        chip.addEventListener(type, () => { if (pressTimer !== null) { window.clearTimeout(pressTimer); pressTimer = null; } });
      }
      chip.addEventListener("click", () => {
        if (longDone) { longDone = false; return; }
        if (stSet.monoOut) { openSection(); return; }                                   // sortie mono déclarée : rien à allumer
        const on = !stSet.on;
        if (on && store.get("trx.spatial.seen", "") !== "1") {
          store.set("trx.spatial.seen", "1");
          ui.log(I18N.t("ui.st_headphones"), "");
        }
        stChange(Object.assign({}, stSet, { on }));
      });
      chip.addEventListener("contextmenu", (ev) => { if (ev && ev.preventDefault) ev.preventDefault(); });
      stRender();
    } else {
      $("sec-spatial").hidden = true; $("st-direct").hidden = true;
    }
    if (lay) layout = new lay.Layout(document, { store: store, onShown: layoutShown, now: () => performance.now(),
                                                 setTimeout: (fn, ms) => window.setTimeout(fn, ms), clearTimeout: (t) => window.clearTimeout(t) });
    $("insecure").hidden = window.isSecureContext;
    $("origin").textContent = location.origin;                                   // à recopier tel quel dans le réglage de Chrome
    $("client-id").value = store.get("trx.client_id", "");                         // seul l'identifiant est mémorisé, jamais le mot de passe
    $("text-size").value = store.get("trx.text", "auto");
    $("layout-select").value = store.get("trx.layout", "auto");

    $("connect").addEventListener("click", async () => {
      const clientId = $("client-id").value.trim(), password = $("password").value;
      if (!clientId || !password) { ui.log(I18N.t("ui.login_missing"), "warn"); return; }
      audio.muted = $("mute").checked; sdrMirrorOutput();
      if (alertLevel !== "off") alertContext();          // le navigateur n'autorise le son qu'après un geste : on le prépare ici  // i18n-ok
      try {
        store.set("trx.mic", $("mic-select").value);
        store.set("trx.out", $("out-select").value);
        await client.connect({ clientId: clientId, password: password, useMic: $("use-mic").checked,
                               micProfile: $("mic-profile").value, micCustom: { echo: $("mic-echo").checked, noise: $("mic-noise").checked },
                               micDeviceId: $("mic-select").value || null,
                               ignoreRigWarning: $("ignore-rig-warning").checked, keepAwake: $("keep-awake").checked,
                               reconnectWindowS: Number($("reconnect-select").value) });
        rigAudio = client.rigAudio;
        await refreshDevices();                                                  // les noms apparaissent une fois le micro autorisé
        await applyOutput();
        store.set("trx.client_id", clientId);
        rememberLogin(clientId, password);                                       // le navigateur propose d'enregistrer
        $("password").value = "";                                               // ne reste pas dans la page une fois connecté
      } catch (err) { fail(err); }
    });
    function rememberLogin(id, password) {
      /* Proposition d'enregistrement du mot de passe (Chrome : API Credential Management). Chrome ne l'enregistre
         JAMAIS sur une page dont le certificat n'est pas reconnu (certificat auto-signé accepté à la main). */
      try {
        if (window.PasswordCredential && navigator.credentials && navigator.credentials.store) {
          navigator.credentials.store(new window.PasswordCredential({ id: id, password: password, name: id })).catch(() => {});
        }
      } catch (e) { /* navigateur sans cette API : le gestionnaire de mots de passe suit le formulaire */ }
    }
    if (typeof window.fetch === "function") {                                   // autorité de la station : lien proposé
      window.fetch("station-ca.crt", { method: "HEAD", cache: "no-store" })
        .then((r) => { $("ca-hint").hidden = !(r && r.ok); }).catch(() => {});
    }
    $("login-form").addEventListener("submit", (ev) => { if (ev && ev.preventDefault) ev.preventDefault(); $("connect").click(); });
    $("password").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { if (ev.preventDefault) ev.preventDefault(); $("connect").click(); } });  // i18n-ok (touche)
    $("disconnect").addEventListener("click", () => client.disconnect());
    $("reconnect-cancel").addEventListener("click", () => client.cancelReconnect());
    $("reconnect-select").value = ["0", "15", "30", "60"].includes(store.get("trx.reconnect", "15")) ? store.get("trx.reconnect", "15") : "15";
    $("reconnect-select").addEventListener("change", (ev) => store.set("trx.reconnect", ev.target.value));
    window.addEventListener("online", () => client.onNetworkOnline());
    $("splash").addEventListener("click", () => { $("splash").hidden = true; });               // un appui passe l'image d'accueil
    window.setTimeout(() => { $("splash").hidden = true; }, 2600);                                // et elle disparaît de toute façon (la feuille de style l'efface déjà à 2 s)
    $("armed").addEventListener("change", (ev) => client.setArmed(ev.target.checked));
    $("ptt").addEventListener("click", () => client.pressPtt().catch(fail));
    $("stop").addEventListener("click", () => client.stop().catch(fail));
    // STOP maintenu 3 s : fenêtre « Se déconnecter » / « Arrêter le TRX à distance » (lot P2 de l'alimentation, décision
    // de l'utilisateur du 2026-11-19 ; avant : déconnexion directe, étape 194). Le premier appui a déjà remis en réception.
    const STOP_HOLD_MS = 3000;
    const stopSub = () => client.powerOffered ? I18N.t("powerviews.hold_power") : I18N.t("powerviews.hold_disconnect");
    let stopHold = null;
    function stopHoldCancel() {
      if (!stopHold) return;
      window.clearInterval(stopHold);
      stopHold = null;
      $("stop-sub").textContent = stopSub();
      $("stop").classList.remove("holding");
    }
    $("stop").addEventListener("pointerdown", (ev) => {
      stopHoldCancel();
      if ($("stop").disabled) return;
      // Doigt ou souris « capturés » par STOP : si la page bouge pendant le maintien (voyants qui arrivent après
      // l'allumage du poste), le pointeur ne « sort » pas du bouton et le maintien n'est pas annulé (essai du 2026-11-20)
      if (ev && ev.pointerId !== undefined && $("stop").setPointerCapture) {
        try { $("stop").setPointerCapture(ev.pointerId); } catch (e) { /* navigateur sans capture */ }
      }
      const t0 = Date.now();
      $("stop").classList.add("holding");
      $("stop-sub").textContent = I18N.t("powerviews.hold_left", { seconds: 3 });
      stopHold = window.setInterval(() => {
        const left = STOP_HOLD_MS - (Date.now() - t0);
        if (left > 0) { $("stop-sub").textContent = I18N.t("powerviews.hold_left", { seconds: Math.ceil(left / 1000) }); return; }
        stopHoldCancel();
        if (navigator.vibrate) { try { navigator.vibrate(80); } catch (e) { /* sans vibreur */ } }
        openStopHold();
      }, 100);
    });
    for (const type of ["pointerup", "pointercancel", "pointerleave"]) $("stop").addEventListener(type, stopHoldCancel);
    // -- fenêtre de STOP maintenu : deux choix, puis confirmation de l'arrêt ; Annuler par défaut, et après 15 s
    let stopHoldTimer = null;
    function armStopHoldTimer() {
      if (stopHoldTimer) window.clearTimeout(stopHoldTimer);
      stopHoldTimer = window.setTimeout(closeStopHold, 15000);
    }
    function openStopHold() {
      const choices = client.stopHoldChoices();
      $("stophold-title").textContent = I18N.t("powerviews.hold_question");
      $("stophold-text").textContent = I18N.t("powerviews.already_rx");
      $("stophold-disconnect").hidden = false; $("stophold-power").hidden = false;
      $("stophold-power").disabled = !choices.powerOff;
      $("stophold-reason").hidden = !choices.powerReason;
      $("stophold-reason").textContent = choices.powerReason;
      $("stophold-confirm").hidden = true; $("stophold-confirm").disabled = false;
      $("stophold-cancel").textContent = I18N.t("common.cancel");
      $("stophold-dialog").hidden = false;
      $("stophold-cancel").focus();
      armStopHoldTimer();
    }
    function closeStopHold() {
      if (stopHoldTimer) { window.clearTimeout(stopHoldTimer); stopHoldTimer = null; }
      $("stophold-dialog").hidden = true;
    }
    $("stophold-cancel").addEventListener("click", closeStopHold);
    $("stophold-disconnect").addEventListener("click", () => {
      closeStopHold();
      ui.log(I18N.t("ui.stop_hold_disconnect"), "");
      client.stop().catch(() => {}).then(() => client.disconnect());
    });
    $("stophold-power").addEventListener("click", () => {
      $("stophold-title").textContent = I18N.t("power.confirm_title");
      $("stophold-text").textContent = I18N.t("power.confirm_text");
      $("stophold-disconnect").hidden = true; $("stophold-power").hidden = true; $("stophold-reason").hidden = true;
      $("stophold-confirm").hidden = false;
      $("stophold-cancel").focus();
      armStopHoldTimer();
    });
    $("stophold-confirm").addEventListener("click", async () => {
      $("stophold-confirm").disabled = true;
      if (stopHoldTimer) { window.clearTimeout(stopHoldTimer); stopHoldTimer = null; }
      let res;
      try { res = await client.powerOff(); } catch (e) { res = { ok: false, reason: "no_reply", detail: String(e && e.message || e) }; }
      if (res && res.ok) { closeStopHold(); return; }
      $("stophold-title").textContent = I18N.t("powerviews.off_refused");
      $("stophold-text").textContent = web.reasonText(res && res.reason, res && res.detail, res && res.ort);
      $("stophold-confirm").hidden = true;
      $("stophold-cancel").textContent = I18N.t("common.close");
    });
    // -- fenêtre « Allumage du TRX » (étapes envoyées par la station) et bandeau « POSTE ÉTEINT »
    let powerCloseTimer = null;
    function renderPower(view) {
      if (powerCloseTimer) { window.clearTimeout(powerCloseTimer); powerCloseTimer = null; }
      if (!view || !view.visible) { $("power-dialog").hidden = true; return; }
      const list = $("power-steps");
      list.textContent = "";
      for (const line of view.lines) {
        const li = el("li", line.status, line.label);
        if (line.detail) li.appendChild(el("span", "detail", line.detail));
        list.appendChild(li);
      }
      $("power-dialog-text").textContent = view.text;
      $("power-retry").hidden = !view.canRetry;
      $("power-continue").hidden = !view.canContinue;
      $("power-hide").hidden = !view.canHide && view.status !== "done";
      $("power-hide").textContent = view.status === "done" ? I18N.t("common.close") : I18N.t("common.hide");
      $("power-dialog").hidden = false;
      if (view.autoCloseMs) powerCloseTimer = window.setTimeout(() => client.powerHide(), view.autoCloseMs);
    }
    $("power-hide").addEventListener("click", () => client.powerHide());
    $("power-continue").addEventListener("click", () => client.powerHide());
    $("power-retry").addEventListener("click", () => client.powerOn("button").catch(fail));
    $("power-on").addEventListener("click", () => client.powerOn("button").catch(fail));
    $("stop").addEventListener("contextmenu", (ev) => { if (ev && ev.preventDefault) ev.preventDefault(); });
    $("mode-pill").addEventListener("click", () => {                                 // USB-D <-> LSB-D ; USB -> USB-D ; LSB -> LSB-D ; autre -> USB-D
      if (frequencyLocked()) return;                                                  // émission ou hors liaison : la station refuserait
      client.pressModePill().catch(fail);
    });
    // ---- « Tout afficher » : 30 derniers spots toutes bandes ; la station ne les envoie qu'aux clients qui regardent
    // le spectre : la liste s'y abonne le temps d'être ouverte (sans toucher à la vue HF si elle est déjà ouverte).
    let recentData = null, recentAt = 0, recentOpen = false;
    function renderRecent() {
      const box = $("cluster-recent");
      box.hidden = !recentOpen;
      $("cluster-all").textContent = recentOpen ? I18N.t("ui.cluster_hide_list") : I18N.t("memoriestab.show_all");
      if (!recentOpen) return;
      box.textContent = "";
      const list = sp && recentData ? sp.recentList(recentData, recentAt) : [];
      if (!list.length) {
        box.appendChild(el("div", "note", client.hello && client.hello.spectrum ? I18N.t("ui.cluster_no_spot")
          : I18N.t("clusterandbeeps.needs_spectrum")));
        return;
      }
      const locked = frequencyLocked();
      for (const s of list) {
        const at = new Date(sp.arrivalMs(s));
        const row = el("button", "");
        row.disabled = locked;
        row.title = locked ? I18N.t("ui.spot_qsy_locked") : I18N.t("ui.spot_qsy");
        row.appendChild(el("span", "mono", at.toLocaleTimeString("fr-FR")));
        row.appendChild(el("span", "", s.dx));
        row.appendChild(el("span", "mono", s.khz.toFixed(1)));
        row.appendChild(el("span", "src", [sp.sourceLabel(s), sp.modeLabel(s), s.comment].filter(Boolean).join(" · ")));
        row.addEventListener("click", () => {
          const target = sp.qsyTarget(s, (mode) => client.adaptSpotMode(mode));
          if (!target || frequencyLocked()) return;
          client.qsy(target.hz, target.mode).then((res) => {
            if (res && res.ok) ui.log(I18N.t("ui.qsy_done", { dx: s.dx, khz: s.khz.toFixed(1) }), "");
            else ui.log(res && res.reason ? I18N.t("ui.qsy_refused_reason", { reason: web.reasonText(res.reason, res.detail, res.ort) }) : I18N.t("ui.qsy_refused"), "warn");
          }).catch(fail);
        });
        box.appendChild(row);
      }
    }
    function setRecentOpen(on) {
      if (on === recentOpen) return;
      recentOpen = on;
      syncWatch();
      renderRecent();
    }
    $("cluster-all").addEventListener("click", () => setRecentOpen(!recentOpen));
    // ---- état des flux du Cluster DX (section affichée dès que le module parle ; âges mis à jour toutes les 5 s)
    let clusterData = null, clusterAt = 0;
    function renderCluster() {
      paintBandDots(clusterData && !web.clusterStatusView(clusterData, (performance.now() - clusterAt) / 1000).stale
        ? clusterData.bands : null);                                                 // module muet : pastilles retirées
      if (!clusterData) { $("sec-cluster").hidden = true; return; }
      const view = web.clusterStatusView(clusterData, (performance.now() - clusterAt) / 1000);
      $("sec-cluster").hidden = false;
      $("cluster-dot").className = "cluster-dot " + (view.stale ? "red" : view.health);
      $("cluster-title").textContent = view.stale ? I18N.t("ui.cluster_unknown") : view.title;
      const list = $("cluster-sources");
      list.textContent = "";
      for (const line of view.lines) {
        const item = el("li", "");
        item.appendChild(el("span", "cluster-dot " + line.dot));
        item.appendChild(el("span", "", line.text));
        list.appendChild(item);
      }
      $("cluster-age").textContent = view.staleText || I18N.t("ui.cluster_every_15s");
    }
    window.setInterval(() => { if (clusterData) renderCluster(); }, 5000);

    // ---- signaler un problème : rapport assemblé, RELU par l'utilisateur, puis envoyé à la station ou partagé
    let bugText = "";
    const deviceInfo = () => ({
      userAgent: navigator.userAgent || "", layout: $("app").className,
      screen: I18N.t("ui.report_screen", { width: window.innerWidth, height: window.innerHeight, density: window.devicePixelRatio || 1 }),
      theme: (document.documentElement.getAttribute && document.documentElement.getAttribute("data-theme")) || I18N.t("ui.report_theme_default"),
    });
    $("bug-prepare").addEventListener("click", () => {
      bugText = client.problemReport($("bug-text").value, deviceInfo());
      $("bug-report").textContent = bugText; $("bug-report").hidden = false;
      $("bug-send").disabled = !connectedFlag; $("bug-share").disabled = false;
    });
    $("bug-send").addEventListener("click", () => { if (bugText) client.sendProblemReport(bugText).catch(fail); });
    $("bug-share").addEventListener("click", async () => {
      if (!bugText) return;
      if (navigator.share) {
        try { await navigator.share({ title: I18N.t("ui.report_share_title"), text: bugText }); return; }
        catch (e) { if (e && e.name === "AbortError") return; }                     // partage annulé par l'utilisateur
      }
      try { await navigator.clipboard.writeText(bugText); ui.log(I18N.t("ui.report_copied"), ""); }
      catch (e) { ui.log(I18N.t("ui.report_copy_failed"), "warn"); }
    });
    window.addEventListener("error", (ev) => client.recordError((ev && ev.message) || I18N.t("ui.error_unknown")));
    window.addEventListener("unhandledrejection", (ev) => client.recordError(I18N.t("ui.promise_rejected", { reason: (ev && ev.reason && ev.reason.message) || (ev && ev.reason) || "?" })));

    $("local-release").addEventListener("click", () => {                             // confirmation en deux temps
      if (!releaseArmed) {
        releaseArmed = true;
        $("local-release").textContent = I18N.t("ui.release_confirm");
        releaseTimer = window.setTimeout(resetRelease, 4000);
        return;
      }
      resetRelease();
      client.releaseLocal().catch(fail);
    });
    $("audio-dock-on").addEventListener("change", (ev) => {
      audioDockWanted = !!ev.target.checked;
      store.set("trx.audiodock", audioDockWanted ? "1" : "0");
      syncDock();
    });
    $("hf-dock-on").addEventListener("change", (ev) => {
      hfDockWanted = !!ev.target.checked;
      store.set("trx.hfdock", hfDockWanted ? "1" : "0");
      syncDock();
    });
    $("freq-set").addEventListener("click", () => {
      const hz = parseKilohertz($("freq-input").value);
      if (hz === null) { ui.log(I18N.t("ui.freq_invalid_14200"), "warn"); return; }
      client.setFrequency(hz).catch(fail);
    });
    for (const [key, id] of CONTROLS) {
      const button = $(id);
      if (!DIALOG_KEYS.includes(key)) { button.addEventListener("click", () => client.pressControl(key).catch(fail)); continue; }
      // NR, NB, NOTCH : appui = bascule ; appui long (téléphone) ou double clic (PC) = fenêtre de réglage
      let pressTimer = null, longDone = false, clickTimer = null;
      button.addEventListener("pointerdown", () => {
        longDone = false;
        if (pressTimer !== null) window.clearTimeout(pressTimer);
        pressTimer = window.setTimeout(() => { pressTimer = null; longDone = true; openControlDialog(key); }, 550);
      });
      for (const type of ["pointerup", "pointercancel", "pointerleave"]) {
        button.addEventListener(type, () => { if (pressTimer !== null) { window.clearTimeout(pressTimer); pressTimer = null; } });
      }
      button.addEventListener("click", () => {
        if (longDone) { longDone = false; return; }                                // l'appui long a déjà ouvert la fenêtre
        if (clickTimer !== null) { window.clearTimeout(clickTimer); clickTimer = null; openControlDialog(key); return; }   // double clic
        clickTimer = window.setTimeout(() => { clickTimer = null; client.pressControl(key).catch(fail); }, DOUBLE_CLICK_MS);
      });
      button.addEventListener("contextmenu", (ev) => { if (ev && ev.preventDefault) ev.preventDefault(); });   // appui long Android
    }
    // ---- fenêtre de réglage NR / NB / Notch (refusée par la station pendant l'émission, verrouillée ici aussi)
    let dialogKey = null, levelTimer = null, levelTouched = 0;
    const DIALOG_TITLES = { NR: "rigdialogs.nr_label", NB: "rigdialogs.nb_label", NOTCH: "ui.notch_title" };   // clés des textes
    function levelRange(name) {
      const caps = client.hello && client.hello.capabilities;
      const range = caps && caps.level_ranges ? caps.level_ranges[name] : null;
      return Array.isArray(range) && range.length === 3 && range[1] > range[0] ? range : null;
    }
    function levelText(value, range) {
      return range[2] > 0 ? String(Math.round((value - range[0]) / range[2])) + " / " + Math.round((range[1] - range[0]) / range[2]) : Number(value).toFixed(2);
    }
    function openControlDialog(key) {
      dialogKey = key;
      $("ctl-dialog").hidden = false;
      renderControlDialog(lastView);
    }
    function closeControlDialog() { dialogKey = null; $("ctl-dialog").hidden = true; }
    function renderControlDialog(v) {
      if (dialogKey === null || !v) return;
      const fn = (v.rig && v.rig.functions) || {}, lv = (v.rig && v.rig.levels) || {};
      const locked = !v.connected || v.controlsLocked;
      const notch = dialogKey === "NOTCH";
      $("ctl-dialog-title").textContent = I18N.t(DIALOG_TITLES[dialogKey]);
      $("ctl-dialog-onrow").hidden = notch; $("ctl-notch-row").hidden = !notch;
      if (notch) {
        const current = fn.MN ? "manual" : fn.ANF ? "auto" : "off";
        for (const [kind, id, needs] of [["off", "ctl-notch-off", null], ["auto", "ctl-notch-auto", "ANF"], ["manual", "ctl-notch-manual", "MN"]]) {
          $(id).className = "chip" + (current === kind ? " on" : "");
          $(id).disabled = locked || (needs !== null && !(needs in fn));
        }
      } else {
        $("ctl-dialog-toggle").textContent = fn[dialogKey] ? I18N.t("ui.ctl_on") : I18N.t("ui.ctl_off");
        $("ctl-dialog-toggle").className = "chip" + (fn[dialogKey] ? " on" : "");
        $("ctl-dialog-toggle").disabled = locked || !(dialogKey in fn);
      }
      const range = notch ? null : levelRange(dialogKey);
      const has = !!range && dialogKey in lv;
      $("ctl-level-row").hidden = !has;
      if (has) {
        const slider = $("ctl-level");
        slider.min = String(range[0]); slider.max = String(range[1]); slider.step = String(range[2] > 0 ? range[2] : (range[1] - range[0]) / 100);
        slider.disabled = locked;
        if (performance.now() - levelTouched > 1500) slider.value = String(lv[dialogKey]);   // pas de saut pendant que le doigt règle
        $("ctl-level-text").textContent = levelText(Number(slider.value), range);
      }
      $("ctl-dialog-note").textContent = locked ? I18N.t("rigdialogs.locked_tx") :
        (notch ? "" : has ? "" : I18N.t("ui.ctl_no_level"));
    }
    $("ctl-dialog-toggle").addEventListener("click", () => { if (dialogKey) client.pressControl(dialogKey).catch(fail); });
    for (const [kind, id] of [["off", "ctl-notch-off"], ["auto", "ctl-notch-auto"], ["manual", "ctl-notch-manual"]]) {
      $(id).addEventListener("click", () => client.setNotch(kind).catch(fail));
    }
    $("ctl-level").addEventListener("input", (ev) => {
      const key = dialogKey, range = key ? levelRange(key) : null;
      if (!range) return;
      const value = Number(ev.target.value);
      levelTouched = performance.now();
      $("ctl-level-text").textContent = levelText(value, range);
      window.clearTimeout(levelTimer);
      levelTimer = window.setTimeout(() => client.setLevelValue(key, value).catch(fail), 150);   // une commande à la fin du geste
    });
    $("ctl-dialog-close").addEventListener("click", closeControlDialog);
    let clarTouched = -1e9, clarTimer = null;
    $("clar").addEventListener("input", (ev) => {
      const hz = Number(ev.target.value), name = ev.target.dataset.name || "XIT";
      $("clar-text").textContent = web.clarifierText(hz);
      clarTouched = performance.now();
      window.clearTimeout(clarTimer);
      clarTimer = window.setTimeout(() => client.setOffset(name, hz).catch(fail), 150);   // une commande à la fin du geste
    });
    $("squelch").addEventListener("input", (ev) => {
      const percent = Number(ev.target.value);
      $("squelch-text").textContent = squelchLabel(percent);
      squelchTouched = performance.now();
      window.clearTimeout(squelchTimer);
      squelchTimer = window.setTimeout(() => client.setSquelch(percent / 100).catch(fail), 150);   // une commande à la fin du geste, pas une par pixel
    });

    $("mem-add-current").addEventListener("click", () => openForm(null));
    $("mem-cancel").addEventListener("click", closeForm);
    $("mem-save").addEventListener("click", async () => {
      const name = $("mem-name").value.trim(), hz = parseKilohertz($("mem-khz").value), mode = $("mem-mode").value;
      if (!name) { ui.log(I18N.t("ui.mem_name_missing"), "warn"); return; }
      if (hz === null) { ui.log(I18N.t("ui.freq_invalid_7100"), "warn"); return; }
      if (!mode) { ui.log(I18N.t("ui.mem_mode_missing"), "warn"); return; }
      try {
        const res = await client.saveMemory({ memoryId: editingId, name: name, hz: hz, mode: mode, favorite: $("mem-fav").checked });
        if (res.ok) closeForm();
      } catch (err) { fail(err); }
    });
    $("mem-delete").addEventListener("click", async () => {
      if (!editingId) return;
      if (!deleteArmed) {                                                        // confirmation en deux temps
        deleteArmed = true;
        $("mem-delete").textContent = I18N.t("rigdialogs.confirm_delete");
        deleteTimer = window.setTimeout(resetDelete, 4000);
        return;
      }
      const id = editingId;
      resetDelete();
      try { const res = await client.deleteMemory(id); if (res.ok) closeForm(); } catch (err) { fail(err); }
    });

    $("mute").addEventListener("change", (ev) => { audio.muted = ev.target.checked || outputIsRig; sdrMirrorOutput(); });
    $("out-select").addEventListener("change", () => { store.set("trx.out", $("out-select").value); applyOutput(); });
    $("mic-select").addEventListener("change", () => { store.set("trx.mic", $("mic-select").value); ui.log(I18N.t("ui.mic_next_connection"), ""); });
    $("volume").addEventListener("input", () => trxVolume());                        // balance TRX / SDR comprise
    $("text-size").addEventListener("change", (ev) => { store.set("trx.text", ev.target.value); applyDisplay(); });
    $("layout-select").addEventListener("change", (ev) => { store.set("trx.layout", ev.target.value); applyDisplay(); });
    const themes = root.TrxTheme || null;                                        // theme.js, chargé dans <head>
    const themeSelect = $("theme-select");
    const knownTheme = (id) => themeSelect.options && Array.from(themeSelect.options).some((o) => o.value === id);
    themeSelect.value = themes && knownTheme(themes.stored()) ? themes.stored() : "defaut";
    if (themes && !knownTheme(themes.stored())) themes.apply("defaut");          // thème mémorisé disparu : celui par défaut
    themeSelect.addEventListener("change", (ev) => {
      if (themes) themes.choose(ev.target.value);
      loadThemeColors();                                                           // canvas : nouvelles couleurs
      if (wfVisible) { drawGrid(); resetFall(); }
      if (hfVisible && hfLast) { const again = hfLast; hfLast = null; hfDraw(again); }
    });
    $("device-select").value = store.get("trx.device", "auto");
    $("device-select").addEventListener("change", (ev) => { store.set("trx.device", ev.target.value); renderLayout(true); });
    $("layout-factory").addEventListener("click", async () => {
      try {
        const res = await client.resetLayout();
        if (res && res.ok) { profile = res.profile || null; profileSource = "factory"; profileVersion += 1; renderLayout(true); ui.log(I18N.t("ui.layout_factory_restored"), "ok"); }
      } catch (err) { fail(err); }
    });
    window.addEventListener("resize", applyDisplay);
    window.addEventListener("orientationchange", applyDisplay);
    document.addEventListener("visibilitychange", () => client.onVisibility(document.hidden));
    window.addEventListener("pagehide", () => { if (client._mineActive()) client.stop().catch(() => {}); });

    wfTexts();
    renderLosses(client.losses);
    applyDisplay();
    refreshDevices();
    renderInstruments([]);
    ui.memories([]);
    ui.connected(false);
  }

  // Textes de la langue choisie chargés avant d'afficher quoi que ce soit (i18n.js ; immédiat dans les tests)
  const I18N = root.TrxI18n || (typeof require === "function" ? require("./i18n.js") : null);
  document.addEventListener("DOMContentLoaded", () => {
    if (!I18N || I18N.loaded) initUi(); else I18N.ready.then(initUi, initUi);
  });
})(typeof window !== "undefined" ? window : globalThis);
