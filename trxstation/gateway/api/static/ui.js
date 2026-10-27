/* Affichage : relie TrxClient (client.js, logique testée sous Node) à la page. Aucune logique de protocole ici. */
(function (root) {
  "use strict";
  const web = root.TrxWeb;
  if (typeof document === "undefined" || !web) return;
  const { TrxClient, modeLabel, shortMode, matchesRigDevice, parseKilohertz, chooseLayout, formatIcomFrequency, frequencyDigits, parseFrequencyEntry,
          BANDS, STEPS_HZ, describeLoss, lossSummary, LINK_ALERTS, alertVolume, alertDurationMs } = web;
  const wf = root.TrxWaterfall;
  if (!wf) return;
  const hfx = root.TrxHfScope || null;              // spectre HF du poste (hfscope.js) ; sans lui, la zone ne propose que puissance et audio
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
  const CONTROLS = [["NR", "ctl-nr"], ["NB", "ctl-nb"], ["PREAMP", "ctl-preamp"], ["AIP", "ctl-aip"], ["AGC", "ctl-agc"],
                    ["COMP", "ctl-comp"], ["FIL", "ctl-fil"], ["TUNER", "ctl-tuner"], ["PWR", "ctl-pwr"]];
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
    let hfSettings = hfx ? hfx.normalizeSettings(safeJson(store.get("trx.hf", "null"))) : { gain: 0, range: 40 };
    const hfSpec = $("hf-spec"), hfFall = $("hf-fall"), hfGrid = $("hf-grid");
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
      $("bands").appendChild(button);
      bandButtons.set(band.key, button);
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
      const current = hfVisible ? "hf" : wfVisible ? "audio" : "tx";
      const hfOk = !!hfx && hfx.available(client.hello, client.state);
      showZone(hfx ? hfx.nextView(current, hfOk) : (current === "tx" ? "audio" : "tx"));
    }
    function showZone(next) {
      /* Zone des graphiques : « tx » (puissance), « audio » (waterfall de l'audio reçu) ou « hf » (spectre du poste, plein écran). */
      const audio = next === "audio";
      if (audio !== wfVisible) {
        wfVisible = audio;
        $("waterfall").hidden = !audio;
        if (audio) { drawGrid(); resetFall(); wfTexts(); startWf(); } else stopWf();
      }
      $("txzone").hidden = audio;
      setHf(next === "hf");
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
      if (resized || !hfx.sameScale(hfLast, frame)) { hfDrawGrid(frame); hfResetFall(); }   // autre taille, largeur ou bande : historique effacé
      hfLast = frame;
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
    function setHf(on) {
      on = on && !!hfx;
      if (on === hfVisible) return;
      hfVisible = on;
      $("hfscope").hidden = !on;
      setVfo(false);
      if (on) {
        hfLast = null; $("hf-wait").hidden = false; $("hf-marker").hidden = true; $("hf-axis").textContent = ""; $("hf-info").textContent = "";
        hfTexts(); enterFullscreen();
        if (lastView) hfState(lastView, lastView.pttState !== "RX");
        if (client.spectrumFrame) hfDraw(client.spectrumFrame);
      } else {
        leaveFullscreen();
      }
    }
    function hfState(v, transmitting) {
      if (!hfVisible) return;
      if (!hfx.available(client.hello, client.state)) { showZone("tx"); return; }   // spectre perdu (mode normal) : retour aux graphiques
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
    $("hf-plot").addEventListener("click", () => { if (!hfVfo) toggleWaterfall(); });   // VFO allumé : un appui ne ferme pas la vue
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
        for (const id of ["mode-select", "mem-mode"]) {
          const select = $(id);
          select.textContent = "";
          for (const m of list) select.appendChild(Object.assign(el("option", "", modeLabel(m)), { value: m }));
        }
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
      armed(value) { $("armed").checked = value; },
      connected(value) {
        connectedFlag = value;
        for (const id of ["armed", "ptt", "stop", "freq-set", "mode-set", "mode-select", "disconnect", "mem-add-current", "step-down", "step-up",
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
          teardownAnalysis(); closeKeypad(); $("wf-tx").hidden = true;
          if (hfVisible) showZone("tx");
        }
      },
      state(v) {
        lastView = v;
        renderFrequency(v.frequencyHz);
        $("freq").className = "freq" + (v.frequencyPending ? " pending" : "") + (v.controlsLocked ? " locked" : "");
        for (const [key, button] of bandButtons) {
          button.className = "chip" + (v.band === key ? " on" : "");
          button.disabled = !v.connected || v.controlsLocked;
        }
        const transmitting = v.pttState !== "RX";
        $("wf-tx").hidden = !(wfVisible && transmitting);
        hfState(v, transmitting);
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
    $("freq-set").addEventListener("click", () => {
      const hz = parseKilohertz($("freq-input").value);
      if (hz === null) { ui.log("Fréquence invalide (en kHz, ex. 14200 ou 7074,5).", "warn"); return; }
      client.setFrequency(hz).catch(fail);
    });
    $("mode-set").addEventListener("click", () => {
      const mode = $("mode-select").value;
      if (mode) client.setMode(mode, 0).catch(fail);
    });
    for (const [key, id] of CONTROLS) $(id).addEventListener("click", () => client.pressControl(key).catch(fail));
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
