// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Affichage : relie TrxClient (client.js, logique testée sous Node) à la page. Aucune logique de protocole ici. */
(function (root) {
  "use strict";
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
  const DOUBLE_CLICK_MS = 260;                        // un appui sur NR/NB/NOTCH attend ce délai : un second appui = double clic
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
      agent: "page " + (/Android/i.test(navigator.userAgent) ? "Android" : /iPhone|iPad/i.test(navigator.userAgent) ? "iOS"
        : /Windows/i.test(navigator.userAgent) ? "Windows" : /Mac/i.test(navigator.userAgent) ? "Mac"
        : /Linux/i.test(navigator.userAgent) ? "Linux" : "navigateur"),
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
        if (rtt !== null) net.push("RTT réseau " + Math.round(rtt * 1000) + " ms");
        if (jitter !== null) net.push("gigue " + Math.round(jitter * 1000) + " ms");
        if (lost !== null && received !== null) net.push("pertes " + lost + "/" + (received + lost));
        const pct = (v) => Math.round(v * 100) + " %";
        const diag = [];
        if (received !== null) diag.push("son reçu : " + received + " paquets" + (rxLevel !== null ? ", niveau " + pct(rxLevel) : ""));
        if (sent !== null) diag.push("micro : " + sent + " paquets envoyés" + (micLevel !== null ? ", niveau capté " + pct(micLevel) : ""));
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
    function audioContext48(Ctx) { try { return new Ctx({ sampleRate: 48000 }); } catch (e) { return new Ctx(); } }
    let freqEls = [], drag = null, kpText = "";
    const bandButtons = new Map();
    const modeButtons = new Map();                                                    // mode Hamlib -> bouton (onglet Accord)
    const bandDots = new Map();                                                       // bande -> pastille des spots actifs
    let releaseArmed = false, releaseTimer = null;                                    // « Reprendre la main » : second appui pour confirmer
    function resetRelease() {
      releaseArmed = false;
      if (releaseTimer !== null) { window.clearTimeout(releaseTimer); releaseTimer = null; }
      $("local-release").textContent = "Reprendre la main";
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
      const landscape = window.matchMedia ? window.matchMedia("(orientation: landscape)").matches : window.innerWidth > window.innerHeight;
      $("app").className = chooseLayout(store.get("trx.layout", "auto"), landscape, window.innerWidth);
      renderLayout(false);
      syncDock();                                                                    // paysage étroit ou portrait : le spectre intégré se retire
    }

    // ---- mise en page personnalisée : profil du compte, servi par la station (layout_get)
    function currentDevice() {
      const coarse = window.matchMedia ? window.matchMedia("(pointer: coarse)").matches : false;
      return lay.detectDevice(window.innerWidth, window.innerHeight, coarse);
    }
    function currentOrientation() {
      const chosen = store.get("trx.layout", "auto");
      if (chosen === "portrait" || chosen === "landscape") return chosen;
      const landscape = window.matchMedia ? window.matchMedia("(orientation: landscape)").matches : window.innerWidth > window.innerHeight;
      return landscape ? "landscape" : "portrait";
    }
    function layoutInfo(plan) {
      const labels = { phone: "smartphone", tablet: "tablette", desktop: "ordinateur" };
      let text = "Interface d'usine.";
      if (profile && profileSource === "user") {
        text = "Profil « " + profile.name + " »";
        if (plan && plan.safe) text += " — variante " + labels[plan.choice.device] + " " + (plan.choice.orientation === "portrait" ? "portrait" : "paysage") +
          (plan.choice.display === "centered" ? " (affichée centrée)" : "") + ".";
        else if (plan) text += " — écran de sécurité : " + lay.safeText(plan);
      }
      $("layout-info").textContent = text;
      $("layout-factory").disabled = !(connectedFlag && profile && profileSource === "user");
    }
    function renderLayout(force) {
      if (!layout) return;
      if (!profile || profileSource !== "user") {                                     // profil d'usine : la page telle qu'elle est écrite
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
      if (plan.unsupported.length) ui.log("Mise en page : widget(s) pas encore pris en charge par cette page, ignoré(s) : " + plan.unsupported.join(", "), "warn");
    }
    async function loadLayout() {
      try {
        const res = await client.getLayout();
        if (!res || !res.ok || !res.profile) return;
        profile = res.profile; profileSource = res.source === "user" ? "user" : "factory"; profileVersion += 1;
        if (Array.isArray(res.warnings) && res.warnings.length) ui.log("Mise en page : " + res.warnings.length + " widget(s) masqué(s), fonction absente du poste.", "");
        renderLayout(true);
      } catch (err) { ui.log("Mise en page non chargée (interface d'usine) : " + (err && err.message ? err.message : err), "warn"); }
    }

    // ---- périphériques audio du navigateur
    const deviceLabel = (kind, id) => {
      const select = $(kind === "audioinput" ? "mic-select" : "out-select");
      const option = Array.from(select.options).find((o) => o.value === id);
      return option ? option.textContent : "";
    };
    const fillDevices = (select, devices, saved) => {
      select.textContent = "";
      select.appendChild(Object.assign(el("option", "", "Périphérique par défaut du système"), { value: "" }));
      for (const d of devices) {
        select.appendChild(Object.assign(el("option", "", d.label || "(nom masqué jusqu'à l'autorisation du micro)"), { value: d.deviceId }));
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
      if (audio.setSinkId) { try { await audio.setSinkId(id); } catch (err) { ui.log("Sortie audio non applicable : " + err.message, "warn"); } }
      if (audioCtx && audioCtx.setSinkId) { try { await audioCtx.setSinkId(id); } catch (err) { /* les alertes restent sur la sortie par défaut */ } }
      const label = id ? deviceLabel("audiooutput", id)
        : (Array.from($("out-select").options).slice(1).map((o) => o.textContent).find((t) => /^(par défaut|default)/i.test(t)) || "");
      outputIsRig = !$("ignore-rig-warning").checked && matchesRigDevice(label, rigAudio);
      if (outputIsRig) {
        audio.muted = true;
        ui.log("Sortie audio COUPÉE : « " + label + " » est une entrée audio du poste (le son reçu serait injecté dans l'émetteur). " +
               "Choisis une autre sortie, ou coche « Ce n'est pas le poste ».", "bad");
      } else { audio.muted = $("mute").checked; }
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
    $("alert-select").value = ["off", "low", "normal", "high"].includes(alertLevel) ? alertLevel : "normal";
    $("alert-select").addEventListener("change", (ev) => { alertLevel = ev.target.value; store.set("trx.alerts", alertLevel); });
    $("alert-test").addEventListener("click", () => {                                 // les trois sons à la suite, pour les reconnaître
      let delay = 0;
      for (const [kind, text] of [["lost", "liaison perdue"], ["restored", "liaison rétablie"], ["failed", "reconnexion impossible"]]) {
        window.setTimeout(() => { ui.log("Son « " + text + " ».", ""); playLinkAlert(kind); }, delay);
        delay += alertDurationMs(kind) + 900;
      }
    });
    // ---- bips de fin d'émission (réglage de la STATION ; l'écoute ici n'émet rien)
    const TONE_LABELS = { duo: "deux tons montants" };
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
        $("beeps-note").textContent = connectedFlag ? "Cette station ne propose pas les bips de fin." : "";
        return;
      }
      const tone = $("roger-tone"), pattern = $("roger-pattern");
      if (tone.options.length !== (settings.tones || []).length) {
        tone.textContent = "";
        for (const t of settings.tones || []) tone.appendChild(Object.assign(el("option", "", TONE_LABELS[t] || t + " Hz"), { value: t }));
      }
      if (pattern.options.length !== (settings.patterns || []).length) {
        pattern.textContent = "";
        for (const n of settings.patterns || []) pattern.appendChild(Object.assign(el("option", "", n + (n > 1 ? " bips" : " bip")), { value: String(n) }));
      }
      $("roger-on").checked = !!settings.roger_enabled; $("lost-on").checked = !!settings.link_lost_enabled;
      tone.value = settings.roger_tone; pattern.value = String(settings.roger_pattern);
      $("beeps-note").textContent = settings.link_lost_enabled
        ? "Bip de liaison perdue ACTIF : si la liaison tombe pendant votre émission, la station émet trois tons descendants avant de couper (émission automatique, sous votre responsabilité)."
        : "";
    }
    function setBeeps(changes) { client.setBeeps(changes).catch(fail).finally(() => renderBeeps(client.beeps || beepSettings)); }
    $("roger-on").addEventListener("change", (ev) => setBeeps({ roger_enabled: !!ev.target.checked }));
    $("roger-tone").addEventListener("change", (ev) => setBeeps({ roger_tone: ev.target.value }));
    $("roger-pattern").addEventListener("change", (ev) => setBeeps({ roger_pattern: Number(ev.target.value) }));
    $("lost-on").addEventListener("change", (ev) => {
      const on = !!ev.target.checked;
      const ask = typeof window.confirm === "function" ? window.confirm : () => true;
      if (on && !ask("Ce bip est ÉMIS par la station quand la liaison avec ce téléphone tombe pendant votre émission : "
                     + "une émission automatique de 0,4 s, sous votre responsabilité. L'activer ?")) { ev.target.checked = false; return; }
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
      $("mem-delete").textContent = "Supprimer";
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
        star.title = m.favorite ? "Retirer des favoris" : "Mettre en favori";
        const recall = el("button", "recall");
        recall.title = "Rappeler cette fréquence et ce mode";
        recall.appendChild(el("span", "mname", m.name));
        recall.appendChild(el("span", "mfreq", formatIcomFrequency(m.hz)));
        recall.appendChild(el("span", "mmode", shortMode(m.mode)));
        const edit = el("button", "edit", "✎");
        edit.title = "Modifier";
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
      digit.className = "dig active";
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
        : kpText ? "Valeur incorrecte" : "kHz si 1000 ou plus, sinon MHz (ex. 7074 ou 14.205)";
      $("kp-ok").disabled = hz === null;
    }
    let keypadOpenedAt = -1e9;
    const keypadReady = () => performance.now() - keypadOpenedAt > 450;            // au toucher, Android envoie un « clic fantôme » à l'endroit du doigt : il tomberait sur le pavé qui vient de s'ouvrir
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
      else if (ev.key === "Backspace") keypadPress("⌫");
      else if (ev.key === "Enter") $("kp-ok").click();
      else if (ev.key === "Escape") closeKeypad();
    });

    // ---- bandes (dernière fréquence et dernier mode par bande) et pas
    for (const band of BANDS) {
      const button = el("button", "chip", band.label);
      button.title = "Bande des " + band.key + " m : dernière fréquence et dernier mode utilisés";
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
        if (level) item.dot.className = ["", "banddot lvl1", "banddot lvl2", "banddot lvl3"][level.level];
        bandButtons.get(key).title = item.title + (level ? " — " + level.count + " spot" + (level.count > 1 ? "s actifs" : " actif") + " (Cluster DX)" : "");
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
      $("loss-detail").textContent = entry ? describeLoss(entry) : "Aucune perte de connexion enregistrée.";
    }
    function renderLosses(list) {
      const select = $("loss-select");
      select.textContent = "";
      $("loss-copy").disabled = $("loss-clear").disabled = list.length === 0;
      if (!list.length) {
        select.appendChild(Object.assign(el("option", "", "Aucune perte enregistrée"), { value: "" }));
        $("loss-last").hidden = true; $("loss-open").hidden = true;
        showLoss(-1);
        return;
      }
      list.forEach((entry, i) => select.appendChild(Object.assign(el("option", "", lossSummary(entry)), { value: String(i) })));
      select.value = "0";
      showLoss(0);
      const last = list[0];
      $("loss-last").textContent = (last.kind === "failed" ? "Dernier échec de connexion : " : "Dernière perte de connexion : ") + last.title + " — " + last.explain;
      $("loss-last").hidden = false; $("loss-open").hidden = false;
    }
    $("loss-select").addEventListener("change", (ev) => showLoss(Number(ev.target.value)));
    $("loss-open").addEventListener("click", () => {
      $("sec-diag").open = true; $("loss-select").value = "0"; showLoss(0);
      if ($("sec-diag").scrollIntoView) $("sec-diag").scrollIntoView();
    });
    $("loss-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText($("loss-detail").textContent); ui.log("Rapport copié dans le presse-papiers.", ""); }
      catch (err) { ui.log("Copie impossible : sélectionne le texte du rapport à la main.", "warn"); }
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
      $("wf-peakinfo").textContent = top ? "pic " + (top.hz / 1000).toFixed(2) : "";
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
      if (lastFrame === 0) { lastFrame = now; lastLine = now - interval; }   // 1re image : l'horloge part de l'horodatage de l'animation (pas de performance.now()), une ligne tout de suite
      const dt = (now - lastFrame) / 1000;
      lastFrame = now;
      drawSpectrum(wfValues, tracker.update(wfValues, dt, wfSettings.peak));
      for (let n = 0; n < 3 && now - lastLine >= interval; n++) { pushLine(wfValues); lastLine += interval; }
      if (now - lastLine > 1000) lastLine = now;                                         // retard important (onglet gelé) : on repart sans rafale
      wfRaf = window.requestAnimationFrame(frame);
    }
    function startWf() {
      if (wfRaf !== null || !analyser) { if (!analyser) $("wf-peakinfo").textContent = "pas d'audio reçu"; return; }
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
         Sinon la vue intégrée se referme (et l'interrupteur disparaît s'il ne peut pas servir). */
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
      $("hf-info").textContent = "largeur " + hfx.spanLabel(frame.lowHz, frame.highHz) + (frame.outOfRange ? " — HORS PLAGE" : "");
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
      $("hf-tx").textContent = v.mine ? "ÉMISSION EN COURS" : "ÉMISSION (" + (v.owner || "?") + ")";
      $("hf-stop").disabled = !v.connected;
      if (transmitting || !v.connected) setVfo(false);                            // jamais d'accord pendant l'émission
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
        const line = el("div", "spot-line k-" + s.kind);
        line.style.left = (((s.hz - hfLast.lowHz) / span) * 100).toFixed(2) + "%";
        line.style.opacity = String(sp.opacity(sp.ageSeconds(s, now)) * 0.7);
        layer.appendChild(line);
      }
      const rowPx = 18;
      for (const tag of sp.layoutLabels(visible, hfLast.lowHz, hfLast.highHz, width, { rows: 3, charPx: 7, padPx: 12 })) {
        const first = spotBook.get(tag.ids[0]);
        const age = first ? sp.ageSeconds(first, now) : 0;
        const button = el("button", "spot-tag k-" + (first ? first.kind : "cluster") + (tag.group ? " group" : "")
                                    + (!tag.group && age <= sp.FRESH_S ? " fresh" : ""), tag.text);
        button.style.left = tag.x.toFixed(1) + "px";
        button.style.top = (2 + tag.row * rowPx) + "px";
        if (!tag.group) button.style.opacity = String(sp.opacity(age));
        button.title = tag.group ? tag.ids.length + " spots proches : liste" : (first ? first.dx + " " + first.khz.toFixed(1) + " kHz" : "");
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
      if (!s) { $("spot-qsy").disabled = true; $("spot-note").textContent = "Spot expiré ou hors de la bande."; return; }
      $("spot-dx").textContent = s.dx;
      $("spot-kind").textContent = sp.kindLabel(s.kind) + (s.count > 1 ? " · " + s.count + " spotteurs" : "");
      $("spot-freq").textContent = s.khz.toFixed(1) + " kHz · " + sp.modeLabel(s);
      $("spot-info").textContent = [s.country ? s.country + (s.continent ? " (" + s.continent + ")" : "") : "",
                                    "de " + (s.de || "?"), (s.time ? s.time.slice(0, 2) + ":" + s.time.slice(2) + " UTC" : ""),
                                    sp.ageLabel(sp.ageSeconds(s, Date.now()))].filter(Boolean).join(" · ");
      $("spot-comment").textContent = s.comment;
      $("spot-qsy").disabled = locked;
      $("spot-qsy").title = locked ? "QSY impossible : émission en cours ou station déconnectée" : "Mettre le poste sur ce spot";
    }
    function spotQsy() {
      const s = spotCardId === null ? null : spotBook.get(spotCardId);
      if (!s || frequencyLocked()) return;
      const target = sp.qsyTarget(s, (mode) => client.adaptSpotMode(mode));
      $("spot-qsy").disabled = true; $("spot-note").textContent = "QSY en cours…";
      client.qsy(target.hz, target.mode).then((res) => {
        if (res && res.ok) { ui.log("QSY sur " + s.dx + " (" + s.khz.toFixed(1) + " kHz).", ""); closeSpotCard(); }
        else { $("spot-note").textContent = "QSY refusé" + (res && res.reason ? " : " + web.reasonText(res.reason, res.detail) : "."); refreshSpotCard(); }
      }).catch((err) => { $("spot-note").textContent = "QSY impossible : " + err.message; refreshSpotCard(); });
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
      $("spot-sort").textContent = "Tri : " + (spotSort === "age" ? "âge" : "fréquence");
      $("spot-list-title").textContent = (spotListIds ? "Spots proches" : "Spots de la bande") + " (" + all.length + ")";
      const box = $("spot-items");
      box.textContent = "";
      if (!all.length) { box.appendChild(el("div", "hf-info", "Aucun spot pour l'instant.")); return; }
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
      dot.title = sp ? sp.healthLabel(state) : "Cluster DX";
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
      } catch (err) { ui.log("Analyse audio indisponible : " + err.message, "warn"); }
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
        if (!(res && res.ok)) ui.log("QSY refusé" + (res && res.reason ? " : " + web.reasonText(res.reason, res.detail) : "."), "warn");
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
        if (name === "width") { drawGrid(); resetFall(); }                              // l'échelle change : l'ancien historique n'a plus de sens
        if (name === "peak") tracker.reset();
      });
    }

    const squelchLabel = (percent) => (percent === 0 ? "ouvert" : percent + " %");

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
        const button = el("button", "chip", "Déconnecter");
        button.addEventListener("click", () => {
          if (!window.confirm("Déconnecter « " + visitor.text + " » ? (il peut se reconnecter ; pour l'en empêcher, désactive son compte sur la station)")) return;
          client.kickListener(visitor.account).catch(fail);
        });
        li.appendChild(el("span", "grow", visitor.text)); li.appendChild(el("span", "dim", visitor.detail)); li.appendChild(button);
        list.appendChild(li);
      }
      $("presence-note").textContent = pv.suspended || pv.grace || (pv.people.length ? "" : "Personne d'autre n'est connecté.");
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
          && !window.confirm("Fermer l'écoute des visiteurs ? Les " + lastPresence.count + " visiteur(s) connecté(s) seront déconnectés.")) {
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
      $("mini-span-info").textContent = miniLast ? "Largeur affichée : " + hfx.spanLabel(miniLast.lowHz, miniLast.highHz) : "";
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
      $("swr-band").textContent = b ? "(" + b.name + " : " + sw.freqLabel(b.low_hz) + " à " + sw.freqLabel(b.high_hz) + " MHz)" : "(hors table : centre et largeur)";
      $("swr-center-row").hidden = $("swr-use-band").checked;
      if (!$("swr-center").value && Number.isFinite(rig.frequency_hz)) $("swr-center").value = String(Math.round(rig.frequency_hz / 1000));
      $("swr-power-text").textContent = " " + $("swr-power").value + " %";
      const range = swrRange(), points = parseInt($("swr-points").value, 10);
      if (!range) { $("swr-plan").textContent = "Choisis une plage."; $("swr-start").disabled = true; return null; }
      const p = sw.plan(range.lowHz, range.highHz, points, Number($("swr-points").max) || sw.MAX_POINTS);
      if (p.error) { $("swr-plan").textContent = web.reasonText(p.error); $("swr-start").disabled = true; return null; }
      const center = $("swr-use-center").checked
        ? $("swr-center").value + " kHz ± " + (Number(String($("swr-width").value).replace(",", ".")) / 2) + " kHz = " : "";
      $("swr-plan").textContent = center + sw.freqLabel(p.lowHz) + " à " + sw.freqLabel(p.highHz) + " MHz, pas de " + (p.stepHz / 1000) +
        " kHz, " + p.freqs.length + " points" + (p.amateurOnly ? "" : " — HORS des bandes radioamateur");
      $("swr-start").disabled = swrRunning || !(lastView && lastView.armed && lastView.connected);
      if (swrPlanTimer !== null) window.clearTimeout(swrPlanTimer);
      swrPlanTimer = window.setTimeout(() => {                                       // plan de la station (rien n'est émis)
        client.swrPlan(range.lowHz, range.highHz, points, Number($("swr-power").value)).then((res) => {
          if (!res || !res.ok || !res.plan) return;
          const pl = res.plan, skipped = pl.points.filter((x) => x.status === "out_of_band").length;
          $("swr-plan").textContent += (pl.power_w ? " ; " + pl.power_w + " W" : "") + " en " + web.modeLabel(pl.fm_mode || "FM") +
            (skipped ? " ; " + skipped + " point(s) hors des bandes de la station, sautés" : "") +
            " ; environ " + Math.round(pl.estimated_s) + " s" + (pl.calibration_needed ? " (étalonnage du poste compris)" : "");
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
      ctx.font = Math.round(10 * ratio) + "px sans-serif";
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
      const why = result && result.reason !== "done" ? " Mesure interrompue (" + web.cutText(result.detail) + ")." : "";
      return (best ? "Meilleur TOS : " + sw.swrText(best.swr) + " à " + sw.freqLabel(best.hz) + " MHz." : "Aucun point mesuré.") + why +
        (result && result.warning === "swr_unstable" ? " Lecture du TOS instable sur ce poste." : "");
    }
    function onSwr(msg) {
      swrRunning = !["done", "cut", "failed", "cancelled"].includes(msg.state);
      $("swr-cancel").hidden = !swrRunning;
      const names = { preparing: "Préparation du poste…", calibrating: "Étalonnage du temps de lecture du poste…", restoring: "Remise en état du poste…" };
      $("swr-progress").textContent = names[msg.state] ||
        (msg.state === "measuring" ? "Point " + ((msg.points || []).filter((p) => p.swr !== null && p.swr !== undefined).length) + " sur " + msg.total : "");
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
      if (!swrName) swrName = (window.prompt("Nom de la mesure (légende de l'image) :", "") || "").trim();
      const W = 1200, H = 760, cv = document.createElement("canvas");
      cv.width = W; cv.height = H;
      const ctx = cv.getContext("2d");
      ctx.fillStyle = sw.COLORS.background; ctx.fillRect(0, 0, W, H);
      const legend = sw.legendLines(swrResult, swrName, web.modeLabel, new Date(swrResult.at ? swrResult.at * 1000 : Date.now()).toLocaleString());
      ctx.fillStyle = sw.COLORS.title; ctx.font = "bold 34px sans-serif"; ctx.fillText(legend[0], 40, 56);
      drawSwrChart(ctx, 30, 80, W - 60, 520, swrResult.points || [], 2);
      ctx.fillStyle = sw.COLORS.text; ctx.font = "22px sans-serif";
      if (legend[1]) ctx.fillText(legend[1], 40, 650);
      const logo = await new Promise((resolve) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = () => resolve(null); img.src = "logo-96.png"; });
      if (logo) ctx.drawImage(logo, 40, 676, 64, 64);
      ctx.fillStyle = sw.COLORS.accent; ctx.font = "bold 24px sans-serif"; ctx.fillText("www.rf-diy.com", 118, 718);
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
      if (!p.plan.amateurOnly && !window.confirm("Cette plage sort des bandes radioamateur : tu vas émettre hors de ces bandes, sous ta seule responsabilité. Continuer ?")) return;
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
          const handle = await window.showSaveFilePicker({ suggestedName: swrFileName(), types: [{ description: "Image PNG", accept: { "image/png": [".png"] } }] });
          const out = await handle.createWritable(); await out.write(blob); await out.close();
        } else {
          const link = el("a", ""); link.href = URL.createObjectURL(blob); link.download = swrFileName(); link.click();
          window.setTimeout(() => URL.revokeObjectURL(link.href), 5000);
        }
        ui.log("Image de la mesure enregistrée.", "");
      } catch (e) { if (!(e && e.name === "AbortError")) fail(e); }
    });
    $("swr-share").addEventListener("click", async () => {
      try {
        const blob = await swrImage();
        if (blob) await navigator.share({ files: [new File([blob], swrFileName(), { type: "image/png" })], title: swrName || "Mesure de TOS" });
      } catch (e) { if (!(e && e.name === "AbortError")) fail(e); }
    });
    $("swr-copy").addEventListener("click", async () => {
      try {
        const blob = await swrImage();
        if (blob) { await navigator.clipboard.write([new window.ClipboardItem({ "image/png": blob })]); ui.log("Image copiée.", ""); }
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
      $("replay-banner").textContent = replayPlaying ? "DIFFUSION DE L'ENREGISTREMENT — STOP pour arrêter" : "Diffusion de l'enregistrement : émission demandée…";
      if (!max) return;
      const tx = !!(lastView && lastView.pttState && lastView.pttState !== "RX");
      const armed = !!(lastView && lastView.armed && lastView.connected);
      $("replay-max").textContent = String(max);
      $("replay-record").textContent = replayRec ? "Arrêter" : "Enregistrer";
      $("replay-record").disabled = tx || replayPlaying || !!replayPending || !rxMedia || typeof MediaRecorder === "undefined";
      $("replay-send").disabled = !replayBuf || !!replayRec || tx || replayPlaying || !!replayPending || !armed || !voiceChain;
      $("replay-hint").hidden = armed;
      $("replay-status").textContent = replayRec ? "Enregistrement en cours (" + max + " s au plus)…"
        : replayPlaying ? "Diffusion en cours…" : replayPending ? "Émission demandée…"
        : replayBuf ? "Enregistré : " + replayBuf.duration.toFixed(1).replace(".", ",") + " s" : "Rien d'enregistré.";
    }
    function replayOnTx(on) {
      /* Émission confirmée de CETTE page (client.js -> chaîne de voix) : la diffusion demandée commence ; fin = arrêt net. */
      if (on) {
        if (replayRec) replayRec.stop();
        if (replayPending && Date.now() - replayPending <= 5000 && replayBuf && voiceChain) {
          replayPending = 0;
          replayPlaying = voiceChain.replayBuffer(replayBuf, () => {        // fin de l'enregistrement : fin d'émission (STOP)
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
            .catch((e) => ui.log("Enregistrement illisible : " + e.message, "warn"));
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
      $("host-bar").className = "hostbar listener-hide" + (h.level !== "ok" ? " " + h.level : "");
      $("host-fill").style.height = Math.round(h.fraction * 100) + "%";
      $("host-bar").title = h.title;
    }
    function showHostInfo() {
      const box = $("host-sections");
      box.textContent = "Lecture…";
      $("host-dialog").hidden = false;
      client.hostInfo().then((sections) => {
        box.textContent = "";
        if (!sections) { box.textContent = "Synthèse indisponible (station plus ancienne ou déconnectée)."; return; }
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
      }).catch((err) => { box.textContent = "Synthèse impossible : " + err.message; });
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
      netRows($("net-rows"), n.probes.length ? n.rows.concat([["Sondes de la station", ""]], n.probes) : n.rows, n.outage);
      const box = $("net-vpn");
      box.textContent = "";
      for (const w of n.vpn) {
        const div = el("div", "alert warn", w.text + " ");
        const skip = el("button", "chip", "Ignorer pour cette adresse");
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
      if (!m.days.length) days.appendChild(el("p", "note", "Aucune mesure sur la période."));
      for (const d of m.days) netBarRow(days, d.date, d.fraction, d.short, d.date + " : " + d.outages + " coupure(s), " + d.detail);
      const heat = $("net-heat");
      heat.textContent = "";
      heat.appendChild(el("b", "", ""));
      for (let h = 0; h < 24; h++) heat.appendChild(el("b", "", h % 6 === 0 ? String(h) : ""));
      for (const d of m.days) {
        heat.appendChild(el("b", "", d.date.slice(5)));
        d.hours.forEach((cell, h) => {
          const c = el("span", cell.n ? "" : "zero");
          if (cell.n) c.style.opacity = String(0.25 + 0.75 * cell.fraction);
          c.title = d.date + " " + h + " h : " + cell.n + " coupure(s)";
          heat.appendChild(c);
        });
      }
      const diag = $("net-diag");
      diag.textContent = "";
      if (!m.diagnoses.length) diag.appendChild(el("p", "note", "Aucune coupure."));
      for (const d of m.diagnoses) netBarRow(diag, d.label, d.fraction, d.count + " (" + Math.round(d.fraction * 100) + " %)", d.label);
      netRows($("net-types"), m.types.length ? m.types : [["—", "aucune mesure"]]);
      const list = $("net-outages");
      list.textContent = "";
      for (const o of m.outages) {
        list.appendChild(el("li", "", new Date(o.when).toLocaleString() + " — " + o.duration + " — " + o.diagnosis +
          (o.agent ? " — " + o.agent : "") + (o.net ? " (" + o.net + ")" : "") + " — " + o.kind + (o.basis ? " ; d'après : " + o.basis : "")));
      }
      if (!m.outages.length) list.appendChild(el("li", "", "Aucune coupure sur la période."));
      const select = $("net-device"), keep = select.value;
      select.textContent = "";
      select.appendChild(el("option", "", "tous"));
      select.firstChild.value = "";
      for (const d of m.devices) {
        const o = el("option", "", (d.agent || "appareil") + " (" + String(d.device).slice(0, 4) + ")");
        o.value = d.device;
        select.appendChild(o);
      }
      select.value = keep;
      renderNetThresholds(m);
    }
    function renderNetThresholds(m) {
      const box = $("net-thr");
      box.textContent = "";
      if (!m.thresholds.length) { box.appendChild(el("p", "note", "Pas encore de mesures par type de réseau.")); return; }
      for (const t of m.thresholds) {
        const card = el("div", "net-thr-type");
        card.appendChild(el("strong", "", t.label + (t.chosen ? " — seuils choisis" : " — seuils de station.toml")));
        const p = t.proposed || {};
        const proposal = p.rtt || p.loss
          ? "Proposé d'après vos mesures : " + (p.rtt ? "aller-retour " + p.rtt.warn + " / " + p.rtt.alert + " ms" : "") +
            (p.rtt && p.loss ? ", " : "") + (p.loss ? "perte " + p.loss.warn + " / " + p.loss.alert + " %" : "")
          : "Pas encore de proposition (7 jours et 2 000 mesures de 10 s de ce réseau ; " + t.days + " jour(s) aujourd'hui).";
        card.appendChild(el("p", "note", proposal));
        const values = { rtt_warn: t.inForce.rtt_warn, rtt_alert: t.inForce.rtt_alert, loss_warn: t.inForce.loss_warn, loss_alert: t.inForce.loss_alert };
        const result = el("p", "note", "");
        const simulate = () => {
          if (!np) return;
          const r = np.simulate(t.rttHist, m.edges.rtt_ms, values.rtt_warn, values.rtt_alert);
          const l = np.simulate(t.lossHist, m.edges.loss_pct, values.loss_warn, values.loss_alert);
          const pct = (x) => (x === null ? "—" : String(x).replace(".", ",") + " %");
          result.textContent = "Sur l'historique — aller-retour : orange " + pct(r.orange_pct) + " du temps, rouge " + pct(r.red_pct) +
            " ; son dégradé dans " + pct(r.degraded_red_pct) + " des moments rouges et " + pct(r.degraded_green_pct) + " des moments verts. " +
            "Perte : orange " + pct(l.orange_pct) + ", rouge " + pct(l.red_pct) + ".";
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
        slider("rtt_warn", "Aller-retour orange", 50, 1500, 50, "ms");
        slider("rtt_alert", "Aller-retour rouge", 100, 3000, 50, "ms");
        slider("loss_warn", "Perte orange", 0.5, 20, 0.5, "%");
        slider("loss_alert", "Perte rouge", 1, 50, 1, "%");
        card.appendChild(result);
        simulate();
        const row = el("div", "row");
        if (p.rtt || p.loss) {
          const take = el("button", "chip", "Prendre la proposition");
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
        const apply = el("button", "chip", "Appliquer");
        apply.addEventListener("click", () => {
          if (values.rtt_warn >= values.rtt_alert || values.loss_warn >= values.loss_alert) {
            ui.log("Seuils refusés : l'orange doit être plus petit que le rouge.", "warn");
            return;
          }
          client.netThresholds(Object.assign({ net_type: t.netType }, values)).then((res) => {
            ui.log(res && res.ok ? "Seuils enregistrés sur la station pour « " + t.label + " »." : "Seuils refusés : " + web.reasonText(res && res.reason, res && res.detail), res && res.ok ? "" : "warn");
            loadNetStats();
          }).catch(fail);
        });
        row.appendChild(apply);
        if (t.chosen) {
          const reset = el("button", "chip", "Revenir aux valeurs de station.toml");
          reset.addEventListener("click", () => client.netThresholds({ net_type: t.netType, reset: true }).then(loadNetStats).catch(fail));
          row.appendChild(reset);
        }
        card.appendChild(row);
        box.appendChild(card);
      }
    }
    function loadNetStats() {
      $("net-status").textContent = "Lecture…";
      client.netStats(Number($("net-days").value), $("net-device").value).then((res) => {
        if (!res || !res.ok) {
          $("net-status").textContent = "Statistiques indisponibles : " + web.reasonText(res && res.reason, res && res.detail);
          return;
        }
        netModel = web.netStatsModel(res.stats);
        $("net-status").textContent = netModel ? "Mesures de " + ($("net-device").value ? "cet appareil" : "tous les appareils") + " ; heures locales de la station." : "Réponse illisible.";
        renderNetStats(netModel);
      }).catch((err) => { $("net-status").textContent = "Lecture impossible : " + err.message; });
    }
    $("net-days").value = "30";                                            // 30 jours par défaut
    $("net-refresh").addEventListener("click", loadNetStats);
    $("net-days").addEventListener("change", loadNetStats);
    $("net-device").addEventListener("change", loadNetStats);
    $("sec-net").addEventListener("toggle", () => { if ($("sec-net").open) loadNetStats(); });
    $("net-clear").addEventListener("click", () => { $("net-clear-confirm").hidden = !$("net-clear-confirm").hidden; });
    $("net-clear-confirm").addEventListener("click", () => {
      $("net-clear-confirm").hidden = true;
      client.netClear().then((res) => {
        ui.log(res && res.ok ? "Historique réseau effacé (les seuils choisis sont gardés)." : "Effacement refusé : " + web.reasonText(res && res.reason, res && res.detail), res && res.ok ? "" : "warn");
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
      swr(msg) {
        onSwr(msg);
      },
      netEvent(msg) {                                          // sonde réseau : coupure diagnostiquée, profil VPN partagé
        if (msg.event === "outage" && msg.outage) {
          const o = msg.outage;
          ui.log("Coupure réseau de " + web.netDuration((o.duration_ms || 0) / 1000) + (o.agent ? " (" + o.agent + ")" : "") +
                 " — tronçon probable : " + (web.NET_DIAGNOSES[o.diagnosis] || "indéterminé") + ".", "warn");
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
        applyOutput().finally(() => audio.play().catch(() => ui.log("Lecture audio bloquée par le navigateur : touche l'écran.", "warn")));
      },
      stats(text) { statsText = text; showNet(); },
      diag(text) { $("diag").textContent = text + (audio.paused ? " · lecture en pause" : "") + (audio.muted ? " · son coupé" : ""); },
      rtt(ms) { rttText = "commande " + ms + " ms"; showNet(); },
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
          $("reconnect-text").textContent = "RECONNEXION… " + info.remainingS + " s";
          $("reconnect-sub").textContent = (info.attempt ? "essai " + info.attempt : "préparation") + (info.lastError ? " · " + info.lastError : "");
        } else if (lost) {
          $("reconnect-text").textContent = "CONNEXION PERDUE";
          $("reconnect-sub").textContent = info.outcome === "auth" ? "identifiants refusés" : "plus de liaison après " + info.seconds + " s";
        }
      },
      memories(list) { renderMemories(list); },
      losses(list) { renderLosses(list); },
      lossRecorded() { /* l'écran se met à jour via losses(list) */ },
      linkAlert(kind) { playLinkAlert(kind); },
      spots(data) { onSpots(data); },
      beeps(settings) { renderBeeps(settings); },
      selcall(status, call) { renderSelcall(status); if (call) playSequence([[880, 120], [0, 40], [1320, 160]]); },
      breizhEvent(entry, alarm) { bzhLogRender(); if (alarm) playSequence([[660, 120], [0, 60], [440, 200]]); },   // repli pendant MON émission
      recentSpots(data) { recentData = data; recentAt = Date.now(); renderRecent(); },
      clusterHealth(state) { onClusterHealth(state); },
      clusterStatus(data) { clusterData = data; clusterAt = performance.now(); renderCluster(); },
      armed(value) { $("armed").checked = value; },
      connected(value) {
        connectedFlag = value;
        if (!value) {                                                            // déconnecté : plus de mode visiteur ni de 🎧
          renderPresence({ listener: false, presence: null });
          bzhRender(null);                                                       // plus de rubrique ni de voyant Breizh
          paintNet({ connected: false });                                        // plus d'indicateur de liaison
          presenceOpen = false; $("presence-dialog").hidden = true;
        }
        renderSelcall(value ? client.selcall : null);
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
        $("tot").textContent = v.tot === null ? (v.lastCut ? "Dernière coupure : " + v.lastCut : "")
          : "Temps restant : " + v.tot + " s" + (v.totWarning ? " — COUPURE IMMINENTE" : "");
        $("owner").textContent = v.clients.length ? "Connectés : " + v.clients.join(", ") : "";
        const faultBox = $("fault");
        faultBox.hidden = !v.fault;
        faultBox.textContent = v.fault ? "DÉFAUT STATION : " + v.fault + " (intervention requise)" : "";
        const ptt = $("ptt");
        ptt.textContent = v.mine ? "PTT — COUPER" : v.other ? "EN ÉMISSION (" + v.owner + ")" : "PTT";
        ptt.className = "ptt" + (v.mine ? " tx" : "");
        ptt.disabled = !v.connected || v.other || !!v.fault || (v.txBlocked && !v.mine);
        const hint = $("mode-hint");
        hint.hidden = !v.dataModeHint;
        hint.textContent = v.dataModeHint;
        renderPresence(v);
        paintHost(v);
        paintNet(v);
        bzhRender(v);
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
      if (ind) { $("sel-ind").textContent = ind.text; $("sel-ind").className = "chip sel-ind" + (ind.open ? " open" : ""); }
      if (!offered) return;
      $("sel-state").textContent = "État : " + (scx.STATE_LABELS[status.state] || status.state) + (status.code && status.state !== "disabled" ? " (code " + status.code + ")" : "");
      if (document.activeElement !== $("sel-code") && !$("sel-code").value) $("sel-code").value = status.code || "";
      if (document.activeElement !== $("sel-test-code") && !$("sel-test-code").value) $("sel-test-code").value = status.code || "";
      $("sel-tail").checked = !!status.send_on_tx_end;
      const calOffered = !!(client.hello && Array.isArray(client.hello.features) && client.hello.features.includes("selcall_calibrate"));
      $("sel-level-box").hidden = !calOffered;
      if (calOffered) {
        if (document.activeElement !== $("sel-level")) $("sel-level").value = status.tx_level_dbfs;
        $("sel-level-text").textContent = " " + String(status.tx_level_dbfs).replace(".", ",") + " dBFS";
        $("sel-calibration").textContent = status.calibration ? "Dernier réglage : " + status.calibration : "";
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
        chip.title = "Armer sur " + code;
        chip.addEventListener("click", () => client.selcallActivate(code).catch(fail));
        box.appendChild(chip);
      }
      const c = status.last_call;
      $("sel-last").textContent = c ? "Dernier appel : " + c.code + " à " + new Date(c.at * 1000).toLocaleTimeString("fr-FR")
        + " (décalage " + (c.delta_hz > 0 ? "+" : "") + c.delta_hz + " Hz, SNR " + c.snr_db + " dB)" : "Aucun appel reçu.";
    }
    function paintSelcallSend() {
      /* « Envoyer SELCALL » : devient « Annuler » pendant l'appel (progression 1/3...) ; une émission de ce client. */
      const st = selStatus, v = lastView;
      const sending = !!(st && st.sending) || !!(v && v.mine && v.pttState && v.pttState !== "RX" && selSendAsked);
      const button = $("sel-send");
      const offered = !!(client.hello && Array.isArray(client.hello.features) && client.hello.features.includes("selcall_send"));
      button.hidden = !offered; $("sel-tail-row").hidden = !offered;
      if (!offered) { $("sel-send-note").textContent = "Appel et trame de fin : station à mettre à jour (0.63.0 ou plus)."; return; }
      button.textContent = sending ? "Annuler" + (st && st.sending ? " (" + st.sending + ")" : "") : "Envoyer SELCALL";
      button.className = sending ? "stop" : "primary";
      button.disabled = !connectedFlag || !st || (!sending && (st.state === "disabled" || !(v && v.armed) || (v && v.pttState !== "RX")));
      $("sel-send-note").textContent = !st || st.state === "disabled" ? "Armez d'abord sur un code."
        : !(v && v.armed) && !sending ? "Cochez « Émission autorisée » (c'est une émission)." : "";
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
        if (!scx.validCode(code)) { ui.log("Code SELCALL : 3 à 8 chiffres.", "warn"); return; }
        client.selcallActivate(code).catch(fail);
      });
      $("sel-rearm").addEventListener("click", () => client.selcallRearm().catch(fail));
      $("sel-deactivate").addEventListener("click", () => client.selcallDeactivate().catch(fail));
      $("sel-filter").addEventListener("change", (ev) => client.selcallOptions({ filter_mode: ev.target.value }).catch(fail));
      $("sel-att").addEventListener("change", (ev) => client.selcallOptions({ attenuation_db: Number(ev.target.value) }).catch(fail));
      const testCode = () => {
        const code = $("sel-test-code").value.trim();
        if (!scx.validCode(code)) { ui.log("Code du fichier de test : 3 à 8 chiffres.", "warn"); return null; }
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
        if (testPlayer) { testPlayer.pause(); testPlayer = null; $("sel-test-play").textContent = "Écouter"; return; }
        testPlayer = new Audio(URL.createObjectURL(new Blob([scx.testWav(code)], { type: "audio/wav" })));   // ici seulement, jamais émis
        testPlayer.onended = () => { testPlayer = null; $("sel-test-play").textContent = "Écouter"; };
        $("sel-test-play").textContent = "Arrêter";
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
      $("voice-direct").className = "chip voice-direct" + (on ? " on" : "");
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
      $("voice-record").textContent = recorder ? "Arrêter l'enregistrement" : "Enregistrer";
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
      g.font = Math.round(11 * ratio) + "px sans-serif"; g.fillStyle = cssVar("--texte-secondaire") || vx.GRAPH.label;
      for (const [hz, label] of [[100, "100"], [300, "300"], [1000, "1 k"], [3000, "3 k Hz"]]) g.fillText(label, xOf(hz) + 3 * ratio, H - 4 * ratio);
      for (const db of [12, -12]) g.fillText((db > 0 ? "+" : "") + db + " dB", 3 * ratio, yOf(db) - 3 * ratio);
      const badges = (s.chorus.on ? ["♫ chorus"] : []).concat(s.reverb.on ? ["≋ réverb"] : []);
      g.fillStyle = vx.GRAPH.badge;
      badges.forEach((text, i) => g.fillText(text, W - 80 * ratio, (16 + 15 * i) * ratio));
      if (!s.enabled) { g.fillStyle = vx.GRAPH.off; g.fillRect(0, 0, W, H); g.fillStyle = vx.GRAPH.offText; g.fillText("ÉTEINT", W / 2 - 22 * ratio, H / 2); }
    }
    // ---- profils de l'opérateur rangés sur la station (après Neutre, DX, Ragchew)
    let voiceProfilesFor = null;
    function voicePresetOptions() {
      const select = $("voice-preset"), keep = select.value;
      select.textContent = "";
      for (const [key, preset] of Object.entries(vx.PRESETS)) select.appendChild(Object.assign(el("option", "", preset.label), { value: key }));
      const mine = client.voiceProfileList || [];
      if (mine.length) select.appendChild(Object.assign(el("option", "", "── Mes profils (station) ──"), { value: "", disabled: true }));
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
        const fz = Object.assign(el("input", ""), { type: "number", min: String(Math.round(hz / 1.5)), max: String(Math.round(hz * 1.5)), step: "10", title: "Fréquence (Hz)" });
        const q = Object.assign(el("input", ""), { type: "number", min: "0.3", max: "8", step: "0.1", title: "Largeur Q (grand = étroit)" });
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
          ui.log("Profil « " + p.name + " » appliqué.", "");
        } else if (vx.PRESETS[choice]) {
          voiceSettings = vx.PRESETS[choice].make();
        }
        voiceSave();
      });
      $("voice-preset").addEventListener("change", voiceProfileButtons);
      $("voice-profile-save").addEventListener("click", () => {
        const current = $("voice-preset").value.startsWith("user:") ? $("voice-preset").value.slice(5) : "";
        const name = (window.prompt("Nom du profil (égaliseur, chorus et réverbération actuels, rangés sur la station) :", current) || "").trim();
        if (!name) return;
        client.saveVoiceProfile(name, vx.validate(voiceSettings)).then((list) => {
          if (!list) return;
          voicePresetOptions(); $("voice-preset").value = "user:" + (list.find((p) => p.name.toLowerCase() === name.toLowerCase()) || { name }).name;
          voiceProfileButtons(); ui.log("Profil « " + name + " » enregistré sur la station.", "");
        }).catch(fail);
      });
      $("voice-profile-delete").addEventListener("click", () => {
        const name = $("voice-preset").value.slice(5);
        if (!name || !window.confirm("Supprimer le profil « " + name + " » de la station ?")) return;
        client.deleteVoiceProfile(name).then((list) => {
          if (list) { voicePresetOptions(); ui.log("Profil « " + name + " » supprimé.", ""); }
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
        file.text().then((text) => { voiceSettings = vx.importJson(text); voiceSave(); ui.log("Réglages de voix importés.", ""); })
          .catch((e) => ui.log("Import impossible : " + e.message, "warn"))
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
        try { recorder = new MediaRecorder(new MediaStream([voiceRaw])); } catch (e) { ui.log("Enregistrement impossible : " + e.message, "warn"); return; }
        recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
        recorder.onstop = () => {
          recorder = null;
          if (recordTimer !== null) { window.clearTimeout(recordTimer); recordTimer = null; }
          new Blob(chunks).arrayBuffer().then((data) => voiceCtx.decodeAudioData(data)).then((buffer) => {
            recordBuffer = buffer;
            $("voice-rec-text").textContent = "Prise de " + buffer.duration.toFixed(1).replace(".", ",") + " s.";
            voiceRender();
          }).catch((e) => { ui.log("Enregistrement illisible : " + e.message, "warn"); voiceRender(); });
        };
        recorder.start();
        $("voice-rec-text").textContent = "Enregistrement… (" + vx.RECORD_MAX_S + " s au plus)";
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
            ui.log("Le micro ne livre que du silence numérique : micro coupé (bouton muet, volume à 0 dans Windows) ou pilote bloqué " +
                   "(débranchez puis rebranchez le micro, puis reconnectez-vous).", "warn");
          } else if (watchMs >= 10000) window.clearInterval(silenceWatch);
        }, 500);
        if (voiceRaw) voiceRaw.addEventListener("ended", () => {
          if (voiceChain === chain) ui.log("Le micro s'est arrêté (débranché ou pilote bloqué) : plus de voix envoyée, reconnectez-vous.", "bad");
        });
        return {
          track: chain.track, stream: chain.stream,
          setTx(on) {
            if (on) chain.setExternal(client.breizhEffectsOff());        // voix par Breizh : égaliseur et effets coupés (limiteur gardé)
            chain.setTx(on);
            if (on && recorder) recorder.stop();                       // toute prise d'émission arrête l'enregistrement
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
    const SCR_WARNING = "SCRAMBLER : votre voix devient incompréhensible pour qui n'a pas le même réglage. Ce n'est PAS un " +
      "chiffrement : tout possesseur d'un scrambler identique vous entend.\n\nEn bandes radioamateur, le Règlement des " +
      "radiocommunications (UIT, art. 25) et la réglementation nationale interdisent les émissions destinées à masquer le sens " +
      "des messages. Vous en prenez l'ENTIÈRE responsabilité.";
    function scrMsg() { return { mode: scr.mode, offsetHz: scr.offsetHz }; }
    function scrSave() { store.set("trx.scrambler", JSON.stringify(scrMsg())); }
    function scrWorklet(ctx) {
      if (!ctx.audioWorklet || typeof AudioWorkletNode === "undefined") return Promise.reject(new Error("AudioWorklet absent de ce navigateur"));
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
        if (ctx.sampleRate !== 48000) ui.log("Scrambler : son à " + ctx.sampleRate + " Hz (prévu pour 48 kHz) : décodage moins propre en face.", "warn");
      } catch (err) {
        scr.tx = false;
        if (chain) chain.setScrambler(null);
        ui.log("Scrambler d'émission impossible (" + (err && err.message ? err.message : err) + ") : voix en CLAIR.", "bad");
      }
      scrRender();
    }
    // ---- chaîne de la réception (Web Audio) : débrouillage du scrambler puis spatialisation (spatial.js), seulement si
    // l'un des deux est en service ; sinon le flux reçu va tel quel à l'élément audio (comme avant).
    function rxStop() {
      if (!rxGraph) return;
      try { rxGraph.raw.pause(); rxGraph.raw.srcObject = null; } catch (e) { /* déjà arrêté */ }
      if (rxGraph.ctx.close) rxGraph.ctx.close().catch(() => {});
      rxGraph = null;
    }
    function rxStream(media) {
      /* Flux à jouer : le flux reçu tel quel, ou traité (AudioWorklet) si le débrouillage ou la spatialisation est en service. */
      rxStop();
      const wantScr = !!(sx && scr.rx), wantSt = stActive();
      if (!media || (!wantScr && !wantSt)) return media;
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        const ctx = audioContext48(Ctx);
        // Chrome : un flux WebRTC distant n'arrive à Web Audio que s'il est aussi lu par un élément (ici muet)
        const raw = new Audio(); raw.muted = true; raw.srcObject = media; raw.play().catch(() => {});
        const dest = ctx.createMediaStreamDestination();
        const state = { ctx, raw, dest, node: null, st: null };
        rxGraph = state;
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
          head.connect(dest);
          scrRender(); stRender();
        }).catch((err) => {
          if (rxGraph !== state) return;
          if (wantScr) scr.rx = false;
          if (wantSt) stFailed = true;
          rxStop(); audio.srcObject = media;
          ui.log("Traitement de la réception impossible (" + (err && err.message ? err.message : err) + ") : réception sans débrouillage ni spatialisation.", "warn");
          scrRender(); stRender();
        });
        if (ctx.resume) ctx.resume().catch(() => {});
        window.setTimeout(() => {                                                   // contexte gardé en pause par le navigateur
          if (rxGraph !== state || ctx.state !== "suspended") return;
          ui.log("Son de la réception en attente du navigateur : touchez l'écran.", "warn");
          document.addEventListener("pointerdown", () => { if (rxGraph === state && ctx.resume) ctx.resume().catch(() => {}); }, { once: true });
        }, 1000);
        return dest.stream;
      } catch (err) {
        if (wantScr) scr.rx = false;
        if (wantSt) stFailed = true;
        ui.log("Traitement de la réception impossible (" + (err && err.message ? err.message : err) + ") : réception sans débrouillage ni spatialisation.", "warn");
        return media;
      }
    }
    function rxApply() {
      if (rxMedia) {
        audio.srcObject = rxStream(rxMedia);
        audio.play().catch(() => {});
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
      ind.textContent = scr.tx ? "SCRAMBLER" : "DÉBROUILLAGE";
      const txState = !scr.tx ? "émission en clair" : (voiceChain && scrTxNode && voiceChain.scrambler === scrTxNode) ? "émission BROUILLÉE"
        : voiceChain ? "émission brouillée : mise en route…" : "émission brouillée dès la connexion avec le micro";
      const rxState = !scr.rx ? "réception en clair" : rxGraph && rxGraph.node ? "réception débrouillée" : "réception débrouillée dès la connexion";
      $("scr-state").textContent = "État : " + txState + " ; " + rxState + " (mode « " + sx.MODES[scr.mode].label + " »).";
    }
    if (sx) {
      for (const [key, m] of Object.entries(sx.MODES)) $("scr-mode").appendChild(Object.assign(el("option", "", m.label), { value: key }));
      const confirmOn = (what) => window.confirm(SCR_WARNING + "\n\n" + what);
      $("scr-tx").addEventListener("change", (ev) => {
        if (ev.target.checked && client.breizhEffectsOff()) {                      // Breizh et scrambler d'émission exclusifs
          ev.target.checked = false;
          ui.log("Breizh Audio Box en service : scrambler d'émission impossible (exclusifs). Choisissez « Direct » dans la rubrique Breizh pour brouiller.", "warn");
          return;
        }
        if (ev.target.checked && !confirmOn("Brouiller VOTRE ÉMISSION ?")) { ev.target.checked = false; return; }
        scr.tx = ev.target.checked;
        ui.log(scr.tx ? "Scrambler : émission brouillée (mode « " + sx.MODES[scr.mode].label + " »)." : "Scrambler : émission en clair.", scr.tx ? "warn" : "");
        scrApplyTx();
      });
      $("scr-rx").addEventListener("change", (ev) => {
        if (ev.target.checked && !confirmOn("Débrouiller la RÉCEPTION ?")) { ev.target.checked = false; return; }
        scr.rx = ev.target.checked;
        ui.log(scr.rx ? "Scrambler : réception débrouillée." : "Scrambler : réception en clair.", "");
        if (scr.rx && spx && stSet.on) {                                            // débrouillage et ST exclusifs (2026-11-03)
          stSet = spx.validate(Object.assign({}, stSet, { on: false })); stSave(); stRender();
          ui.log("Débrouillage en service : spatialisation ST coupée.", "");
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
      $("bzh-ind").className = "chip bzh-ind listener-hide" + (b.level !== "off" ? " " + b.level : "");
      $("bzh-ind").title = "Breizh Audio Box : " + b.text + ". Touche : sa rubrique";
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
        ui.log("Breizh Audio Box en service : scrambler d'émission coupé (exclusifs).", "warn");
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
        if (res && !res.ok) ui.log("Breizh : " + web.reasonText(res.reason, res.detail), "warn");
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
        if (!res || !res.ok) { ui.log("Breizh : " + web.reasonText(res && res.reason, res && res.detail), "warn"); return; }
        ui.log(res.pending ? "Breizh sera repris dès qu'il répondra (à la prochaine émission)." : "Breizh repris : la prochaine émission passera par Breizh.", "");
      }).catch(fail);
    });
    $("bzh-log-refresh").addEventListener("click", bzhLoadLog);
    $("bzh-ind").addEventListener("click", () => { $("sec-breizh").open = true; $("sec-breizh").scrollIntoView({ block: "start" }); });

    // ---- spatialisation stéréo de la réception (spatial.js, docs/spatialisation-cahier-des-charges.md) : traitement de cet
    // appareil seulement, visiteurs compris ; la station n'en sait rien. Réglages gardés par le navigateur.
    const spx = root.TrxSpatial || null;
    let stSet = spx ? spx.validate(safeJson(store.get("trx.spatial", "null"))) : null;
    let stAb = false, stFailed = false, stCorr = null, stOffTimer = null;
    function stActive() { return !!(spx && stSet.on && !stSet.monoOut && !stFailed); }
    function stParams() { return spx.params(stSet, stAb); }
    function stWorklet(ctx) {
      if (!ctx.audioWorklet || typeof AudioWorkletNode === "undefined") return Promise.reject(new Error("AudioWorklet absent de ce navigateur"));
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
        if (sx && scr.rx) {                                                         // débrouillage et ST exclusifs (2026-11-03)
          scr.rx = false; scrRender();
          ui.log("Spatialisation ST en service : débrouillage du scrambler coupé.", "");
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
      chip.className = "chip st-direct" + (stActive() ? " on" : "") + (stSet.monoOut ? " dim" : "");
      chip.textContent = stSet.on && !stSet.monoOut ? "ST ON" : "ST";
      $("st-on").checked = stSet.on; $("st-mono").checked = stSet.monoOut;
      for (const b of $("st-presets").children) b.className = "chip" + (b.value === stSet.preset ? " on" : "");
      $("st-width").value = stSet.width; $("st-width-text").textContent = " " + stSet.width + " %";
      $("st-presence").value = stSet.presence; $("st-presence-text").textContent = " " + stSet.presence + " %";
      $("st-balance").value = stSet.balance;
      $("st-balance-text").textContent = " " + (stSet.balance === 0 ? "centre" : (stSet.balance < 0 ? "G " : "D ") + Math.abs(stSet.balance));
      const state = stFailed ? "indisponible dans ce navigateur (son mono)" : !stSet.on ? "éteinte (son mono)"
        : stSet.monoOut ? "sortie mono déclarée : pas d'effet" : stSet.preset === "mono" ? "préréglage Mono (comparaison)"
        : !rxMedia ? "« " + spx.label(stSet) + " » dès la réception du son" : rxGraph && rxGraph.st ? "« " + spx.label(stSet) + " »" + (stAb ? " — A/B : MONO" : "")
        : "« " + spx.label(stSet) + " » : mise en route…";
      $("st-state").textContent = "État : " + state + ".";
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
          ui.log("Spatialisation : mettez un casque pour profiter de l'effet (sur un haut-parleur unique, il ne s'entend pas).", "");
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
      if (!clientId || !password) { ui.log("Renseigne l'identifiant et le mot de passe.", "warn"); return; }
      audio.muted = $("mute").checked;
      if (alertLevel !== "off") alertContext();          // le navigateur n'autorise le son qu'après un geste : on le prépare ici
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
        $("password").value = "";                                               // ne reste pas dans la page une fois connecté
      } catch (err) { fail(err); }
    });
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
      $("cluster-all").textContent = recentOpen ? "Masquer la liste" : "Tout afficher";
      if (!recentOpen) return;
      box.textContent = "";
      const list = sp && recentData ? sp.recentList(recentData, recentAt) : [];
      if (!list.length) {
        box.appendChild(el("div", "note", client.hello && client.hello.spectrum ? "Aucun spot reçu pour l'instant."
          : "Cette station n'envoie les spots qu'avec le spectre HF (second port CI-V)."));
        return;
      }
      const locked = frequencyLocked();
      for (const s of list) {
        const at = new Date(sp.arrivalMs(s));
        const row = el("button", "");
        row.disabled = locked;
        row.title = locked ? "QSY impossible : émission en cours ou station déconnectée" : "Mettre le poste sur ce spot";
        row.appendChild(el("span", "mono", at.toLocaleTimeString("fr-FR")));
        row.appendChild(el("span", "", s.dx));
        row.appendChild(el("span", "mono", s.khz.toFixed(1)));
        row.appendChild(el("span", "src", [sp.sourceLabel(s), sp.modeLabel(s), s.comment].filter(Boolean).join(" · ")));
        row.addEventListener("click", () => {
          const target = sp.qsyTarget(s, (mode) => client.adaptSpotMode(mode));
          if (!target || frequencyLocked()) return;
          client.qsy(target.hz, target.mode).then((res) => {
            if (res && res.ok) ui.log("QSY sur " + s.dx + " (" + s.khz.toFixed(1) + " kHz).", "");
            else ui.log("QSY refusé" + (res && res.reason ? " : " + web.reasonText(res.reason, res.detail) : "."), "warn");
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
      $("cluster-title").textContent = view.stale ? "État inconnu" : view.title;
      const list = $("cluster-sources");
      list.textContent = "";
      for (const line of view.lines) {
        const item = el("li", "");
        item.appendChild(el("span", "cluster-dot " + line.dot));
        item.appendChild(el("span", "", line.text));
        list.appendChild(item);
      }
      $("cluster-age").textContent = view.staleText || "État reçu de la station toutes les 15 s.";
    }
    window.setInterval(() => { if (clusterData) renderCluster(); }, 5000);

    // ---- signaler un problème : rapport assemblé, RELU par l'utilisateur, puis envoyé à la station ou partagé
    let bugText = "";
    const deviceInfo = () => ({
      userAgent: navigator.userAgent || "", layout: $("app").className,
      screen: window.innerWidth + "×" + window.innerHeight + " (densité " + (window.devicePixelRatio || 1) + ")",
      theme: (document.documentElement.getAttribute && document.documentElement.getAttribute("data-theme")) || "défaut",
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
        try { await navigator.share({ title: "Rapport de problème TRX distant", text: bugText }); return; }
        catch (e) { if (e && e.name === "AbortError") return; }                     // partage annulé par l'utilisateur
      }
      try { await navigator.clipboard.writeText(bugText); ui.log("Rapport copié : colle-le dans un e-mail ou un message.", ""); }
      catch (e) { ui.log("Copie impossible : sélectionne le texte du rapport et copie-le.", "warn"); }
    });
    window.addEventListener("error", (ev) => client.recordError((ev && ev.message) || "erreur inconnue"));
    window.addEventListener("unhandledrejection", (ev) => client.recordError("promesse rejetée : " + ((ev && ev.reason && ev.reason.message) || (ev && ev.reason) || "?")));

    $("local-release").addEventListener("click", () => {                             // confirmation en deux temps
      if (!releaseArmed) {
        releaseArmed = true;
        $("local-release").textContent = "Confirmer : reprendre la main";
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
      if (hz === null) { ui.log("Fréquence invalide (en kHz, ex. 14200 ou 7074,5).", "warn"); return; }
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
    const DIALOG_TITLES = { NR: "Réducteur de bruit (NR)", NB: "Antiparasite (NB)", NOTCH: "Notch" };
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
      $("ctl-dialog-title").textContent = DIALOG_TITLES[dialogKey];
      $("ctl-dialog-onrow").hidden = notch; $("ctl-notch-row").hidden = !notch;
      if (notch) {
        const current = fn.MN ? "manual" : fn.ANF ? "auto" : "off";
        for (const [kind, id, needs] of [["off", "ctl-notch-off", null], ["auto", "ctl-notch-auto", "ANF"], ["manual", "ctl-notch-manual", "MN"]]) {
          $(id).className = "chip" + (current === kind ? " on" : "");
          $(id).disabled = locked || (needs !== null && !(needs in fn));
        }
      } else {
        $("ctl-dialog-toggle").textContent = fn[dialogKey] ? "En marche" : "Arrêté";
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
      $("ctl-dialog-note").textContent = locked ? "Réglages verrouillés pendant l'émission." :
        (notch ? "" : has ? "" : "Le poste ne déclare pas de niveau réglable pour cette fonction.");
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
      if (!name) { ui.log("Donne un nom à la mémoire.", "warn"); return; }
      if (hz === null) { ui.log("Fréquence invalide (en kHz, ex. 7100 ou 7074,5).", "warn"); return; }
      if (!mode) { ui.log("Choisis un mode.", "warn"); return; }
      try {
        const res = await client.saveMemory({ memoryId: editingId, name: name, hz: hz, mode: mode, favorite: $("mem-fav").checked });
        if (res.ok) closeForm();
      } catch (err) { fail(err); }
    });
    $("mem-delete").addEventListener("click", async () => {
      if (!editingId) return;
      if (!deleteArmed) {                                                        // confirmation en deux temps
        deleteArmed = true;
        $("mem-delete").textContent = "Confirmer la suppression";
        deleteTimer = window.setTimeout(resetDelete, 4000);
        return;
      }
      const id = editingId;
      resetDelete();
      try { const res = await client.deleteMemory(id); if (res.ok) closeForm(); } catch (err) { fail(err); }
    });

    $("mute").addEventListener("change", (ev) => { audio.muted = ev.target.checked; });
    $("out-select").addEventListener("change", () => { store.set("trx.out", $("out-select").value); applyOutput(); });
    $("mic-select").addEventListener("change", () => { store.set("trx.mic", $("mic-select").value); ui.log("Le micro choisi s'appliquera à la prochaine connexion.", ""); });
    $("volume").addEventListener("input", (ev) => { audio.volume = parseFloat(ev.target.value); });
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
        if (res && res.ok) { profile = res.profile || null; profileSource = "factory"; profileVersion += 1; renderLayout(true); ui.log("Interface d'usine rétablie.", "ok"); }
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

  document.addEventListener("DOMContentLoaded", initUi);
})(typeof window !== "undefined" ? window : globalThis);
