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
        let jitter = null, lost = null, received = null, rtt = null, rxLevel = null, micLevel = null, sent = null;
        stats.forEach((r) => {
          if (r.type === "inbound-rtp" && r.kind === "audio") {
            jitter = r.jitter; lost = r.packetsLost; received = r.packetsReceived;
            if (typeof r.audioLevel === "number") rxLevel = r.audioLevel;
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
        return { net: net.join(" · "), diag: diag.join(" · ") };
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
      for (let x = 0; x < FW; x++) {
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
      client.watchSpectrum(on);                                                  // balayages reçus seulement vue ouverte
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
    $("hf-plot").addEventListener("pointerdown", (ev) => {
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
        hfDrag.applied = steps;
      }
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

    const ui = {
      status(text, kind) { const b = $("status"); b.textContent = text; b.className = "badge" + (kind ? " " + kind : ""); },
      log(text, level) {
        const li = el("li", level || "", new Date().toLocaleTimeString() + "  " + text);
        logList.insertBefore(li, logList.firstChild);
        while (logList.children.length > 50) logList.removeChild(logList.lastChild);
      },
      spectrum(frame) {
        if (hfVisible) hfDraw(frame);
      },
      remoteStream(stream, track) {
        const media = stream || new MediaStream([track]);
        audio.srcObject = media;
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
      clusterHealth(state) { onClusterHealth(state); },
      clusterStatus(data) { clusterData = data; clusterAt = performance.now(); renderCluster(); },
      armed(value) { $("armed").checked = value; },
      connected(value) {
        connectedFlag = value;
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
          $("local-banner").hidden = true; resetRelease(); closeControlDialog();
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
        const local = v.local || { active: false };                                   // poste utilisé sur place
        $("local-banner").hidden = !local.active;
        if (local.active) {
          $("local-text").textContent = local.text;
          $("local-release").disabled = !v.connected || local.transmitting;          // jamais pendant l'émission au micro du poste
        } else if (releaseArmed) resetRelease();
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
        renderInstruments(v.instruments);
        markActive(v);
        $("rx-level").textContent = v.rxLevel; $("tx-level").textContent = v.txLevel;
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
      },
    };

    const client = new TrxClient(browserEnv(), ui);
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
                               audioProcessing: $("audio-processing").checked, micDeviceId: $("mic-select").value || null,
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
